"""Typed generation facts produced by workflow scanning."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .identity import (
    HashRecord,
    HashStatus,
    LookupDiagnostics,
    LookupStatus,
    ResourceIdentity,
    ResourceStatus,
)


class IssueSeverity(StrEnum):
    """Machine-readable workflow issue severity."""

    WARNING = "warning"
    ERROR = "error"


class WorkflowKind(StrEnum):
    """Generation classification supported by graph evidence."""

    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"


class ResourceRole(StrEnum):
    """How an active resource participates in generation."""

    BASE_MODEL = "base_model"
    LORA = "lora"
    VAE = "vae"
    TEXT_ENCODER = "text_encoder"
    EMBEDDING = "embedding"
    HYPERNETWORK = "hypernetwork"
    CONTROLNET = "controlnet"
    IPADAPTER = "ipadapter"
    STYLE_MODEL = "style_model"
    VISION_ENCODER = "vision_encoder"
    MODEL_PATCH = "model_patch"
    AUXILIARY_MODEL = "auxiliary_model"
    MOTION_MODULE = "motion_module"
    GLIGEN = "gligen"
    UPSCALER = "upscaler"


class ResourceKind(StrEnum):
    """Stable internal resource kind, independent of Civitai AIR type."""

    CHECKPOINT = "checkpoint"
    DIFFUSION_MODEL = "diffusion_model"
    LORA = "lora"
    VAE = "vae"
    CLIP = "clip"
    EMBEDDING = "embedding"
    HYPERNETWORK = "hypernetwork"
    CONTROLNET = "controlnet"
    IPADAPTER = "ipadapter"
    STYLE_MODEL = "style_model"
    VISION_ENCODER = "vision_encoder"
    MODEL_PATCH = "model_patch"
    AUXILIARY_MODEL = "auxiliary_model"
    MOTION_MODULE = "motion_module"
    GLIGEN = "gligen"
    UPSCALER = "upscaler"
    EXTERNAL_MODEL = "external_model"


@dataclass(frozen=True, slots=True)
class ScanIssue:
    """Sanitized scanner diagnostic containing no untrusted value."""

    code: str
    severity: IssueSeverity = IssueSeverity.WARNING
    node_id: str | None = None
    input_name: str | None = None


@dataclass(frozen=True, slots=True)
class PromptField:
    """One prompt branch and the literal text candidates found on it."""

    text: str | None = None
    branch_present: bool = False
    source_node_ids: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromptRecord:
    """Positive and negative prompt facts from the selected generation stage."""

    positive: PromptField = PromptField()
    negative: PromptField = PromptField()


@dataclass(frozen=True, slots=True)
class GenerationSettings:
    """Generation settings known from the active selected stage."""

    seed: int | None = None
    steps: int | None = None
    sampler: str | None = None
    scheduler: str | None = None
    cfg_scale: float | None = None
    guidance: float | None = None
    denoise: float | None = None
    width: int | None = None
    height: int | None = None
    batch_size: int | None = None
    clip_skip: int | None = None


@dataclass(frozen=True, slots=True)
class ResourceStrengths:
    """Optional resource weights without inferred defaults."""

    weight: float | None = None
    model: float | None = None
    clip: float | None = None


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    """One resource proven active in the saved image path."""

    key: str
    role: ResourceRole
    kind: ResourceKind
    node_id: str
    node_class: str
    filename: str
    selected_value: str
    strengths: ResourceStrengths = ResourceStrengths()
    active: bool = True
    detection_rule_id: str | None = None
    hashes: HashRecord = field(default_factory=HashRecord)
    hash_status: HashStatus = HashStatus.NOT_ATTEMPTED
    identity: ResourceIdentity | None = None
    status: ResourceStatus = ResourceStatus.UNRESOLVED
    lookup_status: LookupStatus = LookupStatus.NOT_ATTEMPTED
    lookup_diagnostics: LookupDiagnostics = field(default_factory=LookupDiagnostics)
    unresolved_reason: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowScan:
    """Complete phase-four workflow scan result."""

    save_node_id: str | None
    active_node_ids: tuple[str, ...]
    selected_stage_node_id: str | None
    stage_candidate_ids: tuple[str, ...]
    workflow_kind: WorkflowKind | None
    prompts: PromptRecord
    settings: GenerationSettings
    resources: tuple[ResourceRecord, ...]
    primary_resource_key: str | None
    selected_vae_resource_key: str | None
    issues: tuple[ScanIssue, ...]


__all__ = [
    "GenerationSettings",
    "IssueSeverity",
    "PromptField",
    "PromptRecord",
    "ResourceKind",
    "ResourceRecord",
    "ResourceRole",
    "ResourceStrengths",
    "ScanIssue",
    "WorkflowKind",
    "WorkflowScan",
]
