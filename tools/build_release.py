"""Build and audit deterministic CiviScribe V2 custom-node release archives."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT_NAME = "ccollins-civiscribe"
DEFAULT_ARCHIVE_NAME = f"{DEFAULT_ROOT_NAME}-private-test.zip"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FILE_MODE = stat.S_IFREG | 0o644
ZIP_UNIX_SYSTEM = 3
MIN_ARCHIVE_MEMBER_PARTS = 2
MAX_MEMBER_COUNT = 4096
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024

ROOT_FILES = frozenset({"__init__.py", "LICENSE", "README.md"})
TREE_SUFFIXES: dict[str, frozenset[str]] = {
    "civiscribe": frozenset({".json", ".py"}),
    "locales": frozenset({".json"}),
    "web/runtime": frozenset({".js"}),
}
REQUIRED_MEMBERS = frozenset(
    {
        "__init__.py",
        "LICENSE",
        "README.md",
        "civiscribe/__init__.py",
        "civiscribe/version.py",
        "locales/en/nodeDefs.json",
        "web/runtime/civiscribe.js",
        "web/runtime/extension.js",
    }
)
FORBIDDEN_PARTS = frozenset(
    {
        ".benchmarks",
        ".git",
        ".github",
        ".hypothesis",
        ".mypy_cache",
        ".npm-cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tmp",
        ".uv-cache",
        ".venv",
        "__pycache__",
        "docs",
        "node_modules",
        "test-results",
        "tests",
        "venv",
    }
)
ROOT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
WINDOWS_ABSOLUTE_PATTERN = re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/]")
WINDOWS_UNC_PATTERN = re.compile(r"\\\\[A-Za-z0-9.$_-]+\\[A-Za-z0-9.$_-]+")
PRIVATE_POSIX_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])/(?:Users|home|tmp|var/tmp|private/var|mnt/[a-z])/"
)
FILE_URI_PATTERN = re.compile(r"(?i)\bfile:///(?:[A-Z]:/|Users/|home/|tmp/)")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:EC |OPENSSH |PGP |RSA )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b"),
    re.compile(
        r"""(?ix)
        \b(?:api[_-]?key|access[_-]?token|password|secret)\b
        \s*[:=]\s*
        ["'][A-Za-z0-9._~+/=-]{12,}["']
        """
    ),
)


@dataclass(frozen=True, slots=True)
class ReleaseAuditResult:
    """Sanitized result from auditing one release archive."""

    errors: tuple[str, ...]
    member_count: int
    archive_size_bytes: int | None
    archive_sha256: str | None

    @property
    def valid(self) -> bool:
        return not self.errors

    def report(self, *, mode: str) -> dict[str, object]:
        """Return a deterministic report without filesystem paths or payload values."""

        return {
            "archiveSha256": self.archive_sha256,
            "archiveSizeBytes": self.archive_size_bytes,
            "errors": list(self.errors),
            "memberCount": self.member_count,
            "mode": mode,
            "valid": self.valid,
        }


class ReleaseBuildError(RuntimeError):
    """A sanitized build failure with stable machine-readable error codes."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(sorted(set(errors)))
        super().__init__("release_build_failed")


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction is not None and is_junction(path))


def _valid_root_name(value: str) -> bool:
    return (
        ROOT_NAME_PATTERN.fullmatch(value) is not None
        and value not in {".", ".."}
        and not value.casefold().endswith(".egg-info")
    )


def _safe_parts(value: str) -> tuple[str, ...] | None:
    if (
        not value
        or "\x00" in value
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
    ):
        return None
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return parts


def _has_forbidden_part(parts: Sequence[str]) -> bool:
    folded = tuple(part.casefold() for part in parts)
    return any(
        part in FORBIDDEN_PARTS or part.endswith((".egg-info", ".pyc", ".pyo")) for part in folded
    )


def _allowed_relative(relative: str) -> bool:
    parts = _safe_parts(relative)
    if parts is None or _has_forbidden_part(parts):
        return False
    if relative in ROOT_FILES:
        return True
    for tree, suffixes in TREE_SUFFIXES.items():
        prefix = f"{tree}/"
        if relative.startswith(prefix) and Path(parts[-1]).suffix.casefold() in suffixes:
            return True
    return False


