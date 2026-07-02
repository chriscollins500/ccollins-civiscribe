from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - depends on local test interpreter
    Image = None

from save_node import nodes
from save_node.comfy.workflow_scan import WorkflowScanResult
from save_node.io.png_writer import SOFTWARE_TEXT, build_pnginfo, parameters_text_needs_latin1_fallback
from save_node.metadata.exif_user_comment import (
    EXIF_IFD_TAG,
    USER_COMMENT_TAG,
    build_exif_bytes,
    decode_user_comment,
)
from save_node.metadata.schema import GenerationSettings, GeneratorMetadata, PromptMetadata
from tools.inspect_png_chunks import inspect_png, iter_png_chunks


class PngWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        if Image is None:
            self.skipTest("Pillow is required for PNG chunk verification")

    def test_parameters_are_written_as_text_chunk(self) -> None:
        data = _write_png(
            "prompt\nNegative prompt:\nSteps: 8, Size: 64x32",
        )
        chunks = _png_chunks(data)

        self.assertTrue(_has_chunk(chunks, b"tEXt", b"parameters\x00"))
        self.assertFalse(_has_chunk(chunks, b"iTXt", b"parameters\x00"))
        self.assertTrue(_has_chunk(chunks, b"tEXt", b"Software\x00"))

        with Image.open(BytesIO(data)) as image:
            self.assertIn("parameters", image.text)
            self.assertIn("Size: 64x32", image.text["parameters"])
            self.assertEqual(image.text["Software"], SOFTWARE_TEXT)

    def test_unicode_parameters_get_text_compatibility_and_utf8_copy(self) -> None:
        data = _write_png(
            "雪の街\nNegative prompt:\nSteps: 8, Size: 64x32",
        )
        chunks = _png_chunks(data)

        self.assertTrue(_has_chunk(chunks, b"tEXt", b"parameters\x00"))
        self.assertTrue(_has_chunk(chunks, b"iTXt", b"parameters_utf8\x00"))

        with Image.open(BytesIO(data)) as image:
            self.assertIn("parameters", image.text)
            self.assertIn("parameters_utf8", image.text)
            self.assertIn("???", image.text["parameters"])
            self.assertIn("雪の街", image.text["parameters_utf8"])

    def test_non_latin_unicode_parameters_do_not_crash(self) -> None:
        data = _write_png("雪の街\nNegative prompt:\nSteps: 8, Size: 64x32")
        chunks = _png_chunks(data)

        self.assertTrue(_has_chunk(chunks, b"tEXt", b"parameters\x00"))
        self.assertTrue(_has_chunk(chunks, b"iTXt", b"parameters_utf8\x00"))
        self.assertTrue(parameters_text_needs_latin1_fallback("雪の街"))
        with Image.open(BytesIO(data)) as image:
            self.assertIn("???", image.text["parameters"])
            self.assertIn("雪の街", image.text["parameters_utf8"])

    def test_latin1_parameters_are_written_exactly(self) -> None:
        data = _write_png("café\nNegative prompt:\nSteps: 8, Size: 64x32")

        self.assertFalse(_has_chunk(_png_chunks(data), b"iTXt", b"parameters_utf8\x00"))
        self.assertFalse(parameters_text_needs_latin1_fallback("café"))
        with Image.open(BytesIO(data)) as image:
            self.assertIn("café", image.text["parameters"])

    def test_prompt_workflow_and_civitai_are_itxt(self) -> None:
        chunks = _png_chunks(_write_png("prompt\nNegative prompt:\nSteps: 8, Size: 64x32"))

        self.assertTrue(_has_chunk(chunks, b"iTXt", b"prompt\x00"))
        self.assertTrue(_has_chunk(chunks, b"iTXt", b"workflow\x00"))
        self.assertTrue(_has_chunk(chunks, b"iTXt", b"civitai\x00"))

    def test_full_unicode_prompt_is_preserved_in_prompt_itxt(self) -> None:
        data = _write_png(
            "compatible parameters",
            prompt={"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "雪の街 café"}}},
        )

        with Image.open(BytesIO(data)) as image:
            prompt = json.loads(image.text["prompt"])
            self.assertEqual(prompt["1"]["inputs"]["text"], "雪の街 café")

    def test_standard_text_keywords_are_valid(self) -> None:
        for chunk_type, chunk_data in _png_chunks(_write_png("prompt")):
            if chunk_type not in {b"tEXt", b"zTXt", b"iTXt"}:
                continue
            keyword = chunk_data.split(b"\x00", 1)[0]
            self.assertGreaterEqual(len(keyword), 1)
            self.assertLessEqual(len(keyword), 79)
            self.assertEqual(keyword, keyword.strip())
            self.assertNotIn(b"  ", keyword)
            for byte in keyword:
                self.assertTrue(byte == 32 or 32 <= byte <= 126 or 161 <= byte <= 255)

    def test_standard_software_chunk_is_safe(self) -> None:
        self.assertTrue(SOFTWARE_TEXT.encode("latin-1"))
        self.assertNotIn(b"C:\\", SOFTWARE_TEXT.encode("latin-1"))
        self.assertNotIn(b"/Users/", SOFTWARE_TEXT.encode("latin-1"))
        self.assertNotIn(b"token", SOFTWARE_TEXT.lower().encode("latin-1"))

    def test_exif_user_comment_is_written_by_default(self) -> None:
        data = _write_png("prompt")
        chunk_types = [chunk_type for chunk_type, _chunk_data in _png_chunks(data)]

        self.assertIn(b"eXIf", chunk_types)
        self.assertNotIn(b"tIME", chunk_types)
        self.assertFalse(_has_chunk(_png_chunks(data), b"iTXt", b"XML:com.adobe.xmp\x00"))
        with Image.open(BytesIO(data)) as image:
            exif_ifd = image.getexif().get_ifd(EXIF_IFD_TAG)
            text, encoding = decode_user_comment(exif_ifd.get(USER_COMMENT_TAG))
        self.assertEqual(encoding, "UNICODE UTF-16BE")
        self.assertIn("Civitai metadata:", text)

    def test_minimal_mode_has_only_exif_metadata(self) -> None:
        data = _write_minimal_png("prompt\nNegative prompt:\nSteps: 8, Size: 64x32")
        chunks = _png_chunks(data)
        chunk_types = [chunk_type for chunk_type, _chunk_data in chunks]

        self.assertIn(b"eXIf", chunk_types)
        self.assertFalse(any(kind in {b"tEXt", b"iTXt", b"zTXt"} for kind, _data in chunks))
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.text, {})
            exif_ifd = image.getexif().get_ifd(EXIF_IFD_TAG)
            text, encoding = decode_user_comment(exif_ifd.get(USER_COMMENT_TAG))
        self.assertEqual(encoding, "UNICODE UTF-16BE")
        self.assertIn("Civitai metadata:", text)

    def test_chunk_inspection_tool_reports_metadata_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.png"
            path.write_bytes(_write_png("prompt\nNegative prompt:\nSteps: 8, Size: 64x32"))
            report = inspect_png(path)
            parsed = iter_png_chunks(path)

        self.assertIn("parameters: tEXt", report)
        self.assertIn("prompt: iTXt", report)
        self.assertIn("workflow: iTXt", report)
        self.assertIn("civitai: iTXt", report)
        self.assertIn("Software: tEXt", report)
        self.assertIn("eXIf: present", report)
        self.assertIn("exif UserComment:", report)
        self.assertTrue(all(chunk.crc_ok for chunk in parsed))

    def test_non_latin_parameters_warning_is_embedded_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir()
            image = Image.new("RGB", (8, 8), color=(1, 2, 3))
            scan = WorkflowScanResult(
                prompt=PromptMetadata(positive="雪の街"),
                generation=GenerationSettings(width=8, height=8, steps=1),
                resources=(),
                unresolved_resources=(),
                warnings=(),
                generator=GeneratorMetadata(version="test"),
            )
            patches = [
                mock.patch.object(nodes, "_get_comfy_output_directory", return_value=output_dir),
                mock.patch.object(
                    nodes,
                    "_get_save_image_path",
                    side_effect=lambda prefix, out, _w, _h: (str(out), prefix, 1, "", prefix),
                ),
                mock.patch.object(nodes, "_tensor_to_pil_image", return_value=image),
                mock.patch.object(nodes, "scan_workflow_graph", return_value=scan),
            ]
            for patch in patches:
                patch.start()
            try:
                result = nodes.SaveImageWithCivitaiMetadata().save_images([_FakeTensor()])
            finally:
                for patch in reversed(patches):
                    patch.stop()

            ui = result["ui"]
            png_path = output_dir / ui["images"][0]["filename"]
            with Image.open(png_path) as saved:
                manifest = json.loads(saved.text["civitai"])

        warning_codes = {warning["code"] for warning in manifest["validation"]["warnings"]}
        save_warning_codes = {warning["code"] for warning in manifest.get("saveWarnings", [])}
        self.assertIn("parameters_text_latin1_fallback", warning_codes)
        self.assertIn("parameters_text_latin1_fallback", save_warning_codes)

    def test_node_normal_output_preserves_text_itxt_chunks_and_adds_exif(self) -> None:
        png_path = _run_node_save(civitai_exif_minimal=False)
        chunks = _png_chunks(png_path.read_bytes())

        self.assertTrue(_has_chunk(chunks, b"tEXt", b"parameters\x00"))
        self.assertTrue(_has_chunk(chunks, b"tEXt", b"Software\x00"))
        self.assertTrue(_has_chunk(chunks, b"iTXt", b"prompt\x00"))
        self.assertTrue(_has_chunk(chunks, b"iTXt", b"workflow\x00"))
        self.assertTrue(_has_chunk(chunks, b"iTXt", b"civitai\x00"))
        self.assertIn(b"eXIf", [kind for kind, _data in chunks])
        with Image.open(png_path) as image:
            self.assertIn("parameters", image.text)
            self.assertIn("Steps: 1", image.text["parameters"])
            self.assertIn("civitai", image.text)

    def test_node_minimal_output_omits_text_itxt_chunks_and_keeps_exif(self) -> None:
        png_path = _run_node_save(civitai_exif_minimal=True)
        chunks = _png_chunks(png_path.read_bytes())

        self.assertIn(b"eXIf", [kind for kind, _data in chunks])
        self.assertFalse(any(kind in {b"tEXt", b"iTXt", b"zTXt"} for kind, _data in chunks))
        with Image.open(png_path) as image:
            self.assertEqual(image.text, {})
            exif_ifd = image.getexif().get_ifd(EXIF_IFD_TAG)
            text, encoding = decode_user_comment(exif_ifd.get(USER_COMMENT_TAG))
        self.assertEqual(encoding, "UNICODE UTF-16BE")
        self.assertIn("Steps: 1", text)
        self.assertIn("Size: 8x8", text)


