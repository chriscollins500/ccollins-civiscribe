"""Independent PNG, JPEG, and WebP release-conformance checks.

This module is development tooling. It is deliberately outside the runtime
package and invokes only explicitly configured or PATH-discovered validators.
Reports contain basenames and stable status codes, never local filesystem paths
or raw tool diagnostics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata
import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from PIL import Image, UnidentifiedImageError

MAX_ARTIFACT_BYTES: Final = 256 * 1024 * 1024
MAX_TOOL_OUTPUT_BYTES: Final = 4 * 1024 * 1024
TOOL_TIMEOUT_SECONDS: Final = 30.0
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
USER_COMMENT_PREFIX: Final = b"UNICODE\x00"
EXIF_IFD_TAG: Final = 0x8769
SOFTWARE_TAG: Final = 0x0131
YCBCR_POSITIONING_TAG: Final = 0x0213
EXIF_VERSION_TAG: Final = 0x9000
COMPONENTS_CONFIGURATION_TAG: Final = 0x9101
USER_COMMENT_TAG: Final = 0x9286
FLASHPIX_VERSION_TAG: Final = 0xA000
COLOR_SPACE_TAG: Final = 0xA001
PIXEL_X_DIMENSION_TAG: Final = 0xA002
PIXEL_Y_DIMENSION_TAG: Final = 0xA003
YCBCR_COMPONENTS_CONFIGURATION: Final = b"\x01\x02\x03\x00"
FLASHPIX_VERSION: Final = b"0100"
COLOR_SPACE_UNCALIBRATED: Final = 0xFFFF
YCBCR_POSITIONING_CENTERED: Final = 1
ABSOLUTE_PATH_PATTERN: Final = re.compile(
    r"(?i)(?:[a-z]:[\\/]|\\\\[^\\\s]+\\[^\\\s]+|/(?:users|home)/)"
)
SECRET_PATTERN: Final = re.compile(
    r"(?i)(?:authorization\s*[:=]\s*bearer|api[_ -]?key\s*[:=]|token\s*[:=])"
)
VERSION_PATTERN: Final = re.compile(r"\b\d+(?:\.\d+){1,3}\b")


class AuditStatus(StrEnum):
    """Stable report statuses."""

    PASS = "pass"  # noqa: S105 - a validation status, not a credential.
    FAIL = "fail"
    UNAVAILABLE = "unavailable"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class AuditProfile(StrEnum):
    """Supported independent-reader profiles."""

    RELEASE = "release"
    DEEP = "deep"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One privacy-safe validation result."""

    check: str
    status: AuditStatus
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ToolRecord:
    """One discovered validator without its local executable path."""

    name: str
    status: AuditStatus
    version: str | None


@dataclass(frozen=True, slots=True)
class ArtifactExpectation:
    """Expected media facts derived from the sibling CiviScribe sidecar."""

    path: Path
    file_name: str
    format: str
    width: int
    height: int
    parameters: str
    software: str
    prompt: object | None
    workflow: object | None
    civitai: object | None


@dataclass(frozen=True, slots=True)
class ArtifactReport:
    """Conformance results for one generated media file."""

    file_name: str
    format: str
    checks: tuple[CheckResult, ...]
    status: AuditStatus


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    """Deterministic, path-free conformance report."""

    schema_name: str
    schema_version: str
    profile: str
    status: AuditStatus
    tools: tuple[ToolRecord, ...]
    artifacts: tuple[ArtifactReport, ...]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Executable discovery and version-query contract."""

    name: str
    aliases: tuple[str, ...]
    version_args: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ToolPaths:
    """Resolved validator executables used only by this development process."""

    exiftool: Path | None
    pngcheck: Path | None
    djpeg: Path | None
    webpinfo: Path | None
    dwebp: Path | None
    exiv2: Path | None = None
    imagemagick: Path | None = None


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Bounded subprocess result."""

    returncode: int
    stdout: bytes
    stderr: bytes


