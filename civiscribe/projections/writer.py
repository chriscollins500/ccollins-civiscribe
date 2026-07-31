"""Format-aware metadata projection dispatch."""

from __future__ import annotations

from ..domain import GenerationRecord, ImageFormat
from .exif import (
    ExifMetadataProjection,
    build_reduced_exif_projection,
    build_rich_exif_projection,
)
from .png import (
    PngMetadataProjection,
    build_reduced_png_projection,
    build_rich_png_projection,
)

type ImageMetadataProjection = PngMetadataProjection | ExifMetadataProjection


def build_reduced_writer_projection(
    record: GenerationRecord,
    output_format: ImageFormat,
) -> ImageMetadataProjection:
    """Build the reduced projection supported by the selected container."""

    if output_format is ImageFormat.PNG:
        return build_reduced_png_projection(record)
    return build_reduced_exif_projection(record)


def build_rich_writer_projection(  # noqa: PLR0913 - explicit projection policy is cohesive.
    record: GenerationRecord,
    output_format: ImageFormat,
    *,
    prompt: object,
    workflow: object | None,
    include_workflow: bool = True,
    include_civitai_manifest: bool = True,
) -> ImageMetadataProjection:
    """Build the richest truthful projection supported by the container."""

    if output_format is ImageFormat.PNG:
        return build_rich_png_projection(
            record,
            prompt=prompt,
            workflow=workflow,
            include_workflow=include_workflow,
            include_civitai_manifest=include_civitai_manifest,
        )
    return build_rich_exif_projection(record)


__all__ = [
    "ImageMetadataProjection",
    "build_reduced_writer_projection",
    "build_rich_writer_projection",
]