def _write_png(parameters: str, *, prompt: dict | None = None) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (64, 32), color=(1, 2, 3))
    pnginfo = build_pnginfo(
        parameters=parameters,
        prompt=prompt or {"1": {"class_type": "KSampler", "inputs": {}}},
        extra_pnginfo={"workflow": {"nodes": []}},
        include_workflow=True,
        civitai_manifest={"schemaName": "test"},
    )
    exif = build_exif_bytes(
        prompt=PromptMetadata(positive=parameters.splitlines()[0] if parameters else ""),
        generation=GenerationSettings(width=64, height=32, steps=8),
        resources=(),
    )
    image.save(output, format="PNG", pnginfo=pnginfo, exif=exif)
    return output.getvalue()


def _write_minimal_png(parameters: str) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (64, 32), color=(1, 2, 3))
    exif = build_exif_bytes(
        prompt=PromptMetadata(positive=parameters.splitlines()[0] if parameters else ""),
        generation=GenerationSettings(width=64, height=32, steps=8),
        resources=(),
    )
    image.save(output, format="PNG", exif=exif)
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


class _FakeTensor:
    shape = (8, 8, 3)


def _run_node_save(*, civitai_exif_minimal: bool) -> Path:
    tmp = tempfile.TemporaryDirectory()
    output_dir = Path(tmp.name) / "output"
    output_dir.mkdir()
    image = Image.new("RGB", (8, 8), color=(1, 2, 3))
    scan = WorkflowScanResult(
        prompt=PromptMetadata(positive="test prompt"),
        generation=GenerationSettings(width=8, height=8, steps=1, sampler="Euler", seed=123),
        resources=(),
        unresolved_resources=(),
        warnings=(),
        generator=GeneratorMetadata(version="test"),
    )
    patches = [
        mock.patch.object(nodes, "_get_comfy_output_directory", return_value=output_dir),
        mock.patch.object(
            nodes,
            "_get_save_image_path",
            side_effect=lambda prefix, out, _w, _h: (str(out), prefix, 1, "", prefix),
        ),
        mock.patch.object(nodes, "_tensor_to_pil_image", return_value=image),
        mock.patch.object(nodes, "scan_workflow_graph", return_value=scan),
    ]
    for patch in patches:
        patch.start()
    try:
        result = nodes.SaveImageWithCivitaiMetadata().save_images(
            [_FakeTensor()],
            civitai_exif_minimal=civitai_exif_minimal,
            prompt={"1": {"class_type": "KSampler", "inputs": {}}},
            extra_pnginfo={"workflow": {"nodes": []}},
        )
        path = output_dir / result["ui"]["images"][0]["filename"]
        keep_tmp = getattr(_run_node_save, "_kept_tmp", [])
        keep_tmp.append(tmp)
        _run_node_save._kept_tmp = keep_tmp
        return path
    finally:
        for patch in reversed(patches):
            patch.stop()


if __name__ == "__main__":
    unittest.main()
