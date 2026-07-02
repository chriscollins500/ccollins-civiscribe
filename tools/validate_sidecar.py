"""Validate comfyui-civitai-save-node JSON sidecars without network or mutation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = (
    "sidecarFormat",
    "sidecarSchemaVersion",
    "generator",
    "image",
    "pngMetadata",
    "civitai",
    "resourceLifecycle",
    "warnings",
    "errors",
    "privacy",
)
EXPECTED_FORMAT = "comfyui-civitai-save-node.sidecar"


@dataclass(frozen=True)
class SidecarValidationReport:
    file_name: str
    ok: bool
    messages: tuple[str, ...] = field(default_factory=tuple)
    schema_validation: str = "skipped"

    def to_text(self) -> str:
        lines = [
            f"sidecar: {self.file_name}",
            "json: ok"
            if self.ok or not any(message.startswith("json: failed") for message in self.messages)
            else "json: failed",
        ]
        lines.extend(self.messages)
        lines.append(f"jsonSchema: {self.schema_validation}")
        lines.append(f"result: {'ok' if self.ok else 'failed'}")
        return "\n".join(_sanitize_line(line) for line in lines)


def validate_sidecar_file(path: Path, *, schema_path: Path | None = None) -> SidecarValidationReport:
    file_name = Path(path).name
    messages: list[str] = []
    schema_status = "skipped"

    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return SidecarValidationReport(
            file_name=file_name,
            ok=False,
            messages=(f"read: failed: {_sanitize_exception(exc)}",),
            schema_validation=schema_status,
        )

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return SidecarValidationReport(
            file_name=file_name,
            ok=False,
            messages=(f"utf8: failed: {_sanitize_exception(exc)}",),
            schema_validation=schema_status,
        )
    messages.append("utf8: ok")

    if raw.endswith(b"\n"):
        messages.append("newlineAtEof: ok")
    else:
        messages.append("newlineAtEof: missing")

    try:
        data = _loads_strict_json(text)
    except ValueError as exc:
        return SidecarValidationReport(
            file_name=file_name,
            ok=False,
            messages=(*messages, f"json: failed: {_sanitize_exception(exc)}"),
            schema_validation=schema_status,
        )
    messages.append("json: strict-ok")

    missing = [key for key in REQUIRED_TOP_LEVEL if key not in data]
    if missing:
        messages.append(f"requiredFields: missing {', '.join(missing)}")
    else:
        messages.append("requiredFields: ok")

    if data.get("sidecarFormat") == EXPECTED_FORMAT:
        messages.append("sidecarFormat: ok")
    else:
        messages.append("sidecarFormat: unexpected")

    schema_file = schema_path or _default_schema_path()
    schema_ok = True
    if schema_file.exists():
        try:
            import jsonschema
        except ImportError:
            schema_status = "skipped: jsonschema not installed"
        else:
            try:
                schema = _loads_strict_json(schema_file.read_text(encoding="utf-8"))
                jsonschema.Draft202012Validator(schema).validate(data)
                schema_status = "ok"
            except Exception as exc:
                schema_ok = False
                schema_status = f"failed: {_sanitize_exception(exc)}"
    else:
        schema_status = "skipped: schema file not found"

    ok = not missing and data.get("sidecarFormat") == EXPECTED_FORMAT and schema_ok
    return SidecarValidationReport(
        file_name=file_name,
        ok=ok,
        messages=tuple(messages),
        schema_validation=schema_status,
    )


def _loads_strict_json(text: str) -> Any:
    return json.loads(
        text,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON value {value}")),
    )


def _default_schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas" / "comfyui-civitai-save-node-sidecar.schema.json"


def _sanitize_exception(exc: BaseException) -> str:
    return _sanitize_line(str(exc.__class__.__name__) + ": " + str(exc))


def _sanitize_line(value: str) -> str:
    text = value.replace("\\", "/")
    for marker in ("token=", "api_key=", "apikey=", "authorization="):
        lower = text.lower()
        index = lower.find(marker)
        if index >= 0:
            end = text.find(" ", index)
            if end < 0:
                end = len(text)
            text = text[: index + len(marker)] + "<redacted_secret>" + text[end:]
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a comfyui-civitai-save-node JSON sidecar")
    parser.add_argument("sidecar", type=Path, help="Sidecar JSON file to validate")
    args = parser.parse_args()
    report = validate_sidecar_file(args.sidecar)
    print(report.to_text())
    raise SystemExit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
