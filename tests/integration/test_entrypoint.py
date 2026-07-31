from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngImageFile

from tools.validate_sidecar import validate_sidecar

ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_PACKAGE = "_civiscribe_custom_node_test"
_OUTPUT_DIRECTORY = {"path": ""}
DEFAULT_JPEG_QUALITY = 100
DEFAULT_LOOKUP_TIMEOUT_SECONDS = 4.0
MAX_LOOKUP_TIMEOUT_SECONDS = 30.0
OVERSIZED_LOOKUP_TIMEOUT_SECONDS = 999.0


class _ComfyNode:
    pass


class _ComfyExtension:
    async def get_node_list(self) -> list[type[_ComfyNode]]:
        raise NotImplementedError


class _Input:
    def __init__(self, input_id: str, **kwargs: object) -> None:
        self.id = input_id
        self.options = kwargs


class _Image:
    Type = object
    Input = _Input
    Output = _Input


class _String:
    Input = _Input


class _Combo:
    Input = _Input


class _Int:
    Input = _Input


class _Boolean:
    Input = _Input


class _Float:
    Input = _Input


class _Schema:
    def __init__(self, **kwargs: object) -> None:
        vars(self).update(kwargs)


class _FolderType(Enum):
    output = "output"


class _NodeOutput:
    def __init__(self, *outputs: object, ui: object = None) -> None:
        self.outputs = outputs
        self.ui = ui


class _SavedResult(dict[str, object]):
    def __init__(self, filename: str, subfolder: str, folder_type: _FolderType) -> None:
        super().__init__(
            filename=filename,
            subfolder=subfolder,
            type=folder_type.value,
        )


class _SavedImages:
    def __init__(self, results: list[_SavedResult]) -> None:
        self.results = results


def _fake_comfy_modules() -> dict[str, ModuleType]:
    io_module = ModuleType("comfy_api.latest.io")
    vars(io_module)["ComfyNode"] = _ComfyNode
    vars(io_module)["FolderType"] = _FolderType
    vars(io_module)["Image"] = _Image
    vars(io_module)["String"] = _String
    vars(io_module)["Combo"] = _Combo
    vars(io_module)["Int"] = _Int
    vars(io_module)["Boolean"] = _Boolean
    vars(io_module)["Float"] = _Float
    vars(io_module)["Schema"] = _Schema
    vars(io_module)["NodeOutput"] = _NodeOutput

    ui_module = ModuleType("comfy_api.latest.ui")
    vars(ui_module)["SavedResult"] = _SavedResult
    vars(ui_module)["SavedImages"] = _SavedImages

    latest = ModuleType("comfy_api.latest")
    vars(latest)["ComfyExtension"] = _ComfyExtension
    vars(latest)["io"] = io_module
    vars(latest)["ui"] = ui_module

    comfy_api = ModuleType("comfy_api")
    vars(comfy_api)["latest"] = latest
    folder_paths = ModuleType("folder_paths")
    vars(folder_paths)["get_output_directory"] = lambda: _OUTPUT_DIRECTORY["path"]
    return {
        "comfy_api": comfy_api,
        "comfy_api.latest": latest,
        "comfy_api.latest.io": io_module,
        "comfy_api.latest.ui": ui_module,
        "folder_paths": folder_paths,
    }


def _load_root_entrypoint() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        SYNTHETIC_PACKAGE,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[SYNTHETIC_PACKAGE] = module
    spec.loader.exec_module(module)
    return module


def test_root_import_is_lazy_and_needs_no_comfyui_runtime() -> None:
    module = _load_root_entrypoint()
    try:
        assert module.WEB_DIRECTORY == "./web/dist"
        assert callable(module.comfy_entrypoint)
    finally:
        for name in tuple(sys.modules):
            if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                sys.modules.pop(name, None)


def test_native_v3_entrypoint_registers_civiscribe_node() -> None:
    with patch.dict(sys.modules, _fake_comfy_modules()):
        module = _load_root_entrypoint()
        try:
            extension = asyncio.run(module.comfy_entrypoint())
            assert isinstance(extension, _ComfyExtension)
            nodes = asyncio.run(extension.get_node_list())
            assert len(nodes) == 1
            assert nodes[0].__name__ == "CiviScribeSaveImage"
        finally:
            for name in tuple(sys.modules):
                if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                    sys.modules.pop(name, None)


