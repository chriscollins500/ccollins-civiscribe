from __future__ import annotations

import json
import socket
import ssl
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Mapping
from urllib import error as url_error
from unittest import mock

from save_node.civitai.air import parse_air
from save_node.civitai.lookup import (
    CivitaiApiClient,
    CivitaiHttpResponse,
    CivitaiLookupSettings,
    LOOKUP_RESOLUTION_SOURCE,
    StandardLibraryCivitaiTransport,
    create_verified_ssl_context,
    resolve_resources_with_civitai_api,
)
from save_node.civitai.manual_identities import (
    MANUAL_PINNED_IDENTITY_SOURCE,
    MANUAL_PINNED_LOOKUP_STATUS,
    PREFERRED_PRIMARY_MODEL_AIR_SOURCE,
    apply_manual_resource_identities,
    apply_preferred_primary_model_air,
)
from save_node.civitai.manifest import build_civitai_manifest
from save_node.hashing.resource_identity import HASHED_BUT_NO_CIVITAI_IDENTITY
from save_node.metadata.a1111 import build_a1111_parameters
from save_node.metadata.schema import (
    GenerationSettings,
    HashMetadata,
    ModelResourceMetadata,
    PromptMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationResult,
)
from save_node.metadata.serialize import to_json_text
from save_node.metadata.validate import validate_metadata
from save_node.nodes import _metadata_status

SHA_A = "a" * 64
SHA_B = "b" * 64
AUTO_A = "1234567890"
AUTO_B = "abcdef1234"
SENSITIVE_VALUE = "placeholder-value-not-for-auth"


class FakeTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        timeout_seconds: float,
        headers: Mapping[str, str],
        max_response_bytes: int,
    ) -> CivitaiHttpResponse:
        self.calls.append(
            {
                "url": url,
                "timeout": timeout_seconds,
                "headers": dict(headers),
                "max_response_bytes": max_response_bytes,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeUrlopenResponse:
    def __init__(self, *, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self, _size: int) -> bytes:
        return self._body


class CivitaiLookupTests(unittest.TestCase):
    def test_network_lookup_disabled_by_default(self) -> None:
        transport = FakeTransport([api_response(valid_payload())])
        client = api_client(transport)

        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(),
            client=client,
        )

        self.assertEqual(transport.calls, [])
        self.assertFalse(result.resources[0].resolved)

    def test_disabled_lookup_makes_zero_http_calls(self) -> None:
        transport = FakeTransport([api_response(valid_payload())])

        resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(enabled=False),
            client=api_client(transport),
        )

        self.assertEqual(len(transport.calls), 0)

    def test_disabled_lookup_marks_resource_skipped(self) -> None:
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(enabled=False),
            client=api_client(FakeTransport([])),
        )

        self.assertEqual(result.resources[0].resource.metadata["lookupStatus"], "skipped_lookup_disabled")
        self.assertEqual(result.lookup_debug_summary[0]["lookupStatus"], "skipped_lookup_disabled")
        self.assertEqual(result.lookup_debug_summary[0]["reason"], "lookup_disabled")
        manifest_json = manifest_json_for_lookup_result(result)
        self.assertEqual(manifest_json["resources"][0]["lookupStatus"], "skipped_lookup_disabled")
        self.assertEqual(manifest_json["unresolvedResources"][0]["lookupStatus"], "skipped_lookup_disabled")

    def test_missing_hash_marks_lookup_skipped(self) -> None:
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(sha256=None, auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(FakeTransport([])),
        )

        self.assertEqual(result.resources[0].resource.metadata["lookupStatus"], "skipped_no_hash")
        self.assertEqual(result.lookup_debug_summary[0]["reason"], "missing_hash")

    def test_lookup_by_sha256_succeeds(self) -> None:
        transport = FakeTransport([api_response(valid_payload())])
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        resource = result.resources[0]
        self.assertTrue(resource.resolved)
        self.assertEqual(resource.resource.civitai_model_id, 10)
        self.assertEqual(resource.resource.civitai_model_version_id, 20)
        self.assertEqual(resource.resource.air.raw, "urn:air:sdxl:checkpoint:civitai:10@20")
        self.assertEqual(resource.resource.resolution_source, LOOKUP_RESOLUTION_SOURCE)
        self.assertIn(SHA_A, str(transport.calls[0]["url"]))

    def test_autov2_fallback_succeeds(self) -> None:
        transport = FakeTransport(
            [
                CivitaiHttpResponse(status=404, body=b"{}"),
                api_response(valid_payload(file_hashes={"AutoV2": AUTO_A})),
            ]
        )
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(len(transport.calls), 2)
        self.assertIn(SHA_A, str(transport.calls[0]["url"]))
        self.assertIn(AUTO_A, str(transport.calls[1]["url"]))

    def test_sha256_is_preferred_over_autov2(self) -> None:
        transport = FakeTransport([api_response(valid_payload())])
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(enabled=True, prefer_sha256=True),
            client=api_client(transport),
        )

        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(len(transport.calls), 1)
        self.assertIn(SHA_A, str(transport.calls[0]["url"]))

    def test_lookup_tries_available_hashes_in_civitai_priority_order(self) -> None:
        resource = ResolvedResource(
            resource=ModelResourceMetadata(
                role="checkpoint",
                type="checkpoint",
                name="base.safetensors",
                filename="base.safetensors",
                hashes=HashMetadata(
                    sha256=SHA_A,
                    blake3="c" * 64,
                    auto_v2=AUTO_A,
                    auto_v3="d" * 12,
                    crc32="ABCDEF12",
                    auto_v1="1234ABCD",
                ),
            ),
            resolved=False,
            unresolved_reason=HASHED_BUT_NO_CIVITAI_IDENTITY,
        )
        transport = FakeTransport([CivitaiHttpResponse(status=404, body=b"{}") for _ in range(6)])

        result = resolve_resources_with_civitai_api(
            resources=(resource,),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        urls = [str(call["url"]) for call in transport.calls]
        self.assertIn(SHA_A, urls[0])
        self.assertIn("c" * 64, urls[1])
        self.assertIn(AUTO_A, urls[2])
        self.assertIn("d" * 12, urls[3])
        self.assertIn("abcdef12", urls[4])
        self.assertIn("1234abcd", urls[5])
        self.assertIn("attempted SHA256, BLAKE3, AutoV2, AutoV3, CRC32, AutoV1", result.warnings[0].message)

    def test_user_agent_is_sent_in_mocked_lookup(self) -> None:
        transport = FakeTransport([api_response(valid_payload())])

        resolve_resources_with_civitai_api(
            resources=(hashed_resource(auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        self.assertIn("ComfyUI-Civitai-Save-Node/", str(transport.calls[0]["headers"]["User-Agent"]))

    def test_dual_hash_lookup_failures_are_deduplicated_per_resource(self) -> None:
        transport = FakeTransport(
            [
                CivitaiHttpResponse(status=404, body=b"{}"),
                CivitaiHttpResponse(status=404, body=b"{}"),
            ]
        )

        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.warnings[0].code, "civitai_api_lookup_failed")
        self.assertIn("attempted SHA256, AutoV2", result.warnings[0].message)
        self.assertEqual(result.lookup_debug_summary[0]["hashTypesAttempted"], ["SHA256", "AutoV2"])
        self.assertEqual(result.lookup_debug_summary[0]["result"], "unresolved")

    def test_malformed_json_response_handled_safely(self) -> None:
        result = lookup_with_response(
            CivitaiHttpResponse(status=200, body=b"{bad json"),
            resource=hashed_resource(auto_v2=None),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_invalid_json", warning_codes(result))

    def test_http_404_leaves_resource_unresolved(self) -> None:
        result = lookup_with_response(
            CivitaiHttpResponse(status=404, body=b"{}"), resource=hashed_resource(auto_v2=None)
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_lookup_not_found", warning_codes(result))

    def test_http_429_leaves_resource_unresolved_with_warning(self) -> None:
        result = lookup_with_response(
            CivitaiHttpResponse(status=429, body=b"{}"), resource=hashed_resource(auto_v2=None)
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_rate_limited", warning_codes(result))
        self.assertEqual(result.resources[0].resource.metadata["lookupStatus"], "failed")
        self.assertEqual(result.resources[0].resource.metadata["lookupStatusCode"], 429)
        self.assertTrue(result.resources[0].resource.metadata["lookupRetryable"])
        self.assertTrue(result.lookup_debug_summary[0]["retryable"])
        manifest_json = manifest_json_for_lookup_result(result)
        self.assertEqual(manifest_json["resources"][0]["lookupStatus"], "failed")
        self.assertEqual(manifest_json["unresolvedResources"][0]["lookupStatus"], "failed")
        self.assertEqual(
            manifest_json["unresolvedResources"][0]["unresolvedReason"],
            HASHED_BUT_NO_CIVITAI_IDENTITY,
        )
        self.assertIn("lookupDebugSummary", manifest_json)
        self.assertEqual(manifest_json["metadataStatus"], "partial")

    def test_http_statuses_are_classified_safely(self) -> None:
        cases = [
            (400, "bad_request", "civitai_api_bad_request", False),
            (401, "unauthorized", "civitai_api_unauthorized", False),
            (403, "forbidden", "civitai_api_forbidden", False),
            (405, "method_not_allowed", "civitai_api_method_not_allowed", False),
            (500, "server_error", "civitai_api_server_error", True),
        ]
        for status, reason, code, retryable in cases:
            with self.subTest(status=status):
                result = lookup_with_response(
                    CivitaiHttpResponse(
                        status=status,
                        body=json.dumps({"code": "ERR", "message": "safe message", "issues": []}).encode("utf-8"),
                    ),
                    resource=hashed_resource(auto_v2=None),
                )

                self.assertFalse(result.resources[0].resolved)
                self.assertIn(code, warning_codes(result))
                self.assertEqual(result.lookup_debug_summary[0]["reason"], f"{reason}; HTTP status {status}")
                self.assertEqual(result.lookup_debug_summary[0]["statusCode"], status)
                self.assertEqual(result.lookup_debug_summary[0]["retryable"], retryable)

    def test_ssl_certificate_failure_is_classified_distinctly(self) -> None:
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(FakeTransport([ssl.SSLCertVerificationError("certificate verify failed")])),
        )

        metadata = result.resources[0].resource.metadata
        self.assertEqual(metadata["lookupFailureReason"], "ssl_error")
        self.assertEqual(metadata["lookupFailureClass"], "ssl_certificate_verify_failed")
        self.assertEqual(metadata["lookupClient"], "custom")
        self.assertEqual(metadata["sslContextSource"], "unavailable")
        self.assertEqual(metadata["apiEndpointKind"], "by_hash")
        self.assertEqual(result.lookup_debug_summary[0]["lookupFailureClass"], "ssl_certificate_verify_failed")

    def test_tls_eof_is_classified_distinctly(self) -> None:
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(FakeTransport([ssl.SSLEOFError("unexpected eof while reading")])),
        )

        self.assertEqual(result.resources[0].resource.metadata["lookupFailureReason"], "ssl_error")
        self.assertEqual(result.resources[0].resource.metadata["lookupFailureClass"], "ssl_eof")

    def test_timeout_is_classified_distinctly(self) -> None:
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(FakeTransport([TimeoutError("timed out")])),
        )

        self.assertEqual(result.resources[0].resource.metadata["lookupFailureReason"], "timeout")
        self.assertEqual(result.resources[0].resource.metadata["lookupFailureClass"], "timeout")
        self.assertTrue(result.resources[0].resource.metadata["lookupRetryable"])

    def test_certifi_context_used_when_available(self) -> None:
        fake_context = object()
        fake_certifi = types.SimpleNamespace(where=lambda: "C:/safe/certifi/cacert.pem")
        with mock.patch.dict(sys.modules, {"certifi": fake_certifi}):
            with mock.patch("ssl.create_default_context", return_value=fake_context) as create_context:
                context, source = create_verified_ssl_context()

        self.assertIs(context, fake_context)
        self.assertEqual(source, "certifi")
        create_context.assert_called_once_with(cafile="C:/safe/certifi/cacert.pem")

    def test_system_context_used_when_certifi_unavailable(self) -> None:
        fake_context = object()
        with mock.patch.dict(sys.modules, {"certifi": None}):
            with mock.patch("ssl.create_default_context", return_value=fake_context) as create_context:
                context, source = create_verified_ssl_context()

        self.assertIs(context, fake_context)
        self.assertEqual(source, "system_default")
        create_context.assert_called_once_with()

    def test_certifi_certificate_failure_falls_back_to_verified_system_context(self) -> None:
        response = FakeUrlopenResponse(status=200, body=b"{}")
        certifi_failure = url_error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate"))
        with mock.patch(
            "save_node.civitai.lookup.create_verified_ssl_context", return_value=("certifi_context", "certifi")
        ):
            with mock.patch("save_node.civitai.lookup.ssl.create_default_context", return_value="system_context"):
                with mock.patch(
                    "save_node.civitai.lookup.request.urlopen", side_effect=[certifi_failure, response]
                ) as urlopen:
                    transport = StandardLibraryCivitaiTransport()
                    result = transport.get(
                        "https://civitai.com/api/v1/model-versions/2734704",
                        timeout_seconds=1,
                        headers={"Accept": "application/json"},
                        max_response_bytes=1024,
                    )

        self.assertEqual(result.status, 200)
        self.assertEqual(result.ssl_context_source, "system_default")
        self.assertEqual(result.lookup_client, "urllib")
        self.assertEqual(urlopen.call_args_list[0].kwargs["context"], "certifi_context")
        self.assertEqual(urlopen.call_args_list[1].kwargs["context"], "system_context")

    def test_error_body_shape_with_error_field_is_sanitized(self) -> None:
        result = lookup_with_response(
            CivitaiHttpResponse(
                status=400,
                body=json.dumps({"error": r"bad path C:\\Private\\secret.safetensors"}).encode("utf-8"),
            ),
            resource=hashed_resource(auto_v2=None),
        )

        warning_text = to_json_text([warning.to_json() for warning in result.warnings])
        self.assertIn("civitai_api_bad_request", warning_codes(result))
        self.assertNotIn(r"C:\\Private", warning_text)

    def test_timeout_leaves_resource_unresolved_with_warning(self) -> None:
        transport = FakeTransport([TimeoutError()])
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True, timeout_seconds=0.2),
            client=api_client(transport),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_lookup_timeout", warning_codes(result))
        self.assertTrue(result.lookup_debug_summary[0]["retryable"])
        self.assertEqual(result.lookup_debug_summary[0]["reason"], "timeout")
        self.assertNotIn(SENSITIVE_VALUE, to_json_text(result.lookup_debug_summary) + to_json_text(result.warnings))

    def test_dns_error_is_classified_safely(self) -> None:
        transport = FakeTransport([socket.gaierror("name lookup failed")])
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_dns_error", warning_codes(result))
        self.assertEqual(result.lookup_debug_summary[0]["reason"], "dns_error")
        self.assertTrue(result.lookup_debug_summary[0]["retryable"])

    def test_response_without_matching_hash_is_rejected(self) -> None:
        result = lookup_with_response(
            api_response(valid_payload(file_hashes={"SHA256": SHA_B, "AutoV2": AUTO_B})),
            resource=hashed_resource(auto_v2=None),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_hash_mismatch", warning_codes(result))

    def test_lookup_diagnostics_do_not_include_private_inputs(self) -> None:
        private_resource = hashed_resource(auto_v2=None)
        private_resource = ResolvedResource(
            resource=ModelResourceMetadata(
                **{
                    **private_resource.resource.__dict__,
                    "name": r"C:\Private\Local\base.safetensors",
                    "filename": r"C:\Private\Local\base.safetensors",
                    "selected_value": r"C:\Private\Local\base.safetensors",
                }
            ),
            resolved=False,
            unresolved_reason=private_resource.unresolved_reason,
        )
        result = lookup_with_response(
            api_response(valid_payload(file_hashes={"SHA256": SHA_B})),
            resource=private_resource,
        )
        diagnostics = to_json_text(
            {
                "warnings": [warning.to_json() for warning in result.warnings],
                "debug": result.lookup_debug_summary,
                "prompt": "not included",
            }
        )

        self.assertNotIn(r"C:\Private\Local", diagnostics)
        self.assertNotIn(SENSITIVE_VALUE, diagnostics)
        self.assertNotIn("workflow", diagnostics.lower())
        self.assertNotIn("image bytes", diagnostics.lower())

    def test_conflict_lookup_status_serializes_top_level(self) -> None:
        resource = ResolvedResource(
            resource=ModelResourceMetadata(
                role="checkpoint",
                type="checkpoint",
                name="base.safetensors",
                filename="base.safetensors",
                metadata={"lookupStatus": "conflict"},
            ),
            resolved=False,
            unresolved_reason="identity_conflict",
        )
        manifest = build_civitai_manifest(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(),
            resources=(resource,),
            unresolved_resources=(resource_to_unresolved(resource),),
            hashes=HashMetadata(),
            validation=ValidationResult(),
            include_workflow=False,
            metadata_status="partial",
        )
        manifest_json = json.loads(to_json_text(manifest))

        self.assertEqual(manifest_json["resources"][0]["lookupStatus"], "conflict")
        self.assertEqual(manifest_json["unresolvedResources"][0]["lookupStatus"], "conflict")

    def test_response_with_model_version_but_missing_model_id_does_not_build_air(self) -> None:
        result = lookup_with_response(
            api_response(valid_payload(model_id=None)),
            resource=hashed_resource(auto_v2=None),
        )

        resource = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertIsNone(resource.air)
        self.assertIsNone(resource.civitai_model_id)
        self.assertEqual(resource.civitai_model_version_id, 20)
        self.assertIn("civitai_api_air_missing_model_id", warning_codes(result))

    def test_response_with_enough_fields_builds_full_air(self) -> None:
        result = lookup_with_response(api_response(valid_payload(base_model="Flux.1 Dev", model_type="Checkpoint")))

        self.assertEqual(result.resources[0].resource.air.raw, "urn:air:flux1:checkpoint:civitai:10@20")

    def test_hash_lookup_response_with_air_uses_returned_air_directly(self) -> None:
        official_air = "urn:air:boogu:diffusionmodel:civitai:2714299@3049541+3000001.gguf"
        result = lookup_with_response(
            api_response(
                valid_payload(
                    model_id=2714299,
                    version_id=3049541,
                    base_model="Mystery Base Model",
                    model_type="Checkpoint",
                    extra={"air": official_air},
                )
            ),
            resource=hashed_resource(role="base_model", type_="diffusion_model", auto_v2=None),
        )

        resource = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(resource.air.canonical if resource.air else None, official_air)
        self.assertEqual(resource.air.file_id if resource.air else None, "3000001")
        self.assertEqual(resource.air.format if resource.air else None, "gguf")
        self.assertEqual(resource.air.type if resource.air else None, "diffusionmodel")

    def test_hash_lookup_without_air_fetches_model_version_details_when_needed(self) -> None:
        official_air = "urn:air:boogu:diffusionmodel:civitai:2714299@3049541"
        transport = FakeTransport(
            [
                api_response(
                    valid_payload(
                        model_id=2714299,
                        version_id=3049541,
                        base_model="Mystery Base Model",
                        model_type="Checkpoint",
                    )
                ),
                api_response({"air": official_air}),
            ]
        )
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(role="base_model", type_="diffusion_model", auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        self.assertEqual(len(transport.calls), 2)
        self.assertIn("/model-versions/3049541", str(transport.calls[1]["url"]))
        self.assertEqual(result.resources[0].resource.air.canonical, official_air)

    def test_conflicting_model_version_and_air_is_rejected(self) -> None:
        result = lookup_with_response(
            api_response(
                valid_payload(
                    model_id=10,
                    version_id=20,
                    extra={"air": "urn:air:sdxl:checkpoint:civitai:10@99"},
                )
            ),
            resource=hashed_resource(auto_v2=None),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_air_identity_conflict", warning_codes(result))

    def test_diffusion_model_without_api_air_does_not_invent_checkpoint_air(self) -> None:
        result = lookup_with_response(
            api_response(
                valid_payload(
                    model_id=2432159,
                    version_id=2734704,
                    base_model="Flux.2",
                    model_type="Checkpoint",
                )
            ),
            resource=hashed_resource(role="base_model", type_="diffusion_model", auto_v2=None),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_type_mismatch", warning_codes(result))

    def test_flux2_diffusion_model_lookup_uses_api_returned_checkpoint_air(self) -> None:
        result = lookup_with_response(
            api_response(
                valid_payload(
                    model_id=2432159,
                    version_id=2734704,
                    base_model="Flux.2",
                    model_type="Checkpoint",
                    extra={"air": "urn:air:flux2:checkpoint:civitai:2432159@2734704"},
                )
            ),
            resource=hashed_resource(role="base_model", type_="diffusion_model", auto_v2=None),
        )

        resource = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(resource.air.raw, "urn:air:flux2:checkpoint:civitai:2432159@2734704")
        self.assertEqual(resource.civitai_model_id, 2432159)
        self.assertEqual(resource.civitai_model_version_id, 2734704)

    def test_unknown_ecosystem_does_not_invent_air(self) -> None:
        result = lookup_with_response(
            api_response(valid_payload(base_model="Mystery Base Model")),
            resource=hashed_resource(auto_v2=None),
        )

        self.assertTrue(result.resources[0].resolved)
        self.assertIsNone(result.resources[0].resource.air)
        self.assertIn("civitai_api_unknown_ecosystem", warning_codes(result))

    def test_uncertain_local_model_type_preserves_ids_without_inventing_air(self) -> None:
        result = lookup_with_response(
            api_response(valid_payload()),
            resource=hashed_resource(role="base_model", type_="video_model", auto_v2=None),
        )

        resource = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(resource.civitai_model_id, 10)
        self.assertEqual(resource.civitai_model_version_id, 20)
        self.assertIsNone(resource.air)
        self.assertIn("civitai_api_local_type_not_air_mapped", warning_codes(result))

    def test_type_mismatch_warns_and_does_not_resolve(self) -> None:
        result = lookup_with_response(
            api_response(valid_payload(model_type="LORA")),
            resource=hashed_resource(role="checkpoint", type_="checkpoint", auto_v2=None),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_type_mismatch", warning_codes(result))

    def test_local_cache_identity_wins_over_api_result(self) -> None:
        air, warnings = parse_air("urn:air:sdxl:checkpoint:civitai:10@20")
        self.assertEqual(warnings, ())
        local_resource = ResolvedResource(
            resource=ModelResourceMetadata(
                role="checkpoint",
                type="checkpoint",
                name="base.safetensors",
                hashes=HashMetadata(sha256=SHA_A, auto_v2=AUTO_A),
                air=air,
                civitai_model_id=10,
                civitai_model_version_id=20,
                resolution_source="local_identity_cache",
            ),
            resolved=True,
        )
        transport = FakeTransport([api_response(valid_payload(model_id=99, version_id=100))])

        result = resolve_resources_with_civitai_api(
            resources=(local_resource,),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        self.assertEqual(transport.calls, [])
        self.assertEqual(result.resources[0].resource.civitai_model_id, 10)
        self.assertEqual(result.resources[0].resource.resolution_source, "local_identity_cache")

    def test_manual_pinned_identity_wins_over_api_alternate_match(self) -> None:
        manual_result = apply_manual_resource_identities(
            resources=(hashed_resource(role="base_model", type_="diffusion_model"),),
            manual_resource_identities_json=json.dumps(
                [
                    {
                        "match": {
                            "name": "base.safetensors",
                            "SHA256": SHA_A,
                            "AutoV2": AUTO_A,
                            "role": "base_model",
                            "type": "diffusion_model",
                        },
                        "air": "urn:air:flux2:checkpoint:civitai:2432159@2734704",
                        "modelId": 2432159,
                        "modelVersionId": 2734704,
                        "pinned": True,
                        "confidence": "user_pinned",
                    }
                ]
            ),
        )
        transport = FakeTransport(
            [
                api_response(
                    valid_payload(
                        model_id=2167454,
                        version_id=2442756,
                        base_model="Flux.2",
                        model_type="Checkpoint",
                        extra={"air": "urn:air:flux2:checkpoint:civitai:2167454@2442756"},
                    )
                )
            ]
        )

        result = resolve_resources_with_civitai_api(
            resources=manual_result.resources,
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        resource = result.resources[0].resource
        self.assertEqual(len(transport.calls), 1)
        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(resource.air.canonical, "urn:air:flux2:checkpoint:civitai:2432159@2734704")
        self.assertEqual(resource.civitai_model_id, 2432159)
        self.assertEqual(resource.civitai_model_version_id, 2734704)
        self.assertEqual(resource.resolution_source, MANUAL_PINNED_IDENTITY_SOURCE)
        self.assertEqual(resource.metadata["lookupStatus"], MANUAL_PINNED_LOOKUP_STATUS)
        self.assertTrue(resource.metadata["apiAlternateMatch"])
        self.assertEqual(resource.metadata["apiReturnedAir"], "urn:air:flux2:checkpoint:civitai:2167454@2442756")
        self.assertIn("api_alternate_match", warning_codes(result))
        self.assertEqual(result.lookup_debug_summary[0]["result"], MANUAL_PINNED_LOOKUP_STATUS)
        self.assertEqual(result.lookup_debug_summary[0]["identitySource"], MANUAL_PINNED_IDENTITY_SOURCE)
        self.assertTrue(result.lookup_debug_summary[0]["apiAlternateMatch"])

        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model="base.safetensors", model_hash=AUTO_A),
            resources=result.resources,
            hashes=HashMetadata(additional={"model": AUTO_A}),
        )
        self.assertIn("urn:air:flux2:checkpoint:civitai:2432159@2734704", parameters)
        self.assertNotIn("urn:air:flux2:checkpoint:civitai:2167454@2442756", parameters)

    def test_preferred_primary_model_air_wins_over_api_alternate_match(self) -> None:
        primary = hashed_resource(role="base_model", type_="diffusion_model")
        primary = ResolvedResource(
            resource=ModelResourceMetadata(
                **{
                    **primary.resource.__dict__,
                    "metadata": {"primaryModel": True},
                }
            ),
            resolved=primary.resolved,
            unresolved_reason=primary.unresolved_reason,
        )
        preferred_result = apply_preferred_primary_model_air(
            resources=(primary,),
            preferred_primary_model_air="urn:air:flux2:checkpoint:civitai:2432159@2734704",
        )
        transport = FakeTransport(
            [
                api_response(
                    valid_payload(
                        model_id=2167454,
                        version_id=2442756,
                        base_model="Flux.2",
                        model_type="Checkpoint",
                        extra={"air": "urn:air:flux2:checkpoint:civitai:2167454@2442756"},
                    )
                )
            ]
        )

        result = resolve_resources_with_civitai_api(
            resources=preferred_result.resources,
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        resource = result.resources[0].resource
        self.assertEqual(resource.air.canonical, "urn:air:flux2:checkpoint:civitai:2432159@2734704")
        self.assertEqual(resource.metadata["identitySource"], PREFERRED_PRIMARY_MODEL_AIR_SOURCE)
        self.assertTrue(resource.metadata["apiAlternateMatch"])
        self.assertEqual(resource.metadata["apiReturnedAir"], "urn:air:flux2:checkpoint:civitai:2167454@2442756")
        self.assertEqual(result.lookup_debug_summary[0]["identitySource"], PREFERRED_PRIMARY_MODEL_AIR_SOURCE)
        self.assertEqual(result.lookup_debug_summary[0]["result"], MANUAL_PINNED_LOOKUP_STATUS)
        self.assertIn("api_alternate_match", warning_codes(result))

    def test_preferred_model_version_id_fetches_official_air_when_lookup_enabled(self) -> None:
        primary = hashed_resource(role="base_model", type_="diffusion_model")
        primary = ResolvedResource(
            resource=ModelResourceMetadata(
                **{
                    **primary.resource.__dict__,
                    "metadata": {"primaryModel": True},
                }
            ),
            resolved=primary.resolved,
            unresolved_reason=primary.unresolved_reason,
        )
        preferred_result = apply_preferred_primary_model_air(
            resources=(primary,),
            preferred_primary_model_air="2734704",
        )
        transport = FakeTransport(
            [
                api_response(
                    valid_payload(
                        model_id=2432159,
                        version_id=2734704,
                        base_model="Flux.2",
                        model_type="Checkpoint",
                        extra={"air": "urn:air:flux2:checkpoint:civitai:2432159@2734704"},
                    )
                )
            ]
        )

        result = resolve_resources_with_civitai_api(
            resources=preferred_result.resources,
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        resource = result.resources[0].resource
        self.assertIn("/model-versions/2734704", str(transport.calls[0]["url"]))
        self.assertEqual(resource.air.canonical, "urn:air:flux2:checkpoint:civitai:2432159@2734704")
        self.assertEqual(resource.metadata["identitySource"], PREFERRED_PRIMARY_MODEL_AIR_SOURCE)
        self.assertFalse(resource.metadata["identityIncomplete"])
        self.assertEqual(resource.metadata["lookupMethod"], "model_version")
        self.assertEqual(resource.metadata["apiCompletionStatus"], "resolved")

    def test_preferred_model_version_completion_failure_stays_partial_pinned(self) -> None:
        primary = hashed_resource(role="base_model", type_="diffusion_model")
        primary = ResolvedResource(
            resource=ModelResourceMetadata(
                **{
                    **primary.resource.__dict__,
                    "metadata": {"primaryModel": True},
                }
            ),
            resolved=primary.resolved,
            unresolved_reason=primary.unresolved_reason,
        )
        preferred_result = apply_preferred_primary_model_air(
            resources=(primary,),
            preferred_primary_model_air="2734704",
        )
        transport = FakeTransport([OSError("certificate verify failed")])

        result = resolve_resources_with_civitai_api(
            resources=preferred_result.resources,
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )

        resource = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertIsNone(resource.air)
        self.assertTrue(resource.metadata["identityIncomplete"])
        self.assertEqual(resource.metadata["identityStatus"], "partial_pinned")
        self.assertEqual(resource.metadata["lookupStatus"], MANUAL_PINNED_LOOKUP_STATUS)
        self.assertNotIn("lookupFailureReason", resource.metadata)
        self.assertEqual(resource.metadata["apiCompletionStatus"], "failed")
        self.assertEqual(resource.metadata["apiCompletionFailureReason"], "ssl_error")
        self.assertTrue(resource.metadata["apiCompletionRetryable"])
        self.assertEqual(result.lookup_debug_summary[0]["apiCompletionStatus"], "failed")
        self.assertEqual(result.lookup_debug_summary[0]["apiCompletionFailureReason"], "ssl_error")

        validation = validate_metadata(
            filename_prefix="safe",
            prompt_metadata=PromptMetadata(positive="test"),
            generation=GenerationSettings(steps=1, width=1, height=1),
            resources=result.resources,
            unresolved_resources=result.unresolved_resources,
            prompt={},
            extra_pnginfo={"workflow": {}},
            include_workflow=True,
            include_civitai_manifest=True,
            additional_warnings=result.warnings,
        )
        self.assertIn("preferred_identity_incomplete_air", {warning.code for warning in validation.warnings})
        self.assertEqual(_metadata_status([], validation, result.unresolved_resources), "partial")

    def test_api_token_is_never_written_to_metadata_or_headers(self) -> None:
        payload = valid_payload(extra={"token": SENSITIVE_VALUE, "apiToken": SENSITIVE_VALUE})
        transport = FakeTransport([api_response(payload)])
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True),
            client=api_client(transport),
        )
        manifest = build_civitai_manifest(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(),
            resources=result.resources,
            unresolved_resources=result.unresolved_resources,
            hashes=HashMetadata(),
            validation=ValidationResult(warnings=result.warnings),
            include_workflow=False,
        )
        combined = to_json_text(manifest)

        self.assertNotIn("Authorization", transport.calls[0]["headers"])
        self.assertNotIn(SENSITIVE_VALUE, combined)

    def test_generated_cache_stores_only_validated_identity_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "civitai_identity_cache.generated.json"
            result = resolve_resources_with_civitai_api(
                resources=(hashed_resource(auto_v2=None),),
                settings=CivitaiLookupSettings(
                    enabled=True,
                    cache_results=True,
                    generated_cache_path=cache_path,
                ),
                client=api_client(FakeTransport([api_response(valid_payload(extra={"token": SENSITIVE_VALUE}))])),
            )

            self.assertTrue(result.resources[0].resolved)
            cache_text = cache_path.read_text(encoding="utf-8")
            cache_json = json.loads(cache_text)
            self.assertEqual(cache_json["records"][0]["air"], "urn:air:sdxl:checkpoint:civitai:10@20")
            self.assertEqual(cache_json["records"][0]["civitaiModelVersionId"], 20)
            self.assertNotIn(SENSITIVE_VALUE, cache_text)

    def test_a1111_civitai_resources_includes_api_air(self) -> None:
        result = lookup_with_response(api_response(valid_payload()))
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model="base.safetensors", model_hash=AUTO_A),
            resources=result.resources,
            hashes=HashMetadata(additional={"model": AUTO_A}),
        )

        self.assertIn('"urn":"urn:air:sdxl:checkpoint:civitai:10@20"', parameters)
        self.assertIn('"air":"urn:air:sdxl:checkpoint:civitai:10@20"', parameters)
        self.assertIn('"modelVersionId":20', parameters)
        manifest_json = manifest_json_for_lookup_result(result)
        self.assertEqual(manifest_json["resources"][0]["lookupStatus"], "resolved")

    def test_a1111_civitai_resources_includes_file_id_when_known(self) -> None:
        result = lookup_with_response(
            api_response(valid_payload(extra={"air": "urn:air:sdxl:checkpoint:civitai:10@20+333.safetensor"}))
        )
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model="base.safetensors", model_hash=AUTO_A),
            resources=result.resources,
            hashes=HashMetadata(additional={"model": AUTO_A}),
        )

        self.assertIn('"fileId":"333"', parameters)
        self.assertIn('"format":"safetensor"', parameters)

    def test_manifest_contains_api_resolution_source(self) -> None:
        result = lookup_with_response(api_response(valid_payload()))
        manifest = build_civitai_manifest(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(),
            resources=result.resources,
            unresolved_resources=result.unresolved_resources,
            hashes=HashMetadata(),
            validation=ValidationResult(warnings=result.warnings),
            include_workflow=False,
        )
        manifest_json = json.loads(to_json_text(manifest))

        self.assertEqual(
            manifest_json["resources"][0]["resolutionSource"],
            LOOKUP_RESOLUTION_SOURCE,
        )

    def test_unresolved_resource_remains_unresolved_when_lookup_fails(self) -> None:
        result = lookup_with_response(
            CivitaiHttpResponse(status=404, body=b"{}"),
            resource=hashed_resource(auto_v2=None),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertEqual(result.unresolved_resources[0].reason, HASHED_BUT_NO_CIVITAI_IDENTITY)


def hashed_resource(
    *,
    role: str = "checkpoint",
    type_: str = "checkpoint",
    sha256: str | None = SHA_A,
    auto_v2: str | None = AUTO_A,
) -> ResolvedResource:
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role=role,
            type=type_,
            node_id="1",
            node_class_type="TestLoader",
            name="base.safetensors",
            selected_value="base.safetensors",
            filename="base.safetensors",
            local_path_basename="base.safetensors",
            hashes=HashMetadata(sha256=sha256, auto_v2=auto_v2),
            hash_source="local_file",
            hash_status="hashed",
        ),
        resolved=False,
        unresolved_reason=HASHED_BUT_NO_CIVITAI_IDENTITY,
    )


def valid_payload(
    *,
    model_id: int | None = 10,
    version_id: int = 20,
    base_model: str = "SDXL 1.0",
    model_type: str = "Checkpoint",
    file_hashes: dict[str, str] | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": version_id,
        "name": "Mock Version",
        "baseModel": base_model,
        "trainedWords": ["mocktrigger"],
        "model": {
            "id": model_id,
            "name": "Mock Model",
            "type": model_type,
        },
        "files": [
            {
                "name": "base.safetensors",
                "hashes": file_hashes or {"SHA256": SHA_A, "AutoV2": AUTO_A},
            }
        ],
    }
    if model_id is not None:
        payload["modelId"] = model_id
    if extra:
        payload.update(extra)
    return payload


def api_response(payload: object) -> CivitaiHttpResponse:
    return CivitaiHttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


def api_client(transport: FakeTransport) -> CivitaiApiClient:
    return CivitaiApiClient(base_url="https://example.test/api/v1", transport=transport)


def lookup_with_response(
    response: CivitaiHttpResponse,
    *,
    resource: ResolvedResource | None = None,
):
    return resolve_resources_with_civitai_api(
        resources=(resource or hashed_resource(),),
        settings=CivitaiLookupSettings(enabled=True),
        client=api_client(FakeTransport([response])),
    )


def manifest_json_for_lookup_result(result) -> dict[str, object]:
    manifest = build_civitai_manifest(
        prompt=PromptMetadata(positive="test"),
        generation=GenerationSettings(),
        resources=result.resources,
        unresolved_resources=result.unresolved_resources,
        hashes=HashMetadata(),
        validation=ValidationResult(warnings=result.warnings),
        include_workflow=False,
        metadata_status="partial" if result.unresolved_resources else "complete",
        lookup_debug_summary=result.lookup_debug_summary,
    )
    return json.loads(to_json_text(manifest))


def resource_to_unresolved(resource: ResolvedResource) -> UnresolvedResource:
    metadata = resource.resource
    return UnresolvedResource(
        reason=resource.unresolved_reason or "resource_not_civitai_resolved",
        role=metadata.role,
        type=metadata.type,
        name=metadata.name,
        filename=metadata.filename,
        hashes=metadata.hashes,
        hash_status=metadata.hash_status,
        lookup_status=str(metadata.metadata.get("lookupStatus")),
    )


def warning_codes(result) -> set[str]:
    return {warning.code for warning in result.warnings}


if __name__ == "__main__":
    unittest.main()
