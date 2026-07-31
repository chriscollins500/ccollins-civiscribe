"""Explicit identity parsing with contract-defined precedence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import parse_qs, urlparse

from ..domain import (
    HashRecord,
    IdentitySource,
    ResourceIdentity,
    ResourceRecord,
    ResourceRole,
    ResourceStatus,
    ScanIssue,
)
from .air import parse_air
from .hash_values import (
    hash_record_from_mapping,
    matching_hashes,
)

MAX_MANUAL_JSON_CHARS = 1024 * 1024
MAX_MANUAL_RECORDS = 512
_ASCII_CONTROL_BOUNDARY = 32
_MODEL_PATH_RE = re.compile(r"^/models/([1-9][0-9]*)(?:/[^/?#]+)?/?$")
_SAFE_PARTIAL_TYPES = {
    ResourceRole.BASE_MODEL: "checkpoint",
    ResourceRole.CONTROLNET: "controlnet",
    ResourceRole.EMBEDDING: "embedding",
    ResourceRole.HYPERNETWORK: "hypernet",
    ResourceRole.LORA: "lora",
    ResourceRole.STYLE_MODEL: "other",
    ResourceRole.TEXT_ENCODER: "textencoder",
    ResourceRole.VISION_ENCODER: "other",
    ResourceRole.MODEL_PATCH: "other",
    ResourceRole.AUXILIARY_MODEL: "other",
    ResourceRole.MOTION_MODULE: "motion",
    ResourceRole.GLIGEN: "other",
    ResourceRole.UPSCALER: "upscaler",
    ResourceRole.VAE: "vae",
}


@dataclass(frozen=True, slots=True)
class ExplicitIdentityResult:
    """Resources after manual and preferred identities plus safe diagnostics."""

    resources: tuple[ResourceRecord, ...]
    issues: tuple[ScanIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class _ManualMatch:
    resource_key: str | None = None
    node_id: str | None = None
    filename: str | None = None
    selected_value: str | None = None
    hashes: HashRecord = field(default_factory=HashRecord)

    @property
    def has_selector(self) -> bool:
        return bool(
            self.resource_key
            or self.node_id
            or self.filename
            or self.selected_value
            or not self.hashes.is_empty
        )


@dataclass(frozen=True, slots=True)
class _ManualRecord:
    match: _ManualMatch
    identity: ResourceIdentity
    status: ResourceStatus


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdecimal():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _text(value: object, *, max_chars: int = 512) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > max_chars
        or any(ord(character) < _ASCII_CONTROL_BOUNDARY for character in stripped)
    ):
        return None
    return stripped


def _safe_relative(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    normalized = text.replace("\\", "/")
    windows = PureWindowsPath(text)
    posix = PurePosixPath(normalized)
    if (
        windows.drive
        or windows.root
        or posix.is_absolute()
        or ":" in normalized
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        return None
    return normalized


def _identity_status(identity: ResourceIdentity) -> ResourceStatus:
    if identity.canonical_air is None:
        return ResourceStatus.PARTIAL
    if identity.identity_source == "civitai" and identity.model_version_id is None:
        return ResourceStatus.PARTIAL
    return ResourceStatus.RESOLVED


def _identity_from_ids(
    values: Mapping[str, object],
    *,
    source: IdentitySource,
) -> ResourceIdentity | None:
    model_id = _positive_int(values.get("modelId"))
    version_id = _positive_int(values.get("modelVersionId"))
    if model_id is None and version_id is None:
        return None
    return ResourceIdentity(
        source=source,
        resource_type=_text(values.get("type"), max_chars=64),
        identity_source="civitai",
        identity_id=str(model_id) if model_id is not None else None,
        identity_version=str(version_id) if version_id is not None else None,
        model_id=model_id,
        model_version_id=version_id,
        file_id=_text(values.get("fileId"), max_chars=128),
        format=_text(values.get("format"), max_chars=32),
        base_model=_text(values.get("baseModel"), max_chars=128),
        model_name=_text(values.get("modelName")),
        model_version_name=_text(values.get("modelVersionName")),
    )


def _identity_from_values(
    values: Mapping[str, object],
    *,
    source: IdentitySource,
) -> tuple[ResourceIdentity | None, tuple[ScanIssue, ...]]:
    air_text = _text(values.get("air"), max_chars=4096) or _text(
        values.get("urn"),
        max_chars=4096,
    )
    if air_text is None:
        identity = _identity_from_ids(values, source=source)
        return identity, (() if identity is not None else (ScanIssue("manual_identity_missing"),))

    parsed = parse_air(air_text, provenance=source)
    if parsed.identity is None:
        return None, parsed.issues
    identity = parsed.identity
    model_id = _positive_int(values.get("modelId"))
    version_id = _positive_int(values.get("modelVersionId"))
    if model_id is not None and model_id != identity.model_id:
        return None, (*parsed.issues, ScanIssue("manual_identity_model_id_conflict"))
    if version_id is not None and version_id != identity.model_version_id:
        return None, (*parsed.issues, ScanIssue("manual_identity_version_id_conflict"))
    return (
        replace(
            identity,
            base_model=_text(values.get("baseModel"), max_chars=128),
            model_name=_text(values.get("modelName")),
            model_version_name=_text(values.get("modelVersionName")),
        ),
        parsed.issues,
    )


def _manual_match(value: object) -> _ManualMatch | None:
    if not isinstance(value, Mapping):
        return None
    hashes = hash_record_from_mapping(value.get("hashes")) or HashRecord()
    match = _ManualMatch(
        resource_key=_text(value.get("resourceKey")),
        node_id=_text(value.get("nodeId"), max_chars=128),
        filename=(
            PurePosixPath(filename).name
            if (filename := _safe_relative(value.get("filename"))) is not None
            else None
        ),
        selected_value=_safe_relative(value.get("selectedValue")),
        hashes=hashes,
    )
    return match if match.has_selector else None


def _manual_records(text: str | None) -> tuple[tuple[_ManualRecord, ...], tuple[ScanIssue, ...]]:
    if text is None or text.strip() in {"", "[]"}:
        return (), ()
    if len(text) > MAX_MANUAL_JSON_CHARS:
        return (), (ScanIssue("manual_identity_json_too_large"),)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return (), (ScanIssue("manual_identity_json_invalid"),)
    if not isinstance(payload, list):
        return (), (ScanIssue("manual_identity_json_schema_invalid"),)

    records: list[_ManualRecord] = []
    issues: list[ScanIssue] = []
    if len(payload) > MAX_MANUAL_RECORDS:
        payload = payload[:MAX_MANUAL_RECORDS]
        issues.append(ScanIssue("manual_identity_record_limit_reached"))
    for item in payload:
        if not isinstance(item, Mapping):
            issues.append(ScanIssue("manual_identity_record_invalid"))
            continue
        match = _manual_match(item.get("match"))
        identity, identity_issues = _identity_from_values(item, source=IdentitySource.MANUAL)
        issues.extend(identity_issues)
        if match is None or identity is None:
            issues.append(ScanIssue("manual_identity_record_invalid"))
            continue
        records.append(_ManualRecord(match, identity, _identity_status(identity)))
    return tuple(records), tuple(issues)


def _match_score(resource: ResourceRecord, match: _ManualMatch) -> int | None:
    score = 0
    selectors = (
        (match.resource_key, resource.key, 100),
        (match.node_id, resource.node_id, 80),
        (match.selected_value, resource.selected_value, 40),
        (match.filename, resource.filename, 20),
    )
    for expected, actual, weight in selectors:
        if expected is None:
            continue
        if expected.casefold() != actual.casefold():
            return None
        score += weight
    if not match.hashes.is_empty:
        if not matching_hashes(resource.hashes, match.hashes):
            return None
        score += 60
    return score


def _same_identity(left: ResourceIdentity, right: ResourceIdentity) -> bool:
    if left.canonical_air is not None or right.canonical_air is not None:
        return left.canonical_air == right.canonical_air
    return (
        left.model_id == right.model_id
        and left.model_version_id == right.model_version_id
        and left.resource_type == right.resource_type
    )


def _safe_partial_type(resource: ResourceRecord, identity: ResourceIdentity) -> ResourceIdentity:
    if identity.resource_type is not None:
        return identity
    return replace(identity, resource_type=_SAFE_PARTIAL_TYPES.get(resource.role))


def _apply_manual_record(
    resource: ResourceRecord,
    records: tuple[_ManualRecord, ...],
) -> tuple[ResourceRecord, tuple[ScanIssue, ...]]:
    scored = tuple(
        (score, record)
        for record in records
        if (score := _match_score(resource, record.match)) is not None
    )
    if not scored:
        return resource, ()
    best_score = max(score for score, _record in scored)
    best = tuple(record for score, record in scored if score == best_score)
    if any(not _same_identity(best[0].identity, item.identity) for item in best[1:]):
        return (
            replace(
                resource,
                identity=None,
                status=ResourceStatus.CONFLICT,
                unresolved_reason="manual_identity_conflict",
            ),
            (ScanIssue("manual_identity_conflict", node_id=resource.node_id),),
        )
    selected = best[0]
    identity = _safe_partial_type(resource, selected.identity)
    return (
        replace(
            resource,
            identity=identity,
            status=selected.status,
            unresolved_reason=None,
        ),
        (),
    )


def _preferred_from_url(value: str) -> tuple[ResourceIdentity | None, tuple[ScanIssue, ...]]:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname not in {"civitai.com", "www.civitai.com"}
        or parsed.port not in {None, 443}
    ):
        return None, (ScanIssue("preferred_identity_url_invalid"),)
    match = _MODEL_PATH_RE.fullmatch(parsed.path)
    if match is None:
        return None, (ScanIssue("preferred_identity_url_invalid"),)
    query = parse_qs(parsed.query, keep_blank_values=True)
    versions = query.get("modelVersionId", [])
    model_id = int(match.group(1))
    version_id = _positive_int(versions[0]) if len(versions) == 1 else None
    issues = () if version_id is not None else (ScanIssue("preferred_identity_version_missing"),)
    return (
        ResourceIdentity(
            source=IdentitySource.PREFERRED,
            resource_type="checkpoint",
            identity_source="civitai",
            identity_id=str(model_id),
            identity_version=str(version_id) if version_id is not None else None,
            model_id=model_id,
            model_version_id=version_id,
        ),
        issues,
    )


def _preferred_identity(value: str | None) -> tuple[ResourceIdentity | None, tuple[ScanIssue, ...]]:
    text = _text(value, max_chars=4096)
    if text is None:
        return None, ()
    if text.isdecimal():
        version_id = _positive_int(text)
        if version_id is None:
            return None, (ScanIssue("preferred_identity_invalid"),)
        return (
            ResourceIdentity(
                source=IdentitySource.PREFERRED,
                resource_type="checkpoint",
                identity_source="civitai",
                identity_version=str(version_id),
                model_version_id=version_id,
            ),
            (),
        )
    if text.startswith("https://"):
        return _preferred_from_url(text)
    result = parse_air(text, provenance=IdentitySource.PREFERRED)
    return result.identity, result.issues


def apply_explicit_identities(
    resources: tuple[ResourceRecord, ...],
    *,
    primary_resource_key: str | None,
    preferred_primary: str | None = None,
    manual_json: str | None = None,
) -> ExplicitIdentityResult:
    """Apply manual mappings before the preferred-primary identity."""

    records, issues = _manual_records(manual_json)
    resolved: list[ResourceRecord] = []
    for resource in resources:
        updated, resource_issues = _apply_manual_record(resource, records)
        resolved.append(updated)
        issues = (*issues, *resource_issues)

    preferred, preferred_issues = _preferred_identity(preferred_primary)
    issues = (*issues, *preferred_issues)
    if preferred is not None and primary_resource_key is not None:
        for index, resource in enumerate(resolved):
            if resource.key != primary_resource_key:
                continue
            if resource.identity is not None and resource.identity.source is IdentitySource.MANUAL:
                break
            identity = _safe_partial_type(resource, preferred)
            resolved[index] = replace(
                resource,
                identity=identity,
                status=_identity_status(identity),
                unresolved_reason=None,
            )
            break
    return ExplicitIdentityResult(tuple(resolved), tuple(issues))


__all__ = [
    "MAX_MANUAL_JSON_CHARS",
    "MAX_MANUAL_RECORDS",
    "ExplicitIdentityResult",
    "apply_explicit_identities",
]
