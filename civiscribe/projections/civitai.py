"""Lean structured Civitai manifest projected from canonical generation facts."""

from __future__ import annotations

from ..domain import (
    GenerationRecord,
    IssueSeverity,
    ResourceStatus,
    ScanIssue,
    WorkflowKind,
)
from ..serialization import dumps_json
from .display import display_sampler, display_scheduler
from .resources import (
    a1111_hashes,
    compatibility_hash,
    parser_resource_items,
    resource_by_key,
    resource_manifest_item,
    structured_hashes,
)
from .sanitize import metadata_scalar, metadata_text, resource_filename

SCHEMA_NAME = "ccollins-civiscribe.civitai-manifest"
SCHEMA_VERSION = "1.0.0"


def _issue_json(issue: ScanIssue) -> dict[str, str]:
    result = {
        "code": metadata_scalar(issue.code) or "metadata_issue",
        "severity": issue.severity.value,
    }
    if (node_id := metadata_scalar(issue.node_id)) is not None:
        result["nodeId"] = node_id
    if (input_name := metadata_scalar(issue.input_name)) is not None:
        result["inputName"] = input_name
    return result


def _projection_issues(record: GenerationRecord) -> tuple[ScanIssue, ...]:
    issues: list[ScanIssue] = []
    if (
        record.primary_resource_key is not None
        and resource_by_key(record, record.primary_resource_key) is None
    ):
        issues.append(ScanIssue("primary_resource_key_invalid"))
    if (
        record.selected_vae_resource_key is not None
        and resource_by_key(record, record.selected_vae_resource_key) is None
    ):
        issues.append(ScanIssue("selected_vae_resource_key_invalid"))
    for resource in record.resources:
        if resource.status is ResourceStatus.RESOLVED and resource.identity is None:
            issues.append(ScanIssue("resolved_resource_identity_missing", node_id=resource.node_id))
        elif resource.status is ResourceStatus.CONFLICT:
            issues.append(ScanIssue("resource_identity_conflict", node_id=resource.node_id))
        elif resource.status is not ResourceStatus.RESOLVED:
            issues.append(ScanIssue("resource_identity_incomplete", node_id=resource.node_id))
        if not resource.hashes.is_empty and not structured_hashes(resource.hashes):
            issues.append(ScanIssue("resource_hashes_invalid", node_id=resource.node_id))
    return tuple(issues)


def _deduplicated_issues(record: GenerationRecord) -> tuple[ScanIssue, ...]:
    result: list[ScanIssue] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for issue in (*record.diagnostics.all_issues, *_projection_issues(record)):
        key = (issue.code, issue.severity.value, issue.node_id, issue.input_name)
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return tuple(result)


def _metadata_status(record: GenerationRecord, issues: tuple[ScanIssue, ...]) -> str:
    if any(issue.severity is IssueSeverity.ERROR for issue in issues):
        return "failed"
    if issues or any(
        resource.status is not ResourceStatus.RESOLVED for resource in record.resources
    ):
        return "partial"
    return "complete"


def _resource_name_and_hash(
    record: GenerationRecord,
    key: str | None,
) -> tuple[str | None, str | None]:
    resource = resource_by_key(record, key)
    if resource is None:
        return None, None
    return resource_filename(resource.filename), compatibility_hash(resource.hashes)


def build_civitai_manifest(record: GenerationRecord) -> dict[str, object]:
    """Build a deterministic JSON-compatible manifest without side effects."""

    issues = _deduplicated_issues(record)
    warnings = [_issue_json(issue) for issue in issues if issue.severity is IssueSeverity.WARNING]
    errors = [_issue_json(issue) for issue in issues if issue.severity is IssueSeverity.ERROR]
    model_name, model_hash = _resource_name_and_hash(record, record.primary_resource_key)
    vae_name, vae_hash = _resource_name_and_hash(record, record.selected_vae_resource_key)
    resources = [
        resource_manifest_item(resource) for resource in record.resources if resource.active
    ]
    unresolved = [
        resource_manifest_item(resource)
        for resource in record.resources
        if resource.active and resource.status is not ResourceStatus.RESOLVED
    ]
    return {
        "schemaName": SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "generator": {
            "name": metadata_scalar(record.generator.name),
            "version": metadata_scalar(record.generator.version),
            "comfyuiVersion": metadata_scalar(record.generator.comfyui_version),
        },
        "prompt": {
            "positive": metadata_text(record.prompts.positive.text),
            "negative": metadata_text(record.prompts.negative.text),
            "positiveBranchPresent": record.prompts.positive.branch_present,
            "negativeBranchPresent": record.prompts.negative.branch_present,
        },
        "generation": {
            "workflowType": record.workflow_kind.value
            if record.workflow_kind is not None
            else None,
            "seed": record.settings.seed,
            "steps": record.settings.steps,
            "sampler": display_sampler(record.settings.sampler),
            "scheduler": display_scheduler(record.settings.scheduler),
            "cfgScale": record.settings.cfg_scale,
            "guidance": record.settings.guidance,
            "denoise": (
                record.settings.denoise if record.workflow_kind is WorkflowKind.IMG2IMG else None
            ),
            "width": record.image.width,
            "height": record.image.height,
            "batchSize": record.settings.batch_size,
            "batchIndex": record.image.batch_index,
            "clipSkip": record.settings.clip_skip,
            "model": model_name,
            "modelHash": model_hash,
            "vae": vae_name,
            "vaeHash": vae_hash,
        },
        "image": {
            "format": record.image.format.value,
            "width": record.image.width,
            "height": record.image.height,
            "batchIndex": record.image.batch_index,
        },
        "resources": resources,
        "unresolvedResources": unresolved,
        "civitaiResources": parser_resource_items(record.resources),
        "hashes": a1111_hashes(record),
        "primaryResourceKey": metadata_scalar(record.primary_resource_key),
        "selectedVaeResourceKey": metadata_scalar(record.selected_vae_resource_key),
        "workflowRefs": {
            "prompt": "pnginfo:prompt",
            "workflow": "pnginfo:workflow",
        },
        "metadataStatus": _metadata_status(record, issues),
        "validation": {
            "warnings": warnings,
            "errors": errors,
        },
    }


def build_civitai_manifest_json(record: GenerationRecord) -> str:
    """Serialize the structured manifest through the sole strict encoder."""

    return dumps_json(build_civitai_manifest(record))


__all__ = [
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "build_civitai_manifest",
    "build_civitai_manifest_json",
]
