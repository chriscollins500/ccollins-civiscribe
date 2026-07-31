from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from civiscribe.adapters import model_files
from civiscribe.adapters.model_files import ModelRootLocator
from civiscribe.domain import ResourceKind, ResourceRecord, ResourceRole
from tests.projection_support import model_resource


def _resource(selected_value: str) -> ResourceRecord:
    return replace(model_resource(), selected_value=selected_value)


def test_locator_resolves_exact_selection_below_approved_root(tmp_path: Path) -> None:
    root = tmp_path / "models" / "diffusion_models"
    root.mkdir(parents=True)
    model = root / "nested" / "model.gguf"
    model.parent.mkdir()
    model.write_bytes(b"model")
    locator = ModelRootLocator({"diffusion_models": [root]})

    located = locator.locate(_resource("diffusion_models/nested/model.gguf"))

    assert located is not None
    assert located.path == model.resolve()
    assert located.approved_root == root.resolve()
    assert located.category == "diffusion_models"
    assert located.selected_value == "diffusion_models/nested/model.gguf"


def test_locator_uses_role_specific_categories_without_filename_guessing(
    tmp_path: Path,
) -> None:
    checkpoints = tmp_path / "checkpoints"
    loras = tmp_path / "loras"
    checkpoints.mkdir()
    loras.mkdir()
    (checkpoints / "same.safetensors").write_bytes(b"checkpoint")
    (loras / "same.safetensors").write_bytes(b"lora")
    locator = ModelRootLocator({"checkpoints": [checkpoints], "loras": [loras]})

    base = locator.locate(_resource("same.safetensors"))
    lora = locator.locate(
        replace(
            model_resource(),
            role=ResourceRole.LORA,
            selected_value="same.safetensors",
        )
    )

    assert base is not None
    assert base.path == (checkpoints / "same.safetensors").resolve()
    assert lora is not None
    assert lora.path == (loras / "same.safetensors").resolve()


