from __future__ import annotations

import unittest

from save_node.civitai.air import parse_air
from save_node.metadata.a1111 import build_a1111_parameters
from save_node.metadata.schema import (
    GenerationSettings,
    HashMetadata,
    ModelResourceMetadata,
    PromptMetadata,
    ResolvedResource,
)


class A1111ParametersTests(unittest.TestCase):
    def test_formats_positive_negative_and_settings(self) -> None:
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(
                positive="a cinematic cat",
                negative="blurry, low quality",
            ),
            generation=GenerationSettings(
                steps=28,
                sampler="Euler a",
                scheduler="Karras",
                cfg_scale=7.5,
                seed=12345,
                width=1024,
                height=768,
                model="flux-test.safetensors",
                model_hash="abc123",
                vae="ae.safetensors",
                vae_hash="def456",
                clip_skip=2,
                denoising_strength=0.55,
                version="ComfyUI",
            ),
        )

        self.assertTrue(parameters.startswith("a cinematic cat\nNegative prompt: blurry"))
        self.assertIn("Steps: 28", parameters)
        self.assertIn("Sampler: Euler a", parameters)
        self.assertIn("Schedule type: Karras", parameters)
        self.assertIn("CFG scale: 7.5", parameters)
        self.assertIn("Seed: 12345", parameters)
        self.assertIn("Size: 1024x768", parameters)
        self.assertIn("Model: flux-test.safetensors", parameters)
        self.assertIn("Model hash: abc123", parameters)
        self.assertIn("VAE: ae.safetensors", parameters)
        self.assertIn("VAE hash: def456", parameters)
        self.assertIn("Clip skip: 2", parameters)
        self.assertIn("Denoising strength: 0.55", parameters)
        self.assertIn("Version: ComfyUI", parameters)

    def test_missing_optional_fields_are_omitted(self) -> None:
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="only prompt"),
            generation=GenerationSettings(),
        )

        self.assertEqual(parameters, "only prompt")

    def test_empty_negative_prompt_line_is_included_when_settings_exist(self) -> None:
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="only prompt"),
            generation=GenerationSettings(steps=12, width=512, height=768),
        )

        self.assertEqual(
            parameters,
            "only prompt\nNegative prompt:\nSteps: 12, Size: 512x768",
        )

    def test_civitai_resources_are_embedded_in_settings_line(self) -> None:
        air, warnings = parse_air("urn:air:flux2:lora:civitai:2432159@2734704")
        self.assertEqual(warnings, ())
        resource = ResolvedResource(
            ModelResourceMetadata(
                role="lora",
                type="lora",
                name="Detail Booster",
                air=air,
                civitai_model_id=2432159,
                civitai_model_version_id=2734704,
            )
        )

        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(steps=12),
            resources=(resource,),
        )

        self.assertIn("Civitai resources:", parameters)
        self.assertIn('"urn":"urn:air:flux2:lora:civitai:2432159@2734704"', parameters)
        self.assertIn('"air":"urn:air:flux2:lora:civitai:2432159@2734704"', parameters)
        self.assertIn('"modelVersionId":2734704', parameters)

    def test_unresolved_resource_is_not_embedded_as_civitai_resource(self) -> None:
        resource = ResolvedResource(
            ModelResourceMetadata(
                role="lora",
                type="lora",
                name="local-only.safetensors",
                filename="local-only.safetensors",
                selected_value="loras/local-only.safetensors",
            ),
            resolved=False,
            unresolved_reason="hashed_but_no_civitai_identity",
        )

        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(steps=12),
            resources=(resource,),
        )

        self.assertNotIn("Civitai resources:", parameters)
        self.assertNotIn("local-only.safetensors", parameters)

    def test_hashes_are_embedded_in_settings_line(self) -> None:
        parameters = build_a1111_parameters(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(seed=9),
            hashes=HashMetadata(sha256="f" * 64, auto_v2="A1B2C3D4E5"),
        )

        self.assertIn('Hashes: {"AutoV2":"A1B2C3D4E5","SHA256":"', parameters)


if __name__ == "__main__":
    unittest.main()