def test_public_node_schema_is_native_v3_and_registered_once() -> None:
    with patch.dict(sys.modules, _fake_comfy_modules()):
        module = _load_root_entrypoint()
        try:
            asyncio.run(module.comfy_entrypoint())
            node_module = sys.modules[f"{SYNTHETIC_PACKAGE}.civiscribe.node"]
            node_class = vars(node_module)["CiviScribeSaveImage"]
            schema = node_class.define_schema()
            assert schema.node_id == "CCollins_CiviScribe_SaveImage"
            assert schema.display_name == "CiviScribe - Save Image for Civitai"
            assert schema.category == "CCollins/CiviScribe"
            assert schema.is_output_node is True
            assert [item.id for item in schema.outputs] == ["images"]
            assert schema.outputs[0].options == {
                "display_name": "Images",
                "tooltip": "Original image tensor passed through unchanged.",
            }
            assert [item.id for item in schema.inputs] == [
                "images",
                "positive_prompt_override",
                "negative_prompt_override",
                "filename_prefix",
                "output_format",
                "jpeg_quality",
                "jpeg_alpha_background",
                "webp_lossless",
                "webp_quality",
                "write_sidecar_json",
                "include_workflow",
                "include_civitai_manifest",
                "enable_civitai_lookup",
                "preferred_primary_model_air",
                "hashing_mode",
                "lookup_timeout_seconds",
                "lookup_cache_results",
                "advanced_manual_identities_enabled",
                "manual_resource_identities_json",
            ]
            by_id = {item.id: item for item in schema.inputs}
            assert by_id["output_format"].options["options"] == ["png", "jpeg", "webp"]
            assert by_id["output_format"].options["default"] == "png"
            assert by_id["output_format"].options["tooltip"] == (
                "Image format. PNG and WebP are lossless by default; JPEG is lossy."
            )
            assert by_id["jpeg_quality"].options["default"] == DEFAULT_JPEG_QUALITY
            assert by_id["webp_lossless"].options["default"] is True
            assert by_id["write_sidecar_json"].options["default"] is False
            assert by_id["include_workflow"].options["default"] is True
            assert by_id["include_civitai_manifest"].options["default"] is True
            assert by_id["enable_civitai_lookup"].options["default"] is False
            assert by_id["hashing_mode"].options["default"] == "cached_or_fast"
            assert (
                by_id["lookup_timeout_seconds"].options["default"] == DEFAULT_LOOKUP_TIMEOUT_SECONDS
            )
            assert by_id["lookup_cache_results"].options["default"] is True
            assert by_id["advanced_manual_identities_enabled"].options["default"] is False
            assert by_id["manual_resource_identities_json"].options["advanced"] is True
            assert by_id["positive_prompt_override"].options["optional"] is True
            assert by_id["positive_prompt_override"].options["force_input"] is True
            assert all(item.options.get("display_name") for item in schema.inputs)
            assert all(item.options.get("tooltip") for item in schema.inputs)
            assert vars(node_module)["registered_nodes"]() == (node_class,)
        finally:
            for name in tuple(sys.modules):
                if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                    sys.modules.pop(name, None)


def test_candidate_node_returns_preview_for_exact_committed_file(tmp_path: Path) -> None:
    _OUTPUT_DIRECTORY["path"] = str(tmp_path)
    with patch.dict(sys.modules, _fake_comfy_modules()):
        module = _load_root_entrypoint()
        try:
            asyncio.run(module.comfy_entrypoint())
            node_module = sys.modules[f"{SYNTHETIC_PACKAGE}.civiscribe.node"]
            node_class = vars(node_module)["CiviScribeSaveImage"]
            batch = np.zeros((1, 2, 3, 3), dtype=np.float32)
            result = node_class.execute(batch, filename_prefix="nested/image")
            assert result.outputs == (batch,)
            assert result.outputs[0] is batch
            assert len(result.ui.results) == 1
            preview = result.ui.results[0]
            assert preview["type"] == "output"
            assert preview["subfolder"] == "nested"
            assert (tmp_path / "nested" / str(preview["filename"])).is_file()
        finally:
            for name in tuple(sys.modules):
                if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                    sys.modules.pop(name, None)


