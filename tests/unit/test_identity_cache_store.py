from __future__ import annotations

import errno
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from civiscribe.identity import cache_store
from civiscribe.identity.cache_store import (
    BoundedJsonCache,
    CacheLimits,
    CacheRuntime,
)

SCHEMA = "test.cache"
EXPECTED_LOCK_ATTEMPTS = 2


def _record(key: str, value: object = "safe/value") -> dict[str, object]:
    return {"cacheKey": key, "value": value}


def test_cache_round_trip_is_deterministic_and_old_or_new_json(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    cache = BoundedJsonCache(path, schema_name=SCHEMA)
    assert cache.read().records == ()
    assert cache.merge(_record("b")).written is True
    assert cache.merge(_record("a")).written is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [item["cacheKey"] for item in payload["records"]] == ["a", "b"]
    assert cache.read().records == (_record("a"), _record("b"))


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"\xff", "cache_json_invalid"),
        (b"{}", "cache_schema_invalid"),
        (
            json.dumps(
                {
                    "schemaName": SCHEMA,
                    "formatVersion": 1,
                    "records": "wrong",
                }
            ).encode(),
            "cache_schema_invalid",
        ),
    ],
)
def test_corrupt_cache_is_ignored(payload: bytes, code: str, tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_bytes(payload)
    result = BoundedJsonCache(path, schema_name=SCHEMA).read()
    assert result.records == ()
    assert [issue.code for issue in result.issues] == [code]


def test_cache_size_and_record_bounds_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("x" * 20, encoding="utf-8")
    tiny = BoundedJsonCache(
        path,
        schema_name=SCHEMA,
        limits=CacheLimits(max_bytes=10, max_records=1),
    )
    assert [issue.code for issue in tiny.read().issues] == ["cache_file_too_large"]

    path.write_text(
        json.dumps(
            {
                "schemaName": SCHEMA,
                "formatVersion": 1,
                "records": [_record("a"), _record("b")],
            }
        ),
        encoding="utf-8",
    )
    limited = BoundedJsonCache(
        path,
        schema_name=SCHEMA,
        limits=CacheLimits(max_bytes=4096, max_records=1),
    ).read()
    assert limited.records == (_record("a"),)
    assert [issue.code for issue in limited.issues] == ["cache_record_limit_reached"]


@pytest.mark.parametrize(
    "record",
    [
        {"cacheKey": ""},
        _record("path", "C:\\Users\\private\\model.safetensors"),
        _record("path", "/home/private/model.safetensors"),
        {"cacheKey": "secret", "token": "not-allowed"},
        {"cacheKey": "nan", "value": float("nan")},
    ],
)
def test_cache_rejects_private_or_invalid_records(
    record: dict[str, object],
    tmp_path: Path,
) -> None:
    result = BoundedJsonCache(tmp_path / "cache.json", schema_name=SCHEMA).merge(record)
    assert result.written is False
    assert [issue.code for issue in result.issues] == ["cache_record_invalid"]


def test_cache_accepts_air_urns_without_treating_them_as_drive_paths(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache.json"
    cache = BoundedJsonCache(path, schema_name=SCHEMA)
    record = {
        "cacheKey": "identity:one",
        "identity": {
            "canonicalAir": "urn:air:sdxl:checkpoint:civitai:10@20",
        },
    }

    assert cache.merge(record).written is True
    assert cache.read().records == (record,)


def test_cache_ignores_invalid_records_but_keeps_valid_records(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "schemaName": SCHEMA,
                "formatVersion": 1,
                "records": [_record("good"), {"cacheKey": "", "value": "bad"}],
            }
        ),
        encoding="utf-8",
    )
    result = BoundedJsonCache(path, schema_name=SCHEMA).read()
    assert result.records == (_record("good"),)
    assert [issue.code for issue in result.issues] == ["cache_records_ignored"]


