"""Audit CiviScribe's reviewed identity contract against Civitai's Site API.

This is an explicit, read-only development command. It sends no credentials,
prompts, workflows, filenames, or local path data. Optional deep checks send
only a caller-supplied public hash or model-version ID.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import httpx

from civiscribe.domain import IdentitySource
from civiscribe.identity.air import parse_air
from civiscribe.identity.civitai_client import USER_AGENT, create_tls_contexts
from civiscribe.identity.civitai_contract import (
    SINGLE_HASH_ALGORITHMS,
    SUPPORTED_MODEL_FILE_TYPES,
    SUPPORTED_MODEL_TYPES,
)

ENUMS_URL = "https://civitai.com/api/v1/enums"
API_BASE_URL = "https://civitai.com/api/v1"
MAX_ENUM_RESPONSE_BYTES = 1_000_000
MAX_CONTRACT_RESPONSE_BYTES = 16 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 0.1
MAX_TIMEOUT_SECONDS = 60.0
MAX_SAFE_RESPONSE_STRING_CHARS = 4_096
MIN_PRINTABLE_CODEPOINT = 32
_HASH_LENGTHS = {
    "AutoV1": 8,
    "AutoV2": 10,
    "AutoV3": 12,
    "BLAKE3": 64,
    "CRC32": 8,
    "SHA256": 64,
}


@dataclass(frozen=True, slots=True)
class ContractAudit:
    """Deterministic enum drift report."""

    missing_model_types: tuple[str, ...] = ()
    new_model_types: tuple[str, ...] = ()
    missing_model_file_types: tuple[str, ...] = ()
    new_model_file_types: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    tls_context_source: str | None = None

    @property
    def valid(self) -> bool:
        return not (
            self.missing_model_types
            or self.new_model_types
            or self.missing_model_file_types
            or self.new_model_file_types
            or self.errors
        )

    def as_dict(self) -> dict[str, object]:
        """Return a stable, JSON-ready report without local environment data."""

        return {
            "endpoint": ENUMS_URL,
            "errors": list(self.errors),
            "missingModelFileTypes": list(self.missing_model_file_types),
            "missingModelTypes": list(self.missing_model_types),
            "newModelFileTypes": list(self.new_model_file_types),
            "newModelTypes": list(self.new_model_types),
            "tlsContextSource": self.tls_context_source,
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class ResponseContractAudit:
    """Sanitized model-version or hash-response shape report."""

    endpoint_kind: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    observed_file_count: int | None = None
    tls_context_source: str | None = None

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        """Return a stable report without echoing identifiers or payload text."""

        return {
            "endpointKind": self.endpoint_kind,
            "errors": list(self.errors),
            "observedFileCount": self.observed_file_count,
            "tlsContextSource": self.tls_context_source,
            "valid": self.valid,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class _FetchResult:
    payload: object | None = None
    error: str | None = None
    tls_context_source: str | None = None


def _enum_values(payload: Mapping[str, object], key: str) -> tuple[str, ...] | None:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    if len(value) != len(set(value)):
        return None
    return tuple(value)


def audit_enum_payload(
    payload: object,
    *,
    tls_context_source: str | None = None,
) -> ContractAudit:
    """Compare an enum response with CiviScribe's reviewed contract."""

    if not isinstance(payload, Mapping):
        return ContractAudit(
            errors=("response_root_invalid",),
            tls_context_source=tls_context_source,
        )
    model_types = _enum_values(payload, "ModelType")
    file_types = _enum_values(payload, "ModelFileType")
    errors: list[str] = []
    if model_types is None:
        errors.append("model_type_enum_invalid")
    if file_types is None:
        errors.append("model_file_type_enum_invalid")
    if model_types is None or file_types is None:
        return ContractAudit(
            errors=tuple(errors),
            tls_context_source=tls_context_source,
        )

    expected_models = set(SUPPORTED_MODEL_TYPES)
    expected_files = set(SUPPORTED_MODEL_FILE_TYPES)
    actual_models = set(model_types)
    actual_files = set(file_types)
    return ContractAudit(
        missing_model_types=tuple(sorted(expected_models - actual_models)),
        new_model_types=tuple(sorted(actual_models - expected_models)),
        missing_model_file_types=tuple(sorted(expected_files - actual_files)),
        new_model_file_types=tuple(sorted(actual_files - expected_files)),
        tls_context_source=tls_context_source,
    )


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _safe_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > MAX_SAFE_RESPONSE_STRING_CHARS
        or any(ord(char) < MIN_PRINTABLE_CODEPOINT for char in stripped)
    ):
        return None
    return stripped


def _hash_contract_errors(
    hashes: object,
    *,
    expected_hash: str | None,
) -> tuple[list[str], bool]:
    if not isinstance(hashes, Mapping):
        return ["file_hashes_invalid"], False
    errors: list[str] = []
    matched = False
    for name, hash_value in hashes.items():
        if not isinstance(name, str) or name not in SINGLE_HASH_ALGORITHMS:
            errors.append("file_hash_type_unreviewed")
        normalized_hash = _safe_string(hash_value)
        expected_length = _HASH_LENGTHS.get(name) if isinstance(name, str) else None
        if (
            normalized_hash is None
            or re.fullmatch(r"[0-9A-Fa-f]+", normalized_hash) is None
            or (expected_length is not None and len(normalized_hash) != expected_length)
        ):
            errors.append("file_hash_value_invalid")
        if (
            expected_hash is not None
            and isinstance(hash_value, str)
            and hash_value.casefold() == expected_hash.casefold()
        ):
            matched = True
    return errors, matched


