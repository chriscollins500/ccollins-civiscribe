from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest import mock

from save_node import nodes
from save_node.civitai.identity_cache import (
    IdentityCache,
    parse_identity_cache,
)
from save_node.civitai.identity_resolution import apply_identity_cache
from save_node.civitai.lookup import (
    CivitaiHttpResponse,
    CivitaiLookupSettings,
    resolve_resources_with_civitai_api,
)
from save_node.civitai.manifest import build_civitai_manifest
from save_node.comfy.workflow_scan import WorkflowScanResult
from save_node.hashing.resource_identity import (
    HASHED_BUT_NO_CIVITAI_IDENTITY,
    ResourceHashingResult,
)
from save_node.io.sidecar import build_sidecar_payload
from save_node.metadata.a1111 import build_a1111_parameters
from save_node.metadata.schema import (
    GenerationSettings,
    GeneratorMetadata,
    HashMetadata,
    MetadataOptions,
    ModelResourceMetadata,
    PromptMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
    ValidationResult,
)
from save_node.metadata.serialize import to_json_text
from save_node.metadata.validate import validate_metadata
from save_node.security.redaction import MAX_METADATA_STRING_CHARS

SHA_A = "a" * 64
SHA_B = "b" * 64
AUTO_A = "1234567890"
SENSITIVE = "placeholder-value-not-for-auth"


