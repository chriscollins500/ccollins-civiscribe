from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
from typing import cast

import pytest

from tests.wheel_checker_support import (
    PROJECT_ROOT,
    prepare_probe_tree,
    run_checker,
    wheel_probes,
    write_probe,
)

CONTRACT = cast(
    dict[str, object],
    json.loads(
        (PROJECT_ROOT / "tests/fixtures/wheel-checker/contract.json").read_text(encoding="utf-8")
    ),
)
OUTCOMES = cast(dict[str, dict[str, object]], CONTRACT["outcomes"])


@pytest.mark.parametrize("case_name", tuple(OUTCOMES))
def test_checker_preserves_baseline_wheel_validation(tmp_path: Path, case_name: str) -> None:
    probes = {probe.name: probe for probe in prepare_probe_tree(tmp_path)}
    probe = probes[case_name]
    result = run_checker(write_probe(tmp_path, probe), probe.arguments)
    assert result.as_dict() == OUTCOMES[case_name]


def test_wheel_probe_inventory_covers_every_checker_rule() -> None:
    probes = wheel_probes(Path("source/wheel_probe"))
    assert {probe.name for probe in probes} == set(OUTCOMES)
    assert {
        probe.expected for probe in probes if probe.expected and probe.expected.startswith("W")
    } == {
        *(f"W{index:03d}" for index in range(1, 11)),
        "W101",
        "W102",
        "W201",
        "W202",
    }


def test_installed_wheel_checker_has_the_reviewed_source_and_parser() -> None:
    distribution = importlib.metadata.distribution("check-wheel-contents")
    source = json.loads(distribution.read_text("direct_url.json") or "{}")
    upstream = cast(dict[str, str], CONTRACT["reviewedUpstream"])
    assert distribution.version == upstream["version"]
    assert source["url"] == upstream["repository"]
    assert source["vcs_info"]["vcs"] == "git"
    assert source["vcs_info"]["commit_id"] == upstream["commit"]
    assert importlib.metadata.version("wheel-filename") == upstream["wheelFilename"]
