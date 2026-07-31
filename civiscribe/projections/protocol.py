"""Shared metadata projection contracts for image writers."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class MetadataTier(StrEnum):
    """Pixels-first metadata fallback levels shared by every image format."""

    RICH = "rich"
    REDUCED = "reduced"


class WriterMetadata(Protocol):
    """Minimum immutable metadata surface consumed by an image writer."""

    @property
    def tier(self) -> MetadataTier: ...

    @property
    def warning_codes(self) -> tuple[str, ...]: ...


__all__ = ["MetadataTier", "WriterMetadata"]
