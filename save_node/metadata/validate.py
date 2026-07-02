"""Metadata validation."""

from __future__ import annotations

from typing import Any

from .schema import (
    GenerationSettings,
    PromptMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
    ValidationResult,
)
from ..security.redaction import MAX_METADATA_STRING_CHARS


def validate_phase_one_metadata(
    *,
    filename_prefix: str,
    prompt: Any | None,
    extra_pnginfo: dict[str, Any] | None,
    include_workflow: bool,
    include_civitai_manifest: bool,
) -> ValidationResult:
    prompt_metadata = PromptMetadata()
    generation = GenerationSettings()
    return validate_metadata(
        filename_prefix=filename_prefix,
        prompt_metadata=prompt_metadata,
        generation=generation,
        resources=(),
        unresolved_resources=(),
        prompt=prompt,
        extra_pnginfo=extra_pnginfo,
        include_workflow=include_workflow,
        include_civitai_manifest=include_civitai_manifest,
        additional_warnings=(),
        additional_errors=(),
    )


def validate_metadata(
    *,
    filename_prefix: str,
    prompt_metadata: PromptMetadata,
    generation: GenerationSettings,
    resources: tuple[ResolvedResource, ...],
    unresolved_resources: tuple[UnresolvedResource, ...],
    prompt: Any | None,
    extra_pnginfo: dict[str, Any] | None,
    include_workflow: bool,
    include_civitai_manifest: bool,
    additional_warnings: tuple[ValidationIssue, ...] = (),
    additional_errors: tuple[ValidationIssue, ...] = (),
    parameter_resources: tuple[ResolvedResource, ...] | None = None,
) -> ValidationResult:
    warnings: list[ValidationIssue] = list(additional_warnings)
    errors: list[ValidationIssue] = list(additional_errors)

    if not filename_prefix:
        errors.append(
            ValidationIssue(
                code="empty_filename_prefix",
                message="filename_prefix must not be empty",
                field="filenamePrefix",
            )
        )

    if prompt is None:
        warnings.append(
            ValidationIssue(
                code="missing_prompt",
                message="ComfyUI did not provide prompt metadata",
                field="prompt",
            )
        )

    if not prompt_metadata.positive:
        warnings.append(
            ValidationIssue(
                code="missing_positive_prompt",
                message="Positive prompt could not be derived from available metadata",
                field="prompt.positive",
            )
        )

    if not prompt_metadata.positive and not prompt_metadata.negative:
        warnings.append(
            ValidationIssue(
                code="missing_prompt_text",
                message="A1111 prompt text could not be derived from available metadata",
                field="prompt",
            )
        )

    warnings.extend(_metadata_size_warnings(prompt_metadata))

    if not any(
        value is not None
        for value in (
            generation.steps,
            generation.sampler,
            generation.scheduler,
            generation.cfg_scale,
            generation.seed,
        )
    ):
        warnings.append(
            ValidationIssue(
                code="missing_sampler_settings",
                message="Sampler settings could not be derived from available metadata",
                field="generation",
            )
        )

    if generation.width is None or generation.height is None:
        warnings.append(
            ValidationIssue(
                code="missing_dimensions",
                message="Image dimensions could not be derived from available metadata",
                field="generation",
            )
        )

    if not prompt_metadata.positive and not generation.has_a1111_settings:
        warnings.append(
            ValidationIssue(
                code="a1111_parameters_incomplete",
                message="A1111 parameters cannot be fully built from available fields",
                field="parameters",
            )
        )

    workflow = (extra_pnginfo or {}).get("workflow")
    if include_workflow and workflow is None:
        warnings.append(
            ValidationIssue(
                code="missing_workflow",
                message="include_workflow is enabled but workflow metadata is missing",
                field="workflow",
            )
        )

    if not include_civitai_manifest:
        warnings.append(
            ValidationIssue(
                code="civitai_manifest_disabled",
                message="Civitai manifest metadata is disabled",
                field="civitai",
            )
        )

    for index, resource in enumerate(resources):
        metadata = resource.resource
        if metadata.civitai_model_version_id is not None and metadata.air is None:
            if metadata.metadata.get("identityIncomplete") is True:
                warnings.append(
                    ValidationIssue(
                        code="preferred_identity_incomplete_air",
                        message="Preferred identity has a Civitai modelVersionId but no full AIR; it was emitted as a partial modelVersionId-only identity",
                        field=f"resources[{index}].air",
                    )
                )
            warnings.append(
                ValidationIssue(
                    code="resource_version_without_air",
                    message="Resource has a Civitai modelVersionId but no full AIR URN",
                    field=f"resources[{index}].air",
                )
            )
        if metadata.air is None and metadata.hashes.is_empty:
            warnings.append(
                ValidationIssue(
                    code="resource_without_hash_or_air",
                    message="Detected resource has no hash or AIR metadata yet",
                    field=f"resources[{index}]",
                )
            )
        if not metadata.hashes.is_empty and not (
            metadata.civitai_model_version_id is not None
            or (metadata.air is not None and metadata.air.model_version_id is not None)
        ):
            warnings.append(
                ValidationIssue(
                    code="resource_hashed_but_no_civitai_identity",
                    message="Resource has local hashes but no Civitai AIR or modelVersionId identity",
                    field=f"resources[{index}]",
                )
            )
        if metadata.air is not None and metadata.air.model_version_id is None:
            warnings.append(
                ValidationIssue(
                    code="air_without_model_version_id",
                    message="Resource has AIR metadata but no parsed modelVersionId",
                    field=f"resources[{index}].air.modelVersionId",
                )
            )

    for index, resource in enumerate(unresolved_resources):
        warnings.append(
            ValidationIssue(
                code="unresolved_resource",
                message=f"Resource is unresolved: {resource.reason}",
                field=f"unresolvedResources[{index}]",
            )
        )

    warnings.extend(_resource_consistency_warnings(parameter_resources or resources, resources))

    return ValidationResult(warnings=tuple(warnings), errors=tuple(errors))


