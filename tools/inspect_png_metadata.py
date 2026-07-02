"""Inspect metadata written by Save Image with Civitai Metadata."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from save_node.metadata.exif_user_comment import EXIF_IFD_TAG, USER_COMMENT_TAG, decode_user_comment

_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\[^\\/\s]+[\\/][^\\/\s]+")
_POSIX_PATH_RE = re.compile(r"(?<![\w:/])/[^\s\"'<>]+")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Inspect Civitai metadata in a saved PNG")
    parser.add_argument("png", type=Path, help="Path to a PNG file")
    parser.add_argument("--parameters-chars", type=int, default=600)
    args = parser.parse_args()

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - manual helper
        raise SystemExit("Pillow is required to inspect PNG metadata") from exc

    with Image.open(args.png) as image:
        info = dict(image.info)
        exif = image.getexif()
        try:
            exif_ifd = exif.get_ifd(EXIF_IFD_TAG)
        except Exception:
            exif_ifd = {}
        exif_text, exif_encoding = decode_user_comment(exif_ifd.get(USER_COMMENT_TAG) or exif.get(USER_COMMENT_TAG))

    print("PNG metadata keys:")
    for key in sorted(info):
        print(f"- {key}")

    parameters = info.get("parameters", "")
    if parameters:
        print("\nparameters preview:")
        print(parameters[: args.parameters_chars])

    if exif_text:
        print("\nEXIF UserComment:")
        print(f"- encoding: {exif_encoding}")
        print(f"- decodedLength: {len(exif_text)}")
        print(exif_text[: args.parameters_chars])

    manifest = _parse_manifest(info.get("civitai"))
    if manifest:
        resources = manifest.get("resources") or []
        unresolved = manifest.get("unresolvedResources") or []
        print("\ncivitai manifest:")
        print(f"- schema: {manifest.get('schemaName')} {manifest.get('schemaVersion')}")
        print(f"- resources: {len(resources)}")
        print(f"- unresolvedResources: {len(unresolved)}")
        for index, resource in enumerate(resources[:10]):
            print(
                f"  {index + 1}. role={resource.get('role')} type={resource.get('type')} "
                f"name={resource.get('name') or resource.get('filename')} "
                f"resolved={resource.get('resolved')}"
            )

    combined = "\n".join([*(str(value) for value in info.values()), exif_text])
    path_hits = _path_hits(combined)
    print("\nprivacy scan:")
    if path_hits:
        print("- possible absolute path text found")
        for hit in path_hits[:10]:
            print(f"  {hit}")
    else:
        print("- no obvious absolute path text found")

    return 0


def _parse_manifest(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        print("\ncivitai manifest: invalid JSON")
        return None
    return parsed if isinstance(parsed, dict) else None


def _path_hits(value: str) -> list[str]:
    hits: list[str] = []
    for pattern in (_WINDOWS_PATH_RE, _UNC_PATH_RE, _POSIX_PATH_RE):
        hits.extend(match.group(0) for match in pattern.finditer(value))
    return sorted(set(hits))


if __name__ == "__main__":
    raise SystemExit(main())
