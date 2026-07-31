"""Typed, fidelity-first options for supported Pillow writers."""

from __future__ import annotations

from dataclasses import dataclass, field

type RgbColor = tuple[int, int, int]

BYTE_MAX = 255
JPEG_QUALITY_MAX = 100
RGB_COMPONENT_COUNT = 3
WEBP_METHOD_MAX = 6
WEBP_QUALITY_MAX = 100
HEX_COLOR_LENGTH = 7


def _validate_byte(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= BYTE_MAX:
        raise ValueError("rgb_component_invalid")


@dataclass(frozen=True, slots=True)
class JpegOptions:
    """Maximum-fidelity baseline options for inherently lossy JPEG."""

    quality: int = 100
    optimize: bool = True
    subsampling: int = 0
    alpha_background: RgbColor = (255, 255, 255)

    def __post_init__(self) -> None:
        if (
            isinstance(self.quality, bool)
            or not isinstance(self.quality, int)
            or not 1 <= self.quality <= JPEG_QUALITY_MAX
        ):
            raise ValueError("jpeg_quality_invalid")
        if self.subsampling not in {0, 1, 2}:
            raise ValueError("jpeg_subsampling_invalid")
        if len(self.alpha_background) != RGB_COMPONENT_COUNT:
            raise ValueError("jpeg_alpha_background_invalid")
        for component in self.alpha_background:
            _validate_byte(component)


@dataclass(frozen=True, slots=True)
class WebpOptions:
    """Lossless, deterministic WebP defaults with exact transparent RGB."""

    lossless: bool = True
    quality: int = 100
    method: int = 6
    exact: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.quality, bool)
            or not isinstance(self.quality, int)
            or not 0 <= self.quality <= WEBP_QUALITY_MAX
        ):
            raise ValueError("webp_quality_invalid")
        if (
            isinstance(self.method, bool)
            or not isinstance(self.method, int)
            or not 0 <= self.method <= WEBP_METHOD_MAX
        ):
            raise ValueError("webp_method_invalid")


@dataclass(frozen=True, slots=True)
class WriterOptions:
    """All supported format options; dispatch consumes only the selected set."""

    jpeg: JpegOptions = field(default_factory=JpegOptions)
    webp: WebpOptions = field(default_factory=WebpOptions)


def parse_rgb_color(value: str, *, fallback: RgbColor = (255, 255, 255)) -> RgbColor:
    """Parse a CSS-style six-digit RGB value without accepting other syntax."""

    normalized = value.strip()
    if len(normalized) != HEX_COLOR_LENGTH or not normalized.startswith("#"):
        return fallback
    try:
        return (
            int(normalized[1:3], 16),
            int(normalized[3:5], 16),
            int(normalized[5:7], 16),
        )
    except ValueError:
        return fallback


__all__ = [
    "JpegOptions",
    "RgbColor",
    "WebpOptions",
    "WriterOptions",
    "parse_rgb_color",
]
