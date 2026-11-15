from typing import ClassVar

from civiscribe.adapters.http_api import Routes

class PromptServer:
    instance: ClassVar[PromptServer]
    routes: Routes
