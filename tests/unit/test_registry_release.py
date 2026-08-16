from __future__ import annotations

import re
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_ACTION = "Comfy-Org/publish-node-action@d2366e7abb6ab16f3bb03e3520ae25c8cf749bc9"


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
    assert match.group(1) == "2.0.0"

    package = (PROJECT_ROOT / "package.json").read_text(encoding="utf-8")
    assert '"version": "2.0.0"' in package
    assert ".dev" not in match.group(1)


def test_registry_publish_is_manual_validated_and_commit_pinned() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "\n  push:" not in workflow
    assert "\n  pull_request:" not in workflow
    assert "needs: validate" in workflow
    assert PUBLISH_ACTION in workflow
    assert "secrets.REGISTRY_ACCESS_TOKEN" in workflow
    assert 'skip_checkout: "true"' in workflow
    assert "pat-" not in workflow


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
            "web/dist/",
            "LICENSE",
            "README.md",
        }
    )
    assert "/build/" in ignored_patterns
    assert "/dist/" in ignored_patterns
    assert "build/" not in ignored_patterns
    assert "dist/" not in ignored_patterns
    assert "web/src/" in ignored_patterns
