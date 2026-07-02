"""Local file hashing with in-memory and persistent safe-key caches."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import zlib
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .autov2 import (
    AUTO_V1_OFFSET,
    AUTO_V1_SIZE,
    compute_autov1_from_chunk,
    compute_autov2_from_sha256,
    should_compute_autov2,
)
from ..metadata.schema import HashMetadata, ValidationIssue

CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_HASH_BYTES = 64 * 1024 * 1024 * 1024
DEFAULT_FAST_HASH_BYTES = 512 * 1024 * 1024
HASH_CACHE_FORMAT_VERSION = "1"
HASHING_MODES = {"cached_only", "cached_or_fast", "full"}
SAFETENSORS_HEADER_LIMIT = 16 * 1024 * 1024
_HEX_RE = re.compile(r"^[A-Fa-f0-9]+$")


@dataclass(frozen=True)
class HashCacheKey:
    category: str
    selected_value: str
    size: int
    modified_ns: int


@dataclass(frozen=True)
class HashCacheIdentity:
    category: str
    selected_value: str


@dataclass(frozen=True)
class FileHashResult:
    hashes: HashMetadata
    status: str
    source: str | None = None
    warning: ValidationIssue | None = None
    cache_hit: bool = False


class HashCache:
    """Hash cache keyed by safe model category, selected value, size, and mtime."""

    def __init__(self, persistent_path: Path | None = None) -> None:
        self.persistent_path = persistent_path
        self._entries: dict[HashCacheKey, tuple[HashMetadata, str]] = {}
        self.hits = 0
        self.misses = 0
        self.warnings: tuple[ValidationIssue, ...] = ()
        if self.persistent_path is not None:
            self._load()

    def get(self, key: HashCacheKey) -> HashMetadata | None:
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        return entry[0]

    def set(self, key: HashCacheKey, value: HashMetadata) -> None:
        self._entries[key] = (value, _utc_now_text())
        self._save()

    def _load(self) -> None:
        assert self.persistent_path is not None
        if not self.persistent_path.exists():
            return
        try:
            data = json.loads(self.persistent_path.read_text(encoding="utf-8"))
            records = data.get("records", []) if isinstance(data, dict) else []
            if not isinstance(records, list):
                raise ValueError("hash cache records must be a list")
            entries: dict[HashCacheKey, tuple[HashMetadata, str]] = {}
            for record in records:
                parsed = _parse_cache_record(record)
                if parsed is not None:
                    key, hashes, timestamp = parsed
                    entries[key] = (hashes, timestamp)
            self._entries = entries
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._entries = {}
            self.warnings = (
                ValidationIssue(
                    code="hash_cache_corrupt",
                    message="Persistent hash cache could not be read and was ignored",
                    field="hashCache",
                ),
            )

    def _save(self) -> None:
        if self.persistent_path is None:
            return
        records = []
        for key, (hashes, timestamp) in sorted(
            self._entries.items(),
            key=lambda item: (item[0].category, item[0].selected_value, item[0].size, item[0].modified_ns),
        ):
            records.append(
                {
                    "category": key.category,
                    "selectedValue": key.selected_value,
                    "size": key.size,
                    "modifiedTimeNs": key.modified_ns,
                    "hashTimestamp": timestamp,
                    "hashes": hashes.to_json(),
                }
            )
        payload = {
            "formatVersion": HASH_CACHE_FORMAT_VERSION,
            "records": records,
        }
        try:
            self.persistent_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.persistent_path.with_name(f"{self.persistent_path.name}.tmp")
            tmp_path.write_text(
                json.dumps(
                    payload,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            os.replace(tmp_path, self.persistent_path)
        except OSError:
            self.warnings = (
                *self.warnings,
                ValidationIssue(
                    code="hash_cache_write_failed",
                    message="Persistent hash cache could not be written",
                    field="hashCache",
                ),
            )


def compute_file_hashes(
    path: Path,
    *,
    cache: HashCache | None = None,
    cache_identity: HashCacheIdentity | None = None,
    max_size_bytes: int = DEFAULT_MAX_HASH_BYTES,
    include_autov2: bool = True,
    hashing_mode: str = "full",
) -> FileHashResult:
    """Compute hashes for an already-safe resolved model file path."""

    try:
        resolved_path = path.resolve(strict=True)
        stat = resolved_path.stat()
    except OSError:
        return FileHashResult(
            hashes=HashMetadata(),
            status="hash_failed",
            warning=ValidationIssue(
                code="resource_hash_failed",
                message="Resource file could not be inspected before hashing",
                field="resources",
            ),
        )

    if not resolved_path.is_file():
        return FileHashResult(
            hashes=HashMetadata(),
            status="unreadable",
            warning=ValidationIssue(
                code="resource_file_unreadable",
                message="Resource path is not a readable file",
                field="resources",
            ),
        )

    mode = _safe_hashing_mode(hashing_mode)
    if stat.st_size > max_size_bytes:
        return FileHashResult(
            hashes=HashMetadata(),
            status="too_large",
            warning=ValidationIssue(
                code="resource_hash_size_exceeded",
                message="Resource file exceeds configured hash size guard",
                field="resources",
            ),
        )

    identity = cache_identity or HashCacheIdentity(category="file", selected_value=resolved_path.name)
    key = HashCacheKey(
        category=_safe_cache_category(identity.category),
        selected_value=_safe_cache_selected_value(identity.selected_value),
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
    )
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return FileHashResult(
                hashes=cached,
                status="hashed",
                source="local_file_cache",
                cache_hit=True,
            )

    if mode == "cached_only":
        return FileHashResult(
            hashes=HashMetadata(),
            status="hash_skipped_cached_only",
            warning=ValidationIssue(
                code="resource_hash_skipped_cached_only",
                message="Resource hashing was skipped because hashing_mode is cached_only and no cache entry matched",
                field="resources",
            ),
        )

    try:
        fast_hashes = _fast_hashes(resolved_path)
    except OSError:
        return FileHashResult(
            hashes=HashMetadata(),
            status="unreadable",
            warning=ValidationIssue(
                code="resource_file_unreadable",
                message="Resource file could not be read for hashing",
                field="resources",
            ),
        )

    full_hashes_allowed = mode == "full" or (mode == "cached_or_fast" and stat.st_size <= DEFAULT_FAST_HASH_BYTES)
    if not full_hashes_allowed:
        if cache is not None and not fast_hashes.is_empty:
            cache.set(key, fast_hashes)
        return FileHashResult(
            hashes=fast_hashes,
            status="hashed_fast_partial" if not fast_hashes.is_empty else "hash_skipped_slow",
            source="local_file_fast" if not fast_hashes.is_empty else None,
            warning=ValidationIssue(
                code="resource_hash_skipped_slow",
                message="Full resource hashing was skipped because the file was not already cached and is too large for fast hashing mode",
                field="resources",
            ),
        )

    try:
        full_hashes = _full_hashes(
            resolved_path,
            include_autov2=include_autov2,
            fast_hashes=fast_hashes,
        )
    except OSError:
        return FileHashResult(
            hashes=HashMetadata(),
            status="unreadable",
            warning=ValidationIssue(
                code="resource_file_unreadable",
                message="Resource file could not be read for hashing",
                field="resources",
            ),
        )

    if cache is not None:
        cache.set(key, full_hashes)

    return FileHashResult(
        hashes=full_hashes,
        status="hashed",
        source="local_file",
    )


def default_hash_cache_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "civitai_hash_cache.json"


def _fast_hashes(path: Path) -> HashMetadata:
    return HashMetadata(
        auto_v1=_auto_v1(path),
        auto_v3=_auto_v3_from_safetensors_metadata(path),
    )


def _full_hashes(
    path: Path,
    *,
    include_autov2: bool,
    fast_hashes: HashMetadata,
) -> HashMetadata:
    sha256 = _sha256(path)
    return HashMetadata(
        sha256=sha256,
        auto_v1=fast_hashes.auto_v1,
        auto_v2=compute_autov2_from_sha256(sha256) if include_autov2 and should_compute_autov2(path.name) else None,
        auto_v3=fast_hashes.auto_v3,
        crc32=_crc32(path),
        blake3=_blake3(path),
    )


def _auto_v1(path: Path) -> str:
    with path.open("rb") as file:
        file.seek(AUTO_V1_OFFSET)
        return compute_autov1_from_chunk(file.read(AUTO_V1_SIZE))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _crc32(path: Path) -> str:
    value = 0
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            value = zlib.crc32(chunk, value)
    return f"{value & 0xFFFFFFFF:08X}"


def _blake3(path: Path) -> str | None:
    try:
        import blake3 as blake3_module  # type: ignore[import-not-found]
    except ImportError:
        return None
    digest = blake3_module.blake3()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _auto_v3_from_safetensors_metadata(path: Path) -> str | None:
    if path.suffix.lower() != ".safetensors":
        return None
    try:
        with path.open("rb") as file:
            header_size_bytes = file.read(8)
            if len(header_size_bytes) != 8:
                return None
            header_size = struct.unpack("<Q", header_size_bytes)[0]
            if header_size <= 0 or header_size > SAFETENSORS_HEADER_LIMIT:
                return None
            header = json.loads(file.read(header_size).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, struct.error):
        return None
    if not isinstance(header, dict):
        return None
    metadata = header.get("__metadata__")
    if not isinstance(metadata, dict):
        return None
    for key in ("sshs_model_hash", "sshs_legacy_hash", "modelspec.hash_sha256"):
        value = metadata.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower()
        if len(normalized) >= 12 and _HEX_RE.fullmatch(normalized):
            return normalized[:12]
    return None


def _safe_hashing_mode(value: str) -> str:
    mode = str(value or "cached_or_fast").strip().lower()
    return mode if mode in HASHING_MODES else "cached_or_fast"


def _parse_cache_record(record: Any) -> tuple[HashCacheKey, HashMetadata, str] | None:
    if not isinstance(record, dict):
        return None
    hashes = record.get("hashes")
    if not isinstance(hashes, dict):
        return None
    key = HashCacheKey(
        category=_safe_cache_category(record.get("category")),
        selected_value=_safe_cache_selected_value(record.get("selectedValue")),
        size=int(record.get("size")),
        modified_ns=int(record.get("modifiedTimeNs")),
    )
    hash_metadata = HashMetadata(
        sha256=_string_or_none(hashes.get("SHA256")),
        auto_v1=_string_or_none(hashes.get("AutoV1")),
        auto_v2=_string_or_none(hashes.get("AutoV2")),
        auto_v3=_string_or_none(hashes.get("AutoV3")),
        crc32=_string_or_none(hashes.get("CRC32")),
        blake3=_string_or_none(hashes.get("BLAKE3")),
    )
    return key, hash_metadata, _string_or_none(record.get("hashTimestamp")) or _utc_now_text()


def _safe_cache_category(value: Any) -> str:
    text = str(value or "model").strip().replace("\\", "/")
    parts = [part for part in text.split("/") if part and part not in {".", ".."}]
    safe = "_".join(parts)[:80]
    return safe or "model"


def _safe_cache_selected_value(value: Any) -> str:
    text = str(value or "model").strip().replace("\\", "/")
    if _looks_windows_absolute(text) or text.startswith("/"):
        text = text.rsplit("/", 1)[-1]
    parts = [part for part in text.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return text.rsplit("/", 1)[-1] or "model"
    return "/".join(parts)[:240]


def _looks_windows_absolute(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] == "/" and value[0].isalpha()


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = [
    "DEFAULT_MAX_HASH_BYTES",
    "DEFAULT_FAST_HASH_BYTES",
    "FileHashResult",
    "HashCache",
    "HashCacheIdentity",
    "HashCacheKey",
    "HASHING_MODES",
    "compute_file_hashes",
    "default_hash_cache_path",
]
