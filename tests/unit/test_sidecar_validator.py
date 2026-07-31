from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

import pytest

from civiscribe.domain import ImageFormat
from civiscribe.projections import SidecarArtifact, build_sidecar_projection
from tests.projection_support import complete_record
from tools import validate_sidecar as validator_tool
from tools.validate_sidecar import validate_sidecar


def _projection_payload() -> dict[str, object]:
    return build_sidecar_projection(
        complete_record(),
        SidecarArtifact(
            filename="image_00001_.png",
            sidecar_filename="image_00001_.json",
            subfolder="",
            output_format=ImageFormat.PNG,
            width=1024,
            height=768,
            batch_index=0,
            mode="RGB",
            channels=3,
            incoming_tensor_dtype="float32",
            encoded_sample_bits=8,
            file_size_bytes=1234,
            metadata_status="complete",
        ),
    ).payload


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
        newline="",
    )


def test_validator_accepts_projected_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "image_00001_.json"
    _write_json(path, _projection_payload())
    assert validate_sidecar(path).valid
    assert validate_sidecar(path).errors == ()


def test_validator_rejects_duplicate_keys_and_malformed_json(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schemaName":"one","schemaName":"two"}', encoding="utf-8")
    assert validate_sidecar(duplicate).errors == ("sidecar_unreadable:ValueError",)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert validate_sidecar(malformed).errors == ("sidecar_unreadable:JSONDecodeError",)
    assert validate_sidecar(tmp_path / "missing.json").errors == (
        "sidecar_unreadable:FileNotFoundError",
    )


def test_validator_reports_schema_loading_and_definition_errors(tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecar.json"
    _write_json(sidecar, _projection_payload())
    assert validate_sidecar(
        sidecar,
        schema_path=tmp_path / "missing-schema.json",
    ).errors == ("schema_unreadable:FileNotFoundError",)

    scalar_schema = tmp_path / "scalar-schema.json"
    _write_json(scalar_schema, [])
    assert validate_sidecar(sidecar, schema_path=scalar_schema).errors == ("schema:not_object",)

    invalid_schema = tmp_path / "invalid-schema.json"
    _write_json(invalid_schema, {"type": "not-a-json-schema-type"})
    assert validate_sidecar(sidecar, schema_path=invalid_schema).errors == (
        "schema:definition_invalid",
    )


def test_validator_reports_schema_and_semantic_mismatches_without_values(
    tmp_path: Path,
) -> None:
    payload = _projection_payload()
    artifact = cast(dict[str, object], payload["artifact"])
    artifact.pop("width")
    path = tmp_path / "invalid.json"
    _write_json(path, payload)
    result = validate_sidecar(path)
    assert result.errors == (
        "schema:artifact:required",
        "semantic:generation_image_mismatch",
    )


def test_validator_detects_private_values_without_echoing_them(tmp_path: Path) -> None:
    payload = _projection_payload()
    payloads = cast(dict[str, object], payload["payloads"])
    payloads["prompt"] = {
        "authorization": {"raw": "private"},
        "bearer": "Bearer abcdefghijk",
        "path": r"C:\Users\Person\private\model.safetensors",
    }
    path = tmp_path / "private.json"
    _write_json(path, payload)
    result = validate_sidecar(path)
    assert result.errors == (
        "privacy:absolute_path",
        "privacy:bearer_secret",
        "privacy:sensitive_value",
    )
    assert "Person" not in repr(result)
    assert "abcdefghijk" not in repr(result)


def test_validator_detects_artifact_consistency_failures(tmp_path: Path) -> None:
    payload = _projection_payload()
    artifact = cast(dict[str, object], payload["artifact"])
    artifact.update(
        {
            "fileName": "image_00001_.jpg",
            "sidecarFileName": "different.json",
            "mimeType": "image/webp",
            "mode": "RGBA",
            "channels": 3,
            "hasAlpha": False,
        }
    )
    path = tmp_path / "inconsistent.json"
    _write_json(path, payload)
    result = validate_sidecar(path)
    assert "semantic:artifact_format_mismatch" in result.errors
    assert "semantic:artifact_mode_mismatch" in result.errors
    assert "semantic:sidecar_filename_mismatch" in result.errors


@pytest.mark.parametrize(
    "subfolder",
    [
        "../private",
        "safe/../private",
        "/absolute",
        "trailing/",
        "double//separator",
        r"windows\separator",
        "C:drive",
    ],
)
def test_validator_rejects_unsafe_artifact_subfolder(
    tmp_path: Path,
    subfolder: str,
) -> None:
    payload = _projection_payload()
    artifact = cast(dict[str, object], payload["artifact"])
    artifact["subfolder"] = subfolder
    path = tmp_path / "unsafe-subfolder.json"
    _write_json(path, payload)

    result = validate_sidecar(path)

    assert "semantic:subfolder_unsafe" in result.errors


def test_validator_cli_returns_machine_readable_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "image_00001_.json"
    _write_json(path, _projection_payload())
    monkeypatch.setattr(sys, "argv", ["validate_sidecar.py", str(path)])
    assert validator_tool.main() == 0
    assert json.loads(capsys.readouterr().out) == {"errors": [], "valid": True}
