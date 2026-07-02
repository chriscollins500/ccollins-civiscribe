from __future__ import annotations

import json
import unittest

from save_node.civitai.air import parse_air
from save_node.civitai.manifest import build_civitai_manifest
from save_node.metadata.schema import (
    GenerationSettings,
    HashMetadata,
    ModelResourceMetadata,
    PromptMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
    ValidationResult,
)
from save_node.metadata.serialize import to_json_text
from save_node.version import __version__
from save_node.metadata.validate import validate_metadata
from save_node.security.redaction import redact_absolute_paths


class MetadataSerializationTests(unittest.TestCase):
    def test_manifest_serializes_as_valid_json(self) -> None:
        air, warnings = parse_air("urn:air:flux2:checkpoint:civitai:2432159@2734704")
        self.assertEqual(warnings, ())
        resource = ResolvedResource(
            ModelResourceMetadata(
                role="checkpoint",
                type="checkpoint",
                name="Flux Test",
                filename=r"C:\private\models\flux.safetensors",
                air=air,
                civitai_model_id=2432159,
                civitai_model_version_id=2734704,
            )
        )
        manifest = build_civitai_manifest(
            prompt=PromptMetadata(positive="貓 in neon", negative="low quality"),
            generation=GenerationSettings(steps=10, seed=22, width=512, height=512),
            resources=(resource,),
            unresolved_resources=(
                UnresolvedResource(reason="file missing", filename=r"C:\private\missing.safetensors"),
            ),
            hashes=HashMetadata(sha256="a" * 64),
            validation=ValidationResult(warnings=(ValidationIssue(code="sample_warning", message="sample"),)),
            include_workflow=True,
        )

        text = to_json_text(manifest, indent=2)
        parsed = json.loads(text)

        self.assertEqual(parsed["schemaName"], "comfyui-civitai-save-node")
        self.assertEqual(parsed["schemaVersion"], __version__)
        self.assertEqual(parsed["generator"]["version"], __version__)
        self.assertEqual(parsed["prompt"]["positive"], "貓 in neon")
        self.assertEqual(parsed["resources"][0]["filename"], "flux.safetensors")
        self.assertEqual(parsed["unresolvedResources"][0]["filename"], "missing.safetensors")
        self.assertNotIn(r"C:\private", text)

    def test_unicode_prompt_serialization_is_utf8_safe(self) -> None:
        text = to_json_text(PromptMetadata(positive="雪の街 and emoji-style text"))

        self.assertIn("雪の街", text)
        self.assertEqual(json.loads(text)["positive"], "雪の街 and emoji-style text")

    def test_redaction_preserves_urls_but_redacts_local_paths(self) -> None:
        redacted = redact_absolute_paths("url https://example.test/models/10 path C:/private/model.safetensors")

        self.assertIn("https://example.test/models/10", redacted)
        self.assertIn("<redacted_path:model.safetensors>", redacted)
        self.assertNotIn("C:/private", redacted)

    def test_json_output_is_deterministic(self) -> None:
        settings = GenerationSettings(
            seed=1,
            extra={"z": 3, "a": 1},
        )

        self.assertEqual(to_json_text(settings), to_json_text(settings))
        self.assertEqual(to_json_text(settings), '{"extra":{"a":1,"z":3},"seed":1}')

    def test_unsupported_objects_are_not_serialized_as_python_repr(self) -> None:
        with self.assertRaises(TypeError):
            to_json_text({"bad": object()})

    def test_validation_warns_without_strict_failure_for_missing_optional_data(self) -> None:
        validation = validate_metadata(
            filename_prefix="ok",
            prompt_metadata=PromptMetadata(),
            generation=GenerationSettings(),
            resources=(),
            unresolved_resources=(),
            prompt=None,
            extra_pnginfo={},
            include_workflow=True,
            include_civitai_manifest=True,
        )

        self.assertFalse(validation.has_errors)
        self.assertIn("a1111_parameters_incomplete", {issue.code for issue in validation.warnings})

    def test_validation_errors_for_serious_schema_issue(self) -> None:
        validation = validate_metadata(
            filename_prefix="",
            prompt_metadata=PromptMetadata(positive="test"),
            generation=GenerationSettings(),
            resources=(),
            unresolved_resources=(),
            prompt={},
            extra_pnginfo={},
            include_workflow=False,
            include_civitai_manifest=True,
        )

        self.assertTrue(validation.has_errors)
        self.assertEqual(validation.errors[0].code, "empty_filename_prefix")

    def test_resource_validation_warnings(self) -> None:
        partial_air, warnings = parse_air("urn:air:flux2:lora:civitai:123")
        self.assertTrue(warnings)
        validation = validate_metadata(
            filename_prefix="ok",
            prompt_metadata=PromptMetadata(positive="test"),
            generation=GenerationSettings(steps=1),
            resources=(
                ResolvedResource(
                    ModelResourceMetadata(
                        role="lora",
                        type="lora",
                        air=partial_air,
                        civitai_model_version_id=22,
                    )
                ),
                ResolvedResource(
                    ModelResourceMetadata(
                        role="lora",
                        type="lora",
                        civitai_model_version_id=33,
                    )
                ),
            ),
            unresolved_resources=(UnresolvedResource(reason="missing file", filename="missing.safetensors"),),
            prompt={},
            extra_pnginfo={},
            include_workflow=False,
            include_civitai_manifest=True,
        )

        codes = {issue.code for issue in validation.warnings}
        self.assertIn("air_without_model_version_id", codes)
        self.assertIn("resource_version_without_air", codes)
        self.assertIn("unresolved_resource", codes)


if __name__ == "__main__":
    unittest.main()
