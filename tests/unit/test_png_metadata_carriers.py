from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngImageFile, PngInfo

from civiscribe.domain import ImageFrame, SerializationError, WriteError
from civiscribe.projections import (
    MetadataTier,
    PngMetadataProjection,
    build_reduced_png_projection,
    build_rich_png_projection,
)
from civiscribe.writers import exif as exif_module
from civiscribe.writers import png as png_module
from civiscribe.writers.png import PngWriter
from tests.projection_support import complete_record

EXIF_IFD_TAG = 0x8769
USER_COMMENT_TAG = 0x9286
WORKFLOW_NODE_ID = 10
GOLDEN_CARRIER_CONTRACT = (
    Path(__file__).resolve().parents[1] / "golden" / "png" / "metadata_carriers_v1.json"
)


def _frame() -> ImageFrame:
    return ImageFrame(np.full((2, 3, 3), 0.5, dtype=np.float32))


def _chunk_pairs(path: Path) -> set[tuple[bytes, str | None]]:
    return set(png_module._chunk_inventory(path))


def _user_comment(path: Path) -> bytes:
    with Image.open(path) as image:
        value = image.getexif().get_ifd(EXIF_IFD_TAG)[USER_COMMENT_TAG]
        assert isinstance(value, bytes)
        return value


def test_rich_png_writes_exact_compatibility_carriers(tmp_path: Path) -> None:
    projection = build_rich_png_projection(
        complete_record(),
        prompt={"10": {"class_type": "CLIPTextEncode", "inputs": {"text": "雪"}}},
        workflow={"nodes": [{"id": 10, "type": "CLIPTextEncode"}]},
    )
    path = tmp_path / "rich.png"

    result = PngWriter().write(_frame(), path, projection)

    pairs = _chunk_pairs(path)
    assert {
        (b"tEXt", "parameters"),
        (b"tEXt", "Software"),
        (b"iTXt", "parameters_utf8"),
        (b"iTXt", "prompt"),
        (b"iTXt", "workflow"),
        (b"iTXt", "civitai"),
        (b"eXIf", None),
    }.issubset(pairs)
    assert (b"iTXt", "parameters") not in pairs
    assert result.metadata_tier == "rich"
    with Image.open(path) as image:
        text = cast(PngImageFile, image).text
        assert text["parameters"].startswith("portrait of café ?")
        assert "portrait of café 雪" in text["parameters_utf8"]
        assert json.loads(text["prompt"])["10"]["inputs"]["text"] == "雪"
        assert json.loads(text["workflow"])["nodes"][0]["id"] == WORKFLOW_NODE_ID
        assert json.loads(text["civitai"])["schemaName"] == ("ccollins-civiscribe.civitai-manifest")
    comment = _user_comment(path)
    assert comment.startswith(b"UNICODE\x00")
    assert "portrait of café 雪" in comment[8:].decode("utf-16-be")


def test_rich_png_matches_golden_carrier_contract(tmp_path: Path) -> None:
    contract = json.loads(GOLDEN_CARRIER_CONTRACT.read_text(encoding="utf-8"))
    projection = build_rich_png_projection(
        complete_record(),
        prompt={"10": {"inputs": {"text": "雪"}}},
        workflow={"nodes": [{"id": 10}]},
    )
    path = tmp_path / "golden-carriers.png"

    PngWriter().write(_frame(), path, projection)

    pairs = _chunk_pairs(path)
    required = {
        (
            item["type"].encode("ascii"),
            cast(str | None, item["keyword"]),
        )
        for item in contract["requiredCarriers"]
    }
    forbidden = {
        (
            item["type"].encode("ascii"),
            cast(str | None, item["keyword"]),
        )
        for item in contract["forbiddenCarriers"]
    }
    assert required.issubset(pairs)
    assert forbidden.isdisjoint(pairs)
    assert _user_comment(path).startswith(b"UNICODE\x00")


def test_reduced_png_is_parser_compatible_text_only(tmp_path: Path) -> None:
    projection = build_reduced_png_projection(complete_record())
    path = tmp_path / "reduced.png"

    result = PngWriter().write(_frame(), path, projection)

    pairs = _chunk_pairs(path)
    assert (b"tEXt", "parameters") in pairs
    assert (b"tEXt", "Software") in pairs
    assert (b"iTXt", "parameters_utf8") in pairs
    assert (b"iTXt", "prompt") not in pairs
    assert (b"eXIf", None) not in pairs
    assert result.metadata_tier == "reduced"


def test_pixels_only_png_remains_metadata_free(tmp_path: Path) -> None:
    path = tmp_path / "pixels.png"
    result = PngWriter().write(_frame(), path)
    assert not any(kind in {b"tEXt", b"iTXt", b"eXIf"} for kind, _keyword in _chunk_pairs(path))
    assert result.metadata_tier is None


