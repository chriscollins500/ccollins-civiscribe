"""Redact absolute private paths from metadata-bound values."""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

_WINDOWS_ABSOLUTE_RE = re.compile(r"(?<![\w])(?:[a-zA-Z]:[\\/][^\s\"'<>|?*]+)")
_UNC_ABSOLUTE_RE = re.compile(r"(?<![\w])(?:\\\\[^\\/\s]+[\\/][^\\/\s]+[\\/][^\s\"'<>|?*]+)")
_POSIX_ABSOLUTE_RE = re.compile(r"(?<![\w:/])(?:/[^\s\"'<>]+)")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:^|[_\-\s])(?:authorization|api[_\-\s]?key|api[_\-\s]?token|access[_\-\s]?token|token|secret|password)(?:$|[_\-\s])"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|api[_\-\s]?key|api[_\-\s]?token|access[_\-\s]?token|token|secret|password)\b\s*[:=]\s*([^\s,;&\"'<>]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_MAX_DEPTH = 32
MAX_METADATA_STRING_CHARS = 1_000_000
MAX_PNG_TEXT_BYTES = 16 * 1024 * 1024


def sanitize_metadata_value(value: Any, *, _depth: int = 0, _key: str | None = None) -> Any:
    if _depth > _MAX_DEPTH:
        return "<redacted:too_deep>"

    if _key and _is_sensitive_key(_key):
        return "<redacted_secret>"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        return sanitize_metadata_text(value)

    if isinstance(value, dict):
        return {
            sanitize_metadata_text(str(key)): sanitize_metadata_value(
                item,
                _depth=_depth + 1,
                _key=str(key),
            )
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [sanitize_metadata_value(item, _depth=_depth + 1, _key=_key) for item in value]

    return sanitize_metadata_text(str(value))


def sanitize_metadata_text(value: str) -> str:
    text = _CONTROL_CHARS_RE.sub(" ", str(value))
    text = redact_absolute_paths(text)
    text = redact_secrets(text)
    if len(text) > MAX_METADATA_STRING_CHARS:
        text = text[:MAX_METADATA_STRING_CHARS] + f"...<truncated:{MAX_METADATA_STRING_CHARS} chars max>"
    return text


def redact_absolute_paths(value: str) -> str:
    redacted = _UNC_ABSOLUTE_RE.sub(_replace_path_match, value)
    redacted = _WINDOWS_ABSOLUTE_RE.sub(_replace_path_match, redacted)
    redacted = _POSIX_ABSOLUTE_RE.sub(_replace_path_match, redacted)
    return redacted


def redact_secrets(value: str) -> str:
    redacted = _BEARER_RE.sub("Bearer <redacted_secret>", value)
    return _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted_secret>", redacted)


def _is_sensitive_key(value: str) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(value.strip()))


def _replace_path_match(match: re.Match[str]) -> str:
    path_text = match.group(0)
    basename = PureWindowsPath(path_text).name or PurePosixPath(path_text).name
    return f"<redacted_path:{basename or 'path'}>"
