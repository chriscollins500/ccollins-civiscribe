"""Stable, privacy-safe product errors."""

from __future__ import annotations


class CiviScribeError(Exception):
    """Base error whose message is a stable code, never private data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class InvalidImageError(CiviScribeError):
    """The supplied image cannot be represented by the supported writer."""


class UnsafePathError(CiviScribeError):
    """An untrusted filename template violates the output-path policy."""


class WriteError(CiviScribeError):
    """No safe, verified image could be committed."""


class SerializationError(CiviScribeError):
    """A metadata value cannot be serialized within the strict product contract."""
