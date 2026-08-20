"""Prepare version-specific update notes for the Comfy Registry."""

from __future__ import annotations

import argparse
import ast
import re
from collections.abc import Sequence
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"
DEFAULT_VERSION_FILE = PROJECT_ROOT / "civiscribe" / "version.py"


class ReleaseNotesError(ValueError):
    """Raised when release notes cannot be selected unambiguously."""


def read_project_version(version_file: Path) -> str:
    """Read the literal ``__version__`` assignment without executing code."""

    source = version_file.read_text(encoding="utf-8")
    module = ast.parse(source, filename=version_file.name)
    values: list[str] = []
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            continue
        value = ast.literal_eval(statement.value)
        if isinstance(value, str) and value:
            values.append(value)

    if len(values) != 1:
        raise ReleaseNotesError("version file must define one non-empty literal __version__")
    return values[0]


def extract_release_notes(changelog: str, version: str) -> str:
    """Return one version's dated Markdown section, excluding its heading."""

    if not version or "\n" in version or "\r" in version:
        raise ReleaseNotesError("release version is invalid")

    heading = re.compile(
        rf"^##[ \t]+{re.escape(version)}[ \t]+-[ \t]+\d{{4}}-\d{{2}}-\d{{2}}[ \t]*$",
        re.MULTILINE,
    )
    matches = list(heading.finditer(changelog))
    if len(matches) != 1:
        raise ReleaseNotesError(
            f"CHANGELOG.md must contain exactly one dated section for version {version}"
        )

    section_start = matches[0].end()
    next_heading = re.search(r"^##[ \t]+", changelog[section_start:], re.MULTILINE)
    section_end = (
        section_start + next_heading.start() if next_heading is not None else len(changelog)
    )
    notes = changelog[section_start:section_end].strip()
    if not notes:
        raise ReleaseNotesError(f"CHANGELOG.md section for version {version} is empty")
    if "\x00" in notes:
        raise ReleaseNotesError("release notes contain a NUL character")
    return notes


def prepare_registry_changelog(
    *,
    changelog_path: Path,
    version_file: Path,
    output_path: Path,
    version: str | None = None,
) -> str:
    """Extract and write Registry update notes, returning the selected version."""

    selected_version = version or read_project_version(version_file)
    changelog = changelog_path.read_text(encoding="utf-8")
    notes = extract_release_notes(changelog, selected_version)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{notes}\n", encoding="utf-8", newline="\n")
    return selected_version


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract the current version's CHANGELOG.md section for the Comfy Registry."
    )
    parser.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    parser.add_argument("--version-file", type=Path, default=DEFAULT_VERSION_FILE)
    parser.add_argument("--version", help="Override the version read from civiscribe/version.py")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the release-note extraction command."""

    arguments = _parser().parse_args(argv)
    version = prepare_registry_changelog(
        changelog_path=cast(Path, arguments.changelog),
        version_file=cast(Path, arguments.version_file),
        output_path=cast(Path, arguments.output),
        version=cast(str | None, arguments.version),
    )
    print(f"Prepared Comfy Registry update notes for {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
