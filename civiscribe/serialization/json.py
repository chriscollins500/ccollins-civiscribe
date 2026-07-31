"""One strict JSON encoder for product metadata."""

from __future__ import annotations

import json

from ..domain.errors import SerializationError

DEFAULT_MAX_JSON_CHARS = 4 * 1024 * 1024


def dumps_json(value: object, *, max_chars: int = DEFAULT_MAX_JSON_CHARS) -> str:
    """Serialize strict compact UTF-8 JSON with deterministic key ordering."""

    if max_chars < 1:
        raise SerializationError("json_output_limit_invalid")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise SerializationError("json_value_not_serializable") from exc
    if len(encoded) > max_chars:
        raise SerializationError("json_output_too_large")
    return encoded


__all__ = ["DEFAULT_MAX_JSON_CHARS", "dumps_json"]
