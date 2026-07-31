from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from civiscribe.domain import ImageFrame, InvalidImageError, WriteError
from civiscribe.projections import ExifMetadataProjection, MetadataTier
from civiscribe.writers.png import PngWriter

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "png"
PNG_SAMPLE_BITS = 8


@pytest.mark.parametrize("name", ["rgb_reference.png", "rgba_reference.png"])
def test_writer_matches_golden_decoded_pixels(name: str, tmp_path: Path) -> None:
    with Image.open(GOLDEN / name) as reference:
        expected = np.asarray(reference).copy()
        expected_mode = reference.mode
    normalized = expected.astype(np.float32) / 255.0
    destination = tmp_path / name
    result = PngWriter().write(ImageFrame(normalized), destination)
    with Image.open(destination) as written:
        actual = np.asarray(written)
        assert written.info == {}
    assert np.array_equal(actual, expected)
    assert result.format_name == "PNG"
    assert result.mode == expected_mode
    assert result.encoded_sample_bits == PNG_SAMPLE_BITS


def test_writer_supports_single_channel_frame(tmp_path: Path) -> None:
    frame = ImageFrame(np.array([[[0.0], [0.5], [1.0]]], dtype=np.float32))
    result = PngWriter().write(frame, tmp_path / "gray.png")
    assert result.mode == "L"


def test_writer_accepts_integer_samples_without_rescaling(tmp_path: Path) -> None:
    frame = ImageFrame(np.array([[[0, 127, 300]]], dtype=np.int16))
    path = tmp_path / "integer.png"
    PngWriter().write(frame, path)
    with Image.open(path) as image:
        assert np.asarray(image).tolist() == [[[0, 127, 255]]]


def test_writer_rejects_nonfinite_pixels(tmp_path: Path) -> None:
    frame = ImageFrame(np.array([[[np.nan, 0.0, 0.0]]], dtype=np.float32))
    with pytest.raises(InvalidImageError, match="image_contains_nonfinite_values"):
        PngWriter().write(frame, tmp_path / "bad.png")


def test_writer_rejects_wrong_projection_type(tmp_path: Path) -> None:
    projection = ExifMetadataProjection(
        tier=MetadataTier.REDUCED,
        parameters="Steps: 1",
    )
    with pytest.raises(WriteError, match="png_metadata_projection_invalid"):
        PngWriter().write(
            ImageFrame(np.zeros((1, 1, 3), dtype=np.float32)),
            tmp_path / "wrong.png",
            projection,
        )


class _Reopened:
    def __init__(self, *, format_name: str, size: tuple[int, int]) -> None:
        self.format = format_name
        self.size = size
        self.width, self.height = size
        self.mode = "RGB"

    def __enter__(self) -> _Reopened:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def load(self) -> None:
        return None


def test_writer_rejects_postcheck_format_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Image, "open", lambda _: _Reopened(format_name="JPEG", size=(1, 1)))
    frame = ImageFrame(np.zeros((1, 1, 3), dtype=np.float32))
    with pytest.raises(WriteError, match="png_postcheck_format_mismatch"):
        PngWriter().write(frame, tmp_path / "wrong.png")


def test_writer_rejects_postcheck_dimension_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Image, "open", lambda _: _Reopened(format_name="PNG", size=(2, 2)))
    frame = ImageFrame(np.zeros((1, 1, 3), dtype=np.float32))
    with pytest.raises(WriteError, match="png_postcheck_dimensions_mismatch"):
        PngWriter().write(frame, tmp_path / "wrong.png")


def test_writer_wraps_pillow_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        Image,
        "fromarray",
        lambda _: (_ for _ in ()).throw(ValueError),
    )
    frame = ImageFrame(np.zeros((1, 1, 3), dtype=np.float32))
    with pytest.raises(WriteError, match="png_write_or_postcheck_failed"):
        PngWriter().write(frame, tmp_path / "failed.png")
