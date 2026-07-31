from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from civiscribe.domain import WriteError
from civiscribe.storage import atomic, write_sidecar_json


def _temporary(directory: Path, payload: bytes = b"sidecar") -> Path:
    path = atomic.create_temporary_path(directory, ".json")
    path.write_bytes(payload)
    return path


def test_sidecar_writer_publishes_exact_utf8_without_bom(tmp_path: Path) -> None:
    destination = tmp_path / "image.json"
    text = '{"prompt":"café 雪"}'
    assert write_sidecar_json(destination, text) == destination
    assert destination.read_bytes() == text.encode("utf-8")
    assert not destination.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not list(tmp_path.glob(".civiscribe-*"))


def test_sidecar_writer_never_overwrites_existing_file(tmp_path: Path) -> None:
    destination = tmp_path / "image.json"
    destination.write_bytes(b"existing")
    with pytest.raises(WriteError, match="companion_destination_exists"):
        write_sidecar_json(destination, '{"new":true}')
    assert destination.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".civiscribe-*"))


def test_sidecar_writer_rejects_wrong_extension(tmp_path: Path) -> None:
    with pytest.raises(WriteError, match="sidecar_extension_invalid"):
        write_sidecar_json(tmp_path / "image.txt", "{}")


def test_sidecar_writer_sanitizes_filesystem_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        Path,
        "write_bytes",
        lambda *_: (_ for _ in ()).throw(OSError("private path")),
    )
    with pytest.raises(WriteError, match="sidecar_write_failed"):
        write_sidecar_json(tmp_path / "image.json", "{}")
    assert not list(tmp_path.glob(".civiscribe-*"))


def test_sidecar_writer_sanitizes_unicode_failure(tmp_path: Path) -> None:
    with pytest.raises(WriteError, match="sidecar_write_failed"):
        write_sidecar_json(tmp_path / "image.json", "\ud800")
    assert not list(tmp_path.glob(".civiscribe-*"))


def test_companion_publication_requires_same_directory(tmp_path: Path) -> None:
    source_directory = tmp_path / "source"
    destination_directory = tmp_path / "destination"
    source_directory.mkdir()
    destination_directory.mkdir()
    temporary = _temporary(source_directory)
    with pytest.raises(WriteError, match="companion_directory_mismatch"):
        atomic.publish_companion(temporary, destination_directory / "image.json")
    assert temporary.exists()


def test_companion_hardlink_publication_removes_temporary(tmp_path: Path) -> None:
    temporary = _temporary(tmp_path)
    destination = tmp_path / "image.json"
    assert atomic.publish_companion(temporary, destination) == destination
    assert destination.read_bytes() == b"sidecar"
    assert not temporary.exists()


def test_companion_link_unavailable_uses_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = _temporary(tmp_path)
    destination = tmp_path / "image.json"
    monkeypatch.setattr(
        os,
        "link",
        lambda *_: (_ for _ in ()).throw(OSError(errno.EPERM, "")),
    )
    assert atomic.publish_companion(temporary, destination) == destination
    assert destination.read_bytes() == b"sidecar"
    assert not temporary.exists()


def test_companion_reservation_race_is_stable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = _temporary(tmp_path)
    destination = tmp_path / "image.json"
    destination.write_bytes(b"existing")
    monkeypatch.setattr(
        os,
        "link",
        lambda *_: (_ for _ in ()).throw(OSError(errno.EPERM, "")),
    )
    with pytest.raises(WriteError, match="companion_destination_exists"):
        atomic.publish_companion(temporary, destination)
    assert destination.read_bytes() == b"existing"
    assert temporary.exists()


def test_companion_unexpected_link_failure_is_not_hidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = _temporary(tmp_path)
    monkeypatch.setattr(
        os,
        "link",
        lambda *_: (_ for _ in ()).throw(OSError(errno.EIO, "")),
    )
    with pytest.raises(OSError):
        atomic.publish_companion(temporary, tmp_path / "image.json")
    assert temporary.exists()
