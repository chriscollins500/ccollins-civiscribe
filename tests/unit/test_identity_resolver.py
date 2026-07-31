from __future__ import annotations

import hashlib
import json
import ssl
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Never, cast

import httpx
import pytest

from civiscribe.adapters.model_files import ModelRootLocator
from civiscribe.domain import (
    HashRecord,
    HashStatus,
    IdentitySource,
    LookupStatus,
    ResourceIdentity,
    ResourceKind,
    ResourceRecord,
    ResourceRole,
    ResourceStatus,
    ScanIssue,
)
from civiscribe.identity import resolver as resolver_module
from civiscribe.identity.air import parse_air
from civiscribe.identity.civitai_client import (
    CivitaiClient,
    CivitaiLookupConfig,
    CivitaiLookupResult,
)
from civiscribe.identity.local_cache import IdentityCache, IdentityCacheLookup
from civiscribe.identity.resolver import (
    HASHED_BUT_NO_CIVITAI_IDENTITY,
    IdentityResolutionOptions,
    IdentityServices,
    resolve_resource_identities,
    resolve_scan_identities,
)
from civiscribe.identity.types import HashingMode
from civiscribe.workflow import scan_workflow
from tests.projection_support import MODEL_ID, MODEL_VERSION_ID, model_resource

MODEL_AIR = f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}+2402203.safetensor"
OTHER_AIR = "urn:air:flux2:checkpoint:civitai:90@91"
SHA256 = "a" * 64
TLS_CONTEXTS = (("test", ssl.create_default_context()),)
EXPECTED_ROLE_CANDIDATES = 7
EXPECTED_RETRY_AFTER_SECONDS = 45


def _unresolved(*, hashes: HashRecord | None = None) -> ResourceRecord:
    return replace(
        model_resource(),
        hashes=hashes or HashRecord(),
        hash_status=HashStatus.NOT_ATTEMPTED,
        identity=None,
        status=ResourceStatus.UNRESOLVED,
        lookup_status=LookupStatus.NOT_ATTEMPTED,
        unresolved_reason=None,
    )


def _identity(
    air: str,
    *,
    source: IdentitySource,
) -> ResourceIdentity:
    parsed = parse_air(air, provenance=source)
    assert parsed.identity is not None
    return parsed.identity


def _api_payload(
    *,
    air: str = MODEL_AIR,
    model_id: int = MODEL_ID,
    version_id: int = MODEL_VERSION_ID,
    queried_hash: str = SHA256,
) -> dict[str, object]:
    return {
        "air": air,
        "id": version_id,
        "modelId": model_id,
        "name": "Version",
        "model": {"id": model_id, "name": "Model", "type": "Checkpoint"},
        "files": [
            {
                "id": 2402203,
                "hashes": (
                    {"SHA256": queried_hash}
                    if len(queried_hash) == len(SHA256)
                    else {"AutoV2": queried_hash}
                ),
                "metadata": {"format": "safetensor"},
            }
        ],
    }


def _api(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    enabled: bool = True,
) -> CivitaiClient:
    return CivitaiClient(
        CivitaiLookupConfig(enabled=enabled),
        transport=httpx.MockTransport(handler),
        tls_contexts=TLS_CONTEXTS,
    )


def _cache_identity(
    cache: IdentityCache,
    *,
    air: str = MODEL_AIR,
    hashes: HashRecord | None = None,
) -> None:
    assert (
        cache.put(
            _identity(air, source=IdentitySource.CACHE),
            hashes or HashRecord(sha256=SHA256),
        )
        == ()
    )


def test_manual_identity_outranks_preferred_cache_and_api(tmp_path: Path) -> None:
    cache = IdentityCache(tmp_path / "identities.json")
    _cache_identity(cache, air=OTHER_AIR)
    network_calls = 0

    def fail_if_called(_request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(500)

    resource = _unresolved(hashes=HashRecord(sha256=SHA256))
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        options=IdentityResolutionOptions(
            preferred_primary=OTHER_AIR,
            manual_json=json.dumps([{"match": {"resourceKey": resource.key}, "air": MODEL_AIR}]),
        ),
        services=IdentityServices(
            identity_cache=cache,
            civitai=_api(fail_if_called),
        ),
    )

    resolved = result.resources[0]
    assert resolved.identity is not None
    assert resolved.identity.source is IdentitySource.MANUAL
    assert resolved.identity.canonical_air == MODEL_AIR
    assert resolved.status is ResourceStatus.RESOLVED
    assert resolved.lookup_status is LookupStatus.NOT_ATTEMPTED
    assert network_calls == 0
    assert [issue.code for issue in result.issues] == ["identity_cache_lower_precedence_conflict"]


