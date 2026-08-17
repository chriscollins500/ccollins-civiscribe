from __future__ import annotations

import json
import socket
import ssl
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from civiscribe.domain import (
    HashRecord,
    IdentitySource,
    ResourceIdentity,
    ResourceKind,
    ResourceRecord,
    ResourceRole,
    ResourceStatus,
)
from civiscribe.identity import civitai_client as client_module
from civiscribe.identity.civitai_client import (
    USER_AGENT,
    CivitaiClient,
    CivitaiLookupConfig,
    CivitaiRateLimitGate,
    create_tls_contexts,
    no_private_request_data,
    parse_retry_after,
)
from civiscribe.identity.types import LookupStatus
from tests.projection_support import MODEL_ID, MODEL_VERSION_ID, model_resource

MODEL_AIR = f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}+2402203.safetensor"
SHA256 = "a" * 64
AUTO_V2 = "a" * 10
AUTO_V3 = "b" * 12
VAE_MODEL_ID = 30
VAE_VERSION_ID = 40
VAE_AIR = f"urn:air:qwen:vae:civitai:{VAE_MODEL_ID}@{VAE_VERSION_ID}"
TEXT_ENCODER_MODEL_ID = 50
TEXT_ENCODER_VERSION_ID = 60
TEXT_ENCODER_AIR = (
    f"urn:air:lens:text_encoders:civitai:{TEXT_ENCODER_MODEL_ID}@{TEXT_ENCODER_VERSION_ID}"
)
UNKNOWN_TEXT_ENCODER_AIR = (
    f"urn:air:zimageturbo:unknown:civitai:{TEXT_ENCODER_MODEL_ID}@{TEXT_ENCODER_VERSION_ID}"
)
RETRY_AFTER_DELTA_SECONDS = 45
RETRY_AFTER_DATE_SECONDS = 90
MAX_TEST_COOLDOWN_SECONDS = 30
DEFAULT_TEST_COOLDOWN_SECONDS = 17
SHORT_TEST_COOLDOWN_SECONDS = 5
OVERSIZED_RETRY_AFTER_CHARS = 129
STYLE_MODEL_AIR = f"urn:air:other:unknown:civitai:{MODEL_ID}@{MODEL_VERSION_ID}"
TEST_TLS_CONTEXTS = (("test", ssl.create_default_context()),)
EXPECTED_DUPLICATE_CANDIDATES = 2


def _resource(*, hashes: HashRecord | None = None) -> ResourceRecord:
    return replace(
        model_resource(),
        hashes=hashes or HashRecord(sha256=SHA256, auto_v2=AUTO_V2),
        identity=None,
        status=ResourceStatus.UNRESOLVED,
    )


def _vae_resource(*, hashes: HashRecord | None = None) -> ResourceRecord:
    return replace(
        _resource(hashes=hashes),
        role=ResourceRole.VAE,
        kind=ResourceKind.VAE,
        filename="qwen_image_vae.safetensors",
        selected_value="qwen_image_vae.safetensors",
    )


def _text_encoder_resource(*, hashes: HashRecord | None = None) -> ResourceRecord:
    return replace(
        _resource(hashes=hashes),
        role=ResourceRole.TEXT_ENCODER,
        kind=ResourceKind.CLIP,
        filename="text_encoder.gguf",
        selected_value="text_encoder.gguf",
    )


def _ipadapter_resource(*, hashes: HashRecord | None = None) -> ResourceRecord:
    return replace(
        _resource(hashes=hashes),
        role=ResourceRole.IPADAPTER,
        kind=ResourceKind.IPADAPTER,
        filename="ip_adapter.safetensors",
        selected_value="ip_adapter.safetensors",
    )


def _hypernetwork_resource(*, hashes: HashRecord | None = None) -> ResourceRecord:
    return replace(
        _resource(hashes=hashes),
        role=ResourceRole.HYPERNETWORK,
        kind=ResourceKind.HYPERNETWORK,
        filename="detail.pt",
        selected_value="detail.pt",
    )


def _style_model_resource(*, hashes: HashRecord | None = None) -> ResourceRecord:
    return replace(
        _resource(hashes=hashes),
        role=ResourceRole.STYLE_MODEL,
        kind=ResourceKind.STYLE_MODEL,
        filename="style_model.safetensors",
        selected_value="style_model.safetensors",
    )


def _payload(  # noqa: PLR0913
    *,
    air: str | None = MODEL_AIR,
    model_id: int = MODEL_ID,
    version_id: int = MODEL_VERSION_ID,
    queried_hash: str = SHA256,
    model_type: str = "Checkpoint",
    file_type: str | None = "Model",
    file_primary: bool | None = True,
    file_format: str = "safetensor",
    base_model: str | None = None,
) -> dict[str, object]:
    file: dict[str, object] = {
        "id": 2402203,
        "hashes": {"SHA256": queried_hash, "AutoV2": queried_hash[:10]},
        "metadata": {"format": file_format},
    }
    if file_type is not None:
        file["type"] = file_type
    if file_primary is not None:
        file["primary"] = file_primary
    result: dict[str, object] = {
        "id": version_id,
        "modelId": model_id,
        "name": "NEO",
        "model": {"id": model_id, "name": "SWIFT", "type": model_type},
        "files": [file],
    }
    if air is not None:
        result["air"] = air
    if base_model is not None:
        result["baseModel"] = base_model
    return result


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    enabled: bool = True,
) -> CivitaiClient:
    return CivitaiClient(
        CivitaiLookupConfig(enabled=enabled),
        transport=httpx.MockTransport(handler),
        tls_contexts=TEST_TLS_CONTEXTS,
    )


