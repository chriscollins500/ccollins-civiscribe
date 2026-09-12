"""Start an isolated CPU-only ComfyUI for exact-ZIP Playwright and Axe validation."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from tools.release_bundle import ROOT, stage_node


def run(  # noqa: PLR0913 - explicit isolated runtime and artifact coordinates
    comfy: Path,
    python: Path,
    directory: Path,
    commit: str,
    channel: str,
    *,
    working_tree: bool = False,
) -> None:
    main_file = comfy.resolve() / "main.py"
    if not main_file.is_file() or (comfy / "extra_model_paths.yaml").exists():
        raise ValueError("use a clean ComfyUI checkout without personal model-path configuration")
    node = shutil.which("node")
    if node is None:
        raise ValueError("Node.js is required for Playwright")
    with tempfile.TemporaryDirectory(prefix="civiscribe-e2e-") as temporary:
        base = Path(temporary)
        stage_node(
            directory,
            commit,
            base / "custom_nodes" / "ccollins-civiscribe",
            allow_working_tree=working_tree,
        )
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        command = [
            str(python.resolve()),
            str(main_file),
            "--cpu",
            "--listen",
            "127.0.0.1",
            "--port",
            str(port),
            "--base-directory",
            str(base),
            "--disable-auto-launch",
            "--disable-all-custom-nodes",
            "--whitelist-custom-nodes",
            "ccollins-civiscribe",
        ]
        with (base / "server.log").open("wb") as log:
            process = subprocess.Popen(command, cwd=base, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603
            try:
                url = f"http://127.0.0.1:{port}"
                _wait_for_server(process, url)
                environment = {
                    **os.environ,
                    "CIVISCRIBE_E2E_BASE_URL": url,
                    "CIVISCRIBE_E2E_CHANNEL": channel,
                }
                subprocess.run(  # noqa: S603
                    [node, str(ROOT / "node_modules/@playwright/test/cli.js"), "test"],
                    cwd=ROOT,
                    env=environment,
                    check=True,
                    timeout=600,
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                report = ROOT / ".tmp" / "release-reports"
                report.mkdir(parents=True, exist_ok=True)
                # This log contains only the isolated synthetic runtime, never user workflows.
                shutil.copyfile(base / "server.log", report / "comfy-e2e.log")


def _wait_for_server(process: subprocess.Popen[bytes], url: str) -> None:
    deadline = time.monotonic() + 120
    with httpx.Client(timeout=2, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "isolated ComfyUI exited before registration; inspect comfy-e2e.log"
                )
            try:
                response = client.get(f"{url}/object_info/CCollins_CiviScribe_SaveImage")
                if response.is_success and response.json().get("CCollins_CiviScribe_SaveImage"):
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.25)
    raise TimeoutError("isolated ComfyUI did not register the installed CiviScribe artifact")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--directory", type=Path, default=ROOT / "dist")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--channel", default="chromium")
    parser.add_argument("--working-tree", action="store_true")
    args = parser.parse_args()
    run(
        args.comfy,
        args.python,
        args.directory,
        args.commit,
        args.channel,
        working_tree=args.working_tree,
    )


if __name__ == "__main__":
    main()
