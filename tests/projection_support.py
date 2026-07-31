"""Shared immutable facts for phase-five projection tests."""

from __future__ import annotations

from dataclasses import dataclass

from civiscribe.domain import (
    Diagnostics,
    GenerationRecord,
    GenerationSettings,
    GeneratorRecord,
    HashRecord,
    IdentitySource,
    ImageFormat,
    ImageRecord,
    PromptField,
    PromptRecord,
    ResourceIdentity,
    ResourceKind,
    ResourceRecord,
    ResourceRole,
    ResourceStatus,
    ResourceStrengths,
    WorkflowKind,
)

MODEL_AUTO_V2 = "1234567890"
MODEL_SHA256 = MODEL_AUTO_V2 + ("a" * 54)
MODEL_ID = 2432159
MODEL_VERSION_ID = 2734704
VAE_AUTO_V2 = "abcdef1234"
LORA_AUTO_V2 = "1111111111"
LORA_WEIGHT = 0.75
LORA_MODEL_STRENGTH = 0.8
LORA_CLIP_STRENGTH = 0.6
EMBED_AUTO_V2 = "2222222222"
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 768
CFG_SCALE = 7.0
DENOISE = 0.75


@dataclass(frozen=True, slots=True)
class _IdentityFixture:
    resource_type: str
    model_id: int
    model_version_id: int
    canonical_air: str
    file_id: str
    model_name: str
    version_name: str


def _identity(
    fixture: _IdentityFixture,
    *,
    source: IdentitySource = IdentitySource.API,
) -> ResourceIdentity:
    return ResourceIdentity(
        source=source,
        raw_air=fixture.canonical_air,
        canonical_air=fixture.canonical_air,
        ecosystem="flux2",
        resource_type=fixture.resource_type,
        identity_source="civitai",
        identity_id=str(fixture.model_id),
        identity_version=str(fixture.model_version_id),
        model_id=fixture.model_id,
        model_version_id=fixture.model_version_id,
        file_id=fixture.file_id,
        format="safetensor",
        model_name=fixture.model_name,
        model_version_name=fixture.version_name,
    )


def model_resource() -> ResourceRecord:
    """Return the selected resolved base-model fixture."""

    return ResourceRecord(
        key="1:unet_name",
        role=ResourceRole.BASE_MODEL,
        kind=ResourceKind.DIFFUSION_MODEL,
        node_id="1",
        node_class="UnetLoaderGGUF",
        filename="swiftFastAndDetailed_neo.gguf",
        selected_value="diffusion_models/swiftFastAndDetailed_neo.gguf",
        detection_rule_id="unet_loader",
        hashes=HashRecord(
            auto_v1="1234abcd",
            auto_v2=MODEL_AUTO_V2,
            auto_v3="123456789abc",
            sha256=MODEL_SHA256,
            crc32="ABCDEF12",
            blake3="b" * 64,
        ),
        identity=_identity(
            _IdentityFixture(
                resource_type="checkpoint",
                model_id=MODEL_ID,
                model_version_id=MODEL_VERSION_ID,
                canonical_air=(
                    "urn:air:flux2:checkpoint:civitai:2432159@2734704+2402203.safetensor"
                ),
                file_id="2402203",
                model_name="SWIFT! Fast and detailed ZIT model",
                version_name="NEO",
            )
        ),
        status=ResourceStatus.RESOLVED,
    )


def vae_resource() -> ResourceRecord:
    """Return the selected resolved VAE fixture."""

    return ResourceRecord(
        key="5:vae_name",
        role=ResourceRole.VAE,
        kind=ResourceKind.VAE,
        node_id="5",
        node_class="VAELoader",
        filename="ae.safetensors",
        selected_value="vae/ae.safetensors",
        detection_rule_id="vae_loader",
        hashes=HashRecord(auto_v2=VAE_AUTO_V2),
        identity=_identity(
            _IdentityFixture(
                resource_type="vae",
                model_id=300,
                model_version_id=301,
                canonical_air="urn:air:flux2:vae:civitai:300@301+302.safetensor",
                file_id="302",
                model_name="Flux VAE",
                version_name="ae",
            )
        ),
        status=ResourceStatus.RESOLVED,
    )


