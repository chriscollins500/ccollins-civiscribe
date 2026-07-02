from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from save_node.civitai.air import parse_air
from save_node.civitai.manifest import build_civitai_manifest
from save_node.io.sidecar import (
    SIDECAR_FORMAT,
    SIDECAR_SCHEMA_VERSION,
    build_resource_lifecycle,
    build_sidecar_payload,
    write_sidecar_json_file,
)
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
from save_node.version import __version__
from tools.validate_sidecar import validate_sidecar_file


class SidecarFormatTests(unittest.TestCase):
    def test_modern_sidecar_top_level_shape(self) -> None:
        sidecar = sample_sidecar()

        self.assertEqual(sidecar["sidecarFormat"], SIDECAR_FORMAT)
        self.assertEqual(sidecar["sidecarSchemaVersion"], SIDECAR_SCHEMA_VERSION)
        self.assertNotIn("schema_version", sidecar)
        self.assertEqual(sidecar["legacy"]["schema_version"], "phase-1")
        self.assertEqual(
            sidecar["generator"],
            {
                "name": "Save Image with Civitai Metadata",
                "package": "comfyui-civitai-save-node",
                "version": __version__,
            },
        )
        self.assertRegex(sidecar["createdAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_sidecar_image_and_png_summary_are_safe_and_useful(self) -> None:
        sidecar = sample_sidecar()
        chunks = {(chunk["keyword"], chunk["type"]) for chunk in sidecar["pngMetadata"]["chunks"]}

        self.assertEqual(sidecar["image"]["fileName"], "image.png")
        self.assertEqual(sidecar["image"]["format"], "PNG")
        self.assertEqual(sidecar["image"]["width"], 1024)
        self.assertEqual(sidecar["image"]["height"], 768)
        self.assertNotIn("C:", to_json_text(sidecar["image"]))
        self.assertIn(("parameters", "tEXt"), chunks)
        self.assertIn(("Software", "tEXt"), chunks)
        self.assertIn(("prompt", "iTXt"), chunks)
        self.assertIn(("workflow", "iTXt"), chunks)
        self.assertIn(("civitai", "iTXt"), chunks)
        self.assertIn(("UserComment", "eXIf"), chunks)
        self.assertEqual(sidecar["pngMetadata"]["compatibility"]["parametersChunkType"], "tEXt")
        self.assertEqual(sidecar["pngMetadata"]["compatibility"]["civitaiExifUserComment"], "eXIf/UserComment")

    def test_sidecar_png_summary_reflects_exif_minimal_mode(self) -> None:
        sidecar = sample_sidecar(exif_minimal=True)
        chunks = {(chunk["keyword"], chunk["type"]) for chunk in sidecar["pngMetadata"]["chunks"]}

        self.assertEqual(chunks, {("UserComment", "eXIf")})
        self.assertTrue(sidecar["pngMetadata"]["compatibility"]["minimalMode"])

    def test_sidecar_png_summary_omits_exif_when_exif_failed(self) -> None:
        sidecar = sample_sidecar(exif_user_comment=False)
        chunks = {(chunk["keyword"], chunk["type"]) for chunk in sidecar["pngMetadata"]["chunks"]}

        self.assertNotIn(("UserComment", "eXIf"), chunks)

    def test_a1111_and_civitai_manifest_are_preserved(self) -> None:
        sidecar = sample_sidecar(parameters="snow 雪\nNegative prompt:\nSteps: 8")

        self.assertIn("snow 雪", sidecar["a1111"]["parameters"])
        self.assertTrue(sidecar["a1111"]["unicodeFallbackApplied"])
        self.assertEqual(sidecar["civitai"]["schemaVersion"], __version__)
        self.assertEqual(sidecar["civitai"]["generator"]["version"], __version__)
        self.assertEqual(sidecar["civitai"]["metadataStatus"], "partial")

    def test_resources_lifecycle_lookup_settings_warnings_and_privacy(self) -> None:
        sidecar = sample_sidecar(lookup_enabled=True, manual_enabled=True, manual_entry_count=2)

        self.assertEqual(sidecar["resources"]["resolved"][0]["modelVersionId"], 20)
        self.assertEqual(sidecar["resources"]["final"][0]["modelVersionId"], 20)
        self.assertEqual(sidecar["resources"]["unresolved"][0]["unresolvedReason"], "hashed_but_no_civitai_identity")
        self.assertEqual(sidecar["resourceLifecycle"]["metadataStatus"], "partial")
        self.assertEqual(sidecar["lookupDiagnostics"]["enabled"], True)
        self.assertEqual(sidecar["lookupDiagnostics"]["entries"][0]["lookupStatus"], "failed")
        self.assertEqual(sidecar["settings"]["manualIdentities"], {"enabled": True, "entryCount": 2})
        self.assertEqual(sidecar["warnings"][0]["severity"], "warning")
        self.assertEqual(sidecar["errors"][0]["severity"], "error")
        self.assertFalse(sidecar["privacy"]["absolutePathsIncluded"])
        self.assertEqual(sidecar["privacy"]["lookupRequestData"], ["hashes", "modelVersionId"])

    def test_sidecar_json_is_strict_utf8_with_newline_and_no_nonfinite_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            output.mkdir()
            image_path = output / "image.png"
            image_path.write_bytes(b"png")
            payload = sample_sidecar()

            sidecar_path = write_sidecar_json_file(image_path, payload, output)
            raw = sidecar_path.read_bytes()
            text = raw.decode("utf-8")
            parsed = json.loads(text, parse_constant=lambda value: self.fail(f"non-finite value {value}"))

            self.assertTrue(raw.endswith(b"\n"))
            self.assertEqual(parsed["sidecarFormat"], SIDECAR_FORMAT)
            self.assertNotRegex(text, r"\bNaN\b|\bInfinity\b|-Infinity")

    def test_schema_validator_accepts_generated_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            output.mkdir()
            image_path = output / "image.png"
            image_path.write_bytes(b"png")
            sidecar_path = write_sidecar_json_file(image_path, sample_sidecar(), output)

            report = validate_sidecar_file(sidecar_path)

            self.assertTrue(report.ok, report.to_text())
            self.assertIn(report.schema_validation.split(":", 1)[0], {"ok", "skipped"})

    def test_sidecar_has_no_absolute_paths_or_tokens(self) -> None:
        sidecar = sample_sidecar(
            parameters=r"prompt C:\Private\Local\secret.safetensors token=placeholder-value-not-for-auth"
        )
        text = to_json_text(sidecar)

        self.assertNotIn(r"C:\Private\Local", text)
        self.assertNotIn("/Users/", text)
        self.assertNotIn("/home/", text)
        self.assertNotIn("placeholder-value-not-for-auth", text)
        self.assertIn("<redacted_secret>", text)
        self.assertFalse(re.search(r"[A-Za-z]:\\\\", text))


def sample_sidecar(
    *,
    parameters: str = "positive prompt\nNegative prompt:\nSteps: 8, Sampler: Euler, Size: 1024x768",
    lookup_enabled: bool = False,
    manual_enabled: bool = False,
    manual_entry_count: int = 0,
    exif_minimal: bool = False,
    exif_user_comment: bool = True,
) -> dict[str, object]:
    manifest = build_civitai_manifest(
        prompt=PromptMetadata(positive="positive prompt"),
        generation=GenerationSettings(
            steps=8,
            sampler="Euler",
            width=1024,
            height=768,
            model="base.safetensors",
            model_hash="1234567890",
        ),
        resources=(resolved_resource(),),
        unresolved_resources=(
            UnresolvedResource(
                reason="hashed_but_no_civitai_identity",
                role="vae",
                type="vae",
                name="ae.safetensors",
                hashes=HashMetadata(auto_v2="feedfeed01"),
                hash_status="hashed",
                lookup_status="failed",
            ),
        ),
        hashes=HashMetadata(additional={"model": "1234567890"}),
        validation=ValidationResult(
            warnings=(ValidationIssue(code="sample_warning", message="safe warning"),),
            errors=(ValidationIssue(code="sample_error", message="safe error"),),
        ),
        include_workflow=True,
        generator=GeneratorMetadata(version=__version__),
        metadata_status="partial",
        lookup_debug_summary=(
            {
                "filename": "base.safetensors",
                "role": "checkpoint",
                "lookupStatus": "failed",
                "lookupFailureClass": "ssl_error",
                "retryable": True,
                "lookupClient": "urllib",
                "sslContextSource": "system_default",
            },
        ),
    )
    lifecycle = build_resource_lifecycle(
        raw_resources_found=(unresolved_resource("inactive-upscaler.pth"),),
        active_resources=(unresolved_resource("base.safetensors"),),
        normalized_resources=(unresolved_resource("base.safetensors"),),
        final_resources=(resolved_resource(), unresolved_resource("base.safetensors")),
        unresolved_resources=manifest.unresolved_resources,
        final_a1111_parameters=parameters,
        lookup_debug_summary=manifest.lookup_debug_summary,
        warnings=manifest.validation.warnings,
        metadata_status="partial",
    )
    return build_sidecar_payload(
        image={
            "filename": r"C:\Private\Local\image.png",
            "subfolder": "safe/subfolder",
            "type": "output",
            "width": 1024,
            "height": 768,
            "mode": "RGB",
        },
        options=MetadataOptions(
            strict_mode=False,
            include_workflow=True,
            include_civitai_manifest=True,
            write_sidecar_json=True,
            enable_civitai_lookup=lookup_enabled,
            lookup_cache_results=True,
            civitai_exif_minimal=exif_minimal,
        ),
        prompt={"1": {"class_type": "KSampler"}},
        extra_pnginfo={"workflow": {"nodes": []}},
        civitai_manifest=manifest,
        validation=manifest.validation,
        resource_lifecycle=lifecycle,
        a1111_parameters=parameters,
        manual_identities_enabled=manual_enabled,
        manual_identities_entry_count=manual_entry_count,
        exif_user_comment=exif_user_comment,
    )


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
            hash_status="hashed",
            metadata={"identitySource": "local_cache", "lookupStatus": "resolved_by_cache"},
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
            hashes=HashMetadata(auto_v2="feedfeed01"),
            hash_status="hashed",
            metadata={"lookupStatus": "skipped_lookup_disabled"},
        ),
        resolved=False,
        unresolved_reason="hashed_but_no_civitai_identity",
    )


if __name__ == "__main__":
    unittest.main()
