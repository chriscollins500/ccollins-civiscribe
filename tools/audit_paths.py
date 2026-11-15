"""Resolve development-tool paths beneath the operator-selected scope."""

from __future__ import annotations

from pathlib import Path


def scoped_path(root: Path, candidate: Path) -> Path:
    """Reject traversal or link resolution outside an explicitly selected root."""
    try:
        selected_root = root.resolve()
        resolved = candidate.resolve()
    except RuntimeError as error:
        raise ValueError("audit_path_resolution_failed") from error
    if not resolved.is_relative_to(selected_root):
        raise ValueError("audit_path_outside_selected_root")
    return resolved
