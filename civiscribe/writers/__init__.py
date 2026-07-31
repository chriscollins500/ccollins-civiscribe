"""Image writer adapters."""

from .jpeg import JpegWriter
from .options import JpegOptions, WebpOptions, WriterOptions, parse_rgb_color
from .png import PngWriter
from .protocol import ImageWriter, WriteResult
from .registry import create_writer
from .webp import WebpWriter

__all__ = [
    "ImageWriter",
    "JpegOptions",
    "JpegWriter",
    "PngWriter",
    "WebpOptions",
    "WebpWriter",
    "WriteResult",
    "WriterOptions",
    "create_writer",
    "parse_rgb_color",
]
