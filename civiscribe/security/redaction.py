"""Bounded recursive redaction for embedded ComfyUI JSON."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from ..domain import SerializationError

MAX_METADATA_DEPTH = 32
MAX_METADATA_ITEMS = 500_000
MAX_METADATA_KEY_CHARS = 1_024
MAX_METADATA_STRING_CHARS = 1_000_000

_ABSOLUTE_PATH_FRAGMENT = re.compile(
    r"(?i)(?:[a-z]:[\\/]|\\\\)[^\s\"'<>|]+|/(?:Users|home)/[^\s\"'<>|]+"
)
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SENSITIVE_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "bearer",
        "password",
        "refreshtoken",
        "secret",
        "token",
        "accesstoken",
    }
)

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class JsonSanitizationResult:
    """Sanitized JSON value plus a non-sensitive redaction count."""

    value: JsonValue
    redaction_count: int


@dataclass(slots=True)
class _Budget:
    remaining: int = MAX_METADATA_ITEMS
    redactions: int = 0

    def consume(self) -> None:
        self.remaining -= 1
        if self.remaining < 0:
            raise SerializationError("metadata_item_limit_exceeded")

    def redact(self) -> None:
        self.redactions += 1


def _normalized_key(value: object) -> str:
    key = unicodedata.normalize("NFC", str(value))
    if not key or len(key) > MAX_METADATA_KEY_CHARS or "\x00" in key:
        raise SerializationError("metadata_key_invalid")
    return key


def _is_sensitive_key(key: str) -> bool:
    normalized = "".join(character for character in key.casefold() if character.isalnum())
    return normalized in _SENSITIVE_KEYS


def _clean_text(value: str, budget: _Budget) -> str:
    if len(value) > MAX_METADATA_STRING_CHARS:
        raise SerializationError("metadata_string_limit_exceeded")
    normalized = unicodedata.normalize("NFC", value)
    normalized = "".join(
        character
        if character in {"\n", "\r", "\t"} or unicodedata.category(character) not in {"Cc", "Cf"}
        else " "
        for character in normalized
    )
    redacted, path_count = _ABSOLUTE_PATH_FRAGMENT.subn("<redacted-path>", normalized)
    redacted, secret_count = _BEARER_SECRET.subn("Bearer <redacted-secret>", redacted)
    for _ in range(path_count + secret_count):
        budget.redact()
    return redacted


def _sanitize(
    value: object,
    *,
    budget: _Budget,
    depth: int,
    sensitive: bool = False,
) -> JsonValue:
    if depth > MAX_METADATA_DEPTH:
        raise SerializationError("metadata_depth_limit_exceeded")
    budget.consume()
    if sensitive:
        budget.redact()
        return "<redacted-secret>"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SerializationError("metadata_number_nonfinite")
        return value
    if isinstance(value, str):
        return _clean_text(value, budget)
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, budget=budget, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for raw_key in sorted(value, key=str):
            key = _normalized_key(raw_key)
            if key in result:
                raise SerializationError("metadata_key_collision")
            result[key] = _sanitize(
                value[raw_key],
                budget=budget,
                depth=depth + 1,
                sensitive=_is_sensitive_key(key),
            )
        return result
    raise SerializationError("metadata_value_type_unsupported")


def sanitize_metadata_json(value: object) -> JsonSanitizationResult:
    """Return a JSON-compatible copy with secrets and private paths removed."""

    budget = _Budget()
    sanitized = _sanitize(value, budget=budget, depth=0)
    return JsonSanitizationResult(sanitized, budget.redactions)


__all__ = [
    "MAX_METADATA_DEPTH",
    "MAX_METADATA_ITEMS",
    "MAX_METADATA_KEY_CHARS",
    "MAX_METADATA_STRING_CHARS",
    "JsonSanitizationResult",
    "JsonValue",
    "sanitize_metadata_json",
]
