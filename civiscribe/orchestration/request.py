"""Input to the pixels-first save transaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..domain import ImageFormat, ImageFrame
from ..identity import IdentityResolutionOptions, IdentityServices
from ..writers import WriterOptions


@dataclass(frozen=True, slots=True)
class MetadataRequest:
    """Untrusted ComfyUI metadata inputs and explicit embedding policy."""

    prompt: object | None = None
    workflow: object | None = None
    save_node_id: str | None = None
    positive_prompt_override: str | None = None
    negative_prompt_override: str | None = None
    include_workflow: bool = True
    include_civitai_manifest: bool = True
    comfyui_version: str | None = None
    identity_options: IdentityResolutionOptions = field(default_factory=IdentityResolutionOptions)
    identity_services: IdentityServices | None = None


@dataclass(frozen=True, slots=True)
class SaveRequest:
    images: tuple[ImageFrame, ...]
    output_root: Path
    filename_prefix: str
    output_format: ImageFormat = ImageFormat.PNG
    writer_options: WriterOptions = field(default_factory=WriterOptions)
    write_sidecar_json: bool = False
    timestamp: datetime | None = None
    metadata: MetadataRequest | None = None
