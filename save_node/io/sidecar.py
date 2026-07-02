"""Optional sidecar JSON output."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .paths import safe_sidecar_path
from .png_writer import parameters_text_needs_latin1_fallback
from ..metadata.schema import (
    CivitaiManifest,
    MetadataOptions,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
    ValidationResult,
)
from ..metadata.serialize import sanitize_for_json, to_json_text
from ..security.redaction import sanitize_metadata_text
from ..version import __version__


SIDECAR_FORMAT = "comfyui-civitai-save-node.sidecar"
SIDECAR_SCHEMA_VERSION = "1.0.0"
SIDECAR_SCHEMA_URL = "https://github.com/comfyui-civitai-save-node/comfyui-civitai-save-node/schemas/comfyui-civitai-save-node-sidecar.schema.json"


def build_sidecar_payload(
    *,
    image: Mapping[str, Any],
    options: MetadataOptions,
    prompt: Any | None,
    extra_pnginfo: dict[str, Any],
    civitai_manifest: CivitaiManifest | None,
    validation: ValidationResult,
    resource_lifecycle: dict[str, Any] | None = None,
    a1111_parameters: str = "",
    manual_identities_enabled: bool = False,
    manual_identities_entry_count: int = 0,
    exif_user_comment: bool = True,
) -> dict[str, Any]:
    lifecycle = _normalize_resource_lifecycle(resource_lifecycle or {})
    civitai_json = _manifest_json(civitai_manifest)
    settings = _settings_json(
        options,
        manual_identities_enabled=manual_identities_enabled,
        manual_identities_entry_count=manual_identities_entry_count,
    )
    warnings = _issues_with_severity(validation.warnings)
    errors = _issues_with_severity(validation.errors, severity="error")
    payload: dict[str, Any] = {
        "$schema": SIDECAR_SCHEMA_URL,
        "sidecarFormat": SIDECAR_FORMAT,
        "sidecarSchemaVersion": SIDECAR_SCHEMA_VERSION,
        "generator": {
            "name": "Save Image with Civitai Metadata",
            "package": "comfyui-civitai-save-node",
            "version": __version__,
        },
        "createdAt": _utc_now_rfc3339(),
        "image": _image_json(image),
        "pngMetadata": _png_metadata_summary(
            include_prompt=prompt is not None,
            include_workflow=bool(options.include_workflow and "workflow" in (extra_pnginfo or {})),
            include_civitai=civitai_manifest is not None,
            unicode_fallback=parameters_text_needs_latin1_fallback(a1111_parameters),
            exif_minimal=options.civitai_exif_minimal,
            exif_user_comment=exif_user_comment,
        ),
        "a1111": {
            "parameters": sanitize_metadata_text(a1111_parameters),
            "unicodeFallbackApplied": parameters_text_needs_latin1_fallback(a1111_parameters),
            "compatibilityTarget": "A1111/Civitai-style parameters parser",
        },
        "civitai": civitai_json,
        "resources": _resources_summary(civitai_json, lifecycle),
        "resourceLifecycle": lifecycle,
        "lookupDiagnostics": _lookup_diagnostics(civitai_json, settings),
        "settings": settings,
        "warnings": warnings,
        "errors": errors,
        "privacy": _privacy_json(settings),
        "legacy": {
            "schema_version": "phase-1",
            "deprecated": True,
        },
    }
    return sanitize_for_json(payload)


def build_resource_lifecycle(
    *,
    raw_resources_found: tuple[ResolvedResource, ...] = (),
    active_resources: tuple[ResolvedResource, ...] = (),
    normalized_resources: tuple[ResolvedResource, ...] = (),
    final_resources: tuple[ResolvedResource, ...] = (),
    unresolved_resources: tuple[UnresolvedResource, ...] = (),
    final_a1111_parameters: str = "",
    lookup_debug_summary: tuple[dict[str, object], ...] = (),
    warnings: tuple[ValidationIssue, ...] = (),
    metadata_status: str = "complete",
) -> dict[str, Any]:
    resolved = tuple(resource for resource in final_resources if resource.resolved)
    return sanitize_for_json(
        {
            "rawResourcesFound": [_resource_json(resource) for resource in raw_resources_found],
            "activeResources": [_resource_json(resource) for resource in active_resources],
            "normalizedResources": [_resource_json(resource) for resource in normalized_resources],
            "resolvedResources": [_resolved_resource_json(resource) for resource in resolved],
            "unresolvedResources": [resource.to_json() for resource in unresolved_resources],
            "finalResources": [
                _resolved_resource_json(resource) for resource in resolved if _is_final_civitai_resource(resource)
            ],
            "finalA1111Parameters": final_a1111_parameters,
            "lookupDebugSummary": list(lookup_debug_summary),
            "warnings": [warning.to_json() for warning in warnings],
            "metadataStatus": metadata_status,
        }
    )


def empty_resource_lifecycle(*, metadata_status: str = "partial") -> dict[str, Any]:
    return {
        "rawResourcesFound": [],
        "activeResources": [],
        "normalizedResources": [],
        "resolvedResources": [],
        "unresolvedResources": [],
        "finalResources": [],
        "finalA1111Parameters": "",
        "lookupDebugSummary": [],
        "warnings": [],
        "metadataStatus": metadata_status,
    }


def _normalize_resource_lifecycle(resource_lifecycle: dict[str, Any]) -> dict[str, Any]:
    normalized = empty_resource_lifecycle(
        metadata_status=str(resource_lifecycle.get("metadataStatus") or "partial")
        if isinstance(resource_lifecycle, dict)
        else "partial"
    )
    if isinstance(resource_lifecycle, dict):
        normalized.update(resource_lifecycle)
    for key in (
        "rawResourcesFound",
        "activeResources",
        "normalizedResources",
        "resolvedResources",
        "unresolvedResources",
        "finalResources",
        "lookupDebugSummary",
        "warnings",
    ):
        if not isinstance(normalized.get(key), list):
            normalized[key] = []
    return normalized


def _resource_json(resource: ResolvedResource) -> dict[str, Any]:
    return resource.resource.to_json()


def _resolved_resource_json(resource: ResolvedResource) -> dict[str, Any]:
    return resource.to_json()


def _is_final_civitai_resource(resource: ResolvedResource) -> bool:
    metadata = resource.resource
    return bool(
        resource.resolved
        and (
            metadata.civitai_model_version_id is not None
            or (metadata.air is not None and metadata.air.model_version_id is not None)
        )
    )


def write_sidecar_json_file(
    image_path: Path,
    payload: dict[str, Any],
    output_directory: Path,
) -> Path:
    sidecar_path = safe_sidecar_path(output_directory, image_path)
    sidecar_path.write_text(to_json_text(payload, indent=2) + "\n", encoding="utf-8")
    return sidecar_path


def _utc_now_rfc3339() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _image_json(image: Mapping[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "fileName": _basename(str(image.get("fileName") or image.get("filename") or "image.png")),
        "format": sanitize_metadata_text(str(image.get("format") or "PNG")),
    }
    for key in ("width", "height"):
        value = image.get(key)
        if isinstance(value, int) and value > 0:
            data[key] = value
    mode = image.get("mode")
    if mode:
        data["mode"] = sanitize_metadata_text(str(mode))
    safe_subfolder = image.get("subfolder")
    if safe_subfolder:
        normalized = str(safe_subfolder).replace("\\", "/")
        if not normalized.startswith("/") and ".." not in normalized.split("/"):
            data["relativeSubfolder"] = sanitize_metadata_text(normalized)
    return data


def _basename(value: str) -> str:
    windows_name = PureWindowsPath(value).name
    return PurePosixPath(windows_name).name or windows_name or "image.png"


def _png_metadata_summary(
    *,
    include_prompt: bool,
    include_workflow: bool,
    include_civitai: bool,
    unicode_fallback: bool,
    exif_minimal: bool,
    exif_user_comment: bool,
) -> dict[str, Any]:
    exif_chunk = {
        "type": "eXIf",
        "keyword": "UserComment",
        "encoding": "EXIF UNICODE UTF-16BE",
        "compressed": False,
    }
    chunks: list[dict[str, Any]] = []
    if not exif_minimal:
        chunks.extend(
            [
                {"type": "tEXt", "keyword": "parameters", "encoding": "latin-1", "compressed": False},
                {"type": "tEXt", "keyword": "Software", "encoding": "latin-1", "compressed": False},
            ]
        )
        if unicode_fallback:
            chunks.append({"type": "iTXt", "keyword": "parameters_utf8", "encoding": "utf-8", "compressed": False})
        if include_prompt:
            chunks.append({"type": "iTXt", "keyword": "prompt", "encoding": "utf-8", "compressed": False})
        if include_workflow:
            chunks.append({"type": "iTXt", "keyword": "workflow", "encoding": "utf-8", "compressed": False})
        if include_civitai:
            chunks.append({"type": "iTXt", "keyword": "civitai", "encoding": "utf-8", "compressed": False})
    if exif_user_comment:
        chunks.append(exif_chunk)
    return {
        "chunks": chunks,
        "compatibility": {
            "a1111ParametersChunk": "parameters",
            "parametersChunkType": "tEXt",
            "structuredManifestChunk": "civitai",
            "structuredManifestChunkType": "iTXt",
            "civitaiExifUserComment": "eXIf/UserComment",
            "minimalMode": bool(exif_minimal),
        },
    }


def _manifest_json(civitai_manifest: CivitaiManifest | Mapping[str, Any] | None) -> dict[str, Any]:
    if civitai_manifest is None:
        return {}
    if hasattr(civitai_manifest, "to_json") and callable(civitai_manifest.to_json):
        return sanitize_for_json(civitai_manifest.to_json())
    if isinstance(civitai_manifest, Mapping):
        return sanitize_for_json(dict(civitai_manifest))
    return {}


def _resources_summary(civitai_json: Mapping[str, Any], lifecycle: Mapping[str, Any]) -> dict[str, Any]:
    resources = [item for item in civitai_json.get("resources", []) if isinstance(item, dict)]
    unresolved = [item for item in civitai_json.get("unresolvedResources", []) if isinstance(item, dict)]
    final = [item for item in lifecycle.get("finalResources", []) if isinstance(item, dict)]
    if not final:
        final = [
            item
            for item in resources
            if item.get("resolved") is True
            and (
                item.get("canonicalAir")
                or item.get("urn")
                or item.get("modelVersionId")
                or item.get("civitaiModelVersionId")
            )
        ]
    return {
        "resolved": [item for item in resources if item.get("resolved") is True],
        "unresolved": unresolved,
        "final": final,
    }


def _lookup_diagnostics(civitai_json: Mapping[str, Any], settings: Mapping[str, Any]) -> dict[str, Any]:
    entries = [
        sanitize_for_json(dict(entry))
        for entry in civitai_json.get("lookupDebugSummary", [])
        if isinstance(entry, Mapping)
    ]
    first = entries[0] if entries else {}
    return {
        "enabled": bool(settings.get("enableCivitaiLookup")),
        "client": first.get("lookupClient"),
        "sslContextSource": first.get("sslContextSource"),
        "entries": entries,
    }


def _settings_json(
    options: MetadataOptions,
    *,
    manual_identities_enabled: bool,
    manual_identities_entry_count: int,
) -> dict[str, Any]:
    data = options.to_json()
    data["advancedManualIdentitiesEnabled"] = bool(manual_identities_enabled)
    data["manualIdentities"] = {
        "enabled": bool(manual_identities_enabled),
        "entryCount": max(0, int(manual_identities_entry_count)),
    }
    return data


def _issues_with_severity(issues: tuple[ValidationIssue, ...], *, severity: str = "warning") -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for issue in issues:
        item = issue.to_json()
        item["severity"] = severity
        if issue.field:
            item["path"] = issue.field
        output.append(item)
    return output


def _privacy_json(settings: Mapping[str, Any]) -> dict[str, Any]:
    lookup_enabled = bool(settings.get("enableCivitaiLookup"))
    return {
        "absolutePathsIncluded": False,
        "tokensIncluded": False,
        "promptsSentToCivitai": False,
        "workflowSentToCivitai": False,
        "imagesSentToCivitai": False,
        "lookupRequestData": ["hashes", "modelVersionId"] if lookup_enabled else [],
    }


__all__ = [
    "SIDECAR_FORMAT",
    "SIDECAR_SCHEMA_VERSION",
    "SIDECAR_SCHEMA_URL",
    "build_resource_lifecycle",
    "build_sidecar_payload",
    "empty_resource_lifecycle",
    "write_sidecar_json_file",
]
