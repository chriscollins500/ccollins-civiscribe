from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from civiscribe.domain import (
    Diagnostics,
    HashRecord,
    ImageFormat,
    IssueSeverity,
    LookupStatus,
    ResourceStatus,
    ScanIssue,
)
from civiscribe.domain.identity import LookupDiagnostics
from civiscribe.projections import (
    SidecarArtifact,
    SidecarPolicy,
    build_sidecar_projection,
)
from tests.projection_support import complete_record, model_resource
from tools.validate_sidecar import validate_sidecar

HASH_NAMES = {"AutoV1", "AutoV2", "AutoV3", "SHA256", "CRC32", "BLAKE3"}
EXPECTED_REDACTIONS = 2


def _artifact(**changes: object) -> SidecarArtifact:
    values: dict[str, object] = {
        "filename": "image_00001_.png",
        "sidecar_filename": "image_00001_.json",
        "subfolder": "",
        "output_format": ImageFormat.PNG,
        "width": 1024,
        "height": 768,
        "batch_index": 0,
        "mode": "RGB",
        "channels": 3,
        "incoming_tensor_dtype": "float32",
        "encoded_sample_bits": 8,
        "file_size_bytes": 1234,
        "metadata_status": "complete",
    }
    values.update(changes)
    return SidecarArtifact(**values)  # type: ignore[arg-type]


def _write_projection(path: Path, projection_text: str) -> None:
    path.write_text(projection_text, encoding="utf-8", newline="")


