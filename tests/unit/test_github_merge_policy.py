"""Check that the proposed GitHub rules refer to unconditional, read-only PR jobs."""

from __future__ import annotations

import json

import pytest
import yaml

from tools.build_site import ROOT

WORKFLOWS = ROOT / ".github/workflows"
PROPOSED_RULESET = ROOT / ".github/rulesets/main-merge-checks.json"
GITHUB_ACTIONS_APP = 15368
REQUIRED_JOBS = {
    "validation.yml": "validate",
    "dependency-review.yml": "review",
    "pages.yml": "build",
}


def _delivery_issues(source: str, job_id: str) -> tuple[str, ...]:
    workflow = yaml.safe_load(source)
    # YAML 1.1 reads GitHub's unquoted `on` key as boolean true.
    events = workflow.get("on", workflow.get(True, {}))
    job = workflow["jobs"][job_id]
    issues: list[str] = []
    if "pull_request" not in events or events["pull_request"] not in (None, {}):
        issues.append("Required workflow must run on every pull request without filters.")
    if "if" in job or "needs" in job:
        issues.append("Required job must run without a condition or upstream job.")
    if "pull_request_target" in events or job.get("permissions", workflow.get("permissions")) != {
        "contents": "read"
    }:
        issues.append("Required PR job must use the pull_request trust boundary and read access.")
    return tuple(issues)


def test_merge_ruleset_names_the_checks_available_on_every_pull_request() -> None:
    proposal = json.loads(PROPOSED_RULESET.read_text(encoding="utf-8"))
    assert proposal["enforcement"] == "disabled"
    assert proposal["target"] == "branch"
    assert proposal["conditions"] == {"ref_name": {"include": ["refs/heads/main"], "exclude": []}}
    assert proposal["bypass_actors"] == []
    rules = {rule["type"]: rule["parameters"] for rule in proposal["rules"]}
    assert rules["pull_request"]["required_review_thread_resolution"] is True
    assert rules["required_status_checks"]["strict_required_status_checks_policy"] is True
    assert rules["code_scanning"]["code_scanning_tools"] == [
        {
            "tool": "CodeQL",
            "alerts_threshold": "errors",
            "security_alerts_threshold": "medium_or_higher",
        }
    ]

    for filename, job_id in REQUIRED_JOBS.items():
        source = (WORKFLOWS / filename).read_text(encoding="utf-8")
        assert _delivery_issues(source, job_id) == (), filename

    names: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in workflow["jobs"].items():
            names.setdefault(job.get("name", job_id), []).append((path.name, job_id))
    contexts = rules["required_status_checks"]["required_status_checks"]
    assert len(contexts) == len(REQUIRED_JOBS)
    bindings = []
    for check in contexts:
        assert check["integration_id"] == GITHUB_ACTIONS_APP
        matches = names.get(check["context"], [])
        assert len(matches) == 1, f"{check['context']} must resolve to one job name."
        bindings.extend(matches)
    assert sorted(bindings) == sorted(REQUIRED_JOBS.items())


@pytest.mark.parametrize(
    ("old", "new", "problem"),
    [
        (
            "  pull_request:\n",
            "  pull_request:\n    paths: ['docs/**']\n",
            "Required workflow must run on every pull request without filters.",
        ),
        (
            "  build:\n",
            "  build:\n    if: github.actor != 'dependabot[bot]'\n",
            "Required job must run without a condition or upstream job.",
        ),
    ],
)
def test_merge_policy_catches_a_skipped_required_check(old: str, new: str, problem: str) -> None:
    source = (WORKFLOWS / "pages.yml").read_text(encoding="utf-8")
    assert old in source
    assert _delivery_issues(source.replace(old, new, 1), "build") == (problem,)


def test_pr_checks_use_standard_runners_without_package_caches_or_uploads() -> None:
    for filename, job_id in REQUIRED_JOBS.items():
        workflow = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8"))
        job = workflow["jobs"][job_id]
        assert job["runs-on"] == "ubuntu-24.04", filename
        for step in job["steps"]:
            action = step.get("uses", "").split("@", maxsplit=1)[0]
            if action == "actions/setup-node":
                assert "cache" not in step["with"], filename
                assert step["with"]["package-manager-cache"] is False, filename
            if action in {"actions/upload-artifact", "actions/upload-pages-artifact"}:
                assert step.get("if") == "github.event_name != 'pull_request'", filename