def test_manual_hash_selector_uses_hash_computed_before_matching(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    content = b"selected model bytes"
    (root / "model.gguf").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    resource = replace(_unresolved(), selected_value="model.gguf", filename="model.gguf")

    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        options=IdentityResolutionOptions(
            hashing_mode=HashingMode.FULL,
            manual_json=json.dumps([{"match": {"hashes": {"SHA256": digest}}, "air": MODEL_AIR}]),
        ),
        services=IdentityServices(locator=ModelRootLocator({"diffusion_models": [root]})),
    )

    resolved = result.resources[0]
    assert resolved.hash_status is HashStatus.COMPLETE
    assert resolved.hashes.sha256 == digest
    assert resolved.identity is not None
    assert resolved.identity.source is IdentitySource.MANUAL
    assert resolved.status is ResourceStatus.RESOLVED


def test_local_cache_rejects_parent_checkpoint_for_text_encoder(tmp_path: Path) -> None:
    cache = IdentityCache(tmp_path / "identities.json")
    _cache_identity(cache)
    resource = ResourceRecord(
        key="1:clip_name",
        role=ResourceRole.TEXT_ENCODER,
        kind=ResourceKind.CLIP,
        node_id="1",
        node_class="CLIPLoader",
        filename="qwen3vl_4b_fp8_scaled.safetensors",
        selected_value="qwen3vl_4b_fp8_scaled.safetensors",
        hashes=HashRecord(sha256=SHA256),
    )

    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=None,
        services=IdentityServices(identity_cache=cache),
    )

    resolved = result.resources[0]
    assert resolved.identity is None
    assert resolved.status is ResourceStatus.UNRESOLVED
    assert resolved.lookup_status is LookupStatus.SKIPPED_DISABLED
    assert resolved.unresolved_reason == "resource_type_mismatch"
    assert "identity_cache_resource_type_mismatch" in {issue.code for issue in result.issues}


def test_local_cache_accepts_exact_text_encoder_file_evidence(tmp_path: Path) -> None:
    cache = IdentityCache(tmp_path / "identities.json")
    identity = replace(
        _identity(MODEL_AIR, source=IdentitySource.CACHE),
        file_type="Text Encoder",
        file_primary=False,
    )
    assert cache.put(identity, HashRecord(sha256=SHA256)) == ()
    resource = ResourceRecord(
        key="1:clip_name",
        role=ResourceRole.TEXT_ENCODER,
        kind=ResourceKind.CLIP,
        node_id="1",
        node_class="CLIPLoader",
        filename="qwen3vl_4b_fp8_scaled.safetensors",
        selected_value="qwen3vl_4b_fp8_scaled.safetensors",
        hashes=HashRecord(sha256=SHA256),
    )

    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=None,
        services=IdentityServices(identity_cache=cache),
    )

    resolved = result.resources[0]
    assert resolved.identity is not None
    assert resolved.identity.file_type == "Text Encoder"
    assert resolved.status is ResourceStatus.RESOLVED
    assert resolved.lookup_status is LookupStatus.RESOLVED_BY_CACHE


def test_preferred_partial_identity_is_completed_by_official_api_air() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json=_api_payload())

    resource = _unresolved(hashes=HashRecord(sha256=SHA256))
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        options=IdentityResolutionOptions(preferred_primary=str(MODEL_VERSION_ID)),
        services=IdentityServices(civitai=_api(handler)),
    )

    resolved = result.resources[0]
    assert resolved.identity is not None
    assert resolved.identity.source is IdentitySource.PREFERRED
    assert resolved.identity.canonical_air == MODEL_AIR
    assert resolved.identity.resource_type == "checkpoint"
    assert resolved.status is ResourceStatus.RESOLVED
    assert resolved.lookup_status is LookupStatus.RESOLVED
    assert requests == [f"/api/v1/model-versions/{MODEL_VERSION_ID}"]


