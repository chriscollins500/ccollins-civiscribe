"""Bounded EXIF authoring and verification shared by still-image writers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PIL import Image

from ..domain import WriteError
from ..projections.sanitize import metadata_text

EXIF_IFD_TAG = 0x8769
SOFTWARE_TAG = 0x0131
YCBCR_POSITIONING_TAG = 0x0213
EXIF_VERSION_TAG = 0x9000
COMPONENTS_CONFIGURATION_TAG = 0x9101
USER_COMMENT_TAG = 0x9286
FLASHPIX_VERSION_TAG = 0xA000
COLOR_SPACE_TAG = 0xA001
PIXEL_X_DIMENSION_TAG = 0xA002
PIXEL_Y_DIMENSION_TAG = 0xA003
USER_COMMENT_PREFIX = b"UNICODE\x00"
EXIF_VERSION = b"0232"
YCBCR_COMPONENTS_CONFIGURATION = b"\x01\x02\x03\x00"
FLASHPIX_VERSION = b"0100"
COLOR_SPACE_UNCALIBRATED = 0xFFFF
YCBCR_POSITIONING_CENTERED = 1
MAX_EXIF_USER_COMMENT_BYTES = 60 * 1024


@dataclass(frozen=True, slots=True)
class ExifValues:
    """Decoded EXIF facts required by the CiviScribe writer contract."""

    user_comment: str | None
    software: str | None
    pixel_width: int | None
    pixel_height: int | None
    exif_version: bytes | None = None
    components_configuration: bytes | None = None
    flashpix_version: bytes | None = None
    color_space: int | None = None
    ycbcr_positioning: int | None = None


def safe_text(value: str) -> str:
    """Return normalized, non-executable metadata text."""

    return metadata_text(value) or ""


def normalize_user_comment_type(payload: bytes) -> bytes:
    """Normalize Pillow byte fields that EXIF defines as UNDEFINED."""

    data = bytearray(payload)
    tiff_start = 6 if data.startswith(b"Exif\x00\x00") else 0
    if len(data) < tiff_start + 8:
        raise WriteError("exif_user_comment_layout_invalid")
    marker = bytes(data[tiff_start : tiff_start + 2])
    if marker == b"II":
        byteorder: Literal["little", "big"] = "little"
    elif marker == b"MM":
        byteorder = "big"
    else:
        raise WriteError("exif_user_comment_layout_invalid")
    byte_type = (1).to_bytes(2, byteorder)
    undefined_type = (7).to_bytes(2, byteorder)
    for tag, required in (
        (USER_COMMENT_TAG, True),
        (COMPONENTS_CONFIGURATION_TAG, False),
    ):
        byte_tag = tag.to_bytes(2, byteorder)
        location = data.find(byte_tag + byte_type, tiff_start + 8)
        if location >= 0:
            data[location + 2 : location + 4] = undefined_type
        elif data.find(byte_tag + undefined_type, tiff_start + 8) < 0 and required:
            raise WriteError("exif_user_comment_layout_invalid")
    return bytes(data)


def build_exif(
    user_comment: str,
    *,
    software: str | None = None,
    width: int | None = None,
    height: int | None = None,
    jpeg_required_fields: bool = False,
) -> bytes:
    """Author only truthful software, dimensions, and A1111 UserComment fields."""

    encoded_comment = USER_COMMENT_PREFIX + safe_text(user_comment).encode(
        "utf-16-be",
        errors="replace",
    )
    if len(encoded_comment) > MAX_EXIF_USER_COMMENT_BYTES:
        raise WriteError("exif_user_comment_too_large")
    if (width is None) is not (height is None):
        raise WriteError("exif_dimensions_incomplete")
    if jpeg_required_fields and width is None:
        raise WriteError("exif_jpeg_dimensions_required")

    exif = Image.Exif()
    if software is not None:
        exif[SOFTWARE_TAG] = safe_text(software)
    if jpeg_required_fields:
        exif[YCBCR_POSITIONING_TAG] = YCBCR_POSITIONING_CENTERED
    nested: dict[int, object] = {
        EXIF_VERSION_TAG: EXIF_VERSION,
        USER_COMMENT_TAG: encoded_comment,
    }
    if jpeg_required_fields:
        nested[COMPONENTS_CONFIGURATION_TAG] = YCBCR_COMPONENTS_CONFIGURATION
        nested[FLASHPIX_VERSION_TAG] = FLASHPIX_VERSION
        nested[COLOR_SPACE_TAG] = COLOR_SPACE_UNCALIBRATED
    if width is not None and height is not None:
        if width < 1 or height < 1:
            raise WriteError("exif_dimensions_invalid")
        nested[PIXEL_X_DIMENSION_TAG] = width
        nested[PIXEL_Y_DIMENSION_TAG] = height
    exif[EXIF_IFD_TAG] = nested
    return normalize_user_comment_type(exif.tobytes())


def decode_user_comment(value: object) -> str | None:
    """Decode the Unicode EXIF UserComment form authored by CiviScribe."""

    if isinstance(value, str):
        return value
    if not isinstance(value, bytes) or not value.startswith(USER_COMMENT_PREFIX):
        return None
    return value[len(USER_COMMENT_PREFIX) :].decode("utf-16-be", errors="replace")


def read_exif(image: Image.Image) -> ExifValues:
    """Read the small EXIF subset CiviScribe authors."""

    exif = image.getexif()
    try:
        nested = exif.get_ifd(EXIF_IFD_TAG)
    except (KeyError, TypeError, ValueError):
        nested = {}
    software = exif.get(SOFTWARE_TAG)
    return ExifValues(
        user_comment=decode_user_comment(nested.get(USER_COMMENT_TAG)),
        software=software if isinstance(software, str) else None,
        pixel_width=_integer_or_none(nested.get(PIXEL_X_DIMENSION_TAG)),
        pixel_height=_integer_or_none(nested.get(PIXEL_Y_DIMENSION_TAG)),
        exif_version=_bytes_or_none(nested.get(EXIF_VERSION_TAG)),
        components_configuration=_bytes_or_none(nested.get(COMPONENTS_CONFIGURATION_TAG)),
        flashpix_version=_bytes_or_none(nested.get(FLASHPIX_VERSION_TAG)),
        color_space=_integer_or_none(nested.get(COLOR_SPACE_TAG)),
        ycbcr_positioning=_integer_or_none(exif.get(YCBCR_POSITIONING_TAG)),
    )


def _integer_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bytes_or_none(value: object) -> bytes | None:
    return value if isinstance(value, bytes) else None


__all__ = [
    "COLOR_SPACE_TAG",
    "COLOR_SPACE_UNCALIBRATED",
    "COMPONENTS_CONFIGURATION_TAG",
    "EXIF_IFD_TAG",
    "EXIF_VERSION",
    "EXIF_VERSION_TAG",
    "FLASHPIX_VERSION",
    "FLASHPIX_VERSION_TAG",
    "MAX_EXIF_USER_COMMENT_BYTES",
    "PIXEL_X_DIMENSION_TAG",
    "PIXEL_Y_DIMENSION_TAG",
    "SOFTWARE_TAG",
    "USER_COMMENT_PREFIX",
    "USER_COMMENT_TAG",
    "YCBCR_COMPONENTS_CONFIGURATION",
    "YCBCR_POSITIONING_CENTERED",
    "YCBCR_POSITIONING_TAG",
    "ExifValues",
    "build_exif",
    "decode_user_comment",
    "normalize_user_comment_type",
    "read_exif",
    "safe_text",
]
