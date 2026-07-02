"""Attach local hash identity to scanned resources."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .hashes import HashCache, HashCacheIdentity, compute_file_hashes
from .resolver import ModelRootResolver
from ..metadata.schema import (
    GenerationSettings,
    HashMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
)

HASHED_BUT_NO_CIVITAI_IDENTITY = "hashed_but_no_civitai_identity"


@dataclass(frozen=True)
class ResourceHashingResult:
    resources: tuple[ResolvedResource, ...]
    unresolved_resources: tuple[UnresolvedResource, ...]
    hashes: HashMetadata
    generation: GenerationSettings
    warnings: tuple[ValidationIssue, ...]


def attach_local_hashes(
    *,
    resources: tuple[ResolvedResource, ...],
    generation: GenerationSettings,
    resolver: ModelRootResolver | None = None,
    cache: HashCache | None = None,
    max_size_bytes: int | None = None,
    hashing_mode: str = "full",
) -> ResourceHashingResult:
    resolver = resolver or ModelRootResolver.from_comfy()
    warnings: list[ValidationIssue] = []
    if cache is not None:
        warnings.extend(cache.warnings)
    updated_resources: list[ResolvedResource] = []

    for resource in resources:
        metadata = resource.resource
        resolution = resolver.resolve(metadata)
        warnings.extend(resolution.warnings)

        if resolution.path is None or resolution.status != "resolved":
            updated_resources.append(
                replace(
                    resource,
                    resolved=False,
                    unresolved_reason=resource.unresolved_reason or resolution.status,
                    resource=replace(
                        metadata,
                        hash_status=resolution.status,
                        hash_error=_first_warning_message(resolution.warnings),
                    ),
                )
            )
            continue

        hash_kwargs = {
            "cache": cache,
            "cache_identity": HashCacheIdentity(
                category=resolution.cache_category or metadata.role,
                selected_value=resolution.cache_selected_value
                or metadata.selected_value
                or metadata.filename
                or metadata.name
                or "model",
            ),
        }
        if max_size_bytes is not None:
            hash_kwargs["max_size_bytes"] = max_size_bytes
        hash_kwargs["hashing_mode"] = hashing_mode
        hash_result = compute_file_hashes(resolution.path, **hash_kwargs)
        if hash_result.warning is not None:
            warnings.append(hash_result.warning)
        if cache is not None:
            warnings.extend(cache.warnings)

        updated_metadata = replace(
            metadata,
            hashes=hash_result.hashes,
            hash_source=hash_result.source,
            hash_status=hash_result.status,
            hash_error=hash_result.warning.message if hash_result.warning else None,
        )
        has_identity = _has_civitai_identity(updated_metadata)
        updated_resources.append(
            replace(
                resource,
                resource=updated_metadata,
                resolved=has_identity,
                unresolved_reason=None if has_identity else _unresolved_reason(hash_result.status),
            )
        )

    updated_tuple = tuple(updated_resources)
    unresolved = tuple(_unresolved_from_resource(resource) for resource in updated_tuple if not resource.resolved)
    generation_with_hashes = apply_hashes_to_generation(generation, updated_tuple)
    hashes = build_resource_hash_summary(updated_tuple, generation_with_hashes)
    if _ambiguous_base_model_hash(updated_tuple, generation_with_hashes):
        warnings.append(
            ValidationIssue(
                code="primary_model_hash_ambiguous",
                message="Model hash was not written because multiple base models were detected without a primary model",
                field="generation.modelHash",
            )
        )
    return ResourceHashingResult(
        resources=updated_tuple,
        unresolved_resources=unresolved,
        hashes=hashes,
        generation=generation_with_hashes,
        warnings=tuple(warnings),
    )


def build_resource_hash_summary(
    resources: tuple[ResolvedResource, ...],
    generation: GenerationSettings | None = None,
) -> HashMetadata:
    entries: dict[str, str] = {}
    primary = _select_primary_base_resource(resources, generation)
    for resource in resources:
        metadata = resource.resource
        value = _preferred_hash(metadata.hashes)
        if value is None:
            continue
        is_primary = primary is resource
        for key in _hash_keys(metadata.role, metadata.name or metadata.filename or "resource", is_primary=is_primary):
            entries[key] = value
    return HashMetadata(additional=entries)


def apply_hashes_to_generation(
    generation: GenerationSettings,
    resources: tuple[ResolvedResource, ...],
) -> GenerationSettings:
    model_hash = generation.model_hash
    vae_hash = generation.vae_hash
    model = generation.model
    primary = _select_primary_base_resource(resources, generation)
    if model is None and primary is not None:
        model = primary.resource.name or primary.resource.filename
    if model_hash is None and primary is not None:
        model_hash = _preferred_hash(primary.resource.hashes)

    for resource in resources:
        metadata = resource.resource
        value = _preferred_hash(metadata.hashes)
        if value is None:
            continue
        if vae_hash is None and metadata.role == "vae":
            vae_hash = value
    return replace(generation, model=model, model_hash=model_hash, vae_hash=vae_hash)


def _unresolved_from_resource(resource: ResolvedResource) -> UnresolvedResource:
    metadata = resource.resource
    return UnresolvedResource(
        reason=resource.unresolved_reason or "resource_not_civitai_resolved",
        role=metadata.role,
        type=metadata.type,
        node_id=metadata.node_id,
        node_class_type=metadata.node_class_type,
        display_name=metadata.display_name,
        name=metadata.name,
        selected_value=metadata.selected_value,
        filename=metadata.filename,
        local_path_basename=metadata.local_path_basename,
        raw_air=metadata.air.raw if metadata.air else None,
        hashes=metadata.hashes,
        hash_source=metadata.hash_source,
        hash_status=metadata.hash_status,
        hash_error=metadata.hash_error,
        resolution_source=metadata.resolution_source,
        lookup_status=_metadata_lookup_str(metadata, "lookupStatus"),
        lookup_failure_reason=_metadata_lookup_str(metadata, "lookupFailureReason"),
        lookup_failure_class=_metadata_lookup_str(metadata, "lookupFailureClass"),
        lookup_failure_detail_sanitized=_metadata_lookup_str(metadata, "lookupFailureDetailSanitized"),
        lookup_status_code=_metadata_lookup_int(metadata, "lookupStatusCode"),
        lookup_retryable=_metadata_lookup_bool(metadata, "lookupRetryable"),
        lookup_method=_metadata_lookup_str(metadata, "lookupMethod"),
        lookup_client=_metadata_lookup_str(metadata, "lookupClient"),
        ssl_context_source=_metadata_lookup_str(metadata, "sslContextSource"),
        api_endpoint_kind=_metadata_lookup_str(metadata, "apiEndpointKind"),
        strength=metadata.strength,
        strength_model=metadata.strength_model,
        strength_clip=metadata.strength_clip,
    )


def _metadata_lookup_str(metadata: object, key: str) -> str | None:
    raw_metadata = getattr(metadata, "metadata", {})
    value = raw_metadata.get(key) if isinstance(raw_metadata, dict) else None
    if value is None or value == "":
        return None
    return str(value)


def _metadata_lookup_int(metadata: object, key: str) -> int | None:
    raw_metadata = getattr(metadata, "metadata", {})
    value = raw_metadata.get(key) if isinstance(raw_metadata, dict) else None
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata_lookup_bool(metadata: object, key: str) -> bool | None:
    raw_metadata = getattr(metadata, "metadata", {})
    value = raw_metadata.get(key) if isinstance(raw_metadata, dict) else None
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    return str(value).strip().lower() in {"1", "true", "yes"}


def _has_civitai_identity(metadata: object) -> bool:
    return bool(
        getattr(metadata, "civitai_model_version_id", None)
        or (getattr(metadata, "air", None) is not None and getattr(metadata.air, "model_version_id", None) is not None)
    )


def _unresolved_reason(hash_status: str) -> str:
    if hash_status == "hashed" or hash_status == "hashed_fast_partial":
        return HASHED_BUT_NO_CIVITAI_IDENTITY
    return hash_status


def _preferred_hash(hashes: HashMetadata) -> str | None:
    return hashes.auto_v2 or hashes.sha256 or hashes.blake3 or hashes.auto_v3 or hashes.crc32 or hashes.auto_v1


def _hash_keys(role: str, name: str, *, is_primary: bool = False) -> tuple[str, ...]:
    if role in {"checkpoint", "base_model"}:
        if is_primary:
            return ("Model", "model")
        return (f"Base model:{name}",)
    if role == "lora":
        return (f"LORA:{name}",)
    if role == "vae":
        return (f"VAE:{name}", "vae")
    if role == "embedding":
        return (f"Embedding:{name}",)
    if role == "controlnet":
        return (f"ControlNet:{name}",)
    if role == "ipadapter":
        return (f"IPAdapter:{name}",)
    if role == "upscaler":
        return (f"Upscaler:{name}",)
    if role == "text_encoder":
        return (f"Text Encoder:{name}",)
    return (f"{role}:{name}",)


def _select_primary_base_resource(
    resources: tuple[ResolvedResource, ...],
    generation: GenerationSettings | None,
) -> ResolvedResource | None:
    base_resources = [resource for resource in resources if resource.resource.role in {"checkpoint", "base_model"}]
    for resource in base_resources:
        if resource.resource.metadata.get("primaryModel"):
            return resource
    if generation is not None and generation.model:
        for resource in base_resources:
            metadata = resource.resource
            if generation.model in {metadata.name, metadata.filename, metadata.selected_value}:
                return resource
    if len(base_resources) == 1:
        return base_resources[0]
    return None


def _ambiguous_base_model_hash(
    resources: tuple[ResolvedResource, ...],
    generation: GenerationSettings,
) -> bool:
    base_resources = [
        resource
        for resource in resources
        if resource.resource.role in {"checkpoint", "base_model"}
        and _preferred_hash(resource.resource.hashes) is not None
    ]
    return len(base_resources) > 1 and _select_primary_base_resource(resources, generation) is None


def _first_warning_message(warnings: tuple[ValidationIssue, ...]) -> str | None:
    return warnings[0].message if warnings else None


__all__ = [
    "HASHED_BUT_NO_CIVITAI_IDENTITY",
    "ResourceHashingResult",
    "apply_hashes_to_generation",
    "attach_local_hashes",
    "build_resource_hash_summary",
]
