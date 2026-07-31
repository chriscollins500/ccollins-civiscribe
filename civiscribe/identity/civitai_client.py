"""Bounded, privacy-safe Civitai identity lookup through HTTPX only."""

from __future__ import annotations

import importlib
import json
import math
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from urllib.parse import urlparse

import httpx

from ..domain import (
    HashRecord,
    IdentitySource,
    ResourceIdentity,
    ResourceRecord,
    ScanIssue,
)
from ..version import __version__
from .air import attach_file_to_air_identity, parse_air
from .civitai_contract import (
    BULK_HASH_ALGORITHMS,
    model_file_type_matches_role,
    model_type_to_resource_type,
    normalize_model_file_format,
)
from .hash_values import (
    hash_record_from_mapping,
    iter_hashes,
    merge_hashes,
)
from .resource_types import resource_type_is_ambiguous, resource_type_matches_role
from .types import LookupStatus

CIVITAI_API_BASE = "https://civitai.com/api/v1"
DEFAULT_LOOKUP_TIMEOUT_SECONDS = 4.0
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_ROLE_RESPONSE_BYTES = 16 * 1024 * 1024
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60
MAX_RATE_LIMIT_COOLDOWN_SECONDS = 3_600
MAX_ROLE_MATCH_CANDIDATES = 1_000
USER_AGENT = f"CCollins-CiviScribe/{__version__}"
MIN_PRINTABLE_CODEPOINT = 32
MAX_RETRY_AFTER_HEADER_CHARS = 128
_SAFE_API_HOST = "civitai.com"
_SAFE_API_PORT = 443


@dataclass(frozen=True, slots=True)
class CivitaiLookupConfig:
    """Network policy for explicitly enabled Civitai identity lookup."""

    enabled: bool = False
    timeout_seconds: float = DEFAULT_LOOKUP_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_role_response_bytes: int = DEFAULT_MAX_ROLE_RESPONSE_BYTES
    default_rate_limit_cooldown_seconds: int = DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
    max_rate_limit_cooldown_seconds: int = MAX_RATE_LIMIT_COOLDOWN_SECONDS
    api_base_url: str = CIVITAI_API_BASE

    def __post_init__(self) -> None:
        if (
            self.timeout_seconds <= 0
            or self.max_response_bytes < 1
            or self.max_role_response_bytes < 1
            or self.default_rate_limit_cooldown_seconds < 1
            or self.max_rate_limit_cooldown_seconds < 1
            or (self.default_rate_limit_cooldown_seconds > self.max_rate_limit_cooldown_seconds)
        ):
            raise ValueError("civitai_lookup_limits_invalid")
        _validate_api_base(self.api_base_url)


@dataclass(frozen=True, slots=True)
class CivitaiLookupResult:
    """One deduplicated resource lookup result."""

    identity: ResourceIdentity | None = None
    hashes: HashRecord = field(default_factory=HashRecord)
    status: LookupStatus = LookupStatus.NOT_ATTEMPTED
    issues: tuple[ScanIssue, ...] = ()
    attempted_hashes: tuple[str, ...] = ()
    failure_reason: str | None = None
    http_status: int | None = None
    retryable: bool = False
    retry_after_seconds: int | None = None
    tls_source: str | None = None
    diagnostic_reason: str | None = None
    candidate_count: int | None = None
    compatible_candidate_count: int | None = None


@dataclass(frozen=True, slots=True)
class _RequestResult:
    payload: object | None = None
    failure_reason: str | None = None
    http_status: int | None = None
    retryable: bool = False
    retry_after_seconds: int | None = None
    tls_source: str | None = None


@dataclass(frozen=True, slots=True)
class _PayloadIdentity:
    identity: ResourceIdentity
    hashes: HashRecord


@dataclass(frozen=True, slots=True)
class _AttemptDiagnostics:
    reason: str | None = None
    candidate_count: int | None = None
    compatible_candidate_count: int | None = None


def _validate_api_base(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _SAFE_API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, _SAFE_API_PORT}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("civitai_api_base_invalid")


