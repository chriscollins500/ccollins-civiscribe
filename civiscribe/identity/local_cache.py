"""Validated local Civitai identity mappings keyed by known hashes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..domain import (
    HashRecord,
    IdentitySource,
    ResourceIdentity,
    ResourceRecord,
    ResourceStatus,
    ScanIssue,
)
from ..serialization import dumps_json
from .air import attach_file_to_air_identity, parse_air
from .cache_store import BoundedJsonCache
from .hash_values import (
    HASH_PRIORITY,
    hash_record_from_mapping,
    hash_record_to_mapping,
    matching_hashes,
    merge_hashes,
)

IDENTITY_CACHE_SCHEMA = "ccollins-civiscribe.identity-cache"
MIN_PRINTABLE_CODEPOINT = 32


@dataclass(frozen=True, slots=True)
class IdentityCacheLookup:
    """One local-cache resolution outcome."""

    identity: ResourceIdentity | None = None
    hashes: HashRecord = field(default_factory=HashRecord)
    status: ResourceStatus = ResourceStatus.UNRESOLVED
    issues: tuple[ScanIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class _ParsedRecord:
    identity: ResourceIdentity
    hashes: HashRecord


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _text(value: object, *, max_chars: int = 512) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > max_chars
        or any(ord(item) < MIN_PRINTABLE_CODEPOINT for item in stripped)
    ):
        return None
    return stripped


def _parse_identity(  # noqa: PLR0911
    value: object,
) -> tuple[ResourceIdentity | None, tuple[ScanIssue, ...]]:
    if not isinstance(value, dict):
        return None, (ScanIssue("identity_cache_record_invalid"),)
    air_text = _text(value.get("canonicalAir"), max_chars=4096) or _text(
        value.get("air"),
        max_chars=4096,
    )
    if air_text is not None:
        parsed = parse_air(air_text, provenance=IdentitySource.CACHE)
        if parsed.identity is None:
            return None, parsed.issues
        identity = parsed.identity
        model_id = _positive_int(value.get("modelId"))
        version_id = _positive_int(value.get("modelVersionId"))
        if model_id is not None and identity.model_id != model_id:
            return None, (*parsed.issues, ScanIssue("identity_cache_model_id_conflict"))
        if version_id is not None and identity.model_version_id != version_id:
            return None, (*parsed.issues, ScanIssue("identity_cache_version_id_conflict"))
        file_id = _text(value.get("fileId"), max_chars=128)
        file_primary = _optional_bool(value.get("filePrimary"))
        if file_id is not None:
            attached = attach_file_to_air_identity(
                identity,
                file_id=file_id,
                file_format=_text(value.get("format"), max_chars=32),
                pin_canonical=file_primary is not True,
            )
            if attached.identity is None:
                return None, (*parsed.issues, *attached.issues)
            identity = attached.identity
        return (
            replace(
                identity,
                file_type=_text(value.get("fileType"), max_chars=64),
                file_primary=file_primary,
                base_model=_text(value.get("baseModel"), max_chars=128),
                model_name=_text(value.get("modelName")),
                model_version_name=_text(value.get("modelVersionName")),
            ),
            parsed.issues,
        )

    model_id = _positive_int(value.get("modelId"))
    version_id = _positive_int(value.get("modelVersionId"))
    if model_id is None and version_id is None:
        return None, (ScanIssue("identity_cache_record_invalid"),)
    return (
        ResourceIdentity(
            source=IdentitySource.CACHE,
            resource_type=_text(value.get("type"), max_chars=64),
            identity_source="civitai",
            identity_id=str(model_id) if model_id is not None else None,
            identity_version=str(version_id) if version_id is not None else None,
            model_id=model_id,
            model_version_id=version_id,
            file_id=_text(value.get("fileId"), max_chars=128),
            format=_text(value.get("format"), max_chars=32),
            file_type=_text(value.get("fileType"), max_chars=64),
            file_primary=_optional_bool(value.get("filePrimary")),
            base_model=_text(value.get("baseModel"), max_chars=128),
            model_name=_text(value.get("modelName")),
            model_version_name=_text(value.get("modelVersionName")),
        ),
        (),
    )


def _parse_record(value: dict[str, object]) -> tuple[_ParsedRecord | None, tuple[ScanIssue, ...]]:
    hashes = hash_record_from_mapping(value.get("hashes"))
    identity, issues = _parse_identity(value.get("identity"))
    if hashes is None or identity is None:
        return None, (*issues, ScanIssue("identity_cache_record_invalid"))
    return _ParsedRecord(identity, hashes), issues


def _identity_json(identity: ResourceIdentity) -> dict[str, object]:
    return {
        "air": identity.canonical_air,
        "canonicalAir": identity.canonical_air,
        "type": identity.resource_type,
        "modelId": identity.model_id,
        "modelVersionId": identity.model_version_id,
        "fileId": identity.file_id,
        "format": identity.format,
        "fileType": identity.file_type,
        "filePrimary": identity.file_primary,
        "baseModel": identity.base_model,
        "modelName": identity.model_name,
        "modelVersionName": identity.model_version_name,
    }


def _cache_key(identity: ResourceIdentity, hashes: HashRecord) -> str:
    source = dumps_json(
        {
            "air": identity.canonical_air,
            "hashes": hash_record_to_mapping(hashes),
            "modelId": identity.model_id,
            "modelVersionId": identity.model_version_id,
        }
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _same_identity(left: ResourceIdentity, right: ResourceIdentity) -> bool:
    if left.canonical_air is not None or right.canonical_air is not None:
        return left.canonical_air == right.canonical_air
    return (
        left.model_id == right.model_id
        and left.model_version_id == right.model_version_id
        and left.resource_type == right.resource_type
    )


def _best_match_rank(resource: HashRecord, cached: HashRecord) -> int | None:
    matches = matching_hashes(resource, cached)
    if not matches:
        return None
    by_name = {name: index for index, (name, _field, _length) in enumerate(HASH_PRIORITY)}
    return min(by_name[name] for name in matches)


class IdentityCache:
    """Separate local identity cache; successful API writes are opt-in."""

    def __init__(self, path: Path) -> None:
        self.store = BoundedJsonCache(path, schema_name=IDENTITY_CACHE_SCHEMA)

    def lookup(self, resource: ResourceRecord) -> IdentityCacheLookup:
        """Resolve one resource by its strongest matching cached hash."""

        read = self.store.read()
        candidates: list[tuple[int, _ParsedRecord]] = []
        issues = list(read.issues)
        for item in read.records:
            parsed, parsed_issues = _parse_record(item)
            issues.extend(parsed_issues)
            if parsed is None:
                continue
            rank = _best_match_rank(resource.hashes, parsed.hashes)
            if rank is not None:
                candidates.append((rank, parsed))
        if not candidates:
            return IdentityCacheLookup(issues=tuple(issues))
        best_rank = min(rank for rank, _record in candidates)
        best = tuple(record for rank, record in candidates if rank == best_rank)
        if any(not _same_identity(best[0].identity, item.identity) for item in best[1:]):
            return IdentityCacheLookup(
                status=ResourceStatus.CONFLICT,
                issues=(*issues, ScanIssue("identity_cache_conflict", node_id=resource.node_id)),
            )
        selected = best[0]
        status = (
            ResourceStatus.RESOLVED
            if selected.identity.canonical_air is not None
            else ResourceStatus.PARTIAL
        )
        return IdentityCacheLookup(
            selected.identity,
            merge_hashes(resource.hashes, selected.hashes),
            status,
            tuple(issues),
        )

    def put(
        self,
        identity: ResourceIdentity,
        hashes: HashRecord,
    ) -> tuple[ScanIssue, ...]:
        """Persist one validated identity mapping without local path data."""

        if hashes.is_empty or (
            identity.canonical_air is None and identity.model_version_id is None
        ):
            return (ScanIssue("identity_cache_record_invalid"),)
        result = self.store.merge(
            {
                "cacheKey": _cache_key(identity, hashes),
                "hashes": hash_record_to_mapping(hashes),
                "identity": _identity_json(identity),
            }
        )
        return result.issues


__all__ = [
    "IDENTITY_CACHE_SCHEMA",
    "IdentityCache",
    "IdentityCacheLookup",
]
