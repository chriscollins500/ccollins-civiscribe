"""Format-aware pixels-first still-image save transaction."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from ..domain import (
    CiviScribeError,
    GenerationRecord,
    GeneratorRecord,
    ImageFormat,
    ImageFrame,
    ImageRecord,
    PromptField,
    PromptRecord,
    ScanIssue,
    WorkflowScan,
    WriteError,
    generation_record_from_scan,
)
from ..identity import resolve_scan_identities
from ..projections import (
    ImageMetadataProjection,
    SidecarArtifact,
    SidecarPolicy,
    build_reduced_writer_projection,
    build_rich_writer_projection,
    build_sidecar_projection,
)
from ..storage import write_sidecar_json
from ..storage.atomic import create_temporary_path, flush_file, publish_image
from ..storage.paths import OutputPlan, TemplateValues, resolve_output_plan
from ..workflow import scan_workflow
from ..writers import ImageWriter, WriteResult, create_writer
from .outcome import SavedImage, SaveOutcome, SaveWarning, SidecarStatus
from .request import MetadataRequest, SaveRequest

FALLBACK_PREFIX = "ComfyUI"
MAX_PROMPT_OVERRIDE_CHARS = 1_000_000
_RUNTIME_PROMPT_ISSUE = "runtime_prompt_unavailable_connect_final_prompt_override"
_POSITIVE_PROMPT_EXTRACTION_ISSUES = frozenset(
    {"positive_prompt_ambiguous", "positive_prompt_missing"}
)
_NEGATIVE_PROMPT_EXTRACTION_ISSUES = frozenset(
    {"negative_prompt_ambiguous", "negative_prompt_missing"}
)
_MODE_CHANNELS = {
    "L": 1,
    "RGB": 3,
    "RGBA": 4,
}


@dataclass(frozen=True, slots=True)
class _MetadataContext:
    request: MetadataRequest
    scan: WorkflowScan


@dataclass(frozen=True, slots=True)
class _SaveAttempt:
    frame: ImageFrame
    writer: ImageWriter
    metadata_candidates: tuple[ImageMetadataProjection | None, ...]
    metadata_requested: bool
    record: GenerationRecord | None
    metadata_request: MetadataRequest | None
    write_sidecar_json: bool
    batch_index: int
    warnings: list[SaveWarning]


@dataclass(frozen=True, slots=True)
class _FrameMetadata:
    record: GenerationRecord | None
    candidates: tuple[ImageMetadataProjection | None, ...]


def _prompt_override(
    value: str | None,
    current: PromptField,
    *,
    issue_code: str,
) -> tuple[PromptField, tuple[ScanIssue, ...]]:
    if value is None or value == "":
        return current, ()
    if len(value) > MAX_PROMPT_OVERRIDE_CHARS:
        return current, (ScanIssue(issue_code),)
    return (
        PromptField(
            text=value,
            branch_present=True,
            candidates=(value,),
        ),
        (),
    )


def _prompt_override_applied(value: str | None) -> bool:
    return value is not None and value != "" and len(value) <= MAX_PROMPT_OVERRIDE_CHARS


def _issue_resolved_by_prompt_override(
    issue: ScanIssue,
    *,
    positive_applied: bool,
    negative_applied: bool,
) -> bool:
    if positive_applied and (
        issue.code in _POSITIVE_PROMPT_EXTRACTION_ISSUES
        or (issue.code == _RUNTIME_PROMPT_ISSUE and issue.input_name == "positive_prompt_override")
    ):
        return True
    return negative_applied and (
        issue.code in _NEGATIVE_PROMPT_EXTRACTION_ISSUES
        or (issue.code == _RUNTIME_PROMPT_ISSUE and issue.input_name == "negative_prompt_override")
    )


def _apply_prompt_overrides(
    scan: WorkflowScan,
    metadata: MetadataRequest,
) -> WorkflowScan:
    positive, positive_issues = _prompt_override(
        metadata.positive_prompt_override,
        scan.prompts.positive,
        issue_code="positive_prompt_override_too_large",
    )
    negative, negative_issues = _prompt_override(
        metadata.negative_prompt_override,
        scan.prompts.negative,
        issue_code="negative_prompt_override_too_large",
    )
    positive_applied = _prompt_override_applied(metadata.positive_prompt_override)
    negative_applied = _prompt_override_applied(metadata.negative_prompt_override)
    unresolved_issues = tuple(
        issue
        for issue in scan.issues
        if not _issue_resolved_by_prompt_override(
            issue,
            positive_applied=positive_applied,
            negative_applied=negative_applied,
        )
    )
    return replace(
        scan,
        prompts=PromptRecord(positive=positive, negative=negative),
        issues=(*unresolved_issues, *positive_issues, *negative_issues),
    )


def _plan(
    request: SaveRequest,
    frame: ImageFrame,
    batch_index: int,
    prefix: str,
    record: GenerationRecord | None = None,
) -> OutputPlan:
    primary_model = None
    if record is not None and record.primary_resource_key is not None:
        primary = next(
            (
                resource
                for resource in record.resources
                if resource.key == record.primary_resource_key
            ),
            None,
        )
        primary_model = primary.filename if primary is not None else None
    return resolve_output_plan(
        request.output_root,
        prefix,
        values=TemplateValues(
            width=frame.width,
            height=frame.height,
            batch_index=batch_index,
            now=request.timestamp or datetime.now().astimezone(),
            model=primary_model,
            seed=record.settings.seed if record is not None else None,
            sampler=record.settings.sampler if record is not None else None,
        ),
    )


def _safe_code(exc: BaseException) -> str:
    if isinstance(exc, CiviScribeError):
        return exc.code
    if isinstance(exc, OSError):
        return "filesystem_operation_failed"
    return "unexpected_save_failure"


def _saved_image(
    plan: OutputPlan,
    *,
    final_name: str,
    output_format: ImageFormat,
    result: WriteResult,
) -> SavedImage:
    metadata_status = {
        "rich": "complete",
        "reduced": "partial",
        None: "minimal",
    }[result.metadata_tier]
    return SavedImage(
        filename=final_name,
        subfolder=plan.subfolder,
        output_format=output_format,
        width=result.width,
        height=result.height,
        metadata_status=metadata_status,
    )


def _save_one(
    attempt: _SaveAttempt,
    plan: OutputPlan,
) -> SavedImage:
    for metadata in attempt.metadata_candidates:
        temporary = create_temporary_path(plan.directory, attempt.writer.extension)
        try:
            result = attempt.writer.write(attempt.frame, temporary, metadata)
            flush_file(temporary)
            final_path = publish_image(temporary, plan, attempt.writer.extension)
            if result.metadata_tier == "reduced":
                attempt.warnings.append(
                    SaveWarning(
                        "metadata_reduced_fallback_used",
                        attempt.batch_index,
                    )
                )
            elif result.metadata_tier is None and attempt.metadata_requested:
                attempt.warnings.append(
                    SaveWarning(
                        "metadata_pixels_only_fallback_used",
                        attempt.batch_index,
                    )
                )
            saved_image = _saved_image(
                plan,
                final_name=final_path.name,
                output_format=attempt.writer.output_format,
                result=result,
            )
            return _write_optional_sidecar(
                attempt,
                saved_image,
                final_path=final_path,
                result=result,
            )
        except Exception as exc:
            attempt.warnings.append(SaveWarning(_safe_code(exc), attempt.batch_index))
        finally:
            temporary.unlink(missing_ok=True)
    raise WriteError("all_write_attempts_failed")


def _sidecar_warning_pairs(attempt: _SaveAttempt) -> tuple[tuple[str, int | None], ...]:
    return tuple(
        (warning.code, warning.batch_index)
        for warning in attempt.warnings
        if warning.batch_index in {None, attempt.batch_index}
    )


def _sidecar_failure(
    attempt: _SaveAttempt,
    saved_image: SavedImage,
    code: str,
) -> SavedImage:
    attempt.warnings.append(SaveWarning(code, attempt.batch_index))
    return replace(
        saved_image,
        sidecar_status=SidecarStatus.FAILED,
    )


def _output_channels(mode: str) -> int:
    try:
        return _MODE_CHANNELS[mode]
    except KeyError as exc:
        raise ValueError("sidecar_output_mode_unsupported") from exc


def _write_optional_sidecar(
    attempt: _SaveAttempt,
    saved_image: SavedImage,
    *,
    final_path: Path,
    result: WriteResult,
) -> SavedImage:
    if not attempt.write_sidecar_json:
        return saved_image
    sidecar_path = final_path.with_suffix(".json")
    metadata = attempt.metadata_request
    try:
        projection = build_sidecar_projection(
            attempt.record,
            SidecarArtifact(
                filename=final_path.name,
                sidecar_filename=sidecar_path.name,
                subfolder=saved_image.subfolder,
                output_format=saved_image.output_format,
                width=saved_image.width,
                height=saved_image.height,
                batch_index=attempt.batch_index,
                mode=result.mode,
                channels=_output_channels(result.mode),
                incoming_tensor_dtype=str(attempt.frame.pixels.dtype),
                encoded_sample_bits=result.encoded_sample_bits,
                file_size_bytes=final_path.stat().st_size,
                metadata_status=saved_image.metadata_status,
            ),
            SidecarPolicy(
                prompt=metadata.prompt if metadata is not None else None,
                workflow=metadata.workflow if metadata is not None else None,
                include_workflow=metadata.include_workflow if metadata is not None else False,
                include_civitai_manifest=(
                    metadata.include_civitai_manifest if metadata is not None else False
                ),
                save_warnings=_sidecar_warning_pairs(attempt),
            ),
        )
    except Exception:
        return _sidecar_failure(
            attempt,
            saved_image,
            "sidecar_projection_failed",
        )

    attempt.warnings.extend(
        SaveWarning(code, attempt.batch_index) for code in projection.warning_codes
    )
    try:
        write_sidecar_json(sidecar_path, projection.json_text)
    except Exception:
        return _sidecar_failure(
            attempt,
            saved_image,
            "sidecar_write_failed",
        )
    return replace(
        saved_image,
        sidecar_status=SidecarStatus.WRITTEN,
        sidecar_filename=sidecar_path.name,
    )


def _metadata_context(
    request: SaveRequest,
    warnings: list[SaveWarning],
) -> _MetadataContext | None:
    metadata = request.metadata
    if metadata is None:
        return None
    try:
        scan = scan_workflow(
            metadata.prompt,
            save_node_id=metadata.save_node_id,
        )
        scan = _apply_prompt_overrides(scan, metadata)
    except Exception:
        warnings.append(SaveWarning("metadata_scan_failed"))
        return None
    try:
        scan = resolve_scan_identities(
            scan,
            options=metadata.identity_options,
            services=metadata.identity_services,
        )
    except Exception:
        warnings.append(SaveWarning("metadata_identity_resolution_failed"))
    return _MetadataContext(metadata, scan)


def _frame_metadata(
    request: SaveRequest,
    context: _MetadataContext | None,
    frame: ImageFrame,
    batch_index: int,
    warnings: list[SaveWarning],
) -> _FrameMetadata:
    if context is None:
        return _FrameMetadata(None, (None,))
    record = generation_record_from_scan(
        context.scan,
        image=ImageRecord(
            request.output_format,
            frame.width,
            frame.height,
            batch_index=batch_index,
        ),
        generator=GeneratorRecord(comfyui_version=context.request.comfyui_version),
    )
    candidates: list[ImageMetadataProjection | None] = []
    try:
        rich = build_rich_writer_projection(
            record,
            request.output_format,
            prompt=(context.request.prompt if context.request.prompt is not None else {}),
            workflow=context.request.workflow,
            include_workflow=context.request.include_workflow,
            include_civitai_manifest=context.request.include_civitai_manifest,
        )
        candidates.append(rich)
        warnings.extend(SaveWarning(code, batch_index) for code in rich.warning_codes)
    except Exception:
        warnings.append(SaveWarning("metadata_rich_build_failed", batch_index))
    try:
        candidates.append(build_reduced_writer_projection(record, request.output_format))
    except Exception:
        warnings.append(SaveWarning("metadata_reduced_build_failed", batch_index))
    candidates.append(None)
    return _FrameMetadata(record, tuple(candidates))


def _save_with_plan(
    attempt: _SaveAttempt,
    plan: OutputPlan,
) -> SavedImage | None:
    try:
        return _save_one(attempt, plan)
    except WriteError:
        return None


def save_image_batch(
    request: SaveRequest,
    *,
    writer: ImageWriter | None = None,
) -> SaveOutcome:
    """Save every valid frame possible, with metadata and location fallbacks."""

    if not request.images:
        raise WriteError("image_batch_empty")

    image_writer = writer or create_writer(request.output_format, request.writer_options)
    if image_writer.output_format is not request.output_format:
        raise WriteError("writer_format_mismatch")
    saved: list[SavedImage] = []
    warnings: list[SaveWarning] = []
    context = _metadata_context(request, warnings)
    metadata_requested = request.metadata is not None

    for batch_index, frame in enumerate(request.images):
        frame_metadata = _frame_metadata(request, context, frame, batch_index, warnings)
        attempt = _SaveAttempt(
            frame=frame,
            writer=image_writer,
            metadata_candidates=frame_metadata.candidates,
            metadata_requested=metadata_requested,
            record=frame_metadata.record,
            metadata_request=request.metadata,
            write_sidecar_json=request.write_sidecar_json,
            batch_index=batch_index,
            warnings=warnings,
        )
        try:
            requested_plan = _plan(
                request,
                frame,
                batch_index,
                request.filename_prefix,
                frame_metadata.record,
            )
        except Exception as exc:
            warnings.append(SaveWarning(_safe_code(exc), batch_index))
            try:
                requested_plan = _plan(
                    request,
                    frame,
                    batch_index,
                    FALLBACK_PREFIX,
                    frame_metadata.record,
                )
            except Exception as fallback_exc:
                warnings.append(SaveWarning(_safe_code(fallback_exc), batch_index))
                warnings.append(SaveWarning("image_not_saved", batch_index))
                continue

        saved_image = _save_with_plan(
            attempt,
            requested_plan,
        )
        if saved_image is not None:
            saved.append(saved_image)
            continue

        if requested_plan.subfolder or requested_plan.stem != FALLBACK_PREFIX:
            try:
                fallback_plan = _plan(
                    request,
                    frame,
                    batch_index,
                    FALLBACK_PREFIX,
                    frame_metadata.record,
                )
            except Exception as exc:
                warnings.append(SaveWarning(_safe_code(exc), batch_index))
            else:
                saved_image = _save_with_plan(
                    attempt,
                    fallback_plan,
                )
                if saved_image is not None:
                    saved.append(saved_image)
                    warnings.append(SaveWarning("fallback_output_used", batch_index))
                    continue

        warnings.append(SaveWarning("image_not_saved", batch_index))

    if not saved:
        raise WriteError("no_image_saved")
    return SaveOutcome(tuple(saved), tuple(warnings))
