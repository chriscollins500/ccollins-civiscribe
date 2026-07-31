"""Atomic UTF-8 JSON sidecar publication."""

from __future__ import annotations

from pathlib import Path

from ..domain import WriteError
from .atomic import create_temporary_path, flush_file, publish_companion


def write_sidecar_json(destination: Path, json_text: str) -> Path:
    """Write strict JSON bytes beside a committed image without overwriting."""

    if destination.suffix.casefold() != ".json":
        raise WriteError("sidecar_extension_invalid")
    temporary = create_temporary_path(destination.parent, ".json")
    try:
        temporary.write_bytes(json_text.encode("utf-8"))
        flush_file(temporary)
        return publish_companion(temporary, destination)
    except WriteError:
        raise
    except (OSError, UnicodeError) as exc:
        raise WriteError("sidecar_write_failed") from exc
    finally:
        temporary.unlink(missing_ok=True)
