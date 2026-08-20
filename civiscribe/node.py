"""Native V3 boundary for the CiviScribe save transaction."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import folder_paths
from comfy_api.latest import io, ui

from .adapters import identity_services_from_comfy, image_frames_from_comfy
from .domain import ImageFormat
from .identity import HashingMode, IdentityResolutionOptions
from .orchestration import MetadataRequest, SaveRequest, save_image_batch
from .writers import JpegOptions, WebpOptions, WriterOptions, parse_rgb_color

NODE_ID = "CCollins_CiviScribe_SaveImage"
NODE_DISPLAY_NAME = "CiviScribe - Save Image for Civitai"
NODE_CATEGORY = "CCollins/CiviScribe"
DEFAULT_LOOKUP_TIMEOUT_SECONDS = 4.0
MAX_LOOKUP_TIMEOUT_SECONDS = 30.0
MIN_LOOKUP_TIMEOUT_SECONDS = 1.0


class CiviScribeSaveImage(io.ComfyNode):
    """Save a current ComfyUI IMAGE batch through the V2 transaction."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id=NODE_ID,
            display_name=NODE_DISPLAY_NAME,
            category=NODE_CATEGORY,
            description=(
                "Saves PNG, JPEG, or WebP images to ComfyUI's output directory. "
                "Writes Civitai-compatible metadata while preserving pixels-first saving."
            ),
            search_aliases=["save image", "Civitai", "export image"],
            inputs=[
                io.Image.Input(
                    "images",
                    display_name="Images",
                    tooltip="Images to save.",
                ),
                io.String.Input(
                    "positive_prompt_override",
                    display_name="Final positive prompt override",
                    optional=True,
                    force_input=True,
                    tooltip=(
                        "Connect the final positive prompt string actually sent to the active "
                        "text encoder when an LLM, wildcard, switch, or custom node creates it "
                        "at runtime. This changes metadata only, not generation."
                    ),
                ),
                io.String.Input(
                    "negative_prompt_override",
                    display_name="Final negative prompt override",
                    optional=True,
                    force_input=True,
                    tooltip=(
                        "Connect the final negative prompt string actually sent to the active "
                        "text encoder when a runtime node builds it dynamically. This changes "
                        "metadata only, not generation."
                    ),
                ),
                io.String.Input(
                    "filename_prefix",
                    display_name="Filename / subfolder pattern",
                    default="ComfyUI",
                    tooltip=(
                        "Filename or safe subfolder pattern. Supports ComfyUI "
                        "%date:FORMAT% and %Node name.widget_name% replacements; "
                        "%year%, %month%, %day%, %hour%, %minute%, %second%, "
                        "%width%, %height%, and %batch_num%; plus CiviScribe "
                        "%model%, %seed%, and %sampler% aliases."
                    ),
                ),
                io.Combo.Input(
                    "output_format",
                    display_name="Output format",
                    options=[item.value for item in ImageFormat],
                    default=ImageFormat.PNG.value,
                    tooltip="Image format. PNG and WebP are lossless by default; JPEG is lossy.",
                ),
                io.Int.Input(
                    "jpeg_quality",
                    display_name="JPEG quality",
                    default=100,
                    min=1,
                    max=100,
                    step=1,
                    tooltip="JPEG fidelity. 100 is the maximum-fidelity default.",
                ),
                io.String.Input(
                    "jpeg_alpha_background",
                    display_name="JPEG alpha background",
                    default="#FFFFFF",
                    tooltip="RGB background used when JPEG must flatten transparent pixels.",
                ),
                io.Boolean.Input(
                    "webp_lossless",
                    display_name="Lossless WebP",
                    default=True,
                    tooltip="Use decoded-pixel-preserving WebP encoding.",
                ),
                io.Int.Input(
                    "webp_quality",
                    display_name="WebP effort / quality",
                    default=100,
                    min=0,
                    max=100,
                    step=1,
                    tooltip="WebP compression effort or lossy quality.",
                ),
                io.Boolean.Input(
                    "write_sidecar_json",
                    display_name="Write sidecar JSON",
                    default=False,
                    tooltip="Also write deterministic metadata JSON beside each saved image.",
                ),
                io.Boolean.Input(
                    "include_workflow",
                    display_name="Embed ComfyUI workflow",
                    default=True,
                    tooltip=(
                        "Embed the sanitized ComfyUI API prompt graph and UI workflow graph. "
                        "Turn this off to omit both graph payloads from the image and sidecar."
                    ),
                ),
                io.Boolean.Input(
                    "include_civitai_manifest",
                    display_name="Embed Civitai manifest",
                    default=True,
                    tooltip=(
                        "Include the structured Civitai manifest in rich metadata and sidecars."
                    ),
                ),
                io.Boolean.Input(
                    "enable_civitai_lookup",
                    display_name="Enable Civitai lookup",
                    default=False,
                    tooltip=(
                        "Ask Civitai to identify active resources from hashes. Only hashes or "
                        "a model-version ID are sent; images, prompts, workflows, and paths "
                        "are not."
                    ),
                ),
                io.String.Input(
                    "preferred_primary_model_air",
                    display_name="Preferred primary AIR or Civitai URL",
                    default="",
                    placeholder="urn:air:... or https://civitai.com/models/...",
                    tooltip=(
                        "Optional AIR, Civitai model URL, or model-version ID that pins the "
                        "active primary model identity."
                    ),
                ),
                io.Combo.Input(
                    "hashing_mode",
                    display_name="Hashing mode",
                    options=[item.value for item in HashingMode],
                    default=HashingMode.CACHED_OR_FAST.value,
                    tooltip=(
                        "cached_only reads no model bytes; cached_or_fast uses caches and fast "
                        "hashes; full may read whole model files."
                    ),
                ),
                io.Float.Input(
                    "lookup_timeout_seconds",
                    display_name="Lookup timeout (seconds)",
                    default=DEFAULT_LOOKUP_TIMEOUT_SECONDS,
                    min=MIN_LOOKUP_TIMEOUT_SECONDS,
                    max=MAX_LOOKUP_TIMEOUT_SECONDS,
                    step=0.5,
                    advanced=True,
                    tooltip="Maximum Civitai lookup wait. Saving continues after a timeout.",
                ),
                io.Boolean.Input(
                    "lookup_cache_results",
                    display_name="Cache successful lookup results",
                    default=True,
                    advanced=True,
                    tooltip=(
                        "Store successful identities locally so later saves can resolve them "
                        "without another request."
                    ),
                ),
                io.Boolean.Input(
                    "advanced_manual_identities_enabled",
                    display_name="Enable manual resource identities",
                    default=False,
                    advanced=True,
                    tooltip=(
                        "Enable the advanced JSON mapping for pinning identities of multiple "
                        "active resources."
                    ),
                ),
                io.String.Input(
                    "manual_resource_identities_json",
                    display_name="Manual resource identities JSON",
                    default="[]",
                    multiline=True,
                    advanced=True,
                    tooltip=(
                        "Advanced JSON list of explicit resource identity mappings. Invalid "
                        "data is reported safely and never blocks image saving."
                    ),
                ),
            ],
            outputs=[
                io.Image.Output(
                    "images",
                    display_name="Images",
                    tooltip="Original image tensor passed through unchanged.",
                ),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(  # noqa: PLR0913 - ComfyUI binds one argument per declared widget.
        cls,
        images: io.Image.Type,
        positive_prompt_override: str | None = None,
        negative_prompt_override: str | None = None,
        filename_prefix: str = "ComfyUI",
        output_format: str = "png",
        jpeg_quality: int = 100,
        jpeg_alpha_background: str = "#FFFFFF",
        webp_lossless: bool = True,
        webp_quality: int = 100,
        write_sidecar_json: bool = False,
        include_workflow: bool = True,
        include_civitai_manifest: bool = True,
        enable_civitai_lookup: bool = False,
        preferred_primary_model_air: str = "",
        hashing_mode: str = HashingMode.CACHED_OR_FAST.value,
        lookup_timeout_seconds: float = DEFAULT_LOOKUP_TIMEOUT_SECONDS,
        lookup_cache_results: bool = True,
        advanced_manual_identities_enabled: bool = False,
        manual_resource_identities_json: str = "[]",
    ) -> io.NodeOutput:
        hidden = getattr(cls, "hidden", None)
        prompt = getattr(hidden, "prompt", None)
        extra_pnginfo = getattr(hidden, "extra_pnginfo", None)
        workflow = extra_pnginfo.get("workflow") if isinstance(extra_pnginfo, Mapping) else None
        unique_id = getattr(hidden, "unique_id", None)
        output_root = Path(folder_paths.get_output_directory())
        try:
            selected_format = ImageFormat(str(output_format).casefold())
        except ValueError:
            selected_format = ImageFormat.PNG
        normalized_jpeg_quality = max(1, min(100, int(jpeg_quality)))
        normalized_webp_quality = max(0, min(100, int(webp_quality)))
        normalized_lookup_timeout = max(
            MIN_LOOKUP_TIMEOUT_SECONDS,
            min(MAX_LOOKUP_TIMEOUT_SECONDS, float(lookup_timeout_seconds)),
        )
        try:
            selected_hashing_mode = HashingMode(str(hashing_mode))
        except ValueError:
            selected_hashing_mode = HashingMode.CACHED_OR_FAST
        preferred_primary = preferred_primary_model_air or None
        manual_json = (
            manual_resource_identities_json if advanced_manual_identities_enabled else None
        )
        request = SaveRequest(
            images=image_frames_from_comfy(images),
            output_root=output_root,
            filename_prefix=filename_prefix,
            output_format=selected_format,
            writer_options=WriterOptions(
                jpeg=JpegOptions(
                    quality=normalized_jpeg_quality,
                    alpha_background=parse_rgb_color(jpeg_alpha_background),
                ),
                webp=WebpOptions(
                    lossless=bool(webp_lossless),
                    quality=normalized_webp_quality,
                ),
            ),
            write_sidecar_json=bool(write_sidecar_json),
            metadata=MetadataRequest(
                prompt=prompt,
                workflow=workflow,
                save_node_id=str(unique_id) if unique_id is not None else None,
                positive_prompt_override=positive_prompt_override,
                negative_prompt_override=negative_prompt_override,
                include_workflow=bool(include_workflow),
                include_civitai_manifest=bool(include_civitai_manifest),
                identity_options=IdentityResolutionOptions(
                    hashing_mode=selected_hashing_mode,
                    preferred_primary=preferred_primary,
                    manual_json=manual_json,
                    cache_api_results=bool(lookup_cache_results),
                ),
                identity_services=identity_services_from_comfy(
                    output_root=output_root,
                    enable_lookup=bool(enable_civitai_lookup),
                    lookup_timeout_seconds=normalized_lookup_timeout,
                ),
            ),
        )
        outcome = save_image_batch(request)
        results = [
            ui.SavedResult(
                image.filename,
                image.subfolder,
                io.FolderType.output,
            )
            for image in outcome.saved_images
        ]
        return io.NodeOutput(images, ui=ui.SavedImages(results))


def registered_nodes() -> tuple[type[io.ComfyNode], ...]:
    """Return the complete public V3 node set."""

    return (CiviScribeSaveImage,)


__all__ = [
    "DEFAULT_LOOKUP_TIMEOUT_SECONDS",
    "MAX_LOOKUP_TIMEOUT_SECONDS",
    "MIN_LOOKUP_TIMEOUT_SECONDS",
    "NODE_CATEGORY",
    "NODE_DISPLAY_NAME",
    "NODE_ID",
    "CiviScribeSaveImage",
    "registered_nodes",
]
