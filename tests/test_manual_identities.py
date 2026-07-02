from __future__ import annotations

import json
import unittest

from save_node.civitai.air import parse_air
from save_node.civitai.identity_cache import parse_identity_cache
from save_node.civitai.identity_resolution import apply_identity_cache
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
    ValidationResult,
)
from save_node.metadata.serialize import to_json_text

SHA_A = "a" * 64
SHA_B = "b" * 64
AUTO_A = "09d005300d"
AUTO_B = "1234567890"
PINNED_AIR = "urn:air:flux2:checkpoint:civitai:2432159@2734704"


class ManualResourceIdentityTests(unittest.TestCase):
    def test_preferred_primary_model_air_empty_preserves_resources(self) -> None:
        resource = hashed_resource(primary=True)

        result = apply_preferred_primary_model_air(
            resources=(resource,),
            preferred_primary_model_air="",
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertEqual(result.resources[0].resource.air, None)

    def test_preferred_primary_model_air_resolves_active_primary_model(self) -> None:
        primary = hashed_resource(primary=True)
        secondary = hashed_resource(name="other.gguf", primary=False)

        result = apply_preferred_primary_model_air(
            resources=(secondary, primary),
            preferred_primary_model_air=PINNED_AIR,
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertTrue(result.resources[1].resolved)
        self.assertEqual(result.resources[1].resource.air.canonical, PINNED_AIR)
        self.assertEqual(result.resources[1].resource.metadata["identitySource"], PREFERRED_PRIMARY_MODEL_AIR_SOURCE)
        self.assertEqual(result.resources[1].resource.metadata["confidence"], "user_pinned")
        self.assertTrue(result.resources[1].resource.metadata["pinned"])

    def test_preferred_primary_model_civitai_url_records_partial_identity(self) -> None:
        result = apply_preferred_primary_model_air(
            resources=(hashed_resource(primary=True),),
            preferred_primary_model_air="https://civitai.com/models/2432159?modelVersionId=2734704",
        )

        metadata = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertIsNone(metadata.air)
        self.assertEqual(metadata.civitai_model_id, 2432159)
        self.assertEqual(metadata.civitai_model_version_id, 2734704)
        self.assertEqual(metadata.metadata["identitySource"], PREFERRED_PRIMARY_MODEL_AIR_SOURCE)
        self.assertTrue(metadata.metadata["identityIncomplete"])
        self.assertIn("preferred_primary_model_identity_incomplete", {warning.code for warning in result.warnings})

    def test_preferred_primary_model_civitai_red_url_is_parse_only_alias(self) -> None:
        result = apply_preferred_primary_model_air(
            resources=(hashed_resource(primary=True),),
            preferred_primary_model_air="https://civitai.red/models/2432159?modelVersionId=2734704",
        )

        metadata = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(metadata.civitai_model_id, 2432159)
        self.assertEqual(metadata.civitai_model_version_id, 2734704)
        self.assertIsNone(metadata.air)

    def test_preferred_primary_model_url_without_version_warns_without_guessing(self) -> None:
        result = apply_preferred_primary_model_air(
            resources=(hashed_resource(primary=True),),
            preferred_primary_model_air="https://civitai.com/models/2432159",
        )

        metadata = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(metadata.civitai_model_id, 2432159)
        self.assertIsNone(metadata.civitai_model_version_id)
        self.assertIn(
            "preferred_primary_model_url_missing_model_version_id", {warning.code for warning in result.warnings}
        )

    def test_preferred_primary_model_plain_model_version_id_records_partial_identity(self) -> None:
        result = apply_preferred_primary_model_air(
            resources=(hashed_resource(primary=True),),
            preferred_primary_model_air="2734704",
        )

        metadata = result.resources[0].resource
        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(metadata.civitai_model_version_id, 2734704)
        self.assertIsNone(metadata.air)
        self.assertTrue(metadata.metadata["identityIncomplete"])

    def test_preferred_primary_model_air_emits_civitai_resources(self) -> None:
        result = apply_preferred_primary_model_air(
            resources=(hashed_resource(primary=True),),
            preferred_primary_model_air=PINNED_AIR,
        )

        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model="flux2-dev-Q8_0.gguf", model_hash=AUTO_A),
            resources=result.resources,
            hashes=HashMetadata(additional={"model": AUTO_A}),
        )

        self.assertIn('"air":"urn:air:flux2:checkpoint:civitai:2432159@2734704"', parameters)
        self.assertIn('"modelVersionId":2734704', parameters)
        self.assertIn('"type":"checkpoint"', parameters)

    def test_preferred_primary_model_url_emits_partial_civitai_resource_with_safe_type(self) -> None:
        result = apply_preferred_primary_model_air(
            resources=(hashed_resource(primary=True),),
            preferred_primary_model_air="https://civitai.com/models/2432159?modelVersionId=2734704",
        )

        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model="flux2-dev-Q8_0.gguf", model_hash=AUTO_A),
            resources=result.resources,
            hashes=HashMetadata(additional={"model": AUTO_A}),
        )

        self.assertIn("Civitai resources:", parameters)
        self.assertIn('"type":"checkpoint"', parameters)
        self.assertIn('"modelId":2432159', parameters)
        self.assertIn('"modelVersionId":2734704', parameters)
        self.assertNotIn('"type":"diffusion_model"', parameters)
        self.assertNotIn('"air":', parameters)
        self.assertTrue(result.resources[0].resource.metadata["identityIncomplete"])

    def test_partial_unknown_type_is_not_emitted_as_a1111_civitai_resource(self) -> None:
        resource = ResolvedResource(
            resource=ModelResourceMetadata(
                role="utility",
                type="mystery",
                name="unknown.bin",
                civitai_model_version_id=123,
                metadata={"identityIncomplete": True},
            ),
            resolved=True,
        )

        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(steps=1),
            resources=(resource,),
        )

        self.assertNotIn("Civitai resources:", parameters)

    def test_preferred_primary_model_air_malformed_warns_without_resolving(self) -> None:
        result = apply_preferred_primary_model_air(
            resources=(hashed_resource(primary=True),),
            preferred_primary_model_air="not-air",
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("preferred_primary_model_air_malformed", {warning.code for warning in result.warnings})

    def test_preferred_primary_model_air_is_not_overwritten_by_manual_json(self) -> None:
        preferred = apply_preferred_primary_model_air(
            resources=(hashed_resource(primary=True),),
            preferred_primary_model_air=PINNED_AIR,
        )

        result = apply_manual_resource_identities(
            resources=preferred.resources,
            manual_resource_identities_json=json.dumps(
                [
                    manual_record(
                        air="urn:air:flux2:checkpoint:civitai:2167454@2442756",
                        model_id=2167454,
                        version_id=2442756,
                    )
                ]
            ),
        )

        self.assertEqual(result.resources[0].resource.air.canonical, PINNED_AIR)
        self.assertEqual(result.resources[0].resource.metadata["identitySource"], PREFERRED_PRIMARY_MODEL_AIR_SOURCE)

    def test_manual_pinned_identity_resolves_by_hash(self) -> None:
        result = apply_manual_resource_identities(
            resources=(hashed_resource(),),
            manual_resource_identities_json=manual_json(),
        )

        resource = result.resources[0]
        self.assertTrue(resource.resolved)
        self.assertEqual(resource.resource.air.canonical, PINNED_AIR)
        self.assertEqual(resource.resource.civitai_model_id, 2432159)
        self.assertEqual(resource.resource.civitai_model_version_id, 2734704)
        self.assertEqual(resource.resource.resolution_source, MANUAL_PINNED_IDENTITY_SOURCE)
        self.assertEqual(resource.resource.metadata["identitySource"], MANUAL_PINNED_IDENTITY_SOURCE)
        self.assertEqual(resource.resource.metadata["confidence"], "user_pinned")
        self.assertEqual(resource.resource.metadata["lookupStatus"], MANUAL_PINNED_LOOKUP_STATUS)
        self.assertEqual(result.unresolved_resources, ())

    def test_a1111_parameters_use_manual_pinned_air(self) -> None:
        result = apply_manual_resource_identities(
            resources=(hashed_resource(),),
            manual_resource_identities_json=manual_json(),
        )

        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(model="flux2-dev-Q8_0.gguf", model_hash=AUTO_A),
            resources=result.resources,
            hashes=HashMetadata(additional={"model": AUTO_A}),
        )

        self.assertIn('"air":"urn:air:flux2:checkpoint:civitai:2432159@2734704"', parameters)
        self.assertIn('"urn":"urn:air:flux2:checkpoint:civitai:2432159@2734704"', parameters)
        self.assertIn('"modelId":2432159', parameters)
        self.assertIn('"modelVersionId":2734704', parameters)

    def test_manifest_promotes_manual_identity_fields(self) -> None:
        result = apply_manual_resource_identities(
            resources=(hashed_resource(),),
            manual_resource_identities_json=manual_json(),
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
        manifest_json = json.loads(to_json_text(manifest))
        resource_json = manifest_json["resources"][0]

        self.assertEqual(resource_json["air"]["canonicalAir"], PINNED_AIR)
        self.assertEqual(resource_json["urn"], PINNED_AIR)
        self.assertEqual(resource_json["modelId"], 2432159)
        self.assertEqual(resource_json["modelVersionId"], 2734704)
        self.assertEqual(resource_json["identitySource"], MANUAL_PINNED_IDENTITY_SOURCE)
        self.assertEqual(resource_json["confidence"], "user_pinned")
        self.assertTrue(resource_json["pinned"])

    def test_malformed_manual_json_warns_without_changing_resources(self) -> None:
        result = apply_manual_resource_identities(
            resources=(hashed_resource(),),
            manual_resource_identities_json="{bad json",
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("manual_identity_invalid_json", {warning.code for warning in result.warnings})

    def test_manual_identity_can_match_by_name_when_resource_has_no_hash(self) -> None:
        resource = hashed_resource(sha256=None, auto_v2=None)

        result = apply_manual_resource_identities(
            resources=(resource,),
            manual_resource_identities_json=manual_json(hashes=False),
        )

        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(result.resources[0].resource.air.canonical, PINNED_AIR)

    def test_manual_identity_hash_conflict_does_not_fall_back_to_name(self) -> None:
        result = apply_manual_resource_identities(
            resources=(hashed_resource(sha256=SHA_B, auto_v2=AUTO_B),),
            manual_resource_identities_json=manual_json(),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertEqual(result.unresolved_resources[0].reason, HASHED_BUT_NO_CIVITAI_IDENTITY)

    def test_equally_strong_manual_conflict_warns_without_resolving(self) -> None:
        records = [
            manual_record(air=PINNED_AIR, model_id=2432159, version_id=2734704),
            manual_record(
                air="urn:air:flux2:checkpoint:civitai:2167454@2442756",
                model_id=2167454,
                version_id=2442756,
            ),
        ]

        result = apply_manual_resource_identities(
            resources=(hashed_resource(),),
            manual_resource_identities_json=json.dumps(records),
        )

        self.assertFalse(result.resources[0].resolved)
        self.assertIn("manual_identity_conflict", {warning.code for warning in result.warnings})

    def test_existing_identity_is_not_overwritten_by_manual_input(self) -> None:
        explicit_air, warnings = parse_air("urn:air:flux2:checkpoint:civitai:111@222")
        self.assertEqual(warnings, ())
        resource = hashed_resource()
        resource = ResolvedResource(
            resource=ModelResourceMetadata(
                **{
                    **resource.resource.__dict__,
                    "air": explicit_air,
                    "civitai_model_id": 111,
                    "civitai_model_version_id": 222,
                    "resolution_source": "explicit_workflow",
                }
            ),
            resolved=True,
        )

        result = apply_manual_resource_identities(
            resources=(resource,),
            manual_resource_identities_json=manual_json(),
        )

        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(result.resources[0].resource.air.canonical, "urn:air:flux2:checkpoint:civitai:111@222")
        self.assertEqual(result.resources[0].resource.resolution_source, "explicit_workflow")

    def test_manual_pinned_identity_is_not_overwritten_by_local_cache(self) -> None:
        manual_result = apply_manual_resource_identities(
            resources=(hashed_resource(),),
            manual_resource_identities_json=manual_json(),
        )
        cache_result = parse_identity_cache(
            {
                "records": [
                    {
                        "air": "urn:air:flux2:checkpoint:civitai:2167454@2442756",
                        "modelId": 2167454,
                        "modelVersionId": 2442756,
                        "hashes": {"SHA256": SHA_A, "AutoV2": AUTO_A},
                    }
                ]
            }
        )

        result = apply_identity_cache(resources=manual_result.resources, identity_cache=cache_result.cache)

        self.assertEqual(result.resources[0].resource.air.canonical, PINNED_AIR)
        self.assertEqual(result.resources[0].resource.resolution_source, MANUAL_PINNED_IDENTITY_SOURCE)


def hashed_resource(
    *,
    sha256: str | None = SHA_A,
    auto_v2: str | None = AUTO_A,
    name: str = "flux2-dev-Q8_0.gguf",
    primary: bool = False,
) -> ResolvedResource:
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role="base_model",
            type="diffusion_model",
            node_id="1",
            node_class_type="UnetLoaderGGUF",
            name=name,
            selected_value=f"diffusion_models/{name}",
            filename=name,
            local_path_basename=name,
            hashes=HashMetadata(sha256=sha256, auto_v2=auto_v2),
            hash_status="hashed" if sha256 or auto_v2 else "not_hashed",
            metadata={"primaryModel": True} if primary else {},
        ),
        resolved=False,
        unresolved_reason=HASHED_BUT_NO_CIVITAI_IDENTITY,
    )


def manual_json(*, hashes: bool = True) -> str:
    return json.dumps([manual_record(hashes=hashes)])


def manual_record(
    *,
    air: str = PINNED_AIR,
    model_id: int = 2432159,
    version_id: int = 2734704,
    hashes: bool = True,
) -> dict[str, object]:
    match: dict[str, object] = {
        "name": "flux2-dev-Q8_0.gguf",
        "role": "base_model",
        "type": "diffusion_model",
    }
    if hashes:
        match["SHA256"] = SHA_A
        match["AutoV2"] = AUTO_A
    return {
        "match": match,
        "air": air,
        "modelId": model_id,
        "modelVersionId": version_id,
        "pinned": True,
        "confidence": "user_pinned",
        "note": "Prefer trusted listing",
    }


if __name__ == "__main__":
    unittest.main()
