"""Bounded, privacy-safe JSON transactions for local identity caches."""

from __future__ import annotations

import errno
import json
import math
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

if os.name == "nt":  # pragma: no cover - selected only on Windows
    import msvcrt

    _LOCKING_MODULE: Any = msvcrt
elif os.name == "posix":  # pragma: no cover - selected only on POSIX
    import fcntl

    _LOCKING_MODULE = fcntl
else:  # pragma: no cover - no supported release platform reaches this branch
    _LOCKING_MODULE = None

from ..domain import ScanIssue
from ..serialization import dumps_json

CACHE_FORMAT_VERSION = 1
DEFAULT_MAX_CACHE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_CACHE_RECORDS = 50_000
DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0
MAX_CACHE_DEPTH = 12
MAX_CACHE_STRING_CHARS = 4096
MIN_DRIVE_PATH_CHARS = 2
_LOCK_RETRY_SECONDS = 0.01
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_CONTENTION_ERRNOS = {errno.EACCES, errno.EAGAIN}
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
}


@dataclass(frozen=True, slots=True)
class CacheReadResult:
    """Validated cache records and sanitized diagnostics."""

    records: tuple[dict[str, object], ...] = ()
    issues: tuple[ScanIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class CacheWriteResult:
    """Nonfatal outcome of one cache merge transaction."""

    written: bool
    issues: tuple[ScanIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class CacheLimits:
    """Resource and contention limits for one cache."""

    max_bytes: int = DEFAULT_MAX_CACHE_BYTES
    max_records: int = DEFAULT_MAX_CACHE_RECORDS
    lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class CacheRuntime:
    """Injectable time operations for deterministic lock tests."""

    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


DEFAULT_CACHE_LIMITS = CacheLimits()
DEFAULT_CACHE_RUNTIME = CacheRuntime()


class _LockTimeoutError(OSError):
    pass


def _process_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve(strict=False)))
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


def _is_contention(exc: OSError) -> bool:
    return exc.errno in _CONTENTION_ERRNOS