def test_cache_merge_recovers_from_corrupt_input(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("{", encoding="utf-8")
    result = BoundedJsonCache(path, schema_name=SCHEMA).merge(_record("new"))
    assert result.written is True
    assert [issue.code for issue in result.issues] == ["cache_json_invalid"]
    assert BoundedJsonCache(path, schema_name=SCHEMA).read().records == (_record("new"),)


def test_invalid_cache_limits_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cache_limits_invalid"):
        BoundedJsonCache(
            tmp_path / "cache.json",
            schema_name=SCHEMA,
            limits=CacheLimits(max_bytes=0),
        )


def test_cache_lock_timeout_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_values = iter((0.0, 0.0))
    cache = BoundedJsonCache(
        tmp_path / "cache.json",
        schema_name=SCHEMA,
        limits=CacheLimits(lock_timeout_seconds=0),
        runtime=CacheRuntime(monotonic=lambda: next(monotonic_values), sleep=lambda _: None),
    )
    monkeypatch.setattr(
        cache_store,
        "_lock_byte",
        lambda _handle: (_ for _ in ()).throw(PermissionError(13, "busy")),
    )
    result = cache.merge(_record("a"))
    assert result.written is False
    assert [issue.code for issue in result.issues] == ["cache_lock_timeout"]


def test_cache_write_failure_is_nonfatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = BoundedJsonCache(tmp_path / "cache.json", schema_name=SCHEMA)
    monkeypatch.setattr(
        cache,
        "_write_unlocked",
        lambda _records: (_ for _ in ()).throw(OSError("disk full")),
    )
    result = cache.merge(_record("a"))
    assert result.written is False
    assert [issue.code for issue in result.issues] == ["cache_write_failed"]


def test_platform_lock_helpers_cover_posix_and_unsupported_platforms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []
    locking = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda descriptor, operation: calls.append((descriptor, operation)),
    )
    monkeypatch.setattr(cache_store, "_LOCKING_MODULE", locking)

    with (tmp_path / "platform.lock").open("a+b") as handle:
        monkeypatch.setattr(cache_store, "os", SimpleNamespace(name="posix"))
        cache_store._lock_byte(handle)
        cache_store._unlock_byte(handle)

        monkeypatch.setattr(cache_store, "os", SimpleNamespace(name="unsupported"))
        with pytest.raises(OSError) as exc_info:
            cache_store._lock_byte(handle)
        assert exc_info.value.errno == errno.ENOTSUP
        cache_store._unlock_byte(handle)

    assert [operation for _descriptor, operation in calls] == [3, 4]


def test_platform_lock_retries_contention_then_unlocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []
    unlocked: list[bool] = []

    def lock_once_busy(_handle: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise BlockingIOError(errno.EAGAIN, "busy")

    monotonic_values = iter((0.0, 0.0))
    monkeypatch.setattr(cache_store, "_lock_byte", lock_once_busy)
    monkeypatch.setattr(cache_store, "_unlock_byte", lambda _handle: unlocked.append(True))

    with cache_store._platform_lock(
        tmp_path / "cache.json",
        timeout_seconds=1.0,
        monotonic=lambda: next(monotonic_values),
        sleep=sleeps.append,
    ):
        assert attempts == EXPECTED_LOCK_ATTEMPTS

    assert sleeps == [cache_store._LOCK_RETRY_SECONDS]
    assert unlocked == [True]


def test_platform_lock_propagates_non_contention_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cache_store,
        "_lock_byte",
        lambda _handle: (_ for _ in ()).throw(OSError(errno.EIO, "device error")),
    )

    with (
        pytest.raises(OSError) as exc_info,
        cache_store._platform_lock(
            tmp_path / "cache.json",
            timeout_seconds=1.0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        ),
    ):
        pass

    assert exc_info.value.errno == errno.EIO


def test_cache_value_validation_covers_nested_and_unsupported_values() -> None:
    deeply_nested: object = None
    for _ in range(cache_store.MAX_CACHE_DEPTH + 2):
        deeply_nested = [deeply_nested]

    assert cache_store._safe_cache_value(["safe", 1, None]) is True
    assert cache_store._safe_cache_value(deeply_nested) is False
    assert cache_store._safe_cache_value({1: "non-string-key"}) is False
    assert cache_store._safe_cache_value(object()) is False
    assert cache_store._validated_record(["not", "a", "mapping"]) is None


def test_cache_read_os_error_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_read(_path: Path) -> bytes:
        raise OSError("unavailable")

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    result = BoundedJsonCache(tmp_path / "cache.json", schema_name=SCHEMA).read()
    assert result.records == ()
    assert [issue.code for issue in result.issues] == ["cache_read_failed"]


def test_cache_rejects_utf8_output_larger_than_byte_limit(tmp_path: Path) -> None:
    cache = BoundedJsonCache(
        tmp_path / "cache.json",
        schema_name=SCHEMA,
        limits=CacheLimits(max_bytes=160),
    )

    with pytest.raises(ValueError, match="cache_output_too_large"):
        cache._write_unlocked((_record("unicode", "é" * 60),))


def test_cache_merge_trims_records_to_configured_limit(tmp_path: Path) -> None:
    cache = BoundedJsonCache(
        tmp_path / "cache.json",
        schema_name=SCHEMA,
        limits=CacheLimits(max_bytes=4096, max_records=1),
    )

    assert cache.merge(_record("a")).written is True
    assert cache.merge(_record("b")).written is True
    assert cache.read().records == (_record("b"),)
