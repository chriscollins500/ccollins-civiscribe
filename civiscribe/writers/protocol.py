"""Shared writer protocols and result types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..domain import ImageFormat, ImageFrame
from ..projections import WriterMetadata


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Verified facts about a temporary image artifact."""

    format_name: str
    width: int
    height: int
    mode: str
    encoded_sample_bits: int
    metadata_tier: str | None = None


class ImageWriter(Protocol):
    """One configured still-image writer selected by the application layer."""

    output_format: ImageFormat
    format_name: str
    extension: str

    def write(
        self,
        frame: ImageFrame,
        destination: Path,
        metadata: WriterMetadata | None = None,
    ) -> WriteResult: ...


__all__ = ["ImageWriter", "WriteResult"]