def _privacy_errors(payload: bytes) -> tuple[str, ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return ("member_not_utf8",)

    errors: set[str] = set()
    if (
        WINDOWS_ABSOLUTE_PATTERN.search(text) is not None
        or WINDOWS_UNC_PATTERN.search(text) is not None
        or PRIVATE_POSIX_PATTERN.search(text) is not None
        or FILE_URI_PATTERN.search(text) is not None
    ):
        errors.add("private_path_detected")
    if any(pattern.search(text) is not None for pattern in SECRET_PATTERNS):
        errors.add("secret_detected")
    return tuple(sorted(errors))


def _walk_runtime_tree(source_root: Path, tree: str) -> tuple[list[Path], list[str]]:
    tree_root = source_root.joinpath(*tree.split("/"))
    if not tree_root.is_dir():
        return [], ["runtime_tree_missing"]
    if _is_link_like(tree_root):
        return [], ["source_symlink_detected"]

    files: list[Path] = []
    errors: list[str] = []
    for current, directory_names, file_names in os.walk(tree_root, followlinks=False):
        current_path = Path(current)
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = current_path / name
            if _is_link_like(candidate):
                errors.append("source_symlink_detected")
            else:
                retained_directories.append(name)
        directory_names[:] = retained_directories

        for name in sorted(file_names):
            candidate = current_path / name
            if _is_link_like(candidate):
                errors.append("source_symlink_detected")
                continue
            if not candidate.is_file():
                errors.append("source_non_regular_file")
                continue
            relative = candidate.relative_to(source_root).as_posix()
            if _allowed_relative(relative):
                files.append(candidate)
    return files, errors


def _collect_entries(source_root: Path) -> tuple[tuple[str, bytes], ...]:
    errors: list[str] = []
    if not source_root.is_dir():
        raise ReleaseBuildError(("source_root_invalid",))
    if _is_link_like(source_root):
        raise ReleaseBuildError(("source_symlink_detected",))

    paths: list[Path] = []
    for name in sorted(ROOT_FILES):
        path = source_root / name
        if _is_link_like(path):
            errors.append("source_symlink_detected")
        elif not path.is_file():
            errors.append("required_member_missing")
        else:
            paths.append(path)

    for tree in sorted(TREE_SUFFIXES):
        tree_files, tree_errors = _walk_runtime_tree(source_root, tree)
        paths.extend(tree_files)
        errors.extend(tree_errors)

    relative_paths = {path.relative_to(source_root).as_posix() for path in paths}
    if not REQUIRED_MEMBERS.issubset(relative_paths):
        errors.append("required_member_missing")

    entries: list[tuple[str, bytes]] = []
    for path in sorted(paths, key=lambda item: item.relative_to(source_root).as_posix()):
        relative = path.relative_to(source_root).as_posix()
        try:
            payload = path.read_bytes()
        except OSError:
            errors.append("source_unreadable")
            continue
        errors.extend(_privacy_errors(payload))
        entries.append((relative, payload))

    if errors:
        raise ReleaseBuildError(errors)
    return tuple(entries)


def _zip_bytes(entries: Sequence[tuple[str, bytes]], *, root_name: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for relative, payload in entries:
            info = zipfile.ZipInfo(f"{root_name}/{relative}", FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = ZIP_UNIX_SYSTEM
            info.external_attr = FILE_MODE << 16
            info.internal_attr = 0
            info.extra = b""
            info.comment = b""
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _audit_info_metadata(info: zipfile.ZipInfo) -> set[str]:
    errors: set[str] = set()
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(unix_mode):
        errors.add("symlink_member_detected")
    elif unix_mode and not stat.S_ISREG(unix_mode):
        errors.add("non_regular_member")
    if info.create_system != ZIP_UNIX_SYSTEM or unix_mode != FILE_MODE:
        errors.add("member_permissions_invalid")
    if info.date_time != FIXED_ZIP_TIMESTAMP:
        errors.add("member_timestamp_invalid")
    if info.compress_type != zipfile.ZIP_DEFLATED:
        errors.add("member_compression_invalid")
    if info.flag_bits & 0x1:
        errors.add("encrypted_member")
    if info.extra or info.comment:
        errors.add("member_hidden_metadata")
    return errors


def _member_location(name: str) -> tuple[str | None, str | None, set[str]]:
    parts = _safe_parts(name)
    if parts is None or len(parts) < MIN_ARCHIVE_MEMBER_PARTS:
        return None, None, {"member_path_invalid"}
    relative = "/".join(parts[1:])
    errors: set[str] = set()
    if _has_forbidden_part(parts[1:]):
        errors.add("forbidden_member")
    if not _allowed_relative(relative):
        errors.add("member_not_allowed")
    return parts[0], relative, errors


def _read_member_payload(
    archive: zipfile.ZipFile,
    *,
    info: zipfile.ZipInfo,
) -> tuple[bytes | None, set[str]]:
    if info.file_size > MAX_MEMBER_BYTES:
        return None, {"member_size_exceeded"}
    if info.flag_bits & 0x1:
        return None, set()
    try:
        with archive.open(info, mode="r") as handle:
            payload = handle.read(MAX_MEMBER_BYTES + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        return None, {"member_unreadable"}
    if len(payload) > MAX_MEMBER_BYTES:
        return None, {"member_size_exceeded"}
    return payload, set()


def _audit_members(
    archive: zipfile.ZipFile,
    infos: Sequence[zipfile.ZipInfo],
) -> tuple[set[str], set[str], set[str]]:
    errors: set[str] = set()
    seen_names: set[str] = set()
    seen_relative: set[str] = set()
    root_names: set[str] = set()
    declared_size = 0

    for info in infos[:MAX_MEMBER_COUNT]:
        name = info.filename
        canonical_name = name.casefold()
        if canonical_name in seen_names:
            errors.add("duplicate_member")
        seen_names.add(canonical_name)

        root_name, relative, location_errors = _member_location(name)
        errors.update(location_errors)
        if root_name is None or relative is None:
            continue
        root_names.add(root_name)
        if _allowed_relative(relative):
            seen_relative.add(relative)

        if info.is_dir():
            errors.add("directory_member")
            continue
        errors.update(_audit_info_metadata(info))

        declared_size += info.file_size
        if declared_size > MAX_ARCHIVE_BYTES:
            errors.add("archive_size_exceeded")
            continue
        payload, payload_errors = _read_member_payload(archive, info=info)
        errors.update(payload_errors)
        if payload is not None:
            errors.update(_privacy_errors(payload))
    return errors, seen_relative, root_names


def _audit_open_archive(
    archive: zipfile.ZipFile,
    *,
    expected_root: str,
) -> tuple[tuple[str, ...], int]:
    errors: set[str] = set()
    infos = archive.infolist()
    member_count = len(infos)
    if archive.comment:
        errors.add("archive_comment_detected")
    if member_count > MAX_MEMBER_COUNT:
        errors.add("member_count_exceeded")

    bounded_infos = infos[:MAX_MEMBER_COUNT]
    names = [info.filename for info in bounded_infos]
    if names != sorted(names):
        errors.add("member_order_invalid")
    member_errors, seen_relative, root_names = _audit_members(archive, bounded_infos)
    errors.update(member_errors)

    if root_names != {expected_root}:
        errors.add("root_folder_invalid")
    if not REQUIRED_MEMBERS.issubset(seen_relative):
        errors.add("required_member_missing")
    return tuple(sorted(errors)), member_count


def audit_release(
    archive_path: Path,
    *,
    expected_root: str = DEFAULT_ROOT_NAME,
) -> ReleaseAuditResult:
    """Audit a private custom-node ZIP without extracting it."""

    if not _valid_root_name(expected_root):
        return ReleaseAuditResult(("root_name_invalid",), 0, None, None)
    if _is_link_like(archive_path):
        return ReleaseAuditResult(("archive_symlink_detected",), 0, None, None)
    try:
        payload = archive_path.read_bytes()
    except OSError:
        return ReleaseAuditResult(("archive_unreadable",), 0, None, None)

    digest = _sha256_bytes(payload)
    try:
        with zipfile.ZipFile(io.BytesIO(payload), mode="r") as archive:
            errors, member_count = _audit_open_archive(
                archive,
                expected_root=expected_root,
            )
    except (OSError, RuntimeError, zipfile.BadZipFile):
        return ReleaseAuditResult(
            ("archive_invalid",),
            0,
            len(payload),
            digest,
        )
    return ReleaseAuditResult(errors, member_count, len(payload), digest)


def build_release(
    source_root: Path,
    output_path: Path,
    *,
    root_name: str = DEFAULT_ROOT_NAME,
) -> ReleaseAuditResult:
    """Build, audit, and atomically publish a deterministic custom-node ZIP."""

    if not _valid_root_name(root_name):
        raise ReleaseBuildError(("root_name_invalid",))
    if output_path.suffix.casefold() != ".zip":
        raise ReleaseBuildError(("output_extension_invalid",))
    if _is_link_like(output_path):
        raise ReleaseBuildError(("output_symlink_detected",))

    entries = _collect_entries(source_root)
    entry_paths = {
        path.resolve(strict=False)
        for path in (source_root.joinpath(*relative.split("/")) for relative, _payload in entries)
    }
    if output_path.resolve(strict=False) in entry_paths:
        raise ReleaseBuildError(("output_conflicts_with_source",))

    payload = _zip_bytes(entries, root_name=root_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_bytes(payload)
        result = audit_release(temporary_path, expected_root=root_name)
        if not result.valid:
            raise ReleaseBuildError(result.errors)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    build_parser = subparsers.add_parser("build", help="Build and audit a release ZIP.")
    build_parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=SOURCE_ROOT / "dist" / DEFAULT_ARCHIVE_NAME,
    )
    build_parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    build_parser.add_argument("--root-name", default=DEFAULT_ROOT_NAME)

    audit_parser = subparsers.add_parser("audit", help="Audit an existing release ZIP.")
    audit_parser.add_argument("archive", type=Path)
    audit_parser.add_argument("--root-name", default=DEFAULT_ROOT_NAME)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the deterministic build or read-only audit CLI."""

    args = _parser().parse_args(argv)
    if args.mode == "build":
        try:
            result = build_release(
                args.source_root,
                args.output,
                root_name=args.root_name,
            )
        except ReleaseBuildError as exc:
            result = ReleaseAuditResult(exc.errors, 0, None, None)
    else:
        result = audit_release(args.archive, expected_root=args.root_name)

    print(json.dumps(result.report(mode=args.mode), sort_keys=True))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