def test_candidate_node_can_write_valid_optional_sidecar(tmp_path: Path) -> None:
    _OUTPUT_DIRECTORY["path"] = str(tmp_path)
    with patch.dict(sys.modules, _fake_comfy_modules()):
        module = _load_root_entrypoint()
        try:
            asyncio.run(module.comfy_entrypoint())
            node_module = sys.modules[f"{SYNTHETIC_PACKAGE}.civiscribe.node"]
            node_class = vars(node_module)["CiviScribeSaveImage"]
            batch = np.zeros((1, 2, 3, 3), dtype=np.float32)
            result = node_class.execute(
                batch,
                filename_prefix="nested/image",
                write_sidecar_json=True,
            )
            preview = result.ui.results[0]
            image_path = tmp_path / "nested" / str(preview["filename"])
            sidecar_path = image_path.with_suffix(".json")
            assert image_path.is_file()
            assert sidecar_path.is_file()
            assert validate_sidecar(sidecar_path).valid
        finally:
            for name in tuple(sys.modules):
                if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                    sys.modules.pop(name, None)


@pytest.mark.parametrize(
    ("output_format", "extension", "pillow_format"),
    [
        ("jpeg", ".jpg", "JPEG"),
        ("webp", ".webp", "WEBP"),
    ],
)
def test_candidate_node_dispatches_non_png_preview_to_committed_artifact(
    tmp_path: Path,
    output_format: str,
    extension: str,
    pillow_format: str,
) -> None:
    _OUTPUT_DIRECTORY["path"] = str(tmp_path)
    with patch.dict(sys.modules, _fake_comfy_modules()):
        module = _load_root_entrypoint()
        try:
            asyncio.run(module.comfy_entrypoint())
            node_module = sys.modules[f"{SYNTHETIC_PACKAGE}.civiscribe.node"]
            node_class = vars(node_module)["CiviScribeSaveImage"]
            result = node_class.execute(
                np.zeros((1, 2, 3, 3), dtype=np.float32),
                filename_prefix="image",
                output_format=output_format,
            )
            preview = result.ui.results[0]
            assert str(preview["filename"]).endswith(extension)
            with Image.open(tmp_path / str(preview["filename"])) as image:
                assert image.format == pillow_format
        finally:
            for name in tuple(sys.modules):
                if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                    sys.modules.pop(name, None)


def test_candidate_node_falls_back_to_png_for_unknown_format(tmp_path: Path) -> None:
    _OUTPUT_DIRECTORY["path"] = str(tmp_path)
    with patch.dict(sys.modules, _fake_comfy_modules()):
        module = _load_root_entrypoint()
        try:
            asyncio.run(module.comfy_entrypoint())
            node_module = sys.modules[f"{SYNTHETIC_PACKAGE}.civiscribe.node"]
            node_class = vars(node_module)["CiviScribeSaveImage"]
            result = node_class.execute(
                np.zeros((1, 2, 3, 3), dtype=np.float32),
                filename_prefix="image",
                output_format="unsupported",
            )
            preview = result.ui.results[0]
            assert str(preview["filename"]).endswith(".png")
            with Image.open(tmp_path / str(preview["filename"])) as image:
                assert image.format == "PNG"
        finally:
            for name in tuple(sys.modules):
                if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                    sys.modules.pop(name, None)


