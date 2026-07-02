"""Optional Civitai API lookup by local model hash.

The lookup layer sends only hash values. It never sends prompts, workflow data,
image bytes, sidecar content, local paths, filenames, or node labels.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import socket
import ssl
from typing import Any, Mapping, Protocol
from urllib import error, parse, request

from ..version import __version__
from ..security.redaction import sanitize_metadata_text
from .air import parse_air
from .identity_cache import (
    IdentityCache,
    IdentityMappingRecord,
    generated_identity_cache_path,
    load_identity_cache,
    write_identity_cache,
)
from .manual_identities import (
    MANUAL_PINNED_IDENTITY_SOURCE,
    MANUAL_PINNED_LOOKUP_STATUS,
    PREFERRED_PRIMARY_MODEL_AIR_SOURCE,
)
from ..hashing.resource_identity import HASHED_BUT_NO_CIVITAI_IDENTITY
from ..metadata.schema import (
    AIRMetadata,
    HashMetadata,
    ModelResourceMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
)

DEFAULT_API_BASE_URL = "https://civitai.com/api/v1"
DEFAULT_LOOKUP_TIMEOUT_SECONDS = 4.0
GENERATED_CACHE_MAPPING_SOURCE = "civitai_api_hash_lookup_generated_cache"
LOOKUP_RESOLUTION_SOURCE = "civitai_api_hash_lookup"

_HASH_RE = re.compile(r"^[A-Fa-f0-9]{8,128}$")


def create_verified_ssl_context() -> tuple[ssl.SSLContext, str]:
    """Create a verified HTTPS context, preferring certifi when installed."""

    try:
        import certifi  # type: ignore

        certifi_path = certifi.where()
        if certifi_path:
            return ssl.create_default_context(cafile=certifi_path), "certifi"
    except Exception:
        pass
    return ssl.create_default_context(), "system_default"


@dataclass(frozen=True)
class CivitaiLookupSettings:
    enabled: bool = False
    prefer_sha256: bool = True
    timeout_seconds: float = DEFAULT_LOOKUP_TIMEOUT_SECONDS
    cache_results: bool = False
    base_url: str = DEFAULT_API_BASE_URL
    generated_cache_path: Path = generated_identity_cache_path()


@dataclass(frozen=True)
class CivitaiHttpResponse:
    status: int
    body: bytes
    lookup_client: str | None = None
    ssl_context_source: str | None = None


class CivitaiHttpTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        timeout_seconds: float,
        headers: Mapping[str, str],
        max_response_bytes: int,
    ) -> CivitaiHttpResponse: ...


@dataclass(frozen=True)
class CivitaiApiIdentity:
    civitai_model_id: int | None
    civitai_model_version_id: int
    hashes: HashMetadata
    air: AIRMetadata | None = None
    model_name: str | None = None
    model_version_name: str | None = None
    resource_type: str | None = None
    base_model: str | None = None
    trigger_words: tuple[str, ...] = ()
    source_url: str | None = None
    lookup_timestamp: str | None = None

    def to_identity_record(self) -> IdentityMappingRecord | None:
        if self.air is None or self.civitai_model_id is None:
            return None
        return IdentityMappingRecord(
            air=self.air,
            civitai_model_id=self.civitai_model_id,
            civitai_model_version_id=self.civitai_model_version_id,
            hashes=self.hashes,
            model_name=self.model_name,
            model_version_name=self.model_version_name,
            resource_type=self.resource_type,
            base_model=self.base_model,
            source_url=self.source_url,
            trigger_words=self.trigger_words,
            created_at=self.lookup_timestamp,
            updated_at=self.lookup_timestamp,
        )


@dataclass(frozen=True)
class CivitaiLookupAttempt:
    identity: CivitaiApiIdentity | None = None
    warnings: tuple[ValidationIssue, ...] = ()
    hash_algorithm: str | None = None
    result: str = "unresolved"
    failure_reason: str | None = None
    failure_class: str | None = None
    failure_detail_sanitized: str | None = None
    http_status: int | None = None
    retryable: bool = False
    lookup_client: str | None = None
    ssl_context_source: str | None = None
    api_endpoint_kind: str | None = None


@dataclass(frozen=True)
class CivitaiApiResolutionResult:
    resources: tuple[ResolvedResource, ...]
    unresolved_resources: tuple[UnresolvedResource, ...]
    warnings: tuple[ValidationIssue, ...] = ()
    errors: tuple[ValidationIssue, ...] = ()
    cache_records: tuple[IdentityMappingRecord, ...] = ()
    lookup_debug_summary: tuple[dict[str, object], ...] = ()


class StandardLibraryCivitaiTransport:
    def __init__(self, ssl_context: ssl.SSLContext | None = None, ssl_context_source: str | None = None) -> None:
        if ssl_context is not None:
            source = ssl_context_source or "system_default"
            self._contexts = ((ssl_context, source),)
        else:
            context, source = create_verified_ssl_context()
            contexts: list[tuple[ssl.SSLContext, str]] = [(context, source)]
            if source == "certifi":
                contexts.append((ssl.create_default_context(), "system_default"))
            self._contexts = tuple(contexts)
        self.ssl_context = self._contexts[0][0]
        self.ssl_context_source = self._contexts[0][1]
        self.lookup_client = "urllib_certifi" if self.ssl_context_source == "certifi" else "urllib"

    def get(
        self,
        url: str,
        *,
        timeout_seconds: float,
        headers: Mapping[str, str],
        max_response_bytes: int,
    ) -> CivitaiHttpResponse:
        req = request.Request(url, headers=dict(headers), method="GET")
        last_exception: BaseException | None = None
        for index, (context, source) in enumerate(self._contexts):
            self.ssl_context = context
            self.ssl_context_source = source
            self.lookup_client = "urllib_certifi" if source == "certifi" else "urllib"
            try:
                with request.urlopen(req, timeout=timeout_seconds, context=context) as response:
                    body = response.read(max_response_bytes + 1)
                    if len(body) > max_response_bytes:
                        raise ValueError("response_too_large")
                    return CivitaiHttpResponse(
                        status=int(response.status),
                        body=body,
                        lookup_client=self.lookup_client,
                        ssl_context_source=source,
                    )
            except error.HTTPError as exc:
                body = exc.read(max_response_bytes + 1)
                return CivitaiHttpResponse(
                    status=int(exc.code),
                    body=body[:max_response_bytes],
                    lookup_client=self.lookup_client,
                    ssl_context_source=source,
                )
            except (error.URLError, OSError) as exc:
                last_exception = exc
                if index + 1 < len(self._contexts) and _is_ssl_certificate_failure(exc):
                    continue
                raise
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("no_ssl_context_available")


class CivitaiApiClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_API_BASE_URL,
        transport: CivitaiHttpTransport | None = None,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self.base_url = _validated_https_base_url(base_url)
        self.transport = transport or StandardLibraryCivitaiTransport()
        self.max_response_bytes = max_response_bytes
        self.lookup_client = str(getattr(self.transport, "lookup_client", "custom"))
        self.ssl_context_source = str(getattr(self.transport, "ssl_context_source", "unavailable"))

    def _attempt_context(self, endpoint_kind: str, response: CivitaiHttpResponse | None = None) -> dict[str, str]:
        lookup_client = (
            response.lookup_client
            if response is not None and response.lookup_client
            else str(getattr(self.transport, "lookup_client", self.lookup_client))
        )
        ssl_context_source = (
            response.ssl_context_source
            if response is not None and response.ssl_context_source
            else str(getattr(self.transport, "ssl_context_source", self.ssl_context_source))
        )
        return {
            "lookup_client": lookup_client,
            "ssl_context_source": ssl_context_source,
            "api_endpoint_kind": endpoint_kind,
        }

    def lookup_by_hash(
        self,
        *,
        hash_value: str,
        hash_algorithm: str,
        resource: ModelResourceMetadata,
        timeout_seconds: float,
        field: str,
    ) -> CivitaiLookupAttempt:
        normalized_hash = _normalize_hash(hash_value)
        if not _HASH_RE.fullmatch(normalized_hash):
            return CivitaiLookupAttempt(
                hash_algorithm=hash_algorithm,
                result="skipped",
                failure_reason="invalid_hash",
                failure_class="invalid_hash",
                **self._attempt_context("by_hash"),
                warnings=(
                    ValidationIssue(
                        code="civitai_api_invalid_hash",
                        message="Civitai lookup skipped an invalid hash value",
                        field=field,
                    ),
                ),
            )

        url = _lookup_url(self.base_url, normalized_hash)
        headers = {
            "Accept": "application/json",
            "User-Agent": f"ComfyUI-Civitai-Save-Node/{__version__}",
        }
        try:
            response = self.transport.get(
                url,
                timeout_seconds=max(0.1, float(timeout_seconds)),
                headers=headers,
                max_response_bytes=self.max_response_bytes,
            )
        except (TimeoutError, socket.timeout):
            return _transport_failure_attempt(
                hash_algorithm=hash_algorithm,
                classification=_classify_transport_error(TimeoutError()),
                field=field,
                **self._attempt_context("by_hash"),
            )
        except error.URLError as exc:
            return _transport_failure_attempt(
                hash_algorithm=hash_algorithm,
                classification=_classify_transport_error(exc.reason),
                field=field,
                **self._attempt_context("by_hash"),
            )
        except OSError as exc:
            return _transport_failure_attempt(
                hash_algorithm=hash_algorithm,
                classification=_classify_transport_error(exc),
                field=field,
                **self._attempt_context("by_hash"),
            )
        except ValueError:
            return CivitaiLookupAttempt(
                hash_algorithm=hash_algorithm,
                result="unresolved",
                failure_reason="response_too_large",
                failure_class="response_too_large",
                **self._attempt_context("by_hash"),
                warnings=(
                    ValidationIssue(
                        code="civitai_api_response_too_large",
                        message="Civitai hash lookup response was too large",
                        field=field,
                    ),
                ),
            )

        if response.status < 200 or response.status >= 300:
            reason, retryable = _classify_http_status(response.status)
            return _http_failure_attempt(
                hash_algorithm=hash_algorithm,
                status=response.status,
                reason=reason,
                retryable=retryable,
                body=response.body,
                field=field,
                **self._attempt_context("by_hash", response),
            )

        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return CivitaiLookupAttempt(
                hash_algorithm=hash_algorithm,
                result="unresolved",
                failure_reason="malformed_json",
                failure_class="malformed_json",
                http_status=response.status,
                retryable=False,
                **self._attempt_context("by_hash", response),
                warnings=(
                    ValidationIssue(
                        code="civitai_api_invalid_json",
                        message="Civitai hash lookup returned invalid JSON",
                        field=field,
                    ),
                ),
            )

        payload, detail_warnings = self._maybe_enrich_payload_with_air(
            payload,
            resource=resource,
            timeout_seconds=timeout_seconds,
            field=field,
        )
        identity, warnings = _identity_from_payload(
            payload,
            queried_hash=normalized_hash,
            hash_algorithm=hash_algorithm,
            resource=resource,
            field=field,
        )
        warnings = (*detail_warnings, *warnings)
        if identity is None:
            return CivitaiLookupAttempt(
                identity=None,
                warnings=warnings,
                hash_algorithm=hash_algorithm,
                result="unresolved",
                failure_reason=_failure_reason_from_warnings(warnings),
                failure_class=_failure_reason_from_warnings(warnings),
                http_status=response.status,
                **self._attempt_context("by_hash", response),
            )
        return CivitaiLookupAttempt(
            identity=identity,
            warnings=warnings,
            hash_algorithm=hash_algorithm,
            result="resolved",
            http_status=response.status,
            **self._attempt_context("by_hash", response),
        )

    def lookup_model_version_identity(
        self,
        *,
        model_version_id: int,
        resource: ModelResourceMetadata,
        timeout_seconds: float,
        field: str,
    ) -> CivitaiLookupAttempt:
        url = _model_version_url(self.base_url, model_version_id)
        headers = {
            "Accept": "application/json",
            "User-Agent": f"ComfyUI-Civitai-Save-Node/{__version__}",
        }
        try:
            response = self.transport.get(
                url,
                timeout_seconds=max(0.1, float(timeout_seconds)),
                headers=headers,
                max_response_bytes=self.max_response_bytes,
            )
        except (TimeoutError, socket.timeout):
            return _transport_failure_attempt(
                hash_algorithm="modelVersionId",
                classification=_classify_transport_error(TimeoutError()),
                field=field,
                **self._attempt_context("by_model_version"),
            )
        except error.URLError as exc:
            return _transport_failure_attempt(
                hash_algorithm="modelVersionId",
                classification=_classify_transport_error(exc.reason),
                field=field,
                **self._attempt_context("by_model_version"),
            )
        except OSError as exc:
            return _transport_failure_attempt(
                hash_algorithm="modelVersionId",
                classification=_classify_transport_error(exc),
                field=field,
                **self._attempt_context("by_model_version"),
            )
        except ValueError:
            return CivitaiLookupAttempt(
                hash_algorithm="modelVersionId",
                result="unresolved",
                failure_reason="response_too_large",
                failure_class="response_too_large",
                **self._attempt_context("by_model_version"),
                warnings=(
                    ValidationIssue(
                        code="civitai_api_response_too_large",
                        message="Civitai model-version lookup response was too large",
                        field=field,
                    ),
                ),
            )

        if response.status < 200 or response.status >= 300:
            reason, retryable = _classify_http_status(response.status)
            return _http_failure_attempt(
                hash_algorithm="modelVersionId",
                status=response.status,
                reason=reason,
                retryable=retryable,
                body=response.body,
                field=field,
                **self._attempt_context("by_model_version", response),
            )

        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return CivitaiLookupAttempt(
                hash_algorithm="modelVersionId",
                result="unresolved",
                failure_reason="malformed_json",
                failure_class="malformed_json",
                http_status=response.status,
                retryable=False,
                **self._attempt_context("by_model_version", response),
                warnings=(
                    ValidationIssue(
                        code="civitai_api_invalid_json",
                        message="Civitai model-version lookup returned invalid JSON",
                        field=field,
                    ),
                ),
            )

        identity, warnings = _identity_from_model_version_payload(
            payload,
            requested_model_version_id=model_version_id,
            resource=resource,
            field=field,
        )
        if identity is None:
            return CivitaiLookupAttempt(
                identity=None,
                warnings=warnings,
                hash_algorithm="modelVersionId",
                result="unresolved",
                failure_reason=_failure_reason_from_warnings(warnings),
                failure_class=_failure_reason_from_warnings(warnings),
                http_status=response.status,
                **self._attempt_context("by_model_version", response),
            )
        return CivitaiLookupAttempt(
            identity=identity,
            warnings=warnings,
            hash_algorithm="modelVersionId",
            result="resolved",
            http_status=response.status,
            **self._attempt_context("by_model_version", response),
        )

    def _maybe_enrich_payload_with_air(
        self,
        payload: Any,
        *,
        resource: ModelResourceMetadata,
        timeout_seconds: float,
        field: str,
    ) -> tuple[Any, tuple[ValidationIssue, ...]]:
        if not isinstance(payload, Mapping) or _string_or_none(payload.get("air")):
            return payload, ()
        model_version_id = _int_or_none(payload.get("modelVersionId") or payload.get("id"))
        if model_version_id is None or not _should_fetch_model_version_air(payload, resource):
            return payload, ()

        url = _model_version_url(self.base_url, model_version_id)
        headers = {
            "Accept": "application/json",
            "User-Agent": f"ComfyUI-Civitai-Save-Node/{__version__}",
        }
        try:
            response = self.transport.get(
                url,
                timeout_seconds=max(0.1, float(timeout_seconds)),
                headers=headers,
                max_response_bytes=self.max_response_bytes,
            )
        except (TimeoutError, socket.timeout):
            return payload, (
                ValidationIssue(
                    code="civitai_api_model_version_air_timeout",
                    message="Civitai model-version AIR lookup timed out",
                    field=field,
                ),
            )
        except (OSError, ValueError, IndexError):
            return payload, (
                ValidationIssue(
                    code="civitai_api_model_version_air_lookup_failed",
                    message="Civitai model-version AIR lookup failed",
                    field=field,
                ),
            )
        if response.status < 200 or response.status >= 300:
            return payload, (
                ValidationIssue(
                    code="civitai_api_model_version_air_http_error",
                    message=f"Civitai model-version AIR lookup returned HTTP status {response.status}",
                    field=field,
                ),
            )
        try:
            detail_payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return payload, (
                ValidationIssue(
                    code="civitai_api_model_version_air_invalid_json",
                    message="Civitai model-version AIR lookup returned invalid JSON",
                    field=field,
                ),
            )
        if not isinstance(detail_payload, Mapping):
            return payload, (
                ValidationIssue(
                    code="civitai_api_model_version_air_schema_invalid",
                    message="Civitai model-version AIR lookup did not return an object",
                    field=field,
                ),
            )
        air = _string_or_none(detail_payload.get("air"))
        if not air:
            return payload, (
                ValidationIssue(
                    code="civitai_api_model_version_air_missing",
                    message="Civitai model-version details did not include AIR",
                    field=field,
                ),
            )
        enriched = dict(payload)
        enriched["air"] = air
        return enriched, ()


def resolve_resources_with_civitai_api(
    *,
    resources: tuple[ResolvedResource, ...],
    settings: CivitaiLookupSettings,
    client: CivitaiApiClient | None = None,
) -> CivitaiApiResolutionResult:
    if not settings.enabled:
        updated = tuple(_with_lookup_disabled_metadata(resource) for resource in resources)
        return CivitaiApiResolutionResult(
            resources=updated,
            unresolved_resources=_unresolved_resources(updated),
            lookup_debug_summary=tuple(
                _lookup_debug_item(
                    resource,
                    (),
                    _debug_result_for_resource(resource),
                    None if resource.resolved else "lookup_disabled",
                    (),
                )
                for resource in updated
            ),
        )

    warnings: list[ValidationIssue] = []
    updated: list[ResolvedResource] = []
    cache_records: list[IdentityMappingRecord] = []
    lookup_debug: list[dict[str, object]] = []

    try:
        lookup_client = client or CivitaiApiClient(base_url=settings.base_url)
    except ValueError:
        return CivitaiApiResolutionResult(
            resources=resources,
            unresolved_resources=_unresolved_resources(resources),
            errors=(
                ValidationIssue(
                    code="civitai_api_base_url_rejected",
                    message="Civitai API base URL must be HTTPS",
                    field="civitaiLookup.baseUrl",
                ),
            ),
        )

    for index, resource in enumerate(resources):
        metadata = resource.resource
        if _is_manual_pinned_resource(metadata):
            updated_resource, resource_warnings, debug_item = _resolve_manual_pinned_with_optional_api(
                resource=resource,
                index=index,
                lookup_client=lookup_client,
                settings=settings,
            )
            warnings.extend(resource_warnings)
            updated.append(updated_resource)
            lookup_debug.append(debug_item)
            continue
        if resource.resolved or _has_civitai_identity(metadata):
            status = (
                "resolved_by_cache"
                if metadata.resolution_source in {"local_identity_cache", "user_pinned_cache"}
                else "resolved"
            )
            updated_resource = _with_lookup_metadata(resource, status=status)
            updated.append(updated_resource)
            lookup_debug.append(_lookup_debug_item(updated_resource, (), "resolved", None, ()))
            continue
        if metadata.hashes.is_empty:
            updated_resource = _with_lookup_metadata(resource, status="skipped_no_hash", reason="missing_hash")
            updated.append(updated_resource)
            lookup_debug.append(_lookup_debug_item(updated_resource, (), "unresolved", "missing_hash", ()))
            continue

        identity = None
        field = f"resources[{index}]"
        attempts: list[CivitaiLookupAttempt] = []
        identity_warnings: tuple[ValidationIssue, ...] = ()
        for hash_algorithm, hash_value in _lookup_hash_order(metadata.hashes, settings.prefer_sha256):
            attempt = lookup_client.lookup_by_hash(
                hash_value=hash_value,
                hash_algorithm=hash_algorithm,
                resource=metadata,
                timeout_seconds=settings.timeout_seconds,
                field=field,
            )
            attempts.append(attempt)
            if attempt.identity is not None:
                identity = attempt.identity
                identity_warnings = attempt.warnings
                break

        if identity is None:
            summary_warning = _lookup_summary_warning(resource, attempts, field)
            if summary_warning is not None:
                warnings.append(summary_warning)
            updated_resource = _with_lookup_metadata(
                resource,
                status="failed",
                reason=_summary_failure_reason(attempts),
                failure_class=_summary_failure_class(attempts),
                failure_detail_sanitized=_summary_failure_detail(attempts),
                attempted_hash_types=_attempted_hash_types(attempts),
                status_code=_summary_status_code(attempts),
                retryable=_summary_retryable(attempts),
                lookup_client=_summary_lookup_client(attempts),
                ssl_context_source=_summary_ssl_context_source(attempts),
                api_endpoint_kind=_summary_endpoint_kind(attempts),
            )
            updated.append(updated_resource)
            lookup_debug.append(
                _lookup_debug_item(
                    updated_resource,
                    _attempted_hash_types(attempts),
                    "unresolved",
                    _summary_failure_reason(attempts),
                    tuple(attempts),
                )
            )
            continue

        if _conflicts_with_existing_identity(metadata, identity):
            warnings.append(
                ValidationIssue(
                    code="civitai_api_local_identity_conflict",
                    message="Civitai API identity conflicts with existing local identity and was ignored",
                    field=field,
                )
            )
            updated_resource = _with_lookup_metadata(
                resource,
                status="conflict",
                reason="local_identity_conflict",
                failure_class="identity_conflict",
                attempted_hash_types=_attempted_hash_types(attempts),
                status_code=_summary_status_code(attempts),
                retryable=False,
                lookup_client=_summary_lookup_client(attempts),
                ssl_context_source=_summary_ssl_context_source(attempts),
                api_endpoint_kind=_summary_endpoint_kind(attempts),
            )
            updated.append(updated_resource)
            lookup_debug.append(
                _lookup_debug_item(
                    updated_resource,
                    _attempted_hash_types(attempts),
                    "unresolved",
                    "local_identity_conflict",
                    tuple(attempts),
                )
            )
            continue

        warnings.extend(identity_warnings)
        updated_metadata = _apply_api_identity(metadata, identity)
        updated_resource = replace(
            resource,
            resource=replace(
                updated_metadata,
                metadata={
                    **dict(updated_metadata.metadata),
                    "lookupStatus": "resolved",
                    "lookupAttemptedHashTypes": list(_attempted_hash_types(attempts)),
                    "lookupStatusCode": _summary_status_code(attempts),
                    "lookupRetryable": False,
                    "lookupClient": _summary_lookup_client(attempts),
                    "sslContextSource": _summary_ssl_context_source(attempts),
                    "apiEndpointKind": _summary_endpoint_kind(attempts),
                },
            ),
            resolved=True,
            unresolved_reason=None,
        )
        updated.append(updated_resource)
        lookup_debug.append(
            _lookup_debug_item(updated_resource, _attempted_hash_types(attempts), "resolved", None, tuple(attempts))
        )
        record = identity.to_identity_record()
        if record is not None:
            cache_records.append(record)

    cache_warnings: tuple[ValidationIssue, ...] = ()
    if settings.cache_results and cache_records:
        cache_warnings = _write_generated_cache_records(
            tuple(cache_records),
            settings.generated_cache_path,
        )

    updated_tuple = tuple(updated)
    return CivitaiApiResolutionResult(
        resources=updated_tuple,
        unresolved_resources=_unresolved_resources(updated_tuple),
        warnings=(*warnings, *cache_warnings),
        cache_records=tuple(cache_records),
        lookup_debug_summary=tuple(lookup_debug),
    )


def _resolve_manual_pinned_with_optional_api(
    *,
    resource: ResolvedResource,
    index: int,
    lookup_client: CivitaiApiClient,
    settings: CivitaiLookupSettings,
) -> tuple[ResolvedResource, tuple[ValidationIssue, ...], dict[str, object]]:
    metadata = resource.resource
    field = f"resources[{index}]"
    if _should_complete_preferred_by_model_version(metadata):
        attempt = lookup_client.lookup_model_version_identity(
            model_version_id=int(metadata.civitai_model_version_id),
            resource=metadata,
            timeout_seconds=settings.timeout_seconds,
            field=field,
        )
        if attempt.identity is not None and not _api_identity_differs_from_manual(metadata, attempt.identity):
            updated_resource = _apply_model_version_identity_to_pinned_resource(
                resource,
                attempt.identity,
                attempt=attempt,
            )
            return (
                updated_resource,
                attempt.warnings,
                _lookup_debug_item(
                    updated_resource,
                    _attempted_hash_types((attempt,)),
                    MANUAL_PINNED_LOOKUP_STATUS,
                    None,
                    (attempt,),
                ),
            )
        completion_reason = (
            attempt.failure_reason or _failure_reason_from_warnings(attempt.warnings) or "no matching result"
        )
        updated_resource = _with_lookup_metadata(
            resource,
            status=MANUAL_PINNED_LOOKUP_STATUS,
            attempted_hash_types=_attempted_hash_types((attempt,)),
            status_code=attempt.http_status,
            retryable=False,
            lookup_client=attempt.lookup_client,
            ssl_context_source=attempt.ssl_context_source,
            api_endpoint_kind=attempt.api_endpoint_kind,
            extra_metadata={
                "lookupMethod": "model_version",
                "identityIncomplete": True,
                "identityStatus": "partial_pinned",
                "apiCompletionStatus": "failed",
                "apiCompletionFailureReason": completion_reason,
                **({"apiCompletionFailureClass": attempt.failure_class} if attempt.failure_class else {}),
                **(
                    {"apiCompletionFailureDetailSanitized": attempt.failure_detail_sanitized}
                    if attempt.failure_detail_sanitized
                    else {}
                ),
                "apiCompletionRetryable": attempt.retryable,
                **({"apiCompletionStatusCode": attempt.http_status} if attempt.http_status is not None else {}),
            },
        )
        return (
            updated_resource,
            attempt.warnings,
            _lookup_debug_item(
                updated_resource,
                _attempted_hash_types((attempt,)),
                MANUAL_PINNED_LOOKUP_STATUS,
                completion_reason,
                (attempt,),
            ),
        )

    if metadata.hashes.is_empty:
        updated_resource = _with_lookup_metadata(
            resource,
            status=MANUAL_PINNED_LOOKUP_STATUS,
            reason="missing_hash",
        )
        return (
            updated_resource,
            (),
            _lookup_debug_item(
                updated_resource,
                (),
                MANUAL_PINNED_LOOKUP_STATUS,
                "missing_hash",
                (),
            ),
        )

    identity = None
    attempts: list[CivitaiLookupAttempt] = []
    identity_warnings: tuple[ValidationIssue, ...] = ()
    for hash_algorithm, hash_value in _lookup_hash_order(metadata.hashes, settings.prefer_sha256):
        attempt = lookup_client.lookup_by_hash(
            hash_value=hash_value,
            hash_algorithm=hash_algorithm,
            resource=metadata,
            timeout_seconds=settings.timeout_seconds,
            field=field,
        )
        attempts.append(attempt)
        if attempt.identity is not None:
            identity = attempt.identity
            identity_warnings = attempt.warnings
            break

    extra: dict[str, object] = {}
    warnings: list[ValidationIssue] = []
    reason = _summary_failure_reason(attempts) if identity is None else None
    if identity is not None and _api_identity_differs_from_manual(metadata, identity):
        api_air = identity.air.canonical if identity.air is not None else None
        extra["apiAlternateMatch"] = True
        if api_air:
            extra["apiReturnedAir"] = api_air
        warnings.append(
            ValidationIssue(
                code="api_alternate_match",
                message="Civitai API returned a different identity for a user-pinned resource; the manual identity was kept",
                field=field,
            )
        )
    elif identity is not None:
        extra["apiAlternateMatch"] = False
        warnings.extend(identity_warnings)

    updated_resource = _with_lookup_metadata(
        resource,
        status=MANUAL_PINNED_LOOKUP_STATUS,
        reason=reason,
        failure_class=_summary_failure_class(attempts),
        failure_detail_sanitized=_summary_failure_detail(attempts),
        attempted_hash_types=_attempted_hash_types(attempts),
        status_code=_summary_status_code(attempts),
        retryable=_summary_retryable(attempts) if identity is None else False,
        lookup_client=_summary_lookup_client(attempts),
        ssl_context_source=_summary_ssl_context_source(attempts),
        api_endpoint_kind=_summary_endpoint_kind(attempts),
        extra_metadata={**extra, "lookupMethod": "hash"},
    )
    return (
        updated_resource,
        tuple(warnings),
        _lookup_debug_item(
            updated_resource,
            _attempted_hash_types(attempts),
            MANUAL_PINNED_LOOKUP_STATUS,
            reason,
            tuple(attempts),
        ),
    )


def _should_complete_preferred_by_model_version(metadata: ModelResourceMetadata) -> bool:
    return (
        metadata.metadata.get("identitySource") == PREFERRED_PRIMARY_MODEL_AIR_SOURCE
        and metadata.air is None
        and metadata.civitai_model_version_id is not None
    )


def _apply_model_version_identity_to_pinned_resource(
    resource: ResolvedResource,
    identity: CivitaiApiIdentity,
    *,
    attempt: CivitaiLookupAttempt,
) -> ResolvedResource:
    metadata = resource.resource
    updated_metadata = replace(
        metadata,
        air=identity.air,
        civitai_model_id=identity.civitai_model_id or metadata.civitai_model_id,
        civitai_model_version_id=identity.civitai_model_version_id,
        model_name=identity.model_name or metadata.model_name,
        model_version_name=identity.model_version_name or metadata.model_version_name,
        base_model=identity.base_model or metadata.base_model,
        source_url=identity.source_url or metadata.source_url,
        trigger_words=identity.trigger_words or metadata.trigger_words,
        metadata={
            **dict(metadata.metadata),
            "identityIncomplete": identity.air is None,
            "identityStatus": "partial_pinned" if identity.air is None else "resolved_pinned",
            "lookupStatus": MANUAL_PINNED_LOOKUP_STATUS,
            "lookupMethod": "model_version",
            "lookupAttemptedHashTypes": ["modelVersionId"],
            "lookupStatusCode": attempt.http_status,
            "lookupRetryable": False,
            "lookupClient": attempt.lookup_client,
            "sslContextSource": attempt.ssl_context_source,
            "apiEndpointKind": attempt.api_endpoint_kind,
            "apiCompletionStatus": "resolved",
            "apiCompletionStatusCode": attempt.http_status,
            "apiCompletionRetryable": False,
        },
    )
    return replace(resource, resource=updated_metadata, resolved=True, unresolved_reason=None)


def _identity_from_payload(
    payload: Any,
    *,
    queried_hash: str,
    hash_algorithm: str,
    resource: ModelResourceMetadata,
    field: str,
) -> tuple[CivitaiApiIdentity | None, tuple[ValidationIssue, ...]]:
    warnings: list[ValidationIssue] = []
    if not isinstance(payload, Mapping):
        return None, (
            ValidationIssue(
                code="civitai_api_response_schema_invalid",
                message="Civitai hash lookup response was not a JSON object",
                field=field,
            ),
        )

    matched_hashes = _matching_file_hashes(payload.get("files"), queried_hash)
    if matched_hashes is None:
        return None, (
            ValidationIssue(
                code="civitai_api_hash_mismatch",
                message="Civitai response did not contain the queried hash in returned file hashes",
                field=field,
            ),
        )

    model_version_id = _int_or_none(payload.get("modelVersionId") or payload.get("id"))

    model = payload.get("model") if isinstance(payload.get("model"), Mapping) else {}
    model_id = _int_or_none(payload.get("modelId") or model.get("id"))
    model_type = _string_or_none(payload.get("modelType") or payload.get("type") or model.get("type"))
    api_type = _api_type_to_air_type(model_type)
    local_value = resource.type or resource.role
    local_type = _local_type_to_air_type(local_value)

    official_air: AIRMetadata | None = None
    official_air_text = _string_or_none(payload.get("air"))
    if official_air_text:
        official_air, air_warnings = parse_air(official_air_text)
        warnings.extend(
            ValidationIssue(
                code="civitai_api_air_parse_warning",
                message=warning.message,
                field=field,
            )
            for warning in air_warnings
        )
        if official_air is None:
            return None, (
                ValidationIssue(
                    code="civitai_api_malformed_air",
                    message="Civitai response included malformed AIR",
                    field=field,
                ),
            )
        if official_air.source == "civitai":
            if model_id is not None and official_air.model_id is not None and model_id != official_air.model_id:
                return None, (
                    ValidationIssue(
                        code="civitai_api_air_identity_conflict",
                        message="Civitai response AIR modelId conflicts with response modelId",
                        field=field,
                    ),
                )
            if (
                model_version_id is not None
                and official_air.model_version_id is not None
                and model_version_id != official_air.model_version_id
            ):
                return None, (
                    ValidationIssue(
                        code="civitai_api_air_identity_conflict",
                        message="Civitai response AIR modelVersionId conflicts with response modelVersionId",
                        field=field,
                    ),
                )
            model_id = model_id if model_id is not None else official_air.model_id
            model_version_id = model_version_id if model_version_id is not None else official_air.model_version_id

    if model_version_id is None:
        return None, (
            ValidationIssue(
                code="civitai_api_missing_model_version_id",
                message="Civitai response did not include a modelVersionId",
                field=field,
            ),
        )

    if official_air is not None:
        if (
            local_type
            and official_air.type
            and local_type != official_air.type
            and not _local_type_allows_official_air_override(local_value)
        ):
            return None, (
                ValidationIssue(
                    code="civitai_api_type_mismatch",
                    message="Civitai response AIR type does not match the detected local resource type",
                    field=field,
                ),
            )
    elif api_type and local_type and api_type != local_type:
        return None, (
            ValidationIssue(
                code="civitai_api_type_mismatch",
                message="Civitai response model type does not match the detected local resource type",
                field=field,
            ),
        )

    local_type_is_uncertain = _local_type_is_uncertain_for_air(local_value)
    resource_type = (
        official_air.type
        if official_air is not None
        else (local_type or (api_type if not local_type_is_uncertain else None))
    )
    base_model = _string_or_none(payload.get("baseModel") or payload.get("base_model"))
    ecosystem = _base_model_to_air_ecosystem(base_model)
    if model_id is None:
        warnings.append(
            ValidationIssue(
                code="civitai_api_air_missing_model_id",
                message="Civitai response did not include modelId, so a full AIR URN was not built",
                field=field,
            )
        )
    if official_air is None and ecosystem is None and base_model:
        warnings.append(
            ValidationIssue(
                code="civitai_api_unknown_ecosystem",
                message="Civitai base model could not be mapped confidently to an AIR ecosystem",
                field=field,
            )
        )
    if resource_type is None:
        warnings.append(
            ValidationIssue(
                code="civitai_api_unknown_resource_type",
                message="Resource type could not be mapped confidently to an AIR type",
                field=field,
            )
        )
    if official_air is None and local_type_is_uncertain:
        warnings.append(
            ValidationIssue(
                code="civitai_api_local_type_not_air_mapped",
                message="Local resource type is not mapped to a Civitai AIR type; Civitai IDs may be preserved without inventing AIR",
                field=field,
            )
        )

    air = official_air
    if air is None and model_id is not None and ecosystem is not None and resource_type is not None:
        raw_air = f"urn:air:{ecosystem}:{resource_type}:civitai:{model_id}@{model_version_id}"
        air, air_warnings = parse_air(raw_air)
        warnings.extend(
            ValidationIssue(
                code="civitai_api_air_parse_warning",
                message=warning.message,
                field=field,
            )
            for warning in air_warnings
        )

    return (
        CivitaiApiIdentity(
            civitai_model_id=model_id,
            civitai_model_version_id=model_version_id,
            hashes=_merge_matched_hashes(matched_hashes, hash_algorithm, queried_hash),
            air=air,
            model_name=_string_or_none(payload.get("modelName") or model.get("name")),
            model_version_name=_string_or_none(payload.get("name") or payload.get("versionName")),
            resource_type=resource_type,
            base_model=base_model,
            trigger_words=_string_tuple(payload.get("trainedWords") or payload.get("triggerWords")),
            source_url=_string_or_none(payload.get("url") or model.get("url")),
            lookup_timestamp=_utc_timestamp(),
        ),
        tuple(warnings),
    )


def _identity_from_model_version_payload(
    payload: Any,
    *,
    requested_model_version_id: int,
    resource: ModelResourceMetadata,
    field: str,
) -> tuple[CivitaiApiIdentity | None, tuple[ValidationIssue, ...]]:
    warnings: list[ValidationIssue] = []
    if not isinstance(payload, Mapping):
        return None, (
            ValidationIssue(
                code="civitai_api_response_schema_invalid",
                message="Civitai model-version lookup response was not a JSON object",
                field=field,
            ),
        )

    model_version_id = _int_or_none(payload.get("modelVersionId") or payload.get("id"))
    if model_version_id != requested_model_version_id:
        return None, (
            ValidationIssue(
                code="civitai_api_model_version_mismatch",
                message="Civitai model-version lookup returned a different modelVersionId",
                field=field,
            ),
        )

    model = payload.get("model") if isinstance(payload.get("model"), Mapping) else {}
    model_id = _int_or_none(payload.get("modelId") or model.get("id"))
    model_type = _string_or_none(payload.get("modelType") or payload.get("type") or model.get("type"))
    api_type = _api_type_to_air_type(model_type)
    local_value = resource.type or resource.role
    local_type = _local_type_to_air_type(local_value)

    official_air = None
    official_air_text = _string_or_none(payload.get("air"))
    if official_air_text:
        official_air, air_warnings = parse_air(official_air_text)
        warnings.extend(
            ValidationIssue(
                code="civitai_api_air_parse_warning",
                message=warning.message,
                field=field,
            )
            for warning in air_warnings
        )
        if official_air is None:
            return None, (
                ValidationIssue(
                    code="civitai_api_malformed_air",
                    message="Civitai model-version response included malformed AIR",
                    field=field,
                ),
            )
        if official_air.source == "civitai":
            if model_id is not None and official_air.model_id is not None and model_id != official_air.model_id:
                return None, (
                    ValidationIssue(
                        code="civitai_api_air_identity_conflict",
                        message="Civitai model-version AIR modelId conflicts with response modelId",
                        field=field,
                    ),
                )
            if official_air.model_version_id is not None and official_air.model_version_id != model_version_id:
                return None, (
                    ValidationIssue(
                        code="civitai_api_air_identity_conflict",
                        message="Civitai model-version AIR version conflicts with response modelVersionId",
                        field=field,
                    ),
                )
            model_id = model_id if model_id is not None else official_air.model_id
    else:
        warnings.append(
            ValidationIssue(
                code="civitai_api_model_version_air_missing",
                message="Civitai model-version details did not include official AIR",
                field=field,
            )
        )

    if (
        official_air is not None
        and local_type
        and official_air.type
        and local_type != official_air.type
        and not _local_type_allows_official_air_override(local_value)
    ):
        return None, (
            ValidationIssue(
                code="civitai_api_type_mismatch",
                message="Civitai response AIR type does not match the detected local resource type",
                field=field,
            ),
        )
    if official_air is None and api_type and local_type and api_type != local_type:
        return None, (
            ValidationIssue(
                code="civitai_api_type_mismatch",
                message="Civitai response model type does not match the detected local resource type",
                field=field,
            ),
        )

    return (
        CivitaiApiIdentity(
            civitai_model_id=model_id,
            civitai_model_version_id=model_version_id,
            hashes=_first_file_hashes(payload.get("files")),
            air=official_air,
            model_name=_string_or_none(payload.get("modelName") or model.get("name")),
            model_version_name=_string_or_none(payload.get("name") or payload.get("versionName")),
            resource_type=official_air.type if official_air is not None else (local_type or api_type),
            base_model=_string_or_none(payload.get("baseModel") or payload.get("base_model")),
            trigger_words=_string_tuple(payload.get("trainedWords") or payload.get("triggerWords")),
            source_url=_string_or_none(payload.get("url") or model.get("url")),
            lookup_timestamp=_utc_timestamp(),
        ),
        tuple(warnings),
    )


def _write_generated_cache_records(
    new_records: tuple[IdentityMappingRecord, ...],
    cache_path: Path,
) -> tuple[ValidationIssue, ...]:
    allowed_roots = (cache_path.parent,)
    loaded = load_identity_cache(cache_path, allowed_roots=allowed_roots)
    records_by_hash: dict[str, IdentityMappingRecord] = {}
    for record in loaded.cache.records:
        for key in _record_hash_keys(record):
            records_by_hash.setdefault(key, record)
    for record in new_records:
        for key in _record_hash_keys(record):
            records_by_hash[key] = record

    merged: list[IdentityMappingRecord] = []
    seen: set[tuple[int, int, str]] = set()
    for key in sorted(records_by_hash):
        record = records_by_hash[key]
        record_key = (
            record.civitai_model_id,
            record.civitai_model_version_id,
            record.air.raw,
        )
        if record_key in seen:
            continue
        seen.add(record_key)
        merged.append(record)

    merged_records = tuple(merged)
    cache = IdentityCache(records=merged_records)
    return (
        *loaded.warnings,
        *loaded.errors,
        *write_identity_cache(cache, cache_path, allowed_roots=allowed_roots),
    )


def _lookup_summary_warning(
    resource: ResolvedResource,
    attempts: list[CivitaiLookupAttempt],
    field: str,
) -> ValidationIssue | None:
    if not attempts:
        return None
    hash_types = ", ".join(_attempted_hash_types(attempts)) or "none"
    reason = _summary_failure_reason(attempts)
    if len(attempts) == 1 and attempts[0].warnings:
        warning = attempts[0].warnings[0]
        return ValidationIssue(
            code=warning.code,
            message=f"{warning.message}; attempted {hash_types}",
            field=field,
        )
    return ValidationIssue(
        code="civitai_api_lookup_failed",
        message=f"Civitai API lookup failed for {_safe_resource_name(resource)}: attempted {hash_types}; {reason}",
        field=field,
    )


def _attempted_hash_types(attempts: list[CivitaiLookupAttempt] | tuple[CivitaiLookupAttempt, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for attempt in attempts:
        if attempt.hash_algorithm and attempt.hash_algorithm not in values:
            values.append(attempt.hash_algorithm)
    return tuple(values)


def _summary_failure_reason(attempts: list[CivitaiLookupAttempt] | tuple[CivitaiLookupAttempt, ...]) -> str:
    reasons = [attempt.failure_reason for attempt in attempts if attempt.failure_reason]
    statuses = [attempt.http_status for attempt in attempts if attempt.http_status is not None]
    if not reasons:
        return "no matching result"
    unique = tuple(dict.fromkeys(reasons))
    if len(unique) == 1:
        reason = unique[0]
    elif set(unique).issubset({"not_found", "hash_mismatch"}):
        reason = "no matching result"
    else:
        reason = ", ".join(unique)
    if statuses:
        status_text = ", ".join(str(status) for status in dict.fromkeys(statuses))
        return f"{reason}; HTTP status {status_text}"
    return reason


def _summary_status_code(attempts: list[CivitaiLookupAttempt] | tuple[CivitaiLookupAttempt, ...]) -> int | None:
    for attempt in attempts:
        if attempt.http_status is not None:
            return attempt.http_status
    return None


def _summary_retryable(attempts: list[CivitaiLookupAttempt] | tuple[CivitaiLookupAttempt, ...]) -> bool:
    return any(attempt.retryable for attempt in attempts)


def _summary_failure_class(attempts: list[CivitaiLookupAttempt] | tuple[CivitaiLookupAttempt, ...]) -> str | None:
    for attempt in attempts:
        if attempt.failure_class:
            return attempt.failure_class
    return None


def _summary_failure_detail(attempts: list[CivitaiLookupAttempt] | tuple[CivitaiLookupAttempt, ...]) -> str | None:
    for attempt in attempts:
        if attempt.failure_detail_sanitized:
            return attempt.failure_detail_sanitized
    return None


def _summary_lookup_client(attempts: list[CivitaiLookupAttempt] | tuple[CivitaiLookupAttempt, ...]) -> str | None:
    for attempt in attempts:
        if attempt.lookup_client:
            return attempt.lookup_client
    return None


def _summary_ssl_context_source(attempts: list[CivitaiLookupAttempt] | tuple[CivitaiLookupAttempt, ...]) -> str | None:
    for attempt in attempts:
        if attempt.ssl_context_source:
            return attempt.ssl_context_source
    return None


def _summary_endpoint_kind(attempts: list[CivitaiLookupAttempt] | tuple[CivitaiLookupAttempt, ...]) -> str | None:
    for attempt in attempts:
        if attempt.api_endpoint_kind:
            return attempt.api_endpoint_kind
    return None


def _failure_reason_from_warnings(warnings: tuple[ValidationIssue, ...]) -> str | None:
    if not warnings:
        return None
    mapping = {
        "civitai_api_hash_mismatch": "hash_mismatch",
        "civitai_api_missing_model_version_id": "missing_model_version_id",
        "civitai_api_type_mismatch": "type_mismatch",
        "civitai_api_response_schema_invalid": "invalid_response_schema",
        "civitai_api_air_missing_model_id": "missing_model_id",
        "civitai_api_unknown_ecosystem": "unknown_ecosystem",
        "civitai_api_unknown_resource_type": "unknown_resource_type",
        "civitai_api_air_identity_conflict": "identity_conflict",
        "civitai_api_malformed_air": "malformed_air",
    }
    return mapping.get(warnings[0].code, warnings[0].code)


def _with_lookup_metadata(
    resource: ResolvedResource,
    *,
    status: str,
    reason: str | None = None,
    failure_class: str | None = None,
    failure_detail_sanitized: str | None = None,
    attempted_hash_types: tuple[str, ...] = (),
    status_code: int | None = None,
    retryable: bool | None = None,
    lookup_client: str | None = None,
    ssl_context_source: str | None = None,
    api_endpoint_kind: str | None = None,
    extra_metadata: Mapping[str, object] | None = None,
) -> ResolvedResource:
    metadata = resource.resource
    extra = dict(metadata.metadata)
    extra["lookupStatus"] = status
    if reason:
        extra["lookupFailureReason"] = reason
    if failure_class:
        extra["lookupFailureClass"] = failure_class
    if failure_detail_sanitized:
        extra["lookupFailureDetailSanitized"] = failure_detail_sanitized
    if attempted_hash_types:
        extra["lookupAttemptedHashTypes"] = list(attempted_hash_types)
    if status_code is not None:
        extra["lookupStatusCode"] = status_code
    if retryable is not None:
        extra["lookupRetryable"] = bool(retryable)
    if lookup_client:
        extra["lookupClient"] = lookup_client
    if ssl_context_source:
        extra["sslContextSource"] = ssl_context_source
    if api_endpoint_kind:
        extra["apiEndpointKind"] = api_endpoint_kind
    if extra_metadata:
        extra.update(extra_metadata)
    return replace(resource, resource=replace(metadata, metadata=extra))


def _with_lookup_disabled_metadata(resource: ResolvedResource) -> ResolvedResource:
    metadata = resource.resource
    if _is_manual_pinned_resource(metadata):
        return _with_lookup_metadata(resource, status=MANUAL_PINNED_LOOKUP_STATUS)
    if metadata.resolution_source in {"local_identity_cache", "user_pinned_cache"}:
        return _with_lookup_metadata(resource, status="resolved_by_cache")
    if resource.resolved or _has_civitai_identity(metadata):
        return _with_lookup_metadata(resource, status="resolved")
    return _with_lookup_metadata(resource, status="skipped_lookup_disabled")


def _debug_result_for_resource(resource: ResolvedResource) -> str:
    status = str(resource.resource.metadata.get("lookupStatus") or "")
    if status in {MANUAL_PINNED_LOOKUP_STATUS, "resolved_by_cache", "resolved"}:
        return status
    return "unresolved"


def _lookup_debug_item(
    resource: ResolvedResource,
    attempted_hash_types: tuple[str, ...],
    result: str,
    reason: str | None,
    attempts: tuple[CivitaiLookupAttempt, ...] = (),
) -> dict[str, object]:
    metadata = resource.resource
    item: dict[str, object] = {
        "filename": _safe_resource_name(resource),
        "role": metadata.role,
        "type": metadata.type or "",
        "hashTypesAttempted": list(attempted_hash_types),
        "lookupStatus": str(metadata.metadata.get("lookupStatus") or ""),
        "result": result,
    }
    identity_source = metadata.metadata.get("identitySource")
    if identity_source:
        item["identitySource"] = str(identity_source)
    confidence = metadata.metadata.get("confidence")
    if confidence:
        item["confidence"] = str(confidence)
    if metadata.metadata.get("apiAlternateMatch") is not None:
        item["apiAlternateMatch"] = bool(metadata.metadata.get("apiAlternateMatch"))
    api_air = metadata.metadata.get("apiReturnedAir")
    if api_air:
        item["apiReturnedAir"] = str(api_air)
    api_completion_status = metadata.metadata.get("apiCompletionStatus")
    if api_completion_status:
        item["apiCompletionStatus"] = str(api_completion_status)
    api_completion_reason = metadata.metadata.get("apiCompletionFailureReason")
    if api_completion_reason:
        item["apiCompletionFailureReason"] = str(api_completion_reason)
    api_completion_status_code = metadata.metadata.get("apiCompletionStatusCode")
    if api_completion_status_code is not None:
        item["apiCompletionStatusCode"] = api_completion_status_code
    api_completion_retryable = metadata.metadata.get("apiCompletionRetryable")
    if api_completion_retryable is not None:
        item["apiCompletionRetryable"] = bool(api_completion_retryable)
    failure_class = metadata.metadata.get("lookupFailureClass")
    if failure_class:
        item["lookupFailureClass"] = str(failure_class)
    failure_detail = metadata.metadata.get("lookupFailureDetailSanitized")
    if failure_detail:
        item["lookupFailureDetailSanitized"] = str(failure_detail)
    lookup_client = metadata.metadata.get("lookupClient")
    if lookup_client:
        item["lookupClient"] = str(lookup_client)
    ssl_context_source = metadata.metadata.get("sslContextSource")
    if ssl_context_source:
        item["sslContextSource"] = str(ssl_context_source)
    endpoint_kind = metadata.metadata.get("apiEndpointKind")
    if endpoint_kind:
        item["apiEndpointKind"] = str(endpoint_kind)
    status_code = _summary_status_code(attempts)
    if status_code is not None:
        item["statusCode"] = status_code
    if reason:
        item["reason"] = reason
    item["retryable"] = _summary_retryable(attempts)
    return item


def _safe_resource_name(resource: ResolvedResource) -> str:
    metadata = resource.resource
    name = metadata.filename or metadata.name or metadata.local_path_basename or "resource"
    return str(name).replace("\\", "/").rsplit("/", 1)[-1]


def _lookup_hash_order(hashes: HashMetadata, prefer_sha256: bool) -> tuple[tuple[str, str], ...]:
    ordered = (
        ("SHA256", hashes.sha256),
        ("BLAKE3", hashes.blake3),
        ("AutoV2", hashes.auto_v2),
        ("AutoV3", hashes.auto_v3),
        ("CRC32", hashes.crc32),
        ("AutoV1", hashes.auto_v1),
    )
    if not prefer_sha256 and hashes.auto_v2:
        ordered = (
            ("AutoV2", hashes.auto_v2),
            ("SHA256", hashes.sha256),
            ("BLAKE3", hashes.blake3),
            ("AutoV3", hashes.auto_v3),
            ("CRC32", hashes.crc32),
            ("AutoV1", hashes.auto_v1),
        )
    return tuple((algorithm, value) for algorithm, value in ordered if value)


def _matching_file_hashes(raw_files: Any, queried_hash: str) -> HashMetadata | None:
    if not isinstance(raw_files, list):
        return None
    normalized_query = _normalize_hash(queried_hash)
    for raw_file in raw_files:
        if not isinstance(raw_file, Mapping):
            continue
        hashes = _parse_hashes(raw_file.get("hashes"))
        values = [
            hashes.sha256,
            hashes.blake3,
            hashes.auto_v2,
            hashes.auto_v3,
            hashes.crc32,
            hashes.auto_v1,
            *hashes.additional.values(),
        ]
        if any(_normalize_hash(value) == normalized_query for value in values if value):
            return hashes
    return None


def _first_file_hashes(raw_files: Any) -> HashMetadata:
    if not isinstance(raw_files, list):
        return HashMetadata()
    for raw_file in raw_files:
        if not isinstance(raw_file, Mapping):
            continue
        hashes = _parse_hashes(raw_file.get("hashes"))
        if not hashes.is_empty:
            return hashes
    return HashMetadata()


def _parse_hashes(raw_hashes: Any) -> HashMetadata:
    if not isinstance(raw_hashes, Mapping):
        return HashMetadata()
    sha256 = _string_or_none(_hash_value(raw_hashes, "SHA256", "sha256"))
    auto_v1 = _string_or_none(_hash_value(raw_hashes, "AutoV1", "autoV1", "auto_v1"))
    auto_v2 = _string_or_none(_hash_value(raw_hashes, "AutoV2", "autoV2", "auto_v2"))
    auto_v3 = _string_or_none(_hash_value(raw_hashes, "AutoV3", "autoV3", "auto_v3"))
    crc32 = _string_or_none(_hash_value(raw_hashes, "CRC32", "crc32"))
    blake3 = _string_or_none(_hash_value(raw_hashes, "BLAKE3", "blake3"))
    known_keys = {
        "SHA256",
        "sha256",
        "AutoV1",
        "autoV1",
        "auto_v1",
        "AutoV2",
        "autoV2",
        "auto_v2",
        "AutoV3",
        "autoV3",
        "auto_v3",
        "CRC32",
        "crc32",
        "BLAKE3",
        "blake3",
    }
    additional = {
        str(key): str(value) for key, value in raw_hashes.items() if value is not None and str(key) not in known_keys
    }
    return HashMetadata(
        sha256=sha256,
        auto_v1=auto_v1,
        auto_v2=auto_v2,
        auto_v3=auto_v3,
        crc32=crc32,
        blake3=blake3,
        additional=additional,
    )


def _merge_matched_hashes(
    hashes: HashMetadata,
    hash_algorithm: str,
    queried_hash: str,
) -> HashMetadata:
    if hash_algorithm == "SHA256" and hashes.sha256 is None:
        return replace(hashes, sha256=queried_hash)
    if hash_algorithm == "AutoV2" and hashes.auto_v2 is None:
        return replace(hashes, auto_v2=queried_hash)
    if hash_algorithm == "BLAKE3" and hashes.blake3 is None:
        return replace(hashes, blake3=queried_hash)
    if hash_algorithm == "AutoV3" and hashes.auto_v3 is None:
        return replace(hashes, auto_v3=queried_hash)
    if hash_algorithm == "CRC32" and hashes.crc32 is None:
        return replace(hashes, crc32=queried_hash)
    if hash_algorithm == "AutoV1" and hashes.auto_v1 is None:
        return replace(hashes, auto_v1=queried_hash)
    return hashes


def _apply_api_identity(
    metadata: ModelResourceMetadata,
    identity: CivitaiApiIdentity,
) -> ModelResourceMetadata:
    return replace(
        metadata,
        air=identity.air,
        civitai_model_id=identity.civitai_model_id,
        civitai_model_version_id=identity.civitai_model_version_id,
        resolution_source=LOOKUP_RESOLUTION_SOURCE,
        model_name=identity.model_name,
        model_version_name=identity.model_version_name,
        base_model=identity.base_model,
        source_url=identity.source_url,
        trigger_words=identity.trigger_words,
        metadata={
            **dict(metadata.metadata),
            "identitySource": "civitai_api",
            "confidence": "high" if identity.air is not None else "medium",
            "lookupMatchedHash": _hash_summary(identity.hashes),
            "lookupTimestamp": identity.lookup_timestamp,
        },
    )


def _conflicts_with_existing_identity(
    metadata: ModelResourceMetadata,
    identity: CivitaiApiIdentity,
) -> bool:
    if metadata.air is not None and metadata.air.model_version_id is not None:
        return metadata.air.model_version_id != identity.civitai_model_version_id
    if metadata.civitai_model_version_id is not None:
        return metadata.civitai_model_version_id != identity.civitai_model_version_id
    return False


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


def _has_civitai_identity(metadata: ModelResourceMetadata) -> bool:
    return bool(
        metadata.civitai_model_version_id is not None
        or (metadata.air is not None and metadata.air.model_version_id is not None)
    )


def _is_manual_pinned_resource(metadata: ModelResourceMetadata) -> bool:
    source = metadata.metadata.get("identitySource")
    return metadata.resolution_source in {
        MANUAL_PINNED_IDENTITY_SOURCE,
        PREFERRED_PRIMARY_MODEL_AIR_SOURCE,
    } or source in {MANUAL_PINNED_IDENTITY_SOURCE, PREFERRED_PRIMARY_MODEL_AIR_SOURCE}


def _api_identity_differs_from_manual(
    metadata: ModelResourceMetadata,
    identity: CivitaiApiIdentity,
) -> bool:
    if metadata.air is not None and identity.air is not None and metadata.air.canonical != identity.air.canonical:
        return True
    if (
        metadata.civitai_model_version_id is not None
        and identity.civitai_model_version_id != metadata.civitai_model_version_id
    ):
        return True
    if (
        metadata.civitai_model_id is not None
        and identity.civitai_model_id is not None
        and identity.civitai_model_id != metadata.civitai_model_id
    ):
        return True
    return False


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


def _record_hash_keys(record: IdentityMappingRecord) -> tuple[str, ...]:
    return tuple(
        f"{algorithm.lower()}:{_normalize_hash(value)}" for algorithm, value in _lookup_hash_order(record.hashes, True)
    )


def _hash_summary(hashes: HashMetadata) -> dict[str, str]:
    data = hashes.to_json()
    return {key: data[key] for key in sorted(data)}


def _http_failure_attempt(
    *,
    hash_algorithm: str,
    status: int,
    reason: str,
    retryable: bool,
    body: bytes,
    field: str,
    lookup_client: str | None = None,
    ssl_context_source: str | None = None,
    api_endpoint_kind: str | None = None,
) -> CivitaiLookupAttempt:
    detail = _api_error_detail(body)
    message = f"Civitai hash lookup returned HTTP status {status} ({reason})"
    if detail:
        message = f"{message}: {detail}"
    return CivitaiLookupAttempt(
        hash_algorithm=hash_algorithm,
        result="unresolved",
        failure_reason=reason,
        failure_class=reason,
        failure_detail_sanitized=detail,
        http_status=status,
        retryable=retryable,
        lookup_client=lookup_client,
        ssl_context_source=ssl_context_source,
        api_endpoint_kind=api_endpoint_kind,
        warnings=(
            ValidationIssue(
                code=_http_warning_code(reason),
                message=message,
                field=field,
            ),
        ),
    )


def _transport_failure_attempt(
    *,
    hash_algorithm: str,
    classification: tuple[str, bool, str, str | None],
    field: str,
    lookup_client: str | None = None,
    ssl_context_source: str | None = None,
    api_endpoint_kind: str | None = None,
) -> CivitaiLookupAttempt:
    reason, retryable, failure_class, detail = classification
    return CivitaiLookupAttempt(
        hash_algorithm=hash_algorithm,
        result="unresolved",
        failure_reason=reason,
        failure_class=failure_class,
        failure_detail_sanitized=detail,
        retryable=retryable,
        lookup_client=lookup_client,
        ssl_context_source=ssl_context_source,
        api_endpoint_kind=api_endpoint_kind,
        warnings=(
            ValidationIssue(
                code=_transport_warning_code(reason),
                message=f"Civitai lookup failed: {failure_class}",
                field=field,
            ),
        ),
    )


def _classify_http_status(status: int) -> tuple[str, bool]:
    if status == 400:
        return "bad_request", False
    if status == 401:
        return "unauthorized", False
    if status == 403:
        return "forbidden", False
    if status == 404:
        return "not_found", False
    if status == 405:
        return "method_not_allowed", False
    if status == 429:
        return "rate_limited", True
    if status >= 500:
        return "server_error", True
    return "http_error", False


def _classify_transport_error(exc: object) -> tuple[str, bool, str, str | None]:
    detail = _safe_exception_detail(exc)
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", True, "timeout", detail
    if isinstance(exc, socket.gaierror):
        return "dns_error", True, "dns_error", detail
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "ssl_error", True, "ssl_certificate_verify_failed", detail
    if isinstance(exc, ssl.SSLEOFError):
        return "ssl_error", True, "ssl_eof", detail
    if isinstance(exc, ssl.SSLError):
        text = str(exc).lower()
        if "certificate" in text or "verify" in text:
            return "ssl_error", True, "ssl_certificate_verify_failed", detail
        if "eof" in text or "unexpected eof" in text:
            return "ssl_error", True, "ssl_eof", detail
        return "ssl_error", True, "ssl_tls_handshake_failed", detail
    if isinstance(exc, ConnectionError):
        return "connection_error", True, "connection_error", detail
    if isinstance(exc, OSError):
        text = str(exc).lower()
        if "name or service not known" in text or "getaddrinfo" in text:
            return "dns_error", True, "dns_error", detail
        if "certificate" in text or "cert verify" in text or "verify failed" in text:
            return "ssl_error", True, "ssl_certificate_verify_failed", detail
        if "eof" in text or "unexpected eof" in text:
            return "ssl_error", True, "ssl_eof", detail
        if "ssl" in text or "certificate" in text:
            return "ssl_error", True, "ssl_tls_handshake_failed", detail
        if "connection" in text or "timed out" in text:
            return "connection_error", True, "connection_error", detail
    return "network_error", True, "unknown_network_error", detail


def _api_error_detail(body: bytes) -> str | None:
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    error_text = _string_or_none(payload.get("error"))
    if error_text:
        return _safe_diagnostic_detail(error_text)
    message = _string_or_none(payload.get("message"))
    code = _string_or_none(payload.get("code"))
    if message and code:
        return _safe_diagnostic_detail(f"{code}: {message}")
    if message:
        return _safe_diagnostic_detail(message)
    if code:
        return _safe_diagnostic_detail(code)
    return None


def _safe_diagnostic_detail(value: str) -> str:
    return sanitize_metadata_text(value)[:160]


def _safe_exception_detail(exc: object) -> str | None:
    text = sanitize_metadata_text(str(exc or "")).strip()
    if not text:
        return None
    return text[:160]


def _is_ssl_certificate_failure(exc: object) -> bool:
    reason = exc.reason if isinstance(exc, error.URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    text = str(reason).lower()
    return "certificate" in text or "cert verify" in text or "verify failed" in text or "local issuer" in text


def _http_warning_code(reason: str) -> str:
    mapping = {
        "not_found": "civitai_api_lookup_not_found",
        "rate_limited": "civitai_api_rate_limited",
        "server_error": "civitai_api_server_error",
        "bad_request": "civitai_api_bad_request",
        "unauthorized": "civitai_api_unauthorized",
        "forbidden": "civitai_api_forbidden",
        "method_not_allowed": "civitai_api_method_not_allowed",
    }
    return mapping.get(reason, "civitai_api_http_error")


def _transport_warning_code(reason: str) -> str:
    mapping = {
        "timeout": "civitai_api_lookup_timeout",
        "dns_error": "civitai_api_dns_error",
        "ssl_error": "civitai_api_ssl_error",
        "connection_error": "civitai_api_connection_error",
    }
    return mapping.get(reason, "civitai_api_lookup_failed")


def _lookup_url(base_url: str, hash_value: str) -> str:
    return f"{base_url.rstrip('/')}/model-versions/by-hash/{parse.quote(hash_value, safe='')}"


def _model_version_url(base_url: str, model_version_id: int) -> str:
    return f"{base_url.rstrip('/')}/model-versions/{parse.quote(str(model_version_id), safe='')}"


def _validated_https_base_url(base_url: str) -> str:
    parsed = parse.urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Civitai API base URL must be HTTPS")
    return base_url.rstrip("/")


def _should_fetch_model_version_air(payload: Mapping[str, Any], resource: ModelResourceMetadata) -> bool:
    model = payload.get("model") if isinstance(payload.get("model"), Mapping) else {}
    model_id = _int_or_none(payload.get("modelId") or model.get("id"))
    if model_id is None:
        return False
    local_value = resource.type or resource.role
    local_type = _local_type_to_air_type(local_value)
    model_type = _string_or_none(payload.get("modelType") or payload.get("type") or model.get("type"))
    api_type = _api_type_to_air_type(model_type)
    base_model = _string_or_none(payload.get("baseModel") or payload.get("base_model"))
    ecosystem = _base_model_to_air_ecosystem(base_model)
    if local_type and api_type and local_type != api_type and _local_type_is_uncertain_for_air(local_value):
        return True
    return ecosystem is None or api_type is None or local_type is None


def _api_type_to_air_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_label(value)
    mapping = {
        "checkpoint": "checkpoint",
        "lora": "lora",
        "locon": "lora",
        "textualinversion": "embedding",
        "textual inversion": "embedding",
        "embedding": "embedding",
        "vae": "vae",
        "controlnet": "controlnet",
        "control net": "controlnet",
        "upscaler": "upscaler",
        "diffusionmodel": "diffusionmodel",
        "diffusion model": "diffusionmodel",
        "unet": "unet",
        "other": "other",
        "image": "image",
    }
    return mapping.get(normalized)


def _local_type_to_air_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_label(value)
    mapping = {
        "base model": "checkpoint",
        "base_model": "checkpoint",
        "checkpoint": "checkpoint",
        "lora": "lora",
        "embedding": "embedding",
        "textual inversion": "embedding",
        "textualinversion": "embedding",
        "vae": "vae",
        "controlnet": "controlnet",
        "control net": "controlnet",
        "upscaler": "upscaler",
        "diffusion model": "diffusionmodel",
        "diffusionmodel": "diffusionmodel",
        "diffusion_model": "diffusionmodel",
        "unet": "unet",
        "other": "other",
        "image": "image",
    }
    return mapping.get(normalized)


def _local_type_is_uncertain_for_air(value: str | None) -> bool:
    if value is None:
        return False
    normalized = _normalize_label(value)
    return normalized in {"video model", "video_model", "unknown model", "unknown_model"}


def _local_type_allows_official_air_override(value: str | None) -> bool:
    if value is None:
        return False
    normalized = _normalize_label(value)
    return normalized in {
        "unet",
        "diffusion model",
        "diffusionmodel",
        "diffusion_model",
        "video model",
        "video_model",
        "unknown model",
        "unknown_model",
    }


def _base_model_to_air_ecosystem(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_label(value)
    compact = normalized.replace(" ", "").replace(".", "")
    if compact in {"sdxl", "sdxl10", "stablediffusionxl", "stablediffusionxl10"}:
        return "sdxl"
    if compact in {"sd15", "sd1", "stablediffusion15", "stablediffusion1"}:
        return "sd1"
    if compact.startswith("flux1") or compact in {"flux", "fluxdev"}:
        return "flux1"
    if compact.startswith("flux2"):
        return "flux2"
    if compact.startswith("sd3") or compact.startswith("stablediffusion3"):
        return "sd3"
    return None


def _normalize_label(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("_", " ").replace("-", " ").split())


def _normalize_hash(value: str) -> str:
    return str(value).strip().lower()


def _hash_value(raw_hashes: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw_hashes.get(key)
        if value is not None:
            return value
    return None


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


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if item is not None)
    return ()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "CivitaiApiClient",
    "CivitaiApiIdentity",
    "CivitaiApiResolutionResult",
    "CivitaiHttpResponse",
    "CivitaiLookupSettings",
    "DEFAULT_API_BASE_URL",
    "DEFAULT_LOOKUP_TIMEOUT_SECONDS",
    "GENERATED_CACHE_MAPPING_SOURCE",
    "LOOKUP_RESOLUTION_SOURCE",
    "StandardLibraryCivitaiTransport",
    "resolve_resources_with_civitai_api",
]