def test_lookup_is_disabled_by_default_and_no_hash_is_skipped() -> None:
    assert CivitaiLookupConfig().enabled is False
    assert (
        CivitaiClient(tls_contexts=TEST_TLS_CONTEXTS).lookup(_resource()).status
        is LookupStatus.SKIPPED_DISABLED
    )
    assert (
        _client(lambda _request: pytest.fail("network called"))
        .lookup(_resource(hashes=HashRecord()))
        .status
        is LookupStatus.SKIPPED_NO_HASH
    )


@pytest.mark.parametrize(
    ("timeout_seconds", "max_response_bytes"),
    [
        (0.0, 1),
        (4.0, 0),
    ],
)
def test_lookup_config_rejects_invalid_limits(
    timeout_seconds: float,
    max_response_bytes: int,
) -> None:
    with pytest.raises(ValueError, match="civitai_lookup_limits_invalid"):
        CivitaiLookupConfig(
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )

    with pytest.raises(ValueError, match="civitai_lookup_limits_invalid"):
        CivitaiLookupConfig(max_role_response_bytes=0)


@pytest.mark.parametrize(
    ("default_seconds", "maximum_seconds"),
    [(0, 30), (10, 0), (31, 30)],
)
def test_lookup_config_rejects_invalid_rate_limit_bounds(
    default_seconds: int,
    maximum_seconds: int,
) -> None:
    with pytest.raises(ValueError, match="civitai_lookup_limits_invalid"):
        CivitaiLookupConfig(
            default_rate_limit_cooldown_seconds=default_seconds,
            max_rate_limit_cooldown_seconds=maximum_seconds,
        )


def test_api_base_validation_checks_each_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = {
        "scheme": "https",
        "hostname": "civitai.com",
        "username": None,
        "password": None,
        "port": None,
        "query": "",
        "fragment": "",
    }
    invalid_values = {
        "scheme": "http",
        "hostname": "example.com",
        "username": "user",
        "password": "secret",
        "port": 444,
        "query": "debug=1",
        "fragment": "private",
    }

    for field, value in invalid_values.items():
        parsed = SimpleNamespace(**(valid | {field: value}))
        monkeypatch.setattr(client_module, "urlparse", lambda _value, parsed=parsed: parsed)
        with pytest.raises(ValueError, match="civitai_api_base_invalid"):
            client_module._validate_api_base("ignored")


def test_hash_lookup_uses_api_air_and_sends_only_public_get_data() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload(base_model="Flux.2 D"))

    result = _client(handler).lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == MODEL_AIR
    assert result.identity.model_name == "SWIFT"
    assert result.identity.model_version_name == "NEO"
    assert result.identity.base_model == "Flux.2 D"
    assert result.identity.file_id == "2402203"
    assert result.identity.format == "safetensor"
    assert result.hashes.auto_v2 == AUTO_V2
    assert result.attempted_hashes == ("SHA256",)
    assert len(requests) == 1
    assert requests[0].headers["User-Agent"] == USER_AGENT
    assert no_private_request_data(requests[0])


def test_current_text_encoder_api_type_and_air_resolve_directly() -> None:
    payload = _payload(
        air=TEXT_ENCODER_AIR,
        model_id=TEXT_ENCODER_MODEL_ID,
        version_id=TEXT_ENCODER_VERSION_ID,
        model_type="TextEncoder",
    )

    result = _client(lambda _request: httpx.Response(200, json=payload)).lookup(
        _text_encoder_resource(hashes=HashRecord(sha256=SHA256))
    )

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == TEXT_ENCODER_AIR
    assert result.identity.resource_type == "text_encoders"


@pytest.mark.parametrize(
    ("air", "model_type"),
    [
        (
            (
                "urn:air:zimageturbo:checkpoint:"
                f"civitai:{TEXT_ENCODER_MODEL_ID}@{TEXT_ENCODER_VERSION_ID}"
            ),
            "Checkpoint",
        ),
        (UNKNOWN_TEXT_ENCODER_AIR, "Other"),
    ],
)
@pytest.mark.parametrize(
    ("hash_algorithm", "expected_methods", "expects_role_warning"),
    [
        ("BLAKE3", ["GET"], False),
        ("SHA256", ["GET", "POST"], True),
    ],
)
def test_strong_hash_does_not_promote_parent_model_to_text_encoder(
    air: str,
    model_type: str,
    hash_algorithm: str,
    expected_methods: list[str],
    expects_role_warning: bool,
) -> None:
    requests: list[httpx.Request] = []
    payload = _payload(
        air=air,
        model_id=TEXT_ENCODER_MODEL_ID,
        version_id=TEXT_ENCODER_VERSION_ID,
        model_type=model_type,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[payload] if request.method == "POST" else payload)

    hashes = HashRecord(blake3=SHA256) if hash_algorithm == "BLAKE3" else HashRecord(sha256=SHA256)
    result = _client(handler).lookup(_text_encoder_resource(hashes=hashes))

    assert result.status is LookupStatus.FAILED
    assert result.identity is None
    assert "civitai_response_type_mismatch" in {issue.code for issue in result.issues}
    assert (
        "civitai_response_role_match_missing" in {issue.code for issue in result.issues}
    ) is expects_role_warning
    assert [request.method for request in requests] == expected_methods


