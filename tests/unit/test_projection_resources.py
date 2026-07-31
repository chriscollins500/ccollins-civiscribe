from __future__ import annotations

from dataclasses import replace

import pytest

from civiscribe.domain import (
    HashRecord,
    IdentitySource,
    LookupStatus,
    ResourceIdentity,
    ResourceKind,
    ResourceRecord,
    ResourceRole,
    ResourceStatus,
    ResourceStrengths,
)
from civiscribe.domain.identity import LookupDiagnostics
from civiscribe.projections.resources import (
    a1111_hashes,
    compatibility_hash,
    legacy_hash_list,
    parser_resource_item,
    parser_resource_items,
    resource_by_key,
    resource_manifest_item,
    structured_hashes,
)
from tests.projection_support import (
    LORA_AUTO_V2,
    LORA_CLIP_STRENGTH,
    LORA_MODEL_STRENGTH,
    LORA_WEIGHT,
    MODEL_AUTO_V2,
    MODEL_ID,
    MODEL_SHA256,
    MODEL_VERSION_ID,
    complete_record,
    lora_resource,
    model_resource,
)

EXPECTED_HASH_ALIAS_COUNT = 17
FALLBACK_LORA_WEIGHT = 0.4


def _resource(
    role: ResourceRole,
    kind: ResourceKind,
    node_id: str,
    *,
    hash_value: str | None = "0123456789",
    active: bool = True,
) -> ResourceRecord:
    return ResourceRecord(
        key=f"{node_id}:resource",
        role=role,
        kind=kind,
        node_id=node_id,
        node_class="ResourceLoader",
        filename=f"{role.value}.safetensors",
        selected_value=f"models/{role.value}.safetensors",
        active=active,
        hashes=HashRecord(auto_v2=hash_value),
    )


def test_structured_hashes_accepts_every_known_well_formed_name() -> None:
    hashes = HashRecord(
        auto_v1="ABCDEF12",
        auto_v2="1234567890",
        auto_v3="ABCDEF123456",
        sha256="A" * 64,
        crc32="ABCDEF12",
        blake3="B" * 64,
    )

    assert structured_hashes(hashes) == {
        "AutoV1": "abcdef12",
        "AutoV2": "1234567890",
        "AutoV3": "abcdef123456",
        "SHA256": "a" * 64,
        "CRC32": "abcdef12",
        "BLAKE3": "b" * 64,
    }
    assert (
        structured_hashes(
            HashRecord(
                auto_v1=None,
                auto_v2="short",
                auto_v3="z" * 12,
                sha256="x" * 64,
                crc32="",
                blake3="1" * 63,
            )
        )
        == {}
    )


def test_compatibility_hash_prefers_autov2_then_cached_sha256() -> None:
    assert compatibility_hash(HashRecord(auto_v2=MODEL_AUTO_V2, sha256="f" * 64)) == MODEL_AUTO_V2
    assert compatibility_hash(HashRecord(sha256=MODEL_SHA256)) == MODEL_AUTO_V2
    assert compatibility_hash(HashRecord(auto_v2="invalid", sha256="invalid")) is None


def test_resource_lookup_requires_active_matching_key() -> None:
    record = complete_record()
    inactive = replace(model_resource(), active=False)
    inactive_record = replace(record, resources=(inactive,))

    assert resource_by_key(record, None) is None
    assert resource_by_key(record, "missing") is None
    assert resource_by_key(inactive_record, inactive.key) is None
    assert resource_by_key(record, record.primary_resource_key) == model_resource()


