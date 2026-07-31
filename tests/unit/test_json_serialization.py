from __future__ import annotations

import json

import pytest

from civiscribe.domain import SerializationError
from civiscribe.serialization import dumps_json


def test_json_serialization_is_deterministic_strict_and_utf8_safe() -> None:
    value = {"z": "雪", "a": [1, True, None]}

    first = dumps_json(value)
    second = dumps_json(value)

    assert first == second == '{"a":[1,true,null],"z":"雪"}'
    assert json.loads(first) == value
    assert "NaN" not in first


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"value": float("nan")}, "json_value_not_serializable"),
        ({"value": object()}, "json_value_not_serializable"),
    ],
)
def test_json_serialization_rejects_non_json_values(value: object, message: str) -> None:
    with pytest.raises(SerializationError, match=message):
        dumps_json(value)


def test_json_serialization_enforces_positive_bounded_output() -> None:
    with pytest.raises(SerializationError, match="json_output_limit_invalid"):
        dumps_json({}, max_chars=0)
    with pytest.raises(SerializationError, match="json_output_too_large"):
        dumps_json({"value": "large"}, max_chars=2)
