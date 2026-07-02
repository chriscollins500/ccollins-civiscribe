"""Analyze Civitai generator EXIF metadata samples without mutating files."""

from __future__ import annotations

import argparse
import csv
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from save_node.metadata.exif_user_comment import EXIF_IFD_TAG, USER_COMMENT_TAG, decode_user_comment
from save_node.metadata.serialize import to_json_text
from save_node.security.redaction import sanitize_metadata_text
from tools.inspect_png_chunks import parse_user_comment_fields


def analyze_path(path: Path, output_folder: Path | None = None) -> list[dict[str, Any]]:
    source = path.resolve(strict=True)
    records: list[dict[str, Any]] = []
    if source.suffix.lower() == ".zip":
        with ZipFile(source) as archive:
            for name in archive.namelist():
                if name.endswith("/") or not _looks_like_image(name):
                    continue
                records.append(_analyze_image_bytes(name, archive.read(name)))
    else:
        records.append(_analyze_image_bytes(source.name, source.read_bytes()))

    if output_folder is not None:
        output_folder.mkdir(parents=True, exist_ok=True)
        _write_outputs(output_folder, records)
    return records


def _analyze_image_bytes(name: str, data: bytes) -> dict[str, Any]:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise RuntimeError("Pillow is required to analyze Civitai generator metadata") from exc

    with Image.open(BytesIO(data)) as image:
        image.load()
        exif = image.getexif()
        try:
            exif_ifd = exif.get_ifd(EXIF_IFD_TAG)
        except Exception:
            exif_ifd = {}
        text, encoding = decode_user_comment(exif_ifd.get(USER_COMMENT_TAG) or exif.get(USER_COMMENT_TAG))
        fields = parse_user_comment_fields(text)
        resources = _parse_json_field(fields.get("Civitai resources"))
        metadata = _parse_json_field(fields.get("Civitai metadata"))
        return {
            "fileName": Path(name).name,
            "actualFormat": image.format,
            "width": image.width,
            "height": image.height,
            "rootExifTagCount": len(exif),
            "userCommentEncoding": encoding,
            "userCommentLength": len(text),
            "hasPromptText": bool(text and not text.lstrip().startswith("{")),
            "hasSteps": "Steps" in fields,
            "hasSampler": "Sampler" in fields,
            "hasSeed": "Seed" in fields,
            "hasSize": "Size" in fields,
            "hasCivitaiResources": resources is not None,
            "civitaiResourceCount": len(resources) if isinstance(resources, list) else 0,
            "hasCivitaiMetadata": isinstance(metadata, dict),
            "metadataKeys": sorted(metadata.keys()) if isinstance(metadata, dict) else [],
            "preview": sanitize_metadata_text(text[:500]),
        }


def _parse_json_field(value: str | None) -> Any | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _write_outputs(output_folder: Path, records: list[dict[str, Any]]) -> None:
    (output_folder / "civitai_generator_metadata_summary.json").write_text(
        to_json_text({"records": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output_folder / "civitai_generator_metadata_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "fileName",
            "actualFormat",
            "width",
            "height",
            "userCommentEncoding",
            "userCommentLength",
            "hasSteps",
            "hasSampler",
            "hasSeed",
            "hasSize",
            "hasCivitaiResources",
            "civitaiResourceCount",
            "hasCivitaiMetadata",
            "metadataKeys",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key) for key in fieldnames})
    lines = ["# Civitai Generator Metadata Sample Summary", ""]
    for record in records:
        lines.append(f"## {record['fileName']}")
        lines.append("")
        lines.append(f"- Actual format: {record['actualFormat']}")
        lines.append(f"- Size: {record['width']}x{record['height']}")
        lines.append(f"- UserComment encoding: {record['userCommentEncoding']}")
        lines.append(f"- Civitai resources: {record['civitaiResourceCount']}")
        lines.append(f"- Civitai metadata keys: {', '.join(record['metadataKeys'])}")
        lines.append("")
    (output_folder / "civitai_generator_metadata_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _looks_like_image(name: str) -> bool:
    return Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Analyze Civitai generator EXIF metadata samples")
    parser.add_argument("path", type=Path, help="Image file or zip containing image samples")
    parser.add_argument("--output-folder", type=Path, help="Optional folder for markdown/csv/json summaries")
    args = parser.parse_args()
    records = analyze_path(args.path, args.output_folder)
    print(to_json_text({"recordCount": len(records), "records": records[:5]}, indent=2))


if __name__ == "__main__":
    main()