def test_sha256_bulk_disambiguation_accepts_exact_nonprimary_file_role() -> None:
    requests: list[httpx.Request] = []
    parent_air = (
        f"urn:air:anima:checkpoint:civitai:{TEXT_ENCODER_MODEL_ID}@{TEXT_ENCODER_VERSION_ID}"
    )
    direct = _payload(
        air=parent_air,
        model_id=TEXT_ENCODER_MODEL_ID,
        version_id=TEXT_ENCODER_VERSION_ID,
        model_type="Checkpoint",
    )
    bundled_text_encoder = _payload(
        air=parent_air,
        model_id=TEXT_ENCODER_MODEL_ID,
        version_id=TEXT_ENCODER_VERSION_ID,
        model_type="Checkpoint",
        file_type="Text Encoder",
        file_primary=False,
        file_format="SafeTensor",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[bundled_text_encoder] if request.method == "POST" else direct,
        )

    result = _client(handler).lookup(_text_encoder_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.raw_air == parent_air
    assert result.identity.canonical_air == f"{parent_air}+2402203.safetensor"
    assert result.identity.resource_type == "checkpoint"
    assert result.identity.file_type == "Text Encoder"
    assert result.identity.file_primary is False
    assert [request.method for request in requests] == ["GET", "POST"]
    assert json.loads(requests[1].content) == [SHA256]


def test_file_role_disambiguation_rejects_nonsemantic_other_file() -> None:
    checkpoint = _payload()
    unrelated = _payload(
        file_type="Other",
        file_primary=False,
    )

    result = _client(
        lambda request: httpx.Response(
            200,
            json=[unrelated] if request.method == "POST" else checkpoint,
        )
    ).lookup(_text_encoder_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.FAILED
    assert result.identity is None
    assert result.diagnostic_reason == "no_role_compatible_shared_hash_candidate"


def test_ambiguous_text_encoder_category_requires_a_strong_hash() -> None:
    payload = _payload(
        air=(
            "urn:air:zimageturbo:checkpoint:"
            f"civitai:{TEXT_ENCODER_MODEL_ID}@{TEXT_ENCODER_VERSION_ID}"
        ),
        model_id=TEXT_ENCODER_MODEL_ID,
        version_id=TEXT_ENCODER_VERSION_ID,
        queried_hash=AUTO_V2,
        model_type="Checkpoint",
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    result = _client(handler).lookup(_text_encoder_resource(hashes=HashRecord(auto_v2=AUTO_V2)))

    assert result.status is LookupStatus.FAILED
    assert [issue.code for issue in result.issues] == [
        "civitai_response_type_mismatch",
        "civitai_lookup_failed",
    ]
    assert [request.method for request in requests] == ["GET"]


def test_incompatible_text_encoder_parent_does_not_trigger_details_completion() -> None:
    requests: list[httpx.Request] = []
    partial = _payload(
        air=None,
        model_id=TEXT_ENCODER_MODEL_ID,
        version_id=TEXT_ENCODER_VERSION_ID,
        model_type="Other",
    )
    detailed = _payload(
        air=UNKNOWN_TEXT_ENCODER_AIR,
        model_id=TEXT_ENCODER_MODEL_ID,
        version_id=TEXT_ENCODER_VERSION_ID,
        model_type="Other",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=[partial])
        if request.url.path.endswith(f"/{TEXT_ENCODER_VERSION_ID}"):
            return httpx.Response(200, json=detailed)
        return httpx.Response(200, json=partial)

    result = _client(handler).lookup(_text_encoder_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.FAILED
    assert result.identity is None
    assert [request.method for request in requests] == ["GET", "POST"]


def test_ipadapter_accepts_civitai_controlnet_classification() -> None:
    air = f"urn:air:sdxl:controlnet:civitai:{MODEL_ID}@{MODEL_VERSION_ID}"
    payload = _payload(air=air, model_type="Controlnet")

    result = _client(lambda _request: httpx.Response(200, json=payload)).lookup(
        _ipadapter_resource(hashes=HashRecord(sha256=SHA256))
    )

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == air


def test_hypernetwork_accepts_civitai_hypernetwork_classification() -> None:
    air = f"urn:air:sd1:hypernet:civitai:{MODEL_ID}@{MODEL_VERSION_ID}"
    payload = _payload(air=air, model_type="Hypernetwork")

    result = _client(lambda _request: httpx.Response(200, json=payload)).lookup(
        _hypernetwork_resource(hashes=HashRecord(sha256=SHA256))
    )

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == air


def test_style_model_accepts_civitai_other_classification() -> None:
    payload = _payload(air=STYLE_MODEL_AIR, model_type="Other")

    result = _client(lambda _request: httpx.Response(200, json=payload)).lookup(
        _style_model_resource(hashes=HashRecord(sha256=SHA256))
    )

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == STYLE_MODEL_AIR


def test_sha256_type_collision_uses_role_compatible_official_air() -> None:
    requests: list[httpx.Request] = []
    checkpoint = _payload()
    vae = _payload(
        air=VAE_AIR,
        model_id=VAE_MODEL_ID,
        version_id=VAE_VERSION_ID,
        model_type="VAE",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=[checkpoint, vae])
        return httpx.Response(200, json=checkpoint)

    result = _client(handler).lookup(_vae_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == VAE_AIR
    assert result.identity.resource_type == "vae"
    assert result.identity.model_version_id == VAE_VERSION_ID
    assert [request.method for request in requests] == ["GET", "POST"]
    assert all(no_private_request_data(request) for request in requests)
    assert [issue.code for issue in result.issues] == ["civitai_duplicate_hash_role_disambiguated"]


def test_role_aware_lookup_merges_duplicate_records_for_same_identity() -> None:
    checkpoint = _payload()
    vae = _payload(
        air=VAE_AIR,
        model_id=VAE_MODEL_ID,
        version_id=VAE_VERSION_ID,
        model_type="VAE",
    )

    result = _client(
        lambda request: httpx.Response(
            200,
            json=[vae, vae] if request.method == "POST" else checkpoint,
        )
    ).lookup(_vae_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == VAE_AIR
    assert result.diagnostic_reason == "multiple_compatible_candidates"
    assert result.candidate_count == EXPECTED_DUPLICATE_CANDIDATES
    assert result.compatible_candidate_count == EXPECTED_DUPLICATE_CANDIDATES


def test_role_aware_lookup_transport_failure_keeps_original_mismatch() -> None:
    checkpoint = _payload()

    result = _client(
        lambda request: httpx.Response(
            404 if request.method == "POST" else 200,
            json={"detail": "not found"} if request.method == "POST" else checkpoint,
        )
    ).lookup(_vae_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.FAILED
    assert result.failure_reason == "no_matching_result"
    assert [issue.code for issue in result.issues] == [
        "civitai_response_type_mismatch",
        "civitai_lookup_failed",
    ]


def test_role_aware_lookup_rejects_missing_or_conflicting_candidates() -> None:
    checkpoint = _payload()
    missing = _client(
        lambda request: httpx.Response(
            200,
            json=[checkpoint] if request.method == "POST" else checkpoint,
        )
    ).lookup(_vae_resource(hashes=HashRecord(sha256=SHA256)))
    assert missing.status is LookupStatus.FAILED
    assert missing.diagnostic_reason == "no_role_compatible_shared_hash_candidate"
    assert missing.candidate_count == 1
    assert missing.compatible_candidate_count == 0
    assert [issue.code for issue in missing.issues] == [
        "civitai_response_type_mismatch",
        "civitai_response_role_match_missing",
        "civitai_lookup_failed",
    ]

    first = _payload(
        air=VAE_AIR,
        model_id=VAE_MODEL_ID,
        version_id=VAE_VERSION_ID,
        model_type="VAE",
    )
    second = _payload(
        air="urn:air:qwen:vae:civitai:31@41",
        model_id=31,
        version_id=41,
        model_type="VAE",
    )
    conflict = _client(
        lambda request: httpx.Response(
            200,
            json=[first, second] if request.method == "POST" else checkpoint,
        )
    ).lookup(_vae_resource(hashes=HashRecord(sha256=SHA256)))
    assert conflict.status is LookupStatus.CONFLICT
    assert conflict.failure_reason == "identity_conflict"
    assert conflict.diagnostic_reason == "multiple_compatible_candidates_conflict"
    assert conflict.candidate_count == EXPECTED_DUPLICATE_CANDIDATES
    assert conflict.compatible_candidate_count == EXPECTED_DUPLICATE_CANDIDATES
    assert conflict.attempted_hashes == ("SHA256",)


def test_role_aware_lookup_bounds_and_validates_batch_response() -> None:
    checkpoint = _payload()
    invalid = _client(
        lambda request: httpx.Response(
            200,
            json={} if request.method == "POST" else checkpoint,
        )
    ).lookup(_vae_resource(hashes=HashRecord(sha256=SHA256)))
    assert "civitai_response_schema_invalid" in {issue.code for issue in invalid.issues}

    oversized_candidates = [checkpoint] * (client_module.MAX_ROLE_MATCH_CANDIDATES + 1)
    bounded = _client(
        lambda request: httpx.Response(
            200,
            json=oversized_candidates if request.method == "POST" else checkpoint,
        )
    ).lookup(_vae_resource(hashes=HashRecord(sha256=SHA256)))
    assert "civitai_response_candidate_limit_exceeded" in {issue.code for issue in bounded.issues}


def test_private_request_validator_rejects_unapproved_post_data() -> None:
    valid = httpx.Request(
        "POST",
        "https://civitai.com/api/v1/model-versions/by-hash",
        json=[SHA256],
    )
    assert no_private_request_data(valid)
    assert not no_private_request_data(
        httpx.Request(
            "POST",
            "https://civitai.com/api/v1/model-versions/by-hash",
            json=["prompt text"],
        )
    )
    assert not no_private_request_data(
        httpx.Request(
            "POST",
            "https://civitai.com/api/v1/model-versions/by-hash/ids",
            json=[SHA256],
        )
    )
    assert not no_private_request_data(
        httpx.Request(
            "POST",
            "https://civitai.com/api/v1/model-versions/by-hash",
            content=b"{",
        )
    )


def test_api_air_without_file_details_is_enriched_from_matching_file() -> None:
    air_without_file = f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}"

    result = _client(
        lambda _request: httpx.Response(
            200,
            json=_payload(air=air_without_file),
        )
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == air_without_file
    assert result.identity.file_id == "2402203"
    assert result.identity.format == "safetensor"
    assert result.identity.file_type == "Model"
    assert result.identity.file_primary is True


def test_nonprimary_file_match_pins_canonical_air_to_exact_file() -> None:
    air_without_file = f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}"

    result = _client(
        lambda _request: httpx.Response(
            200,
            json=_payload(
                air=air_without_file,
                file_primary=False,
                file_format="SafeTensor",
            ),
        )
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.raw_air == air_without_file
    assert result.identity.canonical_air == f"{air_without_file}+2402203.safetensor"
    assert result.identity.file_id == "2402203"
    assert result.identity.format == "safetensor"
    assert result.identity.file_primary is False


def test_api_air_file_id_conflict_is_rejected() -> None:
    conflicting_air = (
        f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}+9999999.safetensor"
    )

    result = _client(
        lambda _request: httpx.Response(
            200,
            json=_payload(air=conflicting_air),
        )
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.FAILED
    assert result.identity is None
    assert "civitai_response_air_file_conflict" in {issue.code for issue in result.issues}


def test_hash_lookup_fetches_official_air_when_first_response_lacks_it() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        payload = _payload(air=None) if "by-hash" in request.url.path else _payload()
        return httpx.Response(200, json=payload)

    result = _client(handler).lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == MODEL_AIR
    assert paths == [
        f"/api/v1/model-versions/by-hash/{SHA256}",
        f"/api/v1/model-versions/{MODEL_VERSION_ID}",
    ]


def test_trailing_api_slash_is_normalized() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_payload())

    client = CivitaiClient(
        CivitaiLookupConfig(
            enabled=True,
            api_base_url="https://civitai.com/api/v1/",
        ),
        transport=httpx.MockTransport(handler),
        tls_contexts=TEST_TLS_CONTEXTS,
    )
    result = client.lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert paths == [f"/api/v1/model-versions/by-hash/{SHA256}"]


@pytest.mark.parametrize(
    ("status_code", "reason", "retryable"),
    [
        (404, "no_matching_result", False),
        (429, "rate_limited", True),
        (500, "server_error", True),
        (400, "http_error", False),
    ],
)
def test_http_failures_are_sanitized_and_deduplicated(
    status_code: int,
    reason: str,
    retryable: bool,
) -> None:
    result = _client(
        lambda _request: httpx.Response(status_code, json={"detail": "private upstream text"})
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.FAILED
    assert result.failure_reason == reason
    assert result.http_status == status_code
    assert result.retryable is retryable
    assert [issue.code for issue in result.issues] == ["civitai_lookup_failed"]


def test_retry_after_parses_delay_and_http_date_without_retaining_header_text() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)

    assert parse_retry_after("45", now=lambda: now) == RETRY_AFTER_DELTA_SECONDS
    assert (
        parse_retry_after(
            "Tue, 28 Jul 2026 12:01:30 GMT",
            now=lambda: now,
        )
        == RETRY_AFTER_DATE_SECONDS
    )
    assert parse_retry_after("private upstream text", now=lambda: now) is None


def test_retry_after_rejects_unsafe_values_and_normalizes_naive_dates() -> None:
    naive_now = datetime(2026, 7, 28, 12, 0)

    assert client_module._utc_now().tzinfo is UTC
    assert parse_retry_after("\x00private", now=lambda: naive_now) is None
    assert parse_retry_after("1" * OVERSIZED_RETRY_AFTER_CHARS, now=lambda: naive_now) is None
    assert (
        parse_retry_after(
            "Tue, 28 Jul 2026 12:01:30",
            now=lambda: naive_now,
        )
        == RETRY_AFTER_DATE_SECONDS
    )


def test_rate_limit_gate_ignores_nonpositive_delay() -> None:
    gate = CivitaiRateLimitGate(lambda: 100.0)

    gate.defer(0)

    assert gate.remaining_seconds() == 0


def test_rate_limit_sets_bounded_cooldown_and_suppresses_followup_request() -> None:
    monotonic = [100.0]
    gate = CivitaiRateLimitGate(lambda: monotonic[0])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "900"})

    client = CivitaiClient(
        CivitaiLookupConfig(
            enabled=True,
            default_rate_limit_cooldown_seconds=10,
            max_rate_limit_cooldown_seconds=MAX_TEST_COOLDOWN_SECONDS,
        ),
        transport=httpx.MockTransport(handler),
        tls_contexts=TEST_TLS_CONTEXTS,
        rate_limit_gate=gate,
    )
    first = client.lookup(_resource(hashes=HashRecord(sha256=SHA256)))
    second = client.lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert first.failure_reason == "rate_limited"
    assert first.retry_after_seconds == MAX_TEST_COOLDOWN_SECONDS
    assert second.failure_reason == "rate_limit_cooldown"
    assert second.retry_after_seconds == MAX_TEST_COOLDOWN_SECONDS
    assert second.attempted_hashes == ()
    assert [issue.code for issue in second.issues] == ["civitai_lookup_failed"]
    assert len(requests) == 1

    monotonic[0] += 31
    assert gate.remaining_seconds() == 0


def test_rate_limit_without_header_uses_safe_default_cooldown() -> None:
    result = CivitaiClient(
        CivitaiLookupConfig(
            enabled=True,
            default_rate_limit_cooldown_seconds=DEFAULT_TEST_COOLDOWN_SECONDS,
            max_rate_limit_cooldown_seconds=MAX_TEST_COOLDOWN_SECONDS,
        ),
        transport=httpx.MockTransport(lambda _request: httpx.Response(429)),
        tls_contexts=TEST_TLS_CONTEXTS,
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.failure_reason == "rate_limited"
    assert result.retry_after_seconds == DEFAULT_TEST_COOLDOWN_SECONDS


def test_response_without_matching_hash_is_rejected() -> None:
    result = _client(
        lambda _request: httpx.Response(200, json=_payload(queried_hash="b" * 64))
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.FAILED
    assert [issue.code for issue in result.issues] == [
        "civitai_response_hash_mismatch",
        "civitai_lookup_failed",
    ]


def test_invalid_response_shapes_are_rejected() -> None:
    non_mapping = _client(
        lambda _request: httpx.Response(200, json=["not", "a", "mapping"])
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))
    assert [issue.code for issue in non_mapping.issues] == [
        "civitai_response_schema_invalid",
        "civitai_lookup_failed",
    ]

    no_files = _client(lambda _request: httpx.Response(200, json={"id": MODEL_VERSION_ID})).lookup(
        _resource(hashes=HashRecord(sha256=SHA256))
    )
    assert [issue.code for issue in no_files.issues] == [
        "civitai_response_hash_mismatch",
        "civitai_lookup_failed",
    ]

    missing_version_payload = _payload(air=None)
    missing_version_payload.pop("id")
    missing_version_payload["modelVersionId"] = True
    missing_version = _client(
        lambda _request: httpx.Response(200, json=missing_version_payload)
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))
    assert [issue.code for issue in missing_version.issues] == [
        "civitai_response_version_missing",
        "civitai_lookup_failed",
    ]

    malformed_air = _client(
        lambda _request: httpx.Response(
            200,
            json=_payload(air="not-an-air-identifier"),
        )
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))
    assert malformed_air.status is LookupStatus.FAILED
    assert malformed_air.issues[-1].code == "civitai_lookup_failed"


def test_payload_fallback_fields_and_file_candidates_are_supported() -> None:
    payload = _payload(air=None)
    payload.pop("modelId")
    payload["modelVersionId"] = payload.pop("id")
    payload["modelType"] = "Checkpoint"
    files = payload["files"]
    assert isinstance(files, list)
    files[:0] = [None, {"hashes": None}]

    result = _client(lambda _request: httpx.Response(200, json=payload)).lookup(
        _resource(hashes=HashRecord(auto_v2=AUTO_V2))
    )

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.model_id == MODEL_ID
    assert result.identity.model_version_id == MODEL_VERSION_ID


def test_partial_non_air_payload_does_not_invent_model_id_or_file_data() -> None:
    payload = _payload(air=None)
    payload.pop("modelId")
    model = payload["model"]
    assert isinstance(model, dict)
    model.pop("id")

    result = _client(lambda _request: httpx.Response(200, json=payload)).complete_version(
        _resource(), MODEL_VERSION_ID
    )

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.model_id is None
    assert result.identity.identity_id is None
    assert result.identity.file_id is None
    assert result.identity.format is None


def test_missing_model_type_is_rejected_without_crashing() -> None:
    payload = _payload(air=None)
    model = payload["model"]
    assert isinstance(model, dict)
    model.pop("type")

    result = _client(lambda _request: httpx.Response(200, json=payload)).lookup(
        _resource(hashes=HashRecord(auto_v2=AUTO_V2))
    )

    assert [issue.code for issue in result.issues] == [
        "civitai_response_type_mismatch",
        "civitai_lookup_failed",
    ]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "x" * 513,
        "visible\u0000hidden",
    ],
)
def test_text_sanitizer_rejects_empty_oversized_or_control_text(value: str) -> None:
    assert client_module._text(value) is None


def test_malformed_oversized_and_redirect_responses_are_non_resolving() -> None:
    malformed = _client(
        lambda _request: httpx.Response(200, content=b"{"),
    ).lookup(_resource(hashes=HashRecord(auto_v2=AUTO_V2)))
    assert malformed.failure_reason == "malformed_json"

    oversized = CivitaiClient(
        CivitaiLookupConfig(enabled=True, max_response_bytes=2),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b'{"value":1}')),
        tls_contexts=TEST_TLS_CONTEXTS,
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))
    assert oversized.failure_reason == "response_too_large"

    redirect = _client(
        lambda _request: httpx.Response(302, headers={"Location": "https://example.com/"})
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))
    assert redirect.failure_reason == "redirect_rejected"