TOOL_SPECS: Final[dict[str, ToolSpec]] = {
    "exiftool": ToolSpec("exiftool", ("exiftool", "exiftool.exe"), ("-ver",)),
    "pngcheck": ToolSpec(
        "pngcheck",
        ("pngcheck", "pngcheck.exe", "pngcheck.win64.exe", "pngcheck.win32.exe"),
        ("-v",),
    ),
    "djpeg": ToolSpec("djpeg", ("djpeg", "djpeg.exe"), ("-version",)),
    "webpinfo": ToolSpec("webpinfo", ("webpinfo", "webpinfo.exe"), ("-version",)),
    "dwebp": ToolSpec("dwebp", ("dwebp", "dwebp.exe"), ("-version",)),
    "exiv2": ToolSpec("exiv2", ("exiv2", "exiv2.exe"), ("-V",)),
    "imagemagick": ToolSpec("imagemagick", ("magick", "magick.exe"), ("-version",)),
}


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("sidecar_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("sidecar_root_invalid")
    return cast(dict[str, object], payload)


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return cast(Mapping[str, object], value)


def _integer(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(code)
    return value


def _text(value: object, code: str) -> str:
    if not isinstance(value, str):
        raise ValueError(code)
    return value


def expectation_from_sidecar(media_path: Path) -> ArtifactExpectation:
    """Load exact expected facts from a sibling CiviScribe sidecar."""

    path = media_path.resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise ValueError("artifact_not_regular_file")
    size = path.stat().st_size
    if size < 1 or size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact_size_invalid")
    sidecar = path.with_suffix(".json")
    payload = _load_json(sidecar)
    artifact = _mapping(payload.get("artifact"), "sidecar_artifact_invalid")
    projections = _mapping(payload.get("projections"), "sidecar_projections_invalid")
    generation_record = _mapping(
        payload.get("generationRecord"),
        "sidecar_generation_record_invalid",
    )
    generator = _mapping(generation_record.get("generator"), "sidecar_generator_invalid")
    payloads = _mapping(payload.get("payloads"), "sidecar_payloads_invalid")
    file_name = _text(artifact.get("fileName"), "sidecar_filename_invalid")
    if file_name != path.name or Path(file_name).name != file_name:
        raise ValueError("sidecar_filename_mismatch")
    format_name = _text(artifact.get("format"), "sidecar_format_invalid").casefold()
    expected_suffixes = {
        "png": {".png"},
        "jpeg": {".jpg", ".jpeg"},
        "webp": {".webp"},
    }
    if path.suffix.casefold() not in expected_suffixes.get(format_name, set()):
        raise ValueError("sidecar_format_mismatch")
    app_name = _text(generator.get("name"), "sidecar_generator_name_invalid")
    app_version = _text(generator.get("version"), "sidecar_generator_version_invalid")
    parameters = _text(projections.get("parameters"), "sidecar_parameters_invalid")
    return ArtifactExpectation(
        path=path,
        file_name=file_name,
        format=format_name,
        width=_integer(artifact.get("width"), "sidecar_width_invalid"),
        height=_integer(artifact.get("height"), "sidecar_height_invalid"),
        parameters=parameters,
        software=f"ComfyUI; {app_name} {app_version}",
        prompt=payloads.get("prompt"),
        workflow=payloads.get("workflow"),
        civitai=projections.get("civitai"),
    )


def _decode_user_comment(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, bytes) or not value.startswith(USER_COMMENT_PREFIX):
        return None
    return value[len(USER_COMMENT_PREFIX) :].decode("utf-16-be", errors="replace")


def _check_pillow(expectation: ArtifactExpectation) -> CheckResult:  # noqa: PLR0911
    expected_format = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[expectation.format]
    try:
        with Image.open(expectation.path) as image:
            image.load()
            if image.format != expected_format:
                return CheckResult("pillow_full_decode", AuditStatus.FAIL, "format_mismatch")
            if image.size != (expectation.width, expectation.height):
                return CheckResult("pillow_full_decode", AuditStatus.FAIL, "dimensions_mismatch")
            exif = image.getexif()
            try:
                nested = exif.get_ifd(EXIF_IFD_TAG)
            except (KeyError, TypeError, ValueError):
                nested = {}
            if _decode_user_comment(nested.get(USER_COMMENT_TAG)) != expectation.parameters:
                return CheckResult(
                    "pillow_full_decode",
                    AuditStatus.FAIL,
                    "exif_user_comment_mismatch",
                )
            if expectation.format != "png":
                if exif.get(SOFTWARE_TAG) != expectation.software:
                    return CheckResult("pillow_full_decode", AuditStatus.FAIL, "software_mismatch")
                if nested.get(PIXEL_X_DIMENSION_TAG) != expectation.width:
                    return CheckResult(
                        "pillow_full_decode",
                        AuditStatus.FAIL,
                        "exif_width_mismatch",
                    )
                if nested.get(PIXEL_Y_DIMENSION_TAG) != expectation.height:
                    return CheckResult(
                        "pillow_full_decode",
                        AuditStatus.FAIL,
                        "exif_height_mismatch",
                    )
            if expectation.format == "jpeg" and (
                nested.get(COMPONENTS_CONFIGURATION_TAG) != YCBCR_COMPONENTS_CONFIGURATION
                or nested.get(FLASHPIX_VERSION_TAG) != FLASHPIX_VERSION
                or nested.get(COLOR_SPACE_TAG) != COLOR_SPACE_UNCALIBRATED
                or exif.get(YCBCR_POSITIONING_TAG) != YCBCR_POSITIONING_CENTERED
            ):
                return CheckResult(
                    "pillow_full_decode",
                    AuditStatus.FAIL,
                    "jpeg_required_exif_fields_mismatch",
                )
            if nested.get(EXIF_VERSION_TAG) != b"0232":
                return CheckResult("pillow_full_decode", AuditStatus.FAIL, "exif_version_mismatch")
    except (OSError, ValueError, UnicodeError, UnidentifiedImageError):
        return CheckResult("pillow_full_decode", AuditStatus.FAIL, "decode_failed")
    return CheckResult("pillow_full_decode", AuditStatus.PASS)


def _read_png_chunks(path: Path) -> list[tuple[str, bytes]]:
    payload = path.read_bytes()
    if not payload.startswith(PNG_SIGNATURE):
        raise ValueError("png_signature_invalid")
    chunks: list[tuple[str, bytes]] = []
    offset = len(PNG_SIGNATURE)
    saw_iend = False
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise ValueError("png_chunk_truncated")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type_bytes = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(payload):
            raise ValueError("png_chunk_truncated")
        data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : end])[0]
        actual_crc = zlib.crc32(chunk_type_bytes + data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("png_crc_invalid")
        try:
            chunk_type = chunk_type_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("png_chunk_type_invalid") from exc
        chunks.append((chunk_type, data))
        offset = end
        if chunk_type == "IEND":
            saw_iend = True
            break
    if not saw_iend or offset != len(payload):
        raise ValueError("png_iend_invalid")
    return chunks


def _png_text_fields(chunks: Iterable[tuple[str, bytes]]) -> dict[str, tuple[str, str]]:
    fields: dict[str, tuple[str, str]] = {}
    for chunk_type, payload in chunks:
        if chunk_type == "tEXt":
            try:
                keyword_bytes, value_bytes = payload.split(b"\x00", 1)
                keyword = keyword_bytes.decode("latin-1")
                value = value_bytes.decode("latin-1")
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("png_text_invalid") from exc
        elif chunk_type == "iTXt":
            try:
                keyword_bytes, rest = payload.split(b"\x00", 1)
                if len(rest) < len(b"\x00\x00"):
                    raise ValueError
                compressed = rest[0]
                method = rest[1]
                rest = rest[2:]
                _language, rest = rest.split(b"\x00", 1)
                _translated, text_bytes = rest.split(b"\x00", 1)
                if compressed == 1:
                    if method != 0:
                        raise ValueError
                    text_bytes = zlib.decompress(text_bytes)
                elif compressed != 0:
                    raise ValueError
                keyword = keyword_bytes.decode("latin-1")
                value = text_bytes.decode("utf-8")
            except (ValueError, UnicodeDecodeError, zlib.error) as exc:
                raise ValueError("png_itxt_invalid") from exc
        else:
            continue
        if keyword in fields:
            raise ValueError("png_text_keyword_duplicate")
        fields[keyword] = (chunk_type, value)
    return fields


def _json_text_matches(value: str, expected: object) -> bool:
    try:
        decoded: object = json.loads(value, object_pairs_hook=_strict_object)
        return decoded == expected
    except (json.JSONDecodeError, ValueError):
        return False


def _png_civitai_expectation(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    result = dict(value)
    workflow_refs = result.get("workflowRefs")
    if isinstance(workflow_refs, Mapping):
        result["workflowRefs"] = {
            **workflow_refs,
            "prompt": "pnginfo:prompt",
            "workflow": ("pnginfo:workflow" if workflow_refs.get("workflow") is not None else None),
        }
    return result


def _latin1_parameters(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return normalized.encode("latin-1", errors="replace").decode("latin-1")


def _check_png_carriers(expectation: ArtifactExpectation) -> CheckResult:  # noqa: PLR0911
    if expectation.format != "png":
        return CheckResult("png_carriers", AuditStatus.PASS, "not_applicable")
    try:
        chunks = _read_png_chunks(expectation.path)
        fields = _png_text_fields(chunks)
        latin1_parameters = _latin1_parameters(expectation.parameters)
        if fields.get("parameters") != ("tEXt", latin1_parameters):
            return CheckResult("png_carriers", AuditStatus.FAIL, "parameters_carrier_mismatch")
        if fields.get("Software") != ("tEXt", expectation.software):
            return CheckResult("png_carriers", AuditStatus.FAIL, "software_carrier_mismatch")
        expected_json_fields = {
            "prompt": expectation.prompt,
            "workflow": expectation.workflow,
            "civitai": _png_civitai_expectation(expectation.civitai),
        }
        for keyword, expected in expected_json_fields.items():
            field = fields.get(keyword)
            if expected is None:
                if field is not None:
                    return CheckResult(
                        "png_carriers",
                        AuditStatus.FAIL,
                        f"{keyword}_unexpected",
                    )
                continue
            if field is None or field[0] != "iTXt" or not _json_text_matches(field[1], expected):
                return CheckResult(
                    "png_carriers",
                    AuditStatus.FAIL,
                    f"{keyword}_carrier_mismatch",
                )
        utf8_parameters = fields.get("parameters_utf8")
        if latin1_parameters == expectation.parameters:
            if utf8_parameters is not None:
                return CheckResult(
                    "png_carriers",
                    AuditStatus.FAIL,
                    "parameters_utf8_unexpected",
                )
        elif utf8_parameters != ("iTXt", expectation.parameters):
            return CheckResult(
                "png_carriers",
                AuditStatus.FAIL,
                "parameters_utf8_mismatch",
            )
        if not any(chunk_type == "eXIf" for chunk_type, _payload in chunks):
            return CheckResult("png_carriers", AuditStatus.FAIL, "exif_chunk_missing")
    except (OSError, ValueError):
        return CheckResult("png_carriers", AuditStatus.FAIL, "png_parse_failed")
    return CheckResult("png_carriers", AuditStatus.PASS)


def _resolve_tool(explicit: Path | None, spec: ToolSpec) -> Path | None:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        return candidate if candidate.is_file() else None
    for alias in spec.aliases:
        discovered = shutil.which(alias)
        if discovered is not None:
            return Path(discovered).resolve()
    return None


def resolve_tools(explicit: Mapping[str, Path | None]) -> ToolPaths:
    """Resolve every supported development validator."""

    resolved = {name: _resolve_tool(explicit.get(name), spec) for name, spec in TOOL_SPECS.items()}
    return ToolPaths(**resolved)


def _run_process(
    executable: Path,
    arguments: Sequence[str],
    *,
    timeout: float = TOOL_TIMEOUT_SECONDS,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    try:
        result = subprocess.run(  # noqa: S603
            [str(executable), *arguments],
            check=False,
            capture_output=True,
            shell=False,
            timeout=timeout,
            env=dict(env) if env is not None else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("validator_execution_failed") from exc
    if len(result.stdout) + len(result.stderr) > MAX_TOOL_OUTPUT_BYTES:
        raise RuntimeError("validator_output_too_large")
    return ProcessResult(result.returncode, result.stdout, result.stderr)


def _tool_version(executable: Path, spec: ToolSpec) -> str | None:
    try:
        result = _run_process(executable, spec.version_args, timeout=10.0)
    except RuntimeError:
        return None
    text = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
    match = VERSION_PATTERN.search(text)
    return match.group(0) if match is not None else None


def tool_records(tools: ToolPaths, profile: AuditProfile) -> tuple[ToolRecord, ...]:
    """Describe tool availability without exposing executable paths."""

    required_names = ["exiftool", "pngcheck", "djpeg", "webpinfo", "dwebp"]
    if profile is AuditProfile.DEEP:
        required_names.extend(("exiv2", "imagemagick"))
    records: list[ToolRecord] = []
    for name in required_names:
        executable = cast(Path | None, getattr(tools, name))
        records.append(
            ToolRecord(
                name=name,
                status=AuditStatus.PASS if executable is not None else AuditStatus.UNAVAILABLE,
                version=_tool_version(executable, TOOL_SPECS[name])
                if executable is not None
                else None,
            )
        )
    return tuple(records)


def _external_check(
    check: str,
    executable: Path | None,
    arguments: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> CheckResult:
    if executable is None:
        return CheckResult(check, AuditStatus.UNAVAILABLE, "validator_unavailable")
    try:
        result = _run_process(executable, arguments, env=env)
    except RuntimeError:
        return CheckResult(check, AuditStatus.INFRASTRUCTURE_ERROR, "validator_failed")
    if result.returncode != 0:
        return CheckResult(check, AuditStatus.FAIL, f"validator_exit_{result.returncode}")
    return CheckResult(check, AuditStatus.PASS)


def _decode_with_temp_output(
    check: str,
    executable: Path | None,
    arguments: Sequence[str],
    expectation: ArtifactExpectation,
    output_path: Path,
) -> CheckResult:
    if executable is None:
        return CheckResult(check, AuditStatus.UNAVAILABLE, "validator_unavailable")
    result = _external_check(check, executable, arguments)
    if result.status is not AuditStatus.PASS:
        return result
    try:
        with Image.open(output_path) as decoded:
            decoded.load()
            if decoded.size != (expectation.width, expectation.height):
                return CheckResult(check, AuditStatus.FAIL, "decoded_dimensions_mismatch")
    except (OSError, UnidentifiedImageError):
        return CheckResult(check, AuditStatus.FAIL, "decoded_output_invalid")
    return result


def _exiftool_batch(
    expectations: Sequence[ArtifactExpectation],
    executable: Path | None,
) -> dict[str, CheckResult]:
    if executable is None:
        return {
            item.file_name: CheckResult(
                "exiftool_metadata",
                AuditStatus.UNAVAILABLE,
                "validator_unavailable",
            )
            for item in expectations
        }
    arguments = [
        "-j",
        "-G1",
        "-n",
        "-all",
        "-validate",
        "-warning",
        "-error",
        *(str(item.path) for item in expectations),
    ]
    try:
        result = _run_process(executable, arguments)
    except RuntimeError:
        return {
            item.file_name: CheckResult(
                "exiftool_metadata",
                AuditStatus.INFRASTRUCTURE_ERROR,
                "validator_failed",
            )
            for item in expectations
        }
    if result.returncode != 0:
        return {
            item.file_name: CheckResult(
                "exiftool_metadata",
                AuditStatus.FAIL,
                f"validator_exit_{result.returncode}",
            )
            for item in expectations
        }
    try:
        decoded = json.loads(result.stdout.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return {
            item.file_name: CheckResult(
                "exiftool_metadata",
                AuditStatus.INFRASTRUCTURE_ERROR,
                "validator_output_invalid",
            )
            for item in expectations
        }
    if not isinstance(decoded, list):
        return {
            item.file_name: CheckResult(
                "exiftool_metadata",
                AuditStatus.INFRASTRUCTURE_ERROR,
                "validator_output_invalid",
            )
            for item in expectations
        }
    by_name: dict[str, Mapping[str, object]] = {}
    for raw in decoded:
        if not isinstance(raw, Mapping):
            continue
        source = raw.get("SourceFile")
        if isinstance(source, str):
            by_name[Path(source).name] = cast(Mapping[str, object], raw)
    return {
        item.file_name: _check_exiftool_payload(item, by_name.get(item.file_name))
        for item in expectations
    }


def _check_exiftool_payload(  # noqa: PLR0911, PLR0912
    expectation: ArtifactExpectation,
    payload: Mapping[str, object] | None,
) -> CheckResult:
    if payload is None:
        return CheckResult(
            "exiftool_metadata",
            AuditStatus.INFRASTRUCTURE_ERROR,
            "artifact_result_missing",
        )
    if "ExifTool:Warning" in payload or "ExifTool:Error" in payload:
        return CheckResult("exiftool_metadata", AuditStatus.FAIL, "validator_diagnostic")
    validation = payload.get("ExifTool:Validate")
    if validation is not None and validation != "0 0 0":
        return CheckResult("exiftool_metadata", AuditStatus.FAIL, "validation_failed")
    expected_mime = {
        "png": "image/png",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }[expectation.format]
    if payload.get("File:MIMEType") != expected_mime:
        return CheckResult("exiftool_metadata", AuditStatus.FAIL, "mime_mismatch")
    width_keys = {
        "png": "PNG:ImageWidth",
        "jpeg": "File:ImageWidth",
        "webp": "RIFF:ImageWidth",
    }
    height_keys = {
        "png": "PNG:ImageHeight",
        "jpeg": "File:ImageHeight",
        "webp": "RIFF:ImageHeight",
    }
    if payload.get(width_keys[expectation.format]) != expectation.width:
        return CheckResult("exiftool_metadata", AuditStatus.FAIL, "width_mismatch")
    if payload.get(height_keys[expectation.format]) != expectation.height:
        return CheckResult("exiftool_metadata", AuditStatus.FAIL, "height_mismatch")
    if payload.get("ExifIFD:UserComment") != expectation.parameters:
        return CheckResult("exiftool_metadata", AuditStatus.FAIL, "user_comment_mismatch")
    if payload.get("IFD0:Software", payload.get("PNG:Software")) != expectation.software:
        return CheckResult("exiftool_metadata", AuditStatus.FAIL, "software_mismatch")
    if expectation.format != "png":
        if payload.get("ExifIFD:ExifImageWidth") != expectation.width:
            return CheckResult("exiftool_metadata", AuditStatus.FAIL, "exif_width_mismatch")
        if payload.get("ExifIFD:ExifImageHeight") != expectation.height:
            return CheckResult("exiftool_metadata", AuditStatus.FAIL, "exif_height_mismatch")
    if payload.get("ExifIFD:ExifVersion") != "0232":
        return CheckResult("exiftool_metadata", AuditStatus.FAIL, "exif_version_mismatch")
    if expectation.format == "png":
        if payload.get("PNG:Parameters") != _latin1_parameters(expectation.parameters):
            return CheckResult("exiftool_metadata", AuditStatus.FAIL, "parameters_mismatch")
        for key, expected in {
            "PNG:Prompt": expectation.prompt,
            "PNG:Workflow": expectation.workflow,
            "PNG:Civitai": _png_civitai_expectation(expectation.civitai),
        }.items():
            value = payload.get(key)
            if expected is None:
                if value is not None:
                    return CheckResult("exiftool_metadata", AuditStatus.FAIL, "field_unexpected")
            elif not isinstance(value, str) or not _json_text_matches(value, expected):
                return CheckResult("exiftool_metadata", AuditStatus.FAIL, "json_field_mismatch")
    return CheckResult("exiftool_metadata", AuditStatus.PASS)


def _imagemagick_environment(temp_root: Path) -> dict[str, str]:
    policy_root = temp_root / "imagemagick-policy"
    policy_root.mkdir(exist_ok=True)
    policy = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policymap [
  <!ELEMENT policymap (policy)+>
  <!ELEMENT policy EMPTY>
  <!ATTLIST policy domain NMTOKEN #REQUIRED>
  <!ATTLIST policy name NMTOKEN #IMPLIED>
  <!ATTLIST policy rights NMTOKEN #IMPLIED>
  <!ATTLIST policy pattern CDATA #IMPLIED>
  <!ATTLIST policy value CDATA #IMPLIED>
]>
<policymap>
  <policy domain="resource" name="memory" value="256MiB"/>
  <policy domain="resource" name="map" value="512MiB"/>
  <policy domain="resource" name="disk" value="1GiB"/>
  <policy domain="resource" name="width" value="32768"/>
  <policy domain="resource" name="height" value="32768"/>
  <policy domain="resource" name="area" value="256MP"/>
  <policy domain="resource" name="list-length" value="8"/>
  <policy domain="resource" name="thread" value="4"/>
  <policy domain="resource" name="time" value="30"/>
  <policy domain="delegate" rights="none" pattern="*"/>
  <policy domain="path" rights="none" pattern="@*"/>
  <policy domain="coder" rights="none" pattern="*"/>
  <policy domain="coder" rights="read" pattern="{PNG,JPEG,WEBP}"/>
</policymap>
"""
    (policy_root / "policy.xml").write_text(policy, encoding="utf-8", newline="\n")
    environment = dict(os.environ)
    environment["MAGICK_CONFIGURE_PATH"] = str(policy_root)
    environment["MAGICK_TEMPORARY_PATH"] = str(temp_root)
    return environment


def _artifact_external_checks(
    expectation: ArtifactExpectation,
    tools: ToolPaths,
    profile: AuditProfile,
    temp_root: Path,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if expectation.format == "png":
        checks.append(
            _external_check(
                "pngcheck",
                tools.pngcheck,
                ("-v", str(expectation.path)),
            )
        )
    elif expectation.format == "jpeg":
        output_path = temp_root / f"{expectation.file_name}.ppm"
        checks.append(
            _decode_with_temp_output(
                "djpeg",
                tools.djpeg,
                ("-outfile", str(output_path), str(expectation.path)),
                expectation,
                output_path,
            )
        )
    elif expectation.format == "webp":
        checks.append(
            _external_check(
                "webpinfo",
                tools.webpinfo,
                ("-diag", "-summary", str(expectation.path)),
            )
        )
        checks.append(
            _decode_with_temp_output(
                "dwebp",
                tools.dwebp,
                (
                    str(expectation.path),
                    "-o",
                    str(temp_root / f"{expectation.file_name}.png"),
                ),
                expectation,
                temp_root / f"{expectation.file_name}.png",
            )
        )
    if profile is AuditProfile.DEEP:
        checks.append(
            _external_check(
                "exiv2",
                tools.exiv2,
                ("-pa", str(expectation.path)),
            )
        )
        checks.append(
            _external_check(
                "imagemagick",
                tools.imagemagick,
                ("identify", "-regard-warnings", str(expectation.path)),
                env=_imagemagick_environment(temp_root),
            )
        )
    return checks


def _combined_status(
    checks: Iterable[CheckResult],
    *,
    require_tools: bool,
) -> AuditStatus:
    statuses = {item.status for item in checks}
    if AuditStatus.FAIL in statuses:
        return AuditStatus.FAIL
    if AuditStatus.INFRASTRUCTURE_ERROR in statuses:
        return AuditStatus.INFRASTRUCTURE_ERROR
    if require_tools and AuditStatus.UNAVAILABLE in statuses:
        return AuditStatus.UNAVAILABLE
    return AuditStatus.PASS


def audit_images(
    expectations: Sequence[ArtifactExpectation],
    *,
    tools: ToolPaths,
    profile: AuditProfile = AuditProfile.RELEASE,
    require_tools: bool = False,
    temporary_parent: Path | None = None,
) -> ConformanceReport:
    """Audit generated media without retaining paths or raw diagnostics."""

    if not expectations:
        raise ValueError("no_artifacts")
    names = [item.file_name.casefold() for item in expectations]
    if len(set(names)) != len(names):
        raise ValueError("duplicate_artifact_filename")
    exiftool_results = _exiftool_batch(expectations, tools.exiftool)
    artifact_reports: list[ArtifactReport] = []
    with tempfile.TemporaryDirectory(dir=temporary_parent) as temporary:
        temp_root = Path(temporary)
        for expectation in expectations:
            checks = [
                _check_pillow(expectation),
                _check_png_carriers(expectation),
                exiftool_results[expectation.file_name],
                *_artifact_external_checks(expectation, tools, profile, temp_root),
            ]
            artifact_reports.append(
                ArtifactReport(
                    file_name=expectation.file_name,
                    format=expectation.format,
                    checks=tuple(checks),
                    status=_combined_status(checks, require_tools=require_tools),
                )
            )
    records = tool_records(tools, profile)
    overall_checks = [check for artifact in artifact_reports for check in artifact.checks]
    overall = _combined_status(overall_checks, require_tools=require_tools)
    return ConformanceReport(
        schema_name="ccollins-civiscribe.image-conformance-report",
        schema_version="1.0.0",
        profile=profile.value,
        status=overall,
        tools=records,
        artifacts=tuple(artifact_reports),
    )


def report_payload(report: ConformanceReport) -> dict[str, object]:
    """Serialize a report and enforce its privacy boundary."""

    raw = cast(dict[str, object], asdict(report))
    artifacts = cast(list[dict[str, object]], raw.pop("artifacts"))
    for artifact in artifacts:
        artifact["fileName"] = artifact.pop("file_name")
    payload = {
        "schemaName": raw.pop("schema_name"),
        "schemaVersion": raw.pop("schema_version"),
        **raw,
        "artifacts": artifacts,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if ABSOLUTE_PATH_PATTERN.search(encoded) or SECRET_PATTERN.search(encoded):
        raise ValueError("report_privacy_violation")
    return payload


def write_report(report: ConformanceReport, destination: Path) -> None:
    """Write deterministic strict JSON below the caller-selected audit directory."""

    payload = report_payload(report)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--profile", choices=tuple(AuditProfile), default=AuditProfile.RELEASE)
    parser.add_argument("--require-tools", action="store_true")
    parser.add_argument("--report", required=True, type=Path)
    for name in TOOL_SPECS:
        parser.add_argument(f"--{name}", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the conformance CLI."""

    args = _parser().parse_args(argv)
    try:
        expectations = tuple(expectation_from_sidecar(path) for path in args.images)
        explicit = {name: getattr(args, name) for name in TOOL_SPECS}
        tools = resolve_tools(explicit)
        report = audit_images(
            expectations,
            tools=tools,
            profile=AuditProfile(args.profile),
            require_tools=args.require_tools,
            temporary_parent=args.report.parent,
        )
        write_report(report, args.report)
    except (OSError, ValueError) as exc:
        code = str(exc)
        print(code if re.fullmatch(r"[a-z0-9_]+", code) else "conformance_audit_failed")
        return 2
    print(f"{report.status.value}: {len(report.artifacts)} artifact(s)")
    return 0 if report.status is AuditStatus.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
