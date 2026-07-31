"""Validate one CiviScribe V2 sidecar without mutating it."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from civiscribe.schemas import sidecar_schema_path

_ABSOLUTE_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\|/(?:Users|home)/)")
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SENSITIVE_KEYS = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "bearer",
        "password",
        "refreshtoken",
        "secret",
        "token",
    }
)
_REDACTED_VALUES = frozenset({"", "<redacted-secret>"})
_FORMAT_FACTS = {
    "png": ({"png"}, "image/png"),
    "jpeg": ({"jpg", "jpeg"}, "image/jpeg"),
    "webp": ({"webp"}, "image/webp"),
}
_MODE_CHANNELS = {"L": 1, "RGB": 3, "RGBA": 4}

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class SidecarValidationResult:
    """Deterministic validation result with privacy-safe error codes."""

    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def _reject_duplicate_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
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


def _normalized_sensitive_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _sensitive_value_is_redacted(value: JsonValue) -> bool:
    return value is None or (isinstance(value, str) and value in _REDACTED_VALUES)


def _privacy_errors(value: JsonValue) -> Iterator[str]:
    if isinstance(value, str):
        if _ABSOLUTE_PATH.search(value) is not None:
            yield "privacy:absolute_path"
        if _BEARER_SECRET.search(value) is not None:
            yield "privacy:bearer_secret"
        return
    if isinstance(value, list):
        for item in value:
            yield from _privacy_errors(item)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if _normalized_sensitive_key(key) in _SENSITIVE_KEYS and not _sensitive_value_is_redacted(
            item
        ):
            yield "privacy:sensitive_value"
        yield from _privacy_errors(item)


def _schema_errors(payload: JsonValue, schema: JsonValue) -> Iterator[str]:
    if not isinstance(schema, dict):
        yield "schema:not_object"
        return
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        yield "schema:definition_invalid"
        return
    validator = Draft202012Validator(schema)
    for error in sorted(
        validator.iter_errors(payload),
        key=lambda item: (
            tuple(str(part) for part in item.absolute_path),
            str(item.validator),
        ),
    ):
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        yield f"schema:{path}:{error.validator}"


def _semantic_errors(payload: JsonValue) -> Iterator[str]:
    if not isinstance(payload, dict):
        return
    artifact = payload.get("artifact")
    if not isinstance(artifact, dict):
        return
    output_format = artifact.get("format")
    filename = artifact.get("fileName")
    mime_type = artifact.get("mimeType")
    if isinstance(output_format, str) and output_format in _FORMAT_FACTS:
        extensions, expected_mime = _FORMAT_FACTS[output_format]
        if (
            not isinstance(filename, str)
            or filename.rpartition(".")[2].casefold() not in extensions
            or mime_type != expected_mime
        ):
            yield "semantic:artifact_format_mismatch"

    sidecar_filename = artifact.get("sidecarFileName")
    if (
        isinstance(filename, str)
        and isinstance(sidecar_filename, str)
        and (
            sidecar_filename.rpartition(".")[2].casefold() != "json"
            or sidecar_filename.rpartition(".")[0] != filename.rpartition(".")[0]
        )
    ):
        yield "semantic:sidecar_filename_mismatch"

    subfolder = artifact.get("subfolder")
    if isinstance(subfolder, str) and subfolder:
        parts = subfolder.split("/")
        if (
            subfolder.startswith("/")
            or subfolder.endswith("/")
            or "\\" in subfolder
            or ":" in subfolder
            or "\x00" in subfolder
            or any(part in {"", ".", ".."} for part in parts)
        ):
            yield "semantic:subfolder_unsafe"

    mode = artifact.get("mode")
    channels = artifact.get("channels")
    has_alpha = artifact.get("hasAlpha")
    if (
        isinstance(mode, str)
        and mode in _MODE_CHANNELS
        and (channels != _MODE_CHANNELS[mode] or has_alpha != (mode == "RGBA"))
    ):
        yield "semantic:artifact_mode_mismatch"

    generation_record = payload.get("generationRecord")
    if not isinstance(generation_record, dict):
        return
    record_image = generation_record.get("image")
    if not isinstance(record_image, dict):
        return
    for key in ("format", "width", "height", "batchIndex"):
        if record_image.get(key) != artifact.get(key):
            yield "semantic:generation_image_mismatch"
            return


def validate_sidecar(
    path: Path,
    *,
    schema_path: Path | None = None,
) -> SidecarValidationResult:
    """Validate strict JSON, the packaged schema, and privacy invariants."""

    try:
        payload = _load_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return SidecarValidationResult((f"sidecar_unreadable:{type(exc).__name__}",))

    try:
        schema = _load_json(schema_path or sidecar_schema_path())
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return SidecarValidationResult((f"schema_unreadable:{type(exc).__name__}",))

    schema_errors = tuple(_schema_errors(payload, schema))
    if any(error in {"schema:not_object", "schema:definition_invalid"} for error in schema_errors):
        return SidecarValidationResult(tuple(sorted(set(schema_errors))))
    errors = sorted({*schema_errors, *_semantic_errors(payload), *_privacy_errors(payload)})
    return SidecarValidationResult(tuple(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", type=Path)
    parser.add_argument("--schema", type=Path, default=None)
    args = parser.parse_args()
    result = validate_sidecar(args.sidecar, schema_path=args.schema)
    print(
        json.dumps(
            {
                "errors": list(result.errors),
                "valid": result.valid,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
