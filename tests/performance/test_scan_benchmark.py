from __future__ import annotations

import json
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from civiscribe.workflow import scan_workflow

pytestmark = pytest.mark.performance


def test_scan_benchmark(benchmark: Any) -> None:  # noqa: ANN401
    fixture = Path(__file__).resolve().parents[1] / "fixtures/workflows/basic_checkpoint.json"
    prompt = json.loads(fixture.read_text(encoding="utf-8"))["prompt"]
    result = benchmark(scan_workflow, prompt, save_node_id="7")
    assert result.prompts.positive.text == "a lighthouse at dawn"


def test_scan_python_allocation_plateau(record_property: Any) -> None:  # noqa: ANN401
    fixture = Path(__file__).resolve().parents[1] / "fixtures/workflows/basic_checkpoint.json"
    prompt = json.loads(fixture.read_text(encoding="utf-8"))["prompt"]
    tracemalloc.start()
    try:
        for _ in range(100):
            scan_workflow(prompt, save_node_id="7")
        current, peak = tracemalloc.get_traced_memory()
        record_property("retained_bytes", current)
        record_property("peak_bytes", peak)
        assert peak > 0
    finally:
        tracemalloc.stop()
