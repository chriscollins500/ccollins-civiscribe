from __future__ import annotations

import json
from dataclasses import replace

from civiscribe.domain import (
    Diagnostics,
    HashRecord,
    IdentitySource,
    IssueSeverity,
    ResourceIdentity,
    ResourceStatus,
    ScanIssue,
)
from civiscribe.projections import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    build_civitai_manifest,
    build_civitai_manifest_json,
    build_projection_bundle,
)
from tests.projection_support import (
    CFG_SCALE,
    DENOISE,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    complete_record,
    model_resource,
    vae_resource,
)

RESOURCE_COUNT = 4
CONFLICT_WARNING_COUNT = 2


def test_complete_manifest_contains_shared_generation_and_resource_facts() -> None:
    record = complete_record()

    manifest = build_civitai_manifest(record)

    assert manifest["schemaName"] == SCHEMA_NAME
    assert manifest["schemaVersion"] == SCHEMA_VERSION
    assert manifest["metadataStatus"] == "complete"
    assert manifest["generator"] == {
        "name": "CCollins' CiviScribe",
        "version": record.generator.version,
        "comfyuiVersion": "0.3.50",
    }
    assert manifest["prompt"] == {
        "positive": "portrait of café 雪\ncinematic light",
        "negative": "low quality, watermark",
        "positiveBranchPresent": True,
        "negativeBranchPresent": True,
    }
    generation = manifest["generation"]
    assert isinstance(generation, dict)
    assert generation["workflowType"] == "txt2img"
    assert generation["sampler"] == "DPM++ 2M"
    assert generation["scheduler"] == "Karras"
    assert generation["cfgScale"] == CFG_SCALE
    assert generation["guidance"] is None
    assert generation["denoise"] is None
    assert generation["width"] == IMAGE_WIDTH
    assert generation["height"] == IMAGE_HEIGHT
    assert generation["model"] == "swiftFastAndDetailed_neo.gguf"
    assert generation["vae"] == "ae.safetensors"
    assert manifest["unresolvedResources"] == []
    resources = manifest["resources"]
    civitai_resources = manifest["civitaiResources"]
    assert isinstance(resources, list)
    assert isinstance(civitai_resources, list)
    assert len(resources) == RESOURCE_COUNT
    assert len(civitai_resources) == RESOURCE_COUNT
    assert manifest["workflowRefs"] == {
        "prompt": "pnginfo:prompt",
        "workflow": "pnginfo:workflow",
    }
    assert manifest["validation"] == {"warnings": [], "errors": []}


def test_bundle_serializes_the_exact_manifest_object_deterministically() -> None:
    bundle = build_projection_bundle(complete_record())

    assert json.loads(bundle.civitai_manifest_json) == bundle.civitai_manifest
    assert bundle.civitai_manifest_json == build_civitai_manifest_json(complete_record())
    assert bundle.a1111_parameters
    assert "雪" in bundle.civitai_manifest_json
    assert "\\u96ea" not in bundle.civitai_manifest_json


def test_unresolved_resource_is_structured_but_not_parser_facing() -> None:
    unresolved = replace(
        model_resource(),
        identity=None,
        status=ResourceStatus.UNRESOLVED,
        unresolved_reason="hashed_but_no_civitai_identity",
    )
    record = replace(
        complete_record(),
        resources=(unresolved,),
        primary_resource_key=unresolved.key,
        selected_vae_resource_key=None,
    )

    manifest = build_civitai_manifest(record)

    assert manifest["metadataStatus"] == "partial"
    assert manifest["civitaiResources"] == []
    assert manifest["resources"] == manifest["unresolvedResources"]
    validation = manifest["validation"]
    assert isinstance(validation, dict)
    assert validation["warnings"] == [
        {
            "code": "resource_identity_incomplete",
            "severity": "warning",
            "nodeId": "1",
        }
    ]


