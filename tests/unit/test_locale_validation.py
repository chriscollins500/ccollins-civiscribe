from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.validate_locales import (
    CATALOG_FILENAME,
    SUPPORTED_LOCALES,
    validate_locales,
)

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_LOCALE_LEAF_COUNT = 40


def _catalog(value: object = "Hello {name}") -> dict[str, object]:
    return {"node": {"display_name": value}}


def _write_catalogs(root: Path, value: object = "Hello {name}") -> None:
    for locale in SUPPORTED_LOCALES:
        directory = root / locale
        directory.mkdir(parents=True)
        (directory / CATALOG_FILENAME).write_text(
            json.dumps(_catalog(value), ensure_ascii=False),
            encoding="utf-8",
        )


def test_shipped_locales_have_strict_structural_parity() -> None:
    result = validate_locales(ROOT / "locales")
    assert result.valid
    assert result.errors == ()
    assert result.locale_count == len(SUPPORTED_LOCALES)
    assert result.leaf_count == EXPECTED_LOCALE_LEAF_COUNT


@pytest.mark.parametrize(
    ("replacement", "expected"),
    [
        ("", "ar:node.display_name:blank"),
        ("\u0001", "ar:node.display_name:control_character"),
        ("\u202e", "ar:node.display_name:bidi_control"),
        ("Hello {other}", "ar:node.display_name:placeholder_mismatch"),
        (1, "ar:node.display_name:type_mismatch"),
    ],
)
def test_locale_validator_rejects_unsafe_or_incompatible_leaves(
    tmp_path: Path,
    replacement: object,
    expected: str,
) -> None:
    _write_catalogs(tmp_path)
    (tmp_path / "ar" / CATALOG_FILENAME).write_text(
        json.dumps(_catalog(replacement), ensure_ascii=False),
        encoding="utf-8",
    )
    assert expected in validate_locales(tmp_path).errors


def test_locale_validator_rejects_missing_keys_locales_and_duplicate_json(
    tmp_path: Path,
) -> None:
    _write_catalogs(tmp_path)
    (tmp_path / "ar" / CATALOG_FILENAME).write_text(
        '{"node":{"display_name":"first","display_name":"second"}}',
        encoding="utf-8",
    )
    (tmp_path / "es" / CATALOG_FILENAME).write_text(
        '{"node":{"other":"Hello {name}"}}',
        encoding="utf-8",
    )
    (tmp_path / "fa" / CATALOG_FILENAME).unlink()
    errors = validate_locales(tmp_path).errors
    assert "ar:catalog_invalid" in errors
    assert "es:key_parity_mismatch" in errors
    assert "fa:catalog_invalid" in errors
    assert "locale_set_mismatch" in errors


def test_locale_validator_rejects_invalid_canonical_catalog(tmp_path: Path) -> None:
    _write_catalogs(tmp_path)
    (tmp_path / "en" / CATALOG_FILENAME).write_text("[]", encoding="utf-8")
    result = validate_locales(tmp_path)
    assert not result.valid
    assert result.errors == ("en:catalog_root_invalid",)
    assert result.leaf_count == 0
