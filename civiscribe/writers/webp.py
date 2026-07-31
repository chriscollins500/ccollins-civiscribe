"""Fidelity-first Pillow WebP writer with A1111 EXIF metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from ..domain import ImageFormat, ImageFrame, WriteError
from ..projections import ExifMetadataProjection, WriterMetadata
from .exif import EXIF_VERSION, build_exif, read_exif, safe_text
from .options import WebpOptions
from .pixels import encode_uint8
from .protocol import WriteResult


def _webp_image(frame: ImageFrame) -> Image.Image:
    image = Image.fromarray(encode_uint8(frame))
    return image.convert("RGB") if frame.channels == 1 else image


def _exif_payload(
    metadata: ExifMetadataProjection,
    frame: ImageFrame,
) -> bytes:
    width = frame.width if metadata.write_dimensions else None
    height = frame.height if metadata.write_dimensions else None
    return build_exif(
        metadata.parameters,
        software=metadata.software,
        width=width,
        height=height,
    )


def _verify_metadata(
    image: Image.Image,
    metadata: ExifMetadataProjection,
    frame: ImageFrame,
) -> None:
    values = read_exif(image)
    if values.user_comment != safe_text(metadata.parameters):
        raise WriteError("webp_postcheck_exif_user_comment_mismatch")
    if metadata.software is not None and values.software != safe_text(metadata.software):
        raise WriteError("webp_postcheck_software_mismatch")
    if metadata.write_dimensions and (
        values.pixel_width != frame.width or values.pixel_height != frame.height
    ):
        raise WriteError("webp_postcheck_exif_dimensions_mismatch")
    if values.exif_version != EXIF_VERSION:
        raise WriteError("webp_postcheck_exif_version_mismatch")


class WebpWriter:
    """Encode and verify one still WebP with lossless defaults."""

    output_format = ImageFormat.WEBP
    format_name = "WEBP"
    extension = ".webp"

    def __init__(self, options: WebpOptions | None = None) -> None:
        self.options = options or WebpOptions()

    def write(
        self,
        frame: ImageFrame,
        destination: Path,
        metadata: WriterMetadata | None = None,
    ) -> WriteResult:
        if metadata is not None and not isinstance(metadata, ExifMetadataProjection):
            raise WriteError("webp_metadata_projection_invalid")
        try:
            image = _webp_image(frame)
            save_options: dict[str, Any] = {
                "format": self.format_name,
                "lossless": self.options.lossless,
                "quality": self.options.quality,
                "method": self.options.method,
            }
            if self.options.lossless and self.options.exact:
                save_options["exact"] = True
            if metadata is not None:
                save_options["exif"] = _exif_payload(metadata, frame)
            image.save(destination, **save_options)
            with Image.open(destination) as reopened:
                reopened.load()
                if reopened.format != self.format_name:
                    raise WriteError("webp_postcheck_format_mismatch")
                if reopened.size != (frame.width, frame.height):
                    raise WriteError("webp_postcheck_dimensions_mismatch")
                if metadata is not None:
                    _verify_metadata(reopened, metadata, frame)
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
            raise WriteError("webp_write_or_postcheck_failed") from exc


__all__ = ["WebpWriter"]
