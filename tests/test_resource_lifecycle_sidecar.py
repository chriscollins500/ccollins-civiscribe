from __future__ import annotations

import unittest

from save_node.civitai.air import parse_air
from save_node.io.sidecar import build_resource_lifecycle, build_sidecar_payload
from save_node.metadata.schema import (
    HashMetadata,
    MetadataOptions,
    ModelResourceMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
    ValidationResult,
)
from save_node.metadata.serialize import to_json_text


class ResourceLifecycleSidecarTests(unittest.TestCase):
    def test_sidecar_includes_resource_lifecycle(self) -> None:
        lifecycle = build_resource_lifecycle(
            raw_resources_found=(unresolved_resource("inactive-upscaler.pth"),),
            active_resources=(unresolved_resource("base.safetensors"),),
            normalized_resources=(unresolved_resource("base.safetensors"),),
            final_resources=(
                resolved_resource(),
                unresolved_resource("base.safetensors"),
            ),
            unresolved_resources=(
                UnresolvedResource(
                    reason="hashed_but_no_civitai_identity",
                    name="base.safetensors",
                    lookup_status="skipped_lookup_disabled",
                ),
                UnresolvedResource(
                    reason="hashed_but_no_civitai_identity",
                    role="vae",
                    type="vae",
                    name="ae.safetensors",
                    lookup_status="skipped_lookup_disabled",
                ),
            ),
            final_a1111_parameters="prompt\nNegative prompt:\nSteps: 1",
            lookup_debug_summary=({"filename": "base.safetensors", "lookupStatus": "skipped_lookup_disabled"},),
            warnings=(ValidationIssue(code="safe_warning", message="safe"),),
            metadata_status="partial",
        )
        sidecar = build_sidecar_payload(
            image={"filename": "image.png", "subfolder": "", "type": "output"},
            options=options(),
            prompt={},
            extra_pnginfo={},
            civitai_manifest=None,
            validation=ValidationResult(),
            resource_lifecycle=lifecycle,
        )

        self.assertIn("resourceLifecycle", sidecar)
        self.assertEqual(sidecar["resourceLifecycle"]["metadataStatus"], "partial")
        self.assertEqual(sidecar["resourceLifecycle"]["rawResourcesFound"][0]["name"], "inactive-upscaler.pth")
        self.assertEqual(sidecar["resourceLifecycle"]["activeResources"][0]["name"], "base.safetensors")
        self.assertNotIn("inactive-upscaler.pth", to_json_text(sidecar["resourceLifecycle"]["finalResources"]))
        self.assertEqual(sidecar["resourceLifecycle"]["resolvedResources"][0]["modelVersionId"], 20)
        self.assertEqual(sidecar["resourceLifecycle"]["finalResources"][0]["modelVersionId"], 20)
        self.assertEqual(
            sidecar["resourceLifecycle"]["unresolvedResources"][0]["unresolvedReason"],
            "hashed_but_no_civitai_identity",
        )
        self.assertEqual(sidecar["resourceLifecycle"]["unresolvedResources"][1]["role"], "vae")

    def test_empty_lifecycle_payload_is_normalized(self) -> None:
        sidecar = build_sidecar_payload(
            image={"filename": "image.png", "subfolder": "", "type": "output"},
            options=options(),
            prompt={},
            extra_pnginfo={},
            civitai_manifest=None,
            validation=ValidationResult(),
            resource_lifecycle={},
        )

        lifecycle = sidecar["resourceLifecycle"]
        self.assertEqual(lifecycle["rawResourcesFound"], [])
        self.assertEqual(lifecycle["activeResources"], [])
        self.assertEqual(lifecycle["normalizedResources"], [])
        self.assertEqual(lifecycle["resolvedResources"], [])
        self.assertEqual(lifecycle["unresolvedResources"], [])
        self.assertEqual(lifecycle["finalResources"], [])
        self.assertEqual(lifecycle["metadataStatus"], "partial")

    def test_lifecycle_redacts_absolute_paths(self) -> None:
        lifecycle = build_resource_lifecycle(
            raw_resources_found=(unresolved_resource(r"C:\Users\Chris\models\secret.safetensors"),),
            active_resources=(unresolved_resource(r"C:\Users\Chris\models\secret.safetensors"),),
            normalized_resources=(unresolved_resource(r"C:\Users\Chris\models\secret.safetensors"),),
            final_resources=(unresolved_resource(r"C:\Users\Chris\models\secret.safetensors"),),
            final_a1111_parameters="",
        )

        text = to_json_text(lifecycle)

        self.assertNotIn(r"C:\Users\Chris", text)
        self.assertIn("secret.safetensors", text)


def resolved_resource() -> ResolvedResource:
    air, warnings = parse_air("urn:air:sdxl:checkpoint:civitai:10@20")
    assert warnings == ()
    assert air is not None
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role="checkpoint",
            type="checkpoint",
            name="base.safetensors",
            filename="base.safetensors",
            air=air,
            civitai_model_id=10,
            civitai_model_version_id=20,
            hashes=HashMetadata(auto_v2="1234567890"),
            metadata={"identitySource": "local_cache", "confidence": "high"},
        ),
        resolved=True,
    )


def unresolved_resource(name: str) -> ResolvedResource:
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role="checkpoint",
            type="checkpoint",
            name=name,
            filename=name,
            selected_value=name,
            local_path_basename=name,
            metadata={"lookupStatus": "skipped_lookup_disabled"},
        ),
        resolved=False,
        unresolved_reason="hashed_but_no_civitai_identity",
    )


def options() -> MetadataOptions:
    return MetadataOptions(
        strict_mode=False,
        include_workflow=True,
        include_civitai_manifest=True,
        write_sidecar_json=True,
    )


if __name__ == "__main__":
    unittest.main()
