from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from civiscribe.domain import (
    HashRecord,
    IdentitySource,
    ResourceIdentity,
    ResourceStatus,
)
from civiscribe.identity import local_cache as local_cache_module
from civiscribe.identity.local_cache import IdentityCache
from tests.projection_support import MODEL_ID, MODEL_VERSION_ID, model_resource

MODEL_AIR = f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}+2402203.safetensor"


def _identity(
    *,
    air: str | None = MODEL_AIR,
    model_id: int | None = MODEL_ID,
    version_id: int | None = MODEL_VERSION_ID,
) -> ResourceIdentity:
    return ResourceIdentity(
        source=IdentitySource.CACHE,
        raw_air=air,
        canonical_air=air,
        ecosystem="flux2" if air is not None else None,
        resource_type="checkpoint",
        identity_source="civitai",
        identity_id=str(model_id) if model_id is not None else None,
        identity_version=str(version_id) if version_id is not None else None,
        model_id=model_id,
        model_version_id=version_id,
        file_id="2402203" if air is not None else None,
        format="safetensor" if air is not None else None,
        file_type="Text Encoder" if air is not None else None,
        file_primary=False if air is not None else None,
        base_model="Flux.2 D",
        model_name="Model",
        model_version_name="Version",
    )


def _cache(tmp_path: Path) -> IdentityCache:
    return IdentityCache(tmp_path / "identity-cache.json")


def test_identity_cache_round_trip_resolves_by_hash_without_private_paths(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path)
    hashes = HashRecord(sha256="a" * 64, auto_v2="a" * 10)
    assert cache.put(_identity(), hashes) == ()

    resource = replace(
        model_resource(),
        hashes=HashRecord(sha256="a" * 64),
        identity=None,
        status=ResourceStatus.UNRESOLVED,
    )
    result = cache.lookup(resource)

    assert result.status is ResourceStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.source is IdentitySource.CACHE
    assert result.identity.canonical_air == MODEL_AIR
    assert result.identity.file_type == "Text Encoder"
    assert result.identity.file_primary is False
    assert result.identity.base_model == "Flux.2 D"
    assert result.hashes.auto_v2 == "a" * 10
    cache_text = cache.store.path.read_text(encoding="utf-8")
    assert str(tmp_path) not in cache_text
    assert "C:\\Users\\" not in cache_text


