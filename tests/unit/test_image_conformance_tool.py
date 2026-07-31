from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from PIL import Image, PngImagePlugin

from tools import audit_image_conformance as conformance

EXPECTED_WIDTH = 2


def _chunk(name: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + name
        + payload
        + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
    )


def _expectation(path: Path, *, format_name: str = "png") -> conformance.ArtifactExpectation:
    return conformance.ArtifactExpectation(
        path=path,
        file_name=path.name,
        format=format_name,
        width=2,
        height=1,
        parameters="prompt\nNegative prompt:\nSize: 2x1",
        software="ComfyUI; CCollins' CiviScribe 2.0.0.dev0",
        prompt={"1": {"class_type": "Test"}},
        workflow={"nodes": []},
        civitai={"schemaName": "test"},
    )


def _sidecar(path: Path) -> None:
    payload = {
        "artifact": {
            "fileName": path.name,
            "format": "png",
            "height": 1,
            "width": 2,
        },
        "generationRecord": {
            "generator": {
                "name": "CCollins' CiviScribe",
                "version": "2.0.0.dev0",
            }
        },
        "payloads": {"prompt": {"1": {}}, "workflow": {"nodes": []}},
        "projections": {"parameters": "Steps: 1", "civitai": {"resources": []}},
    }
    path.with_suffix(".json").write_text(json.dumps(payload), encoding="utf-8")


def test_expectation_from_sidecar_accepts_strict_sibling_json(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(b"image")
    _sidecar(image)

    expectation = conformance.expectation_from_sidecar(image)

    assert expectation.file_name == "sample.png"
    assert expectation.format == "png"
    assert expectation.width == EXPECTED_WIDTH
    assert expectation.parameters == "Steps: 1"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda payload: payload.update({"artifact": []}), "sidecar_artifact_invalid"),
        (
            lambda payload: cast(dict[str, object], payload["artifact"]).update(
                {"fileName": "wrong.png"}
            ),
            "sidecar_filename_mismatch",
        ),
        (
            lambda payload: cast(dict[str, object], payload["artifact"]).update({"format": "jpeg"}),
            "sidecar_format_mismatch",
        ),
    ],
)
def test_expectation_rejects_invalid_sidecar(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    code: str,
) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(b"image")
    _sidecar(image)
    sidecar = image.with_suffix(".json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    mutation(cast(dict[str, object], payload))
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=code):
        conformance.expectation_from_sidecar(image)


def test_png_chunk_parser_checks_crc_and_text_carriers(tmp_path: Path) -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "prompt\nNegative prompt:\nSize: 2x1")
    info.add_text("Software", "ComfyUI; CCollins' CiviScribe 2.0.0.dev0")
    info.add_itxt("prompt", '{"1":{"class_type":"Test"}}')
    info.add_itxt("workflow", '{"nodes":[]}')
    info.add_itxt("civitai", '{"schemaName":"test"}')
    path = tmp_path / "sample.png"
    Image.new("RGB", (2, 1)).save(path, pnginfo=info)
    payload = path.read_bytes()
    insertion = payload.rfind(_chunk(b"IEND", b""))
    path.write_bytes(payload[:insertion] + _chunk(b"eXIf", b"test") + payload[insertion:])

    result = conformance._check_png_carriers(_expectation(path))

    assert result == conformance.CheckResult("png_carriers", conformance.AuditStatus.PASS)
    damaged = bytearray(path.read_bytes())
    damaged[-5] ^= 1
    path.write_bytes(damaged)
    assert (
        conformance._check_png_carriers(_expectation(path)).status is conformance.AuditStatus.FAIL
    )


def test_png_itxt_parser_supports_compressed_text() -> None:
    text = "snow 雪".encode()
    payload = b"prompt\x00\x01\x00\x00\x00" + zlib.compress(text)

    fields = conformance._png_text_fields([("iTXt", payload)])

    assert fields == {"prompt": ("iTXt", "snow 雪")}


def test_png_carriers_require_unicode_fallback_only_when_needed(tmp_path: Path) -> None:
    info = PngImagePlugin.PngInfo()
    parameters = "snow 雪\nNegative prompt:\nSize: 2x1"
    info.add_text("parameters", conformance._latin1_parameters(parameters))
    info.add_text("Software", "ComfyUI; CCollins' CiviScribe 2.0.0.dev0")
    info.add_itxt("parameters_utf8", parameters)
    info.add_itxt("prompt", '{"1":{"class_type":"Test"}}')
    info.add_itxt("workflow", '{"nodes":[]}')
    info.add_itxt("civitai", '{"schemaName":"test"}')
    path = tmp_path / "unicode.png"
    Image.new("RGB", (2, 1)).save(path, pnginfo=info)
    payload = path.read_bytes()
    insertion = payload.rfind(_chunk(b"IEND", b""))
    path.write_bytes(payload[:insertion] + _chunk(b"eXIf", b"test") + payload[insertion:])
    expectation = replace(_expectation(path), parameters=parameters)

    assert conformance._check_png_carriers(expectation).status is conformance.AuditStatus.PASS