def test_rich_projection_can_omit_optional_workflow_and_manifest(
    tmp_path: Path,
) -> None:
    projection = build_rich_png_projection(
        complete_record(),
        prompt={},
        workflow={"nodes": []},
        include_workflow=False,
        include_civitai_manifest=False,
    )
    path = tmp_path / "lean-rich.png"
    PngWriter().write(_frame(), path, projection)
    pairs = _chunk_pairs(path)
    assert (b"iTXt", "prompt") not in pairs
    assert (b"iTXt", "workflow") not in pairs
    assert (b"iTXt", "civitai") not in pairs
    assert (b"eXIf", None) in pairs


def test_manifest_workflow_ref_is_null_when_workflow_is_unavailable() -> None:
    projection = build_rich_png_projection(
        complete_record(),
        prompt={},
        workflow=None,
    )
    assert projection.civitai_json is not None
    manifest = json.loads(projection.civitai_json)
    assert manifest["workflowRefs"] == {
        "prompt": "pnginfo:prompt",
        "workflow": None,
    }


def test_disabled_workflow_embedding_omits_both_graphs_and_refs() -> None:
    projection = build_rich_png_projection(
        complete_record(),
        prompt={"10": {"class_type": "KSampler"}},
        workflow={"nodes": [{"id": 10, "type": "KSampler"}]},
        include_workflow=False,
    )
    assert projection.prompt_json is None
    assert projection.workflow_json is None
    assert projection.civitai_json is not None
    manifest = json.loads(projection.civitai_json)
    assert manifest["workflowRefs"] == {"prompt": None, "workflow": None}


def test_projection_reports_redaction_without_exposing_private_values() -> None:
    projection = build_rich_png_projection(
        complete_record(),
        prompt={
            "path": "C:\\Users\\example\\private\\model.safetensors",
            "api_key": "private-token-value",
        },
        workflow=None,
    )
    assert projection.warning_codes == ("embedded_metadata_private_values_redacted",)
    assert projection.prompt_json is not None
    assert "C:\\Users\\" not in projection.prompt_json
    assert "private-token-value" not in projection.prompt_json
    assert "<redacted-path>" in projection.prompt_json
    assert "<redacted-secret>" in projection.prompt_json


def test_projection_rejects_oversized_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "civiscribe.projections.png.build_a1111",
        lambda _record: "x" * (png_module.MAX_METADATA_CHUNK_BYTES + 1),
    )
    with pytest.raises(SerializationError, match="parameters_output_too_large"):
        build_reduced_png_projection(complete_record())


def test_writer_rejects_oversized_itxt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(png_module, "MAX_METADATA_CHUNK_BYTES", 20)
    projection = PngMetadataProjection(
        tier=MetadataTier.RICH,
        parameters="Steps: 1",
        software="CiviScribe",
        prompt_json="x" * 21,
    )
    with pytest.raises(WriteError, match="png_itxt_chunk_too_large"):
        PngWriter().write(_frame(), tmp_path / "huge.png", projection)


def test_writer_rejects_missing_carrier_after_postcheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(png_module, "_chunk_inventory", lambda _path: ())
    projection = build_reduced_png_projection(complete_record())
    with pytest.raises(
        WriteError,
        match="png_postcheck_metadata_carrier_missing",
    ):
        PngWriter().write(_frame(), tmp_path / "missing.png", projection)


@pytest.mark.parametrize("keyword", ["", "\x00", "x" * 80])
def test_text_writer_rejects_invalid_keyword(keyword: str) -> None:
    with pytest.raises(WriteError, match="png_text_keyword_invalid"):
        png_module._add_text(PngInfo(), keyword, "value")


def test_text_writer_rejects_oversized_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(png_module, "MAX_METADATA_CHUNK_BYTES", 4)
    with pytest.raises(WriteError, match="png_text_chunk_too_large"):
        png_module._add_text(PngInfo(), "key", "12345")


def test_safe_text_removes_nul_and_control_characters() -> None:
    assert png_module._safe_text("a\x00b\x01c\n") == "a b c\n"


def test_exif_type_normalizer_supports_little_endian_and_existing_undefined() -> None:
    byte_tag = USER_COMMENT_TAG.to_bytes(2, "little")
    prefix = b"II" + (b"\x00" * 6)
    normalized = exif_module.normalize_user_comment_type(
        prefix + byte_tag + (1).to_bytes(2, "little")
    )
    assert normalized[-2:] == (7).to_bytes(2, "little")
    already_normalized = prefix + byte_tag + (7).to_bytes(2, "little")
    assert exif_module.normalize_user_comment_type(already_normalized) == already_normalized


