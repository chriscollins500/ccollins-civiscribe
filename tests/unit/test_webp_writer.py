from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from civiscribe.domain import GenerationRecord, ImageFrame, WriteError
from civiscribe.projections import (
    ExifMetadataProjection,
    MetadataTier,
    PngMetadataProjection,
    build_reduced_exif_projection,
    build_rich_exif_projection,
)
from civiscribe.writers import WebpOptions, WebpWriter
from civiscribe.writers import exif as exif_module
from civiscribe.writers import webp as webp_module
from civiscribe.writers.exif import ExifValues
from tests.projection_support import complete_record

UINT8_SAMPLE_BITS = 8


def _rgba_frame() -> ImageFrame:
    return ImageFrame(
        np.array(
            [
                [[0.1, 0.2, 0.3, 0.0], [0.4, 0.5, 0.6, 1.0]],
                [[0.7, 0.8, 0.9, 0.5], [0.2, 0.3, 0.4, 1.0]],
            ],
            dtype=np.float32,
        )
    )


def test_lossless_webp_preserves_rgba_and_transparent_rgb_exactly(tmp_path: Path) -> None:
    frame = _rgba_frame()
    path = tmp_path / "image.webp"
    result = WebpWriter().write(frame, path)

    expected = np.clip(
        np.multiply(frame.pixels, np.float32(255.0)),
        0,
        255,
    ).astype(np.uint8)
    with Image.open(path) as image:
        actual = np.asarray(image)
        assert image.info.get("exif") is None
    assert np.array_equal(actual, expected)
    assert result.format_name == "WEBP"
    assert result.mode == "RGBA"
    assert result.encoded_sample_bits == UINT8_SAMPLE_BITS


def test_webp_writer_promotes_grayscale_to_rgb(tmp_path: Path) -> None:
    frame = ImageFrame(np.array([[[0.0], [0.5], [1.0]]], dtype=np.float32))
    path = tmp_path / "gray.webp"
    result = WebpWriter().write(frame, path)
    with Image.open(path) as image:
        assert np.asarray(image).tolist() == [[[0, 0, 0], [127, 127, 127], [255, 255, 255]]]
    assert result.mode == "RGB"


def test_webp_writer_supports_explicit_lossy_mode(tmp_path: Path) -> None:
    path = tmp_path / "lossy.webp"
    result = WebpWriter(WebpOptions(lossless=False, quality=90, exact=False)).write(
        _rgba_frame(),
        path,
    )
    assert path.is_file()
    assert result.format_name == "WEBP"


@pytest.mark.parametrize(
    ("projection_factory", "expected_tier", "standard_fields"),
    [
        (build_rich_exif_projection, "rich", True),
        (build_reduced_exif_projection, "reduced", False),
    ],
)
def test_webp_writer_round_trips_exif_metadata_tiers(
    tmp_path: Path,
    projection_factory: Callable[[GenerationRecord], ExifMetadataProjection],
    expected_tier: str,
    standard_fields: bool,
) -> None:
    projection = projection_factory(complete_record())
    path = tmp_path / f"{expected_tier}.webp"
    result = WebpWriter().write(_rgba_frame(), path, projection)

    with Image.open(path) as image:
        values = exif_module.read_exif(image)
    assert values.user_comment == projection.parameters
    assert (values.software is not None) is standard_fields
    assert (values.pixel_width, values.pixel_height) == (
        (2, 2) if standard_fields else (None, None)
    )
    assert result.metadata_tier == expected_tier


def test_webp_writer_rejects_wrong_projection_type(tmp_path: Path) -> None:
    projection = PngMetadataProjection(
        tier=MetadataTier.REDUCED,
        parameters="Steps: 1",
        software="CiviScribe",
    )
    with pytest.raises(WriteError, match="webp_metadata_projection_invalid"):
        WebpWriter().write(_rgba_frame(), tmp_path / "wrong.webp", projection)


@pytest.mark.parametrize(
    ("values", "error"),
    [
        (
            ExifValues(
                user_comment="wrong",
                software="ComfyUI; CCollins' CiviScribe 2.0.0-test",
                pixel_width=2,
                pixel_height=2,
            ),
            "webp_postcheck_exif_user_comment_mismatch",
        ),
        (
            ExifValues(
                user_comment=build_rich_exif_projection(complete_record()).parameters,
                software="wrong",
                pixel_width=2,
                pixel_height=2,
            ),
            "webp_postcheck_software_mismatch",
        ),
        (
            ExifValues(
                user_comment=build_rich_exif_projection(complete_record()).parameters,
                software="ComfyUI; CCollins' CiviScribe 2.0.0-test",
                pixel_width=1,
                pixel_height=2,
            ),
            "webp_postcheck_exif_dimensions_mismatch",
        ),
        (
            ExifValues(
                user_comment=build_rich_exif_projection(complete_record()).parameters,
                software="ComfyUI; CCollins' CiviScribe 2.0.0-test",
                pixel_width=2,
                pixel_height=2,
            ),
            "webp_postcheck_exif_version_mismatch",
        ),
    ],
)
def test_webp_writer_rejects_exif_postcheck_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    values: ExifValues,
    error: str,
) -> None:
    monkeypatch.setattr(webp_module, "read_exif", lambda _image: values)
    with pytest.raises(WriteError, match=error):
        WebpWriter().write(
            _rgba_frame(),
            tmp_path / "wrong-exif.webp",
            build_rich_exif_projection(complete_record()),
        )


class _Reopened:
    def __init__(self, format_name: str, size: tuple[int, int]) -> None:
        self.format = format_name
        self.size = size
        self.width, self.height = size
        self.mode = "RGBA"

    def __enter__(self) -> _Reopened:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def load(self) -> None:
        return None


@pytest.mark.parametrize(
    ("reopened", "error"),
    [
        (_Reopened("PNG", (2, 2)), "webp_postcheck_format_mismatch"),
        (_Reopened("WEBP", (1, 1)), "webp_postcheck_dimensions_mismatch"),
    ],
)
def test_webp_writer_rejects_postcheck_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reopened: _Reopened,
    error: str,
) -> None:
    monkeypatch.setattr(Image, "open", lambda _path: reopened)
    with pytest.raises(WriteError, match=error):
        WebpWriter().write(_rgba_frame(), tmp_path / "wrong.webp")


def test_webp_writer_wraps_pillow_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Image, "fromarray", lambda _value: (_ for _ in ()).throw(ValueError))
    with pytest.raises(WriteError, match="webp_write_or_postcheck_failed"):
        WebpWriter().write(_rgba_frame(), tmp_path / "failed.webp")
