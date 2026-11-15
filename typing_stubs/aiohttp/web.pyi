from collections.abc import Mapping

class Response:
    def __init__(
        self, *, text: str, status: int, content_type: str, headers: Mapping[str, str]
    ) -> None: ...
