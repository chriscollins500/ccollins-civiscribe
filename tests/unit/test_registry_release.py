from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, cast

import yaml
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_NODE_ACTION = "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020"
SETUP_PYTHON_ACTION = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
ICON_URL = (
    "https://raw.githubusercontent.com/chriscollins500/ccollins-civiscribe/"
    "main/assets/branding/civiscribe-icon.png"
)
BANNER_URL = (
    "https://raw.githubusercontent.com/chriscollins500/ccollins-civiscribe/"
    "main/assets/branding/civiscribe-banner.png"
)
REGISTRY_DESCRIPTION = (
    "Make every ComfyUI image Civitai-ready. CiviScribe saves PNG, JPEG, and WebP with "
    "your prompts, generation settings, model, LoRAs, hashes, and only the resources "
    "actually used. PNG files can also carry a reloadable workflow, so your uploads keep "
    "their creation details without manual metadata work."
)


def test_registry_metadata_uses_permanent_release_identity() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "ccollins-civiscribe"
    assert metadata["project"]["dynamic"] == ["version"]
    assert metadata["project"]["description"] == REGISTRY_DESCRIPTION
    assert metadata["project"]["urls"] == {
        "Repository": "https://github.com/chriscollins500/ccollins-civiscribe",
        "Documentation": "https://github.com/chriscollins500/ccollins-civiscribe#readme",
        "Bug Tracker": "https://github.com/chriscollins500/ccollins-civiscribe/issues",
    }
    assert metadata["tool"]["comfy"] == {
        "PublisherId": "chrisecollins500",
        "DisplayName": "CCollins' CiviScribe",
        "Icon": ICON_URL,
        "Banner": BANNER_URL,
        "requires-comfyui": ">=0.33.1",
        "version": {"path": "civiscribe/version.py"},
    }


def test_registry_branding_assets_match_comfy_dimensions() -> None:
    expected = {
        "civiscribe-icon.png": (400, 400),
        "civiscribe-banner.png": (1680, 720),
    }

    for filename, dimensions in expected.items():
        asset = PROJECT_ROOT / "assets" / "branding" / filename
        with Image.open(asset) as image:
            assert image.format == "PNG"
            assert image.mode == "RGB"
            assert image.size == dimensions


