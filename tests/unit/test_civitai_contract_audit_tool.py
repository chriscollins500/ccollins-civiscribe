from __future__ import annotations

import json
import ssl

import httpx

from civiscribe.identity.civitai_client import USER_AGENT
from civiscribe.identity.civitai_contract import (
    SUPPORTED_MODEL_FILE_TYPES,
    SUPPORTED_MODEL_TYPES,
)
from tools.audit_civitai_api_contract import (
    API_BASE_URL,
    ENUMS_URL,
    audit_enum_payload,
    audit_live_contract,
    audit_live_response_contract,
    audit_model_version_payload,
)

TEST_CONTEXTS = (("test_system", ssl.create_default_context()),)


def _payload() -> dict[str, object]:
    return {
        "ModelType": list(SUPPORTED_MODEL_TYPES),
        "ModelFileType": list(SUPPORTED_MODEL_FILE_TYPES),
    }


def _model_version_payload() -> dict[str, object]:
    return {
        "id": 20,
        "modelId": 10,
        "air": "urn:air:sdxl:checkpoint:civitai:10@20",
        "baseModel": "SDXL 1.0",
        "model": {"id": 10, "type": "Checkpoint"},
        "files": [
            {
                "id": 30,
                "type": "Model",
                "primary": True,
                "hashes": {"SHA256": "a" * 64},
                "metadata": {"format": "SafeTensor"},
            }
        ],
    }


def test_pinned_contract_payload_has_no_drift() -> None:
    result = audit_enum_payload(_payload(), tls_context_source="fixture")

    assert result.valid
    assert result.errors == ()
    assert result.tls_context_source == "fixture"
    assert result.as_dict()["endpoint"] == ENUMS_URL


def test_contract_audit_reports_additions_removals_and_invalid_shapes() -> None:
    payload = _payload()
    model_types = payload["ModelType"]
    assert isinstance(model_types, list)
    model_types.remove("Checkpoint")
    model_types.append("FutureModel")
    result = audit_enum_payload(payload)

    assert not result.valid
    assert result.missing_model_types == ("Checkpoint",)
    assert result.new_model_types == ("FutureModel",)

    invalid = audit_enum_payload({"ModelType": ["Checkpoint"], "ModelFileType": "Model"})
    assert invalid.errors == ("model_file_type_enum_invalid",)


def test_live_audit_uses_public_get_without_credentials_or_private_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == ENUMS_URL
        assert request.headers["User-Agent"] == USER_AGENT
        assert "Authorization" not in request.headers
        assert request.content == b""
        return httpx.Response(200, json=_payload())

    result = audit_live_contract(
        transport=httpx.MockTransport(handler),
        tls_contexts=TEST_CONTEXTS,
    )

    assert result.valid
    assert result.tls_context_source == "test_system"


def test_live_audit_sanitizes_http_and_json_failures() -> None:
    for response in (
        httpx.Response(503, text="private upstream diagnostics"),
        httpx.Response(200, content=b"{"),
    ):
        result = audit_live_contract(
            transport=httpx.MockTransport(lambda _request, response=response: response),
            tls_contexts=TEST_CONTEXTS,
        )
        assert not result.valid
        assert result.errors in {("http_status_503",), ("malformed_json",)}
        serialized = json.dumps(result.as_dict())
        assert "private upstream diagnostics" not in serialized


def test_model_version_response_contract_validates_consumed_fields() -> None:
    result = audit_model_version_payload(
        _model_version_payload(),
        endpoint_kind="hash",
        expected_hash="a" * 64,
        tls_context_source="fixture",
    )

    assert result.valid
    assert result.observed_file_count == 1
    assert result.warnings == ()
    assert result.as_dict()["endpointKind"] == "hash"


def test_response_contract_reports_shape_air_hash_and_enum_drift_safely() -> None:
    payload = _model_version_payload()
    payload["air"] = "urn:air:sdxl:checkpoint:civitai:10@21"
    model = payload["model"]
    assert isinstance(model, dict)
    model["type"] = "FutureType"
    files = payload["files"]
    assert isinstance(files, list)
    file = files[0]
    assert isinstance(file, dict)
    file["type"] = "Future File"
    file["hashes"] = {"FutureHash": "private upstream text"}

    result = audit_model_version_payload(
        payload,
        endpoint_kind="hash",
        expected_hash="a" * 64,
    )

    assert not result.valid
    assert set(result.errors) == {
        "file_hash_type_unreviewed",
        "file_hash_value_invalid",
        "file_type_unreviewed",
        "model_type_unreviewed",
        "official_air_id_conflict",
        "requested_hash_missing",
    }
    assert "private upstream text" not in json.dumps(result.as_dict())


def test_response_contract_distinguishes_missing_and_invalid_official_air() -> None:
    missing_payload = _model_version_payload()
    missing_payload.pop("air")
    invalid_payload = _model_version_payload()
    invalid_payload["air"] = "private upstream text"

    missing = audit_model_version_payload(missing_payload, endpoint_kind="model_version")
    invalid = audit_model_version_payload(invalid_payload, endpoint_kind="model_version")

    assert missing.valid
    assert missing.warnings == ("official_air_missing",)
    assert invalid.errors == ("official_air_invalid",)
    assert "private upstream text" not in json.dumps(invalid.as_dict())


def test_live_response_audit_uses_only_selected_public_identifier() -> None:
    expected_hash = "a" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == f"{API_BASE_URL}/model-versions/by-hash/{expected_hash}"
        assert "Authorization" not in request.headers
        assert request.content == b""
        return httpx.Response(200, json=_model_version_payload())

    result = audit_live_response_contract(
        endpoint_kind="hash",
        identifier=expected_hash,
        transport=httpx.MockTransport(handler),
        tls_contexts=TEST_CONTEXTS,
    )

    assert result.valid
    assert result.tls_context_source == "test_system"


def test_live_response_audit_rejects_identifier_and_sanitizes_failure() -> None:
    invalid = audit_live_response_contract(
        endpoint_kind="hash",
        identifier=r"C:\Users\person\private.safetensors",
    )
    assert invalid.errors == ("identifier_invalid",)

    failed = audit_live_response_contract(
        endpoint_kind="model_version",
        identifier="20",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(503, text="private upstream diagnostics")
        ),
        tls_contexts=TEST_CONTEXTS,
    )
    assert failed.errors == ("http_status_503",)
    assert "private upstream diagnostics" not in json.dumps(failed.as_dict())
