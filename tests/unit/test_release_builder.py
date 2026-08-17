from __future__ import annotations

import json
import stat
import warnings
import zipfile
from pathlib import Path

import pytest

import tools.build_release as release_builder
from tools.build_release import (
    DEFAULT_ROOT_NAME,
    FILE_MODE,
    FIXED_ZIP_TIMESTAMP,
    REQUIRED_MEMBERS,
    ReleaseBuildError,
    audit_release,
    build_release,
    main,
)

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="")


def _runtime_source(root: Path) -> None:
    _write(root / "__init__.py", 'WEB_DIRECTORY = "./web/runtime"\n')
    _write(root / "LICENSE", "MIT License\n")
    _write(root / "README.md", "# CiviScribe\n")
    _write(root / "civiscribe" / "__init__.py", '"""Runtime package."""\n')
    _write(root / "civiscribe" / "version.py", '__version__ = "2.0.0.dev0"\n')
    _write(root / "civiscribe" / "schemas" / "sidecar.json", "{}\n")
    _write(root / "locales" / "en" / "nodeDefs.json", "{}\n")
    _write(root / "locales" / "fr" / "nodeDefs.json", "{}\n")
    _write(root / "web" / "runtime" / "civiscribe.js", "export const value = 1;\n")
    _write(root / "web" / "runtime" / "extension.js", "export const extension = {};\n")


