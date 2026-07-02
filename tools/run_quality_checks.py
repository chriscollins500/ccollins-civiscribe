"""Run local production-readiness checks without network access or mutation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from io import BytesIO
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "fail"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local quality checks for comfyui-civitai-save-node")
    parser.add_argument(
        "--comfy-python",
        type=Path,
        default=None,
        help="Optional ComfyUI Python executable for a second test-suite pass.",
    )
    parser.add_argument(
        "--skip-comfy",
        action="store_true",
        help="Skip the optional ComfyUI Python test-suite pass.",
    )
    args = parser.parse_args()

    checks: list[CheckResult] = []
    checks.append(_run_command("compileall", [sys.executable, "-m", "compileall", "-q", "save_node", "tools"]))
    checks.append(_run_command("unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]))
    checks.append(_run_node_check())
    checks.append(_run_ruff_check())
    checks.append(_run_ruff_format_check())
    checks.append(_run_python_check("sidecar sample validation", _sidecar_sample_validation))
    checks.append(_run_python_check("PNG chunk sample inspection", _png_chunk_sample_inspection))
    checks.append(_run_python_check("import smoke", _import_smoke))
    if not args.skip_comfy and args.comfy_python:
        checks.append(
            _run_command(
                "ComfyUI venv unit tests",
                [str(args.comfy_python), "-m", "unittest", "discover", "-s", "tests"],
            )
        )

    for result in checks:
        suffix = f" - {result.detail}" if result.detail else ""
        print(f"[{result.status}] {result.name}{suffix}")

    return 1 if any(result.failed for result in checks) else 0


def _run_command(name: str, command: list[str]) -> CheckResult:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return CheckResult(name=name, status="skip", detail=f"{Path(command[0]).name} unavailable")
    detail = _last_interesting_line(completed.stdout + "\n" + completed.stderr)
    return CheckResult(name=name, status="pass" if completed.returncode == 0 else "fail", detail=detail)


def _run_node_check() -> CheckResult:
    node = shutil.which("node")
    if not node:
        return CheckResult(name="JS syntax check", status="skip", detail="node unavailable")
    return _run_command("JS syntax check", [node, "--check", "js/civitai_save_node_ui.js"])


def _run_ruff_check() -> CheckResult:
    if not _module_available("ruff"):
        return CheckResult(name="ruff check", status="skip", detail="ruff unavailable")
    return _run_command("ruff check", [sys.executable, "-m", "ruff", "check", "."])


def _run_ruff_format_check() -> CheckResult:
    if not _module_available("ruff"):
        return CheckResult(name="ruff format --check", status="skip", detail="ruff unavailable")
    return _run_command("ruff format --check", [sys.executable, "-m", "ruff", "format", "--check", "."])


def _run_python_check(name: str, fn: Callable[[], str]) -> CheckResult:
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001 - quality runner should report all check failures.
        return CheckResult(name=name, status="fail", detail=_safe_detail(f"{exc.__class__.__name__}: {exc}"))
    return CheckResult(name=name, status="pass", detail=detail)


def _sidecar_sample_validation() -> str:
    from save_node.io.sidecar import build_sidecar_payload, write_sidecar_json_file
    from save_node.metadata.schema import MetadataOptions, ValidationResult
    from tools.validate_sidecar import validate_sidecar_file

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output"
        output.mkdir()
        image = output / "sample.png"
        image.write_bytes(b"png")
        payload = build_sidecar_payload(
            image={"filename": "sample.png", "format": "PNG", "width": 1, "height": 1, "mode": "RGB"},
            options=MetadataOptions(
                strict_mode=False,
                include_workflow=True,
                include_civitai_manifest=True,
                write_sidecar_json=True,
            ),
            prompt={},
            extra_pnginfo={"workflow": {"nodes": []}},
            civitai_manifest=None,
            validation=ValidationResult(),
            a1111_parameters="prompt\nNegative prompt:\nSteps: 1, Size: 1x1",
        )
        sidecar = write_sidecar_json_file(image, payload, output)
        report = validate_sidecar_file(sidecar)
    if not report.ok:
        raise RuntimeError(report.to_text())
    return report.schema_validation


def _png_chunk_sample_inspection() -> str:
    try:
        from PIL import Image
    except ImportError:
        return "Pillow unavailable"
    from save_node.io.png_writer import build_pnginfo
    from save_node.metadata.exif_user_comment import build_exif_bytes
    from save_node.metadata.schema import GenerationSettings, PromptMetadata
    from tools.inspect_png_chunks import inspect_png

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.png"
        output = BytesIO()
        image = Image.new("RGB", (4, 4), color=(1, 2, 3))
        pnginfo = build_pnginfo(
            parameters="prompt\nNegative prompt:\nSteps: 1, Size: 4x4",
            prompt={"1": {"class_type": "KSampler", "inputs": {}}},
            extra_pnginfo={"workflow": {"nodes": []}},
            include_workflow=True,
            civitai_manifest={"schemaName": "test"},
        )
        exif = build_exif_bytes(
            prompt=PromptMetadata(positive="prompt"),
            generation=GenerationSettings(steps=1, width=4, height=4),
            resources=(),
        )
        image.save(output, format="PNG", pnginfo=pnginfo, exif=exif)
        path.write_bytes(output.getvalue())
        report = inspect_png(path)
    required = (
        "parameters: tEXt",
        "prompt: iTXt",
        "workflow: iTXt",
        "civitai: iTXt",
        "Software: tEXt",
        "eXIf: present",
    )
    missing = [item for item in required if item not in report]
    if missing:
        raise RuntimeError(f"missing PNG metadata summary items: {', '.join(missing)}")
    return "parameters tEXt; prompt/workflow/civitai iTXt; eXIf present"


def _import_smoke() -> str:
    import save_node
    from save_node.version import __version__

    if "SaveImageWithCivitaiMetadata" not in save_node.NODE_CLASS_MAPPINGS:
        raise RuntimeError("node class mapping missing")
    return f"version {__version__}"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _last_interesting_line(output: str) -> str:
    for line in reversed(output.splitlines()):
        cleaned = _safe_detail(line.strip())
        if cleaned:
            return cleaned
    return ""


def _safe_detail(value: str) -> str:
    text = value.replace(str(ROOT), "<repo>").replace("\\", "/")
    for marker in ("token=", "api_key=", "apikey=", "authorization="):
        lowered = text.lower()
        index = lowered.find(marker)
        if index >= 0:
            end = text.find(" ", index)
            if end < 0:
                end = len(text)
            text = text[: index + len(marker)] + "<redacted_secret>" + text[end:]
    return text[:240]


if __name__ == "__main__":
    raise SystemExit(main())