def _lock_byte(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        _LOCKING_MODULE.locking(handle.fileno(), _LOCKING_MODULE.LK_NBLCK, 1)
    elif os.name == "posix":
        _LOCKING_MODULE.flock(
            handle.fileno(),
            _LOCKING_MODULE.LOCK_EX | _LOCKING_MODULE.LOCK_NB,
        )
    else:
        raise OSError(errno.ENOTSUP, "cache locking unsupported")


def _unlock_byte(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        _LOCKING_MODULE.locking(handle.fileno(), _LOCKING_MODULE.LK_UNLCK, 1)
    elif os.name == "posix":
        _LOCKING_MODULE.flock(handle.fileno(), _LOCKING_MODULE.LOCK_UN)


@contextmanager
def _platform_lock(
    path: Path,
    *,
    timeout_seconds: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = monotonic() + timeout_seconds
        while True:
            try:
                _lock_byte(handle)
                break
            except OSError as exc:
                if not _is_contention(exc):
                    raise
                if monotonic() >= deadline:
                    raise _LockTimeoutError(errno.ETIMEDOUT, "cache lock timed out") from None
                sleep(_LOCK_RETRY_SECONDS)
        try:
            yield
        finally:
            _unlock_byte(handle)


def _looks_absolute_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    drive_path = (
        len(normalized) >= MIN_DRIVE_PATH_CHARS and normalized[0].isalpha() and normalized[1] == ":"
    )
    return drive_path or normalized.startswith("/")


def _safe_cache_value(value: object, *, depth: int = 0) -> bool:
    if depth > MAX_CACHE_DEPTH:
        safe = False
    elif value is None or isinstance(value, bool | int):
        safe = True
    elif isinstance(value, float):
        safe = math.isfinite(value)
    elif isinstance(value, str):
        safe = len(value) <= MAX_CACHE_STRING_CHARS and not _looks_absolute_path(value)
    elif isinstance(value, list):
        safe = all(_safe_cache_value(item, depth=depth + 1) for item in value)
    elif isinstance(value, Mapping):
        safe = True
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > MAX_CACHE_STRING_CHARS:
                safe = False
                break
            if key.casefold() in _SECRET_KEYS or not _safe_cache_value(
                item,
                depth=depth + 1,
            ):
                safe = False
                break
    else:
        safe = False
    return safe


def _validated_record(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    key = value.get("cacheKey")
    if not isinstance(key, str) or not key or len(key) > MAX_CACHE_STRING_CHARS:
        return None
    return value if _safe_cache_value(value) else None


class BoundedJsonCache:
    """One shared transaction primitive for hash and identity stores."""

    def __init__(
        self,
        path: Path,
        *,
        schema_name: str,
        limits: CacheLimits = DEFAULT_CACHE_LIMITS,
        runtime: CacheRuntime = DEFAULT_CACHE_RUNTIME,
    ) -> None:
        if limits.max_bytes < 1 or limits.max_records < 1 or limits.lock_timeout_seconds < 0:
            raise ValueError("cache_limits_invalid")
        self.path = path
        self.schema_name = schema_name
        self.max_bytes = limits.max_bytes
        self.max_records = limits.max_records
        self.lock_timeout_seconds = limits.lock_timeout_seconds
        self._monotonic = runtime.monotonic
        self._sleep = runtime.sleep
        self._process_lock = _process_lock(path)

    def _read_unlocked(self) -> CacheReadResult:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return CacheReadResult()
        except OSError:
            return CacheReadResult(issues=(ScanIssue("cache_read_failed"),))
        if len(raw) > self.max_bytes:
            return CacheReadResult(issues=(ScanIssue("cache_file_too_large"),))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return CacheReadResult(issues=(ScanIssue("cache_json_invalid"),))
        if (
            not isinstance(payload, dict)
            or payload.get("schemaName") != self.schema_name
            or payload.get("formatVersion") != CACHE_FORMAT_VERSION
            or not isinstance(payload.get("records"), list)
        ):
            return CacheReadResult(issues=(ScanIssue("cache_schema_invalid"),))

        raw_records = payload["records"]
        limited = raw_records[: self.max_records]
        records = tuple(
            record for value in limited if (record := _validated_record(value)) is not None
        )
        issues: list[ScanIssue] = []
        if len(raw_records) > self.max_records:
            issues.append(ScanIssue("cache_record_limit_reached"))
        if len(records) != len(limited):
            issues.append(ScanIssue("cache_records_ignored"))
        return CacheReadResult(records, tuple(issues))

    def read(self) -> CacheReadResult:
        """Read a complete old-or-new cache snapshot without taking the writer lock."""

        return self._read_unlocked()

    def _write_unlocked(self, records: tuple[dict[str, object], ...]) -> None:
        payload = {
            "schemaName": self.schema_name,
            "formatVersion": CACHE_FORMAT_VERSION,
            "records": list(records),
        }
        encoded = dumps_json(payload, max_chars=self.max_bytes).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise ValueError("cache_output_too_large")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def merge(self, record: Mapping[str, object]) -> CacheWriteResult:
        """Merge one validated record under a complete native lock transaction."""

        validated = _validated_record(dict(record))
        if validated is None:
            return CacheWriteResult(False, (ScanIssue("cache_record_invalid"),))
        try:
            with (
                self._process_lock,
                _platform_lock(
                    self.path,
                    timeout_seconds=self.lock_timeout_seconds,
                    monotonic=self._monotonic,
                    sleep=self._sleep,
                ),
            ):
                existing = self._read_unlocked()
                by_key: dict[str, dict[str, object]] = {
                    str(item["cacheKey"]): item for item in existing.records
                }
                by_key[str(validated["cacheKey"])] = validated
                records = tuple(by_key[key] for key in sorted(by_key))
                if len(records) > self.max_records:
                    records = records[-self.max_records :]
                self._write_unlocked(records)
                return CacheWriteResult(True, existing.issues)
        except _LockTimeoutError:
            return CacheWriteResult(False, (ScanIssue("cache_lock_timeout"),))
        except (OSError, ValueError):
            return CacheWriteResult(False, (ScanIssue("cache_write_failed"),))


__all__ = [
    "CACHE_FORMAT_VERSION",
    "DEFAULT_CACHE_LIMITS",
    "DEFAULT_CACHE_RUNTIME",
    "DEFAULT_LOCK_TIMEOUT_SECONDS",
    "DEFAULT_MAX_CACHE_BYTES",
    "DEFAULT_MAX_CACHE_RECORDS",
    "BoundedJsonCache",
    "CacheLimits",
    "CacheReadResult",
    "CacheRuntime",
    "CacheWriteResult",
]
