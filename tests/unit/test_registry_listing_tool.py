from __future__ import annotations

import json
import ssl
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from civiscribe.version import __version__
from tools.verify_registry_listing import (
    ACTIVE_STATUS,
    ProjectRegistryMetadata,
    RegistryCheckOptions,
    RegistryListingError,
    load_project_registry_metadata,
    synchronize_and_verify_registry_listing,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DESCRIPTION = (
    "Make every ComfyUI image Civitai-ready. CiviScribe saves PNG, JPEG, and WebP with "
    "your prompts, generation settings, model, LoRAs, hashes, and only the resources "
    "actually used. PNG files can also carry a reloadable workflow, so your uploads keep "
    "their creation details without manual metadata work."
)
EXPECTED = ProjectRegistryMetadata(
    node_id="ccollins-civiscribe",
    publisher_id="chrisecollins500",
    display_name="CCollins' CiviScribe",
    description=EXPECTED_DESCRIPTION,
    version="2.0.6",
)
AUTH_VALUE = "private-test-value"
REDACTION_SENTINEL = "never-report-this-value"
EXPECTED_TLS_FALLBACK_CALLS = 3


def _node(description: str, latest: str = "2.0.5") -> dict[str, object]:
    return {
        "id": EXPECTED.node_id,
        "name": EXPECTED.display_name,
        "description": description,
        "license": '{"text": "MIT"}',
        "repository": "https://github.com/chriscollins500/ccollins-civiscribe",
        "latest_version": {"version": latest},
    }


def _versions(current_status: str = "NodeVersionStatusPending") -> dict[str, object]:
    return {
        "page": 1,
        "totalPages": 1,
        "versions": [
            {"version": "2.0.6", "status": current_status},
            {"version": "2.0.5", "status": ACTIVE_STATUS},
            {"version": "2.0.4", "status": ACTIVE_STATUS},
        ],
    }


def test_project_registry_metadata_is_loaded_from_static_sources() -> None:
    metadata = load_project_registry_metadata()

    assert metadata == replace(EXPECTED, version=__version__)


def test_matching_listing_is_verified_without_mutation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/nodes/ccollins-civiscribe":
            return httpx.Response(200, json=_node(EXPECTED_DESCRIPTION))
        return httpx.Response(200, json=_versions())

    result = synchronize_and_verify_registry_listing(
        EXPECTED,
        RegistryCheckOptions(
            attempts=1,
            poll_delay_seconds=0,
            transport=httpx.MockTransport(handler),
        ),
    )

    assert result.description_updated is False
    assert result.current_version_status == "NodeVersionStatusPending"
    assert result.catalog_latest_version == "2.0.5"
    assert result.tls_source == "system_default"
    assert [request.method for request in requests] == ["GET", "GET"]


@pytest.mark.parametrize("initial_description", ["old description", EXPECTED_DESCRIPTION])
def test_description_is_synchronized_with_registry_ui_compatible_payload(
    initial_description: str,
) -> None:
    requests: list[httpx.Request] = []
    state = {"description": initial_description}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            payload = json.loads(request.content)
            assert payload == {
                "id": EXPECTED.node_id,
                "name": EXPECTED.display_name,
                "description": EXPECTED_DESCRIPTION,
                "license": '{"text": "MIT"}',
                "repository": "https://github.com/chriscollins500/ccollins-civiscribe",
            }
            assert request.headers["Authorization"] == f"Bearer {AUTH_VALUE}"
            state["description"] = EXPECTED_DESCRIPTION
            return httpx.Response(200, json=payload)
        if request.url.path == "/nodes/ccollins-civiscribe":
            return httpx.Response(200, json=_node(state["description"]))
        return httpx.Response(200, json=_versions())

    result = synchronize_and_verify_registry_listing(
        EXPECTED,
        RegistryCheckOptions(
            token=AUTH_VALUE,
            sync_description=True,
            attempts=1,
            poll_delay_seconds=0,
            transport=httpx.MockTransport(handler),
        ),
    )

    assert result.description_updated is True
    assert [request.method for request in requests] == ["GET", "PUT", "GET", "GET"]


@pytest.mark.parametrize(
    ("node", "versions", "message"),
    [
        (_node(EXPECTED_DESCRIPTION, latest="2.0.4"), _versions(), "latest version is stale"),
        (
            _node(EXPECTED_DESCRIPTION),
            {
                "page": 1,
                "totalPages": 1,
                "versions": [{"version": "2.0.5", "status": ACTIVE_STATUS}],
            },
            "does not yet list published version 2.0.6",
        ),
        (
            _node(EXPECTED_DESCRIPTION),
            _versions(current_status="NodeVersionStatusRejected"),
            "has unacceptable Registry status NodeVersionStatusRejected",
        ),
        (_node("old description"), _versions(), "description is stale"),
    ],
)
def test_inconsistent_public_listing_fails_closed(
    node: dict[str, object],
    versions: dict[str, object],
    message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = node if request.url.path.startswith("/nodes/") else versions
        return httpx.Response(200, json=payload)

    with pytest.raises(RegistryListingError, match=message):
        synchronize_and_verify_registry_listing(
            EXPECTED,
            RegistryCheckOptions(
                attempts=1,
                poll_delay_seconds=0,
                transport=httpx.MockTransport(handler),
            ),
        )


def test_sync_requires_token_and_rejects_bad_retry_settings() -> None:
    with pytest.raises(RegistryListingError, match="requires a Registry token"):
        synchronize_and_verify_registry_listing(
            EXPECTED,
            RegistryCheckOptions(sync_description=True),
        )
    with pytest.raises(RegistryListingError, match="attempts"):
        synchronize_and_verify_registry_listing(EXPECTED, RegistryCheckOptions(attempts=0))


def test_http_failure_is_sanitized_without_response_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=REDACTION_SENTINEL)

    with pytest.raises(RegistryListingError) as captured:
        synchronize_and_verify_registry_listing(
            EXPECTED,
            RegistryCheckOptions(
                attempts=1,
                poll_delay_seconds=0,
                transport=httpx.MockTransport(handler),
            ),
        )

    assert str(captured.value) == "Registry node lookup returned HTTP 403"
    assert REDACTION_SENTINEL not in str(captured.value)


def test_certificate_failure_uses_next_verified_tls_context() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            certificate_error = ssl.SSLCertVerificationError(1, "certificate verification failed")
            raise httpx.ConnectError("TLS failed", request=request) from certificate_error
        if request.url.path == "/nodes/ccollins-civiscribe":
            return httpx.Response(200, json=_node(EXPECTED_DESCRIPTION))
        return httpx.Response(200, json=_versions())

    contexts = (
        ("system_default", ssl.create_default_context()),
        ("truststore", ssl.create_default_context()),
    )
    result = synchronize_and_verify_registry_listing(
        EXPECTED,
        RegistryCheckOptions(
            attempts=1,
            poll_delay_seconds=0,
            transport=httpx.MockTransport(handler),
            tls_contexts=contexts,
        ),
    )

    assert result.tls_source == "truststore"
    assert calls == EXPECTED_TLS_FALLBACK_CALLS


def test_registry_tool_imports_without_image_runtime_dependencies() -> None:
    program = """
import importlib.abc
import sys
class RejectImageRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'PIL', 'torch'}:
            raise ImportError('unexpected image dependency: ' + fullname)
sys.meta_path.insert(0, RejectImageRuntime())
from tools.verify_registry_listing import load_project_registry_metadata
from tools.release_bundle import verify_bundle
from tools.publish_registry_bundle import publish
assert load_project_registry_metadata().node_id == 'ccollins-civiscribe'
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and project-authored program
        [sys.executable, "-c", program],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_version_readback_visits_later_pages_before_selecting_latest() -> None:
    pages: list[int] = []
    expected = replace(EXPECTED, version="2.0.100")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/nodes/"):
            return httpx.Response(200, json=_node(EXPECTED_DESCRIPTION, latest=expected.version))
        page = int(request.url.params["page"])
        pages.append(page)
        start, stop = (0, 100) if page == 1 else (100, 101)
        return httpx.Response(
            200,
            json={
                "page": page,
                "totalPages": 2,
                "versions": [
                    {"version": f"2.0.{i}", "status": ACTIVE_STATUS} for i in range(start, stop)
                ],
            },
        )

    result = synchronize_and_verify_registry_listing(
        expected,
        RegistryCheckOptions(
            attempts=1,
            transport=httpx.MockTransport(handler),
        ),
    )
    assert pages == [1, 2]
    assert result.catalog_latest_version == expected.version


@pytest.mark.parametrize(
    "page_data",
    [
        {},
        {"page": 1, "totalPages": 0},
        {"page": 2, "totalPages": 2},
        {"page": 1, "totalPages": 101},
        {"page": True, "totalPages": True},
    ],
)
def test_invalid_pagination_fails_closed(page_data: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/nodes/"):
            return httpx.Response(200, json=_node(EXPECTED_DESCRIPTION))
        return httpx.Response(200, json={**page_data, "versions": []})

    with pytest.raises(RegistryListingError, match="pagination"):
        synchronize_and_verify_registry_listing(
            EXPECTED,
            RegistryCheckOptions(
                attempts=1,
                transport=httpx.MockTransport(handler),
            ),
        )


@pytest.mark.parametrize("changed_pages", [False, True])
def test_unstable_or_repeated_version_pages_fail_closed(changed_pages: bool) -> None:
    second_page = 2

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/nodes/"):
            return httpx.Response(200, json=_node(EXPECTED_DESCRIPTION))
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json={
                "page": page,
                "totalPages": 3 if changed_pages and page == second_page else second_page,
                "versions": [{"version": "2.0.6", "status": ACTIVE_STATUS}],
            },
        )

    with pytest.raises(RegistryListingError, match=r"changed|duplicate"):
        synchronize_and_verify_registry_listing(
            EXPECTED,
            RegistryCheckOptions(attempts=1, transport=httpx.MockTransport(handler)),
        )
