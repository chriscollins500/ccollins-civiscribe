"""Safe model file resolution against approved ComfyUI model roots."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Mapping

from ..metadata.schema import ModelResourceMetadata, ValidationIssue


RESOURCE_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "checkpoint": ("checkpoints",),
    "base_model": ("diffusion_models", "unet", "checkpoints"),
    "unet": ("diffusion_models", "unet"),
    "lora": ("loras",),
    "vae": ("vae",),
    "text_encoder": ("clip", "text_encoders"),
    "clip": ("clip", "text_encoders"),
    "controlnet": ("controlnet",),
    "ipadapter": ("ipadapter", "ipadapter_models"),
    "upscaler": ("upscale_models",),
    "embedding": ("embeddings",),
}


@dataclass(frozen=True)
class ModelResolution:
    path: Path | None
    status: str
    warnings: tuple[ValidationIssue, ...] = ()
    cache_category: str | None = None
    cache_selected_value: str | None = None


class ModelRootResolver:
    """Resolve untrusted Comfy model selections inside approved roots only."""

    def __init__(self, roots: Mapping[str, Iterable[str | os.PathLike[str]]]) -> None:
        normalized: dict[str, tuple[Path, ...]] = {}
        for category, paths in roots.items():
            safe_roots: list[Path] = []
            for root in paths:
                path = Path(root).expanduser().resolve(strict=False)
                safe_roots.append(path)
            normalized[str(category)] = tuple(dict.fromkeys(safe_roots))
        self.roots = normalized

    @classmethod
    def from_comfy(cls) -> "ModelRootResolver":
        roots: dict[str, list[Path]] = {}
        try:
            import folder_paths
        except Exception:  # pragma: no cover - used outside ComfyUI
            return cls({})

        for category in sorted({alias for aliases in RESOURCE_CATEGORY_ALIASES.values() for alias in aliases}):
            category_roots: list[Path] = []
            try:
                category_roots.extend(Path(path) for path in folder_paths.get_folder_paths(category))
            except Exception:
                pass

            folder_names = getattr(folder_paths, "folder_names_and_paths", {})
            if category in folder_names:
                raw_entry = folder_names[category]
                raw_paths = raw_entry[0] if isinstance(raw_entry, tuple) and raw_entry else raw_entry
                if isinstance(raw_paths, (list, tuple, set)):
                    category_roots.extend(Path(path) for path in raw_paths)

            if category_roots:
                roots[category] = category_roots

        return cls(roots)

    def resolve(self, resource: ModelResourceMetadata) -> ModelResolution:
        source = resource.source_value or resource.selected_value or resource.filename
        if not source:
            return _warning_result(
                "resource_file_not_resolved",
                "Resource has no selected model file value",
                resource,
            )

        source_text = str(source).strip()
        if not source_text:
            return _warning_result(
                "resource_file_not_resolved",
                "Resource selected model file value is empty",
                resource,
            )

        normalized_source = source_text.replace("\\", "/")
        if _has_traversal(normalized_source):
            return _warning_result(
                "resource_path_traversal_rejected",
                "Resource path traversal was rejected",
                resource,
            )
        cache_category = _cache_category(resource)
        cache_selected_value = _cache_selected_value(normalized_source)

        roots = self.roots_for_resource(resource)
        if not roots:
            return _warning_result(
                "resource_model_roots_missing",
                f"No approved model roots are configured for resource role {resource.role}",
                resource,
            )

        candidate_path = Path(normalized_source)
        if candidate_path.is_absolute() or _looks_windows_absolute(normalized_source):
            return self._resolve_absolute(
                Path(normalized_source),
                roots,
                resource,
                cache_category,
                cache_selected_value,
            )

        relative_parts = [part for part in PurePosixPath(normalized_source).parts if part not in {"", "."}]
        if not relative_parts:
            return _warning_result(
                "resource_file_not_resolved",
                "Resource selected model file value is empty after normalization",
                resource,
            )

        candidates = [root.joinpath(*relative_parts) for root in roots]
        existing = [candidate for candidate in candidates if candidate.exists()]
        if existing:
            return self._check_inside_roots(
                existing[0],
                roots,
                resource,
                cache_category,
                cache_selected_value,
            )

        missing_candidate = candidates[0]
        inside = self._path_inside_any_root(missing_candidate, roots)
        if not inside:
            return _warning_result(
                "resource_path_outside_model_roots",
                "Resource path resolved outside approved model roots",
                resource,
            )
        return ModelResolution(
            path=missing_candidate,
            status="missing",
            cache_category=cache_category,
            cache_selected_value=cache_selected_value,
            warnings=(
                ValidationIssue(
                    code="resource_file_missing",
                    message=f"Resource file was not found under approved model roots: {_basename(normalized_source)}",
                    field=_resource_field(resource),
                ),
            ),
        )

    def roots_for_resource(self, resource: ModelResourceMetadata) -> tuple[Path, ...]:
        aliases = RESOURCE_CATEGORY_ALIASES.get(resource.role)
        if aliases is None and resource.type:
            aliases = RESOURCE_CATEGORY_ALIASES.get(resource.type)
        if aliases is None:
            aliases = (resource.role,)

        roots: list[Path] = []
        for alias in aliases:
            roots.extend(self.roots.get(alias, ()))
        return tuple(dict.fromkeys(roots))

    def _resolve_absolute(
        self,
        candidate: Path,
        roots: tuple[Path, ...],
        resource: ModelResourceMetadata,
        cache_category: str,
        cache_selected_value: str,
    ) -> ModelResolution:
        if not self._path_inside_any_root(candidate, roots):
            return _warning_result(
                "resource_absolute_path_outside_roots",
                "Absolute resource path was rejected because it is outside approved model roots",
                resource,
            )
        return self._check_inside_roots(candidate, roots, resource, cache_category, cache_selected_value)

    def _check_inside_roots(
        self,
        candidate: Path,
        roots: tuple[Path, ...],
        resource: ModelResourceMetadata,
        cache_category: str,
        cache_selected_value: str,
    ) -> ModelResolution:
        if not self._path_inside_any_root(candidate, roots):
            return _warning_result(
                "resource_path_outside_model_roots",
                "Resource path resolved outside approved model roots",
                resource,
            )
        if not candidate.exists():
            return ModelResolution(
                path=candidate,
                status="missing",
                cache_category=cache_category,
                cache_selected_value=cache_selected_value,
                warnings=(
                    ValidationIssue(
                        code="resource_file_missing",
                        message=f"Resource file was not found under approved model roots: {_basename(str(candidate))}",
                        field=_resource_field(resource),
                    ),
                ),
            )
        return ModelResolution(
            path=candidate.resolve(strict=True),
            status="resolved",
            cache_category=cache_category,
            cache_selected_value=cache_selected_value,
        )

    def _path_inside_any_root(self, candidate: Path, roots: tuple[Path, ...]) -> bool:
        try:
            resolved_candidate = candidate.resolve(strict=candidate.exists())
        except OSError:
            resolved_candidate = candidate.resolve(strict=False)

        for root in roots:
            try:
                resolved_root = root.resolve(strict=root.exists())
                common = os.path.commonpath(
                    [
                        os.path.normcase(str(resolved_root)),
                        os.path.normcase(str(resolved_candidate)),
                    ]
                )
            except (OSError, ValueError):
                continue
            if common == os.path.normcase(str(resolved_root)):
                return True
        return False


def _warning_result(
    code: str,
    message: str,
    resource: ModelResourceMetadata,
) -> ModelResolution:
    return ModelResolution(
        path=None,
        status=code,
        warnings=(ValidationIssue(code=code, message=message, field=_resource_field(resource)),),
    )


def _has_traversal(value: str) -> bool:
    return any(part == ".." for part in PurePosixPath(value).parts)


def _looks_windows_absolute(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] == "/" and value[0].isalpha()


def _basename(value: str) -> str:
    windows_name = PureWindowsPath(value).name
    posix_name = PurePosixPath(windows_name).name
    return posix_name or windows_name or "resource"


def _cache_category(resource: ModelResourceMetadata) -> str:
    return resource.role or resource.type or "model"


def _cache_selected_value(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or _looks_windows_absolute(normalized):
        return _basename(normalized)
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        return _basename(normalized)
    return "/".join(parts)


def _resource_field(resource: ModelResourceMetadata) -> str:
    if resource.node_id:
        return f"resources[nodeId={resource.node_id}]"
    return "resources"


__all__ = ["ModelResolution", "ModelRootResolver", "RESOURCE_CATEGORY_ALIASES"]
