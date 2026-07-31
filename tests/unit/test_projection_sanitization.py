from __future__ import annotations

import math

import pytest

from civiscribe.projections.a1111 import _add_field, _number
from civiscribe.projections.display import display_sampler, display_scheduler
from civiscribe.projections.sanitize import (
    hash_display_name,
    metadata_scalar,
    metadata_text,
    resource_filename,
    safe_selected_value,
)


def test_metadata_text_normalizes_unicode_newlines_and_controls() -> None:
    value = "Cafe\u0301\r\nline\tkeep\x00drop\u200b"

    assert metadata_text(value) == "Café\nline\tkeep drop "
    assert metadata_text(None) is None


def test_metadata_scalar_is_single_line_comma_safe_and_nullable() -> None:
    assert metadata_scalar("  one,\n two  ") == "one; two"
    assert metadata_scalar("") is None
    assert metadata_scalar(None) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (r"C:\private\models\model.gguf", "model.gguf"),
        ("/private/models/model.gguf", "model.gguf"),
        ("", "unknown"),
    ],
)
def test_resource_filename_discards_path_context(value: str, expected: str) -> None:
    assert resource_filename(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("models/sub/model.gguf", "models/sub/model.gguf"),
        (r"C:\private\model.gguf", "model.gguf"),
        ("/private/model.gguf", "model.gguf"),
        ("../private/model.gguf", "model.gguf"),
        ("models/./model.gguf", "model.gguf"),
        ("models:name.gguf", "models;name.gguf"),
        ("", "unknown"),
    ],
)
def test_selected_value_keeps_only_safe_relative_identifiers(
    value: str,
    expected: str,
) -> None:
    assert safe_selected_value(value) == expected


def test_hash_display_name_strips_known_model_suffix_only() -> None:
    assert hash_display_name("models/portrait.safetensors") == "portrait"
    assert hash_display_name("models/portrait.custom") == "portrait.custom"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        (3, "3"),
        (3.0, "3"),
        (0.0, "0"),
        (2.5, "2.5"),
        (math.inf, None),
    ],
)
def test_a1111_number_formatting_is_finite_and_stable(
    value: int | float | None,
    expected: str | None,
) -> None:
    assert _number(value) == expected


def test_a1111_add_field_omits_empty_values() -> None:
    fields: list[tuple[str, str]] = []

    _add_field(fields, "none", None)
    _add_field(fields, "empty", "")
    _add_field(fields, "known", "value")

    assert fields == [("known", "value")]


def test_display_aliases_map_known_values_and_preserve_safe_custom_values() -> None:
    assert display_sampler("dpmpp_2m") == "DPM++ 2M"
    assert display_sampler("custom,\nsampler") == "custom; sampler"
    assert display_sampler(None) is None
    assert display_scheduler("karras") == "Karras"
    assert display_scheduler("custom_schedule") == "custom_schedule"
    assert display_scheduler(None) is None
