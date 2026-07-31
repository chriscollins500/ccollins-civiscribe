"""Coherent parser and structured projections built from one record."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import GenerationRecord
from ..serialization import dumps_json
from .a1111 import build_a1111
from .civitai import build_civitai_manifest


@dataclass(frozen=True, slots=True)
class ProjectionBundle:
    """All phase-five metadata products for one generation record."""

    a1111_parameters: str
    civitai_manifest: dict[str, object]
    civitai_manifest_json: str


def build_projection_bundle(record: GenerationRecord) -> ProjectionBundle:
    """Build mutually consistent projections from one immutable record."""

    manifest = build_civitai_manifest(record)
    return ProjectionBundle(
        a1111_parameters=build_a1111(record),
        civitai_manifest=manifest,
        civitai_manifest_json=dumps_json(manifest),
    )


__all__ = ["ProjectionBundle", "build_projection_bundle"]
