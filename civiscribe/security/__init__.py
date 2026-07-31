"""Security boundaries shared by metadata adapters."""

from .redaction import JsonSanitizationResult, sanitize_metadata_json

__all__ = ["JsonSanitizationResult", "sanitize_metadata_json"]