def test_manifest_reports_projection_errors_conflicts_and_malformed_hashes_once() -> None:
    resolved_without_identity = replace(
        model_resource(),
        identity=None,
        hashes=HashRecord(auto_v2="bad"),
    )
    conflict = replace(
        vae_resource(),
        status=ResourceStatus.CONFLICT,
    )
    partial = replace(
        model_resource(),
        key="9:model",
        node_id="9",
        status=ResourceStatus.PARTIAL,
        identity=ResourceIdentity(
            source=IdentitySource.MANUAL,
            resource_type="checkpoint",
            model_version_id=9,
        ),
    )
    duplicate = ScanIssue(
        "resource_identity_conflict",
        node_id="5",
        input_name="vae",
    )
    record = replace(
        complete_record(),
        resources=(resolved_without_identity, conflict, partial),
        primary_resource_key="missing",
        selected_vae_resource_key="also-missing",
        diagnostics=Diagnostics(warnings=(duplicate, duplicate)),
    )

    manifest = build_civitai_manifest(record)
    validation = manifest["validation"]
    assert isinstance(validation, dict)
    warnings = validation["warnings"]
    assert isinstance(warnings, list)
    warning_codes = [item["code"] for item in warnings]

    assert manifest["metadataStatus"] == "partial"
    assert warning_codes.count("resource_identity_conflict") == CONFLICT_WARNING_COUNT
    assert {
        "primary_resource_key_invalid",
        "selected_vae_resource_key_invalid",
        "resolved_resource_identity_missing",
        "resource_hashes_invalid",
        "resource_identity_conflict",
        "resource_identity_incomplete",
    } <= set(warning_codes)
    assert {
        "code": "resource_identity_conflict",
        "severity": "warning",
        "nodeId": "5",
        "inputName": "vae",
    } in warnings


def test_error_diagnostic_marks_manifest_failed_and_is_sanitized() -> None:
    error = ScanIssue(
        "schema,error\nunsafe",
        IssueSeverity.ERROR,
        node_id="node,\n1",
        input_name="input,\nname",
    )
    record = replace(
        complete_record(),
        diagnostics=Diagnostics(errors=(error,)),
    )

    manifest = build_civitai_manifest(record)
    validation = manifest["validation"]
    assert isinstance(validation, dict)

    assert manifest["metadataStatus"] == "failed"
    assert validation["errors"] == [
        {
            "code": "schema;error unsafe",
            "severity": "error",
            "nodeId": "node; 1",
            "inputName": "input; name",
        }
    ]


def test_unknown_workflow_and_missing_selected_resources_remain_null() -> None:
    record = replace(
        complete_record(),
        workflow_kind=None,
        resources=(),
        primary_resource_key=None,
        selected_vae_resource_key=None,
    )

    manifest = build_civitai_manifest(record)
    generation = manifest["generation"]
    assert isinstance(generation, dict)

    assert generation["workflowType"] is None
    assert generation["denoise"] is None
    assert generation["model"] is None
    assert generation["modelHash"] is None
    assert generation["vae"] is None
    assert generation["vaeHash"] is None
    assert manifest["metadataStatus"] == "complete"


def test_img2img_manifest_includes_truthful_denoise() -> None:
    record = complete_record()
    record = replace(
        record,
        workflow_kind=record.workflow_kind.IMG2IMG if record.workflow_kind is not None else None,
    )

    manifest = build_civitai_manifest(record)
    generation = manifest["generation"]
    assert isinstance(generation, dict)

    assert generation["workflowType"] == "img2img"
    assert generation["denoise"] == DENOISE


def test_inactive_resource_is_not_in_any_civitai_facing_list() -> None:
    inactive = replace(model_resource(), active=False)
    record = replace(
        complete_record(),
        resources=(inactive,),
        primary_resource_key=None,
        selected_vae_resource_key=None,
    )

    manifest = build_civitai_manifest(record)

    assert manifest["resources"] == []
    assert manifest["unresolvedResources"] == []
    assert manifest["civitaiResources"] == []
    assert manifest["hashes"] == {}


def test_manifest_never_exposes_absolute_resource_paths() -> None:
    resource = replace(
        model_resource(),
        filename=r"C:\Users\person\private\model.gguf",
        selected_value="/home/person/private/model.gguf",
    )
    record = replace(
        complete_record(),
        resources=(resource,),
        primary_resource_key=resource.key,
        selected_vae_resource_key=None,
    )

    encoded = build_civitai_manifest_json(record)

    assert "C:" not in encoded
    assert "/home/" not in encoded
    assert "Users" not in encoded
    assert '"filename":"model.gguf"' in encoded
