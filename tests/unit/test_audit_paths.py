from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.path_support import directory_link
from tools.audit_paths import scoped_path


def test_selected_scope_accepts_descendants_and_normalizes_paths(tmp_path: Path) -> None:
    root = tmp_path / "selected"
    candidate = root / "nested" / ".." / "sidecar.json"
    assert scoped_path(root, candidate) == (root / "sidecar.json").resolve()


def test_selected_scope_rejects_traversal_and_prefix_lookalikes(tmp_path: Path) -> None:
    root = tmp_path / "selected"
    for candidate in (root / ".." / "outside.json", tmp_path / "selected-other/image.json"):
        with pytest.raises(ValueError, match="audit_path_outside_selected_root"):
            scoped_path(root, candidate)


def test_selected_scope_rejects_link_resolution_outside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "selected"
    linked = root / "linked.json"
    original = Path.resolve

    def resolve(path: Path, strict: bool = False) -> Path:
        return original(tmp_path / "outside.json" if path == linked else path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="audit_path_outside_selected_root"):
        scoped_path(root, linked)


def test_selected_scope_reports_link_loops_without_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def resolve(_path: Path, strict: bool = False) -> Path:
        raise RuntimeError("DO_NOT_RECORD")

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match=r"^audit_path_resolution_failed$"):
        scoped_path(tmp_path, tmp_path / "loop")


@pytest.mark.parametrize("resolve_links", [True, False])
def test_selected_scope_accepts_itself_and_the_filesystem_root(
    tmp_path: Path, resolve_links: bool
) -> None:
    assert scoped_path(tmp_path, tmp_path, resolve_links=resolve_links) == tmp_path.resolve()
    root = Path(tmp_path.anchor)
    assert scoped_path(root, tmp_path, resolve_links=resolve_links) == tmp_path.resolve()


@pytest.mark.parametrize("resolve_links", [True, False])
def test_selected_scope_preserves_external_relative_and_unicode_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resolve_links: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    root = Path("operator selected /資料")
    candidate = root / "nested" / ".." / "image.json"
    assert scoped_path(root, candidate, resolve_links=resolve_links) == (
        tmp_path / root / "image.json"
    )
    for escaped in (root / ".." / "escape.json", Path("operator selected /資料-other/file")):
        with pytest.raises(ValueError, match=r"^audit_path_outside_selected_root$"):
            scoped_path(root, escaped, resolve_links=resolve_links)


def test_real_links_preserve_resolution_and_reject_escapes(tmp_path: Path) -> None:
    root = tmp_path / "selected"
    inside = root / "inside"
    outside = tmp_path / "outside"
    inside.mkdir(parents=True)
    outside.mkdir()
    directory_link(inside, root / "internal-link")
    directory_link(outside, root / "escape-link")
    directory_link(inside, tmp_path / "external-alias")

    assert scoped_path(root, root / "internal-link" / "file.json") == inside / "file.json"
    # Resolved containment, rather than lexical containment, remains the contract.
    assert scoped_path(root, tmp_path / "external-alias" / "file.json") == inside / "file.json"
    with pytest.raises(ValueError, match=r"^audit_path_outside_selected_root$"):
        scoped_path(root, root / "escape-link" / "DO_NOT_READ.json")
    assert scoped_path(root, root / "escape-link", resolve_links=False) == root / "escape-link"
    outside.rmdir()
    assert scoped_path(root, root / "escape-link", resolve_links=False) == root / "escape-link"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive and UNC semantics")
def test_windows_case_drive_and_unc_boundaries() -> None:
    assert scoped_path(
        Path(r"C:\Selected"), Path(r"c:\sELECTED\Child.json"), resolve_links=False
    ) == Path(r"C:\Selected\Child.json")
    assert scoped_path(
        Path(r"\\server\share"), Path(r"\\SERVER\SHARE\Child.json"), resolve_links=False
    ) == Path(r"\\server\share\Child.json")
    for root, candidate in (
        (Path(r"C:\Selected"), Path(r"D:\Selected\Child.json")),
        (Path(r"\\server\share"), Path(r"\\server\share-other\Child.json")),
    ):
        with pytest.raises(ValueError, match=r"^audit_path_outside_selected_root$"):
            scoped_path(root, candidate, resolve_links=False)


@pytest.mark.skipif(os.name == "nt", reason="Windows symbolic links require an OS privilege")
def test_real_symbolic_link_loop_has_a_sanitized_error(tmp_path: Path) -> None:
    loop = tmp_path / "DO_NOT_RECORD"
    loop.symlink_to(loop)
    with pytest.raises(ValueError, match=r"^audit_path_resolution_failed$"):
        scoped_path(tmp_path, loop)
