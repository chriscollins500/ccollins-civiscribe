from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import numpy as np
import numpy.typing as npt
from PIL import Image

from civiscribe.domain import ImageFormat, ImageRecord
from civiscribe.projections import build_rich_exif_projection
from civiscribe.writers.exif import read_exif
from tests.projection_support import complete_record

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
JPEG_MEAN_ERROR_LIMIT = 3.0
JPEG_SIZE = (3, 2)
WEBP_SIZE = (2, 2)


def _jpeg_source() -> np.ndarray:
    return np.array(
        [
            [[0.0, 0.1, 0.2], [0.3, 0.4, 0.5], [0.6, 0.7, 0.8]],
            [[1.0, 0.9, 0.8], [0.7, 0.6, 0.5], [0.4, 0.3, 0.2]],
        ],
        dtype=np.float32,
    )


def _webp_source() -> np.ndarray:
    return np.array(
        [
            [[0.1, 0.2, 0.3, 0.0], [0.4, 0.5, 0.6, 1.0]],
            [[0.7, 0.8, 0.9, 0.5], [0.2, 0.3, 0.4, 1.0]],
        ],
        dtype=np.float32,
    )


def _projection(output_format: ImageFormat, size: tuple[int, int]) -> str:
    width, height = size
    record = complete_record()
    record = replace(
        record,
        settings=replace(record.settings, width=width, height=height),
        image=ImageRecord(output_format, width, height),
    )
    return build_rich_exif_projection(record).parameters


def _uint8(values: np.ndarray) -> npt.NDArray[np.uint8]:
    encoded = np.clip(np.multiply(values, np.float32(255.0)), 0, 255).astype(np.uint8)
    return cast(npt.NDArray[np.uint8], encoded)


def test_jpeg_golden_preserves_maximum_fidelity_and_rich_exif() -> None:
    with Image.open(GOLDEN / "jpeg" / "rich_reference.jpg") as image:
        image.load()
        decoded = np.asarray(image)
        exif = read_exif(image)
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == JPEG_SIZE

    expected = _uint8(_jpeg_source())
    mean_error = float(np.abs(decoded.astype(np.int16) - expected.astype(np.int16)).mean())
    assert mean_error < JPEG_MEAN_ERROR_LIMIT
    assert exif.user_comment == _projection(ImageFormat.JPEG, JPEG_SIZE)
    assert exif.software == "ComfyUI; CCollins' CiviScribe 2.0.0-test"
    assert (exif.pixel_width, exif.pixel_height) == JPEG_SIZE


def test_lossless_webp_golden_preserves_exact_rgba_and_rich_exif() -> None:
    with Image.open(GOLDEN / "webp" / "rich_rgba_reference.webp") as image:
        image.load()
        decoded = np.asarray(image)
        exif = read_exif(image)
        assert image.format == "WEBP"
        assert image.mode == "RGBA"
        assert image.size == WEBP_SIZE

    assert np.array_equal(decoded, _uint8(_webp_source()))
    assert exif.user_comment == _projection(ImageFormat.WEBP, WEBP_SIZE)
    assert exif.software == "ComfyUI; CCollins' CiviScribe 2.0.0-test"
    assert (exif.pixel_width, exif.pixel_height) == WEBP_SIZE
