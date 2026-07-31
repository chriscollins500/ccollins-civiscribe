"""Validate immutable V2 golden fixtures and their SHA-256 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

SCHEMA_NAME = "ccollins-civiscribe.golden-manifest"
SCHEMA_VERSION = "1.0.0"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Deterministic manifest validation result."""

    errors: tuple[str, ...]
    fixture_count: int

    @property
    def valid(self) -> bool:
        return not self.errors


def _reject_duplicate_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_key:{key}")
        result[key] = value
    return result


def _load_json(path: Path) -> JsonValue:
    return cast(
        JsonValue,
        json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        ),
    )


def _safe_relative_path(value: JsonValue) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_fixture_fields(
    fixture: dict[str, JsonValue],
    *,
    prefix: str,
) -> list[str]:
    errors: list[str] = []
    expected_size = fixture.get("sizeBytes")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        errors.append(f"{prefix}:size_invalid")

    expected_sha256 = fixture.get("sha256")
    if not isinstance(expected_sha256, str) or SHA256_PATTERN.fullmatch(expected_sha256) is None:
        errors.append(f"{prefix}:sha256_invalid")

    if fixture.get("sourceClass") not in {
        "synthetic",
        "project_authored",
        "sanitized_external",
    }:
        errors.append(f"{prefix}:source_class_invalid")
    if not isinstance(fixture.get("licenseOrConsent"), str) or not fixture["licenseOrConsent"]:
        errors.append(f"{prefix}:license_or_consent_invalid")
    if not isinstance(fixture.get("expected"), dict):
        errors.append(f"{prefix}:expected_invalid")
    if not isinstance(fixture.get("byteEqualityContract"), bool):
        errors.append(f"{prefix}:byte_equality_contract_invalid")
    if not isinstance(fixture.get("updateReason"), str) or not fixture["updateReason"]:
        errors.append(f"{prefix}:update_reason_invalid")
    return errors


def _validate_fixture(
    fixture: JsonValue,
    *,
    index: int,
    fixture_root: Path,
    seen_ids: set[str],
) -> list[str]:
    prefix = f"fixture_{index}"
    if not isinstance(fixture, dict):
        return [f"{prefix}:not_object"]

    errors: list[str] = []
    fixture_id = fixture.get("id")
    if not isinstance(fixture_id, str) or not fixture_id:
        errors.append(f"{prefix}:id_invalid")
    elif fixture_id in seen_ids:
        errors.append(f"{prefix}:id_duplicate")
    else:
        seen_ids.add(fixture_id)

    relative = _safe_relative_path(fixture.get("path"))
    if relative is None:
        return [*errors, f"{prefix}:path_invalid"]

    errors.extend(_validate_fixture_fields(fixture, prefix=prefix))
    fixture_path = fixture_root.joinpath(*relative.parts)
    if not fixture_path.is_file():
        return [*errors, f"{prefix}:file_missing"]

    expected_size = fixture.get("sizeBytes")
    if (
        isinstance(expected_size, int)
        and not isinstance(expected_size, bool)
        and fixture_path.stat().st_size != expected_size
    ):
        errors.append(f"{prefix}:size_mismatch")

    expected_sha256 = fixture.get("sha256")
    if (
        isinstance(expected_sha256, str)
        and SHA256_PATTERN.fullmatch(expected_sha256)
        and _sha256(fixture_path) != expected_sha256
    ):
        errors.append(f"{prefix}:sha256_mismatch")
    return errors


def validate_manifest(path: Path) -> ValidationResult:
    """Validate schema, paths, identity, and bytes for every manifest fixture."""

    errors: list[str] = []
    try:
        payload = _load_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return ValidationResult((f"manifest_unreadable:{type(exc).__name__}",), 0)

    if not isinstance(payload, dict):
        return ValidationResult(("manifest_not_object",), 0)
    if payload.get("schemaName") != SCHEMA_NAME:
        errors.append("schema_name_invalid")
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("schema_version_invalid")

    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list):
        return ValidationResult((*errors, "fixtures_not_array"), 0)

    seen_ids: set[str] = set()
    fixture_root = path.parent
    for index, fixture in enumerate(fixtures):
        errors.extend(
            _validate_fixture(
                fixture,
                index=index,
                fixture_root=fixture_root,
                seen_ids=seen_ids,
            )
        )

    return ValidationResult(tuple(errors), len(fixtures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=Path("tests/golden/manifest.json"),
    )
    args = parser.parse_args()
    result = validate_manifest(args.manifest)
    print(
        json.dumps(
            {
                "errors": list(result.errors),
                "fixtureCount": result.fixture_count,
                "valid": result.valid,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
