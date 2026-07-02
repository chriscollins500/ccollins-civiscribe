"""ComfyUI node mappings for the save node package."""

from .nodes import SaveImageWithCivitaiMetadata
from .version import __version__

NODE_CLASS_MAPPINGS = {
    "SaveImageWithCivitaiMetadata": SaveImageWithCivitaiMetadata,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveImageWithCivitaiMetadata": "Save Image with Civitai Metadata",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "__version__"]