def test_compatible_local_cache_completes_preferred_identity_without_api(
    tmp_path: Path,
) -> None:
    cache = IdentityCache(tmp_path / "identities.json")
    _cache_identity(cache)
    resource = _unresolved(hashes=HashRecord(sha256=SHA256))
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        options=IdentityResolutionOptions(preferred_primary=str(MODEL_VERSION_ID)),
        services=IdentityServices(identity_cache=cache),
    )

    resolved = result.resources[0]
    assert resolved.identity is not None
    assert resolved.identity.source is IdentitySource.PREFERRED
    assert resolved.identity.canonical_air == MODEL_AIR
    assert resolved.status is ResourceStatus.RESOLVED
    assert resolved.lookup_status is LookupStatus.RESOLVED_BY_CACHE


def test_workflow_identity_outranks_conflicting_cache(tmp_path: Path) -> None:
    cache = IdentityCache(tmp_path / "identities.json")
    _cache_identity(cache, air=OTHER_AIR)
    resource = replace(
        _unresolved(hashes=HashRecord(sha256=SHA256)),
        identity=_identity(MODEL_AIR, source=IdentitySource.WORKFLOW),
        status=ResourceStatus.RESOLVED,
    )
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        services=IdentityServices(identity_cache=cache),
    )

    resolved = result.resources[0]
    assert resolved.identity is not None
    assert resolved.identity.source is IdentitySource.WORKFLOW
    assert resolved.identity.canonical_air == MODEL_AIR
    assert resolved.status is ResourceStatus.RESOLVED
    assert [issue.code for issue in result.issues] == ["identity_cache_lower_precedence_conflict"]


def test_local_cache_resolves_before_api(tmp_path: Path) -> None:
    cache = IdentityCache(tmp_path / "identities.json")
    _cache_identity(cache)
    network_calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(500)

    result = resolve_resource_identities(
        (_unresolved(hashes=HashRecord(sha256=SHA256)),),
        primary_resource_key=model_resource().key,
        services=IdentityServices(
            identity_cache=cache,
            civitai=_api(handler),
        ),
    )

    resolved = result.resources[0]
    assert resolved.identity is not None
    assert resolved.identity.source is IdentitySource.CACHE
    assert resolved.lookup_status is LookupStatus.RESOLVED_BY_CACHE
    assert network_calls == 0


def test_api_resolves_unidentified_hashed_resource() -> None:
    result = resolve_resource_identities(
        (_unresolved(hashes=HashRecord(sha256=SHA256)),),
        primary_resource_key=model_resource().key,
        services=IdentityServices(
            civitai=_api(lambda _request: httpx.Response(200, json=_api_payload()))
        ),
    )

    resolved = result.resources[0]
    assert resolved.identity is not None
    assert resolved.identity.source is IdentitySource.API
    assert resolved.status is ResourceStatus.RESOLVED
    assert resolved.lookup_status is LookupStatus.RESOLVED
    assert resolved.unresolved_reason is None


def test_unresolved_status_distinguishes_disabled_lookup_and_no_hash() -> None:
    hashed = resolve_resource_identities(
        (_unresolved(hashes=HashRecord(sha256=SHA256)),),
        primary_resource_key=model_resource().key,
    ).resources[0]
    assert hashed.lookup_status is LookupStatus.SKIPPED_DISABLED
    assert hashed.unresolved_reason == HASHED_BUT_NO_CIVITAI_IDENTITY

    no_hash = resolve_resource_identities(
        (_unresolved(),),
        primary_resource_key=model_resource().key,
        services=IdentityServices(civitai=_api(lambda _request: pytest.fail("network called"))),
    ).resources[0]
    assert no_hash.lookup_status is LookupStatus.SKIPPED_NO_HASH
    assert no_hash.unresolved_reason == "resource_hash_unavailable"


def test_api_stronger_hash_identity_outranks_weaker_hash_disagreement() -> None:
    auto_v2 = "b" * 10
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        queried_hash = request.url.path.rsplit("/", maxsplit=1)[-1]
        if queried_hash == SHA256:
            return httpx.Response(200, json=_api_payload())
        return httpx.Response(
            200,
            json=_api_payload(
                air=OTHER_AIR,
                model_id=90,
                version_id=91,
                queried_hash=auto_v2,
            ),
        )

    result = resolve_resource_identities(
        (_unresolved(hashes=HashRecord(sha256=SHA256, auto_v2=auto_v2)),),
        primary_resource_key=model_resource().key,
        services=IdentityServices(civitai=_api(handler)),
    )

    resource = result.resources[0]
    assert resource.status is ResourceStatus.RESOLVED
    assert resource.lookup_status is LookupStatus.RESOLVED
    assert resource.identity is not None
    assert resource.identity.canonical_air == MODEL_AIR
    assert resource.lookup_diagnostics.attempted_hash_types == ("SHA256",)
    assert resource.unresolved_reason is None
    assert len(requests) == 1


