"""Approved-root model hashing with a privacy-safe persistent cache."""

from __future__ import annotations

import hashlib
import json
import os
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..domain import HashRecord, ScanIssue
from ..serialization import dumps_json
from .cache_store import BoundedJsonCache
from .hash_values import hash_record_from_mapping, hash_record_to_mapping
from .types import HashingMode, HashStatus, LocatedResourceFile

AUTO_V1_OFFSET = 0x100000
AUTO_V1_SIZE = 0x10000
HASH_CHUNK_SIZE = 1024 * 1024
MAX_MODEL_BYTES = 64 * 1024 * 1024 * 1024
MAX_SAFETENSORS_HEADER_BYTES = 16 * 1024 * 1024
HASH_CACHE_SCHEMA = "ccollins-civiscribe.hash-cache"
_ASCII_CONTROL_BOUNDARY = 32
_SAFETENSORS_LENGTH_BYTES = 8
_MIN_SAFETENSORS_HEADER_BYTES = 2


@dataclass(frozen=True, slots=True)
class HashCacheKey:
    """Stable cache identity containing no absolute path."""

    category: str
    selected_value: str
    size: int
    modified_ns: int

    @property
    def token(self) -> str:
        """Return a deterministic opaque cache-record key."""

        source = dumps_json(
            {
                "category": self.category,
                "modifiedNs": self.modified_ns,
                "selectedValue": self.selected_value,
                "size": self.size,
            }
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HashResult:
    """Hashing result that is always safe to attach to diagnostics."""

    hashes: HashRecord = field(default_factory=HashRecord)
    status: HashStatus = HashStatus.FAILED
    issues: tuple[ScanIssue, ...] = ()
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class _ApprovedTarget:
    path: Path
    before: os.stat_result
    key: HashCacheKey


def _safe_relative(value: str) -> str | None:
    normalized = value.replace("\\", "/")
    windows = PureWindowsPath(value)
    posix = PurePosixPath(normalized)
    if (
        not normalized
        or windows.drive
        or windows.root
        or posix.is_absolute()
        or ":" in normalized
        or any(part in {"", ".", ".."} for part in posix.parts)
        or any(ord(character) < _ASCII_CONTROL_BOUNDARY for character in normalized)
    ):
        return None
    return normalized


def _cache_key(
    located: LocatedResourceFile,
    stat: os.stat_result,
) -> HashCacheKey | None:
    category = _safe_relative(located.category)
    selected = _safe_relative(located.selected_value)
    if category is None or selected is None:
        return None
    return HashCacheKey(category, selected, stat.st_size, stat.st_mtime_ns)


def _approved_target(located: LocatedResourceFile) -> _ApprovedTarget | HashResult:
    try:
        root = located.approved_root.resolve(strict=True)
        path = located.path.resolve(strict=True)
        path.relative_to(root)
        before = path.stat()
    except FileNotFoundError:
        return HashResult(
            status=HashStatus.FILE_NOT_FOUND,
            issues=(ScanIssue("resource_file_not_found"),),
        )
    except (OSError, ValueError):
        return HashResult(
            status=HashStatus.FILE_NOT_APPROVED,
            issues=(ScanIssue("resource_file_not_approved"),),
        )
    if not path.is_file() or before.st_size > MAX_MODEL_BYTES:
        return HashResult(
            status=HashStatus.FILE_NOT_APPROVED,
            issues=(ScanIssue("resource_file_not_approved"),),
        )
    key = _cache_key(located, before)
    if key is None:
        return HashResult(
            status=HashStatus.FILE_NOT_APPROVED,
            issues=(ScanIssue("resource_cache_identity_invalid"),),
        )
    return _ApprovedTarget(path, before, key)


class HashCache:
    """Versioned hash cache invalidated by size and nanosecond mtime."""

    def __init__(self, path: Path) -> None:
        self.store = BoundedJsonCache(path, schema_name=HASH_CACHE_SCHEMA)

    def get(self, key: HashCacheKey) -> HashResult | None:
        """Return a validated exact cache match."""

        read = self.store.read()
        for record in read.records:
            if record.get("cacheKey") != key.token:
                continue
            if (
                record.get("category") != key.category
                or record.get("selectedValue") != key.selected_value
                or record.get("size") != key.size
                or record.get("modifiedNs") != key.modified_ns
            ):
                continue
            hashes = hash_record_from_mapping(record.get("hashes"))
            if hashes is not None:
                return HashResult(
                    hashes,
                    HashStatus.CACHE_HIT,
                    read.issues,
                    cache_hit=True,
                )
        return None

    def put(
        self,
        key: HashCacheKey,
        hashes: HashRecord,
        *,
        timestamp: str,
    ) -> tuple[ScanIssue, ...]:
        """Persist known hashes without any local path."""

        result = self.store.merge(
            {
                "cacheKey": key.token,
                "category": key.category,
                "selectedValue": key.selected_value,
                "size": key.size,
                "modifiedNs": key.modified_ns,
                "computedAt": timestamp,
                "hashes": hash_record_to_mapping(hashes),
            }
        )
        return result.issues


def _auto_v1(path: Path) -> str:
    with path.open("rb") as handle:
        handle.seek(AUTO_V1_OFFSET)
        block = handle.read(AUTO_V1_SIZE)
    return hashlib.sha256(block).hexdigest()[:8]


def _safetensors_payload_offset(path: Path) -> int | None:
    if path.suffix.casefold() != ".safetensors":
        return None
    with path.open("rb") as handle:
        raw_length = handle.read(_SAFETENSORS_LENGTH_BYTES)
        if len(raw_length) != _SAFETENSORS_LENGTH_BYTES:
            return None
        header_length = struct.unpack("<Q", raw_length)[0]
        if (
            header_length < _MIN_SAFETENSORS_HEADER_BYTES
            or header_length > MAX_SAFETENSORS_HEADER_BYTES
        ):
            return None
        header = handle.read(header_length)
    try:
        decoded = json.loads(header.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return _SAFETENSORS_LENGTH_BYTES + header_length if isinstance(decoded, dict) else None


def _full_hashes(path: Path) -> HashRecord:
    payload_offset = _safetensors_payload_offset(path)
    full_digest = hashlib.sha256()
    payload_digest = hashlib.sha256() if payload_offset is not None else None
    auto_v1_bytes = bytearray()
    position = 0
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK_SIZE):
            full_digest.update(chunk)
            chunk_end = position + len(chunk)
            auto_start = max(position, AUTO_V1_OFFSET)
            auto_end = min(chunk_end, AUTO_V1_OFFSET + AUTO_V1_SIZE)
            if auto_start < auto_end:
                auto_v1_bytes.extend(chunk[auto_start - position : auto_end - position])
            if (
                payload_digest is not None
                and payload_offset is not None
                and chunk_end > payload_offset
            ):
                payload_start = max(position, payload_offset)
                payload_digest.update(chunk[payload_start - position :])
            position = chunk_end
    sha256 = full_digest.hexdigest()
    return HashRecord(
        auto_v1=hashlib.sha256(auto_v1_bytes).hexdigest()[:8],
        auto_v2=sha256[:10],
        auto_v3=(payload_digest.hexdigest()[:12] if payload_digest is not None else None),
        sha256=sha256,
    )


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and getattr(before, "st_ino", None) == getattr(after, "st_ino", None)
        and getattr(before, "st_dev", None) == getattr(after, "st_dev", None)
    )


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def hash_resource_file(
    located: LocatedResourceFile,
    *,
    mode: HashingMode = HashingMode.CACHED_OR_FAST,
    cache: HashCache | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> HashResult:
    """Resolve cached or permitted hashes from one approved model file."""

    target = _approved_target(located)
    if isinstance(target, HashResult):
        return target
    if cache is not None and (cached := cache.get(target.key)) is not None:
        return cached
    if mode is HashingMode.CACHED_ONLY:
        return HashResult(
            status=HashStatus.SKIPPED_CACHED_ONLY,
            issues=(ScanIssue("resource_hash_skipped_cached_only"),),
        )

    try:
        hashes = (
            _full_hashes(target.path)
            if mode is HashingMode.FULL
            else HashRecord(auto_v1=_auto_v1(target.path))
        )
        after = target.path.stat()
    except OSError:
        return HashResult(
            status=HashStatus.FAILED,
            issues=(ScanIssue("resource_hash_failed"),),
        )
    if not _same_file(target.before, after):
        return HashResult(
            status=HashStatus.FILE_CHANGED,
            issues=(ScanIssue("resource_changed_during_hashing"),),
        )

    status = HashStatus.COMPLETE if mode is HashingMode.FULL else HashStatus.FAST_PARTIAL
    issues = () if status is HashStatus.COMPLETE else (ScanIssue("resource_full_hash_deferred"),)
    if cache is not None:
        issues = (*issues, *cache.put(target.key, hashes, timestamp=_timestamp(clock)))
    return HashResult(hashes, status, issues)


__all__ = [
    "AUTO_V1_OFFSET",
    "AUTO_V1_SIZE",
    "HASH_CACHE_SCHEMA",
    "HashCache",
    "HashCacheKey",
    "HashResult",
    "hash_resource_file",
]
