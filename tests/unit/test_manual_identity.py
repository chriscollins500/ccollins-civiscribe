from __future__ import annotations

import json
from dataclasses import replace

from civiscribe.domain import (
    HashRecord,
    IdentitySource,
    ResourceIdentity,
    ResourceKind,
    ResourceRecord,
    ResourceRole,
    ResourceStatus,
)
from civiscribe.identity import manual as manual_module
from civiscribe.identity.manual import apply_explicit_identities
from tests.projection_support import MODEL_ID, MODEL_VERSION_ID, model_resource

MANUAL_AIR = "urn:air:flux2:checkpoint:civitai:10@20+30.safetensor"
PREFERRED_AIR = "urn:air:flux2:checkpoint:civitai:40@50"
PREFERRED_MODEL_ID = 40
PREFERRED_VERSION_ID = 50


def _unresolved_model() -> ResourceRecord:
    return replace(
        model_resource(),
        identity=None,
        status=ResourceStatus.UNRESOLVED,
        unresolved_reason="not_resolved",
    )


def test_manual_resource_identity_outranks_preferred_primary() -> None:
    resource = _unresolved_model()
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        preferred_primary=PREFERRED_AIR,
        manual_json=json.dumps(
            [
                {
                    "match": {"resourceKey": resource.key},
                    "air": MANUAL_AIR,
                    "modelName": "Pinned model",
                }
            ]
        ),
    )
    resolved = result.resources[0]
    assert resolved.status is ResourceStatus.RESOLVED
    assert resolved.identity is not None
    assert resolved.identity.source is IdentitySource.MANUAL
    assert resolved.identity.canonical_air == MANUAL_AIR
    assert resolved.identity.model_name == "Pinned model"


def test_preferred_full_air_replaces_lower_precedence_workflow_identity() -> None:
    workflow = replace(
        _unresolved_model(),
        identity=ResourceIdentity(
            source=IdentitySource.WORKFLOW,
            canonical_air=MANUAL_AIR,
            model_id=10,
            model_version_id=20,
        ),
        status=ResourceStatus.RESOLVED,
    )
    result = apply_explicit_identities(
        (workflow,),
        primary_resource_key=workflow.key,
        preferred_primary=PREFERRED_AIR,
    )
    identity = result.resources[0].identity
    assert identity is not None
    assert identity.source is IdentitySource.PREFERRED
    assert identity.model_id == PREFERRED_MODEL_ID
    assert identity.model_version_id == PREFERRED_VERSION_ID


def test_preferred_url_and_version_id_are_partial_identities() -> None:
    resource = _unresolved_model()
    url_result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        preferred_primary=("https://civitai.com/models/2432159/name?modelVersionId=2734704"),
    )
    url_identity = url_result.resources[0].identity
    assert url_result.resources[0].status is ResourceStatus.PARTIAL
    assert url_identity is not None
    assert url_identity.model_id == MODEL_ID
    assert url_identity.model_version_id == MODEL_VERSION_ID
    assert url_identity.canonical_air is None
    assert url_identity.resource_type == "checkpoint"

    id_result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        preferred_primary=str(MODEL_VERSION_ID),
    )
    id_identity = id_result.resources[0].identity
    assert id_identity is not None
    assert id_identity.model_id is None
    assert id_identity.model_version_id == MODEL_VERSION_ID


def test_model_only_url_is_partial_and_warns() -> None:
    resource = _unresolved_model()
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        preferred_primary="https://www.civitai.com/models/2432159/model",
    )
    identity = result.resources[0].identity
    assert identity is not None
    assert identity.model_id == MODEL_ID
    assert identity.model_version_id is None
    assert [issue.code for issue in result.issues] == ["preferred_identity_version_missing"]


def test_manual_identity_can_match_by_strong_hash() -> None:
    resource = replace(
        _unresolved_model(),
        hashes=HashRecord(sha256="a" * 64),
    )
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json=json.dumps(
            [
                {
                    "match": {"hashes": {"SHA256": "a" * 64}},
                    "modelId": 10,
                    "modelVersionId": 20,
                }
            ]
        ),
    )
    identity = result.resources[0].identity
    assert identity is not None
    assert identity.source is IdentitySource.MANUAL
    assert identity.resource_type == "checkpoint"