def test_api_same_hash_ambiguity_marks_unidentified_resource_conflicted() -> None:
    class ConflictingClient:
        def lookup(self, _resource: ResourceRecord) -> CivitaiLookupResult:
            return CivitaiLookupResult(
                status=LookupStatus.CONFLICT,
                attempted_hashes=("SHA256",),
                failure_reason="identity_conflict",
                diagnostic_reason="multiple_compatible_candidates_conflict",
                issues=(ScanIssue("civitai_identity_conflict"),),
            )

    result = resolve_resource_identities(
        (_unresolved(hashes=HashRecord(sha256=SHA256)),),
        primary_resource_key=model_resource().key,
        services=IdentityServices(civitai=cast("CivitaiClient", ConflictingClient())),
    )

    resource = result.resources[0]
    assert resource.status is ResourceStatus.CONFLICT
    assert resource.lookup_status is LookupStatus.CONFLICT
    assert resource.identity is None
    assert resource.unresolved_reason == "civitai_identity_conflict"
    assert resource.lookup_diagnostics.attempted_hash_types == ("SHA256",)
    assert [issue.code for issue in result.issues] == ["civitai_identity_conflict"]


def test_hash_locator_cache_and_api_failures_remain_nonfatal(
    tmp_path: Path,
) -> None:
    class RaisingLocator:
        def locate(self, _resource: ResourceRecord) -> Never:
            raise OSError("private path")

    cache = IdentityCache(tmp_path / "identities.json")
    cache.store.path.write_text("{", encoding="utf-8")
    client = _api(lambda _request: (_ for _ in ()).throw(RuntimeError("private")))
    result = resolve_resource_identities(
        (_unresolved(hashes=HashRecord(sha256=SHA256)),),
        primary_resource_key=model_resource().key,
        services=IdentityServices(
            locator=RaisingLocator(),
            identity_cache=cache,
            civitai=client,
        ),
    )

    resource = result.resources[0]
    assert resource.hash_status is HashStatus.FAILED
    assert resource.lookup_status is LookupStatus.FAILED
    assert resource.status is ResourceStatus.UNRESOLVED
    assert [issue.code for issue in result.issues] == [
        "resource_file_location_failed",
        "cache_json_invalid",
        "civitai_lookup_failed",
    ]
    assert all("private" not in issue.code for issue in result.issues)


def test_missing_model_file_and_hash_exception_are_nonfatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingLocator:
        def locate(self, _resource: ResourceRecord) -> None:
            return None

    missing = resolve_resource_identities(
        (_unresolved(),),
        primary_resource_key=model_resource().key,
        services=IdentityServices(
            locator=cast("ModelRootLocator", MissingLocator()),
        ),
    )

    assert missing.resources[0].hash_status is HashStatus.FILE_NOT_FOUND
    assert [issue.code for issue in missing.issues] == ["resource_file_not_found"]

    class LocatedLocator:
        def locate(self, _resource: ResourceRecord) -> object:
            return object()

    monkeypatch.setattr(
        resolver_module,
        "hash_resource_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("private path")),
    )
    failed = resolve_resource_identities(
        (_unresolved(),),
        primary_resource_key=model_resource().key,
        services=IdentityServices(
            locator=cast("ModelRootLocator", LocatedLocator()),
        ),
    )

    assert failed.resources[0].hash_status is HashStatus.FAILED
    assert failed.resources[0].status is ResourceStatus.UNRESOLVED
    assert [issue.code for issue in failed.issues] == ["resource_hash_failed"]


