from __future__ import annotations

import unittest

from save_node.civitai.air import format_air, parse_air


class AIRParserTests(unittest.TestCase):
    def test_parse_full_valid_air(self) -> None:
        raw = "urn:air:flux2:checkpoint:civitai:2432159@2734704"
        air, warnings = parse_air(raw)

        self.assertEqual(warnings, ())
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.raw, raw)
        self.assertEqual(air.scheme, "urn")
        self.assertEqual(air.namespace, "air")
        self.assertEqual(air.ecosystem, "flux2")
        self.assertEqual(air.type, "checkpoint")
        self.assertEqual(air.source, "civitai")
        self.assertEqual(air.model_id, 2432159)
        self.assertEqual(air.model_version_id, 2734704)
        self.assertEqual(format_air(air), raw)

    def test_parse_air_with_optional_layer_and_format(self) -> None:
        raw = "urn:air:sdxl:lora:civitai:10@20:layerA:safetensors"
        air, warnings = parse_air(raw)

        self.assertEqual(warnings, ())
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.layer, "layerA")
        self.assertEqual(air.format, "safetensors")

    def test_parse_air_with_file_id(self) -> None:
        air, warnings = parse_air("urn:air:sdxl:checkpoint:civitai:827184@2514310+2402203")

        self.assertEqual(warnings, ())
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.file_id, "2402203")
        self.assertEqual(air.model_id, 827184)
        self.assertEqual(air.model_version_id, 2514310)

    def test_parse_air_with_file_id_and_format(self) -> None:
        raw = "urn:air:sdxl:checkpoint:civitai:827184@2514310+2402203.safetensor"
        air, warnings = parse_air(raw)

        self.assertEqual(warnings, ())
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.file_id, "2402203")
        self.assertEqual(air.format, "safetensor")
        self.assertEqual(format_air(air), raw)

    def test_parse_air_prefix_normalizes_to_canonical_urn(self) -> None:
        air, warnings = parse_air("air:sdxl:checkpoint:civitai:827184@2514310")

        self.assertEqual(warnings, ())
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.raw, "air:sdxl:checkpoint:civitai:827184@2514310")
        self.assertEqual(air.canonical, "urn:air:sdxl:checkpoint:civitai:827184@2514310")

    def test_parse_bare_air_normalizes_to_canonical_urn(self) -> None:
        air, warnings = parse_air("sdxl:checkpoint:civitai:827184@2514310")

        self.assertEqual(warnings, ())
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(format_air(air), "urn:air:sdxl:checkpoint:civitai:827184@2514310")

    def test_parse_diffusionmodel_and_unet_types(self) -> None:
        diffusion, diffusion_warnings = parse_air("urn:air:boogu:diffusionmodel:civitai:2714299@3049541")
        unet, unet_warnings = parse_air("urn:air:flux2:unet:civitai:1@2")

        self.assertEqual(diffusion_warnings, ())
        self.assertEqual(unet_warnings, ())
        self.assertEqual(diffusion.type if diffusion else None, "diffusionmodel")
        self.assertEqual(unet.type if unet else None, "unet")

    def test_parse_other_upscaler_type(self) -> None:
        air, warnings = parse_air("urn:air:other:upscaler:civitai:147759@164821")

        self.assertEqual(warnings, ())
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.ecosystem, "other")
        self.assertEqual(air.type, "upscaler")

    def test_parse_civitai_r2_source_with_nonnumeric_identity(self) -> None:
        raw = "urn:air:other:other:civitai-r2:civitai-worker-assets@sam_vit_b_01ec64.pth"
        air, warnings = parse_air(raw)

        self.assertEqual(warnings, ())
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.source, "civitai-r2")
        self.assertEqual(air.id, "civitai-worker-assets")
        self.assertEqual(air.version, "sam_vit_b_01ec64")
        self.assertEqual(air.format, "pth")
        self.assertIsNone(air.model_id)
        self.assertIsNone(air.model_version_id)
        self.assertEqual(air.canonical, raw)

    def test_parse_oci_image_air(self) -> None:
        air, warnings = parse_air("urn:air:oci:image:ghcr:civitai/training-toolkit@sha256:abc123")

        self.assertEqual(warnings, ())
        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.ecosystem, "oci")
        self.assertEqual(air.type, "image")
        self.assertEqual(air.source, "ghcr")
        self.assertEqual(air.id, "civitai/training-toolkit")
        self.assertEqual(air.version, "sha256:abc123")
        self.assertIsNone(air.model_id)

    def test_malformed_air_returns_warning_not_exception(self) -> None:
        air, warnings = parse_air("not-an-air")

        self.assertIsNone(air)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].code, "malformed_air")

    def test_incomplete_air_warns_without_guessing_version(self) -> None:
        air, warnings = parse_air("urn:air:flux2:checkpoint:civitai:2432159")

        self.assertIsNotNone(air)
        assert air is not None
        self.assertEqual(air.model_id, 2432159)
        self.assertIsNone(air.model_version_id)
        self.assertEqual(warnings[0].code, "air_missing_model_version_id")


if __name__ == "__main__":
    unittest.main()