def test_candidate_node_embeds_current_v3_hidden_prompt_and_workflow(
    tmp_path: Path,
) -> None:
    _OUTPUT_DIRECTORY["path"] = str(tmp_path)
    prompt = {
        "1": {
            "class_type": "SourceImage",
            "inputs": {},
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }
    workflow = {"nodes": [{"id": 2, "type": "CCollins_CiviScribe_SaveImage"}]}
    with patch.dict(sys.modules, _fake_comfy_modules()):
        module = _load_root_entrypoint()
        try:
            asyncio.run(module.comfy_entrypoint())
            node_module = sys.modules[f"{SYNTHETIC_PACKAGE}.civiscribe.node"]
            node_class = vars(node_module)["CiviScribeSaveImage"]
            node_class.hidden = SimpleNamespace(
                prompt=prompt,
                extra_pnginfo={"workflow": workflow},
                unique_id="2",
            )
            result = node_class.execute(
                np.zeros((1, 2, 3, 3), dtype=np.float32),
                filename_prefix="metadata",
            )
            preview = result.ui.results[0]
            path = tmp_path / str(preview["filename"])
            with Image.open(path) as image:
                text = cast(PngImageFile, image).text
                assert json.loads(text["prompt"]) == prompt
                assert json.loads(text["workflow"]) == workflow
                assert "civitai" in text
                assert "parameters" in text
                assert "Software" in text
                assert image.getexif().get_ifd(0x8769).get(0x9286)
        finally:
            for name in tuple(sys.modules):
                if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                    sys.modules.pop(name, None)


def test_candidate_node_threads_identity_and_prompt_ui_policy(tmp_path: Path) -> None:
    _OUTPUT_DIRECTORY["path"] = str(tmp_path)
    with patch.dict(sys.modules, _fake_comfy_modules()):
        module = _load_root_entrypoint()
        try:
            asyncio.run(module.comfy_entrypoint())
            node_module = sys.modules[f"{SYNTHETIC_PACKAGE}.civiscribe.node"]
            node_class = vars(node_module)["CiviScribeSaveImage"]
            services = object()
            with (
                patch.object(
                    node_module,
                    "identity_services_from_comfy",
                    return_value=services,
                ) as build_services,
                patch.object(
                    node_module,
                    "save_image_batch",
                    return_value=SimpleNamespace(saved_images=[]),
                ) as save_batch,
            ):
                node_class.execute(
                    np.zeros((1, 2, 3, 3), dtype=np.float32),
                    positive_prompt_override="positive override",
                    negative_prompt_override="negative override",
                    enable_civitai_lookup=True,
                    preferred_primary_model_air="2734704",
                    hashing_mode="full",
                    lookup_timeout_seconds=12.5,
                    lookup_cache_results=False,
                    advanced_manual_identities_enabled=True,
                    manual_resource_identities_json='[{"match": {}}]',
                )

            request = save_batch.call_args.args[0]
            assert request.metadata.positive_prompt_override == "positive override"
            assert request.metadata.negative_prompt_override == "negative override"
            assert request.metadata.identity_options.hashing_mode.value == "full"
            assert request.metadata.identity_options.preferred_primary == "2734704"
            assert request.metadata.identity_options.manual_json == '[{"match": {}}]'
            assert request.metadata.identity_options.cache_api_results is False
            assert request.metadata.identity_services is services
            build_services.assert_called_once_with(
                output_root=tmp_path,
                enable_lookup=True,
                lookup_timeout_seconds=12.5,
            )
        finally:
            for name in tuple(sys.modules):
                if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                    sys.modules.pop(name, None)


def test_candidate_node_safely_normalizes_stale_identity_widget_values(
    tmp_path: Path,
) -> None:
    _OUTPUT_DIRECTORY["path"] = str(tmp_path)
    with patch.dict(sys.modules, _fake_comfy_modules()):
        module = _load_root_entrypoint()
        try:
            asyncio.run(module.comfy_entrypoint())
            node_module = sys.modules[f"{SYNTHETIC_PACKAGE}.civiscribe.node"]
            node_class = vars(node_module)["CiviScribeSaveImage"]
            with (
                patch.object(
                    node_module,
                    "identity_services_from_comfy",
                    return_value=object(),
                ) as build_services,
                patch.object(
                    node_module,
                    "save_image_batch",
                    return_value=SimpleNamespace(saved_images=[]),
                ) as save_batch,
            ):
                node_class.execute(
                    np.zeros((1, 2, 3, 3), dtype=np.float32),
                    hashing_mode="unsupported",
                    lookup_timeout_seconds=OVERSIZED_LOOKUP_TIMEOUT_SECONDS,
                    advanced_manual_identities_enabled=False,
                    manual_resource_identities_json="{stale",
                )

            request = save_batch.call_args.args[0]
            assert request.metadata.identity_options.hashing_mode.value == "cached_or_fast"
            assert request.metadata.identity_options.manual_json is None
            build_services.assert_called_once_with(
                output_root=tmp_path,
                enable_lookup=False,
                lookup_timeout_seconds=MAX_LOOKUP_TIMEOUT_SECONDS,
            )
        finally:
            for name in tuple(sys.modules):
                if name == SYNTHETIC_PACKAGE or name.startswith(f"{SYNTHETIC_PACKAGE}."):
                    sys.modules.pop(name, None)
