from __future__ import annotations

from io import BytesIO
import json
import struct
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - depends on local test interpreter
    Image = None

from save_node.civitai.identity_cache import parse_identity_cache
from save_node.civitai.identity_resolution import apply_identity_cache
from save_node.civitai.manifest import build_civitai_manifest
from save_node.comfy.workflow_scan import scan_workflow_graph
from save_node.hashing.resolver import ModelRootResolver
from save_node.hashing.resource_identity import attach_local_hashes
from save_node.io.png_writer import build_pnginfo
from save_node.metadata.a1111 import build_a1111_parameters
from save_node.metadata.serialize import to_json_text
from save_node.metadata.validate import validate_metadata


FLUX2_AIR = "urn:air:flux2:checkpoint:civitai:2432159@2734704"


class Flux2GGUFWorkflowTests(unittest.TestCase):
    def test_unresolved_flux2_workflow_has_sampler_settings_without_fake_civitai_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            resolver = _write_flux2_models(tmp_path)

            scan = scan_workflow_graph(_flux2_prompt(), {"workflow": {"nodes": []}})
            hashed = attach_local_hashes(
                resources=scan.resources,
                generation=scan.generation,
                resolver=resolver,
            )
            validation = _validation(scan, hashed)
            manifest = _manifest(scan, hashed, validation)
            parameters = build_a1111_parameters(
                prompt=scan.prompt,
                generation=hashed.generation,
                resources=hashed.resources,
                hashes=hashed.hashes,
            )
            manifest_json = json.loads(to_json_text(manifest))
            combined = f"{parameters}\n{to_json_text(manifest)}"

            self.assertEqual(scan.generation.steps, 28)
            self.assertEqual(scan.generation.sampler, "euler")
            self.assertEqual(scan.generation.scheduler, "simple")
            self.assertEqual(scan.generation.seed, 123456789)
            self.assertEqual(scan.generation.extra["fluxGuidance"], 4.0)
            self.assertIsNone(scan.generation.cfg_scale)
            self.assertIn("Steps: 28", parameters)
            self.assertIn("Sampler: euler", parameters)
            self.assertIn("Schedule type: simple", parameters)
            self.assertIn("Seed: 123456789", parameters)
            self.assertIn("Guidance: 4", parameters)
            self.assertNotIn("CFG scale:", parameters)
            self.assertIn("Size: 1344x768", parameters)
            self.assertIn("\nNegative prompt:\n", parameters)
            self.assertIn("Model: flux2-dev-Q8_0.gguf", parameters)
            self.assertIn("VAE: flux2-vae.safetensors", parameters)
            self.assertIn("Hashes:", parameters)
            self.assertNotIn("Civitai resources:", parameters)
            self.assertEqual(manifest_json["generation"]["extra"]["fluxGuidance"], 4.0)
            self.assertNotIn("cfgScale", manifest_json["generation"])
            self.assertEqual(
                [resource.resource.name for resource in hashed.resources],
                [
                    "flux2-dev-Q8_0.gguf",
                    "Mistral-Small-3.2-24B-Instruct-2506-UD-Q8_K_XL.gguf",
                    "flux2-vae.safetensors",
                ],
            )
            self.assertNotIn(str(tmp_path), combined)

    def test_local_cache_resolved_flux2_model_writes_full_air_civitai_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            resolver = _write_flux2_models(tmp_path)

            scan = scan_workflow_graph(_flux2_prompt(), {"workflow": {"nodes": []}})
            hashed = attach_local_hashes(
                resources=scan.resources,
                generation=scan.generation,
                resolver=resolver,
            )
            primary = _resource_by_name(hashed.resources, "flux2-dev-Q8_0.gguf")
            parsed_cache = parse_identity_cache(
                {"records": [_flux2_identity_record(primary.resource.hashes.sha256, primary.resource.hashes.auto_v2)]}
            )
            identity = apply_identity_cache(resources=hashed.resources, identity_cache=parsed_cache.cache)
            parameters = build_a1111_parameters(
                prompt=scan.prompt,
                generation=hashed.generation,
                resources=identity.resources,
                hashes=hashed.hashes,
            )
            validation = _validation(
                scan, hashed, resources=identity.resources, unresolved=identity.unresolved_resources
            )
            manifest = _manifest(
                scan, hashed, validation, resources=identity.resources, unresolved=identity.unresolved_resources
            )
            manifest_json = json.loads(to_json_text(manifest))
            combined = f"{parameters}\n{to_json_text(manifest)}"

            self.assertIn("Civitai resources:", parameters)
            self.assertIn('"type":"checkpoint"', parameters)
            self.assertIn(f'"air":"{FLUX2_AIR}"', parameters)
            self.assertIn(f'"urn":"{FLUX2_AIR}"', parameters)
            self.assertIn('"modelId":2432159', parameters)
            self.assertIn('"modelVersionId":2734704', parameters)
            self.assertNotIn('"type":"diffusion_model"', parameters)
            self.assertEqual(manifest_json["resources"][0]["rawAir"], FLUX2_AIR)
            self.assertEqual(manifest_json["resources"][0]["civitaiModelVersionId"], 2734704)
            self.assertNotIn(str(tmp_path), combined)

    def test_flux2_png_fixture_keeps_parameters_as_text_chunk(self) -> None:
        if Image is None:
            self.skipTest("Pillow is required for PNG chunk verification")

        scan = scan_workflow_graph(_flux2_prompt(), {"workflow": {"nodes": []}})
        parameters = build_a1111_parameters(
            prompt=scan.prompt,
            generation=scan.generation,
            resources=scan.resources,
        )
        data = _write_png(parameters)
        chunks = _png_chunks(data)

        self.assertTrue(_has_chunk(chunks, b"tEXt", b"parameters\x00"))
        self.assertFalse(_has_chunk(chunks, b"iTXt", b"parameters\x00"))


