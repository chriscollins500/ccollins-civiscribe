"""Check published-site completeness, private-file exclusion, and failure detection."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import jsonschema
import pytest

from tools.build_site import (
    BASE,
    GUIDES,
    ROOT,
    _mapping,
    _render_markdown,
    _safe_output,
    build_site,
)
from tools.validate_site import validate_site

EXPECTED_PAGE_COUNT = 30
MAX_COMPRESSED_CLIENT_BYTES = 25_000


@pytest.fixture(scope="module")
def built_site() -> Iterator[Path]:
    with TemporaryDirectory(prefix="site-check-", dir=ROOT / ".tmp") as temporary:
        output = Path(temporary)
        build_site(output)
        yield output


def test_complete_site_and_internal_references(built_site: Path) -> None:
    assert validate_site(built_site) == ()
    manifest = json.loads((built_site / "site-manifest.json").read_text("utf-8"))
    assert manifest["guideSources"] == len(GUIDES)
    assert manifest["pages"] == EXPECTED_PAGE_COUNT
    assert len(list(built_site.rglob("*.html"))) == EXPECTED_PAGE_COUNT


def test_no_private_or_development_files_are_published(built_site: Path) -> None:
    banned = {".git", ".codex", "project-history", "node_modules", ".venv", "__pycache__"}
    for path in built_site.rglob("*"):
        assert not banned.intersection(path.relative_to(built_site).parts)
        assert not path.is_symlink()
    assert (built_site / "assets/quill.png").read_bytes() == (
        ROOT / "assets/branding/civiscribe-icon.png"
    ).read_bytes()


@pytest.mark.parametrize("relative", ["../outside-site", ".tmp/../civiscribe", "docs/site"])
def test_output_cannot_target_source_or_escape_the_project(relative: str) -> None:
    with pytest.raises(ValueError, match="output"):
        _safe_output(ROOT / relative)


def test_search_indexes_documents_without_shared_navigation(built_site: Path) -> None:
    entries = json.loads((built_site / "search-index.json").read_text("utf-8"))
    settings = next(entry for entry in entries if entry["url"].endswith("/settings-reference/"))
    assert "jpeg_quality" in settings["text"]
    assert "Browse the complete field guide" not in settings["text"]
    assert all(entry["url"].startswith(BASE + "/") for entry in entries)
    assert all("{{VERSION}}" not in entry["text"] for entry in entries)


def test_raw_html_and_script_urls_are_not_executable(built_site: Path) -> None:
    source = built_site / "source-example.md"
    source.write_text(
        "# Example\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))\n", encoding="utf-8"
    )
    rendered, _ = _render_markdown(source, _mapping())
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert 'href="javascript:' not in rendered
    source.unlink()


def test_validator_detects_broken_links_and_unannounced_file_changes(built_site: Path) -> None:
    path = built_site / "index.html"
    original = path.read_bytes()
    try:
        path.write_text(
            original.decode("utf-8").replace(
                "</main>", f'<a href="{BASE}/missing/">bad</a></main>'
            ),
            encoding="utf-8",
        )
        issues = validate_site(built_site)
        assert any("missing local link target" in issue for issue in issues)
        assert any("manifest: changed file index.html" in issue for issue in issues)
    finally:
        path.write_bytes(original)


def test_browser_example_matches_the_actual_save_report_schema(built_site: Path) -> None:
    contract = json.loads((ROOT / "civiscribe/schemas/api-v1.openapi.json").read_text("utf-8"))
    schema = {"$ref": "#/components/schemas/SaveResult", "components": contract["components"]}
    example = json.loads((built_site / "examples/save-report.json").read_text("utf-8"))
    jsonschema.Draft202012Validator(schema).validate(example)


def test_client_payload_has_a_small_compressed_budget(built_site: Path) -> None:
    assets = ("styles.css", "app.js", "lab-core.js", "theme.js")
    compressed = sum(
        len(gzip.compress((built_site / "assets" / name).read_bytes())) for name in assets
    )
    assert compressed < MAX_COMPRESSED_CLIENT_BYTES


def test_build_is_deterministic(built_site: Path) -> None:
    before = (built_site / "site-manifest.json").read_bytes()
    build_site(built_site)
    assert (built_site / "site-manifest.json").read_bytes() == before


def test_unexpected_files_cannot_enter_a_deployment(built_site: Path) -> None:
    unexpected = built_site / "private-note.txt"
    unexpected.write_text("synthetic test only", encoding="utf-8")
    try:
        assert any("allowlist" in issue for issue in validate_site(built_site))
        with pytest.raises(ValueError, match="unexpected file"):
            build_site(built_site)
        assert unexpected.read_text("utf-8") == "synthetic test only"
    finally:
        unexpected.unlink()
