"""Resolve development-tool paths beneath the operator-selected scope."""

from __future__ import annotations

import os
from pathlib import Path


def _contained_path(root: str, candidate: str) -> Path:
    """Check normalized path components before performing filesystem probes.

    commonpath preserves the candidate's spelling on Windows, where path
    comparisons are case insensitive. The separator-terminated prefix check
    then also expresses that boundary to static path-injection analysis.
    """
    try:
        common = os.path.commonpath((candidate, root))
    except ValueError as error:
        raise ValueError("audit_path_outside_selected_root") from error
    if Path(common) != Path(root):
        raise ValueError("audit_path_outside_selected_root")
    if candidate == common:
        return Path(common)
    prefix = common if common.endswith(os.sep) else common + os.sep
    if not candidate.startswith(prefix):
        raise ValueError("audit_path_outside_selected_root")
    return Path(candidate)


def scoped_path(root: Path, candidate: Path, *, resolve_links: bool = True) -> Path:
    """Reject traversal or link resolution outside an explicitly selected root.

    Link inspection uses lexical containment so the link itself remains
    visible. Other callers retain Path.resolve's loop/error behavior and a
    second containment check after resolution.
    """
    if not resolve_links:
        # Link inspection must preserve the link, including broken links.
        lexical_root = os.path.abspath(root)  # noqa: PTH100 - must not resolve links
        lexical_candidate = os.path.abspath(candidate)  # noqa: PTH100 - must not resolve links
        return _contained_path(lexical_root, lexical_candidate)
    try:
        normalized_root = os.path.realpath(root)
        selected_root = _contained_path(normalized_root, normalized_root).resolve()
        resolved = _contained_path(normalized_root, os.path.realpath(candidate)).resolve()
    except RuntimeError as error:
        raise ValueError("audit_path_resolution_failed") from error
    if not resolved.is_relative_to(selected_root):
        raise ValueError("audit_path_outside_selected_root")
    return resolved
