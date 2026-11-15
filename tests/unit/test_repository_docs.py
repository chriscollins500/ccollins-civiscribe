"""Regressions for the published documentation's links and examples."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import validate_repository_docs as validator


@pytest.fixture
def docs_project(tmp_path: Path) -> Path:
    for name in validator.DOCUMENTS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Example\n", encoding="utf-8")
    reference = tmp_path / "docs/wiki/Settings-reference.md"
    reference.parent.mkdir(parents=True)
    reference.write_text("# Settings reference\n\n`images`\n", encoding="utf-8")
    source = tmp_path / "civiscribe/node.py"
    source.parent.mkdir()
    source.write_text('schema = io.Image.Input("images")\n', encoding="utf-8")
    return tmp_path


def test_current_repository_documentation_passes() -> None:
    assert validator.validate_repository_docs() == ()


@pytest.mark.parametrize(
    "link", ("missing.md", f"{validator.REPOSITORY_URL}/wiki/Missing", "../outside.md")
)
def test_broken_local_wiki_and_escaping_links_fail(docs_project: Path, link: str) -> None:
    (docs_project / "README.md").write_text(
        f"[Example]({link})\n",
        encoding="utf-8",
    )
    assert validator.validate_repository_docs(docs_project) == ("README.md: missing link target",)


def test_local_and_repository_anchors_are_checked(docs_project: Path) -> None:
    (docs_project / "README.md").write_text(
        "# Start here\n\n"
        "[Current](#start-here)\n"
        f"[Source]({validator.REPOSITORY_URL}/blob/main/SUPPORT.md#example)\n"
        f"[Directory]({validator.REPOSITORY_URL}/tree/main/docs)\n"
        "[Bad](SUPPORT.md#missing)\n"
        "[External](https://example.com/guide)\n",
        encoding="utf-8",
    )
    assert validator.validate_repository_docs(docs_project) == ("README.md: missing link anchor",)


def test_missing_setting_and_invalid_examples_fail(docs_project: Path) -> None:
    (docs_project / "docs/wiki/Settings-reference.md").write_text(
        '# Settings\n\n```json\n{"invalid":}\n```\n', encoding="utf-8"
    )
    examples = docs_project / "docs/examples"
    examples.mkdir()
    (examples / "invalid.json").write_text("{", encoding="utf-8")
    assert validator.validate_repository_docs(docs_project) == (
        "docs/wiki/Settings-reference.md: invalid JSON example 1",
        "docs/examples/invalid.json: invalid JSON example 1",
        "Settings-reference.md: missing input images",
    )


def test_missing_document_is_reported(docs_project: Path) -> None:
    (docs_project / "SUPPORT.md").unlink()
    assert validator.validate_repository_docs(docs_project) == ("SUPPORT.md: missing document",)
