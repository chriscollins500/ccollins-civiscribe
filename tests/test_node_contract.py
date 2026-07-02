from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from save_node import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from save_node.metadata.schema import GenerationSettings
from save_node.nodes import _advanced_manual_identities_enabled, _apply_final_image_dimensions


class NodeContractTests(unittest.TestCase):
    def test_comfyui_node_mapping_and_inputs(self) -> None:
        self.assertIn("SaveImageWithCivitaiMetadata", NODE_CLASS_MAPPINGS)
        self.assertEqual(
            NODE_DISPLAY_NAME_MAPPINGS["SaveImageWithCivitaiMetadata"],
            "Save Image with Civitai Metadata",
        )

        node_class = NODE_CLASS_MAPPINGS["SaveImageWithCivitaiMetadata"]
        input_types = node_class.INPUT_TYPES()

        self.assertEqual(node_class.RETURN_TYPES, ("IMAGE",))
        self.assertEqual(node_class.RETURN_NAMES, ("images",))
        self.assertTrue(node_class.OUTPUT_NODE)
        self.assertEqual(
            list(input_types["required"].keys()),
            [
                "images",
                "filename_prefix",
                "write_sidecar_json",
                "strict_mode",
                "include_workflow",
                "include_civitai_manifest",
                "enable_civitai_lookup",
                "lookup_prefer_sha256",
                "lookup_timeout_seconds",
                "lookup_cache_results",
                "use_persistent_hash_cache",
                "hashing_mode",
                "preferred_primary_model_air",
                "advanced_manual_identities_enabled",
                "manual_resource_identities_json",
                "civitai_exif_minimal",
            ],
        )
        self.assertEqual(input_types["required"]["images"][0], "IMAGE")
        self.assertEqual(input_types["hidden"], {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"})
        self.assertFalse(input_types["required"]["enable_civitai_lookup"][1]["default"])
        self.assertFalse(input_types["required"]["lookup_cache_results"][1]["default"])
        self.assertTrue(input_types["required"]["use_persistent_hash_cache"][1]["default"])
        self.assertEqual(input_types["required"]["hashing_mode"][1]["default"], "cached_or_fast")
        self.assertEqual(input_types["required"]["preferred_primary_model_air"][1]["default"], "")
        self.assertEqual(
            input_types["required"]["preferred_primary_model_air"][1]["label"],
            "Preferred AIR or URL",
        )
        self.assertFalse(input_types["required"]["advanced_manual_identities_enabled"][1]["default"])
        self.assertEqual(
            input_types["required"]["advanced_manual_identities_enabled"][1]["label"],
            "Advanced JSON",
        )
        self.assertEqual(input_types["required"]["manual_resource_identities_json"][1]["default"], "[]")
        self.assertTrue(input_types["required"]["manual_resource_identities_json"][1]["multiline"])
        self.assertEqual(
            input_types["required"]["manual_resource_identities_json"][1]["label"],
            "Advanced resource JSON",
        )
        self.assertFalse(input_types["required"]["civitai_exif_minimal"][1]["default"])
        self.assertEqual(
            input_types["required"]["civitai_exif_minimal"][1]["label"],
            "Civitai EXIF Minimal",
        )
        for name, definition in input_types["required"].items():
            self.assertGreaterEqual(len(definition), 2, name)
            self.assertIn("tooltip", definition[1], name)
            self.assertTrue(definition[1]["tooltip"], name)

    def test_frontend_web_directory_and_extension_are_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        js_path = root / "js" / "civitai_save_node_ui.js"

        self.assertTrue(js_path.exists())
        self.assertIn('WEB_DIRECTORY = "./js"', (root / "__init__.py").read_text(encoding="utf-8"))
        text = js_path.read_text(encoding="utf-8")
        self.assertIn('import { app } from "../../scripts/app.js";', text)
        self.assertIn("app.registerExtension", text)
        self.assertIn("SaveImageWithCivitaiMetadata", text)
        self.assertIn("advanced_manual_identities_enabled", text)
        self.assertIn("manual_resource_identities_json", text)
        self.assertIn("const DEBUG = false", text)
        self.assertIn("restoreWidgetFunction", text)
        self.assertIn("setDomVisible", text)
        self.assertIn("widget.computeSize = () => [0, 0]", text)
        self.assertIn("widget.draw = () => {}", text)
        self.assertIn("widget.last_y = undefined", text)
        self.assertIn("requestAnimationFrame", text)
        self.assertIn("Edit JSON", text)
        self.assertIn("openJsonEditor", text)
        self.assertIn("JSON.parse", text)
        self.assertIn("manualJson.value = nextValue", text)
        self.assertIn("DEFAULT_NODE_WIDTH = 600", text)

    def test_advanced_manual_identity_toggle_defaults_and_backcompat(self) -> None:
        self.assertFalse(_advanced_manual_identities_enabled(False, "{bad json"))
        self.assertFalse(_advanced_manual_identities_enabled(None, "[]"))
        self.assertFalse(_advanced_manual_identities_enabled(None, ""))
        self.assertTrue(_advanced_manual_identities_enabled(True, "[]"))
        self.assertTrue(_advanced_manual_identities_enabled(None, '[{"match":{"name":"base.safetensors"}}]'))

    def test_final_image_dimensions_fill_missing_generation_size(self) -> None:
        generation = _apply_final_image_dimensions(GenerationSettings(steps=8), 832, 1216)

        self.assertEqual(generation.width, 832)
        self.assertEqual(generation.height, 1216)

    def test_comfyui_entrypoint_imports_without_top_level_save_node(self) -> None:
        root = Path(__file__).resolve().parents[1]
        module_name = "comfyui_civitai_save_node_import_test"
        original_sys_path = list(sys.path)
        saved_modules = {
            name: module
            for name, module in list(sys.modules.items())
            if name == "save_node" or name.startswith("save_node.")
        }

        try:
            for name in saved_modules:
                sys.modules.pop(name, None)
            sys.modules["save_node"] = None
            sys.path[:] = [entry for entry in sys.path if _resolved_sys_path(entry) != root]

            spec = importlib.util.spec_from_file_location(
                module_name,
                root / "__init__.py",
                submodule_search_locations=[str(root)],
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            self.assertIn("SaveImageWithCivitaiMetadata", module.NODE_CLASS_MAPPINGS)
            self.assertEqual(module.WEB_DIRECTORY, "./js")
            self.assertIn("WEB_DIRECTORY", module.__all__)
            self.assertEqual(
                module.NODE_DISPLAY_NAME_MAPPINGS["SaveImageWithCivitaiMetadata"],
                "Save Image with Civitai Metadata",
            )
        finally:
            for name in list(sys.modules):
                if name == module_name or name.startswith(f"{module_name}."):
                    sys.modules.pop(name, None)
            if sys.modules.get("save_node") is None:
                sys.modules.pop("save_node", None)
            sys.modules.update(saved_modules)
            sys.path[:] = original_sys_path


def _resolved_sys_path(entry: str) -> Path | None:
    try:
        return Path(entry or ".").resolve()
    except OSError:
        return None


if __name__ == "__main__":
    unittest.main()
