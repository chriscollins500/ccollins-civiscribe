from __future__ import annotations

import json
import multiprocessing
import os
from multiprocessing.connection import Connection
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from civiscribe.domain import ImageFormat, ImageFrame
from civiscribe.identity.cache_store import BoundedJsonCache
from civiscribe.orchestration import SaveRequest, save_image_batch
from civiscribe.storage.sidecar import write_sidecar_json

pytestmark = pytest.mark.release


def _checkpoint(channel: Connection) -> None:
    channel.send("ready")
    channel.recv()


def _worker(directory: Path, operation: str, after: bool, channel: Connection) -> None:
    if operation == "cache":
        replace = Path.replace

        def replace_at_boundary(source: Path, target: Path) -> Path:
            if not after:
                _checkpoint(channel)
            result = replace(source, target)
            if after:
                _checkpoint(channel)
            return result

        with patch.object(Path, "replace", replace_at_boundary):
            BoundedJsonCache(directory / "cache.json", schema_name="crash-test").merge(
                {"cacheKey": "new", "value": 2}
            )
    else:
        link = os.link

        def link_at_boundary(source: Path, target: Path) -> None:
            if not after:
                _checkpoint(channel)
            link(source, target)
            if after:
                _checkpoint(channel)

        with patch.object(os, "link", link_at_boundary):
            if operation == "sidecar":
                write_sidecar_json(directory / "original.json", '{"committed":true}')
            else:
                save_image_batch(_request(directory, ImageFormat(operation)))


def _request(directory: Path, image_format: ImageFormat) -> SaveRequest:
    return SaveRequest(
        images=(ImageFrame(np.full((8, 8, 3), 0.5, dtype=np.float32)),),
        output_root=directory,
        filename_prefix="crash",
        output_format=image_format,
    )


@pytest.mark.parametrize("operation", ["cache", "sidecar", "png", "jpeg", "webp"])
@pytest.mark.parametrize("after", [False, True])
def test_kill_at_publication_preserves_commits_and_allows_next_save(
    tmp_path: Path, operation: str, after: bool
) -> None:
    cache = BoundedJsonCache(tmp_path / "cache.json", schema_name="crash-test")
    assert cache.merge({"cacheKey": "old", "value": 1}).written
    original = tmp_path / "original.png"
    Image.new("RGB", (8, 8), (17, 23, 41)).save(original)
    original_bytes = original.read_bytes()
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_worker, args=(tmp_path, operation, after, child))
    process.start()
    child.close()
    try:
        assert parent.poll(30), "worker failed to reach the selected publication boundary"
        assert parent.recv() == "ready"
    finally:
        process.kill()
        process.join(timeout=15)
        parent.close()
    assert not process.is_alive()
    assert original.read_bytes() == original_bytes
    assert cache.read().records[0]["cacheKey"] in {"old", "new"}
    assert cache.merge({"cacheKey": "recovered", "value": 3}).written
    if (tmp_path / "original.json").exists():
        assert json.loads((tmp_path / "original.json").read_text()) == {"committed": True}
    committed = {path: path.read_bytes() for path in tmp_path.glob("crash_*")}
    for path in committed:
        with Image.open(path) as image:
            image.load()
    outcome = save_image_batch(_request(tmp_path, ImageFormat.PNG))
    assert len(outcome.saved_images) == 1
    assert all(path.read_bytes() == data for path, data in committed.items())
