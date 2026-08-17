"""Lean deterministic sidecar projection from one canonical generation record."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ..domain import (
    GenerationRecord,
    ImageFormat,
    PromptField,
    ResourceRecord,
    ScanIssue,
)
from ..security import sanitize_metadata_json
from ..serialization import dumps_json
from .a1111 import build_a1111
from .civitai import build_civitai_manifest
from .resources import resource_manifest_item, structured_hashes
from .sanitize import metadata_scalar, metadata_text

SCHEMA_NAME = "ccollins-civiscribe.sidecar"
SCHEMA_VERSION = "2.0.0"
_HASH_NAMES = ("AutoV1", "AutoV2", "AutoV3", "SHA256", "CRC32", "BLAKE3")
_MIME_TYPES = {
    ImageFormat.PNG: "image/png",
    ImageFormat.JPEG: "image/jpeg",
    ImageFormat.WEBP: "image/webp",
}
_FORMAT_EXTENSIONS = {
    ImageFormat.PNG: {".png"},
    ImageFormat.JPEG: {".jpg", ".jpeg"},
    ImageFormat.WEBP: {".webp"},
}
_METADATA_STATUSES = {"complete", "partial", "minimal"}
RGBA_CHANNELS = 4


@dataclass(frozen=True, slots=True)
class SidecarArtifact:
    """Verified committed-image facts used by the sidecar projection."""

    filename: str
    sidecar_filename: str
    subfolder: str
    output_format: ImageFormat
    width: int
    height: int
    batch_index: int
    mode: str
    channels: int
    incoming_tensor_dtype: str
    encoded_sample_bits: int
    file_size_bytes: int
    metadata_status: str

    def __post_init__(self) -> None:
        for value in (self.filename, self.sidecar_filename):
            if not value or value in {".", ".."} or "/" in value or "\\" in value:
                raise ValueError("sidecar_artifact_filename_invalid")
        image_path = PurePosixPath(self.filename)
        sidecar_path = PurePosixPath(self.sidecar_filename)
        if image_path.suffix.casefold() not in _FORMAT_EXTENSIONS[self.output_format]:
            raise ValueError("sidecar_artifact_format_extension_mismatch")
        if sidecar_path.suffix.casefold() != ".json" or sidecar_path.stem != image_path.stem:
            raise ValueError("sidecar_artifact_filename_mismatch")
        if self.subfolder:
            path = PurePosixPath(self.subfolder.replace("\\", "/"))
            if (
                ":" in self.subfolder
                or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise ValueError("sidecar_artifact_subfolder_invalid")
        if self.width < 1 or self.height < 1 or self.batch_index < 0:
            raise ValueError("sidecar_artifact_dimensions_invalid")
        if self.channels not in {1, 3, 4}:
            raise ValueError("sidecar_artifact_channels_invalid")
        if self.encoded_sample_bits < 1 or self.file_size_bytes < 1:
            raise ValueError("sidecar_artifact_encoding_invalid")
        if self.metadata_status not in _METADATA_STATUSES:
            raise ValueError("sidecar_metadata_status_invalid")


@dataclass(frozen=True, slots=True)
class SidecarProjection:
    """Strict JSON-compatible sidecar payload plus serialized bytes."""

    payload: dict[str, object]
    json_text: str
    warning_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SidecarPolicy:
    """Payload inclusion policy and prior sanitized transaction warnings."""

    prompt: object | None = None
    workflow: object | None = None
    include_workflow: bool = True
    include_civitai_manifest: bool = True
    save_warnings: tuple[tuple[str, int | None], ...] = ()


def _issue(issue: ScanIssue) -> dict[str, object]:
    return {
        "code": metadata_scalar(issue.code) or "metadata_issue",
        "severity": issue.severity.value,
        "nodeId": metadata_scalar(issue.node_id),
        "inputName": metadata_scalar(issue.input_name),
    }


def _prompt_field(field: PromptField) -> dict[str, object]:
    return {
        "text": metadata_text(field.text),
        "branchPresent": field.branch_present,
        "sourceNodeIds": [
            safe for value in field.source_node_ids if (safe := metadata_scalar(value)) is not None
        ],
        "candidates": [
            safe for value in field.candidates if (safe := metadata_text(value)) is not None
        ],
    }


def _resource(resource: ResourceRecord) -> dict[str, object]:
    item = resource_manifest_item(resource)
    known_hashes = structured_hashes(resource.hashes)
    item["hashes"] = {name: known_hashes.get(name) for name in _HASH_NAMES}
    return item


def _generation_record(record: GenerationRecord) -> dict[str, object]:
    settings = record.settings
    return {
        "generator": {
            "name": metadata_scalar(record.generator.name),
            "version": metadata_scalar(record.generator.version),
            "comfyuiVersion": metadata_scalar(record.generator.comfyui_version),
        },
        "image": {
            "format": record.image.format.value,
            "width": record.image.width,
            "height": record.image.height,
            "batchIndex": record.image.batch_index,
        },
        "workflowType": record.workflow_kind.value if record.workflow_kind is not None else None,
        "prompts": {
            "positive": _prompt_field(record.prompts.positive),
            "negative": _prompt_field(record.prompts.negative),
        },
        "settings": {
            "seed": settings.seed,
            "steps": settings.steps,
            "sampler": metadata_scalar(settings.sampler),
            "scheduler": metadata_scalar(settings.scheduler),
            "cfgScale": settings.cfg_scale,
            "guidance": settings.guidance,
            "denoise": settings.denoise,
            "width": settings.width,
            "height": settings.height,
            "batchSize": settings.batch_size,
            "clipSkip": settings.clip_skip,
        },
        "resources": [_resource(resource) for resource in record.resources],
        "primaryResourceKey": metadata_scalar(record.primary_resource_key),
        "selectedVaeResourceKey": metadata_scalar(record.selected_vae_resource_key),
        "diagnostics": {
            "warnings": [_issue(issue) for issue in record.diagnostics.warnings],
            "errors": [_issue(issue) for issue in record.diagnostics.errors],
        },
    }


def _warning_items(
    values: tuple[tuple[str, int | None], ...],
    *,
    extra_codes: tuple[str, ...],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[tuple[str, int | None]] = set()
    for raw_code, batch_index in (
        *values,
        *((code, None) for code in extra_codes),
    ):
        code = metadata_scalar(raw_code) or "save_warning"
        key = (code, batch_index)
        if key in seen:
            continue
        seen.add(key)
        result.append({"code": code, "batchIndex": batch_index})
    return result


def _artifact(artifact: SidecarArtifact) -> dict[str, object]:
    converted = artifact.incoming_tensor_dtype.casefold() != "uint8"
    return {
        "fileName": artifact.filename,
        "sidecarFileName": artifact.sidecar_filename,
        "subfolder": artifact.subfolder or None,
        "format": artifact.output_format.value,
        "mimeType": _MIME_TYPES[artifact.output_format],
        "width": artifact.width,
        "height": artifact.height,
        "batchIndex": artifact.batch_index,
        "mode": metadata_scalar(artifact.mode),
        "channels": artifact.channels,
        "hasAlpha": artifact.channels == RGBA_CHANNELS,
        "incomingTensorDtype": metadata_scalar(artifact.incoming_tensor_dtype),
        "declaredSourceBitDepth": None,
        "measuredEffectiveBitDepth": None,
        "encodedSampleBits": artifact.encoded_sample_bits,
        "precisionConverted": converted,
        "precisionConversionReason": "pillow_writer_boundary" if converted else None,
        "fileSizeBytes": artifact.file_size_bytes,
        "metadataStatus": artifact.metadata_status,
    }


def build_sidecar_projection(
    record: GenerationRecord | None,
    artifact: SidecarArtifact,
    policy: SidecarPolicy | None = None,
) -> SidecarProjection:
    """Build one bounded sidecar without duplicating prompt or workflow payloads."""

    active_policy = policy or SidecarPolicy()
    sanitized_prompt = sanitize_metadata_json(
        active_policy.prompt if active_policy.include_workflow else None
    )
    sanitized_workflow = sanitize_metadata_json(
        active_policy.workflow if active_policy.include_workflow else None
    )
    redaction_count = sanitized_prompt.redaction_count + sanitized_workflow.redaction_count
    warning_codes = ("sidecar_payload_private_values_redacted",) if redaction_count else ()

    parameters: str | None = None
    civitai: dict[str, object] | None = None
    generation_record: dict[str, object] | None = None
    if record is not None:
        generation_record = _generation_record(record)
        parameters = metadata_text(build_a1111(record))
        if active_policy.include_civitai_manifest:
            civitai = build_civitai_manifest(record)
            civitai["workflowRefs"] = {
                "prompt": "#/payloads/prompt" if sanitized_prompt.value is not None else None,
                "workflow": "#/payloads/workflow"
                if active_policy.include_workflow and active_policy.workflow is not None
                else None,
            }

    payload: dict[str, object] = {
        "schemaName": SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "artifact": _artifact(artifact),
        "generationRecord": generation_record,
        "payloads": {
            "prompt": sanitized_prompt.value,
            "workflow": sanitized_workflow.value,
        },
        "projections": {
            "parameters": parameters,
            "civitai": civitai,
        },
        "save": {
            "sidecarStatus": "written",
            "payloadRedactionCount": redaction_count,
            "warnings": _warning_items(
                active_policy.save_warnings,
                extra_codes=warning_codes,
            ),
        },
    }
    return SidecarProjection(
        payload=payload,
        json_text=dumps_json(payload),
        warning_codes=warning_codes,
    )


__all__ = [
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "SidecarArtifact",
    "SidecarPolicy",
    "SidecarProjection",
    "build_sidecar_projection",
]
