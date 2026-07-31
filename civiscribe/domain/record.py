"""Canonical generation record consumed by every metadata projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..version import __version__
from .generation import (
    GenerationSettings,
    IssueSeverity,
    PromptRecord,
    ResourceRecord,
    ScanIssue,
    WorkflowKind,
    WorkflowScan,
)

GENERATOR_NAME = "CCollins' CiviScribe"


class ImageFormat(StrEnum):
    """Still-image formats retained by the V2 product contract."""

    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"


@dataclass(frozen=True, slots=True)
class ImageRecord:
    """Final saved-image facts, independent of latent dimensions."""

    format: ImageFormat
    width: int
    height: int
    batch_index: int = 0

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("image_dimensions_invalid")
        if self.batch_index < 0:
            raise ValueError("batch_index_invalid")


@dataclass(frozen=True, slots=True)
class GeneratorRecord:
    """Generator identity without host paths or user information."""

    name: str = GENERATOR_NAME
    version: str = __version__
    comfyui_version: str | None = None


@dataclass(frozen=True, slots=True)
class Diagnostics:
    """Sanitized warnings and errors attached to canonical generation facts."""

    warnings: tuple[ScanIssue, ...] = ()
    errors: tuple[ScanIssue, ...] = ()

    @property
    def all_issues(self) -> tuple[ScanIssue, ...]:
        """Return errors and warnings in stable severity order."""

        return (*self.errors, *self.warnings)


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    """One source of truth for all parser and structured projections."""

    prompts: PromptRecord
    settings: GenerationSettings
    workflow_kind: WorkflowKind | None
    resources: tuple[ResourceRecord, ...]
    primary_resource_key: str | None
    selected_vae_resource_key: str | None
    image: ImageRecord
    generator: GeneratorRecord
    diagnostics: Diagnostics


def generation_record_from_scan(
    scan: WorkflowScan,
    *,
    image: ImageRecord,
    generator: GeneratorRecord | None = None,
) -> GenerationRecord:
    """Combine scanner facts with final-image facts without inventing values."""

    issues = list(scan.issues)
    scanned_width = scan.settings.width
    scanned_height = scan.settings.height
    if (
        scanned_width is not None
        and scanned_height is not None
        and (scanned_width != image.width or scanned_height != image.height)
    ):
        issues.append(ScanIssue("generation_dimensions_differ_from_final_image"))

    errors = tuple(issue for issue in issues if issue.severity is IssueSeverity.ERROR)
    warnings = tuple(issue for issue in issues if issue.severity is IssueSeverity.WARNING)
    return GenerationRecord(
        prompts=scan.prompts,
        settings=scan.settings,
        workflow_kind=scan.workflow_kind,
        resources=tuple(resource for resource in scan.resources if resource.active),
        primary_resource_key=scan.primary_resource_key,
        selected_vae_resource_key=scan.selected_vae_resource_key,
        image=image,
        generator=generator or GeneratorRecord(),
        diagnostics=Diagnostics(warnings=warnings, errors=errors),
    )


__all__ = [
    "GENERATOR_NAME",
    "Diagnostics",
    "GenerationRecord",
    "GeneratorRecord",
    "ImageFormat",
    "ImageRecord",
    "generation_record_from_scan",
]
