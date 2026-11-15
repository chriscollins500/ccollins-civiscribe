"""Expose exact save facts through native history and Comfy MCP text outputs."""

from __future__ import annotations

from comfy_api.latest import ui

from ..api import save_report
from ..orchestration import SaveOutcome
from ..serialization import dumps_json


class ApiSavedImages(ui.SavedImages):
    """Native previews with an additive, versioned JSON text projection."""

    def __init__(self, results: list[ui.SavedResult], report: str) -> None:
        super().__init__(results)
        self.report = report

    def as_dict(self) -> dict[str, object]:
        return {**super().as_dict(), "text": [self.report]}


def saved_images_with_report(results: list[ui.SavedResult], outcome: SaveOutcome) -> ui.SavedImages:
    """Keep a committed image's native preview even if report projection fails."""

    try:
        return ApiSavedImages(results, dumps_json(save_report(outcome)))
    except Exception:
        return ui.SavedImages(results)
