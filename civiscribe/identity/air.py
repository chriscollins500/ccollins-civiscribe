"""Strict Civitai AIR parsing without identity invention."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import cast

from ..domain import IdentitySource, ResourceIdentity, ScanIssue

MAX_AIR_CHARS = 4096
_AIR_FIELD_COUNT = 4
_ASCII_CONTROL_BOUNDARY = 32
_ASCII_DELETE = 127
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FORMAT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_SUPPORTED_TYPES = {
    "ag",
    "checkpoint",
    "clip",
    "clipvision",
    "controlnet",
    "diffusionmodel",
    "dora",
    "embedding",
    "hypernet",
    "image",
    "locon",
    "lora",
    "lycoris",
    "motion",
    "other",
    "text_encoders",
    "textencoder",
    "unet",
    "unknown",
    "upscaler",
    "vae",
    "visionlanguage",
}


@dataclass(frozen=True, slots=True)
class AirParseResult:
    """Validated AIR identity plus sanitized parser diagnostics."""

    identity: ResourceIdentity | None
    issues: tuple[ScanIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class _Identifier:
    identity_id: str
    version: str | None
    file_id: str | None
    file_format: str | None


def _issue(code: str) -> AirParseResult:
    return AirParseResult(None, (ScanIssue(code),))


def _contains_unsafe_text(value: str) -> bool:
    return any(
        character.isspace()
        or ord(character) < _ASCII_CONTROL_BOUNDARY
        or ord(character) == _ASCII_DELETE
        for character in value
    )


def _split_body(raw: str) -> tuple[str, str, str, str] | None:
    if raw.startswith("urn:air:"):
        body = raw[8:]
    elif raw.startswith("air:"):
        body = raw[4:]
    elif raw.startswith("urn:"):
        return None
    else:
        body = raw
    parts = body.split(":", 3)
    if len(parts) != _AIR_FIELD_COUNT or any(not part for part in parts):
        return None
    return parts[0], parts[1], parts[2], parts[3]


def _split_optional_format(value: str) -> tuple[str, str | None]:
    if "." not in value:
        return value, None
    stem, suffix = value.rsplit(".", 1)
    if not stem or _FORMAT_RE.fullmatch(suffix) is None:
        return value, None
    return stem, suffix


def _identifier_parts(value: str) -> tuple[str, str | None, str | None] | None:
    if not value or value.count("@") > 1 or value.count("+") > 1:
        return None
    before_file, separator, file_part = value.partition("+")
    identity_id, version_separator, version = before_file.partition("@")
    if not identity_id or (version_separator and not version):
        return None
    return identity_id, version or None, file_part if separator else None


def _file_details(
    source: str,
    version: str | None,
    file_part: str | None,
) -> tuple[str | None, str | None, str | None] | None:
    if file_part is not None:
        file_id, file_format = _split_optional_format(file_part)
        if file_part == "" or not file_id:
            return None
        return version, file_id, file_format
    if version is not None and source in {"civitai", "civitai-r2"}:
        normalized_version, file_format = _split_optional_format(version)
        if not normalized_version:
            return None
        return normalized_version, None, file_format
    return version, None, None


def _parse_identifier(source: str, value: str) -> _Identifier | None:
    parts = _identifier_parts(value)
    if parts is None:
        return None
    identity_id, version, file_part = parts
    details = _file_details(source, version, file_part)
    if details is None:
        return None
    version, file_id, file_format = details

    if any(_contains_unsafe_text(part) for part in (identity_id, version or "", file_id or "")):
        return None
    if "+" in identity_id or "@" in identity_id:
        return None
    return _Identifier(identity_id, version or None, file_id, file_format)


def _canonical(
    ecosystem: str,
    resource_type: str,
    source: str,
    parsed: _Identifier,
) -> str:
    tail = parsed.identity_id
    if parsed.version is not None:
        tail = f"{tail}@{parsed.version}"
    if parsed.file_id is not None:
        tail = f"{tail}+{parsed.file_id}"
    if parsed.file_format is not None:
        tail = f"{tail}.{parsed.file_format}"
    return f"urn:air:{ecosystem}:{resource_type}:{source}:{tail}"


def _positive_int(value: str | None) -> int | None:
    if value is None or not value.isdecimal():
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _validate_raw_air(raw_air: object) -> AirParseResult | None:
    if raw_air is None or raw_air == "":
        return AirParseResult(None)
    if not isinstance(raw_air, str):
        return _issue("air_value_not_text")
    if len(raw_air) > MAX_AIR_CHARS:
        return _issue("air_value_too_large")
    if _contains_unsafe_text(raw_air):
        return _issue("air_value_contains_unsafe_characters")
    return None


def _civitai_ids(
    source: str,
    parsed: _Identifier,
) -> tuple[int | None, int | None, tuple[ScanIssue, ...], bool]:
    if source != "civitai":
        return None, None, (), True
    model_id = _positive_int(parsed.identity_id)
    model_version_id = _positive_int(parsed.version)
    issues: list[ScanIssue] = []
    if model_id is None:
        issues.append(ScanIssue("air_civitai_model_id_invalid"))
    if parsed.version is None:
        issues.append(ScanIssue("air_civitai_model_version_missing"))
    elif model_version_id is None:
        issues.append(ScanIssue("air_civitai_model_version_invalid"))
    valid = model_id is not None and (parsed.version is None or model_version_id is not None)
    return model_id, model_version_id, tuple(issues), valid


def parse_air(
    raw_air: object,
    *,
    provenance: IdentitySource,
) -> AirParseResult:
    """Parse canonical, ``air:``-prefixed, or documented bare AIR."""

    validation = _validate_raw_air(raw_air)
    if validation is not None:
        return validation
    raw_air = cast(str, raw_air)

    fields = _split_body(raw_air)
    if fields is None:
        return _issue("air_structure_invalid")
    ecosystem, resource_type, source, identifier_text = fields
    ecosystem = ecosystem.casefold()
    resource_type = resource_type.casefold()
    source = source.casefold()
    if any(_SEGMENT_RE.fullmatch(value) is None for value in (ecosystem, resource_type, source)):
        return _issue("air_segment_invalid")

    parsed = _parse_identifier(source, identifier_text)
    if parsed is None:
        return _issue("air_identifier_invalid")

    issues: list[ScanIssue] = []
    if resource_type not in _SUPPORTED_TYPES:
        issues.append(ScanIssue("air_resource_type_unknown"))

    model_id, model_version_id, civitai_issues, valid = _civitai_ids(source, parsed)
    issues.extend(civitai_issues)
    if not valid:
        return AirParseResult(None, tuple(issues))

    canonical = _canonical(ecosystem, resource_type, source, parsed)
    return AirParseResult(
        ResourceIdentity(
            source=provenance,
            raw_air=raw_air,
            canonical_air=canonical,
            ecosystem=ecosystem,
            resource_type=resource_type,
            identity_source=source,
            identity_id=parsed.identity_id,
            identity_version=parsed.version,
            model_id=model_id,
            model_version_id=model_version_id,
            file_id=parsed.file_id,
            format=parsed.file_format,
        ),
        tuple(issues),
    )


def _attachment_format(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized if _FORMAT_RE.fullmatch(normalized) is not None else None


def _attachment_values(
    identity: ResourceIdentity,
    *,
    file_id: str,
    file_format: str | None,
) -> tuple[str, str | None] | AirParseResult:
    normalized_file_id = file_id.strip()
    normalized_format = _attachment_format(file_format)
    if (
        not normalized_file_id
        or len(normalized_file_id) > MAX_AIR_CHARS
        or _contains_unsafe_text(normalized_file_id)
        or "@" in normalized_file_id
        or "+" in normalized_file_id
        or (file_format is not None and normalized_format is None)
    ):
        return _issue("air_file_details_invalid")
    if identity.file_id is not None and identity.file_id != normalized_file_id:
        return _issue("air_file_id_conflict")
    if (
        identity.format is not None
        and normalized_format is not None
        and identity.format.casefold() != normalized_format
    ):
        return _issue("air_file_format_conflict")
    return normalized_file_id, _attachment_format(identity.format) or normalized_format


def _attachment_conflict(
    identity: ResourceIdentity,
    *,
    file_id: str,
    file_format: str | None,
) -> AirParseResult | None:
    if identity.file_id is not None and identity.file_id != file_id:
        return _issue("air_file_id_conflict")
    if (
        identity.format is not None
        and file_format is not None
        and identity.format.casefold() != file_format
    ):
        return _issue("air_file_format_conflict")
    return None


def attach_file_to_air_identity(
    identity: ResourceIdentity,
    *,
    file_id: str,
    file_format: str | None = None,
    pin_canonical: bool = True,
) -> AirParseResult:
    """Attach validated API file facts while preserving the raw AIR exactly."""

    values = _attachment_values(
        identity,
        file_id=file_id,
        file_format=file_format,
    )
    if isinstance(values, AirParseResult):
        return values
    normalized_file_id, selected_format = values
    canonical = identity.canonical_air
    issues: tuple[ScanIssue, ...] = ()
    if canonical is not None:
        parsed = parse_air(canonical, provenance=identity.source)
        if parsed.identity is None:
            return parsed
        issues = parsed.issues
        parsed_identity = parsed.identity
        conflict = _attachment_conflict(
            parsed_identity,
            file_id=normalized_file_id,
            file_format=selected_format,
        )
        if conflict is not None:
            return conflict
        selected_format = _attachment_format(parsed_identity.format) or selected_format
        if pin_canonical or parsed_identity.file_id is not None:
            canonical = _canonical(
                parsed_identity.ecosystem or "",
                parsed_identity.resource_type or "",
                parsed_identity.identity_source or "",
                _Identifier(
                    parsed_identity.identity_id or "",
                    parsed_identity.identity_version,
                    normalized_file_id,
                    selected_format,
                ),
            )

    return AirParseResult(
        replace(
            identity,
            canonical_air=canonical,
            file_id=normalized_file_id,
            format=selected_format,
        ),
        issues,
    )


__all__ = [
    "MAX_AIR_CHARS",
    "AirParseResult",
    "attach_file_to_air_identity",
    "parse_air",
]