def test_air_id_and_type_conflicts_are_rejected_and_stronger_hash_wins() -> None:
    model_conflict = _client(
        lambda _request: httpx.Response(
            200,
            json=_payload(
                air=(f"urn:air:flux2:checkpoint:civitai:{MODEL_ID + 1}@{MODEL_VERSION_ID}")
            ),
        )
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))
    assert [issue.code for issue in model_conflict.issues] == [
        "civitai_response_air_id_conflict",
        "civitai_lookup_failed",
    ]

    version_conflict = _client(
        lambda _request: httpx.Response(
            200,
            json=_payload(
                air=f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID + 1}"
            ),
        )
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))
    assert [issue.code for issue in version_conflict.issues] == [
        "civitai_response_air_id_conflict",
        "civitai_lookup_failed",
    ]

    type_conflict = _client(
        lambda _request: httpx.Response(
            200,
            json=_payload(air=f"urn:air:flux2:lora:civitai:{MODEL_ID}@{MODEL_VERSION_ID}"),
        )
    ).lookup(_resource(hashes=HashRecord(auto_v2=AUTO_V2)))
    assert [issue.code for issue in type_conflict.issues] == [
        "civitai_response_type_mismatch",
        "civitai_lookup_failed",
    ]

    def conflicting_handler(request: httpx.Request) -> httpx.Response:
        queried = request.url.path.rsplit("/", maxsplit=1)[-1]
        if queried == SHA256:
            return httpx.Response(200, json=_payload(queried_hash=SHA256))
        return httpx.Response(
            200,
            json=_payload(
                air="urn:air:flux2:checkpoint:civitai:90@91",
                model_id=90,
                version_id=91,
                queried_hash=AUTO_V2,
            ),
        )

    result = _client(conflicting_handler).lookup(_resource())
    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == MODEL_AIR
    assert result.attempted_hashes == ("SHA256",)