def test_complete_projection_is_deterministic_schema_valid_and_null_explicit(
    tmp_path: Path,
) -> None:
    policy = SidecarPolicy(
        prompt={"payloadMarker": "prompt-payload-only"},
        workflow={"payloadMarker": "workflow-payload-only"},
    )
    first = build_sidecar_projection(complete_record(), _artifact(), policy)
    second = build_sidecar_projection(complete_record(), _artifact(), policy)
    assert first == second
    assert first.json_text == json.dumps(
        first.payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert first.json_text.count("prompt-payload-only") == 1
    assert first.json_text.count("workflow-payload-only") == 1

    generation = cast(dict[str, object], first.payload["generationRecord"])
    resources = cast(list[object], generation["resources"])
    resource = cast(dict[str, object], resources[0])
    hashes = cast(dict[str, object], resource["hashes"])
    assert set(hashes) == HASH_NAMES
    assert hashes["AutoV1"] == "1234abcd"
    assert hashes["SHA256"] is not None
    vae_resource = cast(dict[str, object], resources[-1])
    vae_hashes = cast(dict[str, object], vae_resource["hashes"])
    assert vae_hashes["AutoV1"] is None
    artifact = cast(dict[str, object], first.payload["artifact"])
    assert artifact["declaredSourceBitDepth"] is None
    assert artifact["measuredEffectiveBitDepth"] is None

    path = tmp_path / "image_00001_.json"
    _write_projection(path, first.json_text)
    assert validate_sidecar(path).valid


def test_minimal_projection_keeps_unknowns_null_and_omits_optional_projections(
    tmp_path: Path,
) -> None:
    projection = build_sidecar_projection(
        None,
        _artifact(metadata_status="minimal"),
    )
    assert projection.payload["generationRecord"] is None
    assert projection.payload["payloads"] == {"prompt": None, "workflow": None}
    assert projection.payload["projections"] == {
        "parameters": None,
        "civitai": None,
    }
    assert projection.warning_codes == ()

    path = tmp_path / "image_00001_.json"
    _write_projection(path, projection.json_text)
    assert validate_sidecar(path).valid


def test_policy_controls_workflow_manifest_and_deduplicates_save_warnings() -> None:
    projection = build_sidecar_projection(
        complete_record(),
        _artifact(),
        SidecarPolicy(
            prompt={"known": True},
            workflow={"secretWorkflowMarker": True},
            include_workflow=False,
            include_civitai_manifest=False,
            save_warnings=(
                ("metadata_reduced_fallback_used", 0),
                ("metadata_reduced_fallback_used", 0),
                ("global_warning", None),
            ),
        ),
    )
    assert projection.payload["payloads"] == {"prompt": {"known": True}, "workflow": None}
    assert cast(dict[str, object], projection.payload["projections"])["civitai"] is None
    save = cast(dict[str, object], projection.payload["save"])
    assert save["warnings"] == [
        {"code": "metadata_reduced_fallback_used", "batchIndex": 0},
        {"code": "global_warning", "batchIndex": None},
    ]
    assert "secretWorkflowMarker" not in projection.json_text


def test_payload_redaction_is_reported_without_leaking_private_values(
    tmp_path: Path,
) -> None:
    projection = build_sidecar_projection(
        complete_record(),
        _artifact(),
        SidecarPolicy(
            prompt={
                "authorization": "Bearer abcdefghijk",
                "path": r"C:\Users\Person\private\model.safetensors",
            },
        ),
    )
    assert projection.warning_codes == ("sidecar_payload_private_values_redacted",)
    assert "abcdefghijk" not in projection.json_text
    assert "C:\\\\Users" not in projection.json_text
    save = cast(dict[str, object], projection.payload["save"])
    assert save["payloadRedactionCount"] == EXPECTED_REDACTIONS
    assert save["warnings"] == [
        {"code": "sidecar_payload_private_values_redacted", "batchIndex": None}
    ]

    path = tmp_path / "image_00001_.json"
    _write_projection(path, projection.json_text)
    assert validate_sidecar(path).valid


def test_unresolved_resource_keeps_all_hash_names_and_diagnostics(
    tmp_path: Path,
) -> None:
    resource = replace(
        model_resource(),
        hashes=HashRecord(),
        identity=None,
        status=ResourceStatus.UNRESOLVED,
        lookup_status=LookupStatus.FAILED,
        lookup_diagnostics=LookupDiagnostics(
            attempted_hash_types=("SHA256",),
            reason="no_hash_match",
            http_status=404,
            retryable=False,
            tls_source="system_default",
            candidate_count=0,
            compatible_candidate_count=0,
        ),
        unresolved_reason="hashed_but_no_civitai_identity",
    )
    record = replace(
        complete_record(),
        resources=(resource,),
        diagnostics=Diagnostics(
            warnings=(ScanIssue("safe_warning", node_id="1"),),
            errors=(
                ScanIssue(
                    "safe_error",
                    severity=IssueSeverity.ERROR,
                    input_name="model",
                ),
            ),
        ),
    )
    projection = build_sidecar_projection(record, _artifact(metadata_status="partial"))
    generation = cast(dict[str, object], projection.payload["generationRecord"])
    projected_resource = cast(dict[str, object], cast(list[object], generation["resources"])[0])
    assert projected_resource["hashes"] == dict.fromkeys(HASH_NAMES)
    assert projected_resource["identity"] is None
    assert projected_resource["resolved"] is False
    assert projected_resource["lookupDiagnostics"] == {
        "status": "failed",
        "attemptedHashTypes": ["SHA256"],
        "reason": "no_hash_match",
        "httpStatus": 404,
        "retryable": False,
        "retryAfterSeconds": None,
        "tlsSource": "system_default",
        "candidateCount": 0,
        "compatibleCandidateCount": 0,
    }
    diagnostics = cast(dict[str, object], generation["diagnostics"])
    assert diagnostics == {
        "warnings": [
            {
                "code": "safe_warning",
                "severity": "warning",
                "nodeId": "1",
                "inputName": None,
            }
        ],
        "errors": [
            {
                "code": "safe_error",
                "severity": "error",
                "nodeId": None,
                "inputName": "model",
            }
        ],
    }
    path = tmp_path / "image_00001_.json"
    _write_projection(path, projection.json_text)
    assert validate_sidecar(path).valid


@pytest.mark.parametrize(
    "changes",
    [
        {"filename": ""},
        {"filename": "."},
        {"filename": "folder/image.png"},
        {"sidecar_filename": r"folder\image.json"},
        {"filename": "image_00001_.jpg"},
        {"sidecar_filename": "different.json"},
        {"sidecar_filename": "image_00001_.txt"},
        {"subfolder": "../private"},
        {"subfolder": "C:/private"},
        {"width": 0},
        {"height": 0},
        {"batch_index": -1},
        {"channels": 2},
        {"encoded_sample_bits": 0},
        {"file_size_bytes": 0},
        {"metadata_status": "failed"},
    ],
)
def test_artifact_rejects_invalid_or_private_facts(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _artifact(**changes)