def lora_resource() -> ResourceRecord:
    """Return one resolved weighted LoRA fixture."""

    return ResourceRecord(
        key="2:lora_name",
        role=ResourceRole.LORA,
        kind=ResourceKind.LORA,
        node_id="2",
        node_class="LoraLoader",
        filename="ProjectRealismPhotoLora_v1.safetensors",
        selected_value="loras/ProjectRealismPhotoLora_v1.safetensors",
        strengths=ResourceStrengths(
            weight=LORA_WEIGHT,
            model=LORA_MODEL_STRENGTH,
            clip=LORA_CLIP_STRENGTH,
        ),
        detection_rule_id="lora_loader",
        hashes=HashRecord(auto_v2=LORA_AUTO_V2),
        identity=_identity(
            _IdentityFixture(
                resource_type="lora",
                model_id=400,
                model_version_id=401,
                canonical_air="urn:air:flux2:lora:civitai:400@401+402.safetensor",
                file_id="402",
                model_name="Project Realism Photo",
                version_name="v1",
            )
        ),
        status=ResourceStatus.RESOLVED,
    )


def embedding_resource() -> ResourceRecord:
    """Return one resolved textual-inversion fixture."""

    return ResourceRecord(
        key="3:embedding",
        role=ResourceRole.EMBEDDING,
        kind=ResourceKind.EMBEDDING,
        node_id="3",
        node_class="EmbeddingLoader",
        filename="detailer.pt",
        selected_value="embeddings/detailer.pt",
        detection_rule_id="embedding_loader",
        hashes=HashRecord(auto_v2=EMBED_AUTO_V2),
        identity=_identity(
            _IdentityFixture(
                resource_type="embedding",
                model_id=500,
                model_version_id=501,
                canonical_air="urn:air:flux2:embedding:civitai:500@501+502.pt",
                file_id="502",
                model_name="Detailer",
                version_name="v1",
            )
        ),
        status=ResourceStatus.RESOLVED,
    )


def complete_record() -> GenerationRecord:
    """Return one fully resolved, Unicode-safe canonical record."""

    resources = (
        model_resource(),
        lora_resource(),
        embedding_resource(),
        vae_resource(),
    )
    return GenerationRecord(
        prompts=PromptRecord(
            positive=PromptField(
                text="portrait of café 雪\ncinematic light",
                branch_present=True,
                source_node_ids=("10",),
            ),
            negative=PromptField(
                text="low quality, watermark",
                branch_present=True,
                source_node_ids=("11",),
            ),
        ),
        settings=GenerationSettings(
            seed=123456789,
            steps=20,
            sampler="dpmpp_2m",
            scheduler="karras",
            cfg_scale=CFG_SCALE,
            denoise=DENOISE,
            width=IMAGE_WIDTH,
            height=IMAGE_HEIGHT,
            batch_size=1,
            clip_skip=2,
        ),
        workflow_kind=WorkflowKind.TXT2IMG,
        resources=resources,
        primary_resource_key="1:unet_name",
        selected_vae_resource_key="5:vae_name",
        image=ImageRecord(ImageFormat.PNG, IMAGE_WIDTH, IMAGE_HEIGHT),
        generator=GeneratorRecord(
            version="2.0.0-test",
            comfyui_version="0.3.50",
        ),
        diagnostics=Diagnostics(),
    )


__all__ = [
    "CFG_SCALE",
    "DENOISE",
    "EMBED_AUTO_V2",
    "IMAGE_HEIGHT",
    "IMAGE_WIDTH",
    "LORA_AUTO_V2",
    "LORA_CLIP_STRENGTH",
    "LORA_MODEL_STRENGTH",
    "LORA_WEIGHT",
    "MODEL_AUTO_V2",
    "MODEL_ID",
    "MODEL_SHA256",
    "MODEL_VERSION_ID",
    "VAE_AUTO_V2",
    "complete_record",
    "embedding_resource",
    "lora_resource",
    "model_resource",
    "vae_resource",
]
