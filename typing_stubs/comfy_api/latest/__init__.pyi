from . import io as io
from . import ui as ui

class ComfyExtension:
    async def get_node_list(self) -> list[type[io.ComfyNode]]: ...