def test_workflow_civitai_air_without_version_stays_partial() -> None:
    identity = _identity(
        "urn:air:flux2:checkpoint:civitai:123",
        source=IdentitySource.WORKFLOW,
    )
    resource = replace(
        _unresolved(),
        identity=identity,
        status=ResourceStatus.PARTIAL,
    )

    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
    )

    resolved = result.resources[0]
    assert resolved.identity is not None
    assert resolved.identity.canonical_air == "urn:air:flux2:checkpoint:civitai:123"
    assert resolved.identity.model_version_id is None
    assert resolved.status is ResourceStatus.PARTIAL
    assert resolved.lookup_status is LookupStatus.SKIPPED_DISABLED
    assert resolved.unresolved_reason == "identity_incomplete"


def test_identity_merge_accepts_file_specific_air_refinement() -> None:
    parent_air = f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}"
    higher = _identity(parent_air, source=IdentitySource.WORKFLOW)
    lower = _identity(MODEL_AIR, source=IdentitySource.API)

    assert resolver_module._identities_compatible(higher, lower)
    merged = resolver_module._merge_identity(higher, lower)
    assert merged.raw_air == parent_air
    assert merged.canonical_air == MODEL_AIR
    assert merged.file_id == "2402203"
    assert merged.format == "safetensor"


def test_identity_merge_rejects_conflicting_file_ids() -> None:
    higher = _identity(MODEL_AIR, source=IdentitySource.WORKFLOW)
    lower = _identity(
        f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}+999.safetensor",
        source=IdentitySource.API,
    )

    assert not resolver_module._identities_compatible(higher, lower)


def test_identity_compatibility_accepts_equivalent_file_format_case() -> None:
    higher = _identity(MODEL_AIR, source=IdentitySource.WORKFLOW)
    lower = replace(
        _identity(MODEL_AIR, source=IdentitySource.API),
        canonical_air=MODEL_AIR.replace(".safetensor", ".SAFETENSOR"),
        format="SAFETENSOR",
    )

    assert resolver_module._identities_compatible(higher, lower)


def test_identity_compatibility_rejects_malformed_canonical_air() -> None:
    higher = replace(
        _identity(MODEL_AIR, source=IdentitySource.WORKFLOW),
        canonical_air="not-an-air",
    )
    lower = _identity(MODEL_AIR, source=IdentitySource.API)

    assert not resolver_module._identities_compatible(higher, lower)


def test_identity_merge_preserves_valid_air_when_file_refinement_is_invalid() -> None:
    higher = _identity(
        f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}",
        source=IdentitySource.WORKFLOW,
    )
    lower = ResourceIdentity(
        source=IdentitySource.API,
        file_id="invalid+file",
    )

    merged = resolver_module._merge_identity(higher, lower)

    assert merged.canonical_air == higher.canonical_air
    assert merged.file_id is None
    assert merged.format is None


def test_identity_merge_preserves_higher_file_facts() -> None:
    higher = _identity(MODEL_AIR, source=IdentitySource.WORKFLOW)
    lower = ResourceIdentity(source=IdentitySource.API)

    merged = resolver_module._merge_identity(higher, lower)

    assert merged.canonical_air == MODEL_AIR
    assert merged.file_id == "2402203"
    assert merged.format == "safetensor"


def test_identity_merge_leaves_file_facts_empty_when_both_are_unqualified() -> None:
    parent_air = f"urn:air:flux2:checkpoint:civitai:{MODEL_ID}@{MODEL_VERSION_ID}"
    higher = _identity(parent_air, source=IdentitySource.WORKFLOW)
    lower = ResourceIdentity(source=IdentitySource.API)

    merged = resolver_module._merge_identity(higher, lower)

    assert merged.canonical_air == parent_air
    assert merged.file_id is None
    assert merged.format is None


def test_conflicting_workflow_air_ids_are_removed_nonfatally() -> None:
    identity = replace(
        _identity(MODEL_AIR, source=IdentitySource.WORKFLOW),
        model_id=999,
    )
    resource = replace(
        _unresolved(),
        identity=identity,
        status=ResourceStatus.RESOLVED,
    )

    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
    )

    resolved = result.resources[0]
    assert resolved.identity is None
    assert resolved.status is ResourceStatus.CONFLICT
    assert resolved.unresolved_reason == "workflow_identity_conflict"
    assert [issue.code for issue in result.issues] == ["workflow_identity_conflict"]


