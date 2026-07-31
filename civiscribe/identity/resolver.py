"""Deterministic resource identity orchestration with pixels-first failures."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..domain import (
    HashRecord,
    HashStatus,
    LookupStatus,
    ResourceIdentity,
    ResourceRecord,
    ResourceStatus,
    ScanIssue,
    WorkflowScan,
)
from ..domain.identity import LookupDiagnostics
from .air import attach_file_to_air_identity, parse_air
from .civitai_client import CivitaiClient, CivitaiLookupResult
from .hash_values import HASH_PRIORITY
from .hashing import HashCache, HashResult, hash_resource_file
from .local_cache import IdentityCache
from .manual import apply_explicit_identities
from .resource_types import identity_matches_role
from .types import HashingMode, ResourceFileLocator

HASHED_BUT_NO_CIVITAI_IDENTITY = "hashed_but_no_civitai_identity"
_HTTP_STATUS_MIN = 100
_HTTP_STATUS_MAX = 599
_MAX_DIAGNOSTIC_CANDIDATES = 1_000
_MAX_RETRY_DELAY_SECONDS = 86_400
_SAFE_HASH_TYPES = frozenset(name for name, _field, _length in HASH_PRIORITY)
_SAFE_LOOKUP_REASONS = frozenset(
    {
        "certificate_verify_failed",
        "dns_error",
        "hash_identity_conflict",
        "http_error",
        "identity_conflict",
        "lookup_diagnostic_redacted",
        "lookup_exception",
        "malformed_json",
        "model_version_not_found",
        "multiple_compatible_candidates",
        "multiple_compatible_candidates_conflict",
        "network_error",
        "no_hash_match",
        "no_matching_result",
        "no_role_compatible_shared_hash_candidate",
        "proxy_error",
        "rate_limit_cooldown",
        "rate_limited",
        "redirect_rejected",
        "resource_type_mismatch",
        "response_candidate_limit_exceeded",
        "response_schema_invalid",
        "response_too_large",
        "server_error",
        "timeout",
    }
)
_SAFE_TLS_SOURCES = frozenset({"certifi", "fallback", "system_default", "test", "truststore"})


@dataclass(frozen=True, slots=True)
class IdentityResolutionOptions:
    """User-selected local and optional remote identity policy."""

    hashing_mode: HashingMode = HashingMode.CACHED_OR_FAST
    preferred_primary: str | None = None
    manual_json: str | None = None
    cache_api_results: bool = False


@dataclass(frozen=True, slots=True)
class IdentityServices:
    """Side-effecting adapters supplied at the orchestration boundary."""

    locator: ResourceFileLocator | None = None
    hash_cache: HashCache | None = None
    identity_cache: IdentityCache | None = None
    civitai: CivitaiClient | None = None


@dataclass(frozen=True, slots=True)
class IdentityResolutionResult:
    """Resolved resources and sanitized diagnostics."""

    resources: tuple[ResourceRecord, ...]
    issues: tuple[ScanIssue, ...] = ()


def _deduplicate_issues(issues: list[ScanIssue]) -> tuple[ScanIssue, ...]:
    result: list[ScanIssue] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for issue in issues:
        key = (issue.code, issue.severity.value, issue.node_id, issue.input_name)
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return tuple(result)


def _safe_lookup_diagnostics(result: CivitaiLookupResult) -> LookupDiagnostics:
    attempted = tuple(
        dict.fromkeys(value for value in result.attempted_hashes if value in _SAFE_HASH_TYPES)
    )
    reason = result.diagnostic_reason or result.failure_reason
    if reason is not None and reason not in _SAFE_LOOKUP_REASONS:
        reason = "lookup_diagnostic_redacted"
    http_status = (
        result.http_status
        if isinstance(result.http_status, int)
        and not isinstance(result.http_status, bool)
        and _HTTP_STATUS_MIN <= result.http_status <= _HTTP_STATUS_MAX
        else None
    )

    def safe_count(value: object) -> int | None:
        return (
            value
            if isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= _MAX_DIAGNOSTIC_CANDIDATES
            else None
        )

    attempted_lookup = result.status in {
        LookupStatus.RESOLVED,
        LookupStatus.FAILED,
        LookupStatus.CONFLICT,
    }
    return LookupDiagnostics(
        attempted_hash_types=attempted,
        reason=reason,
        http_status=http_status,
        retryable=result.retryable if attempted_lookup else None,
        retry_after_seconds=(
            result.retry_after_seconds
            if isinstance(result.retry_after_seconds, int)
            and not isinstance(result.retry_after_seconds, bool)
            and 0 <= result.retry_after_seconds <= _MAX_RETRY_DELAY_SECONDS
            else None
        ),
        tls_source=(result.tls_source if result.tls_source in _SAFE_TLS_SOURCES else None),
        candidate_count=safe_count(result.candidate_count),
        compatible_candidate_count=safe_count(result.compatible_candidate_count),
    )


def _merge_computed_hashes(
    current: HashRecord,
    computed: HashRecord,
    *,
    node_id: str,
) -> tuple[HashRecord, tuple[ScanIssue, ...]]:
    values: dict[str, str | None] = {}
    conflict = False
    for _name, field_name, _length in HASH_PRIORITY:
        current_value = getattr(current, field_name)
        computed_value = getattr(computed, field_name)
        if (
            current_value is not None
            and computed_value is not None
            and current_value.casefold() != computed_value.casefold()
        ):
            conflict = True
        values[field_name] = computed_value or current_value
    issues = (ScanIssue("resource_hash_conflict", node_id=node_id),) if conflict else ()
    return HashRecord(**values), issues


def _hash_resource(
    resource: ResourceRecord,
    *,
    options: IdentityResolutionOptions,
    services: IdentityServices,
) -> tuple[ResourceRecord, tuple[ScanIssue, ...]]:
    if services.locator is None:
        return resource, ()
    try:
        located = services.locator.locate(resource)
    except Exception:
        return (
            replace(resource, hash_status=HashStatus.FAILED),
            (ScanIssue("resource_file_location_failed", node_id=resource.node_id),),
        )
    if located is None:
        return (
            replace(resource, hash_status=HashStatus.FILE_NOT_FOUND),
            (ScanIssue("resource_file_not_found", node_id=resource.node_id),),
        )
    try:
        result = hash_resource_file(
            located,
            mode=options.hashing_mode,
            cache=services.hash_cache,
        )
    except Exception:
        result = HashResult(
            status=HashStatus.FAILED,
            issues=(ScanIssue("resource_hash_failed", node_id=resource.node_id),),
        )
    hashes, merge_issues = _merge_computed_hashes(
        resource.hashes,
        result.hashes,
        node_id=resource.node_id,
    )
    return (
        replace(resource, hashes=hashes, hash_status=result.status),
        (*result.issues, *merge_issues),
    )


def _identity_status(identity: ResourceIdentity | None) -> ResourceStatus:
    if identity is None:
        return ResourceStatus.UNRESOLVED
    if identity.canonical_air is None:
        return ResourceStatus.PARTIAL
    if identity.identity_source == "civitai" and identity.model_version_id is None:
        return ResourceStatus.PARTIAL
    return ResourceStatus.RESOLVED


def _validated_existing_identity(
    resource: ResourceRecord,
) -> tuple[ResourceRecord, tuple[ScanIssue, ...]]:
    identity = resource.identity
    if identity is None:
        return resource, ()
    air = identity.raw_air or identity.canonical_air
    if air is None:
        return replace(resource, status=_identity_status(identity)), ()
    parsed = parse_air(air, provenance=identity.source)
    if parsed.identity is None:
        return (
            replace(
                resource,
                identity=None,
                status=ResourceStatus.UNRESOLVED,
                unresolved_reason="workflow_identity_invalid",
            ),
            parsed.issues,
        )
    normalized = replace(
        parsed.identity,
        file_id=parsed.identity.file_id or identity.file_id,
        format=parsed.identity.format or identity.format,
        file_type=identity.file_type,
        file_primary=identity.file_primary,
        base_model=identity.base_model,
        model_name=identity.model_name,
        model_version_name=identity.model_version_name,
    )
    if (
        identity.model_id is not None
        and normalized.model_id is not None
        and identity.model_id != normalized.model_id
    ) or (
        identity.model_version_id is not None
        and normalized.model_version_id is not None
        and identity.model_version_id != normalized.model_version_id
    ):
        return (
            replace(
                resource,
                identity=None,
                status=ResourceStatus.CONFLICT,
                unresolved_reason="workflow_identity_conflict",
            ),
            (*parsed.issues, ScanIssue("workflow_identity_conflict", node_id=resource.node_id)),
        )
    return (
        replace(
            resource,
            identity=normalized,
            status=_identity_status(normalized),
            unresolved_reason=None,
        ),
        parsed.issues,
    )


def _known_facts_conflict(
    pairs: tuple[tuple[object | None, object | None], ...],
) -> bool:
    return any(
        higher is not None and lower is not None and higher != lower for higher, lower in pairs
    )


def _known_formats_conflict(higher: str | None, lower: str | None) -> bool:
    return higher is not None and lower is not None and higher.casefold() != lower.casefold()


def _identities_compatible(
    higher: ResourceIdentity,
    lower: ResourceIdentity,
) -> bool:
    compared = False
    if higher.canonical_air is not None and lower.canonical_air is not None:
        compared = True
        higher_air = parse_air(higher.canonical_air, provenance=higher.source).identity
        lower_air = parse_air(lower.canonical_air, provenance=lower.source).identity
        if higher_air is None or lower_air is None:
            return False
        air_pairs = (
            (higher_air.ecosystem, lower_air.ecosystem),
            (higher_air.resource_type, lower_air.resource_type),
            (higher_air.identity_source, lower_air.identity_source),
            (higher_air.identity_id, lower_air.identity_id),
            (higher_air.identity_version, lower_air.identity_version),
            (higher_air.file_id, lower_air.file_id),
        )
        if _known_facts_conflict(air_pairs) or _known_formats_conflict(
            higher_air.format,
            lower_air.format,
        ):
            return False

    pairs: tuple[tuple[object | None, object | None], ...] = (
        (higher.model_id, lower.model_id),
        (higher.model_version_id, lower.model_version_id),
        (higher.file_id, lower.file_id),
    )
    compared = compared or any(
        higher_fact is not None and lower_fact is not None for higher_fact, lower_fact in pairs
    )
    source_conflict = _known_facts_conflict(((higher.identity_source, lower.identity_source),))
    return (
        compared
        and not _known_facts_conflict(pairs)
        and not source_conflict
        and not _known_formats_conflict(higher.format, lower.format)
    )


def _merged_air_file_details(
    higher: ResourceIdentity,
    lower: ResourceIdentity,
) -> tuple[str | None, str | None, str | None]:
    canonical_air = higher.canonical_air or lower.canonical_air
    if higher.file_id is not None:
        return canonical_air, higher.file_id, higher.format or lower.format
    if lower.file_id is None:
        return canonical_air, None, higher.format or lower.format
    if higher.canonical_air is None:
        return canonical_air, lower.file_id, lower.format
    attached = attach_file_to_air_identity(
        higher,
        file_id=lower.file_id,
        file_format=lower.format,
    )
    if attached.identity is None:
        return canonical_air, None, higher.format
    return (
        attached.identity.canonical_air,
        attached.identity.file_id,
        attached.identity.format,
    )


def _merge_identity(
    higher: ResourceIdentity,
    lower: ResourceIdentity,
) -> ResourceIdentity:
    official_air_fills_partial = higher.canonical_air is None and lower.canonical_air is not None
    canonical_air, file_id, file_format = _merged_air_file_details(higher, lower)
    return ResourceIdentity(
        source=higher.source,
        raw_air=higher.raw_air or lower.raw_air,
        canonical_air=canonical_air,
        ecosystem=(
            lower.ecosystem if official_air_fills_partial else higher.ecosystem or lower.ecosystem
        ),
        resource_type=(
            lower.resource_type
            if official_air_fills_partial
            else higher.resource_type or lower.resource_type
        ),
        identity_source=higher.identity_source or lower.identity_source,
        identity_id=higher.identity_id or lower.identity_id,
        identity_version=higher.identity_version or lower.identity_version,
        model_id=higher.model_id or lower.model_id,
        model_version_id=higher.model_version_id or lower.model_version_id,
        file_id=file_id,
        format=file_format,
        file_type=higher.file_type or lower.file_type,
        file_primary=(
            higher.file_primary if higher.file_primary is not None else lower.file_primary
        ),
        base_model=higher.base_model or lower.base_model,
        model_name=higher.model_name or lower.model_name,
        model_version_name=higher.model_version_name or lower.model_version_name,
    )


def _apply_lower_identity(
    resource: ResourceRecord,
    lower: ResourceIdentity,
    *,
    lower_status: ResourceStatus,
    lookup_status: LookupStatus,
    conflict_code: str,
) -> tuple[ResourceRecord, tuple[ScanIssue, ...]]:
    higher = resource.identity
    if higher is None:
        return (
            replace(
                resource,
                identity=lower,
                status=lower_status,
                lookup_status=lookup_status,
                unresolved_reason=None,
            ),
            (),
        )
    if not _identities_compatible(higher, lower):
        return (
            replace(resource, lookup_status=LookupStatus.CONFLICT),
            (ScanIssue(conflict_code, node_id=resource.node_id),),
        )
    merged = _merge_identity(higher, lower)
    return (
        replace(
            resource,
            identity=merged,
            status=_identity_status(merged),
            lookup_status=lookup_status,
            unresolved_reason=None,
        ),
        (),
    )


def _apply_local_cache(  # noqa: PLR0911
    resource: ResourceRecord,
    cache: IdentityCache | None,
) -> tuple[ResourceRecord, tuple[ScanIssue, ...]]:
    if cache is None or resource.hashes.is_empty:
        return resource, ()
    try:
        result = cache.lookup(resource)
    except Exception:
        return resource, (ScanIssue("identity_cache_read_failed", node_id=resource.node_id),)
    if result.status is ResourceStatus.CONFLICT:
        if resource.identity is None:
            return (
                replace(
                    resource,
                    status=ResourceStatus.CONFLICT,
                    lookup_status=LookupStatus.CONFLICT,
                    unresolved_reason="identity_cache_conflict",
                ),
                result.issues,
            )
        return (
            resource,
            (*result.issues, ScanIssue("identity_cache_lower_precedence_conflict")),
        )
    updated = replace(
        resource,
        hashes=(result.hashes if not result.hashes.is_empty else resource.hashes),
    )
    if result.identity is None:
        return updated, result.issues
    if result.identity.resource_type is not None and not identity_matches_role(
        updated.role, result.identity
    ):
        return (
            replace(updated, unresolved_reason="resource_type_mismatch"),
            (
                *result.issues,
                ScanIssue(
                    "identity_cache_resource_type_mismatch",
                    node_id=resource.node_id,
                ),
            ),
        )
    if updated.identity is not None and not _identities_compatible(
        updated.identity, result.identity
    ):
        return (
            updated,
            (
                *result.issues,
                ScanIssue(
                    "identity_cache_lower_precedence_conflict",
                    node_id=resource.node_id,
                ),
            ),
        )
    applied, issues = _apply_lower_identity(
        updated,
        result.identity,
        lower_status=result.status,
        lookup_status=LookupStatus.RESOLVED_BY_CACHE,
        conflict_code="identity_cache_lower_precedence_conflict",
    )
    return applied, (*result.issues, *issues)


def _lookup_result(
    resource: ResourceRecord,
    client: CivitaiClient,
) -> CivitaiLookupResult:
    identity = resource.identity
    if (
        identity is not None
        and resource.status is ResourceStatus.PARTIAL
        and identity.model_version_id is not None
    ):
        return client.complete_version(resource, identity.model_version_id)
    return client.lookup(resource)


def _apply_api(
    resource: ResourceRecord,
    *,
    services: IdentityServices,
    cache_api_results: bool,
) -> tuple[ResourceRecord, tuple[ScanIssue, ...]]:
    if resource.status is ResourceStatus.RESOLVED:
        return resource, ()
    client = services.civitai
    if client is None:
        return replace(resource, lookup_status=LookupStatus.SKIPPED_DISABLED), ()
    try:
        result = _lookup_result(resource, client)
    except Exception:
        return (
            replace(
                resource,
                lookup_status=LookupStatus.FAILED,
                lookup_diagnostics=LookupDiagnostics(
                    reason="lookup_exception",
                    retryable=False,
                ),
            ),
            (ScanIssue("civitai_lookup_failed", node_id=resource.node_id),),
        )
    merged_hashes, hash_issues = _merge_computed_hashes(
        resource.hashes,
        result.hashes,
        node_id=resource.node_id,
    )
    updated = replace(
        resource,
        hashes=merged_hashes,
        lookup_status=result.status,
        lookup_diagnostics=_safe_lookup_diagnostics(result),
    )
    if result.status is LookupStatus.CONFLICT:
        if resource.identity is None:
            updated = replace(
                updated,
                status=ResourceStatus.CONFLICT,
                unresolved_reason="civitai_identity_conflict",
            )
        return updated, (*result.issues, *hash_issues)
    if result.identity is None:
        if any(
            issue.code
            in {
                "civitai_response_role_match_missing",
                "civitai_response_type_mismatch",
            }
            for issue in result.issues
        ):
            updated = replace(updated, unresolved_reason="resource_type_mismatch")
        return updated, (*result.issues, *hash_issues)
    applied, apply_issues = _apply_lower_identity(
        updated,
        result.identity,
        lower_status=ResourceStatus.RESOLVED,
        lookup_status=LookupStatus.RESOLVED,
        conflict_code="civitai_lower_precedence_identity_conflict",
    )
    cache_issues: tuple[ScanIssue, ...] = ()
    if cache_api_results and services.identity_cache is not None and applied.identity is not None:
        try:
            cache_issues = services.identity_cache.put(
                result.identity,
                applied.hashes,
            )
        except Exception:
            cache_issues = (ScanIssue("identity_cache_write_failed"),)
    return applied, (*result.issues, *hash_issues, *apply_issues, *cache_issues)


def _finalize_resource(resource: ResourceRecord) -> ResourceRecord:
    if resource.status is ResourceStatus.CONFLICT:
        return replace(
            resource,
            unresolved_reason=resource.unresolved_reason or "resource_identity_conflict",
        )
    status = _identity_status(resource.identity)
    if status is ResourceStatus.RESOLVED:
        return replace(resource, status=status, unresolved_reason=None)
    reason = (
        resource.unresolved_reason
        if resource.unresolved_reason == "resource_type_mismatch"
        else None
    ) or (
        "identity_incomplete"
        if status is ResourceStatus.PARTIAL
        else (
            HASHED_BUT_NO_CIVITAI_IDENTITY
            if not resource.hashes.is_empty
            else "resource_hash_unavailable"
        )
    )
    return replace(resource, status=status, unresolved_reason=reason)


def resolve_resource_identities(
    resources: tuple[ResourceRecord, ...],
    *,
    primary_resource_key: str | None,
    options: IdentityResolutionOptions | None = None,
    services: IdentityServices | None = None,
) -> IdentityResolutionResult:
    """Resolve resource hashes and identities without making pixels depend on them."""

    policy = options or IdentityResolutionOptions()
    adapters = services or IdentityServices()
    issues: list[ScanIssue] = []
    hashed: list[ResourceRecord] = []
    for resource in resources:
        updated, resource_issues = _hash_resource(
            resource,
            options=policy,
            services=adapters,
        )
        hashed.append(updated)
        issues.extend(resource_issues)

    try:
        explicit = apply_explicit_identities(
            tuple(hashed),
            primary_resource_key=primary_resource_key,
            preferred_primary=policy.preferred_primary,
            manual_json=policy.manual_json,
        )
        current = explicit.resources
        issues.extend(explicit.issues)
    except Exception:
        current = tuple(hashed)
        issues.append(ScanIssue("explicit_identity_resolution_failed"))

    resolved: list[ResourceRecord] = []
    for resource in current:
        validated, validation_issues = _validated_existing_identity(resource)
        cached, cache_issues = _apply_local_cache(validated, adapters.identity_cache)
        looked_up, lookup_issues = _apply_api(
            cached,
            services=adapters,
            cache_api_results=policy.cache_api_results,
        )
        resolved.append(_finalize_resource(looked_up))
        issues.extend(validation_issues)
        issues.extend(cache_issues)
        issues.extend(lookup_issues)
    return IdentityResolutionResult(tuple(resolved), _deduplicate_issues(issues))


def resolve_scan_identities(
    scan: WorkflowScan,
    *,
    options: IdentityResolutionOptions | None = None,
    services: IdentityServices | None = None,
) -> WorkflowScan:
    """Return one scan with resolved resources and appended safe diagnostics."""

    result = resolve_resource_identities(
        scan.resources,
        primary_resource_key=scan.primary_resource_key,
        options=options,
        services=services,
    )
    return replace(
        scan,
        resources=result.resources,
        issues=(*scan.issues, *result.issues),
    )


__all__ = [
    "HASHED_BUT_NO_CIVITAI_IDENTITY",
    "IdentityResolutionOptions",
    "IdentityResolutionResult",
    "IdentityServices",
    "resolve_resource_identities",
    "resolve_scan_identities",
]