def test_a1111_hashes_cover_every_active_resource_role_and_selected_aliases() -> None:
    roles = (
        (ResourceRole.BASE_MODEL, ResourceKind.CHECKPOINT),
        (ResourceRole.LORA, ResourceKind.LORA),
        (ResourceRole.VAE, ResourceKind.VAE),
        (ResourceRole.TEXT_ENCODER, ResourceKind.CLIP),
        (ResourceRole.EMBEDDING, ResourceKind.EMBEDDING),
        (ResourceRole.HYPERNETWORK, ResourceKind.HYPERNETWORK),
        (ResourceRole.CONTROLNET, ResourceKind.CONTROLNET),
        (ResourceRole.IPADAPTER, ResourceKind.IPADAPTER),
        (ResourceRole.STYLE_MODEL, ResourceKind.STYLE_MODEL),
        (ResourceRole.VISION_ENCODER, ResourceKind.VISION_ENCODER),
        (ResourceRole.MODEL_PATCH, ResourceKind.MODEL_PATCH),
        (ResourceRole.GLIGEN, ResourceKind.GLIGEN),
        (ResourceRole.UPSCALER, ResourceKind.UPSCALER),
    )
    resources = tuple(
        _resource(role, kind, str(index + 1)) for index, (role, kind) in enumerate(roles)
    )
    text_encoder = resources[3]
    text_encoder_identity = ResourceIdentity(
        source=IdentitySource.CACHE,
        raw_air="urn:air:krea2:text_encoders:civitai:50@60",
        canonical_air="urn:air:krea2:text_encoders:civitai:50@60",
        ecosystem="krea2",
        resource_type="text_encoders",
        identity_source="civitai",
        identity_id="50",
        identity_version="60",
        model_id=50,
        model_version_id=60,
    )
    resources = (
        *resources[:3],
        replace(
            text_encoder,
            identity=text_encoder_identity,
            status=ResourceStatus.RESOLVED,
        ),
        *resources[4:],
    )
    record = replace(
        complete_record(),
        resources=(
            *resources,
            _resource(ResourceRole.LORA, ResourceKind.LORA, "20", hash_value=None),
            _resource(
                ResourceRole.UPSCALER,
                ResourceKind.UPSCALER,
                "21",
                active=False,
            ),
        ),
        primary_resource_key=resources[0].key,
        selected_vae_resource_key=resources[2].key,
    )

    hashes = a1111_hashes(record)

    assert hashes["model"] == "0123456789"
    assert hashes["vae"] == "0123456789"
    assert hashes["model:base_model.safetensors"] == "0123456789"
    assert hashes["LORA:lora.safetensors"] == "0123456789"
    assert hashes["lora:lora.safetensors"] == "0123456789"
    assert hashes["VAE:vae.safetensors"] == "0123456789"
    assert hashes["textencoder:text_encoder.safetensors"] == "0123456789"
    assert hashes["embed:embedding.safetensors"] == "0123456789"
    assert hashes["hypernet:hypernetwork.safetensors"] == "0123456789"
    assert hashes["controlnet:controlnet.safetensors"] == "0123456789"
    assert hashes["ipadapter:ipadapter.safetensors"] == "0123456789"
    assert hashes["stylemodel:style_model.safetensors"] == "0123456789"
    assert hashes["visionencoder:vision_encoder.safetensors"] == "0123456789"
    assert hashes["modelpatch:model_patch.safetensors"] == "0123456789"
    assert hashes["gligen:gligen.safetensors"] == "0123456789"
    assert hashes["upscaler:upscaler.safetensors"] == "0123456789"
    assert len(hashes) == EXPECTED_HASH_ALIAS_COUNT


def test_a1111_hashes_omit_unresolved_text_encoder_hashes() -> None:
    text_encoder = _resource(ResourceRole.TEXT_ENCODER, ResourceKind.CLIP, "1")
    record = replace(
        complete_record(),
        resources=(model_resource(), text_encoder),
    )

    hashes = a1111_hashes(record)

    assert "textencoder:text_encoder.safetensors" not in hashes


def test_legacy_hash_lists_are_active_role_filtered_and_deduplicated() -> None:
    lora = lora_resource()
    record = replace(
        complete_record(),
        resources=(
            lora,
            replace(lora, key="duplicate", node_id="9"),
            replace(lora, key="inactive", node_id="10", active=False),
            replace(lora, key="nohash", node_id="11", hashes=HashRecord()),
            model_resource(),
        ),
    )

    assert legacy_hash_list(record, ResourceRole.LORA) == (
        f"ProjectRealismPhotoLora_v1: {LORA_AUTO_V2}"
    )
    assert legacy_hash_list(record, ResourceRole.CONTROLNET) is None


def test_parser_resource_rejects_inactive_missing_or_untrusted_identity() -> None:
    resolved = model_resource()
    unresolved = replace(resolved, status=ResourceStatus.UNRESOLVED)
    partial_api = replace(
        resolved,
        status=ResourceStatus.PARTIAL,
        identity=replace(resolved.identity, source=IdentitySource.API)
        if resolved.identity is not None
        else None,
    )
    bad_type = replace(
        resolved,
        identity=replace(resolved.identity, resource_type="custom")
        if resolved.identity is not None
        else None,
    )
    missing_type = replace(
        resolved,
        identity=replace(resolved.identity, resource_type=None)
        if resolved.identity is not None
        else None,
    )
    bad_version = replace(
        resolved,
        identity=replace(resolved.identity, model_version_id=0)
        if resolved.identity is not None
        else None,
    )

    assert parser_resource_item(replace(resolved, active=False)) is None
    assert parser_resource_item(replace(resolved, identity=None)) is None
    assert parser_resource_item(unresolved) is None
    assert parser_resource_item(partial_api) is None
    assert parser_resource_item(bad_type) is None
    assert parser_resource_item(missing_type) is None
    assert parser_resource_item(bad_version) is None


