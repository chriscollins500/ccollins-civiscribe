"""Packaged schema locations for developer and release validation."""

from __future__ import annotations

from pathlib import Path


def sidecar_schema_path() -> Path:
    """Return the packaged V2 sidecar schema path."""

    return Path(__file__).with_name("sidecar-v2.schema.json")


__all__ = ["sidecar_schema_path"]
