from __future__ import annotations

import hashlib
import json
import os
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from civiscribe.domain import HashRecord
from civiscribe.identity import hashing
from civiscribe.identity.hashing import (
    AUTO_V1_OFFSET,
    AUTO_V1_SIZE,
    HashCache,
    HashCacheKey,
    hash_resource_file,
)
from civiscribe.identity.types import HashingMode, HashStatus, LocatedResourceFile


def _located(root: Path, name: str = "model.bin") -> LocatedResourceFile:
    return LocatedResourceFile(
        path=root / name,
        approved_root=root,
        category="checkpoints",
        selected_value=name,
    )


def _safetensors_bytes(payload: bytes) -> bytes:
    header = json.dumps(
        {
            "tensor": {
                "dtype": "U8",
                "shape": [len(payload)],
                "data_offsets": [0, len(payload)],
            }
        }
    )
    encoded = header.encode("utf-8")
    return struct.pack("<Q", len(encoded)) + encoded + payload


def test_full_hashing_computes_exact_supported_local_hashes(tmp_path: Path) -> None:
    payload = b"tensor payload"
    content = _safetensors_bytes(payload)
    path = tmp_path / "model.safetensors"
    path.write_bytes(content)
    result = hash_resource_file(_located(tmp_path, path.name), mode=HashingMode.FULL)
    sha256 = hashlib.sha256(content).hexdigest()
    assert result.status is HashStatus.COMPLETE
    assert result.hashes.sha256 == sha256
    assert result.hashes.auto_v2 == sha256[:10]
    assert result.hashes.auto_v3 == hashlib.sha256(payload).hexdigest()[:12]
    assert result.hashes.auto_v1 == hashlib.sha256(b"").hexdigest()[:8]
    assert result.hashes.crc32 is None
    assert result.hashes.blake3 is None
    assert result.issues == ()


def test_auto_v1_uses_legacy_offset_and_size(tmp_path: Path) -> None:
    prefix = b"x" * AUTO_V1_OFFSET
    block = b"y" * AUTO_V1_SIZE
    (tmp_path / "model.bin").write_bytes(prefix + block + b"ignored")
    result = hash_resource_file(_located(tmp_path), mode=HashingMode.CACHED_OR_FAST)
    assert result.status is HashStatus.FAST_PARTIAL
    assert result.hashes.auto_v1 == hashlib.sha256(block).hexdigest()[:8]
    assert result.hashes.sha256 is None
    assert [issue.code for issue in result.issues] == ["resource_full_hash_deferred"]


def test_cached_only_never_opens_uncached_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "model.bin").write_bytes(b"model")
    monkeypatch.setattr(
        Path,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("opened")),
    )
    result = hash_resource_file(_located(tmp_path), mode=HashingMode.CACHED_ONLY)
    assert result.status is HashStatus.SKIPPED_CACHED_ONLY