def _flux2_prompt() -> dict[str, dict]:
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux2-dev-Q8_0.gguf"}},
        "2": {
            "class_type": "CLIPLoaderGGUF",
            "inputs": {"clip_name": "Mistral-Small-3.2-24B-Instruct-2506-UD-Q8_K_XL.gguf"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": "cinematic portrait, precise light, detailed suit"},
        },
        "5": {
            "class_type": "BasicGuider",
            "inputs": {"model": ["1", 0], "conditioning": ["4", 0], "guidance": 4.0},
        },
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": 123456789}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {
            "class_type": "BasicScheduler",
            "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": 28, "denoise": 1.0},
        },
        "9": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 1344, "height": 768, "batch_size": 1},
        },
        "10": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["6", 0],
                "guider": ["5", 0],
                "sampler": ["7", 0],
                "sigmas": ["8", 0],
                "latent_image": ["9", 0],
            },
        },
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImageWithCivitaiMetadata", "inputs": {"images": ["11", 0]}},
    }


def _write_flux2_models(root: Path) -> ModelRootResolver:
    _write(root / "diffusion_models" / "flux2-dev-Q8_0.gguf", b"flux2 gguf")
    _write(root / "text_encoders" / "Mistral-Small-3.2-24B-Instruct-2506-UD-Q8_K_XL.gguf", b"clip")
    _write(root / "vae" / "flux2-vae.safetensors", b"vae")
    return ModelRootResolver(
        {
            "diffusion_models": [root / "diffusion_models"],
            "text_encoders": [root / "text_encoders"],
            "vae": [root / "vae"],
        }
    )


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _resource_by_name(resources, name: str):
    for resource in resources:
        if resource.resource.name == name:
            return resource
    raise AssertionError(f"missing resource {name}")


def _flux2_identity_record(sha256: str | None, auto_v2: str | None) -> dict[str, object]:
    hashes: dict[str, str] = {}
    if sha256:
        hashes["SHA256"] = sha256
    if auto_v2:
        hashes["AutoV2"] = auto_v2
    return {
        "air": FLUX2_AIR,
        "civitaiModelId": 2432159,
        "civitaiModelVersionId": 2734704,
        "modelName": "Flux.2 Dev",
        "modelVersionName": "flux2-dev-Q8_0.gguf",
        "resourceType": "checkpoint",
        "baseModel": "Flux.2",
        "hashes": hashes,
    }


def _validation(scan, hashed, *, resources=None, unresolved=None):
    return validate_metadata(
        filename_prefix="ok",
        prompt_metadata=scan.prompt,
        generation=hashed.generation,
        resources=resources or hashed.resources,
        unresolved_resources=unresolved or hashed.unresolved_resources,
        prompt=_flux2_prompt(),
        extra_pnginfo={"workflow": {"nodes": []}},
        include_workflow=True,
        include_civitai_manifest=True,
        additional_warnings=(*scan.warnings, *hashed.warnings),
    )


def _manifest(scan, hashed, validation, *, resources=None, unresolved=None):
    return build_civitai_manifest(
        prompt=scan.prompt,
        generation=hashed.generation,
        resources=resources or hashed.resources,
        unresolved_resources=unresolved or hashed.unresolved_resources,
        hashes=hashed.hashes,
        validation=validation,
        include_workflow=True,
        generator=scan.generator,
    )


def _write_png(parameters: str) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (1344, 768), color=(1, 2, 3))
    pnginfo = build_pnginfo(
        parameters=parameters,
        prompt=_flux2_prompt(),
        extra_pnginfo={"workflow": {"nodes": []}},
        include_workflow=True,
        civitai_manifest={"schemaName": "test"},
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