def test_parser_resource_rejects_parent_checkpoint_for_text_encoder() -> None:
    text_encoder = _resource(ResourceRole.TEXT_ENCODER, ResourceKind.CLIP, "1")
    checkpoint_identity = ResourceIdentity(
        source=IdentitySource.CACHE,
        raw_air="urn:air:krea2:checkpoint:civitai:50@60",
        canonical_air="urn:air:krea2:checkpoint:civitai:50@60",
        ecosystem="krea2",
        resource_type="checkpoint",
        identity_source="civitai",
        identity_id="50",
        identity_version="60",
        model_id=50,
        model_version_id=60,
        file_id="61",
        format="safetensor",
        file_type="Text Encoder",
        file_primary=False,
    )
    resolved = replace(
        text_encoder,
        identity=checkpoint_identity,
        status=ResourceStatus.RESOLVED,
    )

    assert parser_resource_item(resolved) is None
    manifest_identity = resource_manifest_item(resolved)["identity"]
    assert isinstance(manifest_identity, dict)
    assert manifest_identity["fileType"] == "Text Encoder"
    assert manifest_identity["filePrimary"] is False
    assert resource_manifest_item(resolved)["identityScope"] == "exact_file"
    assert resource_manifest_item(resolved)["parserFacing"] is False
    assert resource_manifest_item(resolved)["parserExclusionReason"] == ("resource_type_mismatch")


def test_manifest_marks_identity_without_version_or_file_scope_as_unknown() -> None:
    resolved = model_resource()
    assert resolved.identity is not None
    incomplete_identity = replace(
        resolved.identity,
        canonical_air=None,
        model_version_id=None,
        identity_version=None,
        file_id=None,
    )

    item = resource_manifest_item(replace(resolved, identity=incomplete_identity))

    assert item["identityScope"] is None
    assert item["parserFacing"] is False
    assert item["parserExclusionReason"] == "model_version_id_missing"


def test_partial_preferred_identity_is_honest_and_parser_safe() -> None:
    resource = replace(
        model_resource(),
        status=ResourceStatus.PARTIAL,
        identity=ResourceIdentity(
            source=IdentitySource.PREFERRED,
            resource_type="diffusion_model",
            model_id=-1,
            model_version_id=2734704,
            model_name="Pinned model",
        ),
    )

    assert parser_resource_item(resource) == {
        "type": "diffusionmodel",
        "modelVersionId": 2734704,
        "identityIncomplete": True,
        "modelName": "Pinned model",
    }


def test_resolved_resource_emits_full_air_aliases_and_optional_identity_fields() -> None:
    item = parser_resource_item(model_resource())

    assert item is not None
    assert item["type"] == "checkpoint"
    assert item["modelId"] == MODEL_ID
    assert item["modelVersionId"] == MODEL_VERSION_ID
    assert item["air"] == item["urn"]
    assert item["fileId"] == "2402203"
    assert item["format"] == "safetensor"
    assert item["modelName"] == "SWIFT! Fast and detailed ZIT model"
    assert item["modelVersionName"] == "NEO"


@pytest.mark.parametrize(
    ("raw_type", "expected_type", "role", "kind"),
    [
        ("dora", "dora", ResourceRole.LORA, ResourceKind.LORA),
        (
            "hypernetwork",
            "hypernet",
            ResourceRole.HYPERNETWORK,
            ResourceKind.HYPERNETWORK,
        ),
        ("locon", "locon", ResourceRole.LORA, ResourceKind.LORA),
        ("lycoris", "lycoris", ResourceRole.LORA, ResourceKind.LORA),
        (
            "motionmodule",
            "motion",
            ResourceRole.MOTION_MODULE,
            ResourceKind.MOTION_MODULE,
        ),
        (
            "other",
            "other",
            ResourceRole.AUXILIARY_MODEL,
            ResourceKind.AUXILIARY_MODEL,
        ),
        (
            "text_encoder",
            "text_encoders",
            ResourceRole.TEXT_ENCODER,
            ResourceKind.CLIP,
        ),
        (
            "textencoder",
            "text_encoders",
            ResourceRole.TEXT_ENCODER,
            ResourceKind.CLIP,
        ),
        (
            "text_encoders",
            "text_encoders",
            ResourceRole.TEXT_ENCODER,
            ResourceKind.CLIP,
        ),
        (
            "unknown",
            "unknown",
            ResourceRole.AUXILIARY_MODEL,
            ResourceKind.AUXILIARY_MODEL,
        ),
    ],
)
def test_parser_resource_preserves_current_civitai_air_types(
    raw_type: str,
    expected_type: str,
    role: ResourceRole,
    kind: ResourceKind,
) -> None:
    resource = replace(
        _resource(role, kind, "1"),
        status=ResourceStatus.RESOLVED,
        identity=ResourceIdentity(
            source=IdentitySource.API,
            resource_type=raw_type,
            model_id=MODEL_ID,
            model_version_id=MODEL_VERSION_ID,
            canonical_air=(f"urn:air:other:{expected_type}:civitai:{MODEL_ID}@{MODEL_VERSION_ID}"),
        ),
    )

    item = parser_resource_item(resource)

    assert item is not None
    assert item["type"] == expected_type
    assert item["modelVersionId"] == MODEL_VERSION_ID
    assert item["air"] == item["urn"]


