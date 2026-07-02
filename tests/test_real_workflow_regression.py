from __future__ import annotations

from io import BytesIO
import struct
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - depends on local test interpreter
    Image = None

from save_node.civitai.manifest import build_civitai_manifest
from save_node.comfy.workflow_scan import scan_workflow_graph
from save_node.hashing.resolver import ModelRootResolver
from save_node.hashing.resource_identity import attach_local_hashes
from save_node.io.png_writer import build_pnginfo
from save_node.metadata.a1111 import build_a1111_parameters
from save_node.metadata.serialize import to_json_text
from save_node.metadata.validate import validate_metadata
from save_node.nodes import _apply_final_image_dimensions


class RealWorkflowRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        if Image is None:
            self.skipTest("Pillow is required for PNG chunk verification")

    def test_civitai_upload_compatibility_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write(tmp_path / "diffusion_models" / "z_image_turbo_bf16.safetensors", b"unused")
            _write(tmp_path / "diffusion_models" / "swiftFastAndDetailed_neo.gguf", b"primary gguf")
            _write(tmp_path / "loras" / "ProjectRealismPhotoLora_v1.safetensors", b"lora")
            _write(tmp_path / "vae" / "ae.safetensors", b"vae")
            _write(tmp_path / "text_encoders" / "Qwen3-4B-BF16.gguf", b"clip")
            _write(tmp_path / "upscale_models" / "4x-UltraSharp.pth", b"upscale")

            prompt = _real_shape_prompt()
            scan = scan_workflow_graph(prompt, {"workflow": {"nodes": []}})
            hashed = attach_local_hashes(
                resources=scan.resources,
                generation=scan.generation,
                resolver=ModelRootResolver(
                    {
                        "diffusion_models": [tmp_path / "diffusion_models"],
                        "loras": [tmp_path / "loras"],
                        "vae": [tmp_path / "vae"],
                        "text_encoders": [tmp_path / "text_encoders"],
                        "upscale_models": [tmp_path / "upscale_models"],
                    }
                ),
            )
            generation = _apply_final_image_dimensions(hashed.generation, 832, 1216)
            validation = validate_metadata(
                filename_prefix="ok",
                prompt_metadata=scan.prompt,
                generation=generation,
                resources=hashed.resources,
                unresolved_resources=hashed.unresolved_resources,
                prompt=prompt,
                extra_pnginfo={"workflow": {"nodes": []}},
                include_workflow=True,
                include_civitai_manifest=True,
                additional_warnings=(*scan.warnings, *hashed.warnings),
            )
            manifest = build_civitai_manifest(
                prompt=scan.prompt,
                generation=generation,
                resources=hashed.resources,
                unresolved_resources=hashed.unresolved_resources,
                hashes=hashed.hashes,
                validation=validation,
                include_workflow=True,
                generator=scan.generator,
            )
            parameters = build_a1111_parameters(
                prompt=scan.prompt,
                generation=generation,
                resources=hashed.resources,
                hashes=hashed.hashes,
            )
            png_bytes = _write_png(parameters, prompt, manifest.to_json())
            chunks = _png_chunks(png_bytes)
            primary_hash = _primary_hash(hashed)
            manifest_text = to_json_text(manifest)
            combined = f"{parameters}\n{manifest_text}"
            active_names = [resource.resource.name for resource in hashed.resources]

            self.assertTrue(_has_chunk(chunks, b"tEXt", b"parameters\x00"))
            self.assertIn("Size: 832x1216", parameters)
            self.assertIn("\nNegative prompt:\n", parameters)
            self.assertIn("Model: swiftFastAndDetailed_neo.gguf", parameters)
            self.assertIn(f"Model hash: {primary_hash}", parameters)
            self.assertIn(f'"model":"{primary_hash}"', parameters)
            self.assertEqual(
                active_names,
                [
                    "swiftFastAndDetailed_neo.gguf",
                    "ProjectRealismPhotoLora_v1.safetensors",
                    "Qwen3-4B-BF16.gguf",
                    "ae.safetensors",
                ],
            )
            self.assertIn("swiftFastAndDetailed_neo.gguf", manifest_text)
            self.assertIn("ProjectRealismPhotoLora_v1.safetensors", manifest_text)
            self.assertIn("Qwen3-4B-BF16.gguf", manifest_text)
            self.assertIn("ae.safetensors", manifest_text)
            self.assertNotIn("z_image_turbo_bf16.safetensors", combined)
            self.assertNotIn("4x-UltraSharp.pth", combined)
            self.assertIn('"unresolvedResources"', manifest_text)
            self.assertNotIn("Civitai resources:", parameters)
            self.assertNotIn(str(tmp_path), combined)


def _real_shape_prompt() -> dict[str, dict]:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors"}},
        "2": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "swiftFastAndDetailed_neo.gguf"}},
        "3": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["2", 0],
                "lora_name": "ProjectRealismPhotoLora_v1.safetensors",
                "strength_model": 0.75,
            },
        },
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["3", 0], "shift": 3.0}},
        "5": {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": "Qwen3-4B-BF16.gguf"}},
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["5", 0], "text": "portrait, studio light"},
        },
        "7": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
        "8": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": ["14", 1], "height": ["14", 2], "batch_size": 1},
        },
        "9": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "10": {
            "class_type": "ClownsharKSampler_Beta",
            "inputs": {
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["8", 0],
                "seed": 44,
                "steps": 18,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
            },
        },
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["9", 0]}},
        "12": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "13": {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["12", 0], "image": ["11", 0]},
        },
        "14": {"class_type": "SmartResolutionCalc", "inputs": {}},
        "15": {"class_type": "SaveImageWithCivitaiMetadata", "inputs": {"images": ["11", 0]}},
    }


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _primary_hash(result) -> str:
    for resource in result.resources:
        if resource.resource.metadata.get("primaryModel"):
            return resource.resource.hashes.auto_v2 or ""
    raise AssertionError("missing primary resource")


def _write_png(parameters: str, prompt: dict[str, dict], manifest: dict) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (832, 1216), color=(4, 5, 6))
    pnginfo = build_pnginfo(
        parameters=parameters,
        prompt=prompt,
        extra_pnginfo={"workflow": {"nodes": []}},
        include_workflow=True,
        civitai_manifest=manifest,
    )
    image.save(output, format="PNG", pnginfo=pnginfo)
    return output.getvalue()


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        chunks.append((chunk_type, chunk_data))
        offset += length + 12
    return chunks


def _has_chunk(chunks: list[tuple[bytes, bytes]], chunk_type: bytes, prefix: bytes) -> bool:
    return any(kind == chunk_type and chunk_data.startswith(prefix) for kind, chunk_data in chunks)


if __name__ == "__main__":
    unittest.main()
