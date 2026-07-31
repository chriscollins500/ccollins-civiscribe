"""Validate CiviScribe's ComfyUI-native locale catalogs."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

CANONICAL_LOCALE = "en"
SUPPORTED_LOCALES = (
    "ar",
    "en",
    "es",
    "fa",
    "fr",
    "ja",
    "ko",
    "pt-BR",
    "ru",
    "tr",
    "zh",
    "zh-TW",
)
CATALOG_FILENAME = "nodeDefs.json"
CONTROL_CODEPOINT_BOUNDARY = 32
_PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_BIDI_CONTROLS = frozenset(
    {
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
)


class DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a key."""


@dataclass(frozen=True, slots=True)
class LocaleValidation:
    """Deterministic locale validation result."""

    errors: tuple[str, ...]
    locale_count: int
    leaf_count: int

    @property
    def valid(self) -> bool:
        return not self.errors


def _reject_duplicates(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate_key:{key}")
        result[key] = value
    return result


def _load_catalog(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
    )


def _leaves(value: object, prefix: str = "") -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {prefix: value}
    result: dict[str, object] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        result.update(_leaves(child, path))
    return result


def _string_error(locale: str, path: str, value: str, canonical: str) -> str | None:
    if not value.strip():
        return f"{locale}:{path}:blank"
    if any(
        ord(character) < CONTROL_CODEPOINT_BOUNDARY and character not in {"\n", "\r", "\t"}
        for character in value
    ):
        return f"{locale}:{path}:control_character"
    if any(character in _BIDI_CONTROLS for character in value):
        return f"{locale}:{path}:bidi_control"
    if sorted(_PLACEHOLDER.findall(value)) != sorted(_PLACEHOLDER.findall(canonical)):
        return f"{locale}:{path}:placeholder_mismatch"
    return None


def _load_catalogs(root: Path) -> tuple[tuple[str, ...], dict[str, object], list[str]]:
    errors: list[str] = []
    found = tuple(
        sorted(
            path.name
            for path in root.iterdir()
            if path.is_dir() and (path / CATALOG_FILENAME).is_file()
        )
    )
    if found != SUPPORTED_LOCALES:
        errors.append("locale_set_mismatch")
    catalogs: dict[str, object] = {}
    for locale in SUPPORTED_LOCALES:
        catalog_path = root / locale / CATALOG_FILENAME
        try:
            catalogs[locale] = _load_catalog(catalog_path)
        except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError):
            errors.append(f"{locale}:catalog_invalid")
    return found, catalogs, errors


def _validate_canonical(catalog: object, errors: list[str]) -> dict[str, object] | None:
    if not isinstance(catalog, Mapping):
        errors.append("en:catalog_root_invalid")
        return None
    canonical = _leaves(catalog)
    for leaf_path, value in canonical.items():
        if not isinstance(value, str):
            errors.append(f"en:{leaf_path}:non_string_leaf")
        elif (error := _string_error("en", leaf_path, value, value)) is not None:
            errors.append(error)
    return canonical


def _validate_translation(
    locale: str,
    catalog: object,
    canonical: Mapping[str, object],
    errors: list[str],
) -> None:
    if not isinstance(catalog, Mapping):
        errors.append(f"{locale}:catalog_root_invalid")
        return
    leaves = _leaves(catalog)
    if leaves.keys() != canonical.keys():
        errors.append(f"{locale}:key_parity_mismatch")
        return
    for leaf_path, canonical_value in canonical.items():
        value = leaves[leaf_path]
        if type(value) is not type(canonical_value):
            errors.append(f"{locale}:{leaf_path}:type_mismatch")
        elif (
            isinstance(value, str)
            and isinstance(canonical_value, str)
            and (
                error := _string_error(
                    locale,
                    leaf_path,
                    value,
                    canonical_value,
                )
            )
            is not None
        ):
            errors.append(error)


def validate_locales(root: Path) -> LocaleValidation:
    """Validate all shipped locale catalogs against canonical English."""

    found, catalogs, errors = _load_catalogs(root)
    canonical_value = catalogs.get(CANONICAL_LOCALE)
    canonical = _validate_canonical(canonical_value, errors)
    if canonical is None:
        return LocaleValidation(tuple(sorted(set(errors))), len(found), 0)

    for locale in SUPPORTED_LOCALES:
        if locale == CANONICAL_LOCALE or locale not in catalogs:
            continue
        _validate_translation(locale, catalogs[locale], canonical, errors)
    return LocaleValidation(
        tuple(sorted(set(errors))),
        len(found),
        len(canonical),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "locales",
    )
    return parser


def main() -> int:
    result = validate_locales(_parser().parse_args().root)
    print(
        json.dumps(
            {
                "errors": list(result.errors),
                "leafCount": result.leaf_count,
                "localeCount": result.locale_count,
                "valid": result.valid,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
