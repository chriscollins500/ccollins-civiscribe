"""Publish the verified Registry ZIP without letting comfy-cli rebuild it."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from civiscribe.tls import create_tls_contexts
from tools.release_bundle import ROOT, artifact_names, verify_bundle
from tools.verify_registry_listing import load_project_registry_metadata


def publish(directory: Path, commit: str, changelog: Path) -> None:
    """All local checks precede the immutable version-creation request."""
    verify_bundle(directory, commit)
    metadata = load_project_registry_metadata()
    notes = changelog.read_text(encoding="utf-8").strip()
    token = os.environ.get("REGISTRY_ACCESS_TOKEN", "").strip()
    if not notes or not token:
        raise ValueError("release notes and Registry token are required")
    # The pinned official CLI owns the Registry request schema, not this adapter.
    from comfy_cli.registry import (  # type: ignore[import-not-found]  # noqa: PLC0415
        RegistryAPI,
        extract_node_configuration,
    )

    config = extract_node_configuration(str(ROOT / "pyproject.toml"))
    api = RegistryAPI()
    if (
        config is None
        or api.base_url != "https://api.comfy.org"
        or config.project.version != metadata.version
    ):
        raise ValueError("Registry target or release version mismatch")
    response = api.publish_node_version(config, token, changelog=notes)
    target = urlsplit(response.signedUrl)
    if target.scheme != "https" or not target.hostname or target.username or target.password:
        raise ValueError("Registry returned an invalid HTTPS upload destination")
    archive = directory / artifact_names()[3]
    with (
        httpx.Client(verify=create_tls_contexts()[0][1], timeout=120.0) as client,
        archive.open("rb") as payload,
    ):
        result = client.put(
            response.signedUrl,
            content=payload,
            headers={"Content-Type": "application/zip"},
        )
        result.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "dist")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--changelog", type=Path, required=True)
    args = parser.parse_args()
    try:
        publish(args.directory, args.commit, args.changelog)
    except Exception as error:
        # HTTP errors can contain signed URLs or server-echoed credentials.
        print(
            f"Registry publication failed ({type(error).__name__}); no automatic retry",
            file=sys.stderr,
        )
        return 1
    print("Verified Registry archive uploaded unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
