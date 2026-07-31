"""Privacy-safe text normalization for parser-facing metadata."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath, PureWindowsPath

_WHITESPACE = re.compile(r"\s+")


def metadata_text(value: str | None) -> str | None:
    """Normalize Unicode and remove non-rendering control characters."""

    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        character
        if character in {"\n", "\t"} or unicodedata.category(character) not in {"Cc", "Cf"}
        else " "
        for character in normalized
    )


def metadata_scalar(value: str | None) -> str | None:
    """Return one injection-resistant A1111 settings value."""

    normalized = metadata_text(value)
    if normalized is None:
        return None
    collapsed = _WHITESPACE.sub(" ", normalized).strip().replace(",", ";")
    return collapsed or None


def resource_filename(value: str) -> str:
    """Return only a resource basename from either path convention."""

    windows_name = PureWindowsPath(value).name
    posix_name = PurePosixPath(windows_name).name
    return metadata_scalar(posix_name or windows_name or value) or "unknown"


def safe_selected_value(value: str) -> str:
    """Keep a safe relative resource value or reduce it to its basename."""

    normalized = unicodedata.normalize("NFC", value).replace("\\", "/")
    windows = PureWindowsPath(normalized)
    posix = PurePosixPath(normalized)
    raw_parts = normalized.split("/")
    if (
        windows.drive
        or windows.root
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or ":" in normalized
    ):
        return resource_filename(normalized).replace(":", ";")
    safe = metadata_scalar(normalized)
    return safe or resource_filename(normalized)


def hash_display_name(value: str) -> str:
    """Return a compact A1111 resource label without a model-file suffix."""

    filename = resource_filename(value)
    lowered = filename.casefold()
    for suffix in (
        ".safetensors",
        ".safetensor",
        ".ckpt",
        ".pt",
        ".pth",
        ".bin",
        ".gguf",
    ):
        if lowered.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


__all__ = [
    "hash_display_name",
    "metadata_scalar",
    "metadata_text",
    "resource_filename",
    "safe_selected_value",
]
