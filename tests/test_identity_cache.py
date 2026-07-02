from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

from save_node.civitai.identity_cache import (
    IdentityCache,
    load_identity_cache,
    parse_identity_cache,
)
from save_node.civitai.identity_resolution import apply_identity_cache
from save_node.civitai.manifest import build_civitai_manifest
from save_node.hashing.resource_identity import HASHED_BUT_NO_CIVITAI_IDENTITY
from save_node.io.sidecar import build_sidecar_payload
from save_node.metadata.a1111 import build_a1111_parameters
from save_node.metadata.schema import (
    GenerationSettings,
    HashMetadata,
    MetadataOptions,
    ModelResourceMetadata,
    PromptMetadata,
    ResolvedResource,
)
from save_node.metadata.serialize import to_json_text
from save_node.metadata.validate import validate_metadata


SHA_A = "a" * 64
SHA_B = "b" * 64
AUTO_A = "1111111111"
AUTO_B = "2222222222"


def basename(value: str) -> str:
    windows_name = PureWindowsPath(value).name
    posix_name = PurePosixPath(windows_name).name
    return posix_name or windows_name


def hashed_resource(
    *,
    role: str = "checkpoint",
    name: str = "base.safetensors",
    sha256: str | None = SHA_A,
    auto_v2: str | None = AUTO_A,
    strength_model: float | None = None,
    strength_clip: float | None = None,
) -> ResolvedResource:
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role=role,
            type=role,
            node_id="1",
            node_class_type="TestLoader",
            name=basename(name),
            selected_value=name,
            filename=basename(name),
            local_path_basename=basename(name),
            hashes=HashMetadata(sha256=sha256, auto_v2=auto_v2),
            hash_source="local_file",
            hash_status="hashed",
            strength=strength_model,
            strength_model=strength_model,
            strength_clip=strength_clip,
        ),
        resolved=False,
        unresolved_reason=HASHED_BUT_NO_CIVITAI_IDENTITY,
    )


def mapping_record(
    *,
    air: str = "urn:air:sdxl:checkpoint:civitai:10@20",
    sha256: str | None = SHA_A,
    auto_v2: str | None = AUTO_A,
    resource_type: str = "checkpoint",
    model_id: int = 10,
    version_id: int = 20,
    pinned: bool = False,
) -> dict:
    hashes: dict[str, str] = {}
    if sha256 is not None:
        hashes["SHA256"] = sha256
    if auto_v2 is not None:
        hashes["AutoV2"] = auto_v2
    record = {
        "air": air,
        "civitaiModelId": model_id,
        "civitaiModelVersionId": version_id,
        "modelName": "Mapped Model",
        "modelVersionName": "Mapped Version",
        "resourceType": resource_type,
        "baseModel": "SDXL",
        "sourceUrl": "https://example.test/models/10",
        "triggerWords": ["mapped"],
        "license": "manual note",
        "usageNotes": "offline test fixture",
        "hashes": hashes,
    }
    if pinned:
        record["pinned"] = True
        record["confidence"] = "user_pinned"
    return record


