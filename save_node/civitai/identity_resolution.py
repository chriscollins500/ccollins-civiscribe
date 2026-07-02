"""Apply offline Civitai identity mappings to hashed resources."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .identity_cache import IdentityCache, LOCAL_IDENTITY_SOURCE
from ..hashing.resource_identity import HASHED_BUT_NO_CIVITAI_IDENTITY
from ..metadata.schema import (
    IdentityCacheMetadata,
    ModelResourceMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
)

USER_PINNED_CACHE_SOURCE = "user_pinned_cache"


@dataclass(frozen=True)
class IdentityResolutionResult:
    resources: tuple[ResolvedResource, ...]
    unresolved_resources: tuple[UnresolvedResource, ...]
    identity_cache: IdentityCacheMetadata
    warnings: tuple[ValidationIssue, ...]
    errors: tuple[ValidationIssue, ...]


def apply_identity_cache(
    *,
    resources: tuple[ResolvedResource, ...],
    identity_cache: IdentityCache,
    warnings: tuple[ValidationIssue, ...] = (),
    errors: tuple[ValidationIssue, ...] = (),
) -> IdentityResolutionResult:
    updated: list[ResolvedResource] = []
    resolution_warnings: list[ValidationIssue] = list(warnings)

    for index, resource in enumerate(resources):
        metadata = resource.resource
        if resource.resolved or _has_existing_identity(metadata):
            updated.append(resource)
            continue
        if metadata.hashes.is_empty:
            updated.append(resource)
            continue

        record = identity_cache.lookup(metadata.hashes)
        if record is None:
            if resource.unresolved_reason == HASHED_BUT_NO_CIVITAI_IDENTITY:
                resolution_warnings.append(
                    ValidationIssue(
                        code="resource_hash_no_local_identity_match",
                        message="Resource has local hashes but no local identity cache match",
                        field=f"resources[{index}]",
                    )
                )
            updated.append(resource)
            continue

        resolved_metadata = _apply_record(metadata, record)
        updated.append(
            replace(
                resource,
                resource=resolved_metadata,
                resolved=True,
                unresolved_reason=None,
            )
        )

    updated_tuple = tuple(updated)
    unresolved = tuple(_unresolved_from_resource(resource) for resource in updated_tuple if not resource.resolved)
    return IdentityResolutionResult(
        resources=updated_tuple,
        unresolved_resources=unresolved,
        identity_cache=identity_cache.metadata,
        warnings=tuple(resolution_warnings),
        errors=errors,
    )


def _apply_record(metadata: ModelResourceMetadata, record: object) -> ModelResourceMetadata:
    identity_source = USER_PINNED_CACHE_SOURCE if getattr(record, "pinned", False) else "local_cache"
    confidence = "user_pinned" if getattr(record, "pinned", False) else getattr(record, "confidence", None) or "high"
    return replace(
        metadata,
        air=record.air,
        civitai_model_id=record.civitai_model_id,
        civitai_model_version_id=record.civitai_model_version_id,
        resolution_source=USER_PINNED_CACHE_SOURCE if getattr(record, "pinned", False) else LOCAL_IDENTITY_SOURCE,
        model_name=record.model_name,
        model_version_name=record.model_version_name,
        base_model=record.base_model,
        source_url=record.source_url,
        trigger_words=record.trigger_words,
        license=record.license,
        usage_notes=record.usage_notes,
        metadata={
            **dict(metadata.metadata),
            "lookupStatus": "resolved_by_cache",
            "identitySource": identity_source,
            "confidence": confidence,
            **({"pinned": True} if getattr(record, "pinned", False) else {}),
            **_record_metadata(record),
        },
    )


def _record_metadata(record: object) -> dict[str, object]:
    data: dict[str, object] = {}
    if record.created_at:
        data["identityCreatedAt"] = record.created_at
    if record.updated_at:
        data["identityUpdatedAt"] = record.updated_at
    if record.resource_type:
        data["identityResourceType"] = record.resource_type
    return data


def _has_existing_identity(metadata: ModelResourceMetadata) -> bool:
    return bool(
        metadata.civitai_model_version_id is not None
        or (metadata.air is not None and metadata.air.model_version_id is not None)
    )


def _unresolved_from_resource(resource: ResolvedResource) -> UnresolvedResource:
    metadata = resource.resource
    return UnresolvedResource(
        reason=resource.unresolved_reason or "resource_not_civitai_resolved",
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


__all__ = ["IdentityResolutionResult", "apply_identity_cache"]
