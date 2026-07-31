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
from civiscribe.writers import JpegOptions, JpegWriter
from civiscribe.writers import exif as exif_module
from civiscribe.writers import jpeg as jpeg_module
from civiscribe.writers.exif import ExifValues
from civiscribe.writers.jpeg import _jpeg_image
from tests.projection_support import complete_record

JPEG_ERROR_LIMIT = 3.0
UINT8_SAMPLE_BITS = 8


def _rgb_frame() -> ImageFrame:
    return ImageFrame(
        np.array(
            [
                [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
                [[0.7, 0.8, 0.9], [0.2, 0.3, 0.4]],
            ],
            dtype=np.float32,
        )
    )


def test_jpeg_writer_uses_maximum_fidelity_defaults_with_bounded_error(
    tmp_path: Path,
) -> None:
    frame = _rgb_frame()
    path = tmp_path / "image.jpg"
    result = JpegWriter().write(frame, path)

    expected = np.clip(
        np.multiply(frame.pixels, np.float32(255.0)),
        0,
        255,
    ).astype(np.uint8)
    with Image.open(path) as image:
        actual = np.asarray(image)
        assert image.info.get("exif") is None
    assert float(np.abs(actual.astype(np.int16) - expected.astype(np.int16)).mean()) < (
        JPEG_ERROR_LIMIT
    )
    assert result.format_name == "JPEG"
    assert result.mode == "RGB"
    assert result.encoded_sample_bits == UINT8_SAMPLE_BITS
    assert result.metadata_tier is None


def test_jpeg_writer_supports_grayscale(tmp_path: Path) -> None:
    result = JpegWriter().write(
        ImageFrame(np.array([[[0.0], [0.5], [1.0]]], dtype=np.float32)),
        tmp_path / "gray.jpg",
    )
    assert result.mode == "L"


def test_jpeg_alpha_is_flattened_over_explicit_background() -> None:
    frame = ImageFrame(
        np.array(
            [[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 1.0]]],
            dtype=np.float32,
        )
    )
    image = _jpeg_image(frame, JpegOptions(alpha_background=(10, 20, 30)))
    assert np.asarray(image).tolist() == [[[10, 20, 30], [0, 255, 0]]]


@pytest.mark.parametrize(
    ("projection_factory", "expected_tier", "standard_fields"),
    [
        (build_rich_exif_projection, "rich", True),
        (build_reduced_exif_projection, "reduced", False),
    ],
)
def test_jpeg_writer_round_trips_exif_metadata_tiers(
    tmp_path: Path,
    projection_factory: Callable[[GenerationRecord], ExifMetadataProjection],
    expected_tier: str,
    standard_fields: bool,
) -> None:
    projection = projection_factory(complete_record())
    path = tmp_path / f"{expected_tier}.jpg"
    result = JpegWriter().write(_rgb_frame(), path, projection)

    with Image.open(path) as image:
        values = exif_module.read_exif(image)
    assert values.user_comment == projection.parameters
    assert (values.software is not None) is standard_fields
    assert (values.pixel_width, values.pixel_height) == (
        (2, 2) if standard_fields else (None, None)
    )
    assert values.components_configuration == (
        exif_module.YCBCR_COMPONENTS_CONFIGURATION if standard_fields else None
    )
    assert values.flashpix_version == (exif_module.FLASHPIX_VERSION if standard_fields else None)
    assert values.color_space == (exif_module.COLOR_SPACE_UNCALIBRATED if standard_fields else None)
    assert values.ycbcr_positioning == (
        exif_module.YCBCR_POSITIONING_CENTERED if standard_fields else None
    )
    assert result.metadata_tier == expected_tier


def test_jpeg_writer_rejects_wrong_projection_type(tmp_path: Path) -> None:
    projection = PngMetadataProjection(
        tier=MetadataTier.REDUCED,
        parameters="Steps: 1",
        software="CiviScribe",
    )
    with pytest.raises(WriteError, match="jpeg_metadata_projection_invalid"):
        JpegWriter().write(_rgb_frame(), tmp_path / "wrong.jpg", projection)


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
            "jpeg_postcheck_exif_user_comment_mismatch",
        ),
        (
            ExifValues(
                user_comment=build_rich_exif_projection(complete_record()).parameters,
                software="wrong",
                pixel_width=2,
                pixel_height=2,
            ),
            "jpeg_postcheck_software_mismatch",
        ),
        (
            ExifValues(
                user_comment=build_rich_exif_projection(complete_record()).parameters,
                software="ComfyUI; CCollins' CiviScribe 2.0.0-test",
                pixel_width=1,
                pixel_height=2,
            ),
            "jpeg_postcheck_exif_dimensions_mismatch",
        ),
        (
            ExifValues(
                user_comment=build_rich_exif_projection(complete_record()).parameters,
                software="ComfyUI; CCollins' CiviScribe 2.0.0-test",
                pixel_width=2,
                pixel_height=2,
            ),
            "jpeg_postcheck_exif_version_mismatch",
        ),
        (
            ExifValues(
                user_comment=build_rich_exif_projection(complete_record()).parameters,
                software="ComfyUI; CCollins' CiviScribe 2.0.0-test",
                pixel_width=2,
                pixel_height=2,
                exif_version=exif_module.EXIF_VERSION,
            ),
            "jpeg_postcheck_exif_required_fields_mismatch",
        ),
    ],
)
def test_jpeg_writer_rejects_exif_postcheck_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    values: ExifValues,
    error: str,
) -> None:
    monkeypatch.setattr(jpeg_module, "read_exif", lambda _image: values)
    with pytest.raises(WriteError, match=error):
        JpegWriter().write(
            _rgb_frame(),
            tmp_path / "wrong-exif.jpg",
            build_rich_exif_projection(complete_record()),
        )


class _Reopened:
    def __init__(self, format_name: str, size: tuple[int, int], mode: str) -> None:
        self.format = format_name
        self.size = size
        self.width, self.height = size
        self.mode = mode

    def __enter__(self) -> _Reopened:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def load(self) -> None:
        return None


@pytest.mark.parametrize(
    ("reopened", "error"),
    [
        (_Reopened("PNG", (2, 2), "RGB"), "jpeg_postcheck_format_mismatch"),
        (_Reopened("JPEG", (1, 1), "RGB"), "jpeg_postcheck_dimensions_mismatch"),
        (_Reopened("JPEG", (2, 2), "CMYK"), "jpeg_postcheck_mode_mismatch"),
    ],
)
def test_jpeg_writer_rejects_postcheck_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reopened: _Reopened,
    error: str,
) -> None:
    monkeypatch.setattr(Image, "open", lambda _path: reopened)
    with pytest.raises(WriteError, match=error):
        JpegWriter().write(_rgb_frame(), tmp_path / "wrong.jpg")


def test_jpeg_writer_wraps_pillow_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Image, "fromarray", lambda _value: (_ for _ in ()).throw(ValueError))
    with pytest.raises(WriteError, match="jpeg_write_or_postcheck_failed"):
        JpegWriter().write(_rgb_frame(), tmp_path / "failed.jpg")