class IdentityCacheTests(unittest.TestCase):
    def test_loads_valid_mapping_by_sha256(self) -> None:
        parsed = parse_identity_cache({"records": [mapping_record()]})
        record = parsed.cache.lookup(HashMetadata(sha256=SHA_A, auto_v2="not-used"))

        self.assertEqual(parsed.errors, ())
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.civitai_model_version_id, 20)

    def test_loads_valid_mapping_by_autov2(self) -> None:
        parsed = parse_identity_cache({"records": [mapping_record(sha256=None, auto_v2=AUTO_A)]})
        record = parsed.cache.lookup(HashMetadata(auto_v2=AUTO_A))

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.air.raw, "urn:air:sdxl:checkpoint:civitai:10@20")

    def test_sha256_is_preferred_over_autov2(self) -> None:
        parsed = parse_identity_cache(
            {
                "records": [
                    mapping_record(air="urn:air:sdxl:checkpoint:civitai:10@20", sha256=SHA_A, auto_v2=AUTO_A),
                    mapping_record(
                        air="urn:air:sdxl:checkpoint:civitai:30@40",
                        sha256=SHA_B,
                        auto_v2=AUTO_A,
                        model_id=30,
                        version_id=40,
                    ),
                ]
            }
        )
        record = parsed.cache.lookup(HashMetadata(sha256=SHA_A, auto_v2=AUTO_A))

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.civitai_model_version_id, 20)

    def test_filename_only_mapping_is_rejected(self) -> None:
        parsed = parse_identity_cache(
            {"records": [{"filename": "base.safetensors", "air": "urn:air:sdxl:checkpoint:civitai:10@20"}]}
        )

        self.assertIn("identity_record_filename_only", {error.code for error in parsed.errors})
        self.assertEqual(parsed.cache.records, ())

    def test_malformed_air_mapping_rejected_with_warning(self) -> None:
        parsed = parse_identity_cache({"records": [mapping_record(air="not-air", sha256=SHA_A, auto_v2=None)]})

        self.assertIn("identity_record_malformed_air", {warning.code for warning in parsed.warnings})
        self.assertEqual(parsed.cache.records, ())

    def test_model_version_conflict_is_rejected(self) -> None:
        parsed = parse_identity_cache(
            {"records": [mapping_record(air="urn:air:sdxl:checkpoint:civitai:10@20", version_id=99)]}
        )

        self.assertIn("identity_record_model_version_conflict", {error.code for error in parsed.errors})
        self.assertEqual(parsed.cache.records, ())

    def test_resource_type_conflict_warns(self) -> None:
        parsed = parse_identity_cache(
            {"records": [mapping_record(air="urn:air:sdxl:lora:civitai:10@20", resource_type="checkpoint")]}
        )

        self.assertIn("identity_record_resource_type_conflict", {warning.code for warning in parsed.warnings})
        self.assertEqual(len(parsed.cache.records), 1)

    def test_resolved_checkpoint_gets_air_and_civitai_ids(self) -> None:
        parsed = parse_identity_cache({"records": [mapping_record()]})
        result = apply_identity_cache(resources=(hashed_resource(),), identity_cache=parsed.cache)

        resource = result.resources[0]
        self.assertTrue(resource.resolved)
        self.assertEqual(resource.resource.air.raw, "urn:air:sdxl:checkpoint:civitai:10@20")
        self.assertEqual(resource.resource.civitai_model_id, 10)
        self.assertEqual(resource.resource.civitai_model_version_id, 20)
        self.assertEqual(resource.resource.resolution_source, "local_identity_cache")
        self.assertEqual(resource.resource.metadata["lookupStatus"], "resolved_by_cache")
        manifest = build_civitai_manifest(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(),
            resources=result.resources,
            unresolved_resources=result.unresolved_resources,
            hashes=HashMetadata(),
            validation=validate_metadata(
                filename_prefix="ok",
                prompt_metadata=PromptMetadata(positive="test"),
                generation=GenerationSettings(),
                resources=result.resources,
                unresolved_resources=result.unresolved_resources,
                prompt={},
                extra_pnginfo={},
                include_workflow=False,
                include_civitai_manifest=True,
            ),
            include_workflow=False,
        )
        manifest_json = json.loads(to_json_text(manifest))
        self.assertEqual(manifest_json["resources"][0]["lookupStatus"], "resolved_by_cache")

    def test_user_pinned_cache_sets_identity_source(self) -> None:
        parsed = parse_identity_cache({"records": [mapping_record(pinned=True)]})
        result = apply_identity_cache(resources=(hashed_resource(),), identity_cache=parsed.cache)

        metadata = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(metadata.resolution_source, "user_pinned_cache")
        self.assertEqual(metadata.metadata["lookupStatus"], "resolved_by_cache")
        self.assertEqual(metadata.metadata["identitySource"], "user_pinned_cache")
        self.assertEqual(metadata.metadata["confidence"], "user_pinned")
        self.assertTrue(metadata.metadata["pinned"])

    def test_local_cache_air_with_file_id_resolves_resource(self) -> None:
        parsed = parse_identity_cache(
            {
                "records": [
                    mapping_record(
                        air="urn:air:sdxl:checkpoint:civitai:10@20+333.safetensor",
                    )
                ]
            }
        )
        result = apply_identity_cache(resources=(hashed_resource(),), identity_cache=parsed.cache)

        air = result.resources[0].resource.air
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.canonical, "urn:air:sdxl:checkpoint:civitai:10@20+333.safetensor")
        self.assertEqual(air.file_id, "333")
        self.assertEqual(air.format, "safetensor")

    def test_resolved_lora_gets_identity_and_preserves_strength(self) -> None:
        parsed = parse_identity_cache(
            {
                "records": [
                    mapping_record(
                        air="urn:air:sdxl:lora:civitai:11@21",
                        resource_type="lora",
                        model_id=11,
                        version_id=21,
                    )
                ]
            }
        )
        result = apply_identity_cache(
            resources=(
                hashed_resource(
                    role="lora",
                    name="loras/detail.safetensors",
                    strength_model=0.8,
                    strength_clip=0.6,
                ),
            ),
            identity_cache=parsed.cache,
        )

        resource = result.resources[0]
        self.assertTrue(resource.resolved)
        self.assertEqual(resource.resource.air.type, "lora")
        self.assertEqual(resource.resource.strength_model, 0.8)
        self.assertEqual(resource.resource.strength_clip, 0.6)

    def test_unresolved_hashed_resource_remains_unresolved(self) -> None:
        result = apply_identity_cache(resources=(hashed_resource(),), identity_cache=IdentityCache.empty())

        self.assertFalse(result.resources[0].resolved)
        self.assertEqual(result.unresolved_resources[0].reason, HASHED_BUT_NO_CIVITAI_IDENTITY)

    def test_resolved_resource_removed_from_unresolved_resources(self) -> None:
        parsed = parse_identity_cache({"records": [mapping_record()]})
        result = apply_identity_cache(resources=(hashed_resource(),), identity_cache=parsed.cache)

        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(result.unresolved_resources, ())

    def test_a1111_civitai_resources_include_full_air(self) -> None:
        parsed = parse_identity_cache({"records": [mapping_record()]})
        result = apply_identity_cache(resources=(hashed_resource(),), identity_cache=parsed.cache)

        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model="base.safetensors", model_hash=AUTO_A),
            resources=result.resources,
            hashes=HashMetadata(additional={"Model": AUTO_A, "model": AUTO_A}),
        )

        self.assertIn('"urn":"urn:air:sdxl:checkpoint:civitai:10@20"', parameters)
        self.assertIn('"modelVersionId":20', parameters)

    def test_a1111_hashes_include_lowercase_model_key(self) -> None:
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model_hash=AUTO_A),
            hashes=HashMetadata(additional={"Model": AUTO_A, "model": AUTO_A}),
        )

        self.assertIn('"model":"1111111111"', parameters)

    def test_manifest_contains_parsed_air_object(self) -> None:
        parsed = parse_identity_cache({"records": [mapping_record()]})
        result = apply_identity_cache(resources=(hashed_resource(),), identity_cache=parsed.cache)
        validation = validate_metadata_for_identity(result)
        manifest = build_civitai_manifest(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(),
            resources=result.resources,
            unresolved_resources=result.unresolved_resources,
            hashes=HashMetadata(additional={"Model": AUTO_A}),
            validation=validation,
            include_workflow=False,
            identity_cache=result.identity_cache,
        )
        manifest_json = json.loads(to_json_text(manifest))

        self.assertEqual(manifest_json["resources"][0]["air"]["modelVersionId"], 20)
        self.assertEqual(manifest_json["resources"][0]["rawAir"], "urn:air:sdxl:checkpoint:civitai:10@20")

    def test_identity_cache_serialization_is_deterministic(self) -> None:
        parsed = parse_identity_cache({"records": [mapping_record()]})

        self.assertEqual(to_json_text(parsed.cache.to_json()), to_json_text(parsed.cache.to_json()))
        self.assertIn('"formatVersion":"1"', to_json_text(parsed.cache.to_json()))

    def test_invalid_json_mapping_handled_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "civitai_identity_cache.json"
            path.write_text("{ bad json", encoding="utf-8")

            loaded = load_identity_cache(path, allowed_roots=(root,))

            self.assertIn("identity_cache_invalid_json", {error.code for error in loaded.errors})
            self.assertEqual(loaded.cache.records, ())

    def test_no_absolute_paths_in_identity_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            private_path = str(Path(tmp) / "secret" / "base.safetensors")
            parsed = parse_identity_cache({"records": [mapping_record_with_source_url(private_path)]})
            result = apply_identity_cache(resources=(hashed_resource(name=private_path),), identity_cache=parsed.cache)
            validation = validate_metadata_for_identity(result)
            manifest = build_civitai_manifest(
                prompt=PromptMetadata(positive="test"),
                generation=GenerationSettings(model="base.safetensors"),
                resources=result.resources,
                unresolved_resources=result.unresolved_resources,
                hashes=HashMetadata(additional={"Model": AUTO_A, "model": AUTO_A}),
                validation=validation,
                include_workflow=False,
                identity_cache=result.identity_cache,
            )
            sidecar = build_sidecar_payload(
                image={"filename": "image.png", "subfolder": "", "type": "output"},
                options=MetadataOptions(
                    strict_mode=False,
                    include_workflow=False,
                    include_civitai_manifest=True,
                    write_sidecar_json=True,
                ),
                prompt={},
                extra_pnginfo={},
                civitai_manifest=manifest,
                validation=validation,
            )
            combined = "\n".join(
                [
                    build_a1111_parameters(
                        prompt=PromptMetadata(positive="test"),
                        generation=GenerationSettings(),
                        resources=result.resources,
                        hashes=HashMetadata(additional={"model": AUTO_A}),
                    ),
                    to_json_text(manifest),
                    to_json_text(sidecar),
                ]
            )

            self.assertNotIn(str(tmp), combined)
            self.assertNotIn(private_path, combined)


def validate_metadata_for_identity(result):
    return validate_metadata(
        filename_prefix="ok",
        prompt_metadata=PromptMetadata(positive="test"),
        generation=GenerationSettings(),
        resources=result.resources,
        unresolved_resources=result.unresolved_resources,
        prompt={},
        extra_pnginfo={},
        include_workflow=False,
        include_civitai_manifest=True,
        additional_warnings=result.warnings,
        additional_errors=result.errors,
    )


def mapping_record_with_source_url(source_url: str) -> dict:
    record = mapping_record()
    record["sourceUrl"] = source_url
    return record


if __name__ == "__main__":
    unittest.main()