def test_release_version_is_final_and_frontend_matches() -> None:
    version_source = (PROJECT_ROOT / "civiscribe" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', version_source, re.MULTILINE)
    assert match is not None
    assert re.fullmatch(r"\d+\.\d+\.\d+", match.group(1))

    package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((PROJECT_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    assert package["version"] == match.group(1)
    assert lock["version"] == package["version"]
    assert lock["packages"][""]["version"] == package["version"]
    assert ".dev" not in match.group(1)


def test_registry_publish_is_manual_validated_and_commit_pinned() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "\n  push:" not in workflow
    assert "\n  pull_request:" not in workflow
    assert "needs: validate" in workflow
    assert "Comfy-Org/publish-node-action" not in workflow
    assert '"comfy-cli==1.16.0" "httpx==0.28.1"' in workflow
    assert "python -m tools.prepare_registry_changelog" in workflow
    assert '"$RUNNER_TEMP/civiscribe-registry-changelog.md"' in workflow
    assert "${{ runner.temp }}" not in workflow
    assert '--changelog "$RUNNER_TEMP/civiscribe-registry-changelog.md"' in workflow
    assert "python -m tools.publish_registry_bundle" in workflow
    assert "comfy node publish" not in workflow
    assert "python -m tools.verify_registry_listing" in workflow
    assert "--sync-description" in workflow
    assert "secrets.REGISTRY_ACCESS_TOKEN" in workflow
    assert "pat-" not in workflow


def test_github_workflows_use_current_node24_action_runtimes() -> None:
    for name in ("validation.yml", "publish.yml"):
        workflow = (PROJECT_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert CHECKOUT_ACTION in workflow
        assert SETUP_PYTHON_ACTION in workflow
        assert "@v4" not in workflow
        assert "@v5" not in workflow

    validation = (PROJECT_ROOT / ".github" / "workflows" / "validation.yml").read_text(
        encoding="utf-8"
    )
    publish = (PROJECT_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert SETUP_NODE_ACTION in validation
    candidate = (PROJECT_ROOT / ".github/workflows/release-validation.yml").read_text()
    assert SETUP_NODE_ACTION in candidate
    assert 'node-version: "24.19.0"' in validation
    assert 'node-version: "24.19.0"' in candidate
    assert "uses: ./.github/workflows/release-validation.yml" in publish


def _workflow(name: str) -> dict[str, Any]:
    source = (PROJECT_ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
    # BaseLoader constructs strings only and preserves GitHub's YAML 1.2 `on` key.
    return cast(dict[str, Any], yaml.load(source, Loader=yaml.BaseLoader))  # noqa: S506


def test_publish_gates_are_dependencies_not_merely_unconnected_steps() -> None:
    workflow = _workflow("publish.yml")
    assert set(workflow["on"]) == {"workflow_dispatch"}
    jobs = workflow["jobs"]
    for job in jobs.values():
        assert job["if"] == "github.ref == 'refs/heads/main'"
    assert jobs["github-release"]["needs"] == "validate"
    assert jobs["publish"]["needs"] == "github-release"
    for job_id in ("github-release", "publish"):
        assert jobs[job_id]["environment"] == "release"
        commands = "\n".join(step.get("run", "") for step in jobs[job_id]["steps"])
        assert "release_bundle verify" in commands
        assert "uv build" not in commands and "nox -s" not in commands
    assert jobs["publish"]["permissions"] == {"contents": "read"}


def test_candidate_requires_exact_artifact_matrix_conformance_and_live_uat() -> None:
    jobs = _workflow("release-validation.yml")["jobs"]
    assert jobs["installed-package"]["needs"] == "build"
    assert jobs["live-v3"]["needs"] == "build"
    assert set(jobs["installed-package"]["strategy"]["matrix"]["os"]) == {
        "ubuntu-24.04",
        "windows-2025",
        "macos-15",
    }
    commands = "\n".join(step.get("run", "") for job in jobs.values() for step in job["steps"])
    assert "nox -s release" in commands
    assert "release_bundle prepare" in commands
    assert "release_corpus.py --require-installed" in commands
    assert "--require-tools" in commands
    assert "tools.test_comfy_artifact" in commands
    assert all("continue-on-error" not in job for job in jobs.values())


def test_comfyignore_keeps_registry_runtime_payload() -> None:
    ignored_patterns = {
        line.strip()
        for line in (PROJECT_ROOT / ".comfyignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert ignored_patterns.isdisjoint(
        {
            "__init__.py",
            "civiscribe/",
            "locales/",
            "web/runtime/",
            "LICENSE",
            "README.md",
        }
    )
    assert "/build/" in ignored_patterns
    assert "/dist/" in ignored_patterns
    assert "build/" not in ignored_patterns
    assert "dist/" not in ignored_patterns
    assert "web/src/" in ignored_patterns
    assert "web/dist/" in ignored_patterns


def test_registry_payload_avoids_known_scanner_false_positive_patterns() -> None:
    runtime_root = PROJECT_ROOT / "web" / "runtime"
    assert runtime_root.is_dir()
    assert not (PROJECT_ROOT / "web" / "dist").exists()

    python_sources = sorted((PROJECT_ROOT / "civiscribe").rglob("*.py"))
    runtime_scripts = sorted(runtime_root.rglob("*.js"))
    assert python_sources
    assert runtime_scripts
    assert all(
        "importlib.import_module(" not in path.read_text(encoding="utf-8")
        for path in python_sources
    )
    assert all(".bind(" not in path.read_text(encoding="utf-8") for path in runtime_scripts)
