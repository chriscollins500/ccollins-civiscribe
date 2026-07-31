"""Single, explicit Pillow-boundary conversion for supported image writers."""

from __future__ import annotations

from typing import cast

import numpy as np
import numpy.typing as npt

from ..domain import ImageFrame, InvalidImageError


def encode_uint8(frame: ImageFrame) -> npt.NDArray[np.uint8]:
    """Convert normalized ComfyUI samples to unsigned 8-bit components."""

    pixels = frame.pixels
    if not np.isfinite(pixels).all():
        raise InvalidImageError("image_contains_nonfinite_values")
    if np.issubdtype(pixels.dtype, np.integer):
        encoded = np.clip(pixels, 0, 255).astype(np.uint8)
    else:
        encoded = np.clip(np.multiply(pixels, 255.0), 0.0, 255.0).astype(np.uint8)
    result = cast(npt.NDArray[np.uint8], encoded)
    if frame.channels == 1:
        return result[:, :, 0]
    return result


__all__ = ["encode_uint8"]