def test_hash_fallback_prefers_autov3_before_autov2() -> None:
    requests: list[httpx.Request] = []
    blake3 = "c" * 64
    payload = _payload()
    files = payload["files"]
    assert isinstance(files, list)
    file_record = files[0]
    assert isinstance(file_record, dict)
    file_record["hashes"] = {"AutoV3": AUTO_V3}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        queried = request.url.path.rsplit("/", maxsplit=1)[-1]
        if queried == AUTO_V3:
            return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"detail": "not found"})

    result = _client(handler).lookup(
        _resource(
            hashes=HashRecord(
                sha256=SHA256,
                blake3=blake3,
                auto_v3=AUTO_V3,
                auto_v2=AUTO_V2,
                crc32="D" * 8,
                auto_v1="e" * 8,
            )
        )
    )

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.attempted_hashes == ("SHA256", "BLAKE3", "AutoV3")
    assert [request.url.path.rsplit("/", maxsplit=1)[-1] for request in requests] == [
        SHA256,
        blake3,
        AUTO_V3,
    ]


def test_no_match_exhausts_hashes_in_authority_order() -> None:
    result = _client(lambda _request: httpx.Response(404, json={"detail": "not found"})).lookup(
        _resource(
            hashes=HashRecord(
                sha256=SHA256,
                blake3="c" * 64,
                auto_v3=AUTO_V3,
                auto_v2=AUTO_V2,
                crc32="D" * 8,
                auto_v1="e" * 8,
            )
        )
    )

    assert result.status is LookupStatus.FAILED
    assert result.attempted_hashes == (
        "SHA256",
        "BLAKE3",
        "AutoV3",
        "AutoV2",
        "CRC32",
        "AutoV1",
    )