def _deterministic_info(name: str, payload: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = FILE_MODE << 16
    return info, payload


def _valid_entries() -> list[tuple[zipfile.ZipInfo, bytes]]:
    payloads = {
        "__init__.py": b'WEB_DIRECTORY = "./web/runtime"\n',
        "LICENSE": b"MIT License\n",
        "README.md": b"# CiviScribe\n",
        "civiscribe/__init__.py": b'"""Runtime package."""\n',
        "civiscribe/version.py": b'__version__ = "2.0.0.dev0"\n',
        "locales/en/nodeDefs.json": b"{}\n",
        "web/runtime/civiscribe.js": b"export const value = 1;\n",
        "web/runtime/extension.js": b"export const extension = {};\n",
    }
    return [
        _deterministic_info(f"{DEFAULT_ROOT_NAME}/{relative}", payload)
        for relative, payload in sorted(payloads.items())
    ]


def _write_archive(
    path: Path,
    entries: list[tuple[zipfile.ZipInfo, bytes]],
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for info, payload in entries:
            archive.writestr(info, payload)


def test_builder_is_allowlisted_deterministic_and_audited(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _runtime_source(source)
    _write(source / "civiscribe" / "__pycache__" / "ignored.pyc", "compiled")
    _write(source / "civiscribe" / "notes.md", "not runtime")
    _write(source / "locales" / "README.md", "not runtime")
    _write(source / "web" / "src" / "source.ts", "not compiled")
    _write(source / "tests" / "test_private.py", "not runtime")
    _write(source / "docs" / "private.md", "not runtime")
    _write(source / "node_modules" / "package" / "index.js", "not runtime")
    _write(source / "package.egg-info" / "PKG-INFO", "not runtime")
    _write(source / ".tmp" / "cache.json", "{}")

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first_result = build_release(source, first)
    second_result = build_release(source, second)

    assert first_result.valid
    assert second_result.valid
    assert first.read_bytes() == second.read_bytes()
    assert first_result.archive_sha256 == second_result.archive_sha256

    with zipfile.ZipFile(first) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert names == sorted(names)
        assert all(name.startswith(f"{DEFAULT_ROOT_NAME}/") for name in names)
        assert {name.removeprefix(f"{DEFAULT_ROOT_NAME}/") for name in names} == {
            "__init__.py",
            "LICENSE",
            "README.md",
            "civiscribe/__init__.py",
            "civiscribe/schemas/sidecar.json",
            "civiscribe/version.py",
            "locales/en/nodeDefs.json",
            "locales/fr/nodeDefs.json",
            "web/runtime/civiscribe.js",
            "web/runtime/extension.js",
        }
        assert all(info.date_time == FIXED_ZIP_TIMESTAMP for info in infos)
        assert all((info.external_attr >> 16) == FILE_MODE for info in infos)


def test_real_v2_source_builds_with_only_runtime_members(tmp_path: Path) -> None:
    output = tmp_path / "civiscribe.zip"
    result = build_release(ROOT, output)

    assert result.valid
    assert audit_release(output).valid
    with zipfile.ZipFile(output) as archive:
        relative_names = {
            info.filename.removeprefix(f"{DEFAULT_ROOT_NAME}/") for info in archive.infolist()
        }
    assert REQUIRED_MEMBERS.issubset(relative_names)
    assert not any(
        part.casefold() in {"__pycache__", "docs", "node_modules", "tests", ".tmp", ".egg-info"}
        for name in relative_names
        for part in name.split("/")
    )


def test_auditor_rejects_traversal_absolute_and_multiple_roots(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    entries = _valid_entries()
    entries.extend(
        [
            _deterministic_info(f"{DEFAULT_ROOT_NAME}/../escape.py", b"pass\n"),
            _deterministic_info("/absolute.py", b"pass\n"),
            _deterministic_info("other-root/file.py", b"pass\n"),
        ]
    )
    _write_archive(archive_path, entries)

    result = audit_release(archive_path)
    assert not result.valid
    assert "member_path_invalid" in result.errors
    assert "root_folder_invalid" in result.errors


def test_auditor_rejects_duplicate_and_case_colliding_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "duplicate.zip"
    entries = _valid_entries()
    entries.extend(
        [
            _deterministic_info(f"{DEFAULT_ROOT_NAME}/README.md", b"duplicate\n"),
            _deterministic_info(f"{DEFAULT_ROOT_NAME}/readme.md", b"collision\n"),
        ]
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        _write_archive(archive_path, entries)

    result = audit_release(archive_path)
    assert "duplicate_member" in result.errors


def test_auditor_rejects_symlinks_forbidden_members_and_hidden_metadata(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "unsafe.zip"
    entries = _valid_entries()
    symlink = zipfile.ZipInfo(
        f"{DEFAULT_ROOT_NAME}/civiscribe/link.py",
        FIXED_ZIP_TIMESTAMP,
    )
    symlink.compress_type = zipfile.ZIP_DEFLATED
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    hidden = _deterministic_info(
        f"{DEFAULT_ROOT_NAME}/civiscribe/hidden.py",
        b"pass\n",
    )[0]
    hidden.extra = b"\x01\x00\x00\x00"
    entries.extend(
        [
            (symlink, b"target.py"),
            (hidden, b"pass\n"),
            _deterministic_info(f"{DEFAULT_ROOT_NAME}/tests/test_runtime.py", b"pass\n"),
            _deterministic_info(
                f"{DEFAULT_ROOT_NAME}/civiscribe/package.egg-info/PKG-INFO",
                b"metadata\n",
            ),
            _deterministic_info(
                f"{DEFAULT_ROOT_NAME}/web/runtime/node_modules/pkg.js",
                b"export {};\n",
            ),
        ]
    )
    _write_archive(archive_path, entries)

    result = audit_release(archive_path)
    assert "symlink_member_detected" in result.errors
    assert "forbidden_member" in result.errors
    assert "member_hidden_metadata" in result.errors
    assert "member_not_allowed" in result.errors


def test_auditor_rejects_private_paths_and_obvious_secrets_without_echoing(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "private.zip"
    entries = _valid_entries()
    private_payload = (
        b'cache = "C:\\\\Users\\\\Example\\\\private.json"\n'
        b'authorization = "Bearer abcdefghijklmnopqrstuvwxyz"\n'
    )
    entries.append(
        _deterministic_info(
            f"{DEFAULT_ROOT_NAME}/civiscribe/private.py",
            private_payload,
        )
    )
    _write_archive(archive_path, entries)

    result = audit_release(archive_path)
    assert "private_path_detected" in result.errors
    assert "secret_detected" in result.errors
    assert "Example" not in repr(result)
    assert "abcdefghijklmnopqrstuvwxyz" not in repr(result)


def test_auditor_rejects_missing_required_members_and_invalid_zip(
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.zip"
    entries = [
        entry
        for entry in _valid_entries()
        if not entry[0].filename.endswith("/web/runtime/extension.js")
    ]
    _write_archive(missing_path, entries)
    assert "required_member_missing" in audit_release(missing_path).errors

    invalid_path = tmp_path / "invalid.zip"
    invalid_path.write_bytes(b"not a zip")
    invalid_result = audit_release(invalid_path)
    assert invalid_result.errors == ("archive_invalid",)
    assert "not a zip" not in repr(invalid_result)


def test_builder_rejects_source_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _runtime_source(source)
    link = source / "civiscribe" / "link.py"
    _write(link, "value = 1\n")

    original = release_builder._is_link_like
    monkeypatch.setattr(
        release_builder,
        "_is_link_like",
        lambda path: path == link or original(path),
    )

    with pytest.raises(ReleaseBuildError) as raised:
        build_release(source, tmp_path / "release.zip")
    assert raised.value.errors == ("source_symlink_detected",)


def test_cli_build_and_audit_reports_are_machine_readable_and_sanitized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    _runtime_source(source)
    output = tmp_path / "release.zip"

    assert main(["build", str(output), "--source-root", str(source)]) == 0
    build_report = json.loads(capsys.readouterr().out)
    assert build_report["mode"] == "build"
    assert build_report["valid"] is True
    assert str(tmp_path) not in json.dumps(build_report)

    assert main(["audit", str(output)]) == 0
    audit_report = json.loads(capsys.readouterr().out)
    assert audit_report["mode"] == "audit"
    assert audit_report["valid"] is True
    assert str(tmp_path) not in json.dumps(audit_report)
