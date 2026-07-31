"""Typed boundaries shared by hashing, caches, and identity lookup."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..domain import HashStatus, LookupStatus, ResourceRecord


class HashingMode(StrEnum):
    """Permitted model-file reads for one resolution operation."""

    CACHED_ONLY = "cached_only"
    CACHED_OR_FAST = "cached_or_fast"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class LocatedResourceFile:
    """An approved ComfyUI model file; ``path`` never enters metadata."""

    path: Path
    approved_root: Path
    category: str
    selected_value: str


class ResourceFileLocator(Protocol):
    """Resolve only resource selections belonging to approved model roots."""

    def locate(self, resource: ResourceRecord) -> LocatedResourceFile | None:
        """Return an approved local file or ``None`` without raising."""


__all__ = [
    "HashStatus",
    "HashingMode",
    "LocatedResourceFile",
    "LookupStatus",
    "ResourceFileLocator",
]
