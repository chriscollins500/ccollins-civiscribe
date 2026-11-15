"""Check repository documentation and wiki references without network access."""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_URL = "https://github.com/chriscollins500/ccollins-civiscribe"
DOCUMENTS = (
    "README.md",
    "ROADMAP.md",
    "SUPPORT.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    ".github/pull_request_template.md",
    "docs/README.md",
    "docs/repository_maintenance.md",
    "docs/api_and_mcp.md",
)
_LINK = re.compile(r"!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)\s*\)")
_JSON_BLOCK = re.compile(r"^```json\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


def _anchors(text: str) -> set[str]:
    counts: Counter[str] = Counter()
    anchors = set()
    for heading in _HEADING.findall(text):
        slug = re.sub(r"[^\w\s-]", "", heading.lower()).strip()
        slug = re.sub(r"\s", "-", slug)
        index = counts[slug]
        counts[slug] += 1
        anchors.add(f"{slug}-{index}" if index else slug)
    return anchors


def _target(root: Path, document: Path, link: str) -> tuple[Path, str] | None:
    parsed = urlsplit(link.strip("<>"))
    url = parsed._replace(fragment="", query="").geturl()
    wiki_url = f"{REPOSITORY_URL}/wiki"
    if url == wiki_url or url.startswith(f"{wiki_url}/"):
        page = unquote(url.removeprefix(wiki_url).strip("/")) or "Home"
        return root / "docs" / "wiki" / f"{page}.md", unquote(parsed.fragment)
    for prefix in (f"{REPOSITORY_URL}/blob/main/", f"{REPOSITORY_URL}/tree/main/"):
        if url.startswith(prefix):
            return root / unquote(url.removeprefix(prefix)), unquote(parsed.fragment)
    if parsed.scheme or parsed.netloc:
        return None
    path = document.parent / unquote(parsed.path) if parsed.path else document
    return path, unquote(parsed.fragment)


def _link_issues(root: Path, document: Path, text: str) -> list[str]:
    issues = []
    label = document.relative_to(root).as_posix()
    for link in _LINK.findall(text):
        target = _target(root, document, link)
        if target is None:
            continue
        path, fragment = target
        path = path.resolve()
        if not path.is_relative_to(root) or not path.exists():
            issues.append(f"{label}: missing link target")
        elif (
            fragment
            and path.suffix == ".md"
            and fragment not in _anchors(path.read_text(encoding="utf-8"))
        ):
            issues.append(f"{label}: missing link anchor")
    return issues


def _json_issues(label: str, examples: list[str]) -> list[str]:
    issues = []
    for index, text in enumerate(examples, start=1):
        try:
            json.loads(text)
        except (ValueError, RecursionError):
            issues.append(f"{label}: invalid JSON example {index}")
    return issues


def _input_issues(root: Path) -> list[str]:
    schema = ast.parse((root / "civiscribe/node.py").read_text(encoding="utf-8"))
    inputs = {
        node.args[0].value
        for node in ast.walk(schema)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Input"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    reference = root / "docs/wiki/Settings-reference.md"
    text = reference.read_text(encoding="utf-8") if reference.is_file() else ""
    documented = set(re.findall(r"`([a-z_]+)`", text))
    return [f"Settings-reference.md: missing input {name}" for name in sorted(inputs - documented)]


def validate_repository_docs(root: Path = PROJECT_ROOT) -> tuple[str, ...]:
    """Return deterministic errors for missing references and malformed examples."""
    root = root.resolve()
    documents = [root / name for name in DOCUMENTS]
    documents.extend(sorted((root / "docs/wiki").glob("*.md")))
    issues = []
    for document in documents:
        label = document.relative_to(root).as_posix()
        if not document.is_file():
            issues.append(f"{label}: missing document")
            continue
        text = document.read_text(encoding="utf-8")
        issues.extend(_link_issues(root, document, text))
        issues.extend(_json_issues(label, _JSON_BLOCK.findall(text)))
    for example in sorted((root / "docs/examples").glob("*.json")):
        issues.extend(
            _json_issues(
                example.relative_to(root).as_posix(), [example.read_text(encoding="utf-8")]
            )
        )
    issues.extend(_input_issues(root))
    return tuple(issues)


def main() -> int:
    issues = validate_repository_docs()
    for issue in issues:
        print(issue)
    if issues:
        return 1
    print("Repository documentation, wiki links, node inputs, and JSON examples: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
