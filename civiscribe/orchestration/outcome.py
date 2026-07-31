"""Privacy-safe result of a save transaction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..domain import ImageFormat


class SidecarStatus(StrEnum):
    """Outcome of the optional post-image sidecar stage."""

    NOT_REQUESTED = "not_requested"
    WRITTEN = "written"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SavedImage:
    filename: str
    subfolder: str
    output_format: ImageFormat
    width: int
    height: int
    metadata_status: str
    sidecar_status: SidecarStatus = SidecarStatus.NOT_REQUESTED
    sidecar_filename: str | None = None


@dataclass(frozen=True, slots=True)
class SaveWarning:
    code: str
    batch_index: int | None = None


@dataclass(frozen=True, slots=True)
class SaveOutcome:
    saved_images: tuple[SavedImage, ...]
    warnings: tuple[SaveWarning, ...]


__all__ = [
    "SaveOutcome",
    "SaveWarning",
    "SavedImage",
    "SidecarStatus",
]
