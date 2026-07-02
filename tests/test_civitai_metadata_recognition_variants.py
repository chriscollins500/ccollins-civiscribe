from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - depends on local test interpreter
    Image = None

from save_node.io.png_writer import build_pnginfo
from save_node.metadata.exif_user_comment import build_exif_bytes
from save_node.metadata.schema import GenerationSettings, PromptMetadata
from tools.inspect_png_chunks import describe_text_chunk, inspect_png, iter_png_chunks
from tools.make_civitai_metadata_recognition_variants import make_variants


PARAMETERS = (
    "Portrait test prompt\n"
    "Negative prompt: blur\n"
    "Steps: 12, Sampler: Euler, Seed: 123, Size: 16x8, "
    "Model: base.safetensors, Model hash: 1111111111, "
    "VAE: ae.safetensors, VAE hash: 2222222222, "
    'Hashes: {"model":"1111111111","Model":"1111111111","vae":"2222222222","VAE:ae.safetensors":"2222222222","LORA:detail.safetensors":"3333333333"}, '
    'Civitai resources: [{"type":"checkpoint","modelId":10,"modelVersionId":20,"air":"urn:air:sdxl:checkpoint:civitai:10@20"},{"type":"vae","modelId":30,"modelVersionId":40,"air":"urn:air:other:vae:civitai:30@40"}]'
)


class CivitaiMetadataRecognitionVariantsTests(unittest.TestCase):
    def setUp(self) -> None:
        if Image is None:
            self.skipTest("Pillow is required for PNG variant verification")

    def test_variants_have_expected_chunks_and_identical_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_source_png(Path(tmp) / "source.png")
            records = make_variants(source)
            output = source.parent / "source_civitai_recognition_variants"
            source_pixels = _pixels(source)

            self.assertEqual(
                [record.variant for record in records],
                [
                    "A_full_baseline",
                    "B_a1111_hashes_only",
                    "C_workflow_and_manifest_only",
                    "D_workflow_only",
                    "E_civitai_manifest_only",
                    "F_no_resource_metadata",
                    "G_a1111_model_hash_only",
                    "H_explicit_civitai_resources_only",
                    "U_exif_usercomment_full_only",
                    "V_parameters_plus_exif",
                    "W_exif_resources_only",
                    "X_exif_civitai_metadata_only",
                    "Y_exif_minimal_no_resources",
                ],
            )

            for record in records:
                path = output / record.filename
                self.assertTrue(path.exists(), record.variant)
                self.assertEqual(_pixels(path), source_pixels, record.variant)
                self.assertIn("metadata summary:", inspect_png(path))
                self.assertTrue(all(chunk.crc_ok for chunk in iter_png_chunks(path)))

            self.assertEqual((output / "source__A_full_baseline.png").read_bytes(), source.read_bytes())

            self.assert_chunks(
                output / "source__B_a1111_hashes_only.png",
                parameters=True,
                workflow=False,
                civitai=False,
                exif=False,
            )
            text_b = _text(output / "source__B_a1111_hashes_only.png")
            self.assertIn("Model hash: 1111111111", text_b["parameters"])
            self.assertIn("VAE hash: 2222222222", text_b["parameters"])
            self.assertIn("Hashes:", text_b["parameters"])
            self.assertNotIn("Civitai resources:", text_b["parameters"])

            self.assert_chunks(
                output / "source__C_workflow_and_manifest_only.png",
                parameters=True,
                workflow=True,
                civitai=True,
                exif=False,
            )
            text_c = _text(output / "source__C_workflow_and_manifest_only.png")
            self.assert_resource_fields_removed(text_c["parameters"])

            self.assert_chunks(
                output / "source__D_workflow_only.png", parameters=True, workflow=True, civitai=False, exif=False
            )
            self.assert_chunks(
                output / "source__E_civitai_manifest_only.png",
                parameters=True,
                workflow=False,
                civitai=True,
                exif=False,
            )
            self.assert_chunks(
                output / "source__F_no_resource_metadata.png",
                parameters=False,
                workflow=False,
                civitai=False,
                exif=False,
            )

            self.assert_chunks(
                output / "source__G_a1111_model_hash_only.png",
                parameters=True,
                workflow=False,
                civitai=False,
                exif=False,
            )
            text_g = _text(output / "source__G_a1111_model_hash_only.png")["parameters"]
            self.assertIn("Model hash: 1111111111", text_g)
            self.assertIn('"model":"1111111111"', text_g)
            self.assertNotIn("VAE hash:", text_g)
            self.assertNotIn('"vae"', text_g)
            self.assertNotIn("VAE:ae.safetensors", text_g)

            self.assert_chunks(
                output / "source__H_explicit_civitai_resources_only.png",
                parameters=True,
                workflow=False,
                civitai=False,
                exif=False,
            )
            text_h = _text(output / "source__H_explicit_civitai_resources_only.png")["parameters"]
            self.assertIn("Civitai resources:", text_h)
            self.assertNotIn("Hashes:", text_h)
            self.assertNotIn("Model hash:", text_h)
            self.assertNotIn("VAE hash:", text_h)

            self.assert_chunks(
                output / "source__U_exif_usercomment_full_only.png",
                parameters=False,
                workflow=False,
                civitai=False,
                exif=True,
                software=False,
            )
            self.assert_chunks(
                output / "source__V_parameters_plus_exif.png",
                parameters=True,
                workflow=False,
                civitai=False,
                exif=True,
                software=False,
            )
            self.assert_chunks(
                output / "source__W_exif_resources_only.png",
                parameters=False,
                workflow=False,
                civitai=False,
                exif=True,
                software=False,
            )
            self.assert_chunks(
                output / "source__X_exif_civitai_metadata_only.png",
                parameters=False,
                workflow=False,
                civitai=False,
                exif=True,
                software=False,
            )
            self.assert_chunks(
                output / "source__Y_exif_minimal_no_resources.png",
                parameters=False,
                workflow=False,
                civitai=False,
                exif=True,
                software=False,
            )

    def test_manifest_files_are_written_without_private_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_source_png(Path(tmp) / "source.png")
            make_variants(source)
            output = source.parent / "source_civitai_recognition_variants"
            manifest_path = output / "recognition_variants_manifest.json"
            csv_path = output / "recognition_variants_manifest.csv"

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            csv_text = csv_path.read_text(encoding="utf-8")
            combined = manifest_path.read_text(encoding="utf-8") + csv_text

            self.assertEqual(manifest["format"], "comfyui-civitai-save-node.civitai-recognition-variants")
            self.assertEqual(len(manifest["variants"]), 13)
            self.assertIn("manualUploadResult", manifest["variants"][0])
            self.assertIn("vaeDisplayed", manifest["variants"][0]["manualUploadResult"])
            self.assertIn("apiMetaResources", csv_text)
            self.assertNotIn(str(tmp), combined)
            self.assertNotIn("C:\\", combined)
            self.assertNotIn("/Users/", combined)
            self.assertNotIn("token=", combined.lower())

    def assert_chunks(
        self,
        path: Path,
        *,
        parameters: bool,
        workflow: bool,
        civitai: bool,
        exif: bool,
        software: bool = True,
    ) -> None:
        chunks = _text_chunks(path)
        self.assertEqual((b"tEXt", "Software") in chunks, software)
        self.assertEqual((b"tEXt", "parameters") in chunks, parameters)
        self.assertFalse((b"iTXt", "parameters") in chunks)
        self.assertEqual((b"iTXt", "workflow") in chunks, workflow)
        self.assertEqual((b"iTXt", "civitai") in chunks, civitai)
        self.assertFalse((b"iTXt", "prompt") in chunks)
        self.assertEqual(_has_exif(path), exif)

    def assert_resource_fields_removed(self, parameters: str) -> None:
        self.assertIn("Steps: 12", parameters)
        self.assertNotIn("Model:", parameters)
        self.assertNotIn("Model hash:", parameters)
        self.assertNotIn("VAE:", parameters)
        self.assertNotIn("VAE hash:", parameters)
        self.assertNotIn("Hashes:", parameters)
        self.assertNotIn("Civitai resources:", parameters)


