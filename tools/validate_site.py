"""Audit generated Pages files, links, anchors, local resources, and privacy boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from tools.build_site import BASE, ROOT, _safe_output, public_paths


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.links: list[str] = []
        self.resources: list[str] = []
        self.h1_count = 0
        self.csp = False
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if identifier := values.get("id"):
            self.ids.append(identifier)
        if href := values.get("href"):
            self.links.append(href)
            if tag == "link" and values.get("rel") in {"stylesheet", "icon"}:
                self.resources.append(href)
        if tag in {"script", "img", "iframe", "video", "audio"} and (src := values.get("src")):
            self.resources.append(src)
        if any(key.lower().startswith("on") for key, _ in attrs):
            self.errors.append("inline event handler")
        if tag == "h1":
            self.h1_count += 1
        if tag == "meta" and (values.get("http-equiv") or "").lower() == "content-security-policy":
            self.csp = "script-src 'self'" in (values.get("content") or "")


def _page_errors(label: str, text: str, page: _Page) -> list[str]:
    errors = [f"{label}: {issue}" for issue in page.errors]
    if page.h1_count != 1:
        errors.append(f"{label}: expected one main heading")
    if len(page.ids) != len(set(page.ids)):
        errors.append(f"{label}: duplicate IDs")
    if not page.csp:
        errors.append(f"{label}: missing restrictive script policy")
    if re.search(r"\{\{[A-Z_]+\}\}", text):
        errors.append(f"{label}: unresolved template token")
    if re.search(r"[A-Z]:\\Users\\Chris\\|D:\\Codex\\|gh[pousr]_[A-Za-z0-9]{25}", text):
        errors.append(f"{label}: private path or credential pattern")
    return errors


def _link_errors(output: Path, path: Path, page: _Page, pages: dict[Path, _Page]) -> list[str]:
    errors: list[str] = []
    label = path.relative_to(output).as_posix()
    for resource in page.resources:
        parsed = urlsplit(resource)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith(BASE + "/"):
            errors.append(f"{label}: non-local resource")
    for href in page.links + page.resources:
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            continue
        if not parsed.path:
            target = path
        elif parsed.path.startswith(BASE + "/"):
            target = output / unquote(parsed.path.removeprefix(BASE + "/"))
            if parsed.path.endswith("/"):
                target /= "index.html"
        else:
            errors.append(f"{label}: link missing the project base path")
            continue
        target = target.resolve()
        if not target.is_relative_to(output) or not target.is_file():
            errors.append(f"{label}: missing local link target {parsed.path}")
        elif (
            parsed.fragment
            and target in pages
            and unquote(parsed.fragment) not in pages[target].ids
        ):
            errors.append(f"{label}: missing anchor {parsed.fragment}")
    return errors


def _manifest_errors(output: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads((output / "site-manifest.json").read_text(encoding="utf-8"))
    actual = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    if actual != public_paths():
        errors.append("manifest: output does not match the public file allowlist")
    if set(manifest["files"]) != public_paths() - {"site-manifest.json"}:
        errors.append("manifest: incomplete or unexpected file inventory")
    for name, digest in manifest["files"].items():
        target = output / name
        if not target.resolve().is_relative_to(output) or not target.is_file():
            errors.append("manifest: invalid file path")
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            errors.append(f"manifest: changed file {name}")
    return errors


def validate_site(output: Path) -> tuple[str, ...]:
    """Return deterministic issues for the exact built website, without network access."""
    output = _safe_output(output)
    pages: dict[Path, _Page] = {}
    errors: list[str] = []
    if any(path.is_symlink() or path.is_junction() for path in output.rglob("*")):
        return ("output contains a link or junction",)
    for path in sorted(output.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        page = _Page()
        page.feed(text)
        pages[path] = page
        errors.extend(_page_errors(path.relative_to(output).as_posix(), text, page))
    if not pages:
        errors.append("no HTML pages")
    for path, page in pages.items():
        errors.extend(_link_errors(output, path, page, pages))
    errors.extend(_manifest_errors(output))
    return tuple(errors)


def main() -> None:
    """Audit a previously built site and exit unsuccessfully on any issue."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".tmp/site-preview/ccollins-civiscribe"
    )
    arguments = parser.parse_args()
    issues = validate_site(arguments.output)
    print(json.dumps({"valid": not issues, "errors": issues}))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
