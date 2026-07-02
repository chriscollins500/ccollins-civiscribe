"""User-pinned Civitai identities supplied directly on the save node."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping
from urllib import parse

from .air import parse_air
from ..hashing.resource_identity import HASHED_BUT_NO_CIVITAI_IDENTITY
from ..metadata.schema import (
    AIRMetadata,
    HashMetadata,
    ModelResourceMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
)
from ..security.redaction import sanitize_metadata_text

MANUAL_PINNED_IDENTITY_SOURCE = "manual_pinned_node_input"
PREFERRED_PRIMARY_MODEL_AIR_SOURCE = "preferred_primary_model_air"
MANUAL_PINNED_LOOKUP_STATUS = "resolved_by_manual_pinned"

_HASH_PRIORITY = (
    ("sha256", "SHA256", "sha256", 600),
    ("blake3", "BLAKE3", "blake3", 500),
    ("auto_v2", "AutoV2", "auto_v2", 400),
    ("auto_v3", "AutoV3", "auto_v3", 300),
    ("crc32", "CRC32", "crc32", 200),
    ("auto_v1", "AutoV1", "auto_v1", 100),
)


@dataclass(frozen=True)
class ManualIdentityRecord:
    air: AIRMetadata | None
    civitai_model_id: int | None
    civitai_model_version_id: int | None
    hashes: HashMetadata
    match_name: str | None = None
    match_role: str | None = None
    match_type: str | None = None
    pinned: bool = True
    confidence: str = "user_pinned"
    note: str | None = None
    index: int = 0
    identity_source: str = MANUAL_PINNED_IDENTITY_SOURCE
    incomplete: bool = False


@dataclass(frozen=True)
class ManualIdentityApplyResult:
    resources: tuple[ResolvedResource, ...]
    unresolved_resources: tuple[UnresolvedResource, ...]
    warnings: tuple[ValidationIssue, ...] = ()
    errors: tuple[ValidationIssue, ...] = ()


def apply_preferred_primary_model_air(
    *,
    resources: tuple[ResolvedResource, ...],
    preferred_primary_model_air: str | None,
) -> ManualIdentityApplyResult:
    """Apply a simple user-pinned AIR/URL/version to the active primary model."""

    text = str(preferred_primary_model_air or "").strip()
    if not text:
        return ManualIdentityApplyResult(
            resources=resources,
            unresolved_resources=_unresolved_resources(resources),
        )

    preferred, warnings = _parse_preferred_primary_identity(text)
    if preferred is None:
        warnings.append(
            ValidationIssue(
                code="preferred_primary_model_air_malformed",
                message="Preferred primary model AIR, URL, or modelVersionId is malformed and was ignored",
                field="preferredPrimaryModelAir",
            )
        )
        return ManualIdentityApplyResult(
            resources=resources,
            unresolved_resources=_unresolved_resources(resources),
            warnings=tuple(warnings),
        )

    target_index = _primary_model_index(resources)
    if target_index is None:
        warnings.append(
            ValidationIssue(
                code="preferred_primary_model_air_no_primary_model",
                message="Preferred primary model AIR was provided, but no active primary model resource was detected",
                field="preferredPrimaryModelAir",
            )
        )
        return ManualIdentityApplyResult(
            resources=resources,
            unresolved_resources=_unresolved_resources(resources),
            warnings=tuple(warnings),
        )

    target = resources[target_index]
    if target.resolved or _has_existing_identity(target.resource):
        return ManualIdentityApplyResult(
            resources=resources,
            unresolved_resources=_unresolved_resources(resources),
            warnings=tuple(warnings),
        )

    if preferred.incomplete:
        warnings.append(
            ValidationIssue(
                code="preferred_primary_model_identity_incomplete",
                message="Preferred primary model identity is partial; official AIR can be completed only when lookup is enabled",
                field="preferredPrimaryModelAir",
            )
        )

    record = ManualIdentityRecord(
        air=preferred.air,
        civitai_model_id=preferred.model_id,
        civitai_model_version_id=preferred.model_version_id,
        hashes=HashMetadata(),
        pinned=True,
        confidence="user_pinned",
        identity_source=PREFERRED_PRIMARY_MODEL_AIR_SOURCE,
        incomplete=preferred.incomplete,
    )
    updated = list(resources)
    updated[target_index] = _apply_record(target, record)
    updated_tuple = tuple(updated)
    return ManualIdentityApplyResult(
        resources=updated_tuple,
        unresolved_resources=_unresolved_resources(updated_tuple),
        warnings=tuple(warnings),
    )


def apply_manual_resource_identities(
    *,
    resources: tuple[ResolvedResource, ...],
    manual_resource_identities_json: str | None,
) -> ManualIdentityApplyResult:
    """Apply trusted user-pinned mappings from the node UI.

    Malformed input is reported as a warning and never blocks saving.
    """

    text = str(manual_resource_identities_json or "").strip()
    if not text or text == "[]":
        return ManualIdentityApplyResult(
            resources=resources,
            unresolved_resources=_unresolved_resources(resources),
        )

    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return ManualIdentityApplyResult(
            resources=resources,
            unresolved_resources=_unresolved_resources(resources),
            warnings=(
                ValidationIssue(
                    code="manual_identity_invalid_json",
                    message="Manual resource identities JSON is invalid and was ignored",
                    field="manualResourceIdentities",
                ),
            ),
        )

    if not isinstance(raw, list):
        return ManualIdentityApplyResult(
            resources=resources,
            unresolved_resources=_unresolved_resources(resources),
            warnings=(
                ValidationIssue(
                    code="manual_identity_schema_invalid",
                    message="Manual resource identities JSON must be an array and was ignored",
                    field="manualResourceIdentities",
                ),
            ),
        )

    records: list[ManualIdentityRecord] = []
    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []
    for index, raw_record in enumerate(raw):
        record, record_warnings, record_errors = _parse_manual_identity_record(raw_record, index)
        warnings.extend(record_warnings)
        errors.extend(record_errors)
        if record is not None:
            records.append(record)

    updated: list[ResolvedResource] = []
    for resource_index, resource in enumerate(resources):
        if resource.resolved or _has_existing_identity(resource.resource):
            updated.append(resource)
            continue
        winner, match_warnings = _best_match(resource, tuple(records), resource_index)
        warnings.extend(match_warnings)
        if winner is None:
            updated.append(resource)
            continue
        updated.append(_apply_record(resource, winner))

    updated_tuple = tuple(updated)
    return ManualIdentityApplyResult(
        resources=updated_tuple,
        unresolved_resources=_unresolved_resources(updated_tuple),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def _parse_manual_identity_record(
    raw_record: Any,
    index: int,
) -> tuple[ManualIdentityRecord | None, tuple[ValidationIssue, ...], tuple[ValidationIssue, ...]]:
    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []
    field = f"manualResourceIdentities[{index}]"

    if not isinstance(raw_record, Mapping):
        return (
            None,
            (
                ValidationIssue(
                    code="manual_identity_record_invalid",
                    message="Manual identity entry must be a JSON object",
                    field=field,
                ),
            ),
            (),
        )

    match = raw_record.get("match")
    if not isinstance(match, Mapping):
        match = {}

    raw_air = _string_or_none(
        raw_record.get("air") or raw_record.get("urn") or raw_record.get("rawAir") or raw_record.get("canonicalAir")
    )
    air, air_warnings = parse_air(raw_air)
    if air_warnings:
        warnings.extend(
            ValidationIssue(
                code="manual_identity_malformed_air",
                message=warning.message,
                field=f"{field}.air",
            )
            for warning in air_warnings
        )
    if air is None:
        return None, tuple(warnings), tuple(errors)

    explicit_model_id = _int_or_none(raw_record.get("modelId") or raw_record.get("civitaiModelId"))
    explicit_version_id = _int_or_none(
        raw_record.get("modelVersionId") or raw_record.get("civitaiModelVersionId") or raw_record.get("versionId")
    )
    model_id = explicit_model_id if explicit_model_id is not None else air.model_id
    version_id = explicit_version_id if explicit_version_id is not None else air.model_version_id

    if explicit_model_id is not None and air.model_id is not None and explicit_model_id != air.model_id:
        warnings.append(
            ValidationIssue(
                code="manual_identity_model_id_conflict",
                message="Manual identity modelId conflicts with AIR modelId",
                field=f"{field}.modelId",
            )
        )
    if (
        explicit_version_id is not None
        and air.model_version_id is not None
        and explicit_version_id != air.model_version_id
    ):
        warnings.append(
            ValidationIssue(
                code="manual_identity_model_version_conflict",
                message="Manual identity modelVersionId conflicts with AIR modelVersionId",
                field=f"{field}.modelVersionId",
            )
        )
    if air.source == "civitai" and version_id is None:
        warnings.append(
            ValidationIssue(
                code="manual_identity_missing_model_version_id",
                message="Manual Civitai identity must include a modelVersionId via AIR or explicit field",
                field=field,
            )
        )
    if any(
        issue.code
        in {
            "manual_identity_model_id_conflict",
            "manual_identity_model_version_conflict",
            "manual_identity_missing_model_version_id",
        }
        for issue in warnings
    ):
        return None, tuple(warnings), tuple(errors)

    hashes = _parse_hashes(raw_record.get("hashes"))
    match_hashes = _parse_hashes(match)
    hashes = _merge_hashes(hashes, match_hashes)
    match_name = _string_or_none(
        match.get("name")
        or match.get("filename")
        or match.get("selectedValue")
        or raw_record.get("filename")
        or raw_record.get("name")
        or raw_record.get("modelName")
    )
    note = _string_or_none(raw_record.get("note"))
    return (
        ManualIdentityRecord(
            air=air,
            civitai_model_id=model_id,
            civitai_model_version_id=version_id,
            hashes=hashes,
            match_name=_basename(match_name) if match_name else None,
            match_role=_string_or_none(match.get("role") or raw_record.get("role")),
            match_type=_string_or_none(match.get("type") or raw_record.get("type") or raw_record.get("resourceType")),
            pinned=True,
            confidence="user_pinned",
            note=note,
            index=index,
            identity_source=MANUAL_PINNED_IDENTITY_SOURCE,
        ),
        tuple(warnings),
        (),
    )


def _best_match(
    resource: ResolvedResource,
    records: tuple[ManualIdentityRecord, ...],
    resource_index: int,
) -> tuple[ManualIdentityRecord | None, tuple[ValidationIssue, ...]]:
    matches: list[tuple[int, ManualIdentityRecord]] = []
    for record in records:
        strength = _match_strength(resource.resource, record)
        if strength:
            matches.append((strength, record))
    if not matches:
        return None, ()

    strongest = max(strength for strength, _record in matches)
    strongest_records = [record for strength, record in matches if strength == strongest]
    first = strongest_records[0]
    if any(not _same_identity(first, record) for record in strongest_records[1:]):
        return None, (
            ValidationIssue(
                code="manual_identity_conflict",
                message="Multiple equally strong manual identities matched one resource; none were applied",
                field=f"resources[{resource_index}]",
            ),
        )
    return first, ()


def _match_strength(metadata: ModelResourceMetadata, record: ManualIdentityRecord) -> int:
    if record.match_role and _normalize_label(record.match_role) != _normalize_label(metadata.role):
        return 0
    if record.match_type and _normalize_label(record.match_type) != _normalize_label(metadata.type or ""):
        return 0

    hash_strength = _hash_match_strength(metadata.hashes, record.hashes)
    if hash_strength:
        return hash_strength
    if not metadata.hashes.is_empty and not record.hashes.is_empty:
        return 0

    if record.match_name:
        resource_names = {
            _normalize_name(value)
            for value in (
                metadata.filename,
                metadata.local_path_basename,
                metadata.name,
                metadata.selected_value,
            )
            if value
        }
        if _normalize_name(record.match_name) in resource_names:
            return 10
    return 0


def _hash_match_strength(resource_hashes: HashMetadata, record_hashes: HashMetadata) -> int:
    for _algorithm, _json_key, attr, strength in _HASH_PRIORITY:
        resource_value = getattr(resource_hashes, attr)
        record_value = getattr(record_hashes, attr)
        if resource_value and record_value and _normalize_hash(resource_value) == _normalize_hash(record_value):
            return strength
    return 0


def _apply_record(resource: ResolvedResource, record: ManualIdentityRecord) -> ResolvedResource:
    metadata = resource.resource
    extra = {
        **dict(metadata.metadata),
        "identitySource": record.identity_source,
        "identityStatus": "partial_pinned" if record.incomplete else "resolved_pinned",
        "confidence": record.confidence,
        "pinned": True,
        "lookupStatus": MANUAL_PINNED_LOOKUP_STATUS,
    }
    if record.incomplete:
        extra["identityIncomplete"] = True
    if record.note:
        extra["manualIdentityNote"] = sanitize_metadata_text(record.note)
    updated_metadata = replace(
        metadata,
        air=record.air,
        civitai_model_id=record.civitai_model_id,
        civitai_model_version_id=record.civitai_model_version_id,
        resolution_source=record.identity_source,
        metadata=extra,
    )
    return replace(resource, resource=updated_metadata, resolved=True, unresolved_reason=None)


def _unresolved_resources(resources: tuple[ResolvedResource, ...]) -> tuple[UnresolvedResource, ...]:
    return tuple(_unresolved_from_resource(resource) for resource in resources if not resource.resolved)


def _unresolved_from_resource(resource: ResolvedResource) -> UnresolvedResource:
    metadata = resource.resource
    return UnresolvedResource(
        reason=resource.unresolved_reason or HASHED_BUT_NO_CIVITAI_IDENTITY,
        role=metadata.role,
        type=metadata.type,
        node_id=metadata.node_id,
        node_class_type=metadata.node_class_type,
        display_name=metadata.display_name,
        name=metadata.name,
        selected_value=metadata.selected_value,
        filename=metadata.filename,
        local_path_basename=metadata.local_path_basename,
        raw_air=metadata.air.raw if metadata.air else None,
        hashes=metadata.hashes,
        hash_source=metadata.hash_source,
        hash_status=metadata.hash_status,
        hash_error=metadata.hash_error,
        resolution_source=metadata.resolution_source,
        lookup_status=_metadata_lookup_str(metadata, "lookupStatus"),
        lookup_failure_reason=_metadata_lookup_str(metadata, "lookupFailureReason"),
        lookup_failure_class=_metadata_lookup_str(metadata, "lookupFailureClass"),
        lookup_failure_detail_sanitized=_metadata_lookup_str(metadata, "lookupFailureDetailSanitized"),
        lookup_status_code=_metadata_lookup_int(metadata, "lookupStatusCode"),
        lookup_retryable=_metadata_lookup_bool(metadata, "lookupRetryable"),
        lookup_method=_metadata_lookup_str(metadata, "lookupMethod"),
        lookup_client=_metadata_lookup_str(metadata, "lookupClient"),
        ssl_context_source=_metadata_lookup_str(metadata, "sslContextSource"),
        api_endpoint_kind=_metadata_lookup_str(metadata, "apiEndpointKind"),
        strength=metadata.strength,
        strength_model=metadata.strength_model,
        strength_clip=metadata.strength_clip,
    )


def _parse_hashes(raw_hashes: Any) -> HashMetadata:
    if not isinstance(raw_hashes, Mapping):
        return HashMetadata()
    return HashMetadata(
        sha256=_string_or_none(_hash_value(raw_hashes, "SHA256", "sha256")),
        auto_v1=_string_or_none(_hash_value(raw_hashes, "AutoV1", "autoV1", "auto_v1")),
        auto_v2=_string_or_none(_hash_value(raw_hashes, "AutoV2", "autoV2", "auto_v2", "modelHash")),
        auto_v3=_string_or_none(_hash_value(raw_hashes, "AutoV3", "autoV3", "auto_v3")),
        crc32=_string_or_none(_hash_value(raw_hashes, "CRC32", "crc32")),
        blake3=_string_or_none(_hash_value(raw_hashes, "BLAKE3", "blake3")),
    )


def _merge_hashes(primary: HashMetadata, secondary: HashMetadata) -> HashMetadata:
    return HashMetadata(
        sha256=primary.sha256 or secondary.sha256,
        auto_v1=primary.auto_v1 or secondary.auto_v1,
        auto_v2=primary.auto_v2 or secondary.auto_v2,
        auto_v3=primary.auto_v3 or secondary.auto_v3,
        crc32=primary.crc32 or secondary.crc32,
        blake3=primary.blake3 or secondary.blake3,
        additional={**dict(secondary.additional), **dict(primary.additional)},
    )


def _same_identity(left: ManualIdentityRecord, right: ManualIdentityRecord) -> bool:
    return (
        left.air.canonical == right.air.canonical
        and left.civitai_model_id == right.civitai_model_id
        and left.civitai_model_version_id == right.civitai_model_version_id
    )


def _has_existing_identity(metadata: ModelResourceMetadata) -> bool:
    return bool(
        metadata.civitai_model_version_id is not None
        or (metadata.air is not None and metadata.air.model_version_id is not None)
    )


def _primary_model_index(resources: tuple[ResolvedResource, ...]) -> int | None:
    for index, resource in enumerate(resources):
        if resource.resource.metadata.get("primaryModel") is True:
            return index
    for index, resource in enumerate(resources):
        metadata = resource.resource
        role = _normalize_label(metadata.role)
        resource_type = _normalize_label(metadata.type or "")
        if role in {"checkpoint", "base model"} or resource_type in {
            "checkpoint",
            "diffusionmodel",
            "diffusion model",
            "unet",
        }:
            return index
    return None


@dataclass(frozen=True)
class _PreferredIdentity:
    air: AIRMetadata | None
    model_id: int | None
    model_version_id: int | None
    incomplete: bool = False


def _parse_preferred_primary_identity(
    text: str,
) -> tuple[_PreferredIdentity | None, list[ValidationIssue]]:
    if _looks_like_air(text):
        air, air_warnings = parse_air(text)
        warnings = [
            ValidationIssue(
                code="preferred_primary_model_air_parse_warning",
                message=sanitize_metadata_text(warning.message),
                field="preferredPrimaryModelAir",
            )
            for warning in air_warnings
        ]
        if air is None:
            return None, warnings
        return _PreferredIdentity(
            air=air,
            model_id=air.model_id,
            model_version_id=air.model_version_id,
            incomplete=air.source == "civitai" and air.model_version_id is None,
        ), warnings

    url_identity, url_warnings = _parse_civitai_url(text)
    if url_identity is not None:
        return url_identity, url_warnings

    if text.isdigit():
        return _PreferredIdentity(
            air=None,
            model_id=None,
            model_version_id=int(text),
            incomplete=True,
        ), []

    return None, []


def _looks_like_air(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("urn:air:") or lowered.startswith("air:") or lowered.count(":") >= 3


def _parse_civitai_url(value: str) -> tuple[_PreferredIdentity | None, list[ValidationIssue]]:
    parsed = parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, []
    host = parsed.netloc.lower()
    if host not in {"civitai.com", "www.civitai.com", "civitai.red", "www.civitai.red"}:
        return None, []
    parts = [part for part in parsed.path.split("/") if part]
    model_id = None
    if len(parts) >= 2 and parts[0] == "models" and parts[1].isdigit():
        model_id = int(parts[1])
    query = parse.parse_qs(parsed.query)
    version_values = query.get("modelVersionId") or query.get("modelversionid") or []
    version_id = _int_or_none(version_values[0]) if version_values else None
    if model_id is None and version_id is None:
        return None, []
    warnings: list[ValidationIssue] = []
    if model_id is not None and version_id is None:
        warnings.append(
            ValidationIssue(
                code="preferred_primary_model_url_missing_model_version_id",
                message="Preferred Civitai URL has a modelId but no modelVersionId; latest version was not guessed",
                field="preferredPrimaryModelAir",
            )
        )
    return (
        _PreferredIdentity(
            air=None,
            model_id=model_id,
            model_version_id=version_id,
            incomplete=True,
        ),
        warnings,
    )


def _hash_value(raw_hashes: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw_hashes.get(key)
        if value is not None:
            return value
    return None


def _metadata_lookup_str(metadata: ModelResourceMetadata, key: str) -> str | None:
    value = metadata.metadata.get(key)
    if value is None or value == "":
        return None
    return str(value)


def _metadata_lookup_int(metadata: ModelResourceMetadata, key: str) -> int | None:
    value = metadata.metadata.get(key)
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata_lookup_bool(metadata: ModelResourceMetadata, key: str) -> bool | None:
    value = metadata.metadata.get(key)
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    return str(value).strip().lower() in {"1", "true", "yes"}


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _basename(value: str) -> str:
    windows_name = PureWindowsPath(value).name
    posix_name = PurePosixPath(windows_name).name
    return posix_name or windows_name or value


def _normalize_name(value: str) -> str:
    return _basename(value).strip().lower()


def _normalize_label(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("_", " ").replace("-", " ").split())


def _normalize_hash(value: str) -> str:
    return str(value).strip().lower()


__all__ = [
    "MANUAL_PINNED_IDENTITY_SOURCE",
    "MANUAL_PINNED_LOOKUP_STATUS",
    "PREFERRED_PRIMARY_MODEL_AIR_SOURCE",
    "ManualIdentityApplyResult",
    "apply_manual_resource_identities",
    "apply_preferred_primary_model_air",
]
