from __future__ import annotations

from datetime import datetime
import tempfile
import unittest
from pathlib import Path

from save_node.io.paths import (
    PathSecurityError,
    ensure_within_directory,
    expand_filename_template,
    normalize_filename_prefix,
    safe_output_path,
    safe_sidecar_path,
)
from save_node.metadata.schema import GenerationSettings


class PathSafetyTests(unittest.TestCase):
    def test_normal_prefix_is_preserved(self) -> None:
        self.assertEqual(normalize_filename_prefix("renders/session"), "renders/session")

    def test_weird_characters_are_sanitized(self) -> None:
        self.assertEqual(normalize_filename_prefix('bad:name*"?'), "bad_name___")

    def test_unicode_prefix_is_allowed(self) -> None:
        self.assertEqual(normalize_filename_prefix("\u6e2c\u8a66/output"), "\u6e2c\u8a66/output")

    def test_parent_traversal_is_rejected(self) -> None:
        with self.assertRaises(PathSecurityError):
            normalize_filename_prefix("../outside")

    def test_windows_absolute_prefix_is_rejected(self) -> None:
        with self.assertRaises(PathSecurityError):
            normalize_filename_prefix(r"C:\Private\Local\secret")

    def test_unc_prefix_is_rejected(self) -> None:
        with self.assertRaises(PathSecurityError):
            normalize_filename_prefix(r"\\server\share\secret")

    def test_output_path_must_stay_under_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            outside = Path(tmp) / "outside"
            output.mkdir()
            outside.mkdir()

            with self.assertRaises(PathSecurityError):
                safe_output_path(output, outside, "image.png")

    def test_output_filename_must_be_single_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with self.assertRaises(PathSecurityError):
                safe_output_path(output, output, "../image.png")

    def test_safe_output_path_allows_nested_output_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            nested = output / "nested"
            output.mkdir()
            path = safe_output_path(output, nested, "image.png")

            self.assertEqual(path, nested / "image.png")

    def test_sidecar_path_stays_under_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            output.mkdir()
            image = output / "image.png"

            self.assertEqual(safe_sidecar_path(output, image), output / "image.json")

    def test_ensure_within_directory_rejects_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            sibling = Path(tmp) / "output-sibling" / "image.png"
            output.mkdir()

            with self.assertRaises(PathSecurityError):
                ensure_within_directory(output, sibling)

    def test_filename_template_expands_date_model_seed_and_sampler(self) -> None:
        expanded, warnings = expand_filename_template(
            "%date:yyyy-MM-dd%/%date:hhmmss%_%model%_%seed%_%sampler%_%width%x%height%",
            generation=GenerationSettings(
                model="swiftFastAndDetailed_neo.gguf",
                seed=123,
                sampler="multistep/res_2m",
                width=832,
                height=1216,
            ),
            now=datetime(2026, 6, 29, 20, 32, 13),
        )

        self.assertEqual(
            normalize_filename_prefix(expanded),
            "2026-06-29/203213_swiftFastAndDetailed_neo.gguf_123_multistep_res_2m_832x1216",
        )
        self.assertEqual(warnings, ())

    def test_filename_template_expands_underscore_date_aliases(self) -> None:
        expanded, warnings = expand_filename_template(
            "%date_yyyy-MM-dd%/%date_hhmmss%_%model%",
            generation=GenerationSettings(model="base.safetensors"),
            now=datetime(2026, 6, 29, 8, 7, 6),
        )

        self.assertEqual(normalize_filename_prefix(expanded), "2026-06-29/080706_base.safetensors")
        self.assertEqual(warnings, ())

    def test_filename_template_sanitizes_model_token_without_creating_subfolders(self) -> None:
        expanded, _warnings = expand_filename_template(
            "renders/%model%",
            generation=GenerationSettings(model="../secret/base:safetensors"),
            now=datetime(2026, 6, 29, 8, 7, 6),
        )

        self.assertEqual(normalize_filename_prefix(expanded), "renders/_secret_base_safetensors")

    def test_filename_template_traversal_in_literal_prefix_is_rejected(self) -> None:
        expanded, _warnings = expand_filename_template(
            "../%model%",
            generation=GenerationSettings(model="base.safetensors"),
            now=datetime(2026, 6, 29, 8, 7, 6),
        )

        with self.assertRaises(PathSecurityError):
            normalize_filename_prefix(expanded)

    def test_unknown_filename_template_token_warns(self) -> None:
        expanded, warnings = expand_filename_template(
            "renders/%unknown%",
            generation=GenerationSettings(),
            now=datetime(2026, 6, 29, 8, 7, 6),
        )

        self.assertEqual(normalize_filename_prefix(expanded), "renders/%unknown%")
        self.assertEqual(warnings[0].code, "unknown_filename_template_token")


if __name__ == "__main__":
    unittest.main()
