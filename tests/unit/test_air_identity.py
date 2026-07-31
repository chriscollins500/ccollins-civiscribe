from __future__ import annotations

from dataclasses import replace

import pytest

import civiscribe.identity.air as air_module
from civiscribe.domain import IdentitySource, ResourceIdentity
from civiscribe.identity.air import MAX_AIR_CHARS, attach_file_to_air_identity, parse_air

MODEL_ID = 827184


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "urn:air:sdxl:checkpoint:civitai:827184@2514310",
            (
                "urn:air:sdxl:checkpoint:civitai:827184@2514310",
                MODEL_ID,
                2514310,
                None,
                None,
            ),
        ),
        (
            "air:sdxl:checkpoint:civitai:827184@2514310+2402203",
            (
                "urn:air:sdxl:checkpoint:civitai:827184@2514310+2402203",
                MODEL_ID,
                2514310,
                "2402203",
                None,
            ),
        ),
        (
            "sdxl:checkpoint:civitai:827184@2514310+2402203.safetensor",
            (
                "urn:air:sdxl:checkpoint:civitai:827184@2514310+2402203.safetensor",
                MODEL_ID,
                2514310,
                "2402203",
                "safetensor",
            ),
        ),
        (
            "urn:air:other:other:civitai-r2:civitai-worker-assets@sam_vit_b_01ec64.pth",
            (
                "urn:air:other:other:civitai-r2:civitai-worker-assets@sam_vit_b_01ec64.pth",
                None,
                None,
                None,
                "pth",
            ),
        ),
        (
            "urn:air:oci:image:ghcr:civitai/training-toolkit@sha256:abc123",
            (
                "urn:air:oci:image:ghcr:civitai/training-toolkit@sha256:abc123",
                None,
                None,
                None,
                None,
            ),
        ),
    ],
)
def test_air_parser_normalizes_documented_forms(
    raw: str,
    expected: tuple[str, int | None, int | None, str | None, str | None],
) -> None:
    canonical, model_id, version_id, file_id, file_format = expected
    result = parse_air(raw, provenance=IdentitySource.WORKFLOW)
    assert result.issues == ()
    assert result.identity is not None
    assert result.identity.raw_air == raw
    assert result.identity.canonical_air == canonical
    assert result.identity.model_id == model_id
    assert result.identity.model_version_id == version_id
    assert result.identity.file_id == file_id
    assert result.identity.format == file_format


def test_non_civitai_identity_never_forces_numeric_model_ids() -> None:
    result = parse_air(
        "urn:air:oci:image:dockerhub:123@456",
        provenance=IdentitySource.API,
    )
    assert result.identity is not None
    assert result.identity.identity_id == "123"
    assert result.identity.identity_version == "456"
    assert result.identity.model_id is None
    assert result.identity.model_version_id is None


def test_file_attachment_preserves_raw_air_and_canonicalizes_api_format() -> None:
    raw = "urn:air:anima:checkpoint:civitai:827184@2514310"
    parsed = parse_air(raw, provenance=IdentitySource.API)
    assert parsed.identity is not None

    attached = attach_file_to_air_identity(
        parsed.identity,
        file_id="2402203",
        file_format="SafeTensor",
    )

    assert attached.issues == ()
    assert attached.identity is not None
    assert attached.identity.raw_air == raw
    assert attached.identity.canonical_air == f"{raw}+2402203.safetensor"
    assert attached.identity.file_id == "2402203"
    assert attached.identity.format == "safetensor"


def test_file_attachment_rejects_conflicting_existing_file_id() -> None:
    parsed = parse_air(
        "urn:air:sdxl:checkpoint:civitai:827184@2514310+2402203.safetensor",
        provenance=IdentitySource.API,
    )
    assert parsed.identity is not None

    attached = attach_file_to_air_identity(
        parsed.identity,
        file_id="9999999",
        file_format="SafeTensor",
    )

    assert attached.identity is None
    assert [issue.code for issue in attached.issues] == ["air_file_id_conflict"]


