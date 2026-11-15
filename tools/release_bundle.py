"""Bind once-built distributions to a commit and verify them before deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

from civiscribe.version import __version__
from tools.audit_paths import scoped_path
from tools.build_release import (
    DEFAULT_ROOT_NAME,
    FIXED_ZIP_TIMESTAMP,
    MAX_MEMBER_BYTES,
    audit_release,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "release-manifest.json"
RELEASE_REPOSITORY = "chriscollins500/ccollins-civiscribe"


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


def release_assets(directory: Path) -> tuple[Path, ...]:
    """The complete public asset list, even when dist holds older builds too."""
    return tuple(directory / name for name in (*artifact_names(), MANIFEST))


def verify_attestations(directory: Path, commit: str, *, registry_only: bool) -> None:
    """Check the exact bytes against the protected main publication workflow."""
    gh = shutil.which("gh")
    if gh is None:
        raise ValueError("GitHub CLI is required to verify release attestations")
    assets = (directory / artifact_names()[3],) if registry_only else release_assets(directory)
    for asset in assets:
        subprocess.run(  # noqa: S603 - resolved CLI, fixed policy and allowlisted assets
            [
                gh,
                "attestation",
                "verify",
                str(asset),
                "--repo",
                RELEASE_REPOSITORY,
                "--signer-workflow",
                f"{RELEASE_REPOSITORY}/.github/workflows/publish.yml",
                "--source-ref",
                "refs/heads/main",
                "--source-digest",
                commit,
                "--deny-self-hosted-runners",
            ],
            check=True,
            timeout=90,
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


def _verify_sdist(path: Path, runtime: dict[str, bytes], package_metadata: bytes) -> None:
    """Check the source archive against the node and wheel without extracting it."""
    prefix = path.name.removesuffix(".tar.gz") + "/"
    expected = {
        **runtime,
        "pyproject.toml": (ROOT / "pyproject.toml").read_bytes(),
        "locales/README.md": (ROOT / "locales/README.md").read_bytes(),
        ".gitignore": (ROOT / ".gitignore").read_bytes(),
        "PKG-INFO": package_metadata,
    }
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            relative = member.name.removeprefix(prefix)
            content = expected.pop(relative, None)
            if (
                not member.name.startswith(prefix)
                or not member.isfile()
                or content is None
                or member.size != len(content)
                or member.size > MAX_MEMBER_BYTES
            ):
                raise ValueError("unexpected source distribution member")
            reader = archive.extractfile(member)
            if reader is None or reader.read() != content:
                raise ValueError("source distribution payload differs from the validated package")
    if expected:
        raise ValueError("source distribution is missing required files")


def validate_payloads(directory: Path) -> None:
    """Compare module bytes, not merely filenames or source-tree timestamps."""
    runtime = _runtime_payload(directory)
    expected = {name: value for name, value in runtime.items() if name.startswith("civiscribe/")}
    with zipfile.ZipFile(directory / artifact_names()[0]) as wheel:
        modules = {
            name: wheel.read(name) for name in wheel.namelist() if name.startswith("civiscribe/")
        }
        if modules != expected:
            raise ValueError("wheel and custom-node runtime differ")
        metadata_name = f"ccollins_civiscribe-{__version__}.dist-info/METADATA"
        package_metadata = wheel.read(metadata_name)
    _verify_sdist(directory / artifact_names()[1], runtime, package_metadata)
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
    root = scoped_path(destination.parent, destination)
    root.mkdir(parents=True, exist_ok=False)
    for name, payload in runtime.items():
        path = scoped_path(root, root / name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify", "stage"))
    parser.add_argument("--directory", type=Path, default=ROOT / "dist")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument(
        "--list-paths", action="store_true", help="print one verified asset per line"
    )
    parser.add_argument(
        "--attestations", choices=("all", "registry"), help="verify signed provenance"
    )
    parser.add_argument(
        "--working-tree", action="store_true", help="local testing only; not publishable"
    )
    args = parser.parse_args()
    if args.attestations and args.mode != "verify":
        parser.error("--attestations requires verify")
    if args.list_paths and args.mode == "stage":
        parser.error("--list-paths requires prepare or verify")
    if args.mode == "prepare":
        _check_source(args.commit, allow_working_tree=args.working_tree)
        prepare_bundle(args.directory, args.commit, working_tree=args.working_tree)
    elif args.mode == "verify":
        verify_bundle(args.directory, args.commit, allow_working_tree=args.working_tree)
        if args.attestations:
            verify_attestations(
                args.directory, args.commit, registry_only=args.attestations == "registry"
            )
    elif args.destination is None:
        parser.error("stage requires --destination (a new isolated custom-node directory)")
    else:
        stage_node(
            args.directory, args.commit, args.destination, allow_working_tree=args.working_tree
        )
    if args.list_paths:
        for asset in release_assets(args.directory):
            print(asset.as_posix())
    else:
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
