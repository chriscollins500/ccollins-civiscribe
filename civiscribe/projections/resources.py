"""Shared resource projection helpers used by every metadata carrier."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ..domain import (
    GenerationRecord,
    HashRecord,
    IdentitySource,
    ResourceIdentity,
    ResourceRecord,
    ResourceRole,
    ResourceStatus,
)
from ..identity.resource_types import resource_type_matches_role
from .sanitize import hash_display_name, metadata_scalar, resource_filename, safe_selected_value

_HEX_LENGTHS = {
    "AutoV1": 8,
    "AutoV2": 10,
    "AutoV3": 12,
    "SHA256": 64,
    "CRC32": 8,
    "BLAKE3": 64,
}
_SAFE_CIVITAI_TYPES = {
    "ag",
    "checkpoint",
    "clip",
    "clipvision",
    "controlnet",
    "diffusionmodel",
    "dora",
    "embedding",
    "hypernet",
    "locon",
    "lora",
    "lycoris",
    "motion",
    "other",
    "text_encoders",
    "unet",
    "unknown",
    "upscaler",
    "vae",
    "visionlanguage",
}
_TYPE_ALIASES = {
    "aestheticgradient": "ag",
    "diffusion_model": "diffusionmodel",
    "embed": "embedding",
    "hypernetwork": "hypernet",
    "motionmodule": "motion",
    "text_encoder": "text_encoders",
    "textencoder": "text_encoders",
    "textualinversion": "embedding",
    "textual_inversion": "embedding",
}
_HASH_PREFIXES = {
    ResourceRole.BASE_MODEL: ("model",),
    ResourceRole.LORA: ("LORA", "lora"),
    ResourceRole.VAE: ("VAE", "vae"),
    ResourceRole.TEXT_ENCODER: ("textencoder",),
    ResourceRole.EMBEDDING: ("embed",),
    ResourceRole.HYPERNETWORK: ("hypernet",),
    ResourceRole.CONTROLNET: ("controlnet",),
    ResourceRole.IPADAPTER: ("ipadapter",),
    ResourceRole.STYLE_MODEL: ("stylemodel",),
    ResourceRole.VISION_ENCODER: ("visionencoder",),
    ResourceRole.MODEL_PATCH: ("modelpatch",),
    # Generic aliases can make auxiliary analysis models look Civitai-facing.
    ResourceRole.AUXILIARY_MODEL: (),
    ResourceRole.MOTION_MODULE: ("motion",),
    ResourceRole.GLIGEN: ("gligen",),
    ResourceRole.UPSCALER: ("upscaler",),
}


@dataclass(frozen=True, slots=True)
class ParserResourceDecision:
    """Parser-facing projection result plus structured exclusion diagnostics."""

    item: dict[str, object] | None
    identity_scope: str | None
    exclusion_reason: str | None


def _valid_hex(value: str | None, length: int) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) != length or re.fullmatch(r"[0-9a-fA-F]+", stripped) is None:
        return None
    return stripped.casefold()


def structured_hashes(hashes: HashRecord) -> dict[str, str]:
    """Return only well-formed supported hash values."""

    candidates = {
        "AutoV1": hashes.auto_v1,
        "AutoV2": hashes.auto_v2,
        "AutoV3": hashes.auto_v3,
        "SHA256": hashes.sha256,
        "CRC32": hashes.crc32,
        "BLAKE3": hashes.blake3,
    }
    return {
        name: normalized
        for name, value in candidates.items()
        if (normalized := _valid_hex(value, _HEX_LENGTHS[name])) is not None
    }


def compatibility_hash(hashes: HashRecord) -> str | None:
    """Return an AutoV2-compatible value without computing a file hash."""

    auto_v2 = _valid_hex(hashes.auto_v2, _HEX_LENGTHS["AutoV2"])
    if auto_v2 is not None:
        return auto_v2
    sha256 = _valid_hex(hashes.sha256, _HEX_LENGTHS["SHA256"])
    return sha256[: _HEX_LENGTHS["AutoV2"]] if sha256 is not None else None


def resource_by_key(record: GenerationRecord, key: str | None) -> ResourceRecord | None:
    """Return one active resource by stable key."""

    if key is None:
        return None
    return next(
        (resource for resource in record.resources if resource.active and resource.key == key),
        None,
    )


def _named_hash_keys(resource: ResourceRecord) -> tuple[str, ...]:
    if resource.role is ResourceRole.TEXT_ENCODER and (
        resource.identity is None
        or resource.status is not ResourceStatus.RESOLVED
        or not resource_type_matches_role(
            resource.role,
            resource.identity.resource_type,
        )
    ):
        return ()
    name = resource_filename(resource.filename)
    return tuple(f"{prefix}:{name}" for prefix in _HASH_PREFIXES[resource.role])


def a1111_hashes(record: GenerationRecord) -> dict[str, str]:
    """Build parser-friendly hash aliases from active resources only."""

    result: dict[str, str] = {}
    for resource in record.resources:
        if not resource.active or (value := compatibility_hash(resource.hashes)) is None:
            continue
        for key in _named_hash_keys(resource):
            result.setdefault(key, value)
        if resource.key == record.primary_resource_key:
            result["model"] = value
        if resource.key == record.selected_vae_resource_key:
            result["vae"] = value
    return result


def legacy_hash_list(record: GenerationRecord, role: ResourceRole) -> str | None:
    """Build the quoted legacy LoRA or textual-inversion hash list."""

    pairs: list[str] = []
    seen: set[tuple[str, str]] = set()
    for resource in record.resources:
        if not resource.active or resource.role is not role:
            continue
        value = compatibility_hash(resource.hashes)
        if value is None:
            continue
        name = hash_display_name(resource.filename)
        identity = (name.casefold(), value)
        if identity in seen:
            continue
        seen.add(identity)
        pairs.append(f"{name}: {value}")
    return ", ".join(pairs) or None


def _civitai_type(value: str | None) -> str | None:
    safe = metadata_scalar(value)
    if safe is None:
        return None
    normalized = _TYPE_ALIASES.get(safe.casefold(), safe.casefold())
    return normalized if normalized in _SAFE_CIVITAI_TYPES else None


def _positive_identifier(value: int | None) -> int | None:
    return value if value is not None and value > 0 else None


def _identity_scope(identity: ResourceIdentity | None) -> str | None:
    if identity is None:
        return None
    if identity.file_id is not None and identity.file_primary is not True:
        return "exact_file"
    if (
        identity.canonical_air is not None
        or identity.model_version_id is not None
        or identity.identity_version is not None
    ):
        return "model_version"
    return None


def _add_identity_details(
    item: dict[str, object],
    identity: ResourceIdentity,
    *,
    allowed_partial: bool,
) -> None:
    model_id = _positive_identifier(identity.model_id)
    if model_id is not None:
        item["modelId"] = model_id

    canonical_air = metadata_scalar(identity.canonical_air)
    if canonical_air is not None and canonical_air.casefold().startswith("urn:air:"):
        item["air"] = canonical_air
        item["urn"] = canonical_air
    elif allowed_partial:
        item["identityIncomplete"] = True

    optional_fields = {
        "fileId": identity.file_id,
        "format": identity.format,
        "modelName": identity.model_name,
        "modelVersionName": identity.model_version_name,
    }
    for field_name, value in optional_fields.items():
        if (safe_value := metadata_scalar(value)) is not None:
            item[field_name] = safe_value


def _add_lora_strengths(item: dict[str, object], resource: ResourceRecord) -> None:
    if resource.role is not ResourceRole.LORA:
        return
    weight = resource.strengths.weight
    if weight is None:
        weight = resource.strengths.model
    strengths = {
        "weight": weight,
        "strengthModel": resource.strengths.model,
        "strengthClip": resource.strengths.clip,
    }
    item.update({name: value for name, value in strengths.items() if value is not None})


def parser_resource_decision(resource: ResourceRecord) -> ParserResourceDecision:
    """Explain whether one resource is safe for parser-facing metadata."""

    identity = resource.identity
    scope = _identity_scope(identity)
    item: dict[str, object] | None = None
    reason: str | None = None
    if not resource.active:
        reason = "inactive_resource"
    elif identity is None:
        reason = "identity_missing"
    else:
        resource_type = _civitai_type(identity.resource_type)
        model_version_id = _positive_identifier(identity.model_version_id)
        if resource_type is None:
            reason = "resource_type_unsupported"
        elif model_version_id is None:
            reason = "model_version_id_missing"
        elif not resource_type_matches_role(
            resource.role,
            resource_type,
            allow_ambiguous=True,
        ):
            reason = "resource_type_mismatch"
        else:
            complete = resource.status is ResourceStatus.RESOLVED
            allowed_partial = resource.status is ResourceStatus.PARTIAL and identity.source in {
                IdentitySource.MANUAL,
                IdentitySource.PREFERRED,
            }
            if not complete and not allowed_partial:
                reason = (
                    "identity_conflict"
                    if resource.status is ResourceStatus.CONFLICT
                    else "identity_incomplete"
                )
            else:
                item = {
                    "type": resource_type,
                    "modelVersionId": model_version_id,
                }
                _add_identity_details(item, identity, allowed_partial=allowed_partial)
                _add_lora_strengths(item, resource)
    return ParserResourceDecision(item, scope, reason)


def parser_resource_item(resource: ResourceRecord) -> dict[str, object] | None:
    """Return one identity safe for the A1111 Civitai-resources field."""

    return parser_resource_decision(resource).item


def parser_resource_items(resources: Iterable[ResourceRecord]) -> list[dict[str, object]]:
    """Return deterministic identity-deduplicated parser-facing resources."""

    result: list[dict[str, object]] = []
    seen: set[tuple[object, object, object]] = set()
    for resource in resources:
        item = parser_resource_item(resource)
        if item is None:
            continue
        identity = (item["type"], item["modelVersionId"], item.get("fileId"))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def resource_manifest_item(resource: ResourceRecord) -> dict[str, object]:
    """Project one active resource without private paths or invented identity."""

    identity = resource.identity
    parser_decision = parser_resource_decision(resource)
    identity_json: dict[str, object] | None = None
    if identity is not None:
        identity_json = {
            "source": identity.source.value,
            "rawAir": metadata_scalar(identity.raw_air),
            "canonicalAir": metadata_scalar(identity.canonical_air),
            "ecosystem": metadata_scalar(identity.ecosystem),
            "type": metadata_scalar(identity.resource_type),
            "airSource": metadata_scalar(identity.identity_source),
            "id": metadata_scalar(identity.identity_id),
            "version": metadata_scalar(identity.identity_version),
            "modelId": _positive_identifier(identity.model_id),
            "modelVersionId": _positive_identifier(identity.model_version_id),
            "fileId": metadata_scalar(identity.file_id),
            "format": metadata_scalar(identity.format),
            "fileType": metadata_scalar(identity.file_type),
            "filePrimary": identity.file_primary,
            "baseModel": metadata_scalar(identity.base_model),
            "modelName": metadata_scalar(identity.model_name),
            "modelVersionName": metadata_scalar(identity.model_version_name),
        }
    lookup = resource.lookup_diagnostics
    return {
        "key": metadata_scalar(resource.key),
        "role": resource.role.value,
        "type": resource.kind.value,
        "filename": resource_filename(resource.filename),
        "selectedValue": safe_selected_value(resource.selected_value),
        "nodeId": metadata_scalar(resource.node_id),
        "nodeClass": metadata_scalar(resource.node_class),
        "active": resource.active,
        "detectionRuleId": metadata_scalar(resource.detection_rule_id),
        "strengths": {
            "weight": resource.strengths.weight,
            "model": resource.strengths.model,
            "clip": resource.strengths.clip,
        },
        "hashes": structured_hashes(resource.hashes),
        "hashStatus": resource.hash_status.value,
        "identity": identity_json,
        "identityScope": parser_decision.identity_scope,
        "parserFacing": parser_decision.item is not None,
        "parserExclusionReason": parser_decision.exclusion_reason,
        "status": resource.status.value,
        "lookupStatus": resource.lookup_status.value,
        "lookupDiagnostics": {
            "status": resource.lookup_status.value,
            "attemptedHashTypes": list(lookup.attempted_hash_types),
            "reason": metadata_scalar(lookup.reason),
            "httpStatus": lookup.http_status,
            "retryable": lookup.retryable,
            "retryAfterSeconds": lookup.retry_after_seconds,
            "tlsSource": metadata_scalar(lookup.tls_source),
            "candidateCount": lookup.candidate_count,
            "compatibleCandidateCount": lookup.compatible_candidate_count,
        },
        "resolved": resource.status is ResourceStatus.RESOLVED,
        "unresolvedReason": metadata_scalar(resource.unresolved_reason),
    }


__all__ = [
    "ParserResourceDecision",
    "a1111_hashes",
    "compatibility_hash",
    "legacy_hash_list",
    "parser_resource_decision",
    "parser_resource_item",
    "parser_resource_items",
    "resource_by_key",
    "resource_manifest_item",
    "structured_hashes",
]