def _metadata_size_warnings(prompt_metadata: PromptMetadata) -> list[ValidationIssue]:
    warnings: list[ValidationIssue] = []
    for field_name, value in (
        ("prompt.positive", prompt_metadata.positive),
        ("prompt.negative", prompt_metadata.negative),
    ):
        if value is None or len(value) <= MAX_METADATA_STRING_CHARS:
            continue
        warnings.append(
            ValidationIssue(
                code="metadata_field_size_exceeded",
                message="Metadata text field exceeds maximum safe serialized length and will be truncated",
                field=field_name,
            )
        )
    return warnings


def _resource_consistency_warnings(
    parameter_resources: tuple[ResolvedResource, ...],
    manifest_resources: tuple[ResolvedResource, ...],
) -> list[ValidationIssue]:
    warnings: list[ValidationIssue] = []
    parameter_keys = {_resource_key(resource) for resource in parameter_resources}
    manifest_keys = {_resource_key(resource) for resource in manifest_resources}

    for key in sorted(parameter_keys - manifest_keys):
        warnings.append(
            ValidationIssue(
                code="resource_in_parameters_not_manifest",
                message=f"Resource appears in parameters but not manifest: {key}",
                field="resources",
            )
        )

    for key in sorted(manifest_keys - parameter_keys):
        warnings.append(
            ValidationIssue(
                code="resource_in_manifest_not_parameters",
                message=f"Resource appears in manifest but not parameters: {key}",
                field="resources",
            )
        )

    return warnings


def _resource_key(resource: ResolvedResource) -> str:
    metadata = resource.resource
    return "|".join(
        [
            metadata.node_id or "",
            metadata.role,
            metadata.type or "",
            metadata.name or "",
            metadata.selected_value or "",
        ]
    )


__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "validate_metadata",
    "validate_phase_one_metadata",
]
