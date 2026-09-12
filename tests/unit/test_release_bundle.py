from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from tools.build_release import build_release
from tools.release_bundle import (
    MANIFEST,
    ROOT,
    artifact_names,
    prepare_bundle,
    stage_node,
    verify_bundle,
)

COMMIT = "a" * 40


def _bundle(tmp_path: Path) -> None:
    wheel, sdist, private, _, *reports = artifact_names()
    build_release(ROOT, tmp_path / private)
    with (
        zipfile.ZipFile(tmp_path / private) as archive,
        zipfile.ZipFile(tmp_path / wheel, "w") as output,
    ):
        for name in archive.namelist():
            relative = name.partition("/")[2]
            if relative.startswith("civiscribe/"):
                output.writestr(relative, archive.read(name))
    (tmp_path / sdist).write_bytes(b"synthetic sdist integrity fixture")
    for name in reports:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    prepare_bundle(tmp_path, COMMIT)


def test_bundle_checks_identity_payloads_and_stages_without_overwrite(tmp_path: Path) -> None:
    _bundle(tmp_path)
    verify_bundle(tmp_path, COMMIT)
    stage_node(tmp_path, COMMIT, tmp_path / "installed")
    assert (tmp_path / "installed/civiscribe/version.py").read_bytes() == (
        ROOT / "civiscribe/version.py"
    ).read_bytes()
    with pytest.raises(FileExistsError):
        stage_node(tmp_path, COMMIT, tmp_path / "installed")
    with pytest.raises(ValueError, match="identity"):
        verify_bundle(tmp_path, "b" * 40)


@pytest.mark.parametrize("name", artifact_names())
def test_bundle_rejects_any_changed_artifact(tmp_path: Path, name: str) -> None:
    _bundle(tmp_path)
    with (tmp_path / name).open("ab") as file:
        file.write(b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        verify_bundle(tmp_path, COMMIT)


def test_bundle_rejects_missing_and_unsafe_manifest_entries(tmp_path: Path) -> None:
    _bundle(tmp_path)
    manifest = json.loads((tmp_path / MANIFEST).read_text(encoding="utf-8"))
    manifest["artifacts"]["../outside"] = {"sha256": "a" * 64, "bytes": 1}
    (tmp_path / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        verify_bundle(tmp_path, COMMIT)


def test_bundle_rejects_a_different_wheel_even_when_preparing_checksums(tmp_path: Path) -> None:
    _bundle(tmp_path)
    with zipfile.ZipFile(tmp_path / artifact_names()[0], "w") as archive:
        archive.writestr("civiscribe/version.py", b"different")
    with pytest.raises(ValueError, match="runtime differ"):
        prepare_bundle(tmp_path, COMMIT)


def test_local_working_tree_bundle_cannot_pass_publication_verification(tmp_path: Path) -> None:
    _bundle(tmp_path)
    prepare_bundle(tmp_path, COMMIT, working_tree=True)
    with pytest.raises(ValueError, match="identity"):
        verify_bundle(tmp_path, COMMIT)
    verify_bundle(tmp_path, COMMIT, allow_working_tree=True)
