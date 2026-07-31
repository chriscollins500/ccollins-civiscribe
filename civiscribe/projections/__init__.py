"""Deterministic metadata projections from one canonical generation record."""

from .a1111 import build_a1111
from .bundle import ProjectionBundle, build_projection_bundle
from .civitai import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    build_civitai_manifest,
    build_civitai_manifest_json,
)
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
from .protocol import MetadataTier, WriterMetadata
from .sidecar import (
    SidecarArtifact,
    SidecarPolicy,
    SidecarProjection,
    build_sidecar_projection,
)
from .writer import (
    ImageMetadataProjection,
    build_reduced_writer_projection,
    build_rich_writer_projection,
)

__all__ = [
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "ExifMetadataProjection",
    "ImageMetadataProjection",
    "MetadataTier",
    "PngMetadataProjection",
    "ProjectionBundle",
    "SidecarArtifact",
    "SidecarPolicy",
    "SidecarProjection",
    "WriterMetadata",
    "build_a1111",
    "build_civitai_manifest",
    "build_civitai_manifest_json",
    "build_projection_bundle",
    "build_reduced_exif_projection",
    "build_reduced_png_projection",
    "build_reduced_writer_projection",
    "build_rich_exif_projection",
    "build_rich_png_projection",
    "build_rich_writer_projection",
    "build_sidecar_projection",
]
