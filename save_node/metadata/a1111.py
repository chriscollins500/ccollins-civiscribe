"""A1111-style human-readable parameter text."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from .schema import (
    GenerationSettings,
    HashMetadata,
    PromptMetadata,
    ResolvedResource,
)
from .serialize import to_json_text
from ..security.redaction import sanitize_metadata_text


def build_a1111_parameters(
    *,
    prompt: PromptMetadata,
    generation: GenerationSettings,
    resources: tuple[ResolvedResource, ...] = (),
    hashes: HashMetadata | None = None,
    include_empty_negative_prompt: bool = True,
) -> str:
    """Build an A1111-compatible parameters block from known metadata."""

    lines: list[str] = [sanitize_metadata_text(prompt.positive or "")]
    settings = _build_settings_fields(
        generation=generation,
        resources=resources,
        hashes=hashes or HashMetadata(),
    )

    if prompt.negative:
        lines.append(f"Negative prompt: {sanitize_metadata_text(prompt.negative)}")
    elif include_empty_negative_prompt and settings:
        lines.append("Negative prompt:")

    if settings:
        lines.append(", ".join(f"{key}: {value}" for key, value in settings))

    return "\n".join(lines)


def build_phase_one_parameters() -> str:
    """Legacy compatibility wrapper for older external callers."""

    return build_a1111_parameters(
        prompt=PromptMetadata(),
        generation=GenerationSettings(),
    )


def build_civitai_resources_for_parameters(resources: tuple[ResolvedResource, ...]) -> list[dict[str, Any]]:
    """Return parser-friendly resolved Civitai resource objects."""

    return _resources_for_parameters(resources)


def _build_settings_fields(
    *,
    generation: GenerationSettings,
    resources: tuple[ResolvedResource, ...],
    hashes: HashMetadata,
) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    _add(fields, "Steps", generation.steps)
    _add(fields, "Sampler", generation.sampler)
    _add(fields, "Schedule type", generation.scheduler)
    _add(fields, "CFG scale", _format_number(generation.cfg_scale))
    if generation.cfg_scale is None:
        _add(fields, "Guidance", _format_number(_flux_guidance(generation.extra)))
    _add(fields, "Seed", generation.seed)
    if generation.width is not None and generation.height is not None:
        _add(fields, "Size", f"{generation.width}x{generation.height}")
    _add(fields, "Batch size", generation.batch_size)
    _add(fields, "Model", generation.model)
    _add(fields, "Model hash", generation.model_hash)
    _add(fields, "VAE", generation.vae)
    _add(fields, "VAE hash", generation.vae_hash)
    _add(fields, "Clip skip", generation.clip_skip)
    _add(fields, "Denoising strength", _format_number(generation.denoising_strength))
    _add(fields, "Version", generation.version)

    hash_json = hashes.to_json()
    if hash_json:
        _add(fields, "Hashes", to_json_text(hash_json))

    resource_json = _resources_for_parameters(resources)
    if resource_json:
        _add(fields, "Civitai resources", to_json_text(resource_json))

    return fields


def _resources_for_parameters(resources: tuple[ResolvedResource, ...]) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = []
    for resource in resources:
        item: dict[str, Any] = {}
        metadata = resource.resource
        model_version_id = metadata.civitai_model_version_id
        if model_version_id is None and metadata.air is not None:
            model_version_id = metadata.air.model_version_id
        model_id = metadata.civitai_model_id
        if model_id is None and metadata.air is not None:
            model_id = metadata.air.model_id
        if model_version_id is None:
            continue
        resource_type = _civitai_facing_resource_type(resource)
        if resource_type is None:
            continue
        item["type"] = resource_type
        if metadata.air:
            emitted_air = metadata.air.canonical or metadata.air.raw
            item["air"] = emitted_air
            item["urn"] = emitted_air
            if metadata.air.file_id:
                item["fileId"] = metadata.air.file_id
            if metadata.air.format:
                item["format"] = metadata.air.format
        if model_id is not None:
            item["modelId"] = model_id
        item["modelVersionId"] = model_version_id
        if metadata.role == "lora" or metadata.type == "lora":
            weight = metadata.strength_model if metadata.strength_model is not None else metadata.strength
            if weight is not None:
                item["weight"] = weight
            if metadata.strength is not None:
                item["strength"] = metadata.strength
            if metadata.strength_model is not None:
                item["strengthModel"] = metadata.strength_model
            if metadata.strength_clip is not None:
                item["strengthClip"] = metadata.strength_clip
        if not item:
            continue
        data.append(item)
    return data


def _civitai_facing_resource_type(resource: ResolvedResource) -> str | None:
    metadata = resource.resource
    if metadata.air is not None:
        return metadata.air.type

    raw_type = _normalize_resource_label(metadata.type)
    raw_role = _normalize_resource_label(metadata.role)
    if raw_type in {"checkpoint", "lora", "embedding", "vae", "controlnet", "upscaler", "unet", "other", "image"}:
        return raw_type
    if raw_type == "diffusionmodel":
        return "diffusionmodel"

    safe_primary_types = {"diffusion_model", "diffusion model", "base_model", "base model", "unet"}
    if (
        metadata.civitai_model_version_id is not None
        and metadata.metadata.get("identityIncomplete") is True
        and (
            raw_role in {"checkpoint", "base_model", "base model"}
            or raw_type in safe_primary_types
            or metadata.metadata.get("primaryModel") is True
        )
    ):
        return "checkpoint"

    if raw_role in {"lora", "vae", "upscaler", "controlnet", "embedding"}:
        return raw_role
    return None


def _normalize_resource_label(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _add(fields: list[tuple[str, str]], key: str, value: object | None) -> None:
    if value is None or value == "":
        return
    fields.append((sanitize_metadata_text(key), sanitize_metadata_text(str(value))))


def _format_number(value: float | None) -> str | None:
    if value is None:
        return None
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _flux_guidance(extra: Any) -> float | None:
    if not isinstance(extra, dict):
        return None
    value = extra.get("fluxGuidance")
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _basename(value: str) -> str:
    windows_name = PureWindowsPath(value).name
    posix_name = PurePosixPath(windows_name).name
    return posix_name or windows_name or value


def _relative_or_basename(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or _looks_windows_absolute(normalized):
        return _basename(normalized)
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return _basename(normalized)
    return "/".join(parts)


def _looks_windows_absolute(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] == "/" and value[0].isalpha()


__all__ = ["build_a1111_parameters", "build_civitai_resources_for_parameters", "build_phase_one_parameters"]