def test_persistent_cache_hit_avoids_file_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "model.bin").write_bytes(b"model")
    cache = HashCache(tmp_path / "hash-cache.json")
    first = hash_resource_file(
        _located(tmp_path),
        mode=HashingMode.FULL,
        cache=cache,
        clock=lambda: datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert first.status is HashStatus.COMPLETE
    cache_text = (tmp_path / "hash-cache.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in cache_text
    assert "C:\\Users\\" not in cache_text

    monkeypatch.setattr(
        hashing,
        "_full_hashes",
        lambda _path: (_ for _ in ()).throw(AssertionError("rehash")),
    )
    second = hash_resource_file(
        _located(tmp_path),
        mode=HashingMode.FULL,
        cache=cache,
    )
    assert second.status is HashStatus.CACHE_HIT
    assert second.cache_hit is True
    assert second.hashes == first.hashes


def test_cache_invalidates_when_mtime_changes(tmp_path: Path) -> None:
    path = tmp_path / "model.bin"
    path.write_bytes(b"one")
    cache = HashCache(tmp_path / "hash-cache.json")
    first = hash_resource_file(_located(tmp_path), mode=HashingMode.FULL, cache=cache)
    path.write_bytes(b"two")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    second = hash_resource_file(_located(tmp_path), mode=HashingMode.FULL, cache=cache)
    assert second.status is HashStatus.COMPLETE
    assert second.cache_hit is False
    assert second.hashes.sha256 != first.hashes.sha256


def test_hashing_rejects_files_outside_approved_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"private")
    result = hash_resource_file(
        LocatedResourceFile(outside, root, "checkpoints", "outside.bin"),
        mode=HashingMode.FULL,
    )
    assert result.status is HashStatus.FILE_NOT_APPROVED


def test_hashing_reports_missing_file(tmp_path: Path) -> None:
    result = hash_resource_file(_located(tmp_path), mode=HashingMode.FULL)
    assert result.status is HashStatus.FILE_NOT_FOUND
    assert [issue.code for issue in result.issues] == ["resource_file_not_found"]


def test_invalid_cache_identity_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "model.bin"
    path.write_bytes(b"model")
    result = hash_resource_file(
        LocatedResourceFile(path, tmp_path, "checkpoints", "../model.bin"),
        mode=HashingMode.FULL,
    )
    assert result.status is HashStatus.FILE_NOT_APPROVED
    assert [issue.code for issue in result.issues] == ["resource_cache_identity_invalid"]


def test_file_mutation_during_hash_is_discarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "model.bin"
    path.write_bytes(b"before")
    original = hashing._full_hashes

    def mutate(target: Path) -> object:
        result = original(target)
        target.write_bytes(b"after mutation")
        return result

    monkeypatch.setattr(hashing, "_full_hashes", mutate)
    result = hash_resource_file(_located(tmp_path), mode=HashingMode.FULL)
    assert result.status is HashStatus.FILE_CHANGED
    assert result.hashes.is_empty


def test_hash_read_failure_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "model.bin").write_bytes(b"model")
    monkeypatch.setattr(
        hashing,
        "_auto_v1",
        lambda _path: (_ for _ in ()).throw(OSError("private path")),
    )
    result = hash_resource_file(_located(tmp_path), mode=HashingMode.CACHED_OR_FAST)
    assert result.status is HashStatus.FAILED
    assert [issue.code for issue in result.issues] == ["resource_hash_failed"]


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"short",
        struct.pack("<Q", hashing.MAX_SAFETENSORS_HEADER_BYTES + 1),
        struct.pack("<Q", 2) + b"xx",
        struct.pack("<Q", 2) + b"[]",
    ],
)
def test_malformed_safetensors_never_invents_autov3(
    content: bytes,
    tmp_path: Path,
) -> None:
    (tmp_path / "model.safetensors").write_bytes(content)
    result = hash_resource_file(
        _located(tmp_path, "model.safetensors"),
        mode=HashingMode.FULL,
    )
    assert result.status is HashStatus.COMPLETE
    assert result.hashes.auto_v3 is None


def test_hashing_rejects_directory_target(tmp_path: Path) -> None:
    directory = tmp_path / "model.bin"
    directory.mkdir()

    result = hash_resource_file(_located(tmp_path), mode=HashingMode.FULL)

    assert result.status is HashStatus.FILE_NOT_APPROVED
    assert [issue.code for issue in result.issues] == ["resource_file_not_approved"]


def test_hash_cache_ignores_mismatched_and_malformed_records(tmp_path: Path) -> None:
    key = HashCacheKey("checkpoints", "model.bin", 5, 123)
    valid_hash = "a" * 64

    mismatched = HashCache(tmp_path / "mismatched-cache.json")
    assert mismatched.store.merge(
        {
            "cacheKey": key.token,
            "category": "loras",
            "selectedValue": key.selected_value,
            "size": key.size,
            "modifiedNs": key.modified_ns,
            "hashes": {"SHA256": valid_hash},
        }
    ).written
    assert mismatched.get(key) is None

    malformed = HashCache(tmp_path / "malformed-cache.json")
    assert malformed.store.merge(
        {
            "cacheKey": key.token,
            "category": key.category,
            "selectedValue": key.selected_value,
            "size": key.size,
            "modifiedNs": key.modified_ns,
            "hashes": {},
        }
    ).written
    assert malformed.get(key) is None


def test_full_hashing_collects_auto_v1_window(tmp_path: Path) -> None:
    block = b"v" * AUTO_V1_SIZE
    (tmp_path / "model.bin").write_bytes(b"\0" * AUTO_V1_OFFSET + block)

    result = hash_resource_file(_located(tmp_path), mode=HashingMode.FULL)

    assert result.status is HashStatus.COMPLETE
    assert result.hashes.auto_v1 == hashlib.sha256(block).hexdigest()[:8]


def test_naive_cache_timestamp_is_normalized_to_utc(tmp_path: Path) -> None:
    (tmp_path / "model.bin").write_bytes(b"model")
    cache_path = tmp_path / "hash-cache.json"
    cache = HashCache(cache_path)

    result = hash_resource_file(
        _located(tmp_path),
        mode=HashingMode.FULL,
        cache=cache,
        clock=lambda: datetime(2026, 7, 18, 12, 30),
    )

    assert result.status is HashStatus.COMPLETE
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["records"][0]["computedAt"] == "2026-07-18T12:30:00Z"
    assert result.hashes != HashRecord()
