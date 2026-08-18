from __future__ import annotations

import re
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_NODE_ACTION = "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020"
SETUP_PYTHON_ACTION = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"


def test_registry_metadata_uses_permanent_release_identity() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "ccollins-civiscribe"
    assert metadata["project"]["dynamic"] == ["version"]
    assert metadata["project"]["urls"] == {
        "Repository": "https://github.com/chriscollins500/ccollins-civiscribe",
        "Documentation": "https://github.com/chriscollins500/ccollins-civiscribe#readme",
        "Bug Tracker": "https://github.com/chriscollins500/ccollins-civiscribe/issues",
    }
    assert metadata["tool"]["comfy"] == {
        "PublisherId": "chrisecollins500",
        "DisplayName": "CCollins' CiviScribe",
        "requires-comfyui": ">=0.33.1",
        "version": {"path": "civiscribe/version.py"},
    }


def test_release_version_is_final_and_frontend_matches() -> None:
    version_source = (PROJECT_ROOT / "civiscribe" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', version_source, re.MULTILINE)
    assert match is not None
    assert match.group(1) == "2.0.3"

    package = (PROJECT_ROOT / "package.json").read_text(encoding="utf-8")
    assert '"version": "2.0.3"' in package
    assert ".dev" not in match.group(1)


def test_registry_publish_is_manual_validated_and_commit_pinned() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "\n  push:" not in workflow
    assert "\n  pull_request:" not in workflow
    assert "needs: validate" in workflow
    assert "Comfy-Org/publish-node-action" not in workflow
    assert 'python -m pip install "comfy-cli==1.16.0"' in workflow
    assert 'comfy node publish --token "$REGISTRY_ACCESS_TOKEN"' in workflow
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
    assert SETUP_NODE_ACTION in publish
    assert 'node-version: "24.19.0"' in validation
    assert 'node-version: "24.19.0"' in publish


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