@pytest.mark.parametrize("category", ["instantid", "pulid"])
def test_locator_supports_registered_easy_adapter_categories(
    category: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / category
    root.mkdir()
    model = root / "adapter.safetensors"
    model.write_bytes(b"adapter")
    locator = ModelRootLocator({category: [root]})
    resource = replace(
        model_resource(),
        role=ResourceRole.IPADAPTER,
        selected_value="adapter.safetensors",
    )

    located = locator.locate(resource)

    assert located is not None
    assert located.path == model.resolve()
    assert located.category == category


def test_locator_supports_core_hypernetwork_category(tmp_path: Path) -> None:
    root = tmp_path / "hypernetworks"
    root.mkdir()
    model = root / "detail.pt"
    model.write_bytes(b"hypernetwork")
    locator = ModelRootLocator({"hypernetworks": [root]})
    resource = replace(
        model_resource(),
        role=ResourceRole.HYPERNETWORK,
        selected_value="detail.pt",
    )

    located = locator.locate(resource)

    assert located is not None
    assert located.path == model.resolve()
    assert located.category == "hypernetworks"


def test_locator_supports_core_style_model_category(tmp_path: Path) -> None:
    root = tmp_path / "style_models"
    root.mkdir()
    model = root / "style_model.safetensors"
    model.write_bytes(b"style-model")
    locator = ModelRootLocator({"style_models": [root]})
    resource = replace(
        model_resource(),
        role=ResourceRole.STYLE_MODEL,
        kind=ResourceKind.STYLE_MODEL,
        filename=model.name,
        selected_value=model.name,
    )

    located = locator.locate(resource)

    assert located is not None
    assert located.path == model.resolve()
    assert located.category == "style_models"


@pytest.mark.parametrize(
    ("role", "kind", "category"),
    [
        (ResourceRole.VISION_ENCODER, ResourceKind.VISION_ENCODER, "clip_vision"),
        (ResourceRole.VISION_ENCODER, ResourceKind.VISION_ENCODER, "text_encoders"),
        (ResourceRole.VISION_ENCODER, ResourceKind.VISION_ENCODER, "clip"),
        (ResourceRole.MODEL_PATCH, ResourceKind.MODEL_PATCH, "model_patches"),
        (
            ResourceRole.AUXILIARY_MODEL,
            ResourceKind.AUXILIARY_MODEL,
            "geometry_estimation",
        ),
        (ResourceRole.AUXILIARY_MODEL, ResourceKind.AUXILIARY_MODEL, "detection"),
        (ResourceRole.AUXILIARY_MODEL, ResourceKind.AUXILIARY_MODEL, "sams"),
        (ResourceRole.AUXILIARY_MODEL, ResourceKind.AUXILIARY_MODEL, "nlf"),
        (ResourceRole.GLIGEN, ResourceKind.GLIGEN, "gligen"),
        (ResourceRole.UPSCALER, ResourceKind.UPSCALER, "latent_upscale_models"),
    ],
)
def test_locator_supports_core_auxiliary_model_categories(
    role: ResourceRole,
    kind: ResourceKind,
    category: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / category
    root.mkdir()
    model = root / "auxiliary.safetensors"
    model.write_bytes(b"auxiliary")
    locator = ModelRootLocator({category: [root]})
    resource = replace(
        model_resource(),
        role=role,
        kind=kind,
        filename=model.name,
        selected_value=model.name,
    )

    located = locator.locate(resource)

    assert located is not None
    assert located.path == model.resolve()
    assert located.category == category


@pytest.mark.parametrize(
    "selected_value",
    [
        "../outside.gguf",
        "/absolute/model.gguf",
        "C:\\private\\model.gguf",
        "nested//model.gguf",
        "nested/./model.gguf",
        "nested/model.gguf:stream",
        "nested/\u0001model.gguf",
    ],
)
def test_locator_rejects_unsafe_selection_values(
    selected_value: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / "models"
    root.mkdir()
    locator = ModelRootLocator({"diffusion_models": [root]})

    assert locator.locate(_resource(selected_value)) is None


def test_locator_rejects_resolved_path_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "models"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    target = outside / "model.gguf"
    target.write_bytes(b"model")
    link = root / "escape.gguf"
    link.write_bytes(b"placeholder")
    original_resolve = Path.resolve

    def redirect_candidate(path: Path, strict: bool = False) -> Path:
        if path == link:
            return target
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", redirect_candidate)

    assert ModelRootLocator({"diffusion_models": [root]}).locate(_resource("escape.gguf")) is None


def test_locator_returns_none_for_missing_or_unconfigured_resources(
    tmp_path: Path,
) -> None:
    root = tmp_path / "models"
    root.mkdir()
    locator = ModelRootLocator({"diffusion_models": [root]})

    assert locator.locate(_resource("missing.gguf")) is None
    assert ModelRootLocator({}).locate(_resource("missing.gguf")) is None


def test_locator_deduplicates_equivalent_configured_roots(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()

    assert model_files._unique_roots((root, root)) == (root,)


def test_locator_skips_configured_roots_that_do_not_exist(tmp_path: Path) -> None:
    locator = ModelRootLocator({"diffusion_models": [tmp_path / "missing"]})

    assert locator.locate(_resource("model.gguf")) is None


def test_locator_ignores_existing_directories_selected_as_models(
    tmp_path: Path,
) -> None:
    root = tmp_path / "models"
    (root / "directory.gguf").mkdir(parents=True)
    locator = ModelRootLocator({"diffusion_models": [root]})

    assert locator.locate(_resource("directory.gguf")) is None


def test_locator_never_reads_external_model_identifiers_as_local_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "models"
    candidate = root / "organization" / "repository"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"must-not-be-hashed")
    locator = ModelRootLocator({"diffusion_models": [root]})
    resource = replace(
        model_resource(),
        kind=ResourceKind.EXTERNAL_MODEL,
        filename="repository",
        selected_value="organization/repository",
        detection_rule_id="was_diffusers_hub_loader",
    )

    assert locator.locate(resource) is None


def test_registered_roots_handles_bad_adapters_and_filters_values(
    tmp_path: Path,
) -> None:
    folder_paths = ModuleType("folder_paths")

    def raise_for_category(_category: str) -> list[str]:
        raise RuntimeError("adapter unavailable")

    folder_paths.__dict__["get_folder_paths"] = raise_for_category
    assert model_files._registered_roots(folder_paths, "checkpoints") is None

    folder_paths.__dict__["get_folder_paths"] = lambda _category: "not-a-sequence"
    assert model_files._registered_roots(folder_paths, "checkpoints") is None

    root = tmp_path / "models"
    folder_paths.__dict__["get_folder_paths"] = lambda _category: [
        root,
        str(root),
        42,
        None,
    ]
    assert model_files._registered_roots(folder_paths, "checkpoints") == (
        root,
        str(root),
    )


def test_folder_paths_roots_skips_unavailable_categories(tmp_path: Path) -> None:
    folder_paths = ModuleType("folder_paths")
    root = tmp_path / "models"

    def get_folder_paths(category: str) -> list[Path]:
        if category == "clip":
            raise KeyError(category)
        return [root, root]

    folder_paths.__dict__["get_folder_paths"] = get_folder_paths

    roots = model_files._folder_paths_roots(folder_paths)

    assert "clip" not in roots
    assert roots["checkpoints"] == (root,)


def test_model_locator_from_comfy_handles_missing_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_module(_name: str) -> ModuleType:
        raise ImportError("folder_paths unavailable")

    monkeypatch.setattr(importlib, "import_module", missing_module)

    assert model_files.model_locator_from_comfy().locate(_resource("model.gguf")) is None


def test_model_locator_from_comfy_uses_registered_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "models"
    root.mkdir()
    model = root / "model.gguf"
    model.write_bytes(b"model")
    folder_paths = ModuleType("folder_paths")
    folder_paths.__dict__["get_folder_paths"] = lambda category: (
        [root] if category == "diffusion_models" else []
    )
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda _name: folder_paths,
    )

    located = model_files.model_locator_from_comfy().locate(_resource("model.gguf"))

    assert located is not None
    assert located.path == model.resolve()
