"""Resource identity values shared by metadata projections and future resolvers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IdentitySource(StrEnum):
    """Trusted source that supplied a resource identity."""

    MANUAL = "manual"
    PREFERRED = "preferred"
    WORKFLOW = "workflow"
    CACHE = "cache"
    API = "api"


class ResourceStatus(StrEnum):
    """Identity-resolution state for an active resource."""

    UNRESOLVED = "unresolved"
    PARTIAL = "partial"
    RESOLVED = "resolved"
    CONFLICT = "conflict"


class HashStatus(StrEnum):
    """Sanitized outcome of local hash resolution."""

    NOT_ATTEMPTED = "not_attempted"
    CACHE_HIT = "cache_hit"
    FAST_PARTIAL = "fast_partial"
    COMPLETE = "complete"
    SKIPPED_CACHED_ONLY = "skipped_cached_only"
    FILE_NOT_FOUND = "file_not_found"
    FILE_NOT_APPROVED = "file_not_approved"
    FILE_CHANGED = "file_changed"
    FAILED = "failed"


class LookupStatus(StrEnum):
    """Sanitized Civitai identity lookup state."""

    NOT_ATTEMPTED = "not_attempted"
    SKIPPED_DISABLED = "skipped_lookup_disabled"
    SKIPPED_NO_HASH = "skipped_no_hash"
    RESOLVED = "resolved"
    RESOLVED_BY_CACHE = "resolved_by_cache"
    FAILED = "failed"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class HashRecord:
    """Supported Civitai hash values without implied computation."""

    auto_v1: str | None = None
    auto_v2: str | None = None
    auto_v3: str | None = None
    sha256: str | None = None
    crc32: str | None = None
    blake3: str | None = None

    @property
    def is_empty(self) -> bool:
        """Return whether no hash value is known."""

        return not any(
            (
                self.auto_v1,
                self.auto_v2,
                self.auto_v3,
                self.sha256,
                self.crc32,
                self.blake3,
            )
        )


@dataclass(frozen=True, slots=True)
class LookupDiagnostics:
    """Sanitized, resource-local Civitai lookup diagnostics."""

    attempted_hash_types: tuple[str, ...] = ()
    reason: str | None = None
    http_status: int | None = None
    retryable: bool | None = None
    retry_after_seconds: int | None = None
    tls_source: str | None = None
    candidate_count: int | None = None
    compatible_candidate_count: int | None = None


@dataclass(frozen=True, slots=True)
class ResourceIdentity:
    """Validated identity facts; AIR parsing and resolution arrive in phase 7."""

    source: IdentitySource
    raw_air: str | None = None
    canonical_air: str | None = None
    ecosystem: str | None = None
    resource_type: str | None = None
    identity_source: str | None = None
    identity_id: str | None = None
    identity_version: str | None = None
    model_id: int | None = None
    model_version_id: int | None = None
    file_id: str | None = None
    format: str | None = None
    file_type: str | None = None
    file_primary: bool | None = None
    base_model: str | None = None
    model_name: str | None = None
    model_version_name: str | None = None


__all__ = [
    "HashRecord",
    "HashStatus",
    "IdentitySource",
    "LookupDiagnostics",
    "LookupStatus",
    "ResourceIdentity",
    "ResourceStatus",
]
