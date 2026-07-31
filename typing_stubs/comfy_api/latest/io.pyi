from enum import Enum
from typing import Any

class ComfyNode: ...

class FolderType(Enum):
    output = ...

class _Input:
    def __init__(
        self,
        id: str,
        display_name: str | None = ...,
        optional: bool = ...,
        tooltip: str | None = ...,
        **kwargs: Any,
    ) -> None: ...

class _Output:
    def __init__(
        self,
        id: str = ...,
        display_name: str | None = ...,
        tooltip: str | None = ...,
        **kwargs: Any,
    ) -> None: ...

class Image:
    Type: Any
    class Input(_Input): ...
    class Output(_Output): ...

class String:
    class Input(_Input):
        def __init__(
            self,
            id: str,
            display_name: str | None = ...,
            optional: bool = ...,
            tooltip: str | None = ...,
            *,
            default: str | None = ...,
            **kwargs: Any,
        ) -> None: ...

class Combo:
    class Input(_Input):
        def __init__(
            self,
            id: str,
            display_name: str | None = ...,
            optional: bool = ...,
            tooltip: str | None = ...,
            *,
            options: list[Any],
            default: Any = ...,
            **kwargs: Any,
        ) -> None: ...

class Int:
    class Input(_Input):
        def __init__(
            self,
            id: str,
            display_name: str | None = ...,
            optional: bool = ...,
            tooltip: str | None = ...,
            *,
            default: int | None = ...,
            min: int | None = ...,
            max: int | None = ...,
            step: int | None = ...,
            **kwargs: Any,
        ) -> None: ...

class Float:
    class Input(_Input):
        def __init__(
            self,
            id: str,
            display_name: str | None = ...,
            optional: bool = ...,
            tooltip: str | None = ...,
            *,
            default: float | None = ...,
            min: float | None = ...,
            max: float | None = ...,
            step: float | None = ...,
            **kwargs: Any,
        ) -> None: ...

class Boolean:
    class Input(_Input):
        def __init__(
            self,
            id: str,
            display_name: str | None = ...,
            optional: bool = ...,
            tooltip: str | None = ...,
            *,
            default: bool | None = ...,
            **kwargs: Any,
        ) -> None: ...

class Schema:
    def __init__(
        self,
        *,
        node_id: str,
        display_name: str | None = ...,
        category: str = ...,
        inputs: list[Any] = ...,
        outputs: list[Any] = ...,
        hidden: list[Any] = ...,
        description: str = ...,
        search_aliases: list[str] = ...,
        is_output_node: bool = ...,
        **kwargs: Any,
    ) -> None: ...

class NodeOutput:
    def __init__(self, *outputs: Any, ui: Any = ...) -> None: ...
