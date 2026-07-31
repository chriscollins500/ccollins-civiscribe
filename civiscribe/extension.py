"""Native ComfyUI V3 extension registration."""

from __future__ import annotations

from comfy_api.latest import ComfyExtension, io

from .node import registered_nodes


class CiviScribeExtension(ComfyExtension):
    """Expose only CiviScribe nodes that have complete executable contracts."""

    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return list(registered_nodes())


__all__ = ["CiviScribeExtension"]
