"""Adapt a current ComfyUI IMAGE batch without importing torch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

import numpy as np
import numpy.typing as npt

from ..domain import ImageFrame, InvalidImageError

BATCH_RANK = 4


class _TensorLike(Protocol):
    def detach(self) -> _TensorLike: ...

    def cpu(self) -> _TensorLike: ...

    def numpy(self) -> npt.NDArray[np.generic]: ...


def _call_if_present(value: object, name: str) -> object:
    method = getattr(value, name, None)
    if method is None:
        return value
    if not callable(method):
        raise InvalidImageError("image_tensor_adapter_invalid")
    return cast(Callable[[], object], method)()


def image_frames_from_comfy(images: object) -> tuple[ImageFrame, ...]:
    """Translate a BHWC tensor-like value into zero-extra-copy frame views."""

    adapted = _call_if_present(images, "detach")
    adapted = _call_if_present(adapted, "cpu")
    numpy_method = getattr(adapted, "numpy", None)
    if numpy_method is not None:
        if not callable(numpy_method):
            raise InvalidImageError("image_tensor_adapter_invalid")
        adapted = cast(Callable[[], Any], numpy_method)()

    batch = np.asarray(adapted)
    if batch.ndim != BATCH_RANK:
        raise InvalidImageError("image_batch_rank_invalid")
    if batch.shape[0] < 1:
        raise InvalidImageError("image_batch_empty")
    return tuple(ImageFrame(batch[index]) for index in range(batch.shape[0]))