class SecurityHardeningTests(unittest.TestCase):
    def test_a1111_redacts_windows_posix_paths_and_token_like_values(self) -> None:
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(
                positive=rf"uses C:\Private\Local\models\base.safetensors and /private/home/model token={SENSITIVE}",
                negative=r"avoid C:\private\bad.safetensors",
            ),
            generation=GenerationSettings(model=r"C:\Private\Local\models\base.safetensors"),
            resources=(),
            hashes=HashMetadata(additional={"model": AUTO_A}),
        )

        self.assertNotIn(r"C:\Private\Local", parameters)
        self.assertNotIn("/private/home", parameters)
        self.assertNotIn(SENSITIVE, parameters)
        self.assertIn("<redacted_path:base.safetensors>", parameters)
        self.assertIn("token=<redacted_secret>", parameters)

    def test_absolute_posix_path_does_not_appear_in_manifest_json(self) -> None:
        manifest = build_civitai_manifest(
            prompt=PromptMetadata(positive="/private/local/secret/model.safetensors"),
            generation=GenerationSettings(model="/private/local/secret/model.safetensors"),
            resources=(),
            unresolved_resources=(
                UnresolvedResource(reason="missing", filename="/private/local/secret/model.safetensors"),
            ),
            hashes=HashMetadata(),
            validation=ValidationResult(),
            include_workflow=False,
        )
        text = to_json_text(manifest)

        self.assertNotIn("/private/local", text)
        self.assertIn("<redacted_path:model.safetensors>", text)

    def test_control_characters_are_removed_from_metadata_text(self) -> None:
        text = to_json_text(PromptMetadata(positive="alpha\x00beta\x1fgamma"))
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="alpha\x00beta\x1fgamma"),
            generation=GenerationSettings(),
        )

        self.assertNotIn("\\u0000", text)
        self.assertNotIn("\x00", parameters)
        self.assertIn("alpha beta gamma", parameters)

    def test_huge_prompt_is_truncated_and_validator_warns(self) -> None:
        huge = "x" * (MAX_METADATA_STRING_CHARS + 10)
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive=huge),
            generation=GenerationSettings(),
        )
        validation = validate_metadata(
            filename_prefix="ok",
            prompt_metadata=PromptMetadata(positive=huge),
            generation=GenerationSettings(),
            resources=(),
            unresolved_resources=(),
            prompt={},
            extra_pnginfo={},
            include_workflow=False,
            include_civitai_manifest=True,
        )

        self.assertIn(f"<truncated:{MAX_METADATA_STRING_CHARS} chars max>", parameters)
        self.assertIn("metadata_field_size_exceeded", {warning.code for warning in validation.warnings})

    def test_validation_issue_output_redacts_paths_and_token_like_values(self) -> None:
        issue = ValidationIssue(
            code="sample",
            message=rf"bad path C:\Private\Local\secret.safetensors token={SENSITIVE}",
            field=r"C:\Private\Local\field",
        )
        result = ValidationResult(errors=(issue,))
        combined = to_json_text(result) + result.format_errors()

        self.assertNotIn(r"C:\Private\Local", combined)
        self.assertNotIn(SENSITIVE, combined)
        self.assertIn("<redacted_secret>", combined)

    def test_conflicting_cache_records_are_rejected(self) -> None:
        parsed = parse_identity_cache(
            {
                "records": [
                    identity_record("urn:air:sdxl:checkpoint:civitai:10@20", sha256=SHA_A),
                    identity_record("urn:air:sdxl:checkpoint:civitai:30@40", sha256=SHA_A, model_id=30, version_id=40),
                ]
            }
        )

        self.assertEqual(len(parsed.cache.records), 1)
        self.assertIn("identity_record_hash_conflict", {error.code for error in parsed.errors})

    def test_invalid_cache_hash_is_rejected(self) -> None:
        parsed = parse_identity_cache(
            {"records": [identity_record("urn:air:sdxl:checkpoint:civitai:10@20", sha256="not-a-sha")]}
        )

        self.assertEqual(parsed.cache.records, ())
        self.assertIn("identity_record_invalid_sha256", {error.code for error in parsed.errors})

    def test_corrupt_generated_cache_recovers_with_valid_api_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "civitai_identity_cache.generated.json"
            cache_path.write_text("{ corrupt json", encoding="utf-8")
            result = resolve_resources_with_civitai_api(
                resources=(hashed_resource(),),
                settings=CivitaiLookupSettings(
                    enabled=True,
                    cache_results=True,
                    generated_cache_path=cache_path,
                ),
                client=FakeClient([api_payload()]),
            )

            self.assertTrue(result.resources[0].resolved)
            self.assertIn("identity_cache_invalid_json", {warning.code for warning in result.warnings})
            cache_json = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(cache_json["records"][0]["civitaiModelVersionId"], 20)

    def test_api_base_url_must_be_https(self) -> None:
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(enabled=True, base_url="http://example.test/api/v1"),
        )

        self.assertIn("civitai_api_base_url_rejected", {error.code for error in result.errors})
        self.assertFalse(result.resources[0].resolved)

    def test_api_response_matching_version_without_matching_file_hash_is_rejected(self) -> None:
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(auto_v2=None),),
            settings=CivitaiLookupSettings(enabled=True),
            client=FakeClient([api_payload(file_hashes={"SHA256": SHA_B})]),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("civitai_api_hash_mismatch", {warning.code for warning in result.warnings})

    def test_suspicious_api_strings_are_metadata_only_and_redacted(self) -> None:
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(enabled=True),
            client=FakeClient(
                [
                    api_payload(
                        extra={
                            "model": {
                                "id": 10,
                                "name": rf"$(calc) C:\Private\Local\secret.safetensors token={SENSITIVE}",
                                "type": "Checkpoint",
                            },
                            "url": rf"https://example.test/models/10?token={SENSITIVE}",
                        }
                    )
                ]
            ),
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
        text = to_json_text(manifest)

        self.assertIn("$(calc)", text)
        self.assertNotIn(r"C:\Private\Local", text)
        self.assertNotIn(SENSITIVE, text)
        self.assertIn("<redacted_secret>", text)

    def test_sidecar_contains_no_absolute_local_paths_or_token_like_values(self) -> None:
        payload = build_sidecar_payload(
            image={"filename": "image.png", "subfolder": "", "type": "output"},
            options=MetadataOptions(
                strict_mode=False,
                include_workflow=True,
                include_civitai_manifest=True,
                write_sidecar_json=True,
            ),
            prompt={"text": rf"C:\Private\Local\prompt.txt apiToken={SENSITIVE}"},
            extra_pnginfo={"workflow": {"path": "/private/local/workflow.json"}},
            civitai_manifest=None,
            validation=ValidationResult(),
        )
        text = to_json_text(payload)

        self.assertNotIn(r"C:\Private\Local", text)
        self.assertNotIn("/private/local", text)
        self.assertNotIn(SENSITIVE, text)

    def test_full_save_with_lookup_disabled_makes_no_http_call(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            self._run_mocked_save(
                tmp,
                enable_civitai_lookup=False,
                transport_calls=calls,
            )

        self.assertEqual(calls, [])

    def test_full_save_with_lookup_enabled_sends_only_hash_values(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            self._run_mocked_save(
                tmp,
                enable_civitai_lookup=True,
                transport_calls=calls,
            )

        self.assertEqual(len(calls), 1)
        self.assertIn(SHA_A, calls[0])
        self.assertNotIn("prompt", calls[0].lower())
        self.assertNotIn("workflow", calls[0].lower())
        self.assertNotIn("base.safetensors", calls[0])
        self.assertNotIn(str(tmp), calls[0])

    def test_end_to_end_resource_consistency_after_api_lookup(self) -> None:
        result = resolve_resources_with_civitai_api(
            resources=(hashed_resource(),),
            settings=CivitaiLookupSettings(enabled=True),
            client=FakeClient([api_payload()]),
        )
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model_hash=AUTO_A),
            resources=result.resources,
            hashes=HashMetadata(additional={"model": AUTO_A}),
        )
        manifest = build_civitai_manifest(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model_hash=AUTO_A),
            resources=result.resources,
            unresolved_resources=result.unresolved_resources,
            hashes=HashMetadata(additional={"model": AUTO_A}),
            validation=ValidationResult(warnings=result.warnings),
            include_workflow=False,
        )
        manifest_json = json.loads(to_json_text(manifest))

        self.assertIn('"urn":"urn:air:sdxl:checkpoint:civitai:10@20"', parameters)
        self.assertEqual(manifest_json["resources"][0]["rawAir"], "urn:air:sdxl:checkpoint:civitai:10@20")
        self.assertEqual(manifest_json["unresolvedResources"], [])
        self.assertEqual(manifest_json["hashes"]["model"], AUTO_A)

    def _run_mocked_save(
        self,
        tmp: str,
        *,
        enable_civitai_lookup: bool,
        transport_calls: list[str],
    ) -> None:
        output_dir = Path(tmp) / "output"
        output_dir.mkdir()
        resource = hashed_resource()
        scan = WorkflowScanResult(
            prompt=PromptMetadata(positive="test prompt"),
            generation=GenerationSettings(model="base.safetensors", width=1, height=1),
            resources=(resource,),
            unresolved_resources=(),
            warnings=(),
            generator=GeneratorMetadata(version="test"),
        )
        hash_result = ResourceHashingResult(
            resources=(resource,),
            unresolved_resources=(),
            hashes=HashMetadata(additional={"model": AUTO_A}),
            generation=GenerationSettings(model="base.safetensors", model_hash=AUTO_A, width=1, height=1),
            warnings=(),
        )
        identity_result = apply_identity_cache(resources=(resource,), identity_cache=IdentityCache.empty())

        def fake_get(*args: Any, **_: Any) -> CivitaiHttpResponse:
            url = str(args[-1])
            transport_calls.append(url)
            return CivitaiHttpResponse(status=200, body=json.dumps(api_payload()).encode("utf-8"))

        with (
            mock.patch.object(nodes, "_get_comfy_output_directory", return_value=output_dir),
            mock.patch.object(nodes, "_get_save_image_path", return_value=(str(output_dir), "image", 1, "", "image")),
            mock.patch.object(nodes, "_tensor_to_pil_image", return_value=FakePilImage()),
            mock.patch.object(nodes, "build_pnginfo", return_value=None),
            mock.patch.object(nodes, "scan_workflow_graph", return_value=scan),
            mock.patch.object(nodes, "attach_local_hashes", return_value=hash_result),
            mock.patch.object(nodes, "apply_identity_cache", return_value=identity_result),
            mock.patch("save_node.civitai.lookup.StandardLibraryCivitaiTransport.get", side_effect=fake_get),
        ):
            nodes.SaveImageWithCivitaiMetadata().save_images(
                [FakeTensor()],
                filename_prefix="safe",
                write_sidecar_json=True,
                include_workflow=True,
                include_civitai_manifest=True,
                enable_civitai_lookup=enable_civitai_lookup,
                prompt={"1": {"class_type": "KSampler", "inputs": {}}},
                extra_pnginfo={"workflow": {"nodes": []}},
            )


class FakeClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, Any]] = []

    def lookup_by_hash(
        self,
        *,
        hash_value: str,
        hash_algorithm: str,
        resource: ModelResourceMetadata,
        timeout_seconds: float,
        field: str,
    ):
        from save_node.civitai.lookup import CivitaiApiClient

        payload = self.payloads.pop(0)
        transport = InlineTransport(payload)
        client = CivitaiApiClient(base_url="https://example.test/api/v1", transport=transport)
        result = client.lookup_by_hash(
            hash_value=hash_value,
            hash_algorithm=hash_algorithm,
            resource=resource,
            timeout_seconds=timeout_seconds,
            field=field,
        )
        self.calls.extend(transport.calls)
        return result


class InlineTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        *,
        timeout_seconds: float,
        headers: Mapping[str, str],
        max_response_bytes: int,
    ) -> CivitaiHttpResponse:
        self.calls.append({"url": url, "headers": dict(headers)})
        return CivitaiHttpResponse(status=200, body=json.dumps(self.payload).encode("utf-8"))


class FakeTensor:
    shape = (1, 1, 3)


class FakePilImage:
    def save(self, path: Path, **_: Any) -> None:
        Path(path).write_bytes(b"fake png")


def hashed_resource(*, auto_v2: str | None = AUTO_A) -> ResolvedResource:
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role="checkpoint",
            type="checkpoint",
            node_id="1",
            node_class_type="CheckpointLoaderSimple",
            name="base.safetensors",
            selected_value="base.safetensors",
            filename="base.safetensors",
            local_path_basename="base.safetensors",
            hashes=HashMetadata(sha256=SHA_A, auto_v2=auto_v2),
            hash_source="local_file",
            hash_status="hashed",
        ),
        resolved=False,
        unresolved_reason=HASHED_BUT_NO_CIVITAI_IDENTITY,
    )


def identity_record(
    air: str,
    *,
    sha256: str = SHA_A,
    model_id: int = 10,
    version_id: int = 20,
) -> dict[str, Any]:
    return {
        "air": air,
        "civitaiModelId": model_id,
        "civitaiModelVersionId": version_id,
        "hashes": {"SHA256": sha256, "AutoV2": AUTO_A},
    }


def api_payload(
    *,
    file_hashes: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": 20,
        "modelId": 10,
        "name": "Mock Version",
        "baseModel": "SDXL 1.0",
        "trainedWords": ["mocktrigger"],
        "model": {"id": 10, "name": "Mock Model", "type": "Checkpoint"},
        "files": [
            {
                "name": r"C:\Private\Local\base.safetensors",
                "hashes": file_hashes or {"SHA256": SHA_A, "AutoV2": AUTO_A},
            }
        ],
    }
    if extra:
        payload.update(extra)
    return payload


if __name__ == "__main__":
    unittest.main()
