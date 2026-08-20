"""Current Civitai Site API identity and enum contracts.

The Site API exposes mutable string enums.  This module is the single,
conservative normalization boundary for values that affect resource identity.
Unknown future values remain untrusted until their semantics are reviewed.
"""

from __future__ import annotations

from ..domain import ResourceRole

SINGLE_HASH_ALGORITHMS = (
    "SHA256",
    "BLAKE3",
    "AutoV3",
    "AutoV2",
    "CRC32",
    "AutoV1",
)
BULK_HASH_ALGORITHMS = frozenset({"SHA256"})

SUPPORTED_MODEL_TYPES = (
    "Checkpoint",
    "TextualInversion",
    "Hypernetwork",
    "AestheticGradient",
    "LORA",
    "LoCon",
    "DoRA",
    "Controlnet",
    "Upscaler",
    "MotionModule",
    "VAE",
    "TextEncoder",
    "UNet",
    "CLIPVision",
    "Poses",
    "Wildcards",
    "Workflows",
    "ComfyWorkflows",
    "Detection",
    "VisionLanguage",
    "CLIP",
    "LLM",
    "Other",
)
SUPPORTED_MODEL_FILE_TYPES = (
    "Model",
    "Text Encoder",
    "Vision Encoder",
    "Pruned Model",
    "Negative",
    "Training Data",
    "VAE",
    "Config",
    "Archive",
    "UNet",
    "Diffusion Model",
    "CLIPVision",
    "ControlNet",
    "Workflow",
    "Upscaler",
    "Enhancement LoRA",
    "Other",
)

_MODEL_TYPE_TO_RESOURCE_TYPE = {
    "aestheticgradient": "ag",
    "checkpoint": "checkpoint",
    "clip": "clip",
    "controlnet": "controlnet",
    "dora": "dora",
    "hypernetwork": "hypernet",
    "locon": "locon",
    "lora": "lora",
    "motionmodule": "motion",
    "textencoder": "text_encoders",
    "textualinversion": "embedding",
    "unet": "unet",
    "upscaler": "upscaler",
    "vae": "vae",
    "visionlanguage": "visionlanguage",
}
_KNOWN_MODEL_TYPES = {value.casefold() for value in SUPPORTED_MODEL_TYPES}
_MODEL_FILE_TYPES = {value.casefold(): value for value in SUPPORTED_MODEL_FILE_TYPES}
_FILE_TYPE_ROLES: dict[str, frozenset[ResourceRole]] = {
    "clipvision": frozenset({ResourceRole.VISION_ENCODER}),
    "controlnet": frozenset({ResourceRole.CONTROLNET, ResourceRole.IPADAPTER}),
    "diffusion model": frozenset({ResourceRole.BASE_MODEL}),
    "enhancement lora": frozenset({ResourceRole.LORA}),
    "negative": frozenset({ResourceRole.EMBEDDING}),
    "pruned model": frozenset({ResourceRole.BASE_MODEL}),
    "text encoder": frozenset({ResourceRole.TEXT_ENCODER}),
    "unet": frozenset({ResourceRole.BASE_MODEL}),
    "upscaler": frozenset({ResourceRole.UPSCALER}),
    "vae": frozenset({ResourceRole.VAE}),
    "vision encoder": frozenset({ResourceRole.VISION_ENCODER}),
}
_FORMAT_ALIASES = {
    "safetensor": "safetensor",
    "safetensors": "safetensor",
}


def model_type_to_resource_type(value: str | None) -> str | None:
    """Map a current Site API ModelType to a conservative AIR-facing type."""

    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized not in _KNOWN_MODEL_TYPES:
        return None
    return _MODEL_TYPE_TO_RESOURCE_TYPE.get(normalized, "unknown")


def normalize_model_file_type(value: str | None) -> str | None:
    """Return the current canonical Site API ModelFileType label."""

    if value is None:
        return None
    return _MODEL_FILE_TYPES.get(value.strip().casefold())


def model_file_type_matches_role(
    role: ResourceRole,
    file_type: str | None,
) -> bool:
    """Return whether a file enum is explicit evidence for a resource role."""

    normalized = normalize_model_file_type(file_type)
    if normalized is None:
        return False
    return role in _FILE_TYPE_ROLES.get(normalized.casefold(), ())


def normalize_model_file_format(value: str | None) -> str | None:
    """Normalize a trustworthy API file format for optional AIR qualification."""

    if value is None:
        return None
    normalized = value.strip().casefold()
    if not normalized or normalized == "other":
        return None
    return _FORMAT_ALIASES.get(normalized, normalized)


__all__ = [
    "BULK_HASH_ALGORITHMS",
    "SINGLE_HASH_ALGORITHMS",
    "SUPPORTED_MODEL_FILE_TYPES",
    "SUPPORTED_MODEL_TYPES",
    "model_file_type_matches_role",
    "model_type_to_resource_type",
    "normalize_model_file_format",
    "normalize_model_file_type",
]
