"""Explicitly regenerate project-authored JPEG/WebP fixtures and their manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from civiscribe.domain import ImageFormat, ImageFrame, ImageRecord
from civiscribe.projections import build_rich_exif_projection
from civiscribe.writers import JpegWriter, WebpWriter
from tests.projection_support import complete_record
from tests.unit.test_image_writer_golden import GOLDEN, _jpeg_source, _webp_source


def main() -> None:
    manifest_path = GOLDEN / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for output_format, relative, pixels, writer in (
        (ImageFormat.JPEG, "jpeg/rich_reference.jpg", _jpeg_source(), JpegWriter()),
        (ImageFormat.WEBP, "webp/rich_rgba_reference.webp", _webp_source(), WebpWriter()),
    ):
        height, width = pixels.shape[:2]
        record = complete_record()
        record = replace(
            record,
            settings=replace(record.settings, width=width, height=height),
            image=ImageRecord(output_format, width, height),
        )
        destination = GOLDEN / relative
        writer.write(ImageFrame(pixels), destination, build_rich_exif_projection(record))
        payload = destination.read_bytes()
        fixture = next(item for item in manifest["fixtures"] if item["path"] == relative)
        fixture["sha256"] = hashlib.sha256(payload).hexdigest()
        fixture["sizeBytes"] = len(payload)
        fixture["expected"]["exifVersion"] = "0232"
        fixture["updateReason"] = (
            "Regenerated from the original synthetic pixels with the current EXIF 2.32 "
            "writer; assert required EXIF fields as well as pixels and generation metadata."
        )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
