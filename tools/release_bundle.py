"""Bind once-built distributions to a commit and verify them before deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from civiscribe.version import __version__
from tools.build_release import DEFAULT_ROOT_NAME, FIXED_ZIP_TIMESTAMP, audit_release

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "release-manifest.json"


def artifact_names() -> tuple[str, ...]:
    return (
        f"ccollins_civiscribe-{__version__}-py3-none-any.whl",
        f"ccollins_civiscribe-{__version__}.tar.gz",
        f"ccollins-civiscribe-{__version__}-private-test.zip",
        f"ccollins-civiscribe-{__version__}-registry.zip",
        "runtime-requirements.txt",
        "runtime-sbom.json",
        "development-licenses.json",
    )


def _facts(path: Path) -> dict[str, str | int]:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"sha256": digest, "bytes": path.stat().st_size}


def _runtime_payload(directory: Path) -> dict[str, bytes]:
    private = directory / artifact_names()[2]
    result = audit_release(private)
    if not result.valid:
        raise ValueError(f"custom-node archive audit failed: {result.errors}")
    with zipfile.ZipFile(private) as archive:
        return {
            name.removeprefix(f"{DEFAULT_ROOT_NAME}/"): archive.read(name)
            for name in archive.namelist()
        }


def validate_payloads(directory: Path) -> None:
    """Compare module bytes, not merely filenames or source-tree timestamps."""
    runtime = _runtime_payload(directory)
    with zipfile.ZipFile(directory / artifact_names()[0]) as wheel:
        modules = {
            name: wheel.read(name) for name in wheel.namelist() if name.startswith("civiscribe/")
        }
    expected = {name: value for name, value in runtime.items() if name.startswith("civiscribe/")}
    if modules != expected:
        raise ValueError("wheel and custom-node runtime differ")
    with zipfile.ZipFile(directory / artifact_names()[3]) as registry:
        expected_registry = {**runtime, "pyproject.toml": (ROOT / "pyproject.toml").read_bytes()}
        if (
            len(registry.infolist()) != len(expected_registry)
            or {name: registry.read(name) for name in registry.namelist()} != expected_registry
        ):
            raise ValueError(
                "Registry archive differs from the audited runtime and project metadata"
            )


def prepare_bundle(directory: Path, commit: str, *, working_tree: bool = False) -> None:
    if re.fullmatch(r"[a-f0-9]{40}", commit) is None:
        raise ValueError("a full source commit is required")
    runtime = _runtime_payload(directory)
    runtime["pyproject.toml"] = (ROOT / "pyproject.toml").read_bytes()
    registry = directory / artifact_names()[3]
    with zipfile.ZipFile(registry, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(runtime.items()):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, payload)
    validate_payloads(directory)
    document = {
        "schemaVersion": 1,
        "commit": commit,
        "version": __version__,
        "sourceState": "working-tree" if working_tree else "committed",
        "artifacts": {name: _facts(directory / name) for name in artifact_names()},
    }
    (directory / MANIFEST).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def verify_bundle(directory: Path, commit: str, *, allow_working_tree: bool = False) -> None:
    document = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    if (
        document.get("schemaVersion") != 1
        or document.get("commit") != commit
        or document.get("version") != __version__
        or document.get("sourceState")
        not in ({"committed", "working-tree"} if allow_working_tree else {"committed"})
        or document.get("artifacts")
        != {name: _facts(directory / name) for name in artifact_names()}
    ):
        raise ValueError("release bundle identity or checksum mismatch")
    validate_payloads(directory)


def stage_node(
    directory: Path, commit: str, destination: Path, *, allow_working_tree: bool = False
) -> None:
    verify_bundle(directory, commit, allow_working_tree=allow_working_tree)
    runtime = _runtime_payload(directory)
    destination.mkdir(parents=True, exist_ok=False)
    for name, payload in runtime.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify", "stage"))
    parser.add_argument("--directory", type=Path, default=ROOT / "dist")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument(
        "--working-tree", action="store_true", help="local testing only; not publishable"
    )
    args = parser.parse_args()
    if args.mode == "prepare":
        _check_source(args.commit, allow_working_tree=args.working_tree)
        prepare_bundle(args.directory, args.commit, working_tree=args.working_tree)
    elif args.mode == "verify":
        verify_bundle(args.directory, args.commit, allow_working_tree=args.working_tree)
    elif args.destination is None:
        parser.error("stage requires --destination (a new isolated custom-node directory)")
    else:
        stage_node(
            args.directory, args.commit, args.destination, allow_working_tree=args.working_tree
        )
    print(f"release bundle {args.mode}: passed")


def _check_source(commit: str, *, allow_working_tree: bool) -> None:
    git = shutil.which("git")
    if git is None:
        raise ValueError("Git is required to bind a release to its source")

    def read_git(*args: str) -> str:
        return subprocess.run(  # noqa: S603 - resolved executable and fixed read-only subcommands
            [git, *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30
        ).stdout.strip()

    if read_git("rev-parse", "HEAD") != commit:
        raise ValueError("source commit is not this checkout's HEAD")
    if read_git("status", "--porcelain") and not allow_working_tree:
        raise ValueError(
            "release source is dirty; use --working-tree only for nonpublishable local tests"
        )


if __name__ == "__main__":
    main()