def test_identity_cache_exception_is_nonfatal() -> None:
    class RaisingCache:
        def lookup(self, _resource: ResourceRecord) -> Never:
            raise OSError("private cache path")

    result = resolve_resource_identities(
        (_unresolved(hashes=HashRecord(sha256=SHA256)),),
        primary_resource_key=model_resource().key,
        services=IdentityServices(
            identity_cache=cast("IdentityCache", RaisingCache()),
        ),
    )

    resolved = result.resources[0]
    assert resolved.status is ResourceStatus.UNRESOLVED
    assert resolved.lookup_status is LookupStatus.SKIPPED_DISABLED
    assert resolved.unresolved_reason == HASHED_BUT_NO_CIVITAI_IDENTITY
    assert [issue.code for issue in result.issues] == ["identity_cache_read_failed"]


def test_api_role_mismatch_sets_specific_unresolved_reason() -> None:
    class RoleMismatchClient:
        def lookup(self, _resource: ResourceRecord) -> CivitaiLookupResult:
            return CivitaiLookupResult(
                status=LookupStatus.FAILED,
                failure_reason="no_matching_result",
                issues=(ScanIssue("civitai_response_type_mismatch"),),
            )

        def complete_version(
            self,
            _resource: ResourceRecord,
            _model_version_id: int,
        ) -> Never:
            raise AssertionError("resource has no partial identity")

    resource = _unresolved(hashes=HashRecord(sha256=SHA256))
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        services=IdentityServices(
            civitai=cast("CivitaiClient", RoleMismatchClient()),
        ),
    )

    resolved = result.resources[0]
    assert resolved.status is ResourceStatus.UNRESOLVED
    assert resolved.lookup_status is LookupStatus.FAILED
    assert resolved.unresolved_reason == "resource_type_mismatch"
    assert [issue.code for issue in result.issues] == ["civitai_response_type_mismatch"]


def test_cache_conflicts_preserve_precedence_and_deduplicate_issues() -> None:
    class ConflictingCache:
        def lookup(self, resource: ResourceRecord) -> IdentityCacheLookup:
            issue = ScanIssue("identity_cache_conflict", node_id=resource.node_id)
            return IdentityCacheLookup(
                status=ResourceStatus.CONFLICT,
                issues=(issue, issue),
            )

    unidentified = replace(
        _unresolved(hashes=HashRecord(sha256=SHA256)),
        node_id="unidentified",
    )
    workflow = replace(
        _unresolved(hashes=HashRecord(sha256=SHA256)),
        node_id="workflow",
        identity=_identity(MODEL_AIR, source=IdentitySource.WORKFLOW),
        status=ResourceStatus.RESOLVED,
    )

    result = resolve_resource_identities(
        (unidentified, workflow),
        primary_resource_key=workflow.key,
        services=IdentityServices(
            identity_cache=cast("IdentityCache", ConflictingCache()),
        ),
    )

    conflicted, preserved = result.resources
    assert conflicted.status is ResourceStatus.CONFLICT
    assert conflicted.unresolved_reason == "identity_cache_conflict"
    assert preserved.identity is not None
    assert preserved.identity.source is IdentitySource.WORKFLOW
    assert preserved.status is ResourceStatus.RESOLVED
    assert [issue.code for issue in result.issues] == [
        "identity_cache_conflict",
        "identity_cache_conflict",
        "identity_cache_lower_precedence_conflict",
    ]


def test_identity_source_mismatch_rejects_lower_cache_identity() -> None:
    higher = ResourceIdentity(
        source=IdentitySource.WORKFLOW,
        identity_source="civitai",
        model_id=MODEL_ID,
        model_version_id=MODEL_VERSION_ID,
    )
    lower = replace(
        higher,
        source=IdentitySource.CACHE,
        identity_source="civitai-r2",
    )

    class SourceMismatchCache:
        def lookup(self, resource: ResourceRecord) -> IdentityCacheLookup:
            return IdentityCacheLookup(
                identity=lower,
                hashes=resource.hashes,
                status=ResourceStatus.PARTIAL,
            )

    resource = replace(
        _unresolved(hashes=HashRecord(sha256=SHA256)),
        identity=higher,
        status=ResourceStatus.PARTIAL,
    )
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        services=IdentityServices(
            identity_cache=cast("IdentityCache", SourceMismatchCache()),
        ),
    )

    resolved = result.resources[0]
    assert resolved.identity == higher
    assert resolved.status is ResourceStatus.PARTIAL
    assert resolved.unresolved_reason == "identity_incomplete"
    assert [issue.code for issue in result.issues] == ["identity_cache_lower_precedence_conflict"]


