"""Exercise an installed package with synthetic images; never use private user media."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

import civiscribe
from civiscribe.domain import ImageFormat, ImageFrame
from civiscribe.orchestration import MetadataRequest, SaveRequest, save_image_batch


def generate(output: Path) -> None:
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/workflows/basic_checkpoint.json"
    prompt = json.loads(fixture.read_text(encoding="utf-8"))["prompt"]
    pixels = np.arange(16 * 24 * 3, dtype=np.uint16).reshape(16, 24, 3).astype(np.uint8)
    frame = ImageFrame(pixels.astype(np.float32) / 255.0)
    for image_format in ImageFormat:
        for workflow in (True, False):
            outcome = save_image_batch(
                SaveRequest(
                    images=(frame,),
                    output_root=output,
                    filename_prefix=f"{image_format.value}_{workflow}",
                    output_format=image_format,
                    write_sidecar_json=True,
                    metadata=MetadataRequest(
                        prompt=prompt,
                        save_node_id="7",
                        positive_prompt_override="Synthetic release validation pattern",
                        negative_prompt_override="synthetic negative prompt",
                        workflow={"nodes": []},
                        include_workflow=workflow,
                    ),
                )
            )
            saved = outcome.saved_images[0]
            if outcome.warnings or saved.sidecar_filename is None:
                raise RuntimeError("release corpus did not save full image and sidecar")
            with Image.open(output / saved.filename) as image:
                image.load()
                if image.size != (24, 16):
                    raise RuntimeError("saved dimensions changed")
                if image_format != ImageFormat.JPEG and not np.array_equal(
                    np.asarray(image), pixels
                ):
                    raise RuntimeError("lossless saved samples changed")
    print(json.dumps({"version": civiscribe.__version__, "images": 6, "passed": True}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-installed", action="store_true")
    parser.add_argument("--package-root", type=Path)
    args = parser.parse_args()
    if args.require_installed and "site-packages" not in Path(civiscribe.__file__).parts:
        raise RuntimeError("smoke test imported source instead of the installed distribution")
    if args.package_root and not Path(civiscribe.__file__).resolve().is_relative_to(
        args.package_root.resolve()
    ):
        raise RuntimeError("smoke test imported a different package than the staged custom node")
    generate(args.output)


if __name__ == "__main__":
    main()
