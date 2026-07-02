"""Strict JSON serialization and redaction for metadata."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
from typing import Any

from ..security.redaction import sanitize_metadata_value


def sanitize_for_json(value: Any) -> Any:
    return sanitize_metadata_value(to_plain_data(value))


def to_plain_data(value: Any) -> Any:
    """Convert supported metadata objects to JSON-compatible primitives."""

    if hasattr(value, "to_json") and callable(value.to_json):
        return to_plain_data(value.to_json())

    if is_dataclass(value):
        return to_plain_data(asdict(value))

    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, Path):
        return value.name

    if isinstance(value, dict):
        return {str(key): to_plain_data(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}

    if isinstance(value, (list, tuple)):
        return [to_plain_data(item) for item in value]

    if isinstance(value, set):
        return sorted((to_plain_data(item) for item in value), key=lambda item: str(item))

    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def to_json_text(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(
        sanitize_for_json(value),
        allow_nan=False,
        ensure_ascii=False,
        indent=indent,
        separators=None if indent else (",", ":"),
        sort_keys=True,
    )
