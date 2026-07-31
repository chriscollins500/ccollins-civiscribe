from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from PIL import Image

from civiscribe.domain import WriteError
from civiscribe.writers import exif as exif_module


def test_exif_round_trip_contains_only_truthful_authored_fields(tmp_path: Path) -> None:
    payload = exif_module.build_exif(
        "prompt 雪",
        software="CiviScribe",
        width=3,
        height=2,
    )
    path = tmp_path / "exif.jpg"
    Image.new("RGB", (3, 2)).save(path, format="JPEG", exif=payload)

    with Image.open(path) as image:
        values = exif_module.read_exif(image)
        raw = image.getexif()

    assert values == exif_module.ExifValues(
        "prompt 雪",
        "CiviScribe",
        3,
        2,
        exif_module.EXIF_VERSION,
    )
    assert raw.get(0x010F) is None
    assert raw.get(0x0110) is None
    assert raw.get(0x8825) is None


def test_exif_builder_supports_comment_only_fallback(tmp_path: Path) -> None:
    path = tmp_path / "comment.webp"
    Image.new("RGB", (1, 1)).save(
        path,
        format="WEBP",
        lossless=True,
        exif=exif_module.build_exif("Steps: 1"),
    )
    with Image.open(path) as image:
        assert exif_module.read_exif(image) == exif_module.ExifValues(
            "Steps: 1",
            None,
            None,
            None,
            exif_module.EXIF_VERSION,
        )


def test_exif_builder_supports_required_jpeg_fields(tmp_path: Path) -> None:
    payload = exif_module.build_exif(
        "Steps: 1",
        width=3,
        height=2,
        jpeg_required_fields=True,
    )
    path = tmp_path / "standards.jpg"
    Image.new("RGB", (3, 2)).save(
        path,
        format="JPEG",
        exif=payload,
    )

    with Image.open(path) as image:
        values = exif_module.read_exif(image)

    assert values.components_configuration == exif_module.YCBCR_COMPONENTS_CONFIGURATION
    assert values.flashpix_version == exif_module.FLASHPIX_VERSION
    assert values.color_space == exif_module.COLOR_SPACE_UNCALIBRATED
    assert values.ycbcr_positioning == exif_module.YCBCR_POSITIONING_CENTERED
    component_tag = exif_module.COMPONENTS_CONFIGURATION_TAG.to_bytes(2, "big")
    undefined_type = (7).to_bytes(2, "big")
    assert component_tag + undefined_type in payload


def test_exif_builder_rejects_oversized_incomplete_and_invalid_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(exif_module, "MAX_EXIF_USER_COMMENT_BYTES", 10)
    with pytest.raises(WriteError, match="exif_user_comment_too_large"):
        exif_module.build_exif("long")
    with pytest.raises(WriteError, match="exif_dimensions_incomplete"):
        exif_module.build_exif("", width=1)
    with pytest.raises(WriteError, match="exif_dimensions_invalid"):
        exif_module.build_exif("", width=0, height=1)
    with pytest.raises(WriteError, match="exif_jpeg_dimensions_required"):
        exif_module.build_exif("", jpeg_required_fields=True)


def test_exif_type_normalizer_supports_big_endian() -> None:
    byte_tag = exif_module.USER_COMMENT_TAG.to_bytes(2, "big")
    prefix = b"MM" + (b"\x00" * 6)
    normalized = exif_module.normalize_user_comment_type(prefix + byte_tag + (1).to_bytes(2, "big"))
    assert normalized[-2:] == (7).to_bytes(2, "big")


def test_exif_reader_ignores_non_string_software_and_non_integer_dimensions() -> None:
    class _Exif:
        def get_ifd(self, _tag: int) -> dict[int, object]:
            return {
                exif_module.USER_COMMENT_TAG: "plain",
                exif_module.PIXEL_X_DIMENSION_TAG: True,
                exif_module.PIXEL_Y_DIMENSION_TAG: "2",
            }

        def get(self, _tag: int) -> bytes:
            return b"not-text"

    class _Image:
        def getexif(self) -> _Exif:
            return _Exif()

    values = exif_module.read_exif(cast(Image.Image, _Image()))
    assert values == exif_module.ExifValues("plain", None, None, None, None)