@pytest.mark.parametrize("api_status", [LookupStatus.RESOLVED, LookupStatus.CONFLICT])
def test_api_cannot_replace_higher_precedence_partial_identity(
    api_status: LookupStatus,
) -> None:
    higher = ResourceIdentity(
        source=IdentitySource.PREFERRED,
        identity_source="civitai",
        model_id=MODEL_ID,
        model_version_id=MODEL_VERSION_ID,
    )
    lower = _identity(OTHER_AIR, source=IdentitySource.API)

    class LowerPrecedenceClient:
        def complete_version(
            self,
            _resource: ResourceRecord,
            _model_version_id: int,
        ) -> CivitaiLookupResult:
            return CivitaiLookupResult(
                identity=lower if api_status is LookupStatus.RESOLVED else None,
                status=api_status,
                issues=(ScanIssue("civitai_identity_conflict"),),
            )

        def lookup(self, _resource: ResourceRecord) -> Never:
            raise AssertionError("partial identity must use version completion")

    resource = replace(
        _unresolved(hashes=HashRecord(sha256=SHA256)),
        identity=higher,
        status=ResourceStatus.PARTIAL,
    )
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        services=IdentityServices(
            civitai=cast("CivitaiClient", LowerPrecedenceClient()),
        ),
    )

    resolved = result.resources[0]
    assert resolved.identity == higher
    assert resolved.status is ResourceStatus.PARTIAL
    assert resolved.lookup_status is LookupStatus.CONFLICT
    assert resolved.unresolved_reason == "identity_incomplete"
    expected = (
        ["civitai_identity_conflict", "civitai_lower_precedence_identity_conflict"]
        if api_status is LookupStatus.RESOLVED
        else ["civitai_identity_conflict"]
    )
    assert [issue.code for issue in result.issues] == expected


def test_api_lookup_diagnostics_propagate_to_resource() -> None:
    class DiagnosticClient:
        def lookup(self, _resource: ResourceRecord) -> CivitaiLookupResult:
            return CivitaiLookupResult(
                status=LookupStatus.FAILED,
                attempted_hashes=("SHA256", "AutoV2"),
                failure_reason="no_matching_result",
                http_status=httpx.codes.OK,
                retryable=False,
                retry_after_seconds=EXPECTED_RETRY_AFTER_SECONDS,
                tls_source="system_default",
                diagnostic_reason="no_role_compatible_shared_hash_candidate",
                candidate_count=EXPECTED_ROLE_CANDIDATES,
                compatible_candidate_count=0,
            )

    resource = _unresolved(hashes=HashRecord(sha256=SHA256))
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        services=IdentityServices(civitai=cast("CivitaiClient", DiagnosticClient())),
    )

    resolved = result.resources[0]
    diagnostics = resolved.lookup_diagnostics
    assert resolved.lookup_status is LookupStatus.FAILED
    assert diagnostics.attempted_hash_types == ("SHA256", "AutoV2")
    assert diagnostics.reason == "no_role_compatible_shared_hash_candidate"
    assert diagnostics.http_status == httpx.codes.OK
    assert diagnostics.retryable is False
    assert diagnostics.retry_after_seconds == EXPECTED_RETRY_AFTER_SECONDS
    assert diagnostics.tls_source == "system_default"
    assert diagnostics.candidate_count == EXPECTED_ROLE_CANDIDATES
    assert diagnostics.compatible_candidate_count == 0


def test_api_lookup_diagnostics_redact_untrusted_values() -> None:
    class HostileDiagnosticClient:
        def lookup(self, _resource: ResourceRecord) -> CivitaiLookupResult:
            return CivitaiLookupResult(
                status=LookupStatus.FAILED,
                attempted_hashes=(
                    "SHA256",
                    r"C:\Users\person\private",
                    "Bearer private-token",
                ),
                failure_reason="Bearer private-token",
                http_status=999,
                retryable=True,
                tls_source=r"C:\Users\person\certificate.pem",
                diagnostic_reason="private prompt text",
                candidate_count=10_000,
                compatible_candidate_count=-1,
            )

    resource = _unresolved(hashes=HashRecord(sha256=SHA256))
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        services=IdentityServices(civitai=cast("CivitaiClient", HostileDiagnosticClient())),
    )

    diagnostics = result.resources[0].lookup_diagnostics
    assert diagnostics.attempted_hash_types == ("SHA256",)
    assert diagnostics.reason == "lookup_diagnostic_redacted"
    assert diagnostics.http_status is None
    assert diagnostics.retryable is True
    assert diagnostics.tls_source is None
    assert diagnostics.candidate_count is None
    assert diagnostics.compatible_candidate_count is None
    assert "private" not in repr(diagnostics).casefold()
    assert "users" not in repr(diagnostics).casefold()
    assert "bearer" not in repr(diagnostics).casefold()


