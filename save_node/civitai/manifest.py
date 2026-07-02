"""Structured Civitai manifest builder."""

from __future__ import annotations

from dataclasses import replace

from ..version import __version__
from ..metadata.schema import (
    CivitaiManifest,
    GenerationSettings,
    GeneratorMetadata,
    HashMetadata,
    IdentityCacheMetadata,
    PromptMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationResult,
    WorkflowRefs,
)


def build_civitai_manifest(
    *,
    prompt: PromptMetadata,
    generation: GenerationSettings,
    resources: tuple[ResolvedResource, ...],
    unresolved_resources: tuple[UnresolvedResource, ...],
    hashes: HashMetadata,
    validation: ValidationResult,
    include_workflow: bool,
    generator: GeneratorMetadata | None = None,
    identity_cache: IdentityCacheMetadata | None = None,
    metadata_status: str = "complete",
    save_warnings: tuple = (),
    lookup_debug_summary: tuple = (),
) -> CivitaiManifest:
    manifest_generator = generator or GeneratorMetadata()
    manifest_generator = replace(manifest_generator, version=__version__)
    return CivitaiManifest(
        prompt=prompt,
        generation=generation,
        resources=resources,
        unresolved_resources=unresolved_resources,
        hashes=hashes,
        validation=validation,
        generator=manifest_generator,
        identity_cache=identity_cache or IdentityCacheMetadata(),
        metadata_status=metadata_status,
        save_warnings=save_warnings,
        lookup_debug_summary=lookup_debug_summary,
        workflow_refs=WorkflowRefs(
            prompt="pnginfo:prompt",
            workflow="pnginfo:workflow" if include_workflow else None,
        ),
    )


def build_phase_one_manifest(*, validation: ValidationResult) -> CivitaiManifest:
    """Legacy compatibility wrapper for older external callers."""

    return build_civitai_manifest(
        prompt=PromptMetadata(),
        generation=GenerationSettings(),
        resources=(),
        unresolved_resources=(),
        hashes=HashMetadata(),
        validation=validation,
        include_workflow=True,
    )


__all__ = ["build_civitai_manifest", "build_phase_one_manifest"]