def test_manual_partial_hypernetwork_identity_gets_safe_civitai_type() -> None:
    resource = replace(
        _unresolved_model(),
        role=ResourceRole.HYPERNETWORK,
        kind=ResourceKind.HYPERNETWORK,
        filename="detail.pt",
        selected_value="detail.pt",
    )
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=None,
        manual_json=json.dumps(
            [
                {
                    "match": {"resourceKey": resource.key},
                    "modelId": 10,
                    "modelVersionId": 20,
                }
            ]
        ),
    )

    identity = result.resources[0].identity
    assert identity is not None
    assert identity.resource_type == "hypernet"


def test_manual_partial_style_model_identity_gets_safe_civitai_type() -> None:
    resource = replace(
        _unresolved_model(),
        role=ResourceRole.STYLE_MODEL,
        kind=ResourceKind.STYLE_MODEL,
        filename="style_model.safetensors",
        selected_value="style_model.safetensors",
    )
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=None,
        manual_json=json.dumps(
            [
                {
                    "match": {"resourceKey": resource.key},
                    "modelId": 10,
                    "modelVersionId": 20,
                }
            ]
        ),
    )

    identity = result.resources[0].identity
    assert identity is not None
    assert identity.resource_type == "other"


def test_hash_mismatch_does_not_fall_back_to_filename() -> None:
    resource = replace(
        _unresolved_model(),
        hashes=HashRecord(sha256="a" * 64),
    )
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json=json.dumps(
            [
                {
                    "match": {
                        "filename": resource.filename,
                        "hashes": {"SHA256": "b" * 64},
                    },
                    "air": MANUAL_AIR,
                }
            ]
        ),
    )
    assert result.resources[0].identity is None


def test_equal_strength_conflicting_manual_records_mark_resource_conflicted() -> None:
    resource = _unresolved_model()
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json=json.dumps(
            [
                {"match": {"resourceKey": resource.key}, "air": MANUAL_AIR},
                {"match": {"resourceKey": resource.key}, "air": PREFERRED_AIR},
            ]
        ),
    )
    resolved = result.resources[0]
    assert resolved.identity is None
    assert resolved.status is ResourceStatus.CONFLICT
    assert resolved.unresolved_reason == "manual_identity_conflict"
    assert [issue.code for issue in result.issues] == ["manual_identity_conflict"]


def test_air_and_explicit_id_conflict_rejects_manual_record() -> None:
    resource = _unresolved_model()
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json=json.dumps(
            [
                {
                    "match": {"resourceKey": resource.key},
                    "air": MANUAL_AIR,
                    "modelVersionId": 999,
                }
            ]
        ),
    )
    assert result.resources[0].identity is None
    assert [issue.code for issue in result.issues] == [
        "manual_identity_version_id_conflict",
        "manual_identity_record_invalid",
    ]


def test_malformed_manual_json_is_sanitized() -> None:
    resource = _unresolved_model()
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json='[{"token":"secret"',
    )
    assert result.resources[0].identity is None
    assert [issue.code for issue in result.issues] == ["manual_identity_json_invalid"]


def test_invalid_preferred_url_is_not_applied() -> None:
    resource = _unresolved_model()
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        preferred_primary="https://example.com/models/1?modelVersionId=2",
    )
    assert result.resources[0].identity is None
    assert [issue.code for issue in result.issues] == ["preferred_identity_url_invalid"]


def test_manual_scalar_and_relative_path_guards_reject_invalid_values() -> None:
    assert manual_module._positive_int(True) is None
    assert manual_module._text("") is None
    assert manual_module._text("x" * 513) is None
    assert manual_module._text("unsafe\x00text") is None
    assert manual_module._safe_relative("../model.safetensors") is None


def test_civitai_air_without_version_is_partial() -> None:
    identity = ResourceIdentity(
        source=IdentitySource.MANUAL,
        canonical_air="urn:air:sdxl:checkpoint:civitai:10",
        identity_source="civitai",
        model_id=10,
    )

    assert manual_module._identity_status(identity) is ResourceStatus.PARTIAL


