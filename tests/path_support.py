"""Real directory links without requiring Windows symbolic-link privileges."""

from __future__ import annotations

import sys
from pathlib import Path


def directory_link(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        from _winapi import CreateJunction  # noqa: PLC0415 - Windows-only API

        CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
