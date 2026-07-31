"""Central format-to-writer dispatch."""

from __future__ import annotations

from ..domain import ImageFormat
from .jpeg import JpegWriter
from .options import WriterOptions
from .png import PngWriter
from .protocol import ImageWriter
from .webp import WebpWriter


def create_writer(
    output_format: ImageFormat,
    options: WriterOptions | None = None,
) -> ImageWriter:
    """Return one configured writer for a supported still-image format."""

    active_options = options or WriterOptions()
    if output_format is ImageFormat.PNG:
        return PngWriter()
    if output_format is ImageFormat.JPEG:
        return JpegWriter(active_options.jpeg)
    if output_format is ImageFormat.WEBP:
        return WebpWriter(active_options.webp)
    raise ValueError("image_format_unsupported")


__all__ = ["create_writer"]
