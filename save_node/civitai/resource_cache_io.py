"""Readable import/export helpers for trusted Civitai identity cache records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from ..metadata.schema import HashMetadata, ValidationIssue
from ..metadata.serialize import sanitize_for_json
from ..version import __version__
from .identity_cache import IdentityCache, IdentityMappingRecord, parse_identity_cache

RESOURCE_CACHE_FORMAT = "comfyui-civitai-save-node.resource-cache"


@dataclass(frozen=True)
class ResourceCacheImportResult:
    cache: IdentityCache
    warnings: tuple[ValidationIssue, ...] = ()
    errors: tuple[ValidationIssue, ...] = ()
    imported_count: int = 0
    skipped_count: int = 0


def export_resource_cache(cache: IdentityCache) -> dict[str, Any]:
    return sanitize_for_json(
        {
            "format": RESOURCE_CACHE_FORMAT,
            "schemaVersion": __version__,
            "generator": {
                "name": "Save Image with Civitai Metadata",
                "version": __version__,
            },
            "exportedAt": _utc_timestamp(),
            "resources": [_record_to_resource(record) for record in cache.records],
        }
    )


def import_resource_cache(
    raw: Any,
    *,
    existing_cache: IdentityCache | None = None,
) -> ResourceCacheImportResult:
    existing_cache = existing_cache or IdentityCache.empty()
    if not isinstance(raw, Mapping):
        return ResourceCacheImportResult(
            cache=existing_cache,
            errors=(
                ValidationIssue(
                    code="resource_cache_schema_invalid",
                    message="Resource cache import must be a JSON object",
                    field="resourceCache",
                ),
            ),
        )
    if raw.get("format") != RESOURCE_CACHE_FORMAT:
        return ResourceCacheImportResult(
            cache=existing_cache,
            errors=(
                ValidationIssue(
                    code="resource_cache_format_invalid",
                    message="Resource cache import format is not supported",
                    field="resourceCache.format",
                ),
            ),
        )
    raw_resources = raw.get("resources")
    if not isinstance(raw_resources, list):
        return ResourceCacheImportResult(
            cache=existing_cache,
            errors=(
                ValidationIssue(
                    code="resource_cache_resources_invalid",
                    message="Resource cache resources must be a JSON array",
                    field="resourceCache.resources",
                ),
            ),
        )

    identity_records = [_resource_to_identity_record(resource) for resource in raw_resources]
    parsed = parse_identity_cache({"records": identity_records}, mapping_source="resource-cache-import")
    warnings = list(parsed.warnings)
    errors = list(parsed.errors)
    merged = list(existing_cache.records)
    imported_count = 0
    skipped_count = 0
    for record in parsed.cache.records:
        conflict_index = _conflict_index(merged, record)
        if conflict_index is None:
            merged.append(record)
            imported_count += 1
            continue
        existing = merged[conflict_index]
        if existing.pinned or existing.locked:
            skipped_count += 1
            warnings.append(
                ValidationIssue(
                    code="resource_cache_import_conflict_preserved_existing",
                    message="Imported resource conflicted with an existing pinned or locked identity and was skipped",
                    field="resourceCache.resources",
                )
            )
            continue
        skipped_count += 1
        warnings.append(
            ValidationIssue(
                code="resource_cache_import_conflict_skipped",
                message="Imported resource conflicted with an existing identity and was skipped",
                field="resourceCache.resources",
            )
        )

    return ResourceCacheImportResult(
        cache=IdentityCache(records=tuple(merged), metadata=existing_cache.metadata),
        warnings=tuple(warnings),
        errors=tuple(errors),
        imported_count=imported_count,
        skipped_count=skipped_count,
    )


def _record_to_resource(record: IdentityMappingRecord) -> dict[str, Any]:
    air = record.air
    data: dict[str, Any] = {
        "canonicalAir": air.canonical,
        "rawAir": air.raw,
        "modelId": record.civitai_model_id,
        "modelVersionId": record.civitai_model_version_id,
        "resourceType": record.resource_type,
        "airType": air.type,
        "hashes": record.hashes.to_json(),
        "aliases": {
            "filenames": [],
            "localNames": [record.model_name] if record.model_name else [],
        },
        "identitySource": "user_pinned_cache" if record.pinned else "local_cache",
        "confidence": record.confidence or ("user_pinned" if record.pinned else "high"),
        "pinned": record.pinned,
        "locked": record.locked,
    }
    if air.file_id:
        data["fileId"] = air.file_id
    if air.format:
        data["format"] = air.format
    if record.usage_notes:
        data["notes"] = record.usage_notes
    if record.source_url:
        data["sourceUrl"] = record.source_url
    return data


def _resource_to_identity_record(resource: Any) -> dict[str, Any]:
    if not isinstance(resource, Mapping):
        return {}
    air_value = resource.get("canonicalAir") or resource.get("rawAir") or resource.get("urn") or resource.get("air")
    if isinstance(air_value, Mapping):
        air_value = air_value.get("canonicalAir") or air_value.get("rawAir") or air_value.get("raw")
    return {
        "air": air_value,
        "civitaiModelId": resource.get("modelId") or resource.get("civitaiModelId"),
        "civitaiModelVersionId": resource.get("modelVersionId") or resource.get("civitaiModelVersionId"),
        "resourceType": resource.get("resourceType") or resource.get("type") or resource.get("airType"),
        "sourceUrl": resource.get("sourceUrl"),
        "usageNotes": resource.get("notes") or resource.get("usageNotes"),
        "hashes": resource.get("hashes") if isinstance(resource.get("hashes"), Mapping) else {},
        "pinned": bool(resource.get("pinned")),
        "locked": bool(resource.get("locked")),
        "confidence": resource.get("confidence"),
    }


def _conflict_index(records: list[IdentityMappingRecord], record: IdentityMappingRecord) -> int | None:
    new_keys = set(_record_hash_keys(record))
    if not new_keys:
        return None
    for index, existing in enumerate(records):
        if not new_keys.intersection(_record_hash_keys(existing)):
            continue
        if _same_identity(existing, record):
            return None
        return index
    return None


def _same_identity(left: IdentityMappingRecord, right: IdentityMappingRecord) -> bool:
    return (
        left.civitai_model_id == right.civitai_model_id
        and left.civitai_model_version_id == right.civitai_model_version_id
        and left.air.canonical == right.air.canonical
    )


def _record_hash_keys(record: IdentityMappingRecord) -> tuple[str, ...]:
    return tuple(f"{algorithm}:{_normalize_hash(value)}" for algorithm, value in _hash_pairs(record.hashes))


def _hash_pairs(hashes: HashMetadata) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for algorithm, attr in (
        ("sha256", "sha256"),
        ("blake3", "blake3"),
        ("auto_v2", "auto_v2"),
        ("auto_v3", "auto_v3"),
        ("crc32", "crc32"),
        ("auto_v1", "auto_v1"),
    ):
        value = getattr(hashes, attr)
        if value:
            pairs.append((algorithm, value))
    return tuple(pairs)


def _normalize_hash(value: str) -> str:
    return str(value).strip().lower()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "RESOURCE_CACHE_FORMAT",
    "ResourceCacheImportResult",
    "export_resource_cache",
    "import_resource_cache",
]
