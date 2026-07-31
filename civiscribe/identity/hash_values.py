"""Validation and deterministic ordering for supported identity hashes."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping

from ..domain import HashRecord

HASH_PRIORITY = (
    ("SHA256", "sha256", 64),
    ("BLAKE3", "blake3", 64),
    ("AutoV3", "auto_v3", 12),
    ("AutoV2", "auto_v2", 10),
    ("CRC32", "crc32", 8),
    ("AutoV1", "auto_v1", 8),
)
_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")


def normalize_hash(value: object, *, length: int, uppercase: bool = False) -> str | None:
    """Return one exact hexadecimal hash value or ``None``."""

    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if len(stripped) != length or _HEX_RE.fullmatch(stripped) is None:
        return None
    return stripped.upper() if uppercase else stripped.casefold()


def hash_record_from_mapping(value: object) -> HashRecord | None:
    """Parse supported hash names without treating malformed data as identity."""

    if not isinstance(value, Mapping):
        return None
    normalized = {
        field_name: normalize_hash(
            value.get(name),
            length=length,
            uppercase=name == "CRC32",
        )
        for name, field_name, length in HASH_PRIORITY
    }
    record = HashRecord(**normalized)
    return None if record.is_empty else record


def hash_record_to_mapping(hashes: HashRecord) -> dict[str, str]:
    """Serialize known hashes in deterministic authority order."""

    result: dict[str, str] = {}
    for name, field_name, _length in HASH_PRIORITY:
        value = getattr(hashes, field_name)
        if value is not None:
            result[name] = value
    return result


def iter_hashes(hashes: HashRecord) -> Iterator[tuple[str, str]]:
    """Yield known hashes from strongest to weakest."""

    for name, field_name, _length in HASH_PRIORITY:
        value = getattr(hashes, field_name)
        if value is not None:
            yield name, value


def matching_hashes(left: HashRecord, right: HashRecord) -> tuple[str, ...]:
    """Return algorithms whose present values agree."""

    return tuple(
        name
        for name, field_name, _length in HASH_PRIORITY
        if (left_value := getattr(left, field_name)) is not None
        and (right_value := getattr(right, field_name)) is not None
        and left_value.casefold() == right_value.casefold()
    )


def merge_hashes(primary: HashRecord, secondary: HashRecord) -> HashRecord:
    """Fill absent values without overriding the higher-precedence record."""

    return HashRecord(
        **{
            field_name: getattr(primary, field_name) or getattr(secondary, field_name)
            for _name, field_name, _length in HASH_PRIORITY
        }
    )


__all__ = [
    "HASH_PRIORITY",
    "hash_record_from_mapping",
    "hash_record_to_mapping",
    "iter_hashes",
    "matching_hashes",
    "merge_hashes",
    "normalize_hash",
]