def test_hash_fallback_stops_after_transport_failure() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ConnectError("offline", request=request)

    result = _client(handler).lookup(
        _resource(
            hashes=HashRecord(
                sha256=SHA256,
                auto_v3=AUTO_V3,
                auto_v2=AUTO_V2,
            )
        )
    )

    assert result.status is LookupStatus.FAILED
    assert result.failure_reason == "network_error"
    assert result.diagnostic_reason == "network_error"
    assert result.attempted_hashes == ("SHA256",)
    assert len(requests) == 1


def test_preferred_diagnostics_uses_sanitized_fallback_for_empty_attempts() -> None:
    diagnostics = client_module._preferred_diagnostics(
        (),
        fallback_reason="network_error",
    )

    assert diagnostics.reason == "network_error"


def test_hash_404_has_distinct_sanitized_diagnostics() -> None:
    result = _client(lambda _request: httpx.Response(404, json={"detail": "not found"})).lookup(
        _resource(hashes=HashRecord(sha256=SHA256))
    )

    assert result.status is LookupStatus.FAILED
    assert result.failure_reason == "no_matching_result"
    assert result.diagnostic_reason == "no_hash_match"
    assert result.http_status == httpx.codes.NOT_FOUND
    assert result.retryable is False
    assert result.tls_source == "test"
    assert result.candidate_count == 0
    assert result.compatible_candidate_count == 0