def _file_contract_errors(
    value: object,
    *,
    expected_hash: str | None,
) -> tuple[list[str], bool]:
    if not isinstance(value, Mapping):
        return ["file_record_invalid"], False
    errors: list[str] = []
    if _positive_int(value.get("id")) is None:
        errors.append("file_id_invalid")
    file_type = value.get("type")
    if not isinstance(file_type, str) or file_type not in SUPPORTED_MODEL_FILE_TYPES:
        errors.append("file_type_unreviewed")
    if not isinstance(value.get("primary"), bool):
        errors.append("file_primary_invalid")
    hash_errors, matched = _hash_contract_errors(
        value.get("hashes"),
        expected_hash=expected_hash,
    )
    errors.extend(hash_errors)

    metadata = value.get("metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        errors.append("file_metadata_invalid")
    elif (
        isinstance(metadata, Mapping)
        and "format" in metadata
        and _safe_string(metadata.get("format")) is None
    ):
        errors.append("file_format_invalid")
    return errors, matched


def _model_contract(payload: Mapping[str, object]) -> tuple[int | None, list[str]]:
    errors: list[str] = []
    model_id = _positive_int(payload.get("modelId"))
    model = payload.get("model")
    if not isinstance(model, Mapping):
        errors.append("model_record_invalid")
        nested_model_id = None
    else:
        nested_model_id = _positive_int(model.get("id"))
        model_type = model.get("type")
        if not isinstance(model_type, str) or model_type not in SUPPORTED_MODEL_TYPES:
            errors.append("model_type_unreviewed")
    if model_id is None:
        model_id = nested_model_id
    elif nested_model_id is not None and model_id != nested_model_id:
        errors.append("model_id_conflict")
    if model_id is None:
        errors.append("model_id_invalid")
    return model_id, errors


def _air_contract(
    value: object,
    *,
    model_id: int | None,
    version_id: int | None,
) -> tuple[list[str], list[str]]:
    if value is None:
        return [], ["official_air_missing"]
    air = _safe_string(value)
    if air is None:
        return ["official_air_invalid"], []
    parsed = parse_air(air, provenance=IdentitySource.API).identity
    if parsed is None:
        return ["official_air_invalid"], []
    if (model_id is not None and parsed.model_id != model_id) or (
        version_id is not None and parsed.model_version_id != version_id
    ):
        return ["official_air_id_conflict"], []
    return [], []


def _files_contract(
    value: object,
    *,
    expected_hash: str | None,
) -> tuple[list[str], int | None]:
    if not isinstance(value, list):
        errors = ["files_invalid"]
        if expected_hash is not None:
            errors.append("requested_hash_missing")
        return errors, None
    errors = [] if value else ["files_empty"]
    matched_hash = expected_hash is None
    for file in value:
        file_errors, file_matched = _file_contract_errors(
            file,
            expected_hash=expected_hash,
        )
        errors.extend(file_errors)
        matched_hash = matched_hash or file_matched
    if not matched_hash:
        errors.append("requested_hash_missing")
    return errors, len(value)


def audit_model_version_payload(
    payload: object,
    *,
    endpoint_kind: str,
    expected_hash: str | None = None,
    tls_context_source: str | None = None,
) -> ResponseContractAudit:
    """Validate fields CiviScribe consumes without retaining the raw response."""

    if not isinstance(payload, Mapping):
        return ResponseContractAudit(
            endpoint_kind,
            errors=("response_root_invalid",),
            tls_context_source=tls_context_source,
        )

    version_id = _positive_int(payload.get("id"))
    errors = [] if version_id is not None else ["model_version_id_invalid"]
    model_id, model_errors = _model_contract(payload)
    errors.extend(model_errors)
    air_errors, warnings = _air_contract(
        payload.get("air"),
        model_id=model_id,
        version_id=version_id,
    )
    errors.extend(air_errors)
    base_model = payload.get("baseModel")
    if base_model is not None and _safe_string(base_model) is None:
        errors.append("base_model_invalid")
    file_errors, file_count = _files_contract(
        payload.get("files"),
        expected_hash=expected_hash,
    )
    errors.extend(file_errors)

    return ResponseContractAudit(
        endpoint_kind,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        observed_file_count=file_count,
        tls_context_source=tls_context_source,
    )


def _decode_response(response: httpx.Response, *, max_response_bytes: int) -> _FetchResult:
    if response.status_code != httpx.codes.OK:
        return _FetchResult(error=f"http_status_{response.status_code}")
    content = response.content
    if len(content) > max_response_bytes:
        return _FetchResult(error="response_too_large")
    try:
        return _FetchResult(payload=json.loads(content.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _FetchResult(error="malformed_json")


def fetch_public_json(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_response_bytes: int = MAX_CONTRACT_RESPONSE_BYTES,
    transport: httpx.BaseTransport | None = None,
    tls_contexts: Sequence[tuple[str, ssl.SSLContext]] | None = None,
) -> _FetchResult:
    """Fetch one fixed-host public JSON response using verified HTTPS."""

    parsed = httpx.URL(url)
    if parsed.scheme != "https" or parsed.host != "civitai.com":
        return _FetchResult(error="endpoint_invalid")

    contexts = tuple(tls_contexts or create_tls_contexts())
    for source, context in contexts:
        try:
            with httpx.Client(
                transport=transport,
                verify=context,
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                trust_env=False,
            ) as client:
                result = _decode_response(
                    client.get(url),
                    max_response_bytes=max_response_bytes,
                )
        except (httpx.HTTPError, OSError, ssl.SSLError):
            continue
        return _FetchResult(
            payload=result.payload,
            error=result.error,
            tls_context_source=source,
        )
    return _FetchResult(error="request_failed")


def fetch_live_enums(
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
    tls_contexts: Sequence[tuple[str, ssl.SSLContext]] | None = None,
) -> _FetchResult:
    """Fetch the public enum contract using verified HTTPS contexts."""

    return fetch_public_json(
        ENUMS_URL,
        timeout_seconds=timeout_seconds,
        max_response_bytes=MAX_ENUM_RESPONSE_BYTES,
        transport=transport,
        tls_contexts=tls_contexts,
    )


def audit_live_contract(
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
    tls_contexts: Sequence[tuple[str, ssl.SSLContext]] | None = None,
) -> ContractAudit:
    """Fetch and audit the public Civitai enum contract."""

    fetched = fetch_live_enums(
        timeout_seconds=timeout_seconds,
        transport=transport,
        tls_contexts=tls_contexts,
    )
    if fetched.error is not None:
        return ContractAudit(
            errors=(fetched.error,),
            tls_context_source=fetched.tls_context_source,
        )
    return audit_enum_payload(
        fetched.payload,
        tls_context_source=fetched.tls_context_source,
    )


def audit_live_response_contract(
    *,
    endpoint_kind: str,
    identifier: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
    tls_contexts: Sequence[tuple[str, ssl.SSLContext]] | None = None,
) -> ResponseContractAudit:
    """Fetch and validate one caller-selected public identity response."""

    if endpoint_kind == "model_version":
        if not identifier.isdecimal() or int(identifier) < 1:
            return ResponseContractAudit(endpoint_kind, errors=("identifier_invalid",))
        suffix = f"model-versions/{identifier}"
        expected_hash = None
    elif endpoint_kind == "hash":
        if re.fullmatch(r"[0-9A-Fa-f]+", identifier) is None or len(identifier) not in {
            8,
            10,
            12,
            64,
        }:
            return ResponseContractAudit(endpoint_kind, errors=("identifier_invalid",))
        suffix = f"model-versions/by-hash/{identifier}"
        expected_hash = identifier
    else:
        return ResponseContractAudit(endpoint_kind, errors=("endpoint_kind_invalid",))

    fetched = fetch_public_json(
        f"{API_BASE_URL}/{suffix}",
        timeout_seconds=timeout_seconds,
        transport=transport,
        tls_contexts=tls_contexts,
    )
    if fetched.error is not None:
        return ResponseContractAudit(
            endpoint_kind,
            errors=(fetched.error,),
            tls_context_source=fetched.tls_context_source,
        )
    return audit_model_version_payload(
        fetched.payload,
        endpoint_kind=endpoint_kind,
        expected_hash=expected_hash,
        tls_context_source=fetched.tls_context_source,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTPS timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "--model-version-id",
        help="Optionally validate one public model-version response shape.",
    )
    parser.add_argument(
        "--hash",
        dest="resource_hash",
        help="Optionally validate one public by-hash response shape.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not MIN_TIMEOUT_SECONDS <= args.timeout <= MAX_TIMEOUT_SECONDS:
        print(json.dumps({"errors": ["timeout_invalid"], "valid": False}, sort_keys=True))
        return 2
    enum_result = audit_live_contract(timeout_seconds=args.timeout)
    response_results: list[ResponseContractAudit] = []
    if args.model_version_id is not None:
        response_results.append(
            audit_live_response_contract(
                endpoint_kind="model_version",
                identifier=args.model_version_id,
                timeout_seconds=args.timeout,
            )
        )
    if args.resource_hash is not None:
        response_results.append(
            audit_live_response_contract(
                endpoint_kind="hash",
                identifier=args.resource_hash,
                timeout_seconds=args.timeout,
            )
        )
    if not response_results:
        print(json.dumps(enum_result.as_dict(), ensure_ascii=False, sort_keys=True))
        return 0 if enum_result.valid else 1

    valid = enum_result.valid and all(result.valid for result in response_results)
    report = {
        "enumContract": enum_result.as_dict(),
        "responseContracts": [result.as_dict() for result in response_results],
        "valid": valid,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
