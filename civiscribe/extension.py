"""Native ComfyUI V3 extension registration."""

from __future__ import annotations

from aiohttp import web
from comfy_api.latest import ComfyExtension, io
from server import PromptServer

from .adapters.http_api import register_routes
from .node import NODE_ID, registered_nodes


class CiviScribeExtension(ComfyExtension):
    """Expose the single native node and routes on ComfyUI's existing server."""

    async def on_load(self) -> None:
        register_routes(PromptServer.instance.routes, web.Response, node_id=NODE_ID)

    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return list(registered_nodes())


__all__ = ["CiviScribeExtension"]
