"""Typed metadata structures for serialized image metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from ..security.redaction import sanitize_metadata_text, sanitize_metadata_value
from ..version import __version__


SCHEMA_NAME = "comfyui-civitai-save-node"
SCHEMA_VERSION = __version__


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    field: str | None = None

    def to_json(self) -> dict[str, str]:
        data = {
            "code": sanitize_metadata_text(self.code),
            "message": sanitize_metadata_text(self.message),
        }
        if self.field:
            data["field"] = sanitize_metadata_text(self.field)
        return data


@dataclass(frozen=True)
class ValidationResult:
    warnings: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    errors: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def format_errors(self) -> str:
        return "; ".join(sanitize_metadata_text(issue.message) for issue in self.errors)

    def with_warning(self, issue: ValidationIssue) -> "ValidationResult":
        return ValidationResult(
            warnings=(*self.warnings, issue),
            errors=self.errors,
        )

    def with_error(self, issue: ValidationIssue) -> "ValidationResult":
        return ValidationResult(
            warnings=self.warnings,
            errors=(*self.errors, issue),
        )

    def to_json(self) -> dict[str, list[dict[str, str]]]:
        return {
            "warnings": [issue.to_json() for issue in self.warnings],
            "errors": [issue.to_json() for issue in self.errors],
        }


@dataclass(frozen=True)
class MetadataOptions:
    strict_mode: bool
    include_workflow: bool
    include_civitai_manifest: bool
    write_sidecar_json: bool
    enable_civitai_lookup: bool = False
    lookup_prefer_sha256: bool = True
    lookup_timeout_seconds: float = 4.0
    lookup_cache_results: bool = False
    use_persistent_hash_cache: bool = True
    hashing_mode: str = "cached_or_fast"
    civitai_exif_minimal: bool = False

    def to_json(self) -> dict[str, bool | float | str]:
        return {
            "strictMode": self.strict_mode,
            "includeWorkflow": self.include_workflow,
            "includeCivitaiManifest": self.include_civitai_manifest,
            "writeSidecarJson": self.write_sidecar_json,
            "enableCivitaiLookup": self.enable_civitai_lookup,
            "lookupPreferSha256": self.lookup_prefer_sha256,
            "lookupTimeoutSeconds": self.lookup_timeout_seconds,
            "lookupCacheResults": self.lookup_cache_results,
            "usePersistentHashCache": self.use_persistent_hash_cache,
            "hashingMode": sanitize_metadata_text(self.hashing_mode),
            "civitaiExifMinimal": self.civitai_exif_minimal,
        }


@dataclass(frozen=True)
class PromptMetadata:
    positive: str | None = None
    negative: str | None = None

    def to_json(self) -> dict[str, str]:
        data: dict[str, str] = {}
        if self.positive:
            data["positive"] = self.positive
        if self.negative:
            data["negative"] = self.negative
        return data


@dataclass(frozen=True)
class HashMetadata:
    sha256: str | None = None
    auto_v1: str | None = None
    auto_v2: str | None = None
    auto_v3: str | None = None
    crc32: str | None = None
    blake3: str | None = None
    additional: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (
            self.sha256 or self.auto_v1 or self.auto_v2 or self.auto_v3 or self.crc32 or self.blake3 or self.additional
        )

    def to_json(self) -> dict[str, str]:
        data: dict[str, str] = {}
        if self.auto_v1:
            data["AutoV1"] = self.auto_v1
        if self.auto_v2:
            data["AutoV2"] = self.auto_v2
        if self.auto_v3:
            data["AutoV3"] = self.auto_v3
        if self.blake3:
            data["BLAKE3"] = self.blake3
        if self.crc32:
            data["CRC32"] = self.crc32
        if self.sha256:
            data["SHA256"] = self.sha256
        for key, value in sorted(self.additional.items()):
            if value and key not in data:
                data[str(key)] = str(value)
        return data


@dataclass(frozen=True)
class AIRMetadata:
    raw: str
    canonical: str
    scheme: str
    namespace: str
    ecosystem: str
    type: str
    source: str
    id: str
    version: str | None = None
    file_id: str | None = None
    model_id: int | None = None
    model_version_id: int | None = None
    layer: str | None = None
    format: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "raw": self.raw,
            "rawAir": self.raw,
            "canonicalAir": self.canonical,
            "scheme": self.scheme,
            "namespace": self.namespace,
            "ecosystem": self.ecosystem,
            "type": self.type,
            "source": self.source,
            "id": self.id,
        }
        if self.version is not None:
            data["version"] = self.version
        if self.file_id is not None:
            data["fileId"] = self.file_id
        if self.model_id is not None:
            data["modelId"] = self.model_id
        if self.model_version_id is not None:
            data["modelVersionId"] = self.model_version_id
        if self.layer:
            data["layer"] = self.layer
        if self.format:
            data["format"] = self.format
        return data


@dataclass(frozen=True)
class GenerationSettings:
    steps: int | None = None
    sampler: str | None = None
    scheduler: str | None = None
    cfg_scale: float | None = None
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    batch_size: int | None = None
    model: str | None = None
    model_hash: str | None = None
    vae: str | None = None
    vae_hash: str | None = None
    clip_skip: int | None = None
    denoising_strength: float | None = None
    version: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_a1111_settings(self) -> bool:
        return any(
            value is not None
            for value in (
                self.steps,
                self.sampler,
                self.scheduler,
                self.cfg_scale,
                self.seed,
                self.width,
                self.height,
                self.batch_size,
                self.model,
                self.model_hash,
                self.vae,
                self.vae_hash,
                self.clip_skip,
                self.denoising_strength,
                self.version,
            )
        ) or bool(self.extra)

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        _set_if_present(data, "steps", self.steps)
        _set_if_present(data, "sampler", self.sampler)
        _set_if_present(data, "scheduler", self.scheduler)
        _set_if_present(data, "cfgScale", self.cfg_scale)
        _set_if_present(data, "seed", self.seed)
        _set_if_present(data, "width", self.width)
        _set_if_present(data, "height", self.height)
        _set_if_present(data, "batchSize", self.batch_size)
        _set_if_present(data, "model", self.model)
        _set_if_present(data, "modelHash", self.model_hash)
        _set_if_present(data, "vae", self.vae)
        _set_if_present(data, "vaeHash", self.vae_hash)
        _set_if_present(data, "clipSkip", self.clip_skip)
        _set_if_present(data, "denoisingStrength", self.denoising_strength)
        _set_if_present(data, "version", self.version)
        if self.extra:
            data["extra"] = dict(sorted(self.extra.items()))
        return data


@dataclass(frozen=True)
class ModelResourceMetadata:
    role: str
    type: str | None = None
    node_id: str | None = None
    node_class_type: str | None = None
    display_name: str | None = None
    name: str | None = None
    selected_value: str | None = None
    source_value: str | None = field(default=None, repr=False, compare=False)
    filename: str | None = None
    local_path_basename: str | None = None
    air: AIRMetadata | None = None
    civitai_model_id: int | None = None
    civitai_model_version_id: int | None = None
    hashes: HashMetadata = field(default_factory=HashMetadata)
    hash_source: str | None = None
    hash_status: str | None = None
    hash_error: str | None = None
    resolution_source: str | None = None
    model_name: str | None = None
    model_version_name: str | None = None
    base_model: str | None = None
    source_url: str | None = None
    trigger_words: tuple[str, ...] = field(default_factory=tuple)
    license: str | None = None
    usage_notes: str | None = None
    strength: float | None = None
    strength_model: float | None = None
    strength_clip: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role}
        _set_if_present(data, "type", self.type)
        _set_if_present(data, "nodeId", self.node_id)
        _set_if_present(data, "nodeClassType", self.node_class_type)
        _set_if_present(data, "displayName", self.display_name)
        _set_if_present(data, "name", self.name)
        _set_if_present(data, "selectedValue", _relative_or_basename(self.selected_value))
        _set_if_present(data, "filename", _basename_or_none(self.filename))
        _set_if_present(data, "localPathBasename", _basename_or_none(self.local_path_basename))
        if self.air is not None:
            emitted_air = self.air.canonical or self.air.raw
            data["air"] = self.air.to_json()
            data["rawAir"] = self.air.raw
            data["canonicalAir"] = self.air.canonical
            data["urn"] = emitted_air
            _set_if_present(data, "fileId", self.air.file_id)
            _set_if_present(data, "format", self.air.format)
            _set_if_present(data, "airType", self.air.type)
            _set_if_present(data, "modelId", self.air.model_id)
            _set_if_present(data, "modelVersionId", self.air.model_version_id)
        _set_if_present(data, "civitaiModelId", self.civitai_model_id)
        _set_if_present(data, "civitaiModelVersionId", self.civitai_model_version_id)
        _set_if_present(data, "modelId", self.civitai_model_id)
        _set_if_present(data, "modelVersionId", self.civitai_model_version_id)
        if not self.hashes.is_empty:
            data["hashes"] = self.hashes.to_json()
        _set_if_present(data, "hashSource", self.hash_source)
        _set_if_present(data, "hashStatus", self.hash_status)
        _set_if_present(data, "hashError", self.hash_error)
        _set_if_present(data, "resolutionSource", self.resolution_source)
        _set_if_present(data, "identitySource", _metadata_lookup_value(self.metadata, "identitySource"))
        _set_if_present(data, "identityStatus", _metadata_lookup_value(self.metadata, "identityStatus"))
        _set_if_present(data, "confidence", _metadata_lookup_value(self.metadata, "confidence"))
        _set_if_present(data, "pinned", _metadata_lookup_value(self.metadata, "pinned"))
        _set_if_present(data, "apiAlternateMatch", _metadata_lookup_value(self.metadata, "apiAlternateMatch"))
        _set_if_present(data, "apiReturnedAir", _metadata_lookup_value(self.metadata, "apiReturnedAir"))
        _set_if_present(data, "apiCompletionStatus", _metadata_lookup_value(self.metadata, "apiCompletionStatus"))
        _set_if_present(
            data, "apiCompletionFailureReason", _metadata_lookup_value(self.metadata, "apiCompletionFailureReason")
        )
        _set_if_present(
            data, "apiCompletionStatusCode", _metadata_lookup_value(self.metadata, "apiCompletionStatusCode")
        )
        _set_if_present(data, "apiCompletionRetryable", _metadata_lookup_value(self.metadata, "apiCompletionRetryable"))
        _set_if_present(data, "lookupStatus", _metadata_lookup_value(self.metadata, "lookupStatus"))
        _set_if_present(data, "lookupFailureReason", _metadata_lookup_value(self.metadata, "lookupFailureReason"))
        _set_if_present(data, "lookupFailureClass", _metadata_lookup_value(self.metadata, "lookupFailureClass"))
        _set_if_present(
            data, "lookupFailureDetailSanitized", _metadata_lookup_value(self.metadata, "lookupFailureDetailSanitized")
        )
        _set_if_present(data, "lookupStatusCode", _metadata_lookup_value(self.metadata, "lookupStatusCode"))
        _set_if_present(data, "lookupRetryable", _metadata_lookup_value(self.metadata, "lookupRetryable"))
        _set_if_present(data, "lookupMethod", _metadata_lookup_value(self.metadata, "lookupMethod"))
        _set_if_present(data, "lookupClient", _metadata_lookup_value(self.metadata, "lookupClient"))
        _set_if_present(data, "sslContextSource", _metadata_lookup_value(self.metadata, "sslContextSource"))
        _set_if_present(data, "apiEndpointKind", _metadata_lookup_value(self.metadata, "apiEndpointKind"))
        _set_if_present(data, "identityIncomplete", _metadata_lookup_value(self.metadata, "identityIncomplete"))
        _set_if_present(data, "modelName", self.model_name)
        _set_if_present(data, "modelVersionName", self.model_version_name)
        _set_if_present(data, "baseModel", self.base_model)
        _set_if_present(data, "sourceUrl", self.source_url)
        if self.trigger_words:
            data["triggerWords"] = list(self.trigger_words)
        _set_if_present(data, "license", self.license)
        _set_if_present(data, "usageNotes", self.usage_notes)
        _set_if_present(data, "strength", self.strength)
        _set_if_present(data, "strengthModel", self.strength_model)
        _set_if_present(data, "strengthClip", self.strength_clip)
        if self.metadata:
            data["metadata"] = dict(sorted(self.metadata.items()))
        return data


@dataclass(frozen=True)
class ResolvedResource:
    resource: ModelResourceMetadata
    resolved: bool = True
    unresolved_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        data = self.resource.to_json()
        data["resolved"] = self.resolved
        _set_if_present(data, "unresolvedReason", self.unresolved_reason)
        return data


@dataclass(frozen=True)
class UnresolvedResource:
    reason: str
    role: str | None = None
    type: str | None = None
    node_id: str | None = None
    node_class_type: str | None = None
    display_name: str | None = None
    name: str | None = None
    selected_value: str | None = None
    filename: str | None = None
    local_path_basename: str | None = None
    raw_air: str | None = None
    hashes: HashMetadata = field(default_factory=HashMetadata)
    hash_source: str | None = None
    hash_status: str | None = None
    hash_error: str | None = None
    resolution_source: str | None = None
    lookup_status: str | None = None
    lookup_failure_reason: str | None = None
    lookup_failure_class: str | None = None
    lookup_failure_detail_sanitized: str | None = None
    lookup_status_code: int | None = None
    lookup_retryable: bool | None = None
    lookup_method: str | None = None
    lookup_client: str | None = None
    ssl_context_source: str | None = None
    api_endpoint_kind: str | None = None
    strength: float | None = None
    strength_model: float | None = None
    strength_clip: float | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"reason": self.reason, "unresolvedReason": self.reason}
        _set_if_present(data, "role", self.role)
        _set_if_present(data, "type", self.type)
        _set_if_present(data, "nodeId", self.node_id)
        _set_if_present(data, "nodeClassType", self.node_class_type)
        _set_if_present(data, "displayName", self.display_name)
        _set_if_present(data, "name", self.name)
        _set_if_present(data, "selectedValue", _relative_or_basename(self.selected_value))
        _set_if_present(data, "filename", _basename_or_none(self.filename))
        _set_if_present(data, "localPathBasename", _basename_or_none(self.local_path_basename))
        _set_if_present(data, "rawAir", self.raw_air)
        if not self.hashes.is_empty:
            data["hashes"] = self.hashes.to_json()
        _set_if_present(data, "hashSource", self.hash_source)
        _set_if_present(data, "hashStatus", self.hash_status)
        _set_if_present(data, "hashError", self.hash_error)
        _set_if_present(data, "resolutionSource", self.resolution_source)
        _set_if_present(data, "lookupStatus", self.lookup_status)
        _set_if_present(data, "lookupFailureReason", self.lookup_failure_reason)
        _set_if_present(data, "lookupFailureClass", self.lookup_failure_class)
        _set_if_present(data, "lookupFailureDetailSanitized", self.lookup_failure_detail_sanitized)
        _set_if_present(data, "lookupStatusCode", self.lookup_status_code)
        _set_if_present(data, "lookupRetryable", self.lookup_retryable)
        _set_if_present(data, "lookupMethod", self.lookup_method)
        _set_if_present(data, "lookupClient", self.lookup_client)
        _set_if_present(data, "sslContextSource", self.ssl_context_source)
        _set_if_present(data, "apiEndpointKind", self.api_endpoint_kind)
        _set_if_present(data, "strength", self.strength)
        _set_if_present(data, "strengthModel", self.strength_model)
        _set_if_present(data, "strengthClip", self.strength_clip)
        return data


@dataclass(frozen=True)
class GeneratorMetadata:
    name: str = "Save Image with Civitai Metadata"
    version: str | None = None

    def to_json(self) -> dict[str, str]:
        data = {"name": self.name}
        if self.version:
            data["version"] = self.version
        return data


@dataclass(frozen=True)
class WorkflowRefs:
    prompt: str = "pnginfo:prompt"
    workflow: str | None = "pnginfo:workflow"

    def to_json(self) -> dict[str, str]:
        data = {"prompt": self.prompt}
        if self.workflow:
            data["workflow"] = self.workflow
        return data


@dataclass(frozen=True)
class IdentityCacheMetadata:
    format_version: str = "none"
    mapping_source: str = "none"
    loaded_record_count: int = 0
    warnings_count: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "formatVersion": self.format_version,
            "mappingSource": self.mapping_source,
            "loadedRecordCount": self.loaded_record_count,
            "warningsCount": self.warnings_count,
        }


@dataclass(frozen=True)
class CivitaiManifest:
    generation: GenerationSettings
    prompt: PromptMetadata
    resources: tuple[ResolvedResource, ...] = field(default_factory=tuple)
    unresolved_resources: tuple[UnresolvedResource, ...] = field(default_factory=tuple)
    hashes: HashMetadata = field(default_factory=HashMetadata)
    validation: ValidationResult = field(default_factory=ValidationResult)
    generator: GeneratorMetadata = field(default_factory=GeneratorMetadata)
    workflow_refs: WorkflowRefs = field(default_factory=WorkflowRefs)
    identity_cache: IdentityCacheMetadata = field(default_factory=IdentityCacheMetadata)
    metadata_status: str = "complete"
    save_warnings: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    lookup_debug_summary: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    schema_name: str = SCHEMA_NAME
    schema_version: str = SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schemaName": self.schema_name,
            "schemaVersion": self.schema_version,
            "generator": self.generator.to_json(),
            "prompt": self.prompt.to_json(),
            "generation": self.generation.to_json(),
            "resources": [resource.to_json() for resource in self.resources],
            "unresolvedResources": [resource.to_json() for resource in self.unresolved_resources],
            "hashes": self.hashes.to_json(),
            "workflowRefs": self.workflow_refs.to_json(),
            "identityCache": self.identity_cache.to_json(),
            "metadataStatus": sanitize_metadata_text(self.metadata_status),
            "validation": self.validation.to_json(),
        }
        if self.save_warnings:
            data["saveWarnings"] = [warning.to_json() for warning in self.save_warnings]
        if self.lookup_debug_summary:
            data["lookupDebugSummary"] = [
                sanitize_metadata_value(dict(summary)) for summary in self.lookup_debug_summary
            ]
        return data


def _set_if_present(data: dict[str, Any], key: str, value: Any | None) -> None:
    if value is not None:
        data[key] = value


def _basename_or_none(value: str | None) -> str | None:
    if not value:
        return None
    windows_name = PureWindowsPath(value).name
    posix_name = PurePosixPath(windows_name).name
    return posix_name or windows_name or None


def _relative_or_basename(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or _looks_windows_absolute(normalized):
        return _basename_or_none(normalized)
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return _basename_or_none(normalized)
    return "/".join(parts)


def _metadata_lookup_value(metadata: Mapping[str, Any], key: str) -> Any | None:
    value = metadata.get(key)
    if value is None or value == "":
        return None
    return value


def _looks_windows_absolute(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] == "/" and value[0].isalpha()
