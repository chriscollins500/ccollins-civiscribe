"""Compare or publish the reviewed Markdown to an existing isolated wiki checkout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.audit_paths import scoped_path

ROOT = Path(__file__).resolve().parents[1]
MAX_PAGES = 128
MAX_PAGE_BYTES = 1024 * 1024


def _checkout(directory: Path) -> Path:
    directory = scoped_path(ROOT / ".tmp", directory, resolve_links=False)
    for path in (directory, *directory.parents):
        if path == ROOT:
            break
        if path.is_symlink() or path.is_junction():
            raise ValueError("wiki_checkout_contains_link")
    directory = scoped_path(ROOT / ".tmp", directory)
    git = directory / ".git"
    if not git.is_dir() or git.is_symlink() or git.is_junction():
        raise ValueError("wiki_checkout_required")
    return directory


def _text(path: Path) -> str:
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ValueError("wiki_page_must_be_an_ordinary_file")
    if path.stat().st_size > MAX_PAGE_BYTES:
        raise ValueError("wiki_page_too_large")
    return path.read_text(encoding="utf-8")


def sync_wiki(directory: Path, *, write: bool = False) -> tuple[str, ...]:
    """Keep known pages in sync; never delete or silently adopt unknown wiki pages."""
    directory = _checkout(directory)
    sources = sorted((ROOT / "docs/wiki").glob("*.md"))
    if not sources or len(sources) > MAX_PAGES:
        raise ValueError("wiki_source_inventory_invalid")
    desired = {path.name: _text(path) for path in sources}
    published = {path.name for path in directory.glob("*.md")}
    if published - desired.keys():
        return ("wiki_has_unmanaged_pages_promote_them_to_reviewed_source_first",)
    issues = []
    for name, text in desired.items():
        target = scoped_path(directory, directory / name, resolve_links=False)
        if target.is_symlink() or target.is_junction():
            raise ValueError("wiki_page_must_be_an_ordinary_file")
        current = _text(target) if target.exists() else None
        if current != text:
            if write:
                target.write_bytes(text.encode("utf-8"))
            else:
                issues.append(f"wiki_page_differs:{name}")
    return tuple(issues)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    issues = sync_wiki(arguments.wiki_root, write=arguments.write)
    print(json.dumps({"valid": not issues, "issues": issues}))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