def test_explicit_identity_failure_is_nonfatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resolver_module,
        "apply_explicit_identities",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("private input")),
    )
    resource = _unresolved(hashes=HashRecord(sha256=SHA256))

    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        options=IdentityResolutionOptions(
            preferred_primary=MODEL_AIR,
            manual_json="[]",
        ),
    )

    resolved = result.resources[0]
    assert resolved.identity is None
    assert resolved.status is ResourceStatus.UNRESOLVED
    assert resolved.lookup_status is LookupStatus.SKIPPED_DISABLED
    assert resolved.unresolved_reason == HASHED_BUT_NO_CIVITAI_IDENTITY
    assert [issue.code for issue in result.issues] == ["explicit_identity_resolution_failed"]


def test_api_cache_write_failure_does_not_undo_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = IdentityCache(tmp_path / "identities.json")
    monkeypatch.setattr(
        cache,
        "put",
        lambda _identity, _hashes: (_ for _ in ()).throw(OSError("disk")),
    )
    result = resolve_resource_identities(
        (_unresolved(hashes=HashRecord(sha256=SHA256)),),
        primary_resource_key=model_resource().key,
        options=IdentityResolutionOptions(cache_api_results=True),
        services=IdentityServices(
            identity_cache=cache,
            civitai=_api(lambda _request: httpx.Response(200, json=_api_payload())),
        ),
    )

    assert result.resources[0].status is ResourceStatus.RESOLVED
    assert [issue.code for issue in result.issues] == ["identity_cache_write_failed"]


def test_malformed_workflow_air_is_removed_without_crashing() -> None:
    resource = replace(
        _unresolved(),
        identity=ResourceIdentity(
            source=IdentitySource.WORKFLOW,
            raw_air="not:an:air",
        ),
    )
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
    )

    resolved = result.resources[0]
    assert resolved.identity is None
    assert resolved.status is ResourceStatus.UNRESOLVED
    assert resolved.unresolved_reason == "resource_hash_unavailable"
    assert [issue.code for issue in result.issues] == ["air_structure_invalid"]


def test_computed_hash_conflict_uses_local_file_and_warns(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    content = b"actual"
    (root / "model.gguf").write_bytes(content)
    actual = hashlib.sha256(content).hexdigest()
    resource = replace(
        _unresolved(hashes=HashRecord(sha256="f" * 64)),
        selected_value="model.gguf",
        filename="model.gguf",
    )
    result = resolve_resource_identities(
        (resource,),
        primary_resource_key=resource.key,
        options=IdentityResolutionOptions(hashing_mode=HashingMode.FULL),
        services=IdentityServices(locator=ModelRootLocator({"diffusion_models": [root]})),
    )

    assert result.resources[0].hashes.sha256 == actual
    assert [issue.code for issue in result.issues] == ["resource_hash_conflict"]


def test_resolve_scan_identities_preserves_scan_and_appends_diagnostics() -> None:
    prompt = {
        "1": {
            "class_type": "SaveImageWithCivitaiMetadata",
            "inputs": {"images": ["2", 0]},
        },
        "2": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 0]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["5", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["8", 0],
                "seed": 1,
                "steps": 2,
                "cfg": 3.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
            },
        },
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "vae.safetensors"}},
        "5": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "model.safetensors"},
        },
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
        "8": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 64, "height": 64, "batch_size": 1},
        },
    }
    scan = scan_workflow(prompt, save_node_id="1")

    resolved = resolve_scan_identities(scan)

    assert resolved.save_node_id == scan.save_node_id
    assert len(resolved.resources) == len(scan.resources)
    assert all(
        resource.lookup_status is LookupStatus.SKIPPED_DISABLED for resource in resolved.resources
    )