@pytest.mark.parametrize(
    "payload",
    [
        b"short",
        b"ZZ" + (b"\x00" * 10),
        b"II" + (b"\x00" * 10),
    ],
)
def test_exif_type_normalizer_rejects_unknown_layout(payload: bytes) -> None:
    with pytest.raises(WriteError, match="exif_user_comment_layout_invalid"):
        exif_module.normalize_user_comment_type(payload)


def test_chunk_inventory_rejects_bad_signature_and_truncation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not-png!")
    with pytest.raises(WriteError, match="png_postcheck_signature_mismatch"):
        png_module._chunk_inventory(bad)

    truncated = tmp_path / "truncated.png"
    truncated.write_bytes(png_module.PNG_SIGNATURE)
    with pytest.raises(WriteError, match="png_chunk_table_truncated"):
        png_module._chunk_inventory(truncated)


def test_chunk_inventory_rejects_oversized_and_malformed_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(png_module, "MAX_METADATA_CHUNK_BYTES", 4)
    oversized = tmp_path / "oversized.png"
    oversized.write_bytes(png_module.PNG_SIGNATURE + (5).to_bytes(4, "big") + b"tEXt")
    with pytest.raises(
        WriteError,
        match="png_postcheck_metadata_chunk_too_large",
    ):
        png_module._chunk_inventory(oversized)

    malformed = tmp_path / "malformed.png"
    malformed.write_bytes(
        png_module.PNG_SIGNATURE + (3).to_bytes(4, "big") + b"tEXt" + b"bad" + (b"\x00" * 4)
    )
    with pytest.raises(WriteError, match="png_postcheck_text_chunk_malformed"):
        png_module._chunk_inventory(malformed)


@pytest.mark.parametrize("value", ["plain", object(), b"ASCII\x00\x00\x00text"])
def test_user_comment_decoder_rejects_non_unicode_values(value: object) -> None:
    expected = "plain" if isinstance(value, str) else None
    assert exif_module.decode_user_comment(value) == expected


class _BrokenExif:
    def get_ifd(self, _tag: int) -> dict[int, bytes]:
        raise ValueError

    def get(self, _tag: int) -> None:
        return None


class _BrokenExifImage:
    def getexif(self) -> _BrokenExif:
        return _BrokenExif()


def test_user_comment_reader_handles_invalid_exif() -> None:
    assert exif_module.read_exif(cast(Image.Image, _BrokenExifImage())).user_comment is None


def test_text_map_is_empty_for_non_png_image() -> None:
    assert png_module._text_map(Image.new("RGB", (1, 1))) == {}


class _Exif:
    def __init__(self, comment: bytes, exif_version: bytes) -> None:
        self.comment = comment
        self.exif_version = exif_version

    def get_ifd(self, _tag: int) -> dict[int, bytes]:
        return {
            exif_module.EXIF_VERSION_TAG: self.exif_version,
            USER_COMMENT_TAG: self.comment,
        }

    def get(self, _tag: int) -> None:
        return None


class _MetadataImage:
    def __init__(self, text: dict[str, str], comment: bytes, exif_version: bytes) -> None:
        self.text = text
        self.comment = comment
        self.exif_version = exif_version

    def getexif(self) -> _Exif:
        return _Exif(self.comment, self.exif_version)


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ("parameters", "png_postcheck_parameters_mismatch"),
        ("Software", "png_postcheck_software_mismatch"),
        ("prompt", "png_postcheck_prompt_mismatch"),
        ("workflow", "png_postcheck_workflow_mismatch"),
        ("civitai", "png_postcheck_civitai_mismatch"),
        ("exif", "png_postcheck_exif_user_comment_mismatch"),
        ("exif_version", "png_postcheck_exif_version_mismatch"),
    ],
)
def test_metadata_postcheck_rejects_each_mismatched_carrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    error: str,
) -> None:
    projection = build_rich_png_projection(
        complete_record(),
        prompt={},
        workflow={"nodes": []},
    )
    text = {
        "parameters": png_module._latin1_text(projection.parameters),
        "Software": png_module._latin1_text(projection.software),
        "prompt": projection.prompt_json or "",
        "workflow": projection.workflow_json or "",
        "civitai": projection.civitai_json or "",
    }
    comment = exif_module.USER_COMMENT_PREFIX + (projection.exif_user_comment or "").encode(
        "utf-16-be"
    )
    exif_version = exif_module.EXIF_VERSION
    if field == "exif":
        comment = b"invalid"
    elif field == "exif_version":
        exif_version = b"0000"
    else:
        text[field] = "invalid"
    monkeypatch.setattr(
        png_module,
        "_chunk_inventory",
        lambda _path: tuple(png_module._required_pairs(projection)),
    )
    with pytest.raises(WriteError, match=error):
        png_module._verify_metadata(
            tmp_path / "unused.png",
            cast(Image.Image, _MetadataImage(text, comment, exif_version)),
            projection,
        )
