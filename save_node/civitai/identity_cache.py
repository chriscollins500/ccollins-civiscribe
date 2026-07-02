"""Offline Civitai/AIR identity mapping from trusted local JSON."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .air import parse_air
from ..metadata.schema import AIRMetadata, HashMetadata, IdentityCacheMetadata, ValidationIssue
from ..metadata.serialize import to_json_text

CACHE_FORMAT_VERSION = "1"
DEFAULT_CACHE_FILENAME = "civitai_identity_cache.json"
DEFAULT_GENERATED_CACHE_FILENAME = "civitai_identity_cache.generated.json"
LOCAL_IDENTITY_SOURCE = "local_identity_cache"
_SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_AUTOV1_RE = re.compile(r"^[A-Fa-f0-9]{8}$")
_AUTOV2_RE = re.compile(r"^[A-Fa-f0-9]{10}$")
_AUTOV3_RE = re.compile(r"^[A-Fa-f0-9]{12}$")
_CRC32_RE = re.compile(r"^[A-Fa-f0-9]{8}$")
_BLAKE3_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_HASH_PRIORITY = (
    ("sha256", "SHA256", "sha256"),
    ("blake3", "BLAKE3", "blake3"),
    ("auto_v2", "AutoV2", "auto_v2"),
    ("auto_v3", "AutoV3", "auto_v3"),
    ("crc32", "CRC32", "crc32"),
    ("auto_v1", "AutoV1", "auto_v1"),
)


@dataclass(frozen=True)
class IdentityMappingRecord:
    air: AIRMetadata
    civitai_model_id: int
    civitai_model_version_id: int
    hashes: HashMetadata
    model_name: str | None = None
    model_version_name: str | None = None
    resource_type: str | None = None
    base_model: str | None = None
    source_url: str | None = None
    trigger_words: tuple[str, ...] = field(default_factory=tuple)
    license: str | None = None
    usage_notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    pinned: bool = False
    locked: bool = False
    confidence: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "air": self.air.raw,
            "parsedAir": self.air.to_json(),
            "civitaiModelId": self.civitai_model_id,
            "civitaiModelVersionId": self.civitai_model_version_id,
            "hashes": self.hashes.to_json(),
        }
        _set_if_present(data, "modelName", self.model_name)
        _set_if_present(data, "modelVersionName", self.model_version_name)
        _set_if_present(data, "resourceType", self.resource_type)
        _set_if_present(data, "baseModel", self.base_model)
        _set_if_present(data, "sourceUrl", self.source_url)
        if self.trigger_words:
            data["triggerWords"] = list(self.trigger_words)
        _set_if_present(data, "license", self.license)
        _set_if_present(data, "usageNotes", self.usage_notes)
        _set_if_present(data, "createdAt", self.created_at)
        _set_if_present(data, "updatedAt", self.updated_at)
        if self.pinned:
            data["pinned"] = True
        if self.locked:
            data["locked"] = True
        _set_if_present(data, "confidence", self.confidence)
        return data


@dataclass(frozen=True)
class IdentityCacheLoadResult:
    cache: "IdentityCache"
    warnings: tuple[ValidationIssue, ...] = ()
    errors: tuple[ValidationIssue, ...] = ()


class IdentityCache:
    def __init__(
        self,
        *,
        records: tuple[IdentityMappingRecord, ...] = (),
        metadata: IdentityCacheMetadata | None = None,
    ) -> None:
        self.records = records
        self.metadata = metadata or IdentityCacheMetadata()
        self._hash_index: dict[str, dict[str, IdentityMappingRecord]] = {
            algorithm: {} for algorithm, _json_key, _attr in _HASH_PRIORITY
        }
        for record in records:
            for algorithm, value in _hash_pairs(record.hashes):
                self._hash_index.setdefault(algorithm, {})[_normalize_hash(value)] = record

    @classmethod
    def empty(cls) -> "IdentityCache":
        return cls(metadata=IdentityCacheMetadata())

    def lookup(self, hashes: HashMetadata) -> IdentityMappingRecord | None:
        for algorithm, value in _hash_pairs(hashes):
            record = self._hash_index.get(algorithm, {}).get(_normalize_hash(value))
            if record is not None:
                return record
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "formatVersion": CACHE_FORMAT_VERSION,
            "records": [record.to_json() for record in self.records],
        }


def load_identity_cache(
    path: Path,
    *,
    allowed_roots: tuple[Path, ...] | None = None,
) -> IdentityCacheLoadResult:
    safe_path = _safe_cache_path(path, allowed_roots or default_identity_cache_roots())
    if safe_path is None:
        return IdentityCacheLoadResult(
            cache=IdentityCache.empty(),
            errors=(
                ValidationIssue(
                    code="identity_cache_path_rejected",
                    message="Identity cache path is outside approved configuration roots",
                    field="identityCache",
                ),
            ),
        )

    if not safe_path.exists():
        return IdentityCacheLoadResult(cache=IdentityCache.empty())

    try:
        text = safe_path.read_text(encoding="utf-8")
        raw = json.loads(text)
    except json.JSONDecodeError:
        return IdentityCacheLoadResult(
            cache=IdentityCache.empty(),
            errors=(
                ValidationIssue(
                    code="identity_cache_invalid_json",
                    message="Identity cache JSON is invalid",
                    field="identityCache",
                ),
            ),
        )
    except OSError:
        return IdentityCacheLoadResult(
            cache=IdentityCache.empty(),
            errors=(
                ValidationIssue(
                    code="identity_cache_unreadable",
                    message="Identity cache file could not be read",
                    field="identityCache",
                ),
            ),
        )

    parsed = parse_identity_cache(raw, mapping_source=safe_path.name)
    metadata = IdentityCacheMetadata(
        format_version=parsed.cache.metadata.format_version,
        mapping_source=safe_path.name,
        loaded_record_count=len(parsed.cache.records),
        warnings_count=len(parsed.warnings),
    )
    return IdentityCacheLoadResult(
        cache=IdentityCache(records=parsed.cache.records, metadata=metadata),
        warnings=parsed.warnings,
        errors=parsed.errors,
    )


def combine_identity_caches(
    *,
    primary: IdentityCache,
    secondary: IdentityCache,
    mapping_source: str = "combined",
) -> IdentityCache:
    """Combine caches with primary records winning duplicate hash indexes."""

    records = (*secondary.records, *primary.records)
    return IdentityCache(
        records=records,
        metadata=IdentityCacheMetadata(
            format_version=CACHE_FORMAT_VERSION,
            mapping_source=mapping_source,
            loaded_record_count=len(records),
            warnings_count=primary.metadata.warnings_count + secondary.metadata.warnings_count,
        ),
    )


def parse_identity_cache(raw: Any, *, mapping_source: str = "inline") -> IdentityCacheLoadResult:
    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []
    records: list[IdentityMappingRecord] = []

    if isinstance(raw, list):
        format_version = CACHE_FORMAT_VERSION
        raw_records = raw
    elif isinstance(raw, dict):
        format_version = str(raw.get("formatVersion") or raw.get("format_version") or CACHE_FORMAT_VERSION)
        raw_records = raw.get("records", [])
    else:
        return IdentityCacheLoadResult(
            cache=IdentityCache.empty(),
            errors=(
                ValidationIssue(
                    code="identity_cache_schema_invalid",
                    message="Identity cache must be a JSON object or records array",
                    field="identityCache",
                ),
            ),
        )

    if not isinstance(raw_records, list):
        return IdentityCacheLoadResult(
            cache=IdentityCache.empty(),
            errors=(
                ValidationIssue(
                    code="identity_cache_records_invalid",
                    message="Identity cache records must be a JSON array",
                    field="identityCache.records",
                ),
            ),
        )

    for index, raw_record in enumerate(raw_records):
        record, record_warnings, record_errors = parse_identity_record(raw_record, index=index)
        warnings.extend(record_warnings)
        errors.extend(record_errors)
        if record is not None:
            conflict = _record_conflict(records, record)
            if conflict is not None:
                errors.append(
                    ValidationIssue(
                        code="identity_record_hash_conflict",
                        message="Identity mapping record hash conflicts with an earlier Civitai identity",
                        field=f"identityCache.records[{index}].hashes",
                    )
                )
                continue
            records.append(record)

    metadata = IdentityCacheMetadata(
        format_version=format_version,
        mapping_source=mapping_source,
        loaded_record_count=len(records),
        warnings_count=len(warnings),
    )
    return IdentityCacheLoadResult(
        cache=IdentityCache(records=tuple(records), metadata=metadata),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def parse_identity_record(
    raw_record: Any,
    *,
    index: int,
) -> tuple[IdentityMappingRecord | None, tuple[ValidationIssue, ...], tuple[ValidationIssue, ...]]:
    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []
    field = f"identityCache.records[{index}]"

    if not isinstance(raw_record, dict):
        return (
            None,
            (),
            (
                ValidationIssue(
                    code="identity_record_invalid",
                    message="Identity mapping record must be an object",
                    field=field,
                ),
            ),
        )

    hashes = _parse_hashes(raw_record.get("hashes", {}))
    errors.extend(_hash_validation_errors(hashes, f"{field}.hashes"))
    if hashes.is_empty:
        errors.append(
            ValidationIssue(
                code="identity_record_missing_hash",
                message="Identity mapping record contains no hash identifiers",
                field=f"{field}.hashes",
            )
        )
    if hashes.is_empty and raw_record.get("filename"):
        errors.append(
            ValidationIssue(
                code="identity_record_filename_only",
                message="Identity mapping record cannot resolve identity by filename only",
                field=field,
            )
        )

    raw_air = _string_or_none(raw_record.get("air") or raw_record.get("rawAir") or raw_record.get("urn"))
    air, air_warnings = parse_air(raw_air)
    if air_warnings:
        warnings.extend(
            ValidationIssue(
                code="identity_record_malformed_air",
                message=warning.message,
                field=f"{field}.air",
            )
            for warning in air_warnings
        )
    if air is None:
        return None, tuple(warnings), tuple(errors)

    explicit_model_id = _int_or_none(raw_record.get("civitaiModelId") or raw_record.get("modelId"))
    explicit_version_id = _int_or_none(
        raw_record.get("civitaiModelVersionId") or raw_record.get("modelVersionId") or raw_record.get("versionId")
    )
    model_id = explicit_model_id if explicit_model_id is not None else air.model_id
    version_id = explicit_version_id if explicit_version_id is not None else air.model_version_id

    if (
        explicit_version_id is not None
        and air.model_version_id is not None
        and explicit_version_id != air.model_version_id
    ):
        errors.append(
            ValidationIssue(
                code="identity_record_model_version_conflict",
                message="Identity mapping record modelVersionId conflicts with AIR modelVersionId",
                field=f"{field}.civitaiModelVersionId",
            )
        )

    if explicit_model_id is not None and air.model_id is not None and explicit_model_id != air.model_id:
        errors.append(
            ValidationIssue(
                code="identity_record_model_id_conflict",
                message="Identity mapping record modelId conflicts with AIR modelId",
                field=f"{field}.civitaiModelId",
            )
        )

    resource_type = _string_or_none(raw_record.get("resourceType") or raw_record.get("type"))
    if resource_type and air.type and resource_type.lower() != air.type.lower():
        warnings.append(
            ValidationIssue(
                code="identity_record_resource_type_conflict",
                message="Identity mapping record resource type does not match AIR type",
                field=f"{field}.resourceType",
            )
        )

    if model_id is None or version_id is None:
        errors.append(
            ValidationIssue(
                code="identity_record_missing_civitai_ids",
                message="Identity mapping record must provide Civitai modelId and modelVersionId via AIR or explicit fields",
                field=field,
            )
        )

    if errors:
        return None, tuple(warnings), tuple(errors)

    return (
        IdentityMappingRecord(
            air=air,
            civitai_model_id=model_id,
            civitai_model_version_id=version_id,
            hashes=hashes,
            model_name=_string_or_none(raw_record.get("modelName") or raw_record.get("name")),
            model_version_name=_string_or_none(raw_record.get("modelVersionName") or raw_record.get("versionName")),
            resource_type=resource_type,
            base_model=_string_or_none(raw_record.get("baseModel") or raw_record.get("ecosystem")),
            source_url=_string_or_none(raw_record.get("sourceUrl")),
            trigger_words=_string_tuple(raw_record.get("triggerWords")),
            license=_string_or_none(raw_record.get("license")),
            usage_notes=_string_or_none(raw_record.get("usageNotes") or raw_record.get("usage")),
            created_at=_string_or_none(raw_record.get("createdAt")),
            updated_at=_string_or_none(raw_record.get("updatedAt")),
            pinned=_bool_or_false(raw_record.get("pinned")),
            locked=_bool_or_false(raw_record.get("locked")),
            confidence=_string_or_none(raw_record.get("confidence")),
        ),
        tuple(warnings),
        (),
    )


def default_identity_cache_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / DEFAULT_CACHE_FILENAME


def generated_identity_cache_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / DEFAULT_GENERATED_CACHE_FILENAME


def default_identity_cache_roots() -> tuple[Path, ...]:
    return (default_identity_cache_path().parent,)


def write_identity_cache(
    cache: IdentityCache,
    path: Path,
    *,
    allowed_roots: tuple[Path, ...] | None = None,
) -> tuple[ValidationIssue, ...]:
    safe_path = _safe_cache_path(path, allowed_roots or default_identity_cache_roots())
    if safe_path is None:
        return (
            ValidationIssue(
                code="identity_cache_write_path_rejected",
                message="Identity cache write path is outside approved configuration roots",
                field="identityCache",
            ),
        )

    try:
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=safe_path.parent,
                prefix=f".{safe_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(to_json_text(cache.to_json(), indent=2))
            os.replace(temp_path, safe_path)
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
    except (OSError, TypeError, ValueError):
        return (
            ValidationIssue(
                code="identity_cache_write_failed",
                message="Identity cache file could not be written",
                field="identityCache",
            ),
        )
    return ()


def _safe_cache_path(path: Path, allowed_roots: tuple[Path, ...]) -> Path | None:
    candidate = Path(path).expanduser().resolve(strict=False)
    for root in allowed_roots:
        resolved_root = Path(root).expanduser().resolve(strict=False)
        try:
            common = os.path.commonpath([os.path.normcase(str(resolved_root)), os.path.normcase(str(candidate))])
        except ValueError:
            continue
        if common == os.path.normcase(str(resolved_root)):
            return candidate
    return None


def _parse_hashes(raw_hashes: Any) -> HashMetadata:
    if not isinstance(raw_hashes, Mapping):
        return HashMetadata()
    sha256 = _string_or_none(_hash_value(raw_hashes, "SHA256", "sha256"))
    auto_v1 = _string_or_none(_hash_value(raw_hashes, "AutoV1", "autoV1", "auto_v1"))
    auto_v2 = _string_or_none(_hash_value(raw_hashes, "AutoV2", "autoV2", "auto_v2", "modelHash"))
    auto_v3 = _string_or_none(_hash_value(raw_hashes, "AutoV3", "autoV3", "auto_v3"))
    crc32 = _string_or_none(_hash_value(raw_hashes, "CRC32", "crc32"))
    blake3 = _string_or_none(_hash_value(raw_hashes, "BLAKE3", "blake3"))
    known_keys = {
        "SHA256",
        "sha256",
        "AutoV1",
        "autoV1",
        "auto_v1",
        "AutoV2",
        "autoV2",
        "auto_v2",
        "modelHash",
        "AutoV3",
        "autoV3",
        "auto_v3",
        "CRC32",
        "crc32",
        "BLAKE3",
        "blake3",
    }
    additional = {
        str(key): str(value) for key, value in raw_hashes.items() if value is not None and str(key) not in known_keys
    }
    return HashMetadata(
        sha256=sha256,
        auto_v1=auto_v1,
        auto_v2=auto_v2,
        auto_v3=auto_v3,
        crc32=crc32,
        blake3=blake3,
        additional=additional,
    )


def _hash_validation_errors(hashes: HashMetadata, field: str) -> list[ValidationIssue]:
    errors: list[ValidationIssue] = []
    if hashes.sha256 and not _SHA256_RE.fullmatch(hashes.sha256):
        errors.append(
            ValidationIssue(
                code="identity_record_invalid_sha256",
                message="Identity mapping record SHA256 hash is malformed",
                field=f"{field}.SHA256",
            )
        )
    if hashes.auto_v2 and not _AUTOV2_RE.fullmatch(hashes.auto_v2):
        errors.append(
            ValidationIssue(
                code="identity_record_invalid_autov2",
                message="Identity mapping record AutoV2 hash is malformed",
                field=f"{field}.AutoV2",
            )
        )
    if hashes.auto_v1 and not _AUTOV1_RE.fullmatch(hashes.auto_v1):
        errors.append(
            ValidationIssue(
                code="identity_record_invalid_autov1",
                message="Identity mapping record AutoV1 hash is malformed",
                field=f"{field}.AutoV1",
            )
        )
    if hashes.auto_v3 and not _AUTOV3_RE.fullmatch(hashes.auto_v3):
        errors.append(
            ValidationIssue(
                code="identity_record_invalid_autov3",
                message="Identity mapping record AutoV3 hash is malformed",
                field=f"{field}.AutoV3",
            )
        )
    if hashes.crc32 and not _CRC32_RE.fullmatch(hashes.crc32):
        errors.append(
            ValidationIssue(
                code="identity_record_invalid_crc32",
                message="Identity mapping record CRC32 hash is malformed",
                field=f"{field}.CRC32",
            )
        )
    if hashes.blake3 and not _BLAKE3_RE.fullmatch(hashes.blake3):
        errors.append(
            ValidationIssue(
                code="identity_record_invalid_blake3",
                message="Identity mapping record BLAKE3 hash is malformed",
                field=f"{field}.BLAKE3",
            )
        )
    return errors


def _record_conflict(
    records: list[IdentityMappingRecord],
    record: IdentityMappingRecord,
) -> IdentityMappingRecord | None:
    new_keys = set(_record_hash_keys(record))
    if not new_keys:
        return None
    for existing in records:
        if not new_keys.intersection(_record_hash_keys(existing)):
            continue
        if _same_identity(existing, record):
            continue
        return existing
    return None


def _same_identity(left: IdentityMappingRecord, right: IdentityMappingRecord) -> bool:
    return (
        left.civitai_model_id == right.civitai_model_id
        and left.civitai_model_version_id == right.civitai_model_version_id
        and left.air.raw == right.air.raw
    )


def _record_hash_keys(record: IdentityMappingRecord) -> tuple[str, ...]:
    return tuple(f"{algorithm}:{_normalize_hash(value)}" for algorithm, value in _hash_pairs(record.hashes))


def _hash_pairs(hashes: HashMetadata) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for algorithm, _json_key, attr in _HASH_PRIORITY:
        value = getattr(hashes, attr)
        if value:
            pairs.append((algorithm, value))
    return tuple(pairs)


def _hash_value(raw_hashes: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw_hashes.get(key)
        if value is not None:
            return value
    return None


def _normalize_hash(value: str) -> str:
    return value.strip().lower()


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if item is not None)
    return ()


def _bool_or_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _set_if_present(data: dict[str, Any], key: str, value: Any | None) -> None:
    if value is not None:
        data[key] = value


__all__ = [
    "CACHE_FORMAT_VERSION",
    "DEFAULT_CACHE_FILENAME",
    "DEFAULT_GENERATED_CACHE_FILENAME",
    "LOCAL_IDENTITY_SOURCE",
    "IdentityCache",
    "IdentityCacheLoadResult",
    "IdentityMappingRecord",
    "combine_identity_caches",
    "default_identity_cache_path",
    "generated_identity_cache_path",
    "load_identity_cache",
    "parse_identity_cache",
    "parse_identity_record",
    "write_identity_cache",
]
