from __future__ import annotations

import json
import unittest

from save_node.civitai.air import parse_air
from save_node.civitai.identity_cache import IdentityCache, IdentityMappingRecord
from save_node.civitai.identity_resolution import apply_identity_cache
from save_node.civitai.resource_cache_io import RESOURCE_CACHE_FORMAT, export_resource_cache, import_resource_cache
from save_node.hashing.resource_identity import HASHED_BUT_NO_CIVITAI_IDENTITY
from save_node.metadata.schema import HashMetadata, ModelResourceMetadata, ResolvedResource
from save_node.metadata.serialize import to_json_text

SHA_A = "a" * 64
SHA_B = "b" * 64
AUTO_A = "09d005300d"


class ResourceCacheIoTests(unittest.TestCase):
    def test_export_produces_readable_json_without_absolute_paths(self) -> None:
        cache = IdentityCache(records=(record(source_url=r"C:\Users\Chris\secret.safetensors"),))

        payload = export_resource_cache(cache)
        text = to_json_text(payload, indent=2)

        self.assertEqual(payload["format"], RESOURCE_CACHE_FORMAT)
        self.assertIn('"resources"', text)
        self.assertNotIn(r"C:\Users\Chris", text)

    def test_import_accepts_valid_cache(self) -> None:
        payload = export_resource_cache(IdentityCache(records=(record(),)))

        result = import_resource_cache(payload)

        self.assertEqual(result.errors, ())
        self.assertEqual(result.imported_count, 1)
        self.assertEqual(result.cache.records[0].civitai_model_version_id, 2734704)

    def test_import_rejects_malformed_cache_safely(self) -> None:
        result = import_resource_cache({"format": "wrong", "resources": []})

        self.assertIn("resource_cache_format_invalid", {error.code for error in result.errors})
        self.assertEqual(result.cache.records, ())

    def test_import_does_not_overwrite_existing_pinned_conflict(self) -> None:
        existing = IdentityCache(records=(record(pinned=True),))
        incoming = export_resource_cache(
            IdentityCache(
                records=(
                    record(
                        air_text="urn:air:flux2:checkpoint:civitai:2167454@2442756",
                        model_id=2167454,
                        version_id=2442756,
                    ),
                )
            )
        )

        result = import_resource_cache(incoming, existing_cache=existing)

        self.assertEqual(result.imported_count, 0)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(result.cache.records[0].civitai_model_id, 2432159)
        self.assertIn(
            "resource_cache_import_conflict_preserved_existing", {warning.code for warning in result.warnings}
        )

    def test_imported_pinned_entry_resolves_resource(self) -> None:
        payload = export_resource_cache(IdentityCache(records=(record(pinned=True),)))
        imported = import_resource_cache(payload)

        result = apply_identity_cache(resources=(resource(),), identity_cache=imported.cache)

        self.assertTrue(result.resources[0].resolved)
        self.assertEqual(result.resources[0].resource.air.canonical, "urn:air:flux2:checkpoint:civitai:2432159@2734704")
        self.assertEqual(result.resources[0].resource.resolution_source, "user_pinned_cache")

    def test_export_contains_no_prompt_workflow_image_or_token_data(self) -> None:
        payload = export_resource_cache(IdentityCache(records=(record(),)))
        text = json.dumps(payload)

        self.assertNotIn("prompt", text.lower())
        self.assertNotIn("workflow", text.lower())
        self.assertNotIn("image bytes", text.lower())
        self.assertNotIn("token=", text.lower())


def record(
    *,
    air_text: str = "urn:air:flux2:checkpoint:civitai:2432159@2734704",
    model_id: int = 2432159,
    version_id: int = 2734704,
    sha256: str = SHA_A,
    pinned: bool = False,
    source_url: str | None = None,
) -> IdentityMappingRecord:
    air, warnings = parse_air(air_text)
    assert warnings == ()
    assert air is not None
    return IdentityMappingRecord(
        air=air,
        civitai_model_id=model_id,
        civitai_model_version_id=version_id,
        hashes=HashMetadata(sha256=sha256, auto_v2=AUTO_A),
        model_name="Flux.2",
        resource_type="checkpoint",
        source_url=source_url,
        pinned=pinned,
        confidence="user_pinned" if pinned else "high",
    )


def resource() -> ResolvedResource:
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role="base_model",
            type="diffusion_model",
            name="flux2-dev-Q8_0.gguf",
            filename="flux2-dev-Q8_0.gguf",
            hashes=HashMetadata(sha256=SHA_A, auto_v2=AUTO_A),
        ),
        resolved=False,
        unresolved_reason=HASHED_BUT_NO_CIVITAI_IDENTITY,
    )


if __name__ == "__main__":
    unittest.main()