def test_png_civitai_expectation_uses_embedded_carrier_references() -> None:
    sidecar_manifest = {
        "workflowRefs": {
            "prompt": "#/payloads/prompt",
            "workflow": "#/payloads/workflow",
        }
    }

    assert conformance._png_civitai_expectation(sidecar_manifest) == {
        "workflowRefs": {
            "prompt": "pnginfo:prompt",
            "workflow": "pnginfo:workflow",
        }
    }


def test_resolve_tools_uses_explicit_regular_file(tmp_path: Path) -> None:
    executable = tmp_path / "tool.exe"
    executable.write_bytes(b"tool")

    tools = conformance.resolve_tools({"exiftool": executable})

    assert tools.exiftool == executable.resolve()


def test_external_check_distinguishes_unavailable_and_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    unavailable = conformance._external_check("tool", None, ())
    assert unavailable.status is conformance.AuditStatus.UNAVAILABLE

    monkeypatch.setattr(
        conformance,
        "_run_process",
        lambda *_args, **_kwargs: conformance.ProcessResult(3, b"", b"private path"),
    )
    failed = conformance._external_check("tool", tmp_path / "tool.exe", ())
    assert failed == conformance.CheckResult(
        "tool",
        conformance.AuditStatus.FAIL,
        "validator_exit_3",
    )


def test_exiftool_payload_checks_expected_metadata() -> None:
    expectation = _expectation(Path("sample.png"))
    payload: dict[str, object] = {
        "ExifTool:Validate": "0 0 0",
        "File:MIMEType": "image/png",
        "PNG:ImageWidth": 2,
        "PNG:ImageHeight": 1,
        "PNG:Parameters": expectation.parameters,
        "PNG:Software": expectation.software,
        "PNG:Prompt": '{"1":{"class_type":"Test"}}',
        "PNG:Workflow": '{"nodes":[]}',
        "PNG:Civitai": '{"schemaName":"test"}',
        "ExifIFD:ExifVersion": "0232",
        "ExifIFD:UserComment": expectation.parameters,
        "ExifIFD:ExifImageWidth": 2,
        "ExifIFD:ExifImageHeight": 1,
    }

    result = conformance._check_exiftool_payload(expectation, payload)

    assert result.status is conformance.AuditStatus.PASS
    payload["ExifTool:Warning"] = "C:\\Users\\private"
    assert (
        conformance._check_exiftool_payload(expectation, payload).detail == "validator_diagnostic"
    )


def test_report_payload_contains_no_paths_or_raw_diagnostics() -> None:
    report = conformance.ConformanceReport(
        schema_name="ccollins-civiscribe.image-conformance-report",
        schema_version="1.0.0",
        profile="release",
        status=conformance.AuditStatus.PASS,
        tools=(conformance.ToolRecord("tool", conformance.AuditStatus.PASS, "1.2.3"),),
        artifacts=(
            conformance.ArtifactReport(
                file_name="sample.png",
                format="png",
                checks=(conformance.CheckResult("check", conformance.AuditStatus.PASS),),
                status=conformance.AuditStatus.PASS,
            ),
        ),
    )

    encoded = json.dumps(conformance.report_payload(report))

    assert "C:\\Users\\" not in encoded
    assert "/home/" not in encoded


def test_report_payload_rejects_private_values() -> None:
    report = conformance.ConformanceReport(
        schema_name="ccollins-civiscribe.image-conformance-report",
        schema_version="1.0.0",
        profile="release",
        status=conformance.AuditStatus.FAIL,
        tools=(),
        artifacts=(
            conformance.ArtifactReport(
                file_name="C:\\Users\\private.png",
                format="png",
                checks=(),
                status=conformance.AuditStatus.FAIL,
            ),
        ),
    )
    with pytest.raises(ValueError, match="report_privacy_violation"):
        conformance.report_payload(report)


def test_combined_status_honors_release_tool_requirement() -> None:
    checks = [conformance.CheckResult("tool", conformance.AuditStatus.UNAVAILABLE)]
    assert conformance._combined_status(checks, require_tools=False) is conformance.AuditStatus.PASS
    assert (
        conformance._combined_status(checks, require_tools=True)
        is conformance.AuditStatus.UNAVAILABLE
    )


def test_imagemagick_policy_can_be_reused_across_batch(tmp_path: Path) -> None:
    first = conformance._imagemagick_environment(tmp_path)
    second = conformance._imagemagick_environment(tmp_path)

    assert first["MAGICK_CONFIGURE_PATH"] == second["MAGICK_CONFIGURE_PATH"]
    policy = tmp_path / "imagemagick-policy" / "policy.xml"
    assert policy.is_file()
    assert 'pattern="{PNG,JPEG,WEBP}"' in policy.read_text(encoding="utf-8")
