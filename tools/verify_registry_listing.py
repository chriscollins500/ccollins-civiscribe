"""Synchronize and verify CiviScribe's public Comfy Registry listing."""

from __future__ import annotations

import argparse
import os
import re
import ssl
import sys
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

import httpx

from civiscribe.tls import create_tls_contexts
from tools.prepare_registry_changelog import read_project_version

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYPROJECT = PROJECT_ROOT / "pyproject.toml"
DEFAULT_VERSION_FILE = PROJECT_ROOT / "civiscribe" / "version.py"
REGISTRY_API_ORIGIN: Final = "https://api.comfy.org"
REGISTRY_USER_AGENT: Final = "CCollins-CiviScribe-Registry-Check/1.0"
ACTIVE_STATUS: Final = "NodeVersionStatusActive"
PENDING_STATUS: Final = "NodeVersionStatusPending"
ACCEPTABLE_CURRENT_STATUSES: Final = frozenset({ACTIVE_STATUS, PENDING_STATUS})
MAX_RESPONSE_BYTES: Final = 2_000_000
HTTP_SUCCESS_MIN: Final = 200
HTTP_SUCCESS_MAX: Final = 300
MAX_ATTEMPTS: Final = 60
MAX_POLL_DELAY_SECONDS: Final = 30.0
MAX_TIMEOUT_SECONDS: Final = 60.0
MAX_VERSION_PAGES: Final = 100
VERSION_PAGE_SIZE: Final = 100
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_FINAL_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class RegistryListingError(RuntimeError):
    """Raised when Registry synchronization or verification cannot be proven."""


class _RegistryRequestError(RegistryListingError):
    """Sanitized request failure with enough detail for verified TLS fallback."""

    def __init__(self, message: str, *, certificate_failure: bool = False) -> None:
        super().__init__(message)
        self.certificate_failure = certificate_failure


@dataclass(frozen=True, slots=True)
class ProjectRegistryMetadata:
    """Expected public Registry fields derived from checked-in project metadata."""

    node_id: str
    publisher_id: str
    display_name: str
    description: str
    version: str


@dataclass(frozen=True, slots=True)
class RegistryListingResult:
    """Sanitized evidence from a successful Registry verification."""

    description_updated: bool
    current_version_status: str
    catalog_latest_version: str
    latest_active_version: str
    tls_source: str


@dataclass(frozen=True, slots=True)
class RegistryRequest:
    """Optional data for one bounded Registry request."""

    context: str
    token: str | None = None
    json_body: Mapping[str, str] | None = None
    params: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class RegistryCheckOptions:
    """Bounded synchronization settings and injectable test seams."""

    token: str | None = None
    sync_description: bool = False
    attempts: int = 6
    poll_delay_seconds: float = 5.0
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = None
    tls_contexts: Sequence[tuple[str, ssl.SSLContext]] | None = None
    sleep: Callable[[float], None] = time.sleep