@pytest.mark.parametrize(
    ("exception_factory", "reason", "retryable"),
    [
        (
            lambda request: httpx.ProxyError("proxy unavailable", request=request),
            "proxy_error",
            True,
        ),
        (
            lambda request: _connect_error_with_cause(
                request,
                socket.gaierror("name resolution failed"),
            ),
            "dns_error",
            True,
        ),
        (
            lambda request: httpx.ConnectError("connection failed", request=request),
            "network_error",
            True,
        ),
        (
            lambda request: httpx.RemoteProtocolError(
                "protocol failed",
                request=request,
            ),
            "network_error",
            True,
        ),
    ],
)
def test_transport_errors_are_sanitized(
    exception_factory: Callable[[httpx.Request], httpx.HTTPError],
    reason: str,
    retryable: bool,
) -> None:
    result = _client(lambda request: (_ for _ in ()).throw(exception_factory(request))).lookup(
        _resource(hashes=HashRecord(sha256=SHA256))
    )

    assert result.failure_reason == reason
    assert result.retryable is retryable


def _connect_error_with_cause(
    request: httpx.Request,
    cause: BaseException,
) -> httpx.ConnectError:
    error = httpx.ConnectError("connection failed", request=request)
    error.__cause__ = cause
    return error


def test_timeout_and_certificate_errors_are_sanitized() -> None:
    timeout = _client(
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("late", request=request))
    ).lookup(_resource(hashes=HashRecord(sha256=SHA256)))
    assert timeout.failure_reason == "timeout"
    assert timeout.retryable is True

    request = httpx.Request("GET", f"https://civitai.com/api/v1/model-versions/{MODEL_VERSION_ID}")
    certificate = httpx.ConnectError(
        "tls",
        request=request,
    )
    certificate.__cause__ = ssl.SSLCertVerificationError(
        1,
        "certificate verify failed: private host omitted",
    )
    failed = _client(lambda _request: (_ for _ in ()).throw(certificate)).lookup(
        _resource(hashes=HashRecord(sha256=SHA256))
    )
    assert failed.failure_reason == "certificate_verify_failed"
    assert failed.retryable is False


def test_certificate_failure_uses_next_verified_context() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            certificate = httpx.ConnectError("tls", request=request)
            certificate.__cause__ = ssl.SSLCertVerificationError(
                1,
                "certificate verify failed",
            )
            raise certificate
        return httpx.Response(200, json=_payload())

    contexts = (
        ("system_default", ssl.create_default_context()),
        ("fallback", ssl.create_default_context()),
    )
    client = CivitaiClient(
        CivitaiLookupConfig(enabled=True),
        transport=httpx.MockTransport(handler),
        tls_contexts=contexts,
    )
    result = client.lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert result.tls_source == "fallback"
    assert calls == len(contexts)


def test_empty_internal_client_group_returns_sanitized_network_failure() -> None:
    group = client_module._ClientGroup(
        config=CivitaiLookupConfig(enabled=True),
        transport=httpx.MockTransport(lambda _request: pytest.fail("empty group made a request")),
        contexts=(),
        rate_limit_gate=CivitaiRateLimitGate(),
        wall_clock=lambda: datetime.now(UTC),
    )

    with group:
        result = group.get(f"https://civitai.com/api/v1/model-versions/{MODEL_VERSION_ID}")

    assert result.failure_reason == "network_error"
    assert result.retryable is True


def test_internal_client_group_honors_existing_cooldown_without_request() -> None:
    gate = CivitaiRateLimitGate(lambda: 100.0)
    gate.defer(SHORT_TEST_COOLDOWN_SECONDS)
    group = client_module._ClientGroup(
        config=CivitaiLookupConfig(enabled=True),
        transport=httpx.MockTransport(lambda _request: pytest.fail("cooldown made a request")),
        contexts=TEST_TLS_CONTEXTS,
        rate_limit_gate=gate,
        wall_clock=lambda: datetime.now(UTC),
    )

    with group:
        result = group.get(f"https://civitai.com/api/v1/model-versions/{MODEL_VERSION_ID}")

    assert result.failure_reason == "rate_limit_cooldown"
    assert result.retry_after_seconds == SHORT_TEST_COOLDOWN_SECONDS


def test_complete_version_respects_enabled_policy() -> None:
    disabled = CivitaiClient(tls_contexts=TEST_TLS_CONTEXTS).complete_version(
        _resource(),
        MODEL_VERSION_ID,
    )
    assert disabled.status is LookupStatus.SKIPPED_DISABLED

    completed = _client(
        lambda _request: httpx.Response(200, json=_payload()),
    ).complete_version(_resource(), MODEL_VERSION_ID)
    assert completed.status is LookupStatus.RESOLVED
    assert completed.identity is not None
    assert completed.identity.canonical_air == MODEL_AIR


