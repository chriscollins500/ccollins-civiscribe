"""Regressions for public navigation, shared versions, and action provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools import validate_public_project as validator
from tools.build_site import GUIDES, ROOT


def test_current_public_project_is_consistent() -> None:
    assert validator.validate_public_project() == ()


@pytest.mark.parametrize("locked", ["", 'version = "2.0.12"\n'])
def test_dynamic_editable_lock_and_explicit_matching_version_are_supported(
    tmp_path: Path, locked: str
) -> None:
    (tmp_path / "civiscribe").mkdir()
    (tmp_path / "civiscribe/version.py").write_text('__version__ = "2.0.12"\n', encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"version": "2.0.12"}), encoding="utf-8")
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "ccollins-civiscribe"\n' + locked, encoding="utf-8"
    )
    assert validator.version_issues(tmp_path) == ()
    (tmp_path / "package.json").write_text('{"version":"0.0.0"}', encoding="utf-8")
    assert validator.version_issues(tmp_path) == (
        "package.json: package version differs from civiscribe/version.py",
    )


def test_missing_hub_backlink_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = validator._read

    def read(root: Path, name: str) -> str:
        text = original(root, name)
        return text.replace("guides/project-hub/", "missing/") if name == "README.md" else text

    monkeypatch.setattr(validator, "_read", read)
    assert "README.md: missing public project navigation" in validator.validate_public_project()


def test_missing_website_guide_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    guides = dict(GUIDES)
    guides.pop("Project-hub")
    monkeypatch.setattr(validator, "GUIDES", guides)
    assert "wiki and website guide inventories differ" in validator.validate_public_project()


def test_documentation_wheel_hash_drift_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = validator._read

    def read(root: Path, name: str) -> str:
        text = original(root, name)
        return text.replace("sha256:", "sha256:0") if name.endswith("requirements.txt") else text

    monkeypatch.setattr(validator, "_read", read)
    assert validator.documentation_pin_issues(ROOT)


def test_moving_action_refs_are_rejected_and_local_workflows_remain_valid() -> None:
    assert validator.workflow_pin_issues("- uses: actions/checkout@v6\n")
    assert not validator.workflow_pin_issues(
        "- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
        "  uses: ./.github/workflows/release-validation.yml\n"
    )


def test_issue_and_discussion_forms_have_valid_unique_fields() -> None:
    paths = list((ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"))
    paths.extend((ROOT / ".github/DISCUSSION_TEMPLATE").glob("*.yml"))
    for path in paths:
        form = yaml.safe_load(path.read_text("utf-8"))
        if path.name == "config.yml":
            assert form["blank_issues_enabled"] is True
            continue
        assert form["body"], path.name
        fields = [field for field in form["body"] if field["type"] != "markdown"]
        ids = [field["id"] for field in fields]
        assert len(ids) == len(set(ids)), path.name
        assert all(field["attributes"]["label"] for field in fields), path.name


def test_workflows_parse_and_wiki_publication_stays_after_checks_on_main() -> None:
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text("utf-8"))
        # PyYAML's YAML 1.1 resolver reads GitHub's unquoted "on" key as True.
        assert workflow.get("on", workflow.get(True)), path.name
        assert workflow["jobs"], path.name
    website = yaml.safe_load((ROOT / ".github/workflows/pages.yml").read_text("utf-8"))
    wiki = website["jobs"]["wiki"]
    assert wiki["permissions"] == {"contents": "write"}
    assert wiki["needs"] == "build"
    assert "github.event_name != 'pull_request'" in wiki["if"]
    assert "github.ref == 'refs/heads/main'" in wiki["if"]
    assert "wiki" in website["jobs"]["deploy"]["needs"]