@pytest.mark.parametrize(
    ("file_id", "file_format"),
    [
        ("", None),
        ("x" * (MAX_AIR_CHARS + 1), None),
        ("unsafe file", None),
        ("file@version", None),
        ("file+other", None),
        ("2402203", "unsafe format"),
    ],
)
def test_file_attachment_rejects_invalid_file_details(
    file_id: str,
    file_format: str | None,
) -> None:
    parsed = parse_air(
        "urn:air:sdxl:checkpoint:civitai:827184@2514310",
        provenance=IdentitySource.API,
    )
    assert parsed.identity is not None

    attached = attach_file_to_air_identity(
        parsed.identity,
        file_id=file_id,
        file_format=file_format,
    )

    assert attached.identity is None
    assert [issue.code for issue in attached.issues] == ["air_file_details_invalid"]


def test_file_attachment_rejects_direct_and_canonical_format_conflicts() -> None:
    parsed = parse_air(
        "urn:air:sdxl:checkpoint:civitai:827184@2514310+2402203.safetensor",
        provenance=IdentitySource.API,
    )
    assert parsed.identity is not None
    direct = attach_file_to_air_identity(
        parsed.identity,
        file_id="2402203",
        file_format="gguf",
    )
    assert direct.identity is None
    assert [issue.code for issue in direct.issues] == ["air_file_format_conflict"]

    detached_fields = replace(parsed.identity, file_id=None, format=None)
    canonical_id_conflict = attach_file_to_air_identity(
        detached_fields,
        file_id="999",
        file_format="safetensor",
    )
    assert canonical_id_conflict.identity is None
    assert [issue.code for issue in canonical_id_conflict.issues] == ["air_file_id_conflict"]

    canonical_format_conflict = attach_file_to_air_identity(
        detached_fields,
        file_id="2402203",
        file_format="gguf",
    )
    assert canonical_format_conflict.identity is None
    assert [issue.code for issue in canonical_format_conflict.issues] == [
        "air_file_format_conflict"
    ]


def test_file_attachment_handles_unqualified_and_invalid_canonical_identity() -> None:
    unqualified = ResourceIdentity(source=IdentitySource.API)
    attached = attach_file_to_air_identity(
        unqualified,
        file_id="2402203",
        file_format="SafeTensor",
    )
    assert attached.identity is not None
    assert attached.identity.canonical_air is None
    assert attached.identity.file_id == "2402203"

    invalid = replace(unqualified, canonical_air="not-an-air")
    rejected = attach_file_to_air_identity(invalid, file_id="2402203")
    assert rejected.identity is None
    assert [issue.code for issue in rejected.issues] == ["air_structure_invalid"]


def test_primary_file_attachment_can_preserve_parent_canonical_air() -> None:
    raw = "urn:air:sdxl:checkpoint:civitai:827184@2514310"
    parsed = parse_air(raw, provenance=IdentitySource.API)
    assert parsed.identity is not None

    attached = attach_file_to_air_identity(
        parsed.identity,
        file_id="2402203",
        file_format="SafeTensor",
        pin_canonical=False,
    )

    assert attached.identity is not None
    assert attached.identity.canonical_air == raw
    assert attached.identity.file_id == "2402203"
    assert attached.identity.format == "safetensor"


def test_unknown_type_is_preserved_with_warning() -> None:
    result = parse_air(
        "urn:air:other:futuretype:example:resource@v1",
        provenance=IdentitySource.MANUAL,
    )
    assert result.identity is not None
    assert result.identity.resource_type == "futuretype"
    assert [issue.code for issue in result.issues] == ["air_resource_type_unknown"]


