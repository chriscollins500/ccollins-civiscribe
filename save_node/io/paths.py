"""Path normalization helpers for safe ComfyUI output writes."""

from __future__ import annotations

from datetime import datetime
import os
import re
from pathlib import Path

from ..metadata.schema import GenerationSettings, ValidationIssue


class PathSecurityError(ValueError):
    """Raised when an untrusted path tries to escape the output directory."""


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_INVALID_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_WINDOWS_DRIVE = re.compile(r"^[a-zA-Z]:")
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
_MAX_SEGMENT_LENGTH = 120
_MAX_PREFIX_LENGTH = 240
_TEMPLATE_TOKEN = re.compile(r"%([^%]+)%")


def normalize_filename_prefix(value: object, default: str = "CivitaiMetadata") -> str:
    """Return a relative, sanitized ComfyUI filename prefix.

    Forward slashes are preserved as ComfyUI subfolder separators. Absolute
    paths, drive-letter paths, UNC paths, and parent-directory traversal are
    rejected instead of being silently rewritten.
    """

    raw = str(value if value is not None else default).strip()
    if not raw:
        raw = default

    normalized = raw.replace("\\", "/")
    if _looks_absolute(normalized):
        raise PathSecurityError("filename_prefix must be relative")

    clean_parts: list[str] = []
    for part in normalized.split("/"):
        part = part.strip()
        if not part or part == ".":
            continue
        if part == "..":
            raise PathSecurityError("filename_prefix must not contain '..'")
        clean_parts.append(_clean_component(part))

    prefix = "/".join(clean_parts) or default
    if len(prefix) > _MAX_PREFIX_LENGTH:
        prefix = prefix[:_MAX_PREFIX_LENGTH].rstrip(" ._/")
    return prefix or default


def expand_filename_template(
    value: object,
    *,
    generation: GenerationSettings,
    now: datetime | None = None,
    counter: int | None = None,
    default: str = "CivitaiMetadata",
) -> tuple[str, tuple[ValidationIssue, ...]]:
    """Expand a small safe subset of Comfy-style filename tokens."""

    raw = str(value if value is not None else default)
    current_time = now or datetime.now()
    warnings: list[ValidationIssue] = []

    def replace_token(match: re.Match[str]) -> str:
        token = match.group(1)
        token_lower = token.lower()
        replacement: object | None

        if token_lower.startswith("date:"):
            replacement = _format_date_token(token[5:], current_time)
        elif token_lower.startswith("date_"):
            replacement = _format_date_token(token[5:], current_time)
        elif token_lower == "seed":
            replacement = generation.seed
        elif token_lower == "model":
            replacement = generation.model
        elif token_lower == "sampler":
            replacement = generation.sampler
        elif token_lower == "width":
            replacement = generation.width
        elif token_lower == "height":
            replacement = generation.height
        elif token_lower == "counter":
            replacement = f"{counter or 0:05}"
        else:
            warnings.append(
                ValidationIssue(
                    code="unknown_filename_template_token",
                    message=f"Filename template token is not recognized and was left unchanged: %{token}%",
                    field="filenamePrefix",
                )
            )
            return match.group(0)

        return _safe_template_value(replacement, fallback=token_lower.replace(":", "_"))

    return _TEMPLATE_TOKEN.sub(replace_token, raw), tuple(warnings)


def sanitize_filename_component(value: object, default: str = "image") -> str:
    """Return a single safe filename component, rejecting separators."""

    raw = str(value if value is not None else default).strip()
    if not raw:
        raw = default

    normalized = raw.replace("\\", "/")
    if "/" in normalized or normalized in {".", ".."} or _looks_absolute(normalized):
        raise PathSecurityError("filename must be a single relative component")
    return _clean_component(normalized)


def ensure_within_directory(base_directory: os.PathLike[str] | str, target: os.PathLike[str] | str) -> Path:
    """Normalize target and ensure it is inside base_directory."""

    base = Path(base_directory).resolve(strict=False)
    candidate = Path(target).resolve(strict=False)

    try:
        common = os.path.commonpath(
            [
                os.path.normcase(str(base)),
                os.path.normcase(str(candidate)),
            ]
        )
    except ValueError as exc:
        raise PathSecurityError("path is not on the output directory drive") from exc

    if common != os.path.normcase(str(base)):
        raise PathSecurityError("path escapes the output directory")
    return candidate


def safe_output_path(
    output_directory: os.PathLike[str] | str,
    output_folder: os.PathLike[str] | str,
    filename: object,
) -> Path:
    """Build a safe image path inside ComfyUI's output directory."""

    safe_folder = ensure_within_directory(output_directory, output_folder)
    safe_name = sanitize_filename_component(filename)
    return ensure_within_directory(output_directory, safe_folder / safe_name)


def safe_sidecar_path(
    output_directory: os.PathLike[str] | str,
    image_path: os.PathLike[str] | str,
) -> Path:
    """Return a JSON sidecar path next to an already-safe image path."""

    safe_image_path = ensure_within_directory(output_directory, image_path)
    return ensure_within_directory(output_directory, safe_image_path.with_suffix(".json"))


def _looks_absolute(value: str) -> bool:
    return value.startswith("/") or bool(_WINDOWS_DRIVE.match(value))


def _format_date_token(format_text: str, value: datetime) -> str:
    python_format = format_text
    replacements = (
        ("yyyy", "%Y"),
        ("YYYY", "%Y"),
        ("MM", "%m"),
        ("dd", "%d"),
        ("DD", "%d"),
        ("HH", "%H"),
        ("hh", "%H"),
        ("mm", "%M"),
        ("ss", "%S"),
    )
    for source, target in replacements:
        python_format = python_format.replace(source, target)
    return value.strftime(python_format)


def _safe_template_value(value: object | None, *, fallback: str) -> str:
    raw = str(value if value not in {None, ""} else fallback)
    raw = raw.replace("\\", "_").replace("/", "_")
    if _looks_absolute(raw):
        raw = Path(raw).name
    return sanitize_filename_component(raw, fallback)


def _clean_component(value: str) -> str:
    cleaned = _CONTROL_CHARS.sub("_", value)
    cleaned = _WINDOWS_INVALID_CHARS.sub("_", cleaned)
    cleaned = cleaned.strip(" .")
    if not cleaned:
        cleaned = "_"

    stem = cleaned.split(".", 1)[0].upper()
    if stem in _RESERVED_WINDOWS_NAMES:
        cleaned = f"_{cleaned}"

    if len(cleaned) > _MAX_SEGMENT_LENGTH:
        cleaned = cleaned[:_MAX_SEGMENT_LENGTH].rstrip(" .")
    return cleaned or "_"
