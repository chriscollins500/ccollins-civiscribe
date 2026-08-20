"""Shared Civitai resource-type compatibility rules."""

from __future__ import annotations

from ..domain import ResourceIdentity, ResourceRole
from .civitai_contract import model_file_type_matches_role

_ROLE_TYPES: dict[ResourceRole, frozenset[str]] = {
    ResourceRole.BASE_MODEL: frozenset({"checkpoint", "diffusionmodel", "unet"}),
    ResourceRole.CONTROLNET: frozenset({"controlnet"}),
    ResourceRole.EMBEDDING: frozenset({"embedding"}),
    ResourceRole.HYPERNETWORK: frozenset({"hypernet"}),
    ResourceRole.IPADAPTER: frozenset({"controlnet"}),
    ResourceRole.LORA: frozenset({"dora", "locon", "lora", "lycoris"}),
    ResourceRole.STYLE_MODEL: frozenset({"ag", "unknown"}),
    ResourceRole.TEXT_ENCODER: frozenset(
        {"clip", "text_encoders", "textencoder", "visionlanguage"}
    ),
    ResourceRole.VISION_ENCODER: frozenset({"clipvision", "unknown"}),
    ResourceRole.MODEL_PATCH: frozenset({"unknown"}),
    ResourceRole.AUXILIARY_MODEL: frozenset({"unknown"}),
    ResourceRole.MOTION_MODULE: frozenset({"motion"}),
    ResourceRole.GLIGEN: frozenset({"unknown"}),
    ResourceRole.UPSCALER: frozenset({"upscaler"}),
    ResourceRole.VAE: frozenset({"vae"}),
}

_AMBIGUOUS_ROLE_TYPES: dict[ResourceRole, frozenset[str]] = {
    ResourceRole.BASE_MODEL: frozenset({"other", "unknown"}),
    ResourceRole.CONTROLNET: frozenset({"other", "unknown"}),
    ResourceRole.EMBEDDING: frozenset({"other", "unknown"}),
    ResourceRole.HYPERNETWORK: frozenset({"other", "unknown"}),
    ResourceRole.IPADAPTER: frozenset({"checkpoint", "other", "unknown"}),
    ResourceRole.LORA: frozenset({"other", "unknown"}),
    ResourceRole.STYLE_MODEL: frozenset({"other"}),
    # Parent checkpoint listings commonly bundle encoder files. They are not
    # standalone text-encoder identities and must not become extra checkpoints.
    ResourceRole.TEXT_ENCODER: frozenset(),
    ResourceRole.VISION_ENCODER: frozenset({"other"}),
    ResourceRole.MODEL_PATCH: frozenset({"checkpoint", "controlnet", "other"}),
    ResourceRole.AUXILIARY_MODEL: frozenset({"other"}),
    ResourceRole.MOTION_MODULE: frozenset({"other", "unknown"}),
    ResourceRole.GLIGEN: frozenset({"checkpoint", "controlnet", "other"}),
    ResourceRole.UPSCALER: frozenset({"other", "unknown"}),
    ResourceRole.VAE: frozenset({"other", "unknown"}),
}


def resource_type_matches_role(
    role: ResourceRole,
    resource_type: str | None,
    *,
    allow_ambiguous: bool = False,
) -> bool:
    """Return whether a Civitai/AIR type represents the active resource role."""

    if resource_type is None:
        return False
    normalized = resource_type.casefold()
    if normalized in _ROLE_TYPES[role]:
        return True
    return allow_ambiguous and normalized in _AMBIGUOUS_ROLE_TYPES[role]


def resource_type_is_ambiguous(role: ResourceRole, resource_type: str | None) -> bool:
    """Return whether a type is only a legacy/ambiguous match for a role."""

    return resource_type is not None and resource_type.casefold() in _AMBIGUOUS_ROLE_TYPES[role]


def identity_matches_role(
    role: ResourceRole,
    identity: ResourceIdentity,
    *,
    allow_ambiguous: bool = False,
    allow_file_evidence: bool = True,
) -> bool:
    """Match an identity by AIR type or explicit Civitai file-type evidence."""

    return resource_type_matches_role(
        role,
        identity.resource_type,
        allow_ambiguous=allow_ambiguous,
    ) or (allow_file_evidence and model_file_type_matches_role(role, identity.file_type))


__all__ = [
    "identity_matches_role",
    "resource_type_is_ambiguous",
    "resource_type_matches_role",
]
