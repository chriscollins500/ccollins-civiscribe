from __future__ import annotations

from pathlib import Path

import pytest

from tools.prepare_registry_changelog import (
    ReleaseNotesError,
    extract_release_notes,
    main,
    prepare_registry_changelog,
    read_project_version,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_current_release_notes_are_selected_from_project_sources(tmp_path: Path) -> None:
    version_file = PROJECT_ROOT / "civiscribe" / "version.py"
    output = tmp_path / "registry-notes.md"

    version = prepare_registry_changelog(
        changelog_path=PROJECT_ROOT / "CHANGELOG.md",
        version_file=version_file,
        output_path=output,
    )

    assert version == "2.0.5"
    assert read_project_version(version_file) == version
    assert output.read_text(encoding="utf-8").startswith(
        "- Added final-prompt guidance and diagnostics"
    )
    assert "## 2.0.4" not in output.read_text(encoding="utf-8")


def test_release_notes_preserve_nested_markdown_until_next_version() -> None:
    changelog = """# Changelog

## Unreleased

## 3.1.4 - 2026-08-18

- First item

### Details

More context.

## 3.1.3 - 2026-08-17

- Older item
"""

    assert extract_release_notes(changelog, "3.1.4") == (
        "- First item\n\n### Details\n\nMore context."
    )


@pytest.mark.parametrize(
    ("changelog", "message"),
    [
        ("## 1.0.0 - 2026-08-18\n", "section for version 1.0.0 is empty"),
        ("## 1.0.1 - 2026-08-18\n- Other\n", "exactly one dated section"),
        (
            "## 1.0.0 - 2026-08-18\n- One\n## 1.0.0 - 2026-08-19\n- Two\n",
            "exactly one dated section",
        ),
        ("## 1.0.0 - 2026-08-18\n- Bad\x00note\n", "NUL character"),
    ],
)
def test_release_notes_reject_missing_ambiguous_or_unsafe_sections(
    changelog: str,
    message: str,
) -> None:
    with pytest.raises(ReleaseNotesError, match=message):
        extract_release_notes(changelog, "1.0.0")


def test_version_reader_rejects_executable_or_ambiguous_values(tmp_path: Path) -> None:
    version_file = tmp_path / "version.py"
    version_file.write_text("__version__ = build_version()\n", encoding="utf-8")

    with pytest.raises(ValueError):
        read_project_version(version_file)


def test_command_writes_explicit_version_as_utf8(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## 9.0.0 - 2026-08-18\n\n- Unicode: caf\u00e9 \u6e2c\u8a66\n",
        encoding="utf-8",
    )
    output = tmp_path / "notes" / "registry.md"

    result = main(
        [
            "--changelog",
            str(changelog),
            "--version",
            "9.0.0",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert output.read_bytes() == "- Unicode: caf\u00e9 \u6e2c\u8a66\n".encode()
