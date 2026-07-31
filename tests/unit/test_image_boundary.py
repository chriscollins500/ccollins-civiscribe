from __future__ import annotations

from typing import cast

import numpy as np
import pytest

from civiscribe.adapters import image_frames_from_comfy
from civiscribe.domain import ImageFrame, InvalidImageError

HEIGHT = 2
WIDTH = 3
RGBA_CHANNELS = 4
BATCH_SIZE = 2


class _TensorLike:
    def __init__(self, value: np.ndarray) -> None:
        self.value = value
        self.calls: list[str] = []

    def detach(self) -> _TensorLike:
        self.calls.append("detach")
        return self

    def cpu(self) -> _TensorLike:
        self.calls.append("cpu")
        return self

    def numpy(self) -> np.ndarray:
        self.calls.append("numpy")
        return self.value


def test_image_frame_reports_shape_without_precision_conversion() -> None:
    pixels = np.zeros((HEIGHT, WIDTH, RGBA_CHANNELS), dtype=np.float16)
    frame = ImageFrame(pixels)
    assert frame.height == HEIGHT
    assert frame.width == WIDTH
    assert frame.channels == RGBA_CHANNELS
    assert frame.pixels.dtype == np.float16


@pytest.mark.parametrize(
    ("pixels", "code"),
    [
        (np.zeros((2, 3), dtype=np.float32), "image_frame_rank_invalid"),
        (np.zeros((0, 3, 3), dtype=np.float32), "image_dimensions_invalid"),
        (np.zeros((2, 3, 2), dtype=np.float32), "image_channel_count_unsupported"),
        (np.full((1, 1, 1), "x", dtype=object), "image_dtype_not_numeric"),
        (np.zeros((1, 1, 1), dtype=np.complex64), "image_dtype_complex_unsupported"),
    ],
)
def test_image_frame_rejects_unsupported_values(
    pixels: np.ndarray,
    code: str,
) -> None:
    with pytest.raises(InvalidImageError, match=code):
        ImageFrame(pixels)


def test_comfy_adapter_uses_detach_cpu_numpy_without_extra_frame_copies() -> None:
    batch = np.zeros((BATCH_SIZE, 3, 4, 3), dtype=np.float32)
    tensor = _TensorLike(batch)
    frames = image_frames_from_comfy(tensor)
    assert tensor.calls == ["detach", "cpu", "numpy"]
    assert len(frames) == BATCH_SIZE
    assert np.shares_memory(frames[0].pixels, batch)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (np.zeros((2, 3, 4), dtype=np.float32), "image_batch_rank_invalid"),
        (np.zeros((0, 2, 2, 3), dtype=np.float32), "image_batch_empty"),
        (np.zeros((1, 2, 2, 2), dtype=np.float32), "image_channel_count_unsupported"),
    ],
)
def test_comfy_adapter_rejects_invalid_batches(value: object, code: str) -> None:
    with pytest.raises(InvalidImageError, match=code):
        image_frames_from_comfy(value)


def test_comfy_adapter_rejects_noncallable_tensor_hooks() -> None:
    class BadDetach:
        detach = 1

    class BadNumpy:
        numpy = 1

    for value in (BadDetach(), BadNumpy()):
        with pytest.raises(InvalidImageError, match="image_tensor_adapter_invalid"):
            image_frames_from_comfy(cast(object, value))