def _required_string(mapping: Mapping[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryListingError(f"{context}.{key} must be a non-empty string")
    return value


def load_project_registry_metadata(
    pyproject_path: Path = DEFAULT_PYPROJECT,
    version_file: Path = DEFAULT_VERSION_FILE,
) -> ProjectRegistryMetadata:
    """Load the expected listing from static project files without executing them."""

    document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = document.get("project")
    tool = document.get("tool")
    if not isinstance(project, dict) or not isinstance(tool, dict):
        raise RegistryListingError("pyproject.toml is missing project or tool metadata")
    comfy = tool.get("comfy")
    if not isinstance(comfy, dict):
        raise RegistryListingError("pyproject.toml is missing tool.comfy metadata")

    node_id = _required_string(project, "name", "project")
    publisher_id = _required_string(comfy, "PublisherId", "tool.comfy")
    if _SAFE_ID.fullmatch(node_id) is None or _SAFE_ID.fullmatch(publisher_id) is None:
        raise RegistryListingError("Registry node or publisher ID contains unsafe characters")

    return ProjectRegistryMetadata(
        node_id=node_id,
        publisher_id=publisher_id,
        display_name=_required_string(comfy, "DisplayName", "tool.comfy"),
        description=_required_string(project, "description", "project"),
        version=read_project_version(version_file),
    )


def _decode_object(response: httpx.Response, context: str) -> dict[str, Any]:
    if not HTTP_SUCCESS_MIN <= response.status_code < HTTP_SUCCESS_MAX:
        raise RegistryListingError(f"{context} returned HTTP {response.status_code}")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise RegistryListingError(f"{context} response exceeded the size limit")
    try:
        payload = response.json()
    except ValueError as error:
        raise RegistryListingError(f"{context} returned malformed JSON") from error
    if not isinstance(payload, dict):
        raise RegistryListingError(f"{context} returned a non-object response")
    return cast(dict[str, Any], payload)


def _request_object(
    client: httpx.Client,
    method: str,
    path: str,
    request: RegistryRequest,
) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": REGISTRY_USER_AGENT}
    if request.token is not None:
        headers["Authorization"] = f"Bearer {request.token}"
    try:
        with client.stream(
            method,
            path,
            headers=headers,
            json=request.json_body,
            params=request.params,
        ) as response:
            content = bytearray()
            for block in response.iter_bytes(chunk_size=64 * 1024):
                content.extend(block)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise RegistryListingError(
                        f"{request.context} response exceeded the size limit"
                    )
            return _decode_object(
                httpx.Response(response.status_code, content=bytes(content)), request.context
            )
    except httpx.TimeoutException as error:
        raise _RegistryRequestError(f"{request.context} timed out") from error
    except httpx.HTTPError as error:
        certificate_failure = _certificate_failure(error)
        reason = "certificate verification" if certificate_failure else type(error).__name__
        raise _RegistryRequestError(
            f"{request.context} failed with {reason}",
            certificate_failure=certificate_failure,
        ) from error


def _certificate_failure(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _fetch_node(client: httpx.Client, node_id: str) -> dict[str, Any]:
    return _request_object(
        client,
        "GET",
        f"/nodes/{node_id}",
        RegistryRequest(context="Registry node lookup"),
    )


def _fetch_versions(client: httpx.Client, node_id: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    expected_total: int | None = None
    seen: set[str] = set()
    for page in range(1, MAX_VERSION_PAGES + 1):
        payload = _request_object(
            client,
            "GET",
            "/versions",
            RegistryRequest(
                context="Registry version lookup",
                params={
                    "nodeId": node_id,
                    "page": str(page),
                    "pageSize": str(VERSION_PAGE_SIZE),
                    "include_status_reason": "false",
                },
            ),
        )
        page_records = _version_records(payload)
        total_pages = _page_count(payload, page)
        if expected_total is not None and total_pages != expected_total:
            raise RegistryListingError("Registry version pagination changed during readback")
        expected_total = total_pages
        for record in page_records:
            version = _required_string(record, "version", "Registry version")
            if version in seen:
                raise RegistryListingError("Registry returned duplicate version records")
            seen.add(version)
        if len(page_records) > VERSION_PAGE_SIZE or (page < total_pages and not page_records):
            raise RegistryListingError("Registry returned an invalid version page")
        records.extend(page_records)
        if page == total_pages:
            return {"versions": records}
    raise RegistryListingError("Registry version pagination exceeded the page limit")


def _page_count(payload: Mapping[str, Any], page: int) -> int:
    total_pages = payload.get("totalPages")
    if (
        type(total_pages) is not int
        or not page <= total_pages <= MAX_VERSION_PAGES
        or type(payload.get("page")) is not int
        or payload["page"] != page
    ):
        raise RegistryListingError("Registry returned invalid pagination metadata")
    return total_pages


def _node_update_payload(
    node: Mapping[str, Any],
    expected: ProjectRegistryMetadata,
) -> dict[str, str]:
    """Mirror the Registry web form's five-field update contract."""

    node_id = _required_string(node, "id", "Registry node")
    if node_id != expected.node_id:
        raise RegistryListingError("Registry returned a different node ID")
    return {
        "id": node_id,
        "name": expected.display_name,
        "description": expected.description,
        "license": _required_string(node, "license", "Registry node"),
        "repository": _required_string(node, "repository", "Registry node"),
    }


def _update_description(
    client: httpx.Client,
    node: Mapping[str, Any],
    expected: ProjectRegistryMetadata,
    token: str,
) -> None:
    if not token.strip():
        raise RegistryListingError("Registry token environment variable is empty")
    _request_object(
        client,
        "PUT",
        f"/publishers/{expected.publisher_id}/nodes/{expected.node_id}",
        RegistryRequest(
            context="Registry node update",
            token=token,
            json_body=_node_update_payload(node, expected),
        ),
    )


def _version_key(value: str) -> tuple[int, int, int]:
    match = _FINAL_VERSION.fullmatch(value)
    if match is None:
        raise RegistryListingError(f"Registry returned unsupported version syntax: {value}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _version_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_versions = payload.get("versions")
    if not isinstance(raw_versions, list):
        raise RegistryListingError("Registry version lookup omitted versions")
    records: list[dict[str, Any]] = []
    for raw in raw_versions:
        if not isinstance(raw, dict):
            raise RegistryListingError("Registry returned a malformed version record")
        records.append(cast(dict[str, Any], raw))
    return records


def _verify_snapshot(
    node: Mapping[str, Any],
    versions_payload: Mapping[str, Any],
    expected: ProjectRegistryMetadata,
    *,
    description_updated: bool,
    tls_source: str,
) -> RegistryListingResult:
    if _required_string(node, "description", "Registry node") != expected.description:
        raise RegistryListingError("public Registry description is stale")

    records = _version_records(versions_payload)
    current = next(
        (record for record in records if record.get("version") == expected.version),
        None,
    )
    if current is None:
        raise RegistryListingError(
            f"Registry does not yet list published version {expected.version}"
        )
    current_status = _required_string(current, "status", "Registry version")
    if current_status not in ACCEPTABLE_CURRENT_STATUSES:
        raise RegistryListingError(
            f"published version {expected.version} has unacceptable Registry status "
            f"{current_status}"
        )

    active_versions = [
        _required_string(record, "version", "Registry version")
        for record in records
        if record.get("status") == ACTIVE_STATUS
    ]
    if not active_versions:
        raise RegistryListingError("Registry does not report an active version")
    latest_active = max(active_versions, key=_version_key)

    latest = node.get("latest_version")
    if not isinstance(latest, dict):
        raise RegistryListingError("Registry node omitted latest_version")
    catalog_latest = _required_string(latest, "version", "Registry latest_version")
    if catalog_latest != latest_active:
        raise RegistryListingError(
            "public Registry latest version is stale: "
            f"catalog={catalog_latest}, active={latest_active}"
        )

    return RegistryListingResult(
        description_updated=description_updated,
        current_version_status=current_status,
        catalog_latest_version=catalog_latest,
        latest_active_version=latest_active,
        tls_source=tls_source,
    )


def synchronize_and_verify_registry_listing(
    expected: ProjectRegistryMetadata,
    options: RegistryCheckOptions | None = None,
) -> RegistryListingResult:
    """Synchronize description when requested, then prove public listing consistency."""

    options = options or RegistryCheckOptions()
    contexts = _validated_contexts(options)

    description_updated = False
    last_error: RegistryListingError | None = None
    for attempt in range(options.attempts):
        for context_index, (tls_source, tls_context) in enumerate(contexts):
            try:
                with httpx.Client(
                    base_url=REGISTRY_API_ORIGIN,
                    timeout=options.timeout_seconds,
                    follow_redirects=False,
                    transport=options.transport,
                    verify=tls_context,
                    trust_env=False,
                ) as client:
                    node = _fetch_node(client, expected.node_id)
                    if options.sync_description and not description_updated:
                        _update_description(client, node, expected, cast(str, options.token))
                        description_updated = True
                        node = _fetch_node(client, expected.node_id)
                    versions = _fetch_versions(client, expected.node_id)
                    return _verify_snapshot(
                        node,
                        versions,
                        expected,
                        description_updated=description_updated,
                        tls_source=tls_source,
                    )
            except _RegistryRequestError as error:
                last_error = error
                if error.certificate_failure and context_index + 1 < len(contexts):
                    continue
                break
            except RegistryListingError as error:
                last_error = error
                break
        if attempt + 1 < options.attempts:
            options.sleep(options.poll_delay_seconds)

    if last_error is None:
        raise RegistryListingError("Registry verification did not run")
    raise last_error


def _validated_contexts(
    options: RegistryCheckOptions,
) -> Sequence[tuple[str, ssl.SSLContext]]:
    """Validate bounded options and return the ordered verified trust contexts."""

    if options.attempts < 1 or options.attempts > MAX_ATTEMPTS:
        raise RegistryListingError("attempts must be between 1 and 60")
    if not 0 <= options.poll_delay_seconds <= MAX_POLL_DELAY_SECONDS:
        raise RegistryListingError("poll delay must be between 0 and 30 seconds")
    if not 0 < options.timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise RegistryListingError("timeout must be greater than 0 and at most 60 seconds")
    if options.sync_description and options.token is None:
        raise RegistryListingError("description synchronization requires a Registry token")
    contexts = options.tls_contexts or create_tls_contexts()
    if not contexts:
        raise RegistryListingError("no verified TLS context is available")
    return contexts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize and verify the public Comfy Registry listing."
    )
    parser.add_argument("--pyproject", type=Path, default=DEFAULT_PYPROJECT)
    parser.add_argument("--version-file", type=Path, default=DEFAULT_VERSION_FILE)
    parser.add_argument("--sync-description", action="store_true")
    parser.add_argument("--token-env", default="REGISTRY_ACCESS_TOKEN")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--poll-delay-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run Registry synchronization and verification without exposing credentials."""

    arguments = _parser().parse_args(argv)
    try:
        expected = load_project_registry_metadata(
            cast(Path, arguments.pyproject),
            cast(Path, arguments.version_file),
        )
        sync_description = cast(bool, arguments.sync_description)
        token_env = cast(str, arguments.token_env)
        token = os.environ.get(token_env) if sync_description else None
        if sync_description and token is None:
            raise RegistryListingError(f"required environment variable {token_env} is unset")
        result = synchronize_and_verify_registry_listing(
            expected,
            RegistryCheckOptions(
                token=token,
                sync_description=sync_description,
                attempts=cast(int, arguments.attempts),
                poll_delay_seconds=cast(float, arguments.poll_delay_seconds),
                timeout_seconds=cast(float, arguments.timeout_seconds),
            ),
        )
    except (OSError, RegistryListingError, tomllib.TOMLDecodeError) as error:
        print(f"Registry listing verification failed: {error}", file=sys.stderr)
        return 1

    action = "updated and verified" if result.description_updated else "verified"
    print(
        f"Registry listing {action}: {expected.node_id}; "
        f"published {expected.version} is {result.current_version_status}; "
        f"catalog latest active version is {result.catalog_latest_version}; "
        f"TLS trust source is {result.tls_source}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
