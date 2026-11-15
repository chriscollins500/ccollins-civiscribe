from __future__ import annotations

from pathlib import Path

import pytest

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
