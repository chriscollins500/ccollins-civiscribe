"""Image values retained at incoming precision until a writer boundary."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from .errors import InvalidImageError

FRAME_RANK = 3


@dataclass(frozen=True, slots=True)
class ImageFrame:
    """One HWC image frame backed by a numeric NumPy array."""

    pixels: npt.NDArray[np.generic]

    def __post_init__(self) -> None:
        if self.pixels.ndim != FRAME_RANK:
            raise InvalidImageError("image_frame_rank_invalid")
        height, width, channels = self.pixels.shape
        if height < 1 or width < 1:
            raise InvalidImageError("image_dimensions_invalid")
        if channels not in {1, 3, 4}:
            raise InvalidImageError("image_channel_count_unsupported")
        if not np.issubdtype(self.pixels.dtype, np.number):
            raise InvalidImageError("image_dtype_not_numeric")
        if np.issubdtype(self.pixels.dtype, np.complexfloating):
            raise InvalidImageError("image_dtype_complex_unsupported")

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def channels(self) -> int:
        return int(self.pixels.shape[2])
