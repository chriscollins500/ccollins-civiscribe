from __future__ import annotations

import json
from pathlib import Path

from tools.validate_golden_manifest import validate_manifest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "golden" / "manifest.json"
INITIAL_FIXTURE_COUNT = 7


def test_initial_png_manifest_is_valid() -> None:
    result = validate_manifest(MANIFEST)
    assert result.valid
    assert result.fixture_count == INITIAL_FIXTURE_COUNT
    assert result.errors == ()


def test_manifest_rejects_traversal_without_reading_outside_fixture_root(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schemaName": "ccollins-civiscribe.golden-manifest",
                "schemaVersion": "1.0.0",
                "fixtures": [
                    {
                        "id": "unsafe",
                        "path": "../private.png",
                        "sizeBytes": 0,
                        "sha256": "0" * 64,
                        "sourceClass": "synthetic",
                        "licenseOrConsent": "Project-authored synthetic fixture.",
                        "expected": {},
                        "byteEqualityContract": False,
                        "updateReason": "Negative traversal test.",
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = validate_manifest(path)
    assert not result.valid
    assert "fixture_0:path_invalid" in result.errors
