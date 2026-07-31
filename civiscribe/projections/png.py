"""Exact logical metadata carriers for normal PNG output."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import GenerationRecord, SerializationError
from ..security import sanitize_metadata_json
from ..serialization import dumps_json
from .a1111 import build_a1111
from .civitai import build_civitai_manifest
from .protocol import MetadataTier
from .sanitize import metadata_text

MAX_PARAMETERS_CHARS = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PngMetadataProjection:
    """Strings consumed by the PNG writer without graph or identity work."""

    tier: MetadataTier
    parameters: str
    software: str
    prompt_json: str | None = None
    workflow_json: str | None = None
    civitai_json: str | None = None
    exif_user_comment: str | None = None
    warning_codes: tuple[str, ...] = ()


def _parameters(record: GenerationRecord) -> str:
    value = metadata_text(build_a1111(record)) or ""
    if len(value) > MAX_PARAMETERS_CHARS:
        raise SerializationError("parameters_output_too_large")
    return value


def _software(record: GenerationRecord) -> str:
    return f"ComfyUI; {record.generator.name} {record.generator.version}"


def _json_carrier(value: object) -> tuple[str, bool]:
    sanitized = sanitize_metadata_json(value)
    return dumps_json(sanitized.value), sanitized.redaction_count > 0


def build_reduced_png_projection(record: GenerationRecord) -> PngMetadataProjection:
    """Build the parser-compatible tEXt-only fallback."""

    return PngMetadataProjection(
        tier=MetadataTier.REDUCED,
        parameters=_parameters(record),
        software=_software(record),
    )


def build_rich_png_projection(
    record: GenerationRecord,
    *,
    prompt: object,
    workflow: object | None,
    include_workflow: bool = True,
    include_civitai_manifest: bool = True,
) -> PngMetadataProjection:
    """Build normal PNG tEXt/iTXt/eXIf values from one canonical record."""

    parameters = _parameters(record)
    prompt_json, prompt_redacted = _json_carrier(prompt)
    workflow_json: str | None = None
    workflow_redacted = False
    if include_workflow and workflow is not None:
        workflow_json, workflow_redacted = _json_carrier(workflow)

    civitai_json: str | None = None
    if include_civitai_manifest:
        manifest = build_civitai_manifest(record)
        manifest["workflowRefs"] = {
            "prompt": "pnginfo:prompt",
            "workflow": "pnginfo:workflow" if workflow_json is not None else None,
        }
        civitai_json = dumps_json(manifest)

    warning_codes = (
        ("embedded_metadata_private_values_redacted",)
        if prompt_redacted or workflow_redacted
        else ()
    )
    return PngMetadataProjection(
        tier=MetadataTier.RICH,
        parameters=parameters,
        software=_software(record),
        prompt_json=prompt_json,
        workflow_json=workflow_json,
        civitai_json=civitai_json,
        exif_user_comment=parameters,
        warning_codes=warning_codes,
    )


__all__ = [
    "MAX_PARAMETERS_CHARS",
    "PngMetadataProjection",
    "build_reduced_png_projection",
    "build_rich_png_projection",
]
