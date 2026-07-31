from typing import Any

from .io import FolderType

class SavedResult(dict[str, Any]):
    def __init__(self, filename: str, subfolder: str, type: FolderType) -> None: ...

class SavedImages:
    def __init__(self, results: list[SavedResult], is_animated: bool = ...) -> None: ...