def test_manual_records_reject_missing_malformed_and_conflicting_identities() -> None:
    resource = _unresolved_model()
    cases = (
        (
            [{"match": {"resourceKey": resource.key}}],
            ["manual_identity_missing", "manual_identity_record_invalid"],
        ),
        (
            [{"match": {"resourceKey": resource.key}, "air": "not-an-air"}],
            ["air_structure_invalid", "manual_identity_record_invalid"],
        ),
        (
            [
                {
                    "match": {"resourceKey": resource.key},
                    "air": MANUAL_AIR,
                    "modelId": 999,
                }
            ],
            ["manual_identity_model_id_conflict", "manual_identity_record_invalid"],
        ),
        (
            [{"match": "not-a-mapping", "air": MANUAL_AIR}],
            ["manual_identity_record_invalid"],
        ),
    )

    for payload, expected_issues in cases:
        result = apply_explicit_identities(
            (resource,),
            primary_resource_key=resource.key,
            manual_json=json.dumps(payload),
        )
        assert result.resources[0].identity is None
        assert [issue.code for issue in result.issues] == expected_issues


def test_manual_json_size_schema_record_limit_and_item_guards() -> None:
    resource = _unresolved_model()
    too_large = "[" + (" " * manual_module.MAX_MANUAL_JSON_CHARS)
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json=too_large,
    )
    assert [issue.code for issue in result.issues] == ["manual_identity_json_too_large"]

    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json=json.dumps({"match": {"resourceKey": resource.key}}),
    )
    assert [issue.code for issue in result.issues] == ["manual_identity_json_schema_invalid"]

    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json=json.dumps([None] * (manual_module.MAX_MANUAL_RECORDS + 1)),
    )
    issue_codes = [issue.code for issue in result.issues]
    assert issue_codes[0] == "manual_identity_record_limit_reached"
    assert issue_codes.count("manual_identity_record_invalid") == (manual_module.MAX_MANUAL_RECORDS)


def test_manual_selector_mismatch_is_not_applied() -> None:
    resource = _unresolved_model()
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json=json.dumps(
            [{"match": {"resourceKey": "different-resource"}, "air": MANUAL_AIR}]
        ),
    )

    assert result.resources[0].identity is None
    assert result.issues == ()


def test_equal_strength_partial_manual_identities_conflict() -> None:
    resource = _unresolved_model()
    result = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        manual_json=json.dumps(
            [
                {
                    "match": {"resourceKey": resource.key},
                    "modelId": 10,
                    "modelVersionId": 20,
                },
                {
                    "match": {"resourceKey": resource.key},
                    "modelId": 30,
                    "modelVersionId": 40,
                },
            ]
        ),
    )

    assert result.resources[0].status is ResourceStatus.CONFLICT
    assert [issue.code for issue in result.issues] == ["manual_identity_conflict"]


def test_preferred_identity_rejects_invalid_path_and_zero_version() -> None:
    resource = _unresolved_model()
    invalid_path = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        preferred_primary="https://civitai.com/images/10?modelVersionId=20",
    )
    assert [issue.code for issue in invalid_path.issues] == ["preferred_identity_url_invalid"]

    zero_version = apply_explicit_identities(
        (resource,),
        primary_resource_key=resource.key,
        preferred_primary="0",
    )
    assert [issue.code for issue in zero_version.issues] == ["preferred_identity_invalid"]


def test_preferred_identity_handles_empty_and_unmatched_resource_sets() -> None:
    empty = apply_explicit_identities(
        (),
        primary_resource_key="missing",
        preferred_primary=PREFERRED_AIR,
    )
    assert empty.resources == ()
    assert empty.issues == ()

    resource = _unresolved_model()
    unmatched = apply_explicit_identities(
        (resource,),
        primary_resource_key="different-resource",
        preferred_primary=PREFERRED_AIR,
    )
    assert unmatched.resources == (resource,)
    assert unmatched.issues == ()
