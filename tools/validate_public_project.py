"""Check cross-surface navigation, version identity, guide coverage, and workflow pins."""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

from tools.audit_paths import scoped_path
from tools.build_site import BASE, GUIDES, ORIGIN, PROJECT_PAGES, ROOT

WEBSITE = ORIGIN + BASE + "/"
REPOSITORY = "https://github.com/chriscollins500/ccollins-civiscribe"
REQUIRED_LINKS = {
    "README.md": (WEBSITE, WEBSITE + "guides/project-hub/"),
    "SUPPORT.md": (WEBSITE + "guides/project-hub/", REPOSITORY + "/discussions"),
    "ROADMAP.md": (
        WEBSITE + "guides/project-hub/",
        "https://github.com/users/chriscollins500/projects/2",
    ),
    "docs/wiki/Home.md": (WEBSITE, REPOSITORY + "/wiki/Project-hub"),
    "docs/wiki/_Sidebar.md": (WEBSITE, REPOSITORY + "/wiki/Project-hub"),
    "docs/wiki/_Footer.md": (WEBSITE, REPOSITORY + "/releases/latest"),
    ".github/ISSUE_TEMPLATE/config.yml": (
        WEBSITE + "guides/project-hub/",
        REPOSITORY + "/security/advisories/new",
    ),
    "docs/site/layout.html": (
        "{{BASE}}/guides/project-hub/",
        "{{BASE}}/support/",
        "{{BASE}}/roadmap/",
        "{{BASE}}/security/",
        "{{BASE}}/contributing/",
    ),
}


def _read(root: Path, name: str) -> str:
    return scoped_path(root, root / name).read_text(encoding="utf-8")


def version_issues(root: Path) -> tuple[str, ...]:
    """Compare only package versions; API and schema versions have their own contracts."""
    tree = ast.parse(_read(root, "civiscribe/version.py"))
    version = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    )
    package = json.loads(_read(root, "package.json"))
    lock = tomllib.loads(_read(root, "uv.lock"))
    locked = next(item for item in lock["package"] if item["name"] == "ccollins-civiscribe")
    return tuple(
        f"{name}: package version differs from civiscribe/version.py"
        # uv omits the version of this editable, dynamically versioned project.
        for name, actual in (
            ("package.json", package["version"]),
            ("uv.lock", locked.get("version", version)),
        )
        if actual != version
    )


def workflow_pin_issues(text: str) -> tuple[str, ...]:
    return tuple(
        "workflow action must use a complete commit SHA"
        for value in re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)", text, re.MULTILINE)
        if not value.startswith("./") and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", value)
    )


def documentation_pin_issues(root: Path) -> tuple[str, ...]:
    packages = {item["name"]: item for item in tomllib.loads(_read(root, "uv.lock"))["package"]}
    issues = []
    names = set()
    for line in _read(root, "docs/site/requirements.txt").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-z-]+)==([0-9.]+) --hash=(sha256:[0-9a-f]{64})", line)
        if match is None:
            issues.append("documentation requirements must pin a version and wheel hash")
            continue
        name, version, digest = match.groups()
        names.add(name)
        package = packages.get(name, {})
        if package.get("version") != version or digest not in {
            wheel["hash"] for wheel in package.get("wheels", [])
        }:
            issues.append("documentation requirement differs from the locked wheel")
    if names != {"markdown-it-py", "mdurl"}:
        issues.append("documentation dependency inventory differs from the reviewed renderer")
    return tuple(issues)


def validate_public_project(root: Path = ROOT) -> tuple[str, ...]:
    root = root.resolve()
    issues = list(version_issues(root))
    issues.extend(documentation_pin_issues(root))
    declared = re.search(
        r"This guide covers CiviScribe \*\*([^*]+)\*\*", _read(root, "docs/wiki/Home.md")
    )
    package = json.loads(_read(root, "package.json"))
    if declared is None or declared.group(1) != package["version"]:
        issues.append("wiki Home: current guide version differs from the package")
    project = tomllib.loads(_read(root, "pyproject.toml"))["project"]["urls"]
    for key, expected in {
        "Homepage": WEBSITE,
        "Documentation": WEBSITE + "guides/",
        "Wiki": REPOSITORY + "/wiki",
        "Roadmap": WEBSITE + "roadmap/",
    }.items():
        if project.get(key) != expected:
            issues.append(f"pyproject.toml: incorrect {key} destination")
    for name, destinations in REQUIRED_LINKS.items():
        text = _read(root, name)
        if any(destination not in text for destination in destinations):
            issues.append(f"{name}: missing public project navigation")
    sources = {
        path.stem
        for path in (root / "docs/wiki").glob("*.md")
        if not path.name.startswith("_") and path.stem != "Home"
    }
    if sources != set(GUIDES):
        issues.append("wiki and website guide inventories differ")
    issues.extend(
        f"{name}: missing shared project page"
        for name in PROJECT_PAGES
        if not scoped_path(root, root / name).is_file()
    )
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        issues.extend(
            f"{path.name}: {issue}"
            for issue in workflow_pin_issues(_read(root, path.relative_to(root).as_posix()))
        )
    return tuple(issues)


def main() -> None:
    issues = validate_public_project()
    for issue in issues:
        print(issue)
    if issues:
        raise SystemExit(1)
    print("Public project navigation, package versions, guide inventories, and action pins: passed")


if __name__ == "__main__":
    main()