DEFAULT_LOOKUP_CONFIG = CivitaiLookupConfig()


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CivitaiRateLimitGate:
    """Thread-safe process-local cooldown without sleeping or retrying."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def defer(self, seconds: int) -> None:
        """Extend the cooldown by a positive caller-supplied delay."""

        if seconds < 1:
            return
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._clock() + seconds)

    def remaining_seconds(self) -> int:
        """Return whole seconds remaining without exposing clock values."""

        with self._lock:
            return max(0, math.ceil(self._blocked_until - self._clock()))


PROCESS_RATE_LIMIT_GATE = CivitaiRateLimitGate()


def parse_retry_after(
    value: str | None,
    *,
    now: Callable[[], datetime] = _utc_now,
) -> int | None:
    """Parse an HTTP Retry-After delay or date into non-negative seconds."""

    if value is None:
        return None
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > MAX_RETRY_AFTER_HEADER_CHARS
        or any(ord(char) < MIN_PRINTABLE_CODEPOINT for char in stripped)
    ):
        return None
    if stripped.isascii() and stripped.isdecimal():
        return int(stripped)
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    current = now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return max(0, math.ceil((parsed - current).total_seconds()))


def _tls_minimum(context: ssl.SSLContext) -> ssl.SSLContext:
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def create_tls_contexts() -> tuple[tuple[str, ssl.SSLContext], ...]:
    """Return verified trust contexts in system, truststore, certifi order."""

    contexts: list[tuple[str, ssl.SSLContext]] = [
        ("system_default", _tls_minimum(ssl.create_default_context()))
    ]
    try:
        truststore = importlib.import_module("truststore")
        contexts.append(
            (
                "truststore",
                _tls_minimum(truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)),
            )
        )
    except (ImportError, AttributeError, ssl.SSLError):
        pass
    try:
        certifi = importlib.import_module("certifi")
        certifi_context = ssl.create_default_context(cafile=certifi.where())
        contexts.append(("certifi", _tls_minimum(certifi_context)))
    except (ImportError, AttributeError, OSError, ssl.SSLError):
        pass
    return tuple(contexts)


def _certificate_failure(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _failure_from_exception(exc: BaseException) -> tuple[str, bool]:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", True
    if _certificate_failure(exc):
        return "certificate_verify_failed", False
    if isinstance(exc, httpx.ProxyError):
        return "proxy_error", True
    if isinstance(exc, httpx.ConnectError):
        cause: BaseException | None = exc
        while cause is not None:
            if isinstance(cause, socket.gaierror):
                return "dns_error", True
            cause = cause.__cause__ or cause.__context__
        return "network_error", True
    return "network_error", True


def _http_failure(status: int) -> tuple[str, bool]:
    if status == httpx.codes.NOT_FOUND:
        return "no_matching_result", False
    if status == httpx.codes.TOO_MANY_REQUESTS:
        return "rate_limited", True
    if status >= httpx.codes.INTERNAL_SERVER_ERROR:
        return "server_error", True
    return "http_error", False


def _bounded_json(response: httpx.Response, max_bytes: int) -> _RequestResult:
    content = bytearray()
    for chunk in response.iter_bytes():
        content.extend(chunk)
        if len(content) > max_bytes:
            return _RequestResult(
                failure_reason="response_too_large",
                http_status=response.status_code,
            )
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _RequestResult(
            failure_reason="malformed_json",
            http_status=response.status_code,
        )
    return _RequestResult(payload=payload, http_status=response.status_code)


class _ClientGroup:
    def __init__(
        self,
        *,
        config: CivitaiLookupConfig,
        transport: httpx.BaseTransport | None,
        contexts: Sequence[tuple[str, ssl.SSLContext]],
        rate_limit_gate: CivitaiRateLimitGate,
        wall_clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._rate_limit_gate = rate_limit_gate
        self._wall_clock = wall_clock
        self._clients = tuple(
            (
                source,
                httpx.Client(
                    transport=transport,
                    verify=context,
                    timeout=httpx.Timeout(config.timeout_seconds),
                    follow_redirects=False,
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                    trust_env=False,
                ),
            )
            for source, context in contexts
        )

    def __enter__(self) -> _ClientGroup:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        for _source, client in self._clients:
            client.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: object | None = None,
        max_response_bytes: int | None = None,
    ) -> _RequestResult:
        cooldown_seconds = self._rate_limit_gate.remaining_seconds()
        if cooldown_seconds > 0:
            return _RequestResult(
                failure_reason="rate_limit_cooldown",
                retryable=True,
                retry_after_seconds=cooldown_seconds,
            )
        last_failure = _RequestResult(failure_reason="network_error", retryable=True)
        for index, (source, client) in enumerate(self._clients):
            try:
                with client.stream(method, url, json=json_body) as response:
                    if response.is_redirect:
                        return _RequestResult(
                            failure_reason="redirect_rejected",
                            http_status=response.status_code,
                            tls_source=source,
                        )
                    if response.status_code != httpx.codes.OK:
                        reason, retryable = _http_failure(response.status_code)
                        retry_after_seconds: int | None = None
                        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                            supplied = parse_retry_after(
                                response.headers.get("Retry-After"),
                                now=self._wall_clock,
                            )
                            retry_after_seconds = min(
                                (
                                    supplied
                                    if supplied is not None
                                    else self._config.default_rate_limit_cooldown_seconds
                                ),
                                self._config.max_rate_limit_cooldown_seconds,
                            )
                            self._rate_limit_gate.defer(retry_after_seconds)
                        return _RequestResult(
                            failure_reason=reason,
                            http_status=response.status_code,
                            retryable=retryable,
                            retry_after_seconds=retry_after_seconds,
                            tls_source=source,
                        )
                    result = _bounded_json(
                        response,
                        max_response_bytes or self._config.max_response_bytes,
                    )
                    return replace(result, tls_source=source)
            except httpx.HTTPError as exc:
                reason, retryable = _failure_from_exception(exc)
                last_failure = _RequestResult(
                    failure_reason=reason,
                    retryable=retryable,
                    tls_source=source,
                )
                has_next_context = index + 1 < len(self._clients)
                if reason != "certificate_verify_failed" or not has_next_context:
                    return last_failure
        return last_failure

    def get(self, url: str) -> _RequestResult:
        return self._request("GET", url)

    def post_json(
        self,
        url: str,
        value: object,
        *,
        max_response_bytes: int,
    ) -> _RequestResult:
        return self._request(
            "POST",
            url,
            json_body=value,
            max_response_bytes=max_response_bytes,
        )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


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


def _model_type(payload: Mapping[str, object]) -> str | None:
    model = _mapping(payload.get("model"))
    raw = _text(payload.get("modelType"), max_chars=64) or _text(
        model.get("type"),
        max_chars=64,
    )
    return model_type_to_resource_type(raw)


def _matching_file(
    payload: Mapping[str, object],
    queried_hash: str,
) -> Mapping[str, object] | None:
    files = payload.get("files")
    if not isinstance(files, list):
        return None
    normalized = queried_hash.casefold()
    for value in files:
        file = _mapping(value)
        hashes = hash_record_from_mapping(file.get("hashes"))
        if hashes is not None and any(
            candidate.casefold() == normalized for _name, candidate in iter_hashes(hashes)
        ):
            return file
    return None


def _identity_ids(payload: Mapping[str, object]) -> tuple[int | None, int | None]:
    model = _mapping(payload.get("model"))
    model_id = _positive_int(payload.get("modelId")) or _positive_int(model.get("id"))
    version_id = _positive_int(payload.get("modelVersionId")) or _positive_int(payload.get("id"))
    return model_id, version_id


def _type_matches_role(
    resource: ResourceRecord,
    resource_type: str | None,
    *,
    allow_ambiguous: bool = False,
) -> bool:
    return resource_type_matches_role(
        resource.role,
        resource_type,
        allow_ambiguous=allow_ambiguous,
    )


def _ambiguous_for_role(resource: ResourceRecord, resource_type: str | None) -> bool:
    return resource_type_is_ambiguous(resource.role, resource_type)


def _parse_payload_identity(  # noqa: PLR0911
    payload: object,
    *,
    resource: ResourceRecord,
    queried_hash: str | None = None,
    allow_ambiguous_types: bool = False,
    allow_file_role_evidence: bool = False,
) -> tuple[_PayloadIdentity | None, tuple[ScanIssue, ...]]:
    if not isinstance(payload, Mapping):
        return None, (ScanIssue("civitai_response_schema_invalid"),)
    file = _matching_file(payload, queried_hash) if queried_hash is not None else None
    if queried_hash is not None and file is None:
        return None, (ScanIssue("civitai_response_hash_mismatch"),)

    model_id, version_id = _identity_ids(payload)
    if version_id is None:
        return None, (ScanIssue("civitai_response_version_missing"),)
    air_text = _text(payload.get("air"), max_chars=4096)
    parsed_air = (
        parse_air(air_text, provenance=IdentitySource.API) if air_text is not None else None
    )
    if parsed_air is not None and parsed_air.identity is None:
        return None, parsed_air.issues
    identity = parsed_air.identity if parsed_air is not None else None
    if identity is not None and (
        (model_id is not None and identity.model_id != model_id)
        or identity.model_version_id != version_id
    ):
        return None, (ScanIssue("civitai_response_air_id_conflict"),)

    file_hashes = hash_record_from_mapping(file.get("hashes")) if file is not None else None
    file_id = _positive_int(file.get("id")) if file is not None else None
    file_type = _text(file.get("type"), max_chars=64) if file is not None else None
    file_primary = _optional_bool(file.get("primary")) if file is not None else None
    file_format = (
        normalize_model_file_format(
            _text(_mapping(file.get("metadata")).get("format"), max_chars=32)
        )
        if file is not None
        else None
    )

    resource_type = identity.resource_type if identity is not None else _model_type(payload)
    type_matches = _type_matches_role(
        resource,
        resource_type,
        allow_ambiguous=allow_ambiguous_types,
    )
    file_matches = allow_file_role_evidence and model_file_type_matches_role(
        resource.role, file_type
    )
    if not type_matches and not file_matches:
        return None, (ScanIssue("civitai_response_type_mismatch"),)

    model = _mapping(payload.get("model"))
    issues = list(parsed_air.issues if parsed_air is not None else ())
    if identity is not None and file_id is not None:
        attached = attach_file_to_air_identity(
            identity,
            file_id=str(file_id),
            file_format=file_format,
            pin_canonical=file_primary is not True,
        )
        if attached.identity is None:
            conflict = any(
                issue.code in {"air_file_format_conflict", "air_file_id_conflict"}
                for issue in attached.issues
            )
            code = (
                "civitai_response_air_file_conflict"
                if conflict
                else "civitai_response_air_file_invalid"
            )
            return None, (ScanIssue(code),)
        identity = attached.identity
        issues.extend(attached.issues)

    resolved = (
        replace(
            identity,
            file_type=file_type,
            file_primary=file_primary,
            base_model=_text(payload.get("baseModel"), max_chars=128),
            model_name=_text(model.get("name")),
            model_version_name=_text(payload.get("name")),
        )
        if identity is not None
        else ResourceIdentity(
            source=IdentitySource.API,
            resource_type=resource_type,
            identity_source="civitai",
            identity_id=str(model_id) if model_id is not None else None,
            identity_version=str(version_id),
            model_id=model_id,
            model_version_id=version_id,
            file_id=str(file_id) if file_id is not None else None,
            format=file_format,
            file_type=file_type,
            file_primary=file_primary,
            base_model=_text(payload.get("baseModel"), max_chars=128),
            model_name=_text(model.get("name")),
            model_version_name=_text(payload.get("name")),
        )
    )
    return _PayloadIdentity(resolved, file_hashes or HashRecord()), tuple(issues)


def _same_identity(left: ResourceIdentity, right: ResourceIdentity) -> bool:
    if left.canonical_air is not None or right.canonical_air is not None:
        return left.canonical_air == right.canonical_air
    return (
        left.model_id == right.model_id
        and left.model_version_id == right.model_version_id
        and left.resource_type == right.resource_type
    )


_DIAGNOSTIC_PRIORITY = {
    "multiple_compatible_candidates_conflict": 60,
    "hash_identity_conflict": 50,
    "no_role_compatible_shared_hash_candidate": 40,
    "resource_type_mismatch": 30,
    "no_hash_match": 20,
    "multiple_compatible_candidates": 10,
}


def _preferred_diagnostics(
    values: Sequence[_AttemptDiagnostics],
    *,
    fallback_reason: str | None = None,
) -> _AttemptDiagnostics:
    if not values:
        return _AttemptDiagnostics(reason=fallback_reason)
    selected = max(
        values,
        key=lambda item: _DIAGNOSTIC_PRIORITY.get(item.reason or "", 0),
    )
    if selected.reason is not None:
        return selected
    return replace(selected, reason=fallback_reason)


def _select_role_compatible_identity(
    payload: object,
    *,
    resource: ResourceRecord,
    queried_hash: str,
) -> tuple[
    _PayloadIdentity | None,
    tuple[ScanIssue, ...],
    _AttemptDiagnostics,
]:
    if not isinstance(payload, list):
        return (
            None,
            (ScanIssue("civitai_response_schema_invalid"),),
            _AttemptDiagnostics(reason="response_schema_invalid"),
        )
    if len(payload) > MAX_ROLE_MATCH_CANDIDATES:
        return (
            None,
            (ScanIssue("civitai_response_candidate_limit_exceeded"),),
            _AttemptDiagnostics(reason="response_candidate_limit_exceeded"),
        )

    matches: list[tuple[_PayloadIdentity, tuple[ScanIssue, ...]]] = []
    for candidate in payload:
        parsed, issues = _parse_payload_identity(
            candidate,
            resource=resource,
            queried_hash=queried_hash,
            allow_ambiguous_types=True,
            allow_file_role_evidence=True,
        )
        if parsed is None:
            continue
        matches.append((parsed, issues))
    if not matches:
        return (
            None,
            (ScanIssue("civitai_response_role_match_missing"),),
            _AttemptDiagnostics(
                reason="no_role_compatible_shared_hash_candidate",
                candidate_count=len(payload),
                compatible_candidate_count=0,
            ),
        )

    selected, selected_issues = matches[0]
    if any(not _same_identity(selected.identity, item.identity) for item, _issues in matches[1:]):
        return (
            None,
            (ScanIssue("civitai_response_role_identity_conflict"),),
            _AttemptDiagnostics(
                reason="multiple_compatible_candidates_conflict",
                candidate_count=len(payload),
                compatible_candidate_count=len(matches),
            ),
        )
    hashes = selected.hashes
    for item, _issues in matches[1:]:
        hashes = merge_hashes(hashes, item.hashes)
    return (
        _PayloadIdentity(selected.identity, hashes),
        (*selected_issues, ScanIssue("civitai_duplicate_hash_role_disambiguated")),
        _AttemptDiagnostics(
            reason=("multiple_compatible_candidates" if len(matches) > 1 else None),
            candidate_count=len(payload),
            compatible_candidate_count=len(matches),
        ),
    )


class CivitaiClient:
    """Resolve identities without ever sending local content or paths."""

    def __init__(
        self,
        config: CivitaiLookupConfig = DEFAULT_LOOKUP_CONFIG,
        *,
        transport: httpx.BaseTransport | None = None,
        tls_contexts: Sequence[tuple[str, ssl.SSLContext]] | None = None,
        rate_limit_gate: CivitaiRateLimitGate | None = None,
        wall_clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.config = config
        self._transport = transport
        self._tls_contexts = tuple(tls_contexts or create_tls_contexts())
        self._rate_limit_gate = rate_limit_gate or CivitaiRateLimitGate()
        self._wall_clock = wall_clock

    def _url(self, suffix: str) -> str:
        return f"{self.config.api_base_url.rstrip('/')}/{suffix}"

    def _cooldown_result(self, resource: ResourceRecord) -> CivitaiLookupResult | None:
        retry_after_seconds = self._rate_limit_gate.remaining_seconds()
        if retry_after_seconds < 1:
            return None
        return CivitaiLookupResult(
            status=LookupStatus.FAILED,
            issues=(ScanIssue("civitai_lookup_failed", node_id=resource.node_id),),
            failure_reason="rate_limit_cooldown",
            retryable=True,
            retry_after_seconds=retry_after_seconds,
            diagnostic_reason="rate_limit_cooldown",
        )

    def _lookup_preflight(
        self,
        resource: ResourceRecord,
    ) -> tuple[tuple[tuple[str, str], ...], CivitaiLookupResult | None]:
        if not self.config.enabled:
            return (), CivitaiLookupResult(status=LookupStatus.SKIPPED_DISABLED)
        available = tuple(iter_hashes(resource.hashes))
        if not available:
            return (), CivitaiLookupResult(status=LookupStatus.SKIPPED_NO_HASH)
        return available, self._cooldown_result(resource)

    def _details(
        self,
        clients: _ClientGroup,
        version_id: int,
        resource: ResourceRecord,
        *,
        queried_hash: str | None = None,
        allow_ambiguous_types: bool = False,
    ) -> tuple[_PayloadIdentity | None, _RequestResult, tuple[ScanIssue, ...]]:
        response = clients.get(self._url(f"model-versions/{version_id}"))
        if response.payload is None:
            return None, response, ()
        identity, issues = _parse_payload_identity(
            response.payload,
            resource=resource,
            queried_hash=queried_hash,
            allow_ambiguous_types=allow_ambiguous_types,
        )
        return identity, response, issues

    def _sha256_role_attempt(
        self,
        clients: _ClientGroup,
        resource: ResourceRecord,
        hash_value: str,
        original_issues: tuple[ScanIssue, ...],
    ) -> tuple[
        _PayloadIdentity | None,
        _RequestResult,
        tuple[ScanIssue, ...],
        _AttemptDiagnostics,
    ]:
        response = clients.post_json(
            self._url("model-versions/by-hash"),
            [hash_value],
            max_response_bytes=self.config.max_role_response_bytes,
        )
        if response.payload is None:
            diagnostics = _AttemptDiagnostics(
                reason=(
                    "no_hash_match"
                    if response.failure_reason == "no_matching_result"
                    else response.failure_reason
                ),
                candidate_count=0 if response.http_status == httpx.codes.NOT_FOUND else None,
                compatible_candidate_count=(
                    0 if response.http_status == httpx.codes.NOT_FOUND else None
                ),
            )
            return None, response, original_issues, diagnostics
        identity, issues, diagnostics = _select_role_compatible_identity(
            response.payload,
            resource=resource,
            queried_hash=hash_value,
        )
        if identity is not None:
            return identity, response, issues, diagnostics
        return None, response, (*original_issues, *issues), diagnostics

    def _hash_attempt(
        self,
        clients: _ClientGroup,
        resource: ResourceRecord,
        algorithm: str,
        hash_value: str,
    ) -> tuple[
        _PayloadIdentity | None,
        _RequestResult,
        tuple[ScanIssue, ...],
        _AttemptDiagnostics,
    ]:
        response = clients.get(self._url(f"model-versions/by-hash/{hash_value}"))
        if response.payload is None:
            diagnostics = _AttemptDiagnostics(
                reason=(
                    "no_hash_match"
                    if response.failure_reason == "no_matching_result"
                    else response.failure_reason
                ),
                candidate_count=0 if response.http_status == httpx.codes.NOT_FOUND else None,
                compatible_candidate_count=(
                    0 if response.http_status == httpx.codes.NOT_FOUND else None
                ),
            )
            return None, response, (), diagnostics
        identity, issues = _parse_payload_identity(
            response.payload,
            resource=resource,
            queried_hash=hash_value,
        )
        diagnostics = _AttemptDiagnostics(
            reason=(
                "no_hash_match"
                if any(issue.code == "civitai_response_hash_mismatch" for issue in issues)
                else (
                    "resource_type_mismatch"
                    if any(issue.code == "civitai_response_type_mismatch" for issue in issues)
                    else None
                )
            ),
            candidate_count=1,
            compatible_candidate_count=1 if identity is not None else 0,
        )
        supports_bulk_disambiguation = algorithm in BULK_HASH_ALGORITHMS
        needs_role_disambiguation = (
            supports_bulk_disambiguation
            and identity is None
            and any(issue.code == "civitai_response_type_mismatch" for issue in issues)
        )
        used_ambiguous_type = False
        if needs_role_disambiguation:
            identity, response, issues, diagnostics = self._sha256_role_attempt(
                clients,
                resource,
                hash_value,
                issues,
            )
            used_ambiguous_type = identity is not None and _ambiguous_for_role(
                resource,
                identity.identity.resource_type,
            )
        if identity is None or identity.identity.canonical_air is not None:
            return identity, response, issues, diagnostics
        version_id = identity.identity.model_version_id
        if version_id is None:
            return identity, response, issues, diagnostics
        detailed, detail_response, detail_issues = self._details(
            clients,
            version_id,
            resource,
            queried_hash=hash_value,
            allow_ambiguous_types=used_ambiguous_type,
        )
        if detailed is not None:
            return detailed, detail_response, (*issues, *detail_issues), diagnostics
        return identity, response, (*issues, *detail_issues), diagnostics

    def lookup(self, resource: ResourceRecord) -> CivitaiLookupResult:
        """Fall back through hashes in authority order until one resolves."""

        available, preflight_result = self._lookup_preflight(resource)
        if preflight_result is not None:
            return preflight_result

        attempt_diagnostics: list[_AttemptDiagnostics] = []
        issues: list[ScanIssue] = []
        attempted: list[str] = []
        last_failure = _RequestResult(failure_reason="no_matching_result")
        with _ClientGroup(
            config=self.config,
            transport=self._transport,
            contexts=self._tls_contexts,
            rate_limit_gate=self._rate_limit_gate,
            wall_clock=self._wall_clock,
        ) as clients:
            for algorithm, value in available:
                attempted.append(algorithm)
                identity, response, attempt_issues, diagnostics = self._hash_attempt(
                    clients,
                    resource,
                    algorithm,
                    value,
                )
                attempt_diagnostics.append(diagnostics)
                issues.extend(attempt_issues)
                last_failure = response
                if any(
                    issue.code == "civitai_response_role_identity_conflict"
                    for issue in attempt_issues
                ):
                    return CivitaiLookupResult(
                        status=LookupStatus.CONFLICT,
                        issues=tuple(issues),
                        attempted_hashes=tuple(attempted),
                        failure_reason="identity_conflict",
                        http_status=response.http_status,
                        retryable=response.retryable,
                        retry_after_seconds=response.retry_after_seconds,
                        tls_source=response.tls_source,
                        diagnostic_reason=(
                            diagnostics.reason or "multiple_compatible_candidates_conflict"
                        ),
                        candidate_count=diagnostics.candidate_count,
                        compatible_candidate_count=(diagnostics.compatible_candidate_count),
                    )
                if identity is not None:
                    return CivitaiLookupResult(
                        identity=identity.identity,
                        hashes=merge_hashes(resource.hashes, identity.hashes),
                        status=LookupStatus.RESOLVED,
                        issues=tuple(issues),
                        attempted_hashes=tuple(attempted),
                        http_status=response.http_status,
                        retryable=response.retryable,
                        retry_after_seconds=response.retry_after_seconds,
                        tls_source=response.tls_source,
                        diagnostic_reason=diagnostics.reason,
                        candidate_count=diagnostics.candidate_count,
                        compatible_candidate_count=(diagnostics.compatible_candidate_count),
                    )
                if response.payload is None and response.failure_reason not in {
                    None,
                    "no_matching_result",
                }:
                    issues.append(ScanIssue("civitai_lookup_failed", node_id=resource.node_id))
                    return CivitaiLookupResult(
                        status=LookupStatus.FAILED,
                        issues=tuple(issues),
                        attempted_hashes=tuple(attempted),
                        failure_reason=response.failure_reason,
                        http_status=response.http_status,
                        retryable=response.retryable,
                        retry_after_seconds=response.retry_after_seconds,
                        tls_source=response.tls_source,
                        diagnostic_reason=(diagnostics.reason or response.failure_reason),
                        candidate_count=diagnostics.candidate_count,
                        compatible_candidate_count=(diagnostics.compatible_candidate_count),
                    )

        diagnostics = _preferred_diagnostics(
            attempt_diagnostics,
            fallback_reason=last_failure.failure_reason,
        )
        issues.append(ScanIssue("civitai_lookup_failed", node_id=resource.node_id))
        return CivitaiLookupResult(
            status=LookupStatus.FAILED,
            issues=tuple(issues),
            attempted_hashes=tuple(attempted),
            failure_reason=last_failure.failure_reason,
            http_status=last_failure.http_status,
            retryable=last_failure.retryable,
            retry_after_seconds=last_failure.retry_after_seconds,
            tls_source=last_failure.tls_source,
            diagnostic_reason=diagnostics.reason,
            candidate_count=diagnostics.candidate_count,
            compatible_candidate_count=diagnostics.compatible_candidate_count,
        )

    def complete_version(
        self,
        resource: ResourceRecord,
        version_id: int,
    ) -> CivitaiLookupResult:
        """Complete an explicit partial model-version identity when enabled."""

        if not self.config.enabled:
            return CivitaiLookupResult(status=LookupStatus.SKIPPED_DISABLED)
        if (cooldown := self._cooldown_result(resource)) is not None:
            return cooldown
        with _ClientGroup(
            config=self.config,
            transport=self._transport,
            contexts=self._tls_contexts,
            rate_limit_gate=self._rate_limit_gate,
            wall_clock=self._wall_clock,
        ) as clients:
            identity, response, issues = self._details(clients, version_id, resource)
        if identity is None:
            diagnostic_reason = (
                "model_version_not_found"
                if response.failure_reason == "no_matching_result"
                else response.failure_reason
            )
            return CivitaiLookupResult(
                status=LookupStatus.FAILED,
                issues=(*issues, ScanIssue("civitai_lookup_failed", node_id=resource.node_id)),
                failure_reason=response.failure_reason,
                http_status=response.http_status,
                retryable=response.retryable,
                retry_after_seconds=response.retry_after_seconds,
                tls_source=response.tls_source,
                diagnostic_reason=diagnostic_reason,
                candidate_count=(0 if response.http_status == httpx.codes.NOT_FOUND else None),
                compatible_candidate_count=(
                    0 if response.http_status == httpx.codes.NOT_FOUND else None
                ),
            )
        return CivitaiLookupResult(
            identity=identity.identity,
            hashes=merge_hashes(resource.hashes, identity.hashes),
            status=LookupStatus.RESOLVED,
            issues=issues,
            http_status=response.http_status,
            retryable=response.retryable,
            retry_after_seconds=response.retry_after_seconds,
            tls_source=response.tls_source,
            candidate_count=1,
            compatible_candidate_count=1,
        )


def no_private_request_data(request: httpx.Request) -> bool:
    """Return whether a request contains only approved public identity data."""

    if (
        request.url.host != _SAFE_API_HOST
        or request.url.scheme != "https"
        or "authorization" in request.headers
    ):
        return False
    if request.method == "GET":
        return request.content == b""
    if request.method != "POST" or request.url.path.rstrip("/") != "/api/v1/model-versions/by-hash":
        return False
    try:
        value = json.loads(request.content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], str)
        and re.fullmatch(r"[0-9A-Fa-f]{64}", value[0]) is not None
    )


__all__ = [
    "CIVITAI_API_BASE",
    "DEFAULT_LOOKUP_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_MAX_ROLE_RESPONSE_BYTES",
    "DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS",
    "MAX_RATE_LIMIT_COOLDOWN_SECONDS",
    "PROCESS_RATE_LIMIT_GATE",
    "USER_AGENT",
    "CivitaiClient",
    "CivitaiLookupConfig",
    "CivitaiLookupResult",
    "CivitaiRateLimitGate",
    "create_tls_contexts",
    "no_private_request_data",
    "parse_retry_after",
]
