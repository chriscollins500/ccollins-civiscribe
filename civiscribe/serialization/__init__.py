"""Strict deterministic serialization boundaries."""

from .json import DEFAULT_MAX_JSON_CHARS, dumps_json

__all__ = ["DEFAULT_MAX_JSON_CHARS", "dumps_json"]
