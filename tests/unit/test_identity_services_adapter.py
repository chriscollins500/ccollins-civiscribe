from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

from civiscribe.adapters import identity_services as adapter
from civiscribe.adapters.identity_services import identity_services_from_comfy

LOOKUP_TIMEOUT_SECONDS = 9.0


def _folder_paths(
    *,
    user_directory: Path,
    model_root: Path,
) -> ModuleType:
    module = ModuleType("folder_paths")
    module.get_user_directory = lambda: str(user_directory)  # type: ignore[attr-defined]
    module.get_folder_paths = (  # type: ignore[attr-defined]
        lambda category: [str(model_root)] if category == "checkpoints" else []
    )
    return module


def test_services_use_comfy_user_directory_and_keep_lookup_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_directory = tmp_path / "user"
    model_root = tmp_path / "models"
    module = _folder_paths(user_directory=user_directory, model_root=model_root)
    monkeypatch.setattr(adapter, "_FOLDER_PATHS_MODULE", module)

    services = identity_services_from_comfy(output_root=tmp_path / "output")

    assert services.hash_cache is not None
    assert services.identity_cache is not None
    assert services.civitai is not None
    assert services.civitai.config.enabled is False
    expected = user_directory / adapter.CACHE_DIRECTORY_NAME
    assert services.hash_cache.store.path == expected / "hash-cache.json"
    assert services.identity_cache.store.path == expected / "identity-cache.json"
    assert not expected.exists()


def test_services_fall_back_to_output_for_unavailable_user_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _folder_paths(
        user_directory=tmp_path / "unused",
        model_root=tmp_path / "models",
    )
    module.get_user_directory = (  # type: ignore[attr-defined]
        lambda: (_ for _ in ()).throw(OSError("private"))
    )
    monkeypatch.setattr(adapter, "_FOLDER_PATHS_MODULE", module)
    output_root = tmp_path / "output"

    services = identity_services_from_comfy(
        output_root=output_root,
        enable_lookup=True,
        lookup_timeout_seconds=LOOKUP_TIMEOUT_SECONDS,
    )

    assert services.hash_cache is not None
    assert services.civitai is not None
    assert services.civitai.config.enabled is True
    assert services.civitai.config.timeout_seconds == LOOKUP_TIMEOUT_SECONDS
    assert services.hash_cache.store.path.parent == (
        output_root / f".{adapter.CACHE_DIRECTORY_NAME}"
    )


def test_services_degrade_cleanly_when_comfy_module_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "_FOLDER_PATHS_MODULE", None)

    services = identity_services_from_comfy(output_root=tmp_path)

    assert services.locator is None
    assert services.hash_cache is None
    assert services.identity_cache is None
    assert services.civitai is not None
    assert services.civitai.config.enabled is False
