from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from civiscribe.domain import WriteError
from civiscribe.storage import atomic
from civiscribe.storage.paths import OutputPlan


def _plan(directory: Path) -> OutputPlan:
    return OutputPlan(directory, directory, "", "image")


def test_temporary_file_flush_and_hardlink_publication(tmp_path: Path) -> None:
    temporary = atomic.create_temporary_path(tmp_path, ".png")
    temporary.write_bytes(b"complete")
    atomic.flush_file(temporary)
    destination = atomic.publish_image(temporary, _plan(tmp_path), ".png")
    assert destination.name == "image_00001_.png"
    assert destination.read_bytes() == b"complete"
    assert not temporary.exists()


def test_publication_skips_existing_counter(tmp_path: Path) -> None:
    (tmp_path / "image_00001_.png").write_bytes(b"existing")
    temporary = atomic.create_temporary_path(tmp_path, ".png")
    temporary.write_bytes(b"new")
    destination = atomic.publish_image(temporary, _plan(tmp_path), ".png")
    assert destination.name == "image_00002_.png"
    assert (tmp_path / "image_00001_.png").read_bytes() == b"existing"


def test_hardlink_race_advances_counter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = atomic.create_temporary_path(tmp_path, ".png")
    temporary.write_bytes(b"new")
    original_link = os.link
    calls = 0

    def link_with_race(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            destination.write_bytes(b"racer")
            raise FileExistsError
        original_link(source, destination)

    monkeypatch.setattr(os, "link", link_with_race)
    destination = atomic.publish_image(temporary, _plan(tmp_path), ".png")
    assert destination.name == "image_00002_.png"
    assert (tmp_path / "image_00001_.png").read_bytes() == b"racer"


def test_link_unavailable_uses_exclusive_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = atomic.create_temporary_path(tmp_path, ".png")
    temporary.write_bytes(b"complete")
    monkeypatch.setattr(os, "link", lambda *_: (_ for _ in ()).throw(OSError(errno.EPERM, "")))
    destination = atomic.publish_image(temporary, _plan(tmp_path), ".png")
    assert destination.read_bytes() == b"complete"
    assert not temporary.exists()


def test_reservation_race_advances_counter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = atomic.create_temporary_path(tmp_path, ".png")
    temporary.write_bytes(b"complete")
    monkeypatch.setattr(os, "link", lambda *_: (_ for _ in ()).throw(OSError(errno.EPERM, "")))
    original = atomic._publish_with_reservation
    calls = 0

    def publish_with_race(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            destination.write_bytes(b"racer")
            raise FileExistsError
        original(source, destination)

    monkeypatch.setattr(atomic, "_publish_with_reservation", publish_with_race)
    destination = atomic.publish_image(temporary, _plan(tmp_path), ".png")
    assert destination.name == "image_00002_.png"
    assert (tmp_path / "image_00001_.png").read_bytes() == b"racer"


def test_unexpected_link_error_is_not_hidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = atomic.create_temporary_path(tmp_path, ".png")
    temporary.write_bytes(b"complete")
    monkeypatch.setattr(os, "link", lambda *_: (_ for _ in ()).throw(OSError(errno.EIO, "")))
    with pytest.raises(OSError):
        atomic.publish_image(temporary, _plan(tmp_path), ".png")
    assert temporary.exists()


def test_failed_reservation_replace_removes_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = atomic.create_temporary_path(tmp_path, ".png")
    temporary.write_bytes(b"complete")
    destination = tmp_path / "final.png"

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        atomic._publish_with_reservation(temporary, destination)
    assert not destination.exists()
    assert temporary.exists()


def test_counter_exhaustion_is_stable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = atomic.create_temporary_path(tmp_path, ".png")
    monkeypatch.setattr(
        OutputPlan,
        "next_counter",
        lambda self, extension: atomic.MAX_COUNTER + 1,
    )
    with pytest.raises(WriteError, match="output_counter_exhausted"):
        atomic.publish_image(temporary, _plan(tmp_path), ".png")


@pytest.mark.parametrize("extension", ["png", ".tar.gz", "../jpg"])
def test_atomic_storage_rejects_untrusted_extensions(
    tmp_path: Path,
    extension: str,
) -> None:
    with pytest.raises(WriteError, match="output_extension_invalid"):
        atomic.create_temporary_path(tmp_path, extension)


def test_atomic_storage_publishes_each_supported_extension(tmp_path: Path) -> None:
    for extension in (".png", ".jpg", ".webp"):
        temporary = atomic.create_temporary_path(tmp_path, extension)
        assert temporary.name.endswith(f"{extension}.tmp")
        temporary.write_bytes(extension.encode("ascii"))
        destination = atomic.publish_image(temporary, _plan(tmp_path), extension)
        assert destination.name == f"image_00001_{extension}"
