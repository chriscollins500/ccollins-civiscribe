"""Lossless Pillow PNG writer with exact compatibility carriers."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO, cast

from PIL import Image, UnidentifiedImageError
from PIL.PngImagePlugin import PngInfo

from ..domain import ImageFormat, ImageFrame, WriteError
from ..projections import PngMetadataProjection, WriterMetadata
from .exif import EXIF_VERSION, build_exif, read_exif, safe_text
from .pixels import encode_uint8
from .protocol import WriteResult

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_TEXT_KEYWORD_BYTES = 79
MAX_METADATA_CHUNK_BYTES = 8 * 1024 * 1024


def _safe_text(value: str) -> str:
    return safe_text(unicodedata.normalize("NFC", value))


def _latin1_text(value: str) -> str:
    return _safe_text(value).encode("latin-1", errors="replace").decode("latin-1")


def _add_text(pnginfo: PngInfo, keyword: str, value: str) -> None:
    encoded_keyword = keyword.encode("latin-1", errors="strict")
    encoded_value = _latin1_text(value).encode("latin-1", errors="strict")
    if not 1 <= len(encoded_keyword) <= MAX_PNG_TEXT_KEYWORD_BYTES or b"\x00" in encoded_keyword:
        raise WriteError("png_text_keyword_invalid")
    if len(encoded_value) > MAX_METADATA_CHUNK_BYTES:
        raise WriteError("png_text_chunk_too_large")
    pnginfo.add(b"tEXt", encoded_keyword + b"\x00" + encoded_value)


def _add_itxt(pnginfo: PngInfo, keyword: str, value: str) -> None:
    safe_value = _safe_text(value)
    if len(safe_value.encode("utf-8")) > MAX_METADATA_CHUNK_BYTES:
        raise WriteError("png_itxt_chunk_too_large")
    pnginfo.add_itxt(keyword, safe_value, zip=False)


def _build_pnginfo(metadata: PngMetadataProjection) -> PngInfo:
    pnginfo = PngInfo()
    _add_text(pnginfo, "parameters", metadata.parameters)
    _add_text(pnginfo, "Software", metadata.software)
    safe_parameters = _safe_text(metadata.parameters)
    if _latin1_text(safe_parameters) != safe_parameters:
        _add_itxt(pnginfo, "parameters_utf8", safe_parameters)
    if metadata.prompt_json is not None:
        _add_itxt(pnginfo, "prompt", metadata.prompt_json)
    if metadata.workflow_json is not None:
        _add_itxt(pnginfo, "workflow", metadata.workflow_json)
    if metadata.civitai_json is not None:
        _add_itxt(pnginfo, "civitai", metadata.civitai_json)
    return pnginfo


def _read_exact(handle: BinaryIO, length: int) -> bytes:
    value = handle.read(length)
    if len(value) != length:
        raise WriteError("png_chunk_table_truncated")
    return value


def _chunk_inventory(path: Path) -> tuple[tuple[bytes, str | None], ...]:
    result: list[tuple[bytes, str | None]] = []
    with path.open("rb") as handle:
        if _read_exact(handle, len(PNG_SIGNATURE)) != PNG_SIGNATURE:
            raise WriteError("png_postcheck_signature_mismatch")
        while True:
            length = int.from_bytes(_read_exact(handle, 4), "big")
            chunk_type = _read_exact(handle, 4)
            is_metadata = chunk_type in {b"tEXt", b"iTXt", b"eXIf"}
            if is_metadata and length > MAX_METADATA_CHUNK_BYTES:
                raise WriteError("png_postcheck_metadata_chunk_too_large")
            if is_metadata:
                payload = _read_exact(handle, length)
            else:
                handle.seek(length, 1)
                payload = b""
            _read_exact(handle, 4)
            keyword: str | None = None
            if chunk_type in {b"tEXt", b"iTXt"}:
                keyword_bytes, separator, _ = payload.partition(b"\x00")
                if not separator:
                    raise WriteError("png_postcheck_text_chunk_malformed")
                keyword = keyword_bytes.decode("latin-1")
            result.append((chunk_type, keyword))
            if chunk_type == b"IEND":
                return tuple(result)


def _text_map(image: Image.Image) -> Mapping[str, str]:
    value = getattr(image, "text", None)
    if not isinstance(value, Mapping):
        return {}
    return cast(Mapping[str, str], value)


def _required_pairs(metadata: PngMetadataProjection) -> set[tuple[bytes, str | None]]:
    pairs: set[tuple[bytes, str | None]] = {
        (b"tEXt", "parameters"),
        (b"tEXt", "Software"),
    }
    if _latin1_text(metadata.parameters) != _safe_text(metadata.parameters):
        pairs.add((b"iTXt", "parameters_utf8"))
    if metadata.prompt_json is not None:
        pairs.add((b"iTXt", "prompt"))
    if metadata.workflow_json is not None:
        pairs.add((b"iTXt", "workflow"))
    if metadata.civitai_json is not None:
        pairs.add((b"iTXt", "civitai"))
    if metadata.exif_user_comment is not None:
        pairs.add((b"eXIf", None))
    return pairs


def _verify_metadata(
    path: Path,
    reopened: Image.Image,
    metadata: PngMetadataProjection,
) -> None:
    inventory = set(_chunk_inventory(path))
    if not _required_pairs(metadata).issubset(inventory):
        raise WriteError("png_postcheck_metadata_carrier_missing")
    text = _text_map(reopened)
    if text.get("parameters") != _latin1_text(metadata.parameters):
        raise WriteError("png_postcheck_parameters_mismatch")
    if text.get("Software") != _latin1_text(metadata.software):
        raise WriteError("png_postcheck_software_mismatch")
    if metadata.prompt_json is not None and text.get("prompt") != metadata.prompt_json:
        raise WriteError("png_postcheck_prompt_mismatch")
    if metadata.workflow_json is not None and text.get("workflow") != metadata.workflow_json:
        raise WriteError("png_postcheck_workflow_mismatch")
    if metadata.civitai_json is not None and text.get("civitai") != metadata.civitai_json:
        raise WriteError("png_postcheck_civitai_mismatch")
    if metadata.exif_user_comment is not None:
        exif = read_exif(reopened)
        if exif.user_comment != _safe_text(metadata.exif_user_comment):
            raise WriteError("png_postcheck_exif_user_comment_mismatch")
        if exif.exif_version != EXIF_VERSION:
            raise WriteError("png_postcheck_exif_version_mismatch")


class PngWriter:
    """Encode and verify one lossless 8-bit PNG."""

    output_format = ImageFormat.PNG
    format_name = "PNG"
    extension = ".png"
    compress_level = 4

    def write(
        self,
        frame: ImageFrame,
        destination: Path,
        metadata: WriterMetadata | None = None,
    ) -> WriteResult:
        if metadata is not None and not isinstance(metadata, PngMetadataProjection):
            raise WriteError("png_metadata_projection_invalid")
        encoded = encode_uint8(frame)
        try:
            image = Image.fromarray(encoded)
            if metadata is None:
                image.save(
                    destination,
                    format=self.format_name,
                    compress_level=self.compress_level,
                    optimize=False,
                )
            else:
                exif = (
                    build_exif(metadata.exif_user_comment)
                    if metadata.exif_user_comment is not None
                    else b""
                )
                image.save(
                    destination,
                    format=self.format_name,
                    compress_level=self.compress_level,
                    optimize=False,
                    pnginfo=_build_pnginfo(metadata),
                    exif=exif,
                )
            with Image.open(destination) as reopened:
                reopened.load()
                if reopened.format != self.format_name:
                    raise WriteError("png_postcheck_format_mismatch")
                if reopened.size != (frame.width, frame.height):
                    raise WriteError("png_postcheck_dimensions_mismatch")
                if metadata is not None:
                    _verify_metadata(destination, reopened, metadata)
                return WriteResult(
                    format_name=self.format_name,
                    width=reopened.width,
                    height=reopened.height,
                    mode=reopened.mode,
                    encoded_sample_bits=8,
                    metadata_tier=metadata.tier.value if metadata is not None else None,
                )
        except WriteError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError, UnidentifiedImageError) as exc:
            raise WriteError("png_write_or_postcheck_failed") from exc
