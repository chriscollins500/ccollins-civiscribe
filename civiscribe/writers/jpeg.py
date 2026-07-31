"""Maximum-fidelity Pillow JPEG writer with A1111 EXIF metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from ..domain import ImageFormat, ImageFrame, WriteError
from ..projections import ExifMetadataProjection, WriterMetadata
from .exif import (
    COLOR_SPACE_UNCALIBRATED,
    EXIF_VERSION,
    FLASHPIX_VERSION,
    YCBCR_COMPONENTS_CONFIGURATION,
    YCBCR_POSITIONING_CENTERED,
    build_exif,
    read_exif,
    safe_text,
)
from .options import JpegOptions
from .pixels import encode_uint8
from .protocol import WriteResult

RGBA_CHANNELS = 4


def _jpeg_image(frame: ImageFrame, options: JpegOptions) -> Image.Image:
    encoded = encode_uint8(frame)
    image = Image.fromarray(encoded)
    if frame.channels != RGBA_CHANNELS:
        return image
    background = Image.new(
        "RGBA",
        image.size,
        (*options.alpha_background, 255),
    )
    return Image.alpha_composite(background, image.convert("RGBA")).convert("RGB")


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
        jpeg_required_fields=metadata.write_dimensions,
    )


def _verify_metadata(
    image: Image.Image,
    metadata: ExifMetadataProjection,
    frame: ImageFrame,
) -> None:
    values = read_exif(image)
    if values.user_comment != safe_text(metadata.parameters):
        raise WriteError("jpeg_postcheck_exif_user_comment_mismatch")
    if metadata.software is not None and values.software != safe_text(metadata.software):
        raise WriteError("jpeg_postcheck_software_mismatch")
    if metadata.write_dimensions and (
        values.pixel_width != frame.width or values.pixel_height != frame.height
    ):
        raise WriteError("jpeg_postcheck_exif_dimensions_mismatch")
    if values.exif_version != EXIF_VERSION:
        raise WriteError("jpeg_postcheck_exif_version_mismatch")
    if metadata.write_dimensions and (
        values.components_configuration != YCBCR_COMPONENTS_CONFIGURATION
        or values.flashpix_version != FLASHPIX_VERSION
        or values.color_space != COLOR_SPACE_UNCALIBRATED
        or values.ycbcr_positioning != YCBCR_POSITIONING_CENTERED
    ):
        raise WriteError("jpeg_postcheck_exif_required_fields_mismatch")


class JpegWriter:
    """Encode and verify one maximum-fidelity baseline JPEG."""

    output_format = ImageFormat.JPEG
    format_name = "JPEG"
    extension = ".jpg"

    def __init__(self, options: JpegOptions | None = None) -> None:
        self.options = options or JpegOptions()

    def write(
        self,
        frame: ImageFrame,
        destination: Path,
        metadata: WriterMetadata | None = None,
    ) -> WriteResult:
        if metadata is not None and not isinstance(metadata, ExifMetadataProjection):
            raise WriteError("jpeg_metadata_projection_invalid")
        try:
            image = _jpeg_image(frame, self.options)
            save_options: dict[str, Any] = {
                "format": self.format_name,
                "quality": self.options.quality,
                "optimize": self.options.optimize,
                "subsampling": self.options.subsampling,
            }
            if metadata is not None:
                save_options["exif"] = _exif_payload(metadata, frame)
            image.save(destination, **save_options)
            with Image.open(destination) as reopened:
                reopened.load()
                if reopened.format != self.format_name:
                    raise WriteError("jpeg_postcheck_format_mismatch")
                if reopened.size != (frame.width, frame.height):
                    raise WriteError("jpeg_postcheck_dimensions_mismatch")
                if reopened.mode not in {"L", "RGB"}:
                    raise WriteError("jpeg_postcheck_mode_mismatch")
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
            raise WriteError("jpeg_write_or_postcheck_failed") from exc


__all__ = ["JpegWriter"]