def test_identity_cache_id_only_record_is_partial(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    hashes = HashRecord(auto_v2="b" * 10)
    assert cache.put(_identity(air=None), hashes) == ()

    result = cache.lookup(
        replace(
            model_resource(),
            hashes=hashes,
            identity=None,
            status=ResourceStatus.UNRESOLVED,
        )
    )

    assert result.status is ResourceStatus.PARTIAL
    assert result.identity is not None
    assert result.identity.canonical_air is None
    assert result.identity.model_version_id == MODEL_VERSION_ID


def test_identity_cache_rejects_air_and_id_conflict(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.store.merge(
        {
            "cacheKey": "bad",
            "hashes": {"SHA256": "a" * 64},
            "identity": {
                "canonicalAir": MODEL_AIR,
                "modelId": MODEL_ID,
                "modelVersionId": MODEL_VERSION_ID + 1,
            },
        }
    )
    result = cache.lookup(
        replace(
            model_resource(),
            hashes=HashRecord(sha256="a" * 64),
            identity=None,
            status=ResourceStatus.UNRESOLVED,
        )
    )

    assert result.identity is None
    assert result.status is ResourceStatus.UNRESOLVED
    assert [issue.code for issue in result.issues] == [
        "identity_cache_version_id_conflict",
        "identity_cache_record_invalid",
    ]


def test_equal_strength_conflicting_cache_records_do_not_resolve(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    hashes = HashRecord(auto_v2="c" * 10)
    assert cache.put(_identity(), hashes) == ()
    conflicting_air = "urn:air:flux2:checkpoint:civitai:90@91"
    assert (
        cache.put(
            _identity(air=conflicting_air, model_id=90, version_id=91),
            hashes,
        )
        == ()
    )

    result = cache.lookup(
        replace(
            model_resource(),
            hashes=hashes,
            identity=None,
            status=ResourceStatus.UNRESOLVED,
        )
    )

    assert result.status is ResourceStatus.CONFLICT
    assert result.identity is None
    assert [issue.code for issue in result.issues] == ["identity_cache_conflict"]


def test_identity_cache_uses_strongest_available_hash(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    assert cache.put(_identity(), HashRecord(sha256="d" * 64)) == ()
    weaker_air = "urn:air:flux2:checkpoint:civitai:70@71"
    assert (
        cache.put(
            _identity(air=weaker_air, model_id=70, version_id=71),
            HashRecord(auto_v2="e" * 10),
        )
        == ()
    )
    result = cache.lookup(
        replace(
            model_resource(),
            hashes=HashRecord(sha256="d" * 64, auto_v2="e" * 10),
            identity=None,
            status=ResourceStatus.UNRESOLVED,
        )
    )

    assert result.status is ResourceStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == MODEL_AIR


def test_identity_cache_prefers_autov3_over_autov2(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    assert cache.put(_identity(), HashRecord(auto_v3="b" * 12)) == ()
    weaker_air = "urn:air:flux2:checkpoint:civitai:70@71"
    assert (
        cache.put(
            _identity(air=weaker_air, model_id=70, version_id=71),
            HashRecord(auto_v2="c" * 10),
        )
        == ()
    )

    result = cache.lookup(
        replace(
            model_resource(),
            hashes=HashRecord(auto_v3="b" * 12, auto_v2="c" * 10),
            identity=None,
            status=ResourceStatus.UNRESOLVED,
        )
    )

    assert result.status is ResourceStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == MODEL_AIR


def test_identity_cache_rejects_records_without_hash_or_identity(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    assert [issue.code for issue in cache.put(_identity(), HashRecord())] == [
        "identity_cache_record_invalid"
    ]
    assert [
        issue.code
        for issue in cache.put(
            ResourceIdentity(source=IdentitySource.CACHE),
            HashRecord(auto_v2="f" * 10),
        )
    ] == ["identity_cache_record_invalid"]


def test_identity_cache_scalar_guards_reject_invalid_values() -> None:
    assert local_cache_module._positive_int(True) is None
    assert local_cache_module._positive_int(0) is None
    assert local_cache_module._positive_int("1") is None
    assert local_cache_module._text("") is None
    assert local_cache_module._text("x" * 513) is None
    assert local_cache_module._text("unsafe\x00text") is None


def test_identity_cache_parser_rejects_invalid_record_shapes_and_air() -> None:
    identity, issues = local_cache_module._parse_identity("not-a-record")
    assert identity is None
    assert [issue.code for issue in issues] == ["identity_cache_record_invalid"]

    identity, issues = local_cache_module._parse_identity({"air": "not-an-air"})
    assert identity is None
    assert [issue.code for issue in issues] == ["air_structure_invalid"]

    identity, issues = local_cache_module._parse_identity(
        {
            "canonicalAir": MODEL_AIR,
            "modelId": MODEL_ID + 1,
        }
    )
    assert identity is None
    assert [issue.code for issue in issues] == ["identity_cache_model_id_conflict"]

    identity, issues = local_cache_module._parse_identity({"modelName": "No IDs"})
    assert identity is None
    assert [issue.code for issue in issues] == ["identity_cache_record_invalid"]

    identity, issues = local_cache_module._parse_identity(
        {
            "canonicalAir": MODEL_AIR,
            "fileId": "different-file",
        }
    )
    assert identity is None
    assert [issue.code for issue in issues] == ["air_file_id_conflict"]


def test_identity_cache_compares_partial_identities_and_unmatched_hashes() -> None:
    left = _identity(air=None)
    same = _identity(air=None)
    different = _identity(air=None, model_id=99, version_id=100)

    assert local_cache_module._same_identity(left, same) is True
    assert local_cache_module._same_identity(left, different) is False
    assert (
        local_cache_module._best_match_rank(
            HashRecord(sha256="a" * 64),
            HashRecord(sha256="b" * 64),
        )
        is None
    )


def test_identity_cache_skips_valid_nonmatching_records(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    assert cache.put(_identity(), HashRecord(sha256="a" * 64)) == ()
    assert (
        cache.put(
            _identity(
                air="urn:air:flux2:checkpoint:civitai:90@91",
                model_id=90,
                version_id=91,
            ),
            HashRecord(sha256="b" * 64),
        )
        == ()
    )

    result = cache.lookup(
        replace(
            model_resource(),
            hashes=HashRecord(sha256="a" * 64),
            identity=None,
            status=ResourceStatus.UNRESOLVED,
        )
    )

    assert result.status is ResourceStatus.RESOLVED
    assert result.identity is not None
    assert result.identity.canonical_air == MODEL_AIR
