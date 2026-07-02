"""Civitai-style EXIF UserComment metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .a1111 import build_civitai_resources_for_parameters
from .schema import GenerationSettings, PromptMetadata, ResolvedResource
from .serialize import to_json_text
from ..security.redaction import sanitize_metadata_text
from ..version import __version__

EXIF_IFD_TAG = 0x8769
USER_COMMENT_TAG = 0x9286
USER_COMMENT_UNICODE_PREFIX = b"UNICODE\x00"


def build_exif_bytes(
    *,
    prompt: PromptMetadata,
    generation: GenerationSettings,
    resources: tuple[ResolvedResource, ...] = (),
    output_format: str = "png",
    created_at: datetime | None = None,
) -> bytes:
    """Build a PNG/JPEG-compatible EXIF payload containing only UserComment."""

    from PIL import Image

    text = build_exif_user_comment_text(
        prompt=prompt,
        generation=generation,
        resources=resources,
        output_format=output_format,
        created_at=created_at,
    )
    exif = Image.Exif()
    exif[EXIF_IFD_TAG] = {USER_COMMENT_TAG: encode_user_comment(text)}
    return exif.tobytes()


def build_exif_user_comment_text(
    *,
    prompt: PromptMetadata,
    generation: GenerationSettings,
    resources: tuple[ResolvedResource, ...] = (),
    output_format: str = "png",
    created_at: datetime | None = None,
) -> str:
    """Build the text Civitai stores in EXIF UserComment."""

    resource_json = build_civitai_resources_for_parameters(resources)
    metadata_json = build_civitai_metadata_json(
        prompt=prompt,
        generation=generation,
        resources=resource_json,
        output_format=output_format,
    )

    lines: list[str] = [sanitize_metadata_text(prompt.positive or "")]
    if prompt.negative:
        lines.append(f"Negative prompt: {sanitize_metadata_text(prompt.negative)}")

    fields = _settings_fields(
        generation=generation,
        resources=resource_json,
        metadata=metadata_json,
        created_at=created_at,
    )
    if fields:
        lines.append(", ".join(f"{key}: {value}" for key, value in fields))
    return "\n".join(lines)


def encode_user_comment(text: str) -> bytes:
    """Encode EXIF UserComment as UNICODE-prefixed UTF-16BE."""

    return USER_COMMENT_UNICODE_PREFIX + sanitize_metadata_text(text).encode("utf-16-be", errors="replace")


def decode_user_comment(value: bytes | str | None) -> tuple[str, str]:
    """Decode common EXIF UserComment encodings for tools/tests."""

    if value is None:
        return "", "absent"
    if isinstance(value, str):
        return sanitize_metadata_text(value), "str"
    if value.startswith(USER_COMMENT_UNICODE_PREFIX):
        payload = value[len(USER_COMMENT_UNICODE_PREFIX) :]
        if len(payload) % 2 == 1 and payload.startswith(b"\x00"):
            payload = payload[1:]
        return payload.decode("utf-16-be", errors="replace"), "UNICODE UTF-16BE"
    if value.startswith(b"ASCII\x00\x00\x00"):
        return value[8:].decode("ascii", errors="replace"), "ASCII"
    return value.decode("utf-8", errors="replace"), "unknown"


def build_civitai_metadata_json(
    *,
    prompt: PromptMetadata,
    generation: GenerationSettings,
    resources: list[dict[str, Any]],
    output_format: str = "png",
) -> dict[str, Any]:
    """Build the compact Civitai metadata object embedded in UserComment."""

    data: dict[str, Any] = {
        "workflow": "txt2img",
        "outputFormat": sanitize_metadata_text(output_format.lower() or "png"),
        "generator": {
            "name": "ComfyUI",
            "node": "Save Image with Civitai Metadata",
            "package": "comfyui-civitai-save-node",
            "version": __version__,
        },
        "resources": resources,
    }
    if generation.width is not None and generation.height is not None:
        data["aspectRatio"] = {
            "width": int(generation.width),
            "height": int(generation.height),
        }
    if generation.steps is not None:
        data["steps"] = int(generation.steps)
    if generation.sampler:
        data["sampler"] = sanitize_metadata_text(generation.sampler)
    cfg_or_guidance = _cfg_or_guidance(generation)
    if cfg_or_guidance is not None:
        data["cfgScale"] = cfg_or_guidance
    if generation.seed is not None:
        data["seed"] = int(generation.seed)
    if prompt.positive:
        data["prompt"] = sanitize_metadata_text(prompt.positive)
    if prompt.negative is not None:
        data["negativePrompt"] = sanitize_metadata_text(prompt.negative)
    return data


def _settings_fields(
    *,
    generation: GenerationSettings,
    resources: list[dict[str, Any]],
    metadata: dict[str, Any],
    created_at: datetime | None,
) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    _add(fields, "Steps", generation.steps)
    _add(fields, "Sampler", generation.sampler)
    _add(fields, "CFG scale", _format_number(_cfg_or_guidance(generation)))
    _add(fields, "Seed", generation.seed)
    if generation.width is not None and generation.height is not None:
        _add(fields, "Size", f"{int(generation.width)}x{int(generation.height)}")
    _add(fields, "Created Date", _created_at_text(created_at))
    if resources:
        _add(fields, "Civitai resources", to_json_text(resources))
    _add(fields, "Civitai metadata", to_json_text(metadata))
    return fields


def _cfg_or_guidance(generation: GenerationSettings) -> float | None:
    if generation.cfg_scale is not None:
        return float(generation.cfg_scale)
    if isinstance(generation.extra, dict):
        value = generation.extra.get("fluxGuidance") or generation.extra.get("guidance")
        try:
            if value is not None and value != "":
                return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _created_at_text(created_at: datetime | None) -> str:
    value = created_at or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


__all__ = [
    "EXIF_IFD_TAG",
    "USER_COMMENT_TAG",
    "USER_COMMENT_UNICODE_PREFIX",
    "build_civitai_metadata_json",
    "build_exif_bytes",
    "build_exif_user_comment_text",
    "decode_user_comment",
    "encode_user_comment",
]
