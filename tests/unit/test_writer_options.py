from __future__ import annotations

from typing import Any, cast

import pytest

from civiscribe.domain import ImageFormat
from civiscribe.writers import (
    JpegOptions,
    JpegWriter,
    PngWriter,
    WebpOptions,
    WebpWriter,
    WriterOptions,
    create_writer,
    parse_rgb_color,
)


@pytest.mark.parametrize(
    "value",
    [0, 101, True, "100"],
)
def test_jpeg_options_reject_invalid_quality(value: object) -> None:
    with pytest.raises(ValueError, match="jpeg_quality_invalid"):
        JpegOptions(quality=cast(Any, value))


@pytest.mark.parametrize("value", [-1, 3])
def test_jpeg_options_reject_invalid_subsampling(value: int) -> None:
    with pytest.raises(ValueError, match="jpeg_subsampling_invalid"):
        JpegOptions(subsampling=value)


def test_jpeg_options_reject_invalid_background_shape_and_components() -> None:
    with pytest.raises(ValueError, match="jpeg_alpha_background_invalid"):
        JpegOptions(alpha_background=cast(Any, (1, 2)))
    with pytest.raises(ValueError, match="rgb_component_invalid"):
        JpegOptions(alpha_background=(1, 2, 256))


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"quality": -1}, "webp_quality_invalid"),
        ({"quality": 101}, "webp_quality_invalid"),
        ({"quality": True}, "webp_quality_invalid"),
        ({"method": -1}, "webp_method_invalid"),
        ({"method": 7}, "webp_method_invalid"),
        ({"method": True}, "webp_method_invalid"),
    ],
)
def test_webp_options_reject_invalid_values(
    kwargs: dict[str, object],
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        WebpOptions(**cast(Any, kwargs))


def test_rgb_parser_accepts_only_six_digit_hex_and_uses_safe_fallback() -> None:
    assert parse_rgb_color("#12aBcD") == (18, 171, 205)
    assert parse_rgb_color("not-a-color") == (255, 255, 255)
    assert parse_rgb_color("#zzzzzz", fallback=(1, 2, 3)) == (1, 2, 3)


def test_writer_registry_uses_selected_typed_options() -> None:
    options = WriterOptions(
        jpeg=JpegOptions(quality=91),
        webp=WebpOptions(lossless=False, quality=87),
    )
    png = create_writer(ImageFormat.PNG, options)
    jpeg = create_writer(ImageFormat.JPEG, options)
    webp = create_writer(ImageFormat.WEBP, options)

    assert isinstance(png, PngWriter)
    assert isinstance(jpeg, JpegWriter)
    assert jpeg.options is options.jpeg
    assert isinstance(webp, WebpWriter)
    assert webp.options is options.webp


def test_writer_registry_rejects_unknown_runtime_value() -> None:
    with pytest.raises(ValueError, match="image_format_unsupported"):
        create_writer(cast(Any, "avif"))
