"""Keep publication bounded and preserve unreviewed wiki content and attachments."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import sync_wiki as publisher


@pytest.fixture
def wiki(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(publisher, "ROOT", tmp_path)
    source = tmp_path / "docs/wiki"
    source.mkdir(parents=True)
    (source / "Home.md").write_text("# Synthetic guide\n", encoding="utf-8")
    directory = tmp_path / ".tmp/wiki"
    (directory / ".git").mkdir(parents=True)
    return directory


def test_publish_and_compare_preserve_attachments(wiki: Path) -> None:
    attachment = wiki / "attachment.bin"
    attachment.write_bytes(b"synthetic attachment")
    assert publisher.sync_wiki(wiki) == ("wiki_page_differs:Home.md",)
    assert publisher.sync_wiki(wiki, write=True) == ()
    assert publisher.sync_wiki(wiki) == ()
    assert attachment.read_bytes() == b"synthetic attachment"


def test_unknown_pages_block_publication_without_modifying_any_content(wiki: Path) -> None:
    unknown = wiki / "Unreviewed.md"
    unknown.write_text("Keep this contribution", encoding="utf-8")
    assert publisher.sync_wiki(wiki, write=True) == (
        "wiki_has_unmanaged_pages_promote_them_to_reviewed_source_first",
    )
    assert unknown.read_text("utf-8") == "Keep this contribution"
    assert not (wiki / "Home.md").exists()


def test_destination_must_be_an_isolated_checkout(wiki: Path) -> None:
    with pytest.raises(ValueError, match="outside_selected_root"):
        publisher.sync_wiki(wiki.parent.parent / "other")
    (wiki / ".git").rmdir()
    with pytest.raises(ValueError, match="checkout_required"):
        publisher.sync_wiki(wiki)


def test_even_a_broken_target_link_is_rejected_before_writing(
    wiki: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.is_symlink
    target = wiki / "Home.md"
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(ValueError, match="ordinary_file"):
        publisher.sync_wiki(wiki, write=True)
    assert not target.exists()


def test_oversized_source_cannot_be_published(wiki: Path) -> None:
    source = publisher.ROOT / "docs/wiki/Home.md"
    source.write_bytes(b"x" * (publisher.MAX_PAGE_BYTES + 1))
    with pytest.raises(ValueError, match="too_large"):
        publisher.sync_wiki(wiki, write=True)