@pytest.mark.parametrize("resource_type", ["text_encoders", "unknown"])
def test_current_civitai_air_types_are_recognized(resource_type: str) -> None:
    raw = f"urn:air:zimageturbo:{resource_type}:civitai:1@2"

    result = parse_air(raw, provenance=IdentitySource.API)

    assert result.issues == ()
    assert result.identity is not None
    assert result.identity.resource_type == resource_type
    assert result.identity.canonical_air == raw


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (None, None),
        ("", None),
        (42, "air_value_not_text"),
        ("urn:notair:sdxl:checkpoint:civitai:1@2", "air_structure_invalid"),
        ("urn:air:sdxl:checkpoint:civitai", "air_structure_invalid"),
        ("urn:air:sd xl:checkpoint:civitai:1@2", "air_value_contains_unsafe_characters"),
        ("urn:air:sdxl:check/point:civitai:1@2", "air_segment_invalid"),
        ("urn:air:sdxl:checkpoint:civitai:@2", "air_identifier_invalid"),
        ("urn:air:sdxl:checkpoint:civitai:1@@2", "air_identifier_invalid"),
        ("urn:air:sdxl:checkpoint:civitai:abc@2", "air_civitai_model_id_invalid"),
        ("urn:air:sdxl:checkpoint:civitai:1@abc", "air_civitai_model_version_invalid"),
    ],
)
def test_air_parser_rejects_malformed_values_without_crashing(
    raw: object,
    code: str | None,
) -> None:
    result = parse_air(raw, provenance=IdentitySource.MANUAL)
    assert result.identity is None
    assert [issue.code for issue in result.issues] == ([] if code is None else [code])


def test_civitai_air_without_version_remains_partial_parse_evidence() -> None:
    result = parse_air(
        "urn:air:sdxl:checkpoint:civitai:827184",
        provenance=IdentitySource.PREFERRED,
    )
    assert result.identity is not None
    assert result.identity.model_id == MODEL_ID
    assert result.identity.model_version_id is None
    assert [issue.code for issue in result.issues] == ["air_civitai_model_version_missing"]


def test_air_length_limit_is_sanitized() -> None:
    result = parse_air(
        "x" * (MAX_AIR_CHARS + 1),
        provenance=IdentitySource.MANUAL,
    )
    assert result.identity is None
    assert [issue.code for issue in result.issues] == ["air_value_too_large"]


@pytest.mark.parametrize(
    ("raw", "expected_file_id"),
    [
        ("urn:air:sdxl:checkpoint:civitai:1@2+2402203.", "2402203."),
        ("urn:air:sdxl:checkpoint:civitai:1@2+.safetensor", ".safetensor"),
    ],
)
def test_invalid_optional_format_suffix_remains_part_of_file_id(
    raw: str,
    expected_file_id: str,
) -> None:
    result = parse_air(raw, provenance=IdentitySource.MANUAL)

    assert result.identity is not None
    assert result.identity.file_id == expected_file_id
    assert result.identity.format is None


def test_empty_file_identifier_is_rejected() -> None:
    result = parse_air(
        "urn:air:sdxl:checkpoint:civitai:1@2+",
        provenance=IdentitySource.MANUAL,
    )

    assert result.identity is None
    assert [issue.code for issue in result.issues] == ["air_identifier_invalid"]


@pytest.mark.parametrize(
    "identifier",
    [
        "unsafe identity@v1",
        "identity@unsafe version",
        "identity@v1+unsafe file",
    ],
)
def test_identifier_helper_rejects_unsafe_components(identifier: str) -> None:
    assert air_module._parse_identifier("example", identifier) is None


def test_file_details_defensively_rejects_empty_normalized_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        air_module,
        "_split_optional_format",
        lambda _value: ("", None),
    )

    assert air_module._file_details("civitai", "version", None) is None


@pytest.mark.parametrize("identity_id", ["identity+alias", "identity@alias"])
def test_identifier_helper_defensively_rejects_embedded_delimiters(
    identity_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        air_module,
        "_identifier_parts",
        lambda _value: (identity_id, None, None),
    )

    assert air_module._parse_identifier("example", "ignored") is None
