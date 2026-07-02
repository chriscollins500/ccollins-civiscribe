"""AIR URN parsing and formatting."""

from __future__ import annotations

from ..metadata.schema import AIRMetadata, ValidationIssue

_SUPPORTED_TYPES = {
    "checkpoint",
    "lora",
    "embedding",
    "vae",
    "controlnet",
    "upscaler",
    "diffusionmodel",
    "unet",
    "other",
    "image",
}


def parse_air(raw_air: str | None) -> tuple[AIRMetadata | None, tuple[ValidationIssue, ...]]:
    """Parse Civitai AIR while preserving the raw input exactly."""

    if raw_air is None or raw_air == "":
        return None, ()

    raw = str(raw_air)
    body = raw
    warnings: list[ValidationIssue] = []

    if body.startswith("urn:air:"):
        body = body[len("urn:air:") :]
    elif body.startswith("air:"):
        body = body[len("air:") :]
    else:
        body = body

    parts = body.split(":", 3)
    if len(parts) != 4 or any(part == "" for part in parts):
        return None, (_malformed(raw, "AIR must contain ecosystem, type, source, and id"),)

    ecosystem, resource_type, source, identifier = parts
    if resource_type not in _SUPPORTED_TYPES:
        warnings.append(
            ValidationIssue(
                code="air_unknown_resource_type",
                message=f"AIR resource type is not in the known Civitai type list: {resource_type}",
                field="air.type",
            )
        )

    identifier, layer, legacy_format = _split_legacy_layer_format(identifier, source)
    parsed = _parse_identifier(raw, identifier)
    warnings.extend(parsed.warnings)
    version, version_format = _split_civitai_r2_version_format(parsed.version, source)
    file_format = parsed.format or version_format or legacy_format

    canonical = _canonical_air(
        ecosystem=ecosystem,
        resource_type=resource_type,
        source=source,
        identifier=parsed.id,
        version=version,
        file_id=parsed.file_id,
        file_format=file_format,
    )
    model_id = _parse_int(parsed.id) if source == "civitai" else None
    model_version_id = _parse_int(version or "") if source == "civitai" else None
    if source == "civitai":
        if model_id is None:
            warnings.append(_malformed(raw, "Civitai AIR model id is not numeric"))
        if version is None:
            warnings.append(
                ValidationIssue(
                    code="air_missing_model_version_id",
                    message="Civitai AIR does not include a model version id",
                    field="air.modelVersionId",
                )
            )
        if version is not None and model_version_id is None:
            warnings.append(_malformed(raw, "Civitai AIR model version id is not numeric"))

    metadata = AIRMetadata(
        raw=raw,
        canonical=canonical,
        scheme="urn",
        namespace="air",
        ecosystem=ecosystem,
        type=resource_type,
        source=source,
        id=parsed.id,
        version=version,
        file_id=parsed.file_id,
        model_id=model_id,
        model_version_id=model_version_id,
        layer=layer,
        format=file_format,
    )
    return metadata, tuple(warnings)


def format_air(air: AIRMetadata) -> str:
    """Return canonical AIR for emitted metadata."""

    return air.canonical


class _IdentifierParts:
    def __init__(
        self,
        *,
        id: str,
        version: str | None,
        file_id: str | None,
        format: str | None,
        warnings: tuple[ValidationIssue, ...] = (),
    ) -> None:
        self.id = id
        self.version = version
        self.file_id = file_id
        self.format = format
        self.warnings = warnings


def _parse_identifier(raw: str, identifier: str) -> _IdentifierParts:
    if not identifier:
        return _IdentifierParts(
            id="", version=None, file_id=None, format=None, warnings=(_malformed(raw, "AIR id is empty"),)
        )

    if "@" in identifier:
        item_id, rest = identifier.split("@", 1)
    else:
        item_id, rest = identifier, ""

    version = rest or None
    file_id = None
    file_format = None
    if version and "+" in version:
        version, file_part = version.split("+", 1)
        version = version or None
        file_id, file_format = _split_file_format(file_part)

    warnings: list[ValidationIssue] = []
    if not item_id:
        warnings.append(_malformed(raw, "AIR id is empty"))
    return _IdentifierParts(
        id=item_id,
        version=version,
        file_id=file_id,
        format=file_format,
        warnings=tuple(warnings),
    )


def _split_file_format(value: str) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    if "." not in value:
        return value, None
    file_id, file_format = value.rsplit(".", 1)
    return file_id or None, file_format or None


def _split_civitai_r2_version_format(version: str | None, source: str) -> tuple[str | None, str | None]:
    if source != "civitai-r2" or not version or "." not in version:
        return version, None
    stem, file_format = version.rsplit(".", 1)
    if not stem or not file_format:
        return version, None
    return stem, file_format


def _split_legacy_layer_format(identifier: str, source: str) -> tuple[str, str | None, str | None]:
    if source != "civitai" or identifier.count(":") != 2:
        return identifier, None, None
    head, layer, file_format = identifier.split(":", 2)
    if "@" not in head:
        return identifier, None, None
    return head, layer or None, file_format or None


def _canonical_air(
    *,
    ecosystem: str,
    resource_type: str,
    source: str,
    identifier: str,
    version: str | None,
    file_id: str | None,
    file_format: str | None,
) -> str:
    tail = identifier
    if version is not None:
        tail = f"{tail}@{version}"
    if file_id is not None:
        tail = f"{tail}+{file_id}"
    if file_format is not None and (file_id is not None or version is not None):
        tail = f"{tail}.{file_format}"
    return f"urn:air:{ecosystem}:{resource_type}:{source}:{tail}"


def _parse_int(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    return None


def _malformed(raw: str, message: str) -> ValidationIssue:
    return ValidationIssue(
        code="malformed_air",
        message=f"{message}: {raw}",
        field="air",
    )


__all__ = ["format_air", "parse_air"]