def test_lora_parser_fields_support_explicit_and_model_fallback_weights() -> None:
    explicit = parser_resource_item(lora_resource())
    fallback_resource = replace(
        lora_resource(),
        strengths=ResourceStrengths(model=FALLBACK_LORA_WEIGHT),
    )
    fallback = parser_resource_item(fallback_resource)

    assert explicit is not None
    assert explicit["weight"] == LORA_WEIGHT
    assert explicit["strengthModel"] == LORA_MODEL_STRENGTH
    assert explicit["strengthClip"] == LORA_CLIP_STRENGTH
    assert fallback is not None
    assert fallback["weight"] == FALLBACK_LORA_WEIGHT
    assert fallback["strengthModel"] == FALLBACK_LORA_WEIGHT
    assert "strengthClip" not in fallback


def test_resolved_identity_without_optional_fields_stays_minimal() -> None:
    resource = replace(
        model_resource(),
        identity=ResourceIdentity(
            source=IdentitySource.WORKFLOW,
            resource_type="checkpoint",
            model_version_id=1,
            canonical_air="not-an-air",
        ),
    )

    assert parser_resource_item(resource) == {
        "type": "checkpoint",
        "modelVersionId": 1,
    }


def test_parser_resource_list_omits_invalid_items_and_deduplicates_identity() -> None:
    model = model_resource()
    duplicate = replace(model, key="duplicate", node_id="20")

    assert parser_resource_items((replace(model, identity=None), model, duplicate)) == [
        parser_resource_item(model)
    ]


def test_structured_resource_item_preserves_unknowns_without_private_paths() -> None:
    unresolved = ResourceRecord(
        key="7:model",
        role=ResourceRole.BASE_MODEL,
        kind=ResourceKind.DIFFUSION_MODEL,
        node_id="7",
        node_class="Loader",
        filename=r"C:\Users\person\models\private.gguf",
        selected_value=r"C:\Users\person\models\private.gguf",
        hashes=HashRecord(auto_v2="bad"),
        status=ResourceStatus.UNRESOLVED,
        lookup_status=LookupStatus.FAILED,
        lookup_diagnostics=LookupDiagnostics(
            attempted_hash_types=("SHA256", "AutoV2"),
            reason="no_role_compatible_shared_hash_candidate",
            http_status=200,
            retryable=False,
            retry_after_seconds=12,
            tls_source="system_default",
            candidate_count=3,
            compatible_candidate_count=0,
        ),
        unresolved_reason="hashed_but_no_civitai_identity",
    )
    item = resource_manifest_item(unresolved)

    assert item["filename"] == "private.gguf"
    assert item["selectedValue"] == "private.gguf"
    assert item["hashes"] == {}
    assert item["identity"] is None
    assert item["lookupDiagnostics"] == {
        "status": "failed",
        "attemptedHashTypes": ["SHA256", "AutoV2"],
        "reason": "no_role_compatible_shared_hash_candidate",
        "httpStatus": 200,
        "retryable": False,
        "retryAfterSeconds": 12,
        "tlsSource": "system_default",
        "candidateCount": 3,
        "compatibleCandidateCount": 0,
    }
    assert item["resolved"] is False
    assert item["unresolvedReason"] == "hashed_but_no_civitai_identity"
    assert item["identityScope"] is None
    assert item["parserFacing"] is False
    assert item["parserExclusionReason"] == "identity_missing"
    assert "Users" not in str(item)


def test_structured_resolved_resource_contains_all_identity_fields() -> None:
    item = resource_manifest_item(model_resource())
    identity = item["identity"]

    assert isinstance(identity, dict)
    assert identity["source"] == "api"
    assert identity["rawAir"] == identity["canonicalAir"]
    assert identity["ecosystem"] == "flux2"
    assert identity["airSource"] == "civitai"
    assert identity["id"] == "2432159"
    assert identity["version"] == "2734704"
    assert identity["baseModel"] is None
    assert item["identityScope"] == "exact_file"
    assert item["parserFacing"] is True
    assert item["parserExclusionReason"] is None
    assert item["status"] == "resolved"
    assert item["resolved"] is True
