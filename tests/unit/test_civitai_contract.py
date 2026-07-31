from __future__ import annotations

import pytest

from civiscribe.domain import ResourceRole
from civiscribe.identity.civitai_contract import (
    BULK_HASH_ALGORITHMS,
    SINGLE_HASH_ALGORITHMS,
    SUPPORTED_MODEL_FILE_TYPES,
    SUPPORTED_MODEL_TYPES,
    model_file_type_matches_role,
    model_type_to_resource_type,
    normalize_model_file_format,
    normalize_model_file_type,
)


@pytest.mark.parametrize(
    ("model_type", "resource_type"),
    [
        ("Checkpoint", "checkpoint"),
        ("TextualInversion", "embedding"),
        ("Hypernetwork", "hypernet"),
        ("AestheticGradient", "unknown"),
        ("LORA", "lora"),
        ("LoCon", "locon"),
        ("DoRA", "dora"),
        ("Controlnet", "controlnet"),
        ("Upscaler", "upscaler"),
        ("MotionModule", "motion"),
        ("VAE", "vae"),
        ("TextEncoder", "text_encoders"),
        ("UNet", "unet"),
        ("CLIPVision", "unknown"),
        ("Poses", "unknown"),
        ("Wildcards", "unknown"),
        ("Workflows", "unknown"),
        ("Detection", "unknown"),
        ("VisionLanguage", "unknown"),
        ("CLIP", "unknown"),
        ("LLM", "unknown"),
        ("Other", "unknown"),
    ],
)
def test_current_civitai_model_types_have_conservative_fallbacks(
    model_type: str,
    resource_type: str,
) -> None:
    assert model_type in SUPPORTED_MODEL_TYPES
    assert model_type_to_resource_type(model_type) == resource_type
    assert model_type_to_resource_type(model_type.swapcase()) == resource_type


@pytest.mark.parametrize(
    ("file_type", "roles"),
    [
        ("Model", ()),
        ("Text Encoder", (ResourceRole.TEXT_ENCODER,)),
        ("Vision Encoder", (ResourceRole.VISION_ENCODER,)),
        ("Pruned Model", (ResourceRole.BASE_MODEL,)),
        ("Negative", (ResourceRole.EMBEDDING,)),
        ("Training Data", ()),
        ("VAE", (ResourceRole.VAE,)),
        ("Config", ()),
        ("Archive", ()),
        ("UNet", (ResourceRole.BASE_MODEL,)),
        ("Diffusion Model", (ResourceRole.BASE_MODEL,)),
        ("CLIPVision", (ResourceRole.VISION_ENCODER,)),
        (
            "ControlNet",
            (ResourceRole.CONTROLNET, ResourceRole.IPADAPTER),
        ),
        ("Workflow", ()),
        ("Upscaler", (ResourceRole.UPSCALER,)),
        ("Enhancement LoRA", (ResourceRole.LORA,)),
        ("Other", ()),
    ],
)
def test_current_civitai_file_types_supply_only_explicit_role_evidence(
    file_type: str,
    roles: tuple[ResourceRole, ...],
) -> None:
    assert file_type in SUPPORTED_MODEL_FILE_TYPES
    assert normalize_model_file_type(file_type) is not None
    for role in ResourceRole:
        assert model_file_type_matches_role(role, file_type) is (role in roles)


def test_unknown_civitai_types_remain_untrusted() -> None:
    assert model_type_to_resource_type("FutureType") is None
    assert normalize_model_file_type("Future File Type") is None
    assert not model_file_type_matches_role(
        ResourceRole.BASE_MODEL,
        "Future File Type",
    )


@pytest.mark.parametrize("value", [None, "", "Other"])
def test_model_file_format_omits_unknown_or_empty_values(value: str | None) -> None:
    assert normalize_model_file_format(value) is None


def test_hash_endpoint_capabilities_match_current_site_api() -> None:
    assert SINGLE_HASH_ALGORITHMS == (
        "SHA256",
        "BLAKE3",
        "AutoV3",
        "AutoV2",
        "CRC32",
        "AutoV1",
    )
    assert frozenset({"SHA256"}) == BULK_HASH_ALGORITHMS
