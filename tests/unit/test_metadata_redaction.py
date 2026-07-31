from __future__ import annotations

import math

import pytest

from civiscribe.domain import SerializationError
from civiscribe.security.redaction import (
    MAX_METADATA_DEPTH,
    MAX_METADATA_ITEMS,
    MAX_METADATA_STRING_CHARS,
    sanitize_metadata_json,
)

EXPECTED_REDACTION_COUNT = 4


def test_recursive_metadata_sanitization_preserves_safe_json() -> None:
    source = {
        "nodes": [{"id": 1, "enabled": True, "weight": 0.5, "empty": None}],
        "tuple": ("text", 2),
    }
    result = sanitize_metadata_json(source)
    assert result.value == {
        "nodes": [{"empty": None, "enabled": True, "id": 1, "weight": 0.5}],
        "tuple": ["text", 2],
    }
    assert result.redaction_count == 0


def test_metadata_sanitization_redacts_paths_bearer_and_sensitive_keys() -> None:
    result = sanitize_metadata_json(
        {
            "authorization": "Bearer should-not-survive",
            "message": "Bearer abcdefghijk and /home/person/private/file.txt",
            "path": "\\\\server\\share\\private.bin",
        }
    )
    text = repr(result.value)
    assert "should-not-survive" not in text
    assert "abcdefghijk" not in text
    assert "/home/person" not in text
    assert "\\\\server" not in text
    assert result.redaction_count == EXPECTED_REDACTION_COUNT


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (math.inf, "metadata_number_nonfinite"),
        (object(), "metadata_value_type_unsupported"),
        ({"": "value"}, "metadata_key_invalid"),
        ({"bad\x00key": "value"}, "metadata_key_invalid"),
    ],
)
def test_metadata_sanitization_rejects_invalid_values(
    value: object,
    code: str,
) -> None:
    with pytest.raises(SerializationError, match=code):
        sanitize_metadata_json(value)


def test_metadata_sanitization_rejects_oversized_string() -> None:
    with pytest.raises(SerializationError, match="metadata_string_limit_exceeded"):
        sanitize_metadata_json("x" * (MAX_METADATA_STRING_CHARS + 1))


def test_metadata_sanitization_rejects_excess_depth() -> None:
    value: object = "leaf"
    for _ in range(MAX_METADATA_DEPTH + 1):
        value = [value]
    with pytest.raises(SerializationError, match="metadata_depth_limit_exceeded"):
        sanitize_metadata_json(value)


def test_metadata_sanitization_rejects_excess_items() -> None:
    value = [None] * MAX_METADATA_ITEMS
    with pytest.raises(SerializationError, match="metadata_item_limit_exceeded"):
        sanitize_metadata_json(value)


def test_metadata_sanitization_rejects_stringified_key_collision() -> None:
    with pytest.raises(SerializationError, match="metadata_key_collision"):
        sanitize_metadata_json({1: "number", "1": "string"})
