"""Deterministic A1111/Civitai-compatible generation text."""

from __future__ import annotations

import math

from ..domain import GenerationRecord, ResourceRole, WorkflowKind
from ..serialization import dumps_json
from .display import display_sampler, display_scheduler
from .resources import (
    a1111_hashes,
    compatibility_hash,
    legacy_hash_list,
    parser_resource_items,
    resource_by_key,
)
from .sanitize import metadata_scalar, metadata_text, resource_filename


def _number(value: int | float | None) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return None
    if value == 0:
        return "0"
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"


def _add_field(fields: list[tuple[str, str]], name: str, value: str | None) -> None:
    if value is not None and value != "":
        fields.append((name, value))


def _settings_fields(record: GenerationRecord) -> list[tuple[str, str]]:
    settings = record.settings
    fields: list[tuple[str, str]] = []
    _add_field(fields, "Steps", _number(settings.steps))
    _add_field(fields, "Sampler", display_sampler(settings.sampler))
    _add_field(fields, "Schedule type", display_scheduler(settings.scheduler))
    _add_field(fields, "CFG scale", _number(settings.cfg_scale))
    if settings.cfg_scale is None:
        _add_field(fields, "Guidance", _number(settings.guidance))
    _add_field(fields, "Seed", _number(settings.seed))
    _add_field(fields, "Size", f"{record.image.width}x{record.image.height}")
    _add_field(fields, "Batch size", _number(settings.batch_size))

    primary = resource_by_key(record, record.primary_resource_key)
    if primary is not None:
        _add_field(fields, "Model", resource_filename(primary.filename))
        _add_field(fields, "Model hash", compatibility_hash(primary.hashes))

    selected_vae = resource_by_key(record, record.selected_vae_resource_key)
    if selected_vae is not None:
        _add_field(fields, "VAE", resource_filename(selected_vae.filename))
        _add_field(fields, "VAE hash", compatibility_hash(selected_vae.hashes))

    _add_field(fields, "Clip skip", _number(settings.clip_skip))
    if record.workflow_kind is WorkflowKind.IMG2IMG:
        _add_field(fields, "Denoising strength", _number(settings.denoise))

    lora_hashes = legacy_hash_list(record, ResourceRole.LORA)
    if lora_hashes is not None:
        _add_field(fields, "Lora hashes", dumps_json(lora_hashes))
    embedding_hashes = legacy_hash_list(record, ResourceRole.EMBEDDING)
    if embedding_hashes is not None:
        _add_field(fields, "TI hashes", dumps_json(embedding_hashes))

    hashes = a1111_hashes(record)
    if hashes:
        _add_field(fields, "Hashes", dumps_json(hashes))
    resources = parser_resource_items(record.resources)
    if resources:
        _add_field(fields, "Civitai resources", dumps_json(resources))
    return fields


def build_a1111(record: GenerationRecord) -> str:
    """Build one parser-friendly parameters block from canonical facts."""

    fields = _settings_fields(record)
    positive = metadata_text(record.prompts.positive.text)
    negative = metadata_text(record.prompts.negative.text)
    lines = [positive or ""]
    lines.append(f"Negative prompt: {negative}" if negative else "Negative prompt:")
    lines.append(", ".join(f"{metadata_scalar(name) or name}: {value}" for name, value in fields))
    return "\n".join(lines)


__all__ = ["build_a1111"]
