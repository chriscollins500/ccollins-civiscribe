"""Native ComfyUI V3 entry point for CCollins' CiviScribe."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .civiscribe.extension import CiviScribeExtension


WEB_DIRECTORY = "./web/runtime"


async def comfy_entrypoint() -> CiviScribeExtension:
    """Create the V3 extension without importing ComfyUI during package inspection."""

    from .civiscribe.extension import CiviScribeExtension

    return CiviScribeExtension()


__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
