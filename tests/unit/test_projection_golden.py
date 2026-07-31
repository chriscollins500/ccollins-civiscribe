from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

from civiscribe.projections import build_projection_bundle
from tests.projection_support import complete_record

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "projections" / "complete_record_v1.json"
type GoldenSection = dict[str, str | int]
type GoldenContract = dict[str, str | GoldenSection]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_complete_projection_matches_immutable_golden_contract() -> None:
    contract = cast(GoldenContract, json.loads(GOLDEN.read_text(encoding="utf-8")))
    a1111 = cast(GoldenSection, contract["a1111"])
    manifest = cast(GoldenSection, contract["manifest"])
    bundle = build_projection_bundle(complete_record())

    assert len(bundle.a1111_parameters.encode()) == a1111["utf8Bytes"]
    assert _sha256(bundle.a1111_parameters) == a1111["sha256"]
    assert len(bundle.civitai_manifest_json.encode()) == manifest["utf8Bytes"]
    assert _sha256(bundle.civitai_manifest_json) == manifest["sha256"]
    assert bundle.civitai_manifest["schemaName"] == manifest["schemaName"]
    assert bundle.civitai_manifest["schemaVersion"] == manifest["schemaVersion"]
