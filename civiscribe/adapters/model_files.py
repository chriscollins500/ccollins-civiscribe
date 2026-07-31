"""Resolve scanner-selected model files only beneath approved ComfyUI roots."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import ModuleType

from ..domain import ResourceKind, ResourceRecord, ResourceRole
from ..identity.types import LocatedResourceFile

_ASCII_CONTROL_BOUNDARY = 32
RESOURCE_CATEGORY_ALIASES: dict[ResourceRole, tuple[str, ...]] = {
    ResourceRole.BASE_MODEL: ("diffusion_models", "unet", "unet_gguf", "checkpoints"),
    ResourceRole.LORA: ("loras",),
    ResourceRole.VAE: ("vae",),
    ResourceRole.TEXT_ENCODER: ("text_encoders", "clip", "clip_gguf"),
    ResourceRole.EMBEDDING: ("embeddings",),
    ResourceRole.HYPERNETWORK: ("hypernetworks",),
    ResourceRole.CONTROLNET: ("controlnet",),
    ResourceRole.IPADAPTER: (
        "ipadapter",
        "ipadapter_models",
        "instantid",
        "pulid",
        "diffusion_models",
    ),
    ResourceRole.STYLE_MODEL: ("style_models",),
    ResourceRole.VISION_ENCODER: ("clip_vision", "text_encoders", "clip"),
    ResourceRole.MODEL_PATCH: ("model_patches", "diffusion_models", "checkpoints"),
    ResourceRole.AUXILIARY_MODEL: (
        "geometry_estimation",
        "detection",
        "sams",
        "nlf",
    ),
    ResourceRole.MOTION_MODULE: ("animatediff_models",),
    ResourceRole.GLIGEN: ("gligen",),
    ResourceRole.UPSCALER: ("upscale_models", "latent_upscale_models"),
}


def _safe_relative_parts(value: str) -> tuple[str, ...] | None:
    normalized = value.replace("\\", "/")
    windows = PureWindowsPath(value)
    posix = PurePosixPath(normalized)
    if (
        not normalized
        or windows.drive
        or windows.root
        or posix.is_absolute()
        or ":" in normalized
        or any(part in {"", ".", ".."} for part in posix.parts)
        or any(ord(character) < _ASCII_CONTROL_BOUNDARY for character in normalized)
    ):
        return None
    return posix.parts


def _unique_roots(values: Iterable[str | Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for value in values:
        root = Path(value)
        key = str(root.resolve(strict=False)).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(root)
    return tuple(result)


class ModelRootLocator:
    """Locate exact selected resource values beneath configured model roots."""

    def __init__(self, roots: Mapping[str, Iterable[str | Path]]) -> None:
        self._roots = {
            category: _unique_roots(values) for category, values in roots.items() if category
        }

    def locate(self, resource: ResourceRecord) -> LocatedResourceFile | None:
        """Return an approved existing file or ``None`` without guessing."""

        if resource.kind is ResourceKind.EXTERNAL_MODEL:
            return None
        parts = _safe_relative_parts(resource.selected_value)
        if parts is None:
            return None
        aliases = RESOURCE_CATEGORY_ALIASES[resource.role]
        variants = [parts]
        if len(parts) > 1 and parts[0].casefold() in {alias.casefold() for alias in aliases}:
            variants.insert(0, parts[1:])

        for category in aliases:
            for configured_root in self._roots.get(category, ()):
                try:
                    root = configured_root.resolve(strict=True)
                except OSError:
                    continue
                for relative_parts in variants:
                    try:
                        candidate = root.joinpath(*relative_parts).resolve(strict=True)
                        candidate.relative_to(root)
                    except (OSError, ValueError):
                        continue
                    if candidate.is_file():
                        return LocatedResourceFile(
                            path=candidate,
                            approved_root=root,
                            category=category,
                            selected_value="/".join(parts),
                        )
        return None


def _folder_paths_roots(
    folder_paths_module: ModuleType,
) -> dict[str, tuple[Path, ...]]:
    roots: dict[str, tuple[Path, ...]] = {}
    categories = {alias for aliases in RESOURCE_CATEGORY_ALIASES.values() for alias in aliases}
    for category in sorted(categories):
        values = _registered_roots(folder_paths_module, category)
        if values is not None:
            roots[category] = _unique_roots(values)
    return roots


def _registered_roots(
    folder_paths_module: ModuleType,
    category: str,
) -> tuple[str | Path, ...] | None:
    try:
        values = folder_paths_module.get_folder_paths(category)
    except Exception:
        return None
    if not isinstance(values, list | tuple):
        return None
    return tuple(value for value in values if isinstance(value, str | Path))


def model_locator_from_comfy() -> ModelRootLocator:
    """Build a locator from current ComfyUI model roots without hard-coded paths."""

    try:
        folder_paths_module = importlib.import_module("folder_paths")
    except ImportError:
        return ModelRootLocator({})
    return ModelRootLocator(_folder_paths_roots(folder_paths_module))


__all__ = [
    "RESOURCE_CATEGORY_ALIASES",
    "ModelRootLocator",
    "model_locator_from_comfy",
]
