"""A1111-compatible EXIF projections for JPEG and WebP."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import GenerationRecord, SerializationError
from .a1111 import build_a1111
from .png import MAX_PARAMETERS_CHARS
from .protocol import MetadataTier
from .sanitize import metadata_text


@dataclass(frozen=True, slots=True)
class ExifMetadataProjection:
    """Truthful fields consumed by the JPEG and WebP EXIF writers."""

    tier: MetadataTier
    parameters: str
    software: str | None = None
    write_dimensions: bool = False
    warning_codes: tuple[str, ...] = ()


def _parameters(record: GenerationRecord) -> str:
    value = metadata_text(build_a1111(record)) or ""
    if len(value) > MAX_PARAMETERS_CHARS:
        raise SerializationError("parameters_output_too_large")
    return value


def _software(record: GenerationRecord) -> str:
    return f"ComfyUI; {record.generator.name} {record.generator.version}"


def build_reduced_exif_projection(record: GenerationRecord) -> ExifMetadataProjection:
    """Build the smallest parser-compatible EXIF fallback."""

    return ExifMetadataProjection(
        tier=MetadataTier.REDUCED,
        parameters=_parameters(record),
    )


def build_rich_exif_projection(record: GenerationRecord) -> ExifMetadataProjection:
    """Build normal EXIF fields without inventing camera or provenance data."""

    return ExifMetadataProjection(
        tier=MetadataTier.RICH,
        parameters=_parameters(record),
        software=_software(record),
        write_dimensions=True,
    )


__all__ = [
    "ExifMetadataProjection",
    "build_reduced_exif_projection",
    "build_rich_exif_projection",
]
