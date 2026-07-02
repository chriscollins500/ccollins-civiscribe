"""Minimal ComfyUI save-image node with safe metadata handling."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from .civitai.identity_cache import (
    combine_identity_caches,
    default_identity_cache_path,
    generated_identity_cache_path,
    load_identity_cache,
)
from .civitai.identity_resolution import apply_identity_cache
from .civitai.lookup import CivitaiLookupSettings, resolve_resources_with_civitai_api
from .civitai.manual_identities import apply_manual_resource_identities, apply_preferred_primary_model_air
from .civitai.manifest import build_civitai_manifest
from .comfy.workflow_scan import scan_workflow_graph
from .io.paths import expand_filename_template, normalize_filename_prefix, safe_output_path
from .io.png_writer import build_pnginfo, parameters_text_needs_latin1_fallback
from .io.sidecar import (
    build_resource_lifecycle,
    build_sidecar_payload,
    empty_resource_lifecycle,
    write_sidecar_json_file,
)
from .hashing.hashes import HashCache, default_hash_cache_path
from .hashing.resource_identity import attach_local_hashes
from .metadata.a1111 import build_a1111_parameters
from .metadata.exif_user_comment import build_exif_bytes
from .metadata.schema import (
    GenerationSettings,
    GeneratorMetadata,
    HashMetadata,
    IdentityCacheMetadata,
    MetadataOptions,
    PromptMetadata,
    ValidationIssue,
    ValidationResult,
)
from .metadata.serialize import sanitize_for_json
from .metadata.validate import validate_metadata

try:
    import folder_paths
except Exception:  # pragma: no cover - available inside ComfyUI
    folder_paths = None

_PERSISTENT_HASH_CACHE = HashCache(persistent_path=default_hash_cache_path())
_MEMORY_HASH_CACHE = HashCache()


class SaveImageWithCivitaiMetadata:
    """Save images through ComfyUI's output folder with Civitai-compatible metadata."""

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    CATEGORY = "image"

    type = "output"

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The generated image to save."}),
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "CivitaiMetadata",
                        "tooltip": "Where to save the image and how to name it. Supports tokens like %date:yyyy-MM-dd%, %date:hhmmss%, %model%, %seed%, %width%, and %height%.",
                    },
                ),
                "write_sidecar_json": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "Also save a JSON sidecar next to the image. Useful for debugging or checking exactly what metadata was written. The image still saves if the sidecar fails.",
                    },
                ),
                "strict_mode": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "Debug option. When off, the image saves even if metadata has problems. Recommended: off.",
                    },
                ),
                "include_workflow": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Embed the ComfyUI workflow in the image so it can be reloaded later.",
                    },
                ),
                "include_civitai_manifest": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Embed structured Civitai-focused metadata, including resources, hashes, lookup status, and warnings.",
                    },
                ),
                "enable_civitai_lookup": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "Ask Civitai to identify models from hashes. Sends only hash values or model version IDs, never images, prompts, workflows, or local paths. Recommended: off for normal use, on for resolving unknown resources.",
                    },
                ),
                "lookup_prefer_sha256": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "When multiple hashes are available, try SHA256 first because it is the strongest match.",
                    },
                ),
                "lookup_timeout_seconds": (
                    "FLOAT",
                    {
                        "default": 4.0,
                        "min": 0.1,
                        "max": 30.0,
                        "step": 0.5,
                        "tooltip": "How long to wait for Civitai lookup before giving up and saving anyway. Metadata lookup never blocks the image from saving permanently.",
                    },
                ),
                "lookup_cache_results": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "Remember successful Civitai lookup results so future saves can resolve the same resource without asking Civitai again.",
                    },
                ),
                "use_persistent_hash_cache": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Remember model file hashes so large checkpoints, GGUFs, LoRAs, and VAEs do not need to be rehashed every save.",
                    },
                ),
                "hashing_mode": (
                    ["cached_or_fast", "cached_only", "full"],
                    {
                        "default": "cached_or_fast",
                        "tooltip": "Controls how much model hashing happens during save. cached_only is fastest, cached_or_fast is recommended, full is slowest but most complete.",
                    },
                ),
                "preferred_primary_model_air": (
                    "STRING",
                    {
                        "default": "",
                        "label": "Preferred AIR or URL",
                        "display_name": "Preferred AIR or URL",
                        "tooltip": "Optional. Paste a Civitai AIR, Civitai model URL, or model version ID to force the active primary model to use this Civitai listing.",
                        "placeholder": "urn:air:flux2:checkpoint:civitai:2432159@2734704",
                    },
                ),
                "advanced_manual_identities_enabled": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label": "Advanced JSON",
                        "display_name": "Advanced JSON",
                        "tooltip": "Shows the advanced JSON override box for pinning multiple resources. Most users should leave this off and use Preferred AIR or URL instead.",
                    },
                ),
                "manual_resource_identities_json": (
                    "STRING",
                    {
                        "default": "[]",
                        "multiline": True,
                        "rows": 4,
                        "label": "Advanced resource JSON",
                        "display_name": "Advanced resource JSON",
                        "tooltip": "Advanced optional JSON list of pinned AIR/modelVersionId mappings. Most users should use Preferred primary model AIR. Empty means automatic behavior. Invalid JSON never blocks saving.",
                        "placeholder": '[\n  {\n    "match": {"AutoV2": "09d005300d"},\n    "air": "urn:air:flux2:checkpoint:civitai:2432159@2734704",\n    "pinned": true\n  }\n]',
                    },
                ),
                "civitai_exif_minimal": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label": "Civitai EXIF Minimal",
                        "display_name": "Civitai EXIF Minimal",
                        "tooltip": "Writes only the Civitai-style EXIF metadata layer and omits the extra PNG text/iTXt metadata chunks. Useful for clean Civitai-style exports.",
                    },
                ),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    def save_images(
        self,
        images: Any,
        filename_prefix: str = "CivitaiMetadata",
        write_sidecar_json: bool = False,
        strict_mode: bool = False,
        include_workflow: bool = True,
        include_civitai_manifest: bool = True,
        enable_civitai_lookup: bool = False,
        lookup_prefer_sha256: bool = True,
        lookup_timeout_seconds: float = 4.0,
        lookup_cache_results: bool = False,
        use_persistent_hash_cache: bool = True,
        hashing_mode: str = "cached_or_fast",
        preferred_primary_model_air: str = "",
        advanced_manual_identities_enabled: bool | None = None,
        manual_resource_identities_json: str = "[]",
        civitai_exif_minimal: bool = False,
        prompt: Any | None = None,
        extra_pnginfo: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        output_dir = _get_comfy_output_directory()
        save_warnings: list[ValidationIssue] = []

        first_image = images[0]
        height = int(first_image.shape[0])
        width = int(first_image.shape[1])

        prompt_metadata = PromptMetadata()
        generation = GenerationSettings(width=width, height=height)
        resources = ()
        unresolved_resources = ()
        raw_resources_found = ()
        active_scan_resources = ()
        normalized_resources = ()
        image_hashes = HashMetadata()
        generator = GeneratorMetadata()
        identity_cache_metadata = IdentityCacheMetadata()
        lookup_debug_summary: tuple[dict[str, object], ...] = ()
        scan_warnings: tuple[ValidationIssue, ...] = ()
        hash_warnings: tuple[ValidationIssue, ...] = ()
        identity_warnings: tuple[ValidationIssue, ...] = ()
        identity_errors: tuple[ValidationIssue, ...] = ()
        preferred_identity_warnings: tuple[ValidationIssue, ...] = ()
        preferred_identity_errors: tuple[ValidationIssue, ...] = ()
        manual_identity_warnings: tuple[ValidationIssue, ...] = ()
        manual_identity_errors: tuple[ValidationIssue, ...] = ()
        lookup_warnings: tuple[ValidationIssue, ...] = ()
        lookup_errors: tuple[ValidationIssue, ...] = ()

        try:
            scan = scan_workflow_graph(prompt, extra_pnginfo or {})
            prompt_metadata = scan.prompt
            generation = scan.generation
            resources = scan.resources
            unresolved_resources = scan.unresolved_resources
            raw_resources_found = scan.raw_resources
            active_scan_resources = scan.resources
            scan_warnings = scan.warnings
            generator = scan.generator
        except Exception:
            save_warnings.append(
                _save_warning("metadata_scan_failed", "Workflow scanning failed; saving image with minimal metadata")
            )

        try:
            hash_result = attach_local_hashes(
                resources=resources,
                generation=generation,
                cache=_PERSISTENT_HASH_CACHE if use_persistent_hash_cache else _MEMORY_HASH_CACHE,
                hashing_mode=_safe_hashing_mode(hashing_mode),
            )
            resources = hash_result.resources
            unresolved_resources = hash_result.unresolved_resources
            image_hashes = hash_result.hashes
            generation = hash_result.generation
            hash_warnings = hash_result.warnings
            normalized_resources = resources
        except Exception:
            save_warnings.append(
                _save_warning(
                    "metadata_hashing_failed", "Resource hashing failed; saving image with unresolved resources"
                )
            )
            normalized_resources = resources

        try:
            preferred_identity_result = apply_preferred_primary_model_air(
                resources=resources,
                preferred_primary_model_air=preferred_primary_model_air,
            )
            resources = preferred_identity_result.resources
            unresolved_resources = preferred_identity_result.unresolved_resources
            preferred_identity_warnings = preferred_identity_result.warnings
            preferred_identity_errors = preferred_identity_result.errors
        except Exception:
            save_warnings.append(
                _save_warning(
                    "metadata_preferred_primary_air_failed",
                    "Preferred primary model AIR processing failed; saving image without preferred AIR identity resolution",
                )
            )

        manual_identities_enabled = _advanced_manual_identities_enabled(
            advanced_manual_identities_enabled,
            manual_resource_identities_json,
        )
        if manual_identities_enabled:
            try:
                manual_identity_result = apply_manual_resource_identities(
                    resources=resources,
                    manual_resource_identities_json=manual_resource_identities_json,
                )
                resources = manual_identity_result.resources
                unresolved_resources = manual_identity_result.unresolved_resources
                manual_identity_warnings = manual_identity_result.warnings
                manual_identity_errors = manual_identity_result.errors
            except Exception:
                save_warnings.append(
                    _save_warning(
                        "metadata_manual_identity_failed",
                        "Manual identity processing failed; saving image without node-pinned identity resolution",
                    )
                )

        try:
            identity_load = load_identity_cache(default_identity_cache_path())
            generated_identity_load = load_identity_cache(generated_identity_cache_path())
            identity_cache = combine_identity_caches(
                primary=identity_load.cache,
                secondary=generated_identity_load.cache,
                mapping_source="local_and_generated_identity_cache",
            )
            identity_result = apply_identity_cache(
                resources=resources,
                identity_cache=identity_cache,
                warnings=(*identity_load.warnings, *generated_identity_load.warnings),
                errors=(*identity_load.errors, *generated_identity_load.errors),
            )
            resources = identity_result.resources
            unresolved_resources = identity_result.unresolved_resources
            identity_cache_metadata = identity_result.identity_cache
            identity_warnings = identity_result.warnings
            identity_errors = identity_result.errors
        except Exception:
            save_warnings.append(
                _save_warning(
                    "metadata_identity_cache_failed",
                    "Identity cache processing failed; saving image without local Civitai identity resolution",
                )
            )

        try:
            lookup_result = resolve_resources_with_civitai_api(
                resources=resources,
                settings=CivitaiLookupSettings(
                    enabled=bool(enable_civitai_lookup),
                    prefer_sha256=bool(lookup_prefer_sha256),
                    timeout_seconds=float(lookup_timeout_seconds),
                    cache_results=bool(lookup_cache_results),
                ),
            )
            resources = lookup_result.resources
            unresolved_resources = lookup_result.unresolved_resources
            lookup_warnings = lookup_result.warnings
            lookup_errors = lookup_result.errors
            lookup_debug_summary = lookup_result.lookup_debug_summary
        except Exception:
            save_warnings.append(
                _save_warning(
                    "metadata_lookup_failed", "Civitai lookup failed; saving image without API identity resolution"
                )
            )

        generation = _apply_final_image_dimensions(generation, width, height)

        filename_warnings: tuple[ValidationIssue, ...] = ()
        try:
            expanded_prefix, filename_warnings = expand_filename_template(
                filename_prefix,
                generation=generation,
            )
            safe_prefix = normalize_filename_prefix(expanded_prefix)
            full_output_folder, base_filename, counter, _subfolder, _ = _get_save_image_path(
                safe_prefix,
                output_dir,
                width,
                height,
            )
        except Exception:
            save_warnings.append(
                _save_warning(
                    "filename_prefix_fallback", "Filename template or path was rejected; using a safe fallback filename"
                )
            )
            safe_prefix = "CivitaiMetadata"
            full_output_folder, base_filename, counter, _subfolder, _ = _fallback_save_image_path(
                output_dir, safe_prefix
            )

        try:
            parameters = build_a1111_parameters(
                prompt=prompt_metadata,
                generation=generation,
                resources=resources,
                hashes=image_hashes,
            )
            if parameters_text_needs_latin1_fallback(parameters):
                save_warnings.append(
                    _save_warning(
                        "parameters_text_latin1_fallback",
                        "A1111 parameters contained text outside PNG tEXt Latin-1; wrote a compatible parameters chunk and preserved full Unicode metadata in iTXt",
                        "parameters",
                    )
                )
        except Exception:
            save_warnings.append(
                _save_warning(
                    "a1111_parameters_failed", "A1111 parameters could not be built; saving image with blank parameters"
                )
            )
            parameters = ""

        try:
            validation = validate_metadata(
                filename_prefix=safe_prefix,
                prompt_metadata=prompt_metadata,
                generation=generation,
                resources=resources,
                unresolved_resources=unresolved_resources,
                prompt=prompt,
                extra_pnginfo=extra_pnginfo,
                include_workflow=include_workflow,
                include_civitai_manifest=include_civitai_manifest,
                additional_warnings=(
                    *scan_warnings,
                    *hash_warnings,
                    *preferred_identity_warnings,
                    *manual_identity_warnings,
                    *identity_warnings,
                    *lookup_warnings,
                    *filename_warnings,
                    *save_warnings,
                ),
                additional_errors=(
                    *preferred_identity_errors,
                    *manual_identity_errors,
                    *identity_errors,
                    *lookup_errors,
                ),
            )
        except Exception:
            save_warnings.append(
                _save_warning(
                    "metadata_validation_failed",
                    "Metadata validation failed; saving image with minimal validation status",
                )
            )
            validation = ValidationResult(warnings=tuple(save_warnings))

        if strict_mode and validation.has_errors:
            validation = validation.with_warning(
                _save_warning(
                    "strict_mode_metadata_errors_ignored",
                    "Strict mode found metadata errors, but image saving continues",
                )
            )

        try:
            prompt_json = sanitize_for_json(prompt)
        except Exception:
            save_warnings.append(
                _save_warning("prompt_metadata_sanitize_failed", "Prompt metadata could not be serialized safely")
            )
            prompt_json = None
        try:
            extra_json = sanitize_for_json(extra_pnginfo or {})
        except Exception:
            save_warnings.append(
                _save_warning("workflow_metadata_sanitize_failed", "Workflow metadata could not be serialized safely")
            )
            extra_json = {}

        exif_bytes = None
        try:
            exif_bytes = build_exif_bytes(
                prompt=prompt_metadata,
                generation=generation,
                resources=resources,
                output_format="png",
            )
        except Exception:
            warning = _save_warning(
                "exif_metadata_failed", "Civitai EXIF metadata could not be built; saving image without EXIF metadata"
            )
            save_warnings.append(warning)
            validation = validation.with_warning(warning)

        metadata_status = _metadata_status(save_warnings, validation, unresolved_resources)
        civitai_manifest = None
        if include_civitai_manifest:
            try:
                civitai_manifest = build_civitai_manifest(
                    prompt=prompt_metadata,
                    generation=generation,
                    resources=resources,
                    unresolved_resources=unresolved_resources,
                    hashes=image_hashes,
                    validation=validation,
                    include_workflow=include_workflow,
                    generator=generator,
                    identity_cache=identity_cache_metadata,
                    metadata_status=metadata_status,
                    save_warnings=tuple(save_warnings),
                    lookup_debug_summary=lookup_debug_summary,
                )
            except Exception:
                save_warnings.append(
                    _save_warning(
                        "civitai_manifest_failed",
                        "Civitai manifest could not be built; saving image without structured manifest",
                    )
                )
                metadata_status = "partial"

        pnginfo = None
        if not civitai_exif_minimal:
            try:
                pnginfo = build_pnginfo(
                    parameters=parameters,
                    prompt=prompt_json,
                    extra_pnginfo=extra_json,
                    include_workflow=include_workflow,
                    civitai_manifest=civitai_manifest,
                )
            except Exception:
                warning = _save_warning(
                    "png_metadata_failed",
                    "PNG metadata could not be built; saving pixels without custom PNG text metadata",
                )
                save_warnings.append(warning)
                validation = validation.with_warning(warning)
                pnginfo = None

        results: list[dict[str, str]] = []
        for image in images:
            image_file = f"{base_filename}_{counter:05}_.png"
            try:
                image_path = safe_output_path(output_dir, full_output_folder, image_file)
            except Exception:
                save_warnings.append(
                    _save_warning("output_path_fallback", "Output path was rejected; using the default output folder")
                )
                image_path = safe_output_path(output_dir, output_dir, f"CivitaiMetadata_{counter:05}_.png")
            image_path.parent.mkdir(parents=True, exist_ok=True)

            pil_image = _tensor_to_pil_image(image)
            try:
                save_kwargs: dict[str, Any] = {"compress_level": 4}
                if pnginfo is not None:
                    save_kwargs["pnginfo"] = pnginfo
                if exif_bytes is not None:
                    save_kwargs["exif"] = exif_bytes
                pil_image.save(image_path, **save_kwargs)
            except Exception:
                save_warnings.append(
                    _save_warning(
                        "image_save_metadata_retry", "Image save with metadata failed; retrying without custom metadata"
                    )
                )
                pil_image.save(image_path, compress_level=4)

            result = {
                "filename": image_path.name,
                "subfolder": _relative_subfolder(output_dir, image_path.parent),
                "type": self.type,
            }
            results.append(result)

            if write_sidecar_json:
                try:
                    try:
                        resource_lifecycle = build_resource_lifecycle(
                            raw_resources_found=raw_resources_found,
                            active_resources=active_scan_resources,
                            normalized_resources=normalized_resources,
                            final_resources=resources,
                            unresolved_resources=unresolved_resources,
                            final_a1111_parameters=parameters,
                            lookup_debug_summary=lookup_debug_summary,
                            warnings=validation.warnings,
                            metadata_status=metadata_status,
                        )
                    except Exception:
                        save_warnings.append(
                            _save_warning(
                                "resource_lifecycle_failed",
                                "Resource lifecycle diagnostics could not be built; writing sidecar with empty lifecycle",
                            )
                        )
                        resource_lifecycle = empty_resource_lifecycle(metadata_status="partial")
                    sidecar_payload = build_sidecar_payload(
                        image={
                            **result,
                            "fileName": image_path.name,
                            "format": "PNG",
                            "width": int(getattr(pil_image, "width", width)),
                            "height": int(getattr(pil_image, "height", height)),
                            "mode": str(getattr(pil_image, "mode", "") or ""),
                        },
                        options=MetadataOptions(
                            strict_mode=bool(strict_mode),
                            include_workflow=bool(include_workflow),
                            include_civitai_manifest=bool(include_civitai_manifest),
                            write_sidecar_json=bool(write_sidecar_json),
                            enable_civitai_lookup=bool(enable_civitai_lookup),
                            lookup_prefer_sha256=bool(lookup_prefer_sha256),
                            lookup_timeout_seconds=float(lookup_timeout_seconds),
                            lookup_cache_results=bool(lookup_cache_results),
                            use_persistent_hash_cache=bool(use_persistent_hash_cache),
                            hashing_mode=_safe_hashing_mode(hashing_mode),
                            civitai_exif_minimal=bool(civitai_exif_minimal),
                        ),
                        prompt=prompt_json,
                        extra_pnginfo=extra_json,
                        civitai_manifest=civitai_manifest,
                        validation=validation,
                        resource_lifecycle=resource_lifecycle,
                        a1111_parameters=parameters,
                        manual_identities_enabled=manual_identities_enabled,
                        manual_identities_entry_count=_manual_identity_entry_count(
                            manual_identities_enabled,
                            manual_resource_identities_json,
                        ),
                        exif_user_comment=exif_bytes is not None,
                    )
                    write_sidecar_json_file(image_path, sidecar_payload, output_dir)
                except Exception:
                    save_warnings.append(
                        _save_warning("sidecar_write_failed", "Sidecar JSON could not be written; image save completed")
                    )

            counter += 1

        return {"ui": {"images": results}, "result": (images,)}


def _get_comfy_output_directory() -> Path:
    if folder_paths is None:  # pragma: no cover - convenience outside ComfyUI
        return Path.cwd() / "output"
    return Path(folder_paths.get_output_directory())


def _get_save_image_path(
    filename_prefix: str,
    output_dir: Path,
    width: int,
    height: int,
) -> tuple[str, str, int, str, str]:
    if folder_paths is not None:
        return folder_paths.get_save_image_path(
            filename_prefix,
            str(output_dir),
            width,
            height,
        )

    subfolder = ""
    base_filename = filename_prefix.replace("/", "_")
    return str(output_dir), base_filename, 1, subfolder, filename_prefix


def _fallback_save_image_path(output_dir: Path, filename_prefix: str) -> tuple[str, str, int, str, str]:
    return str(output_dir), filename_prefix.replace("/", "_") or "CivitaiMetadata", 1, "", filename_prefix


def _relative_subfolder(output_dir: Path, image_folder: Path) -> str:
    base = output_dir.resolve(strict=False)
    folder = image_folder.resolve(strict=False)
    relative = folder.relative_to(base)
    if str(relative) == ".":
        return ""
    return relative.as_posix()


def _tensor_to_pil_image(image: Any) -> Any:
    from PIL import Image
    import numpy as np

    image_array = 255.0 * image.cpu().numpy()
    image_array = np.clip(image_array, 0, 255).astype(np.uint8)
    return Image.fromarray(image_array)


def _apply_final_image_dimensions(
    generation: Any,
    width: int,
    height: int,
) -> Any:
    if generation.width is not None and generation.height is not None:
        return generation
    return replace(
        generation,
        width=generation.width if generation.width is not None else int(width),
        height=generation.height if generation.height is not None else int(height),
    )


def _save_warning(code: str, message: str, field: str = "save") -> ValidationIssue:
    return ValidationIssue(code=code, message=message, field=field)


def _safe_hashing_mode(value: object) -> str:
    mode = str(value or "cached_or_fast").strip().lower()
    if mode in {"cached_only", "cached_or_fast", "full"}:
        return mode
    return "cached_or_fast"


def _advanced_manual_identities_enabled(value: object | None, manual_resource_identities_json: str | None) -> bool:
    if value is None:
        text = str(manual_resource_identities_json or "").strip()
        return bool(text and text != "[]")
    return bool(value)


def _manual_identity_entry_count(enabled: bool, manual_resource_identities_json: str | None) -> int:
    if not enabled:
        return 0
    try:
        parsed = json.loads(manual_resource_identities_json or "[]")
    except Exception:
        return 0
    if isinstance(parsed, list):
        return len(parsed)
    return 0


def _metadata_status(
    save_warnings: list[ValidationIssue],
    validation: ValidationResult,
    unresolved_resources: tuple[Any, ...] = (),
) -> str:
    codes = {warning.code for warning in save_warnings}
    if {"png_metadata_failed", "a1111_parameters_failed", "civitai_manifest_failed"}.issubset(codes):
        return "failed"
    if "png_metadata_failed" in codes:
        return "minimal"
    if unresolved_resources:
        return "partial"
    if any(code.endswith("_failed") for code in codes):
        return "partial"
    if validation.has_errors:
        return "partial"
    partial_warning_codes = {
        "resource_version_without_air",
        "preferred_identity_incomplete_air",
        "preferred_primary_model_identity_incomplete",
    }
    if any(warning.code in partial_warning_codes for warning in validation.warnings):
        return "partial"
    return "complete"


__all__ = ["SaveImageWithCivitaiMetadata"]