def _write_source_png(path: Path) -> Path:
    image = Image.new("RGB", (16, 8))
    for x in range(16):
        for y in range(8):
            image.putpixel((x, y), (x * 10 % 255, y * 20 % 255, (x + y) * 7 % 255))
    pnginfo = build_pnginfo(
        parameters=PARAMETERS,
        prompt={"1": {"class_type": "KSampler", "inputs": {"seed": 123}}},
        extra_pnginfo={"workflow": {"nodes": [{"id": 1, "type": "KSampler"}]}},
        include_workflow=True,
        civitai_manifest={"schemaName": "test", "resources": [{"modelVersionId": 20}]},
    )
    exif = build_exif_bytes(
        prompt=PromptMetadata(positive="Portrait test prompt", negative="blur"),
        generation=GenerationSettings(steps=12, sampler="Euler", seed=123, width=16, height=8),
        resources=(),
    )
    image.save(path, format="PNG", pnginfo=pnginfo, exif=exif)
    return path


def _pixels(path: Path) -> bytes:
    with Image.open(path) as image:
        image.load()
        return image.convert("RGBA").tobytes()


def _text(path: Path) -> dict[str, str]:
    with Image.open(path) as image:
        image.load()
        return dict(image.text)


def _text_chunks(path: Path) -> set[tuple[bytes, str]]:
    chunks: set[tuple[bytes, str]] = set()
    for chunk in iter_png_chunks(path):
        keyword, _description = describe_text_chunk(chunk)
        if keyword is not None:
            chunks.add((chunk.kind, keyword))
    return chunks


def _has_exif(path: Path) -> bool:
    return any(chunk.kind == b"eXIf" for chunk in iter_png_chunks(path))


if __name__ == "__main__":
    unittest.main()
