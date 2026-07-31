"""Provider-independent development sessions for CiviScribe V2."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from shutil import which

import nox

from civiscribe.version import __version__

nox.options.sessions = ["python", "frontend"]
PROJECT_ROOT = Path(__file__).resolve().parent
PRIVATE_RELEASE_ARCHIVE = f"dist/ccollins-civiscribe-{__version__}-private-test.zip"
TOOL_CACHE_ROOT = Path(tempfile.gettempdir()) / "ccollins-civiscribe"


def _uv_executable() -> str:
    discovered = which("uv")
    if discovered is not None:
        return discovered
    relative = Path("Scripts/uv.exe") if sys.platform == "win32" else Path("bin/uv")
    local = PROJECT_ROOT / ".venv" / relative
    return str(local) if local.is_file() else "uv"


def _uv(*arguments: str) -> tuple[str, ...]:
    if sys.platform == "win32":
        return (_uv_executable(), "--system-certs", *arguments)
    return (_uv_executable(), *arguments)


def _run_uv(session: nox.Session, *arguments: str) -> None:
    session.run(
        *_uv(*arguments),
        external=True,
        env={"UV_CACHE_DIR": str(TOOL_CACHE_ROOT / "uv-cache")},
    )


def _run_python_module(
    session: nox.Session,
    module: str,
    *arguments: str,
) -> None:
    """Run a Python tool without relying on relocatable console launchers."""

    _run_uv(session, "run", "--locked", "python", "-m", module, *arguments)


@nox.session(python=False)
def python(session: nox.Session) -> None:
    """Run the locked Python quality profile."""

    _run_python_module(session, "ruff", "format", "--check", ".")
    _run_python_module(session, "ruff", "check", ".")
    _run_python_module(
        session,
        "mypy",
        "civiscribe",
        "tools",
        "tests",
        "noxfile.py",
    )
    _run_uv(
        session,
        "run",
        "--locked",
        "python",
        "tools/validate_locales.py",
        "locales",
    )
    _run_uv(
        session,
        "run",
        "--locked",
        "python",
        "tools/validate_golden_manifest.py",
        "tests/golden/manifest.json",
    )
    _run_uv(
        session,
        "run",
        "--locked",
        "python",
        "tools/validate_sidecar.py",
        "tests/golden/sidecar/complete_v2.json",
    )
    _run_python_module(
        session,
        "pytest",
        "--cov=civiscribe",
        "--cov-report=term-missing",
    )


@nox.session(python=False)
def frontend(session: nox.Session) -> None:
    """Run the locked frontend quality profile."""

    environment = {
        "npm_config_cache": str(TOOL_CACHE_ROOT / "npm-cache"),
    }
    if sys.platform == "win32":
        environment["NODE_USE_SYSTEM_CA"] = "1"
    session.run("npm", "ci", external=True, env=environment)
    session.run("npm", "run", "check", external=True, env=environment)


@nox.session(python=False)
def e2e(session: nox.Session) -> None:
    """Run browser UAT against an already-running isolated ComfyUI."""

    environment = {
        "npm_config_cache": str(TOOL_CACHE_ROOT / "npm-cache"),
    }
    if sys.platform == "win32":
        environment["NODE_USE_SYSTEM_CA"] = "1"
    for name in ("CIVISCRIBE_E2E_BASE_URL", "CIVISCRIBE_E2E_CHANNEL"):
        if value := os.environ.get(name):
            environment[name] = value
    session.run("npm", "ci", external=True, env=environment)
    session.run("npm", "run", "test:e2e", external=True, env=environment)


@nox.session(python=False)
def conformance(session: nox.Session) -> None:
    """Run independent media readers with caller-supplied artifact/tool arguments."""

    if not session.posargs:
        session.error("pass audit_image_conformance.py arguments after --")
    _run_uv(
        session,
        "run",
        "--locked",
        "python",
        "tools/audit_image_conformance.py",
        *session.posargs,
    )


@nox.session(python=False)
def build(session: nox.Session) -> None:
    """Build and inspect the Python distribution artifacts."""

    _run_uv(session, "build")
    _run_python_module(session, "check_wheel_contents", "dist")
    _run_uv(
        session,
        "run",
        "--locked",
        "python",
        "tools/build_release.py",
        "build",
        PRIVATE_RELEASE_ARCHIVE,
    )
    _run_uv(
        session,
        "run",
        "--locked",
        "python",
        "tools/build_release.py",
        "audit",
        PRIVATE_RELEASE_ARCHIVE,
    )
