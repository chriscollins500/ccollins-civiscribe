from __future__ import annotations

import re
import subprocess
import sys
import unittest

from save_node.civitai.manifest import build_civitai_manifest
from save_node.io.png_writer import SOFTWARE_TEXT
from save_node.io.sidecar import SIDECAR_SCHEMA_VERSION, build_sidecar_payload
from save_node.metadata.schema import (
    GenerationSettings,
    HashMetadata,
    MetadataOptions,
    PromptMetadata,
    ValidationResult,
)
from save_node.version import __version__


class ReleaseReadinessTests(unittest.TestCase):
    def test_version_is_consistent_across_package_docs_and_metadata(self) -> None:
        pyproject = _read("pyproject.toml")
        readme = _read("README.md")
        changelog = _read("CHANGELOG.md")

        self.assertIn(f'version = "{__version__}"', pyproject)
        self.assertIn(f"Pre-release {__version__}", readme)
        self.assertRegex(changelog, rf"## {re.escape(__version__)}\b")
        self.assertIn(f"comfyui-civitai-save-node {__version__}", SOFTWARE_TEXT)

        manifest = build_civitai_manifest(
            prompt=PromptMetadata(positive="test"),
            generation=GenerationSettings(width=1, height=1),
            resources=(),
            unresolved_resources=(),
            hashes=HashMetadata(),
            validation=ValidationResult(),
            include_workflow=True,
        )
        sidecar = build_sidecar_payload(
            image={"filename": "image.png", "format": "PNG", "width": 1, "height": 1},
            options=MetadataOptions(
                strict_mode=False,
                include_workflow=True,
                include_civitai_manifest=True,
                write_sidecar_json=True,
            ),
            prompt={},
            extra_pnginfo={"workflow": {"nodes": []}},
            civitai_manifest=manifest,
            validation=ValidationResult(),
            a1111_parameters="test\nNegative prompt:\nSteps: 1, Size: 1x1",
        )

        self.assertEqual(manifest.to_json()["generator"]["version"], __version__)
        self.assertEqual(manifest.to_json()["schemaVersion"], __version__)
        self.assertEqual(sidecar["generator"]["version"], __version__)
        self.assertEqual(sidecar["sidecarSchemaVersion"], SIDECAR_SCHEMA_VERSION)
        self.assertNotEqual(sidecar["sidecarSchemaVersion"], __version__)

    def test_tool_help_entrypoints_are_available(self) -> None:
        for script in (
            "tools/validate_sidecar.py",
            "tools/inspect_png_chunks.py",
            "tools/analyze_civitai_generator_metadata.py",
            "tools/make_civitai_metadata_recognition_variants.py",
            "tools/run_quality_checks.py",
        ):
            with self.subTest(script=script):
                completed = subprocess.run(
                    [sys.executable, script, "--help"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("usage:", completed.stdout)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


if __name__ == "__main__":
    unittest.main()