def test_complete_version_honors_existing_rate_limit_cooldown() -> None:
    gate = CivitaiRateLimitGate(lambda: 100.0)
    gate.defer(SHORT_TEST_COOLDOWN_SECONDS)
    client = CivitaiClient(
        CivitaiLookupConfig(enabled=True),
        transport=httpx.MockTransport(lambda _request: pytest.fail("cooldown made a request")),
        tls_contexts=TEST_TLS_CONTEXTS,
        rate_limit_gate=gate,
    )

    result = client.complete_version(_resource(), MODEL_VERSION_ID)

    assert result.status is LookupStatus.FAILED
    assert result.failure_reason == "rate_limit_cooldown"
    assert result.retry_after_seconds == SHORT_TEST_COOLDOWN_SECONDS


def test_complete_version_failure_is_sanitized() -> None:
    failed = _client(
        lambda _request: httpx.Response(404, json={"detail": "not found"}),
    ).complete_version(_resource(), MODEL_VERSION_ID)

    assert failed.status is LookupStatus.FAILED
    assert failed.failure_reason == "no_matching_result"
    assert failed.http_status == httpx.codes.NOT_FOUND
    assert [issue.code for issue in failed.issues] == ["civitai_lookup_failed"]


def test_missing_official_air_keeps_valid_hash_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "by-hash" in request.url.path:
            return httpx.Response(200, json=_payload(air=None))
        return httpx.Response(200, json=["invalid", "details"])

    result = _client(handler).lookup(_resource(hashes=HashRecord(sha256=SHA256)))

    assert result.status is LookupStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air is None
    assert [issue.code for issue in result.issues] == ["civitai_response_schema_invalid"]

    partial = client_module._PayloadIdentity(
        ResourceIdentity(
            source=IdentitySource.API,
            resource_type="checkpoint",
            identity_source="civitai",
        ),
        HashRecord(),
    )
    monkeypatch.setattr(
        client_module,
        "_parse_payload_identity",
        lambda *_args, **_kwargs: (partial, ()),
    )
    defensive = _client(lambda _request: httpx.Response(200, json={"ignored": True})).lookup(
        _resource(hashes=HashRecord(sha256=SHA256))
    )

    assert defensive.status is LookupStatus.RESOLVED
    assert defensive.identity is partial.identity


@pytest.mark.parametrize(
    ("right", "expected"),
    [
        (
            ResourceIdentity(
                source=IdentitySource.API,
                resource_type="checkpoint",
                model_id=MODEL_ID,
                model_version_id=MODEL_VERSION_ID,
            ),
            True,
        ),
        (
            ResourceIdentity(
                source=IdentitySource.API,
                resource_type="checkpoint",
                model_id=MODEL_ID + 1,
                model_version_id=MODEL_VERSION_ID,
            ),
            False,
        ),
        (
            ResourceIdentity(
                source=IdentitySource.API,
                resource_type="checkpoint",
                model_id=MODEL_ID,
                model_version_id=MODEL_VERSION_ID + 1,
            ),
            False,
        ),
        (
            ResourceIdentity(
                source=IdentitySource.API,
                resource_type="lora",
                model_id=MODEL_ID,
                model_version_id=MODEL_VERSION_ID,
            ),
            False,
        ),
    ],
)
def test_non_air_identity_comparison(
    right: ResourceIdentity,
    expected: bool,
) -> None:
    left = ResourceIdentity(
        source=IdentitySource.API,
        resource_type="checkpoint",
        model_id=MODEL_ID,
        model_version_id=MODEL_VERSION_ID,
    )

    assert client_module._same_identity(left, right) is expected


def test_tls_contexts_require_verification_and_tls_1_2_or_newer() -> None:
    contexts = create_tls_contexts()

    assert contexts
    assert contexts[0][0] == "system_default"
    for _source, context in contexts:
        assert context.check_hostname is True
        assert context.verify_mode is ssl.CERT_REQUIRED
        assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_tls_contexts_include_available_truststore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module,
        "_truststore_provider",
        SimpleNamespace(SSLContext=ssl.SSLContext),
    )

    contexts = create_tls_contexts()

    assert "truststore" in [source for source, _context in contexts]


def test_tls_contexts_tolerate_missing_optional_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_module, "_truststore_provider", None)
    monkeypatch.setattr(client_module, "_certifi_provider", None)

    contexts = create_tls_contexts()

    assert [source for source, _context in contexts] == ["system_default"]


def test_client_builds_default_tls_contexts_when_not_supplied() -> None:
    client = CivitaiClient()

    assert client._tls_contexts


def test_api_base_rejects_non_https_or_unapproved_hosts() -> None:
    with pytest.raises(ValueError, match="civitai_api_base_invalid"):
        CivitaiLookupConfig(enabled=True, api_base_url="http://civitai.com/api/v1")
    with pytest.raises(ValueError, match="civitai_api_base_invalid"):
        CivitaiLookupConfig(enabled=True, api_base_url="https://example.com/api/v1")


def test_no_private_request_data_rejects_authorization_or_body() -> None:
    authorized = httpx.Request(
        "GET",
        f"https://civitai.com/api/v1/model-versions/{MODEL_VERSION_ID}",
        headers={"Authorization": "Bearer hidden"},
    )
    body = httpx.Request(
        "POST",
        "https://civitai.com/api/v1/model-versions",
        content=json.dumps({"prompt": "private"}),
    )
    get_with_body = httpx.Request(
        "GET",
        "https://civitai.com/api/v1/model-versions",
        content=b"private",
    )
    wrong_host = httpx.Request(
        "GET",
        "https://example.com/api/v1/model-versions",
    )
    insecure = httpx.Request(
        "GET",
        "http://civitai.com/api/v1/model-versions",
    )

    assert no_private_request_data(authorized) is False
    assert no_private_request_data(body) is False
    assert no_private_request_data(get_with_body) is False
    assert no_private_request_data(wrong_host) is False
    assert no_private_request_data(insecure) is False
