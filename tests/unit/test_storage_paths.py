from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from civiscribe.domain import UnsafePathError
from civiscribe.storage.paths import OutputPlan, TemplateValues, resolve_output_plan

VALUES = TemplateValues(
    width=1024,
    height=768,
    batch_index=3,
    now=datetime(2026, 7, 18, 14, 5, 6, tzinfo=UTC),
    model="model/name:Q8.gguf",
    seed=123456789,
    sampler="multistep/res_2m",
)
MAX_COMPONENT_LENGTH = 120
NEXT_COUNTER_AFTER_TWO_FILES = 3
NEXT_JPEG_COUNTER = 8
NEXT_PNG_COUNTER = 4


def test_template_expands_documented_tokens_and_safe_subfolders(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "images/%date:yyyy-MM-dd%/%date:hhmmss%_%width%x%height%_%batch_num%",
        values=VALUES,
    )
    assert plan.root == tmp_path.resolve()
    assert plan.subfolder == "images/2026-07-18"
    assert plan.stem == "140506_1024x768_3"
    assert plan.directory.is_dir()
    assert plan.directory.is_relative_to(plan.root)


def test_generation_tokens_are_single_safe_filename_components(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "%date:yyyy-MM-dd%/%date:hhmmss%_%model%_%seed%_%sampler%",
        values=VALUES,
    )
    assert plan.subfolder == "2026-07-18"
    assert plan.stem == "140506_model_name_Q8.gguf_123456789_multistep_res_2m"


def test_missing_generation_tokens_use_stable_safe_fallbacks(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "%model%_%seed%_%sampler%",
        values=TemplateValues(
            width=1,
            height=1,
            batch_index=0,
            now=VALUES.now,
        ),
    )
    assert plan.stem == "model_seed_sampler"


@pytest.mark.parametrize(
    "extension", ["safetensors", "safetensor", "ckpt", "pt", "pth", "bin", "gguf", "sft"]
)
def test_model_noext_preserves_model_token_and_version_dots(tmp_path: Path, extension: str) -> None:
    filename = f"DreamModel.v2.Q8.{extension.upper()}"
    plan = resolve_output_plan(
        tmp_path,
        "%model_noext%/%model%_%model_noext%",
        values=replace(VALUES, model=filename),
    )
    assert plan.subfolder == "DreamModel.v2.Q8"
    assert plan.stem == f"{filename}_DreamModel.v2.Q8"


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("DreamModel.v2", "DreamModel.v2"),
        ("DreamModel.custom", "DreamModel.custom"),
        ("DreamModel.safetensors.backup", "DreamModel.safetensors.backup"),
        ("DreamModel.ckpt.safetensors", "DreamModel.ckpt"),
        ("DreamModel.safetensors.safetensors", "DreamModel.safetensors"),
        ("  DreamModel.v2.safetensors  ", "DreamModel.v2"),
        ("\u96ea.v2.gguf", "\u96ea.v2"),
        ("a" * (MAX_COMPONENT_LENGTH + 1) + ".safetensors", "a" * MAX_COMPONENT_LENGTH),
        (None, "model"),
        ("", "model"),
        ("  ", "model"),
        (".safetensors", "model"),
    ],
)
def test_model_noext_removes_only_a_known_final_extension(
    tmp_path: Path, model: str | None, expected: str
) -> None:
    plan = resolve_output_plan(tmp_path, "%model_noext%", values=replace(VALUES, model=model))
    assert plan.stem == expected


def test_model_noext_cannot_inject_paths_or_other_tokens(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "%model_noext%_%seed%",
        values=replace(VALUES, model="folder\\%seed%:name.gguf"),
    )
    assert plan.directory == tmp_path.resolve()
    assert plan.stem == "folder__seed__name_123456789"


def test_model_token_does_not_evaluate_unused_noext_value(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path, "%model%", values=replace(VALUES, model="... .safetensors")
    )
    assert plan.stem == "... .safetensors"


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("%counter%", "00007.png"),
        ("%counter:1%_portrait", "7_portrait.png"),
        ("%counter:9%_portrait", "000000007_portrait.png"),
        ("portrait_%counter:4%", "portrait_0007.png"),
        ("portrait_%counter:2%_final", "portrait_07_final.png"),
        ("%model_noext%_%counter:4%_%seed%", "model_name_Q8_0007_123456789.png"),
        ("portrait_%counter:2%_1", "portrait_07_1.png"),
        ("\u96ea.e\u0301_%counter:3%", "\u96ea.\u00e9_007.png"),
    ],
)
def test_counter_token_controls_position_and_minimum_width(
    tmp_path: Path, pattern: str, expected: str
) -> None:
    plan = resolve_output_plan(tmp_path, f"%date:yyyy-MM-dd%/{pattern}", values=VALUES)
    assert plan.subfolder == "2026-07-18"
    assert plan.filename(7, ".png") == expected


def test_counter_grows_beyond_padding_without_wrapping(tmp_path: Path) -> None:
    plan = resolve_output_plan(tmp_path, "%counter:2%_image", values=VALUES)
    assert plan.filename(100, ".webp") == "100_image.webp"


def test_counter_survives_component_truncation(tmp_path: Path) -> None:
    plan = resolve_output_plan(tmp_path, "%counter:9%_" + "a" * 200, values=VALUES)
    filename = plan.filename(999_999_999, ".png")
    assert filename.startswith("999999999_")
    assert len(Path(filename).stem) == MAX_COMPONENT_LENGTH


@pytest.mark.parametrize(
    ("pattern", "code"),
    [
        ("%counter%_%counter:4%", "filename_counter_repeated"),
        ("%counter:4%/image", "filename_counter_in_subfolder"),
        ("folder\\%counter%\\image", "filename_counter_in_subfolder"),
        ("a" * MAX_COMPONENT_LENGTH + "%counter%", "filename_counter_truncated"),
        ("a" * (MAX_COMPONENT_LENGTH - 1) + "%counter%", "filename_counter_truncated"),
        ("%counter:0%", "filename_token_unknown"),
        ("%counter:10%", "filename_token_unknown"),
        ("%counter:04%", "filename_token_unknown"),
        ("%counter:-1%", "filename_token_unknown"),
        ("%counter:%", "filename_token_unknown"),
        ("%counter:\u0664%", "filename_token_unknown"),
        ("%counter:4%_%unknown%", "filename_token_unknown"),
        ("C:/%counter:4%", "filename_absolute_path_rejected"),
        ("folder/../%counter%", "filename_traversal_rejected"),
    ],
)
def test_invalid_counter_templates_are_rejected_before_creating_directories(
    tmp_path: Path, pattern: str, code: str
) -> None:
    root = tmp_path / "not-created"
    with pytest.raises(UnsafePathError, match=code):
        resolve_output_plan(root, pattern, values=VALUES)
    assert not root.exists()


def test_rendered_counter_cannot_create_windows_device_name(tmp_path: Path) -> None:
    plan = resolve_output_plan(tmp_path, "COM%counter:1%", values=VALUES)
    with pytest.raises(UnsafePathError, match="filename_device_name_rejected"):
        plan.filename(1, ".png")


def test_model_value_cannot_inject_counter_token(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "%model_noext%",
        values=replace(VALUES, model="%counter:4%.gguf"),
    )
    assert plan.filename(1, ".png") == "_counter_4__00001_.png"


def test_uppercase_hour_token_and_filename_sanitization(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "%date:HHmmss%/bad?name.",
        values=VALUES,
    )
    assert plan.subfolder == "140506"
    assert plan.stem == "bad_name"


def test_date_token_supports_current_comfyui_format_parts(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "%date:yyyy-yy-M-MM-d-dd-h-hh-m-mm-s-ss%",
        values=VALUES,
    )
    assert plan.stem == "2026-26-7-07-18-18-14-14-5-05-6-06"


def test_legacy_comfyui_time_tokens_are_supported(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "%year%-%month%-%day%_%hour%-%minute%-%second%",
        values=VALUES,
    )
    assert plan.stem == "2026-7-18_14-5-6"


def test_prototype_date_alias_remains_supported(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "%date_YYYY-MM-DD%/%date_HHmmss%",
        values=VALUES,
    )
    assert plan.subfolder == "2026-07-18"
    assert plan.stem == "140506"


def test_literal_percent_is_allowed_when_it_is_not_an_unresolved_token(
    tmp_path: Path,
) -> None:
    plan = resolve_output_plan(tmp_path, "quality_100%", values=VALUES)
    assert plan.stem == "quality_100%"


def test_generation_token_values_cannot_inject_more_tokens(tmp_path: Path) -> None:
    plan = resolve_output_plan(
        tmp_path,
        "%model%_%sampler%",
        values=TemplateValues(
            width=1,
            height=1,
            batch_index=0,
            now=VALUES.now,
            model="%width%.gguf",
            sampler="%date:yyyy%",
        ),
    )
    assert plan.stem == "_width_.gguf__date_yyyy_"


def test_long_safe_component_is_bounded(tmp_path: Path) -> None:
    plan = resolve_output_plan(tmp_path, "a" * 200, values=VALUES)
    assert len(plan.stem) == MAX_COMPONENT_LENGTH


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("", "filename_template_length_invalid"),
        ("a" * 513, "filename_template_length_invalid"),
        ("/absolute", "filename_absolute_path_rejected"),
        ("C:/absolute", "filename_absolute_path_rejected"),
        ("//server/share", "filename_absolute_path_rejected"),
        ("folder/../escape", "filename_traversal_rejected"),
        ("folder//name", "filename_traversal_rejected"),
        ("folder/./name", "filename_traversal_rejected"),
        ("name:stream", "filename_colon_rejected"),
        ("NUL.txt", "filename_device_name_rejected"),
        ("...", "filename_component_empty"),
        ("%unknown%", "filename_token_unknown"),
        ("%date:%", "filename_token_unknown"),
    ],
)
def test_unsafe_templates_are_rejected(tmp_path: Path, value: str, code: str) -> None:
    with pytest.raises(UnsafePathError, match=code):
        resolve_output_plan(tmp_path, value, values=VALUES)


def test_non_string_template_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError, match="filename_template_not_string"):
        resolve_output_plan(tmp_path, cast(str, 42), values=VALUES)


def test_existing_symlink_component_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda self: self.name == "linked" or original(self),
    )
    with pytest.raises(UnsafePathError, match="output_symlink_rejected"):
        resolve_output_plan(tmp_path, "linked/file", values=VALUES)


def test_resolved_component_must_remain_under_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.is_relative_to
    monkeypatch.setattr(
        Path,
        "is_relative_to",
        lambda self, other: False if self.name == "escape" else original(self, other),
    )
    with pytest.raises(UnsafePathError, match="output_escape_rejected"):
        resolve_output_plan(tmp_path, "escape/file", values=VALUES)


def test_counter_scan_ignores_unrelated_entries_and_finds_highest(tmp_path: Path) -> None:
    (tmp_path / "prefix_00002_.png").write_bytes(b"x")
    (tmp_path / "prefix_bad_.png").write_bytes(b"x")
    (tmp_path / "other_00099_.png").write_bytes(b"x")
    (tmp_path / "prefix_00003_.png").mkdir()
    plan = OutputPlan(tmp_path, tmp_path, "", "prefix")
    assert plan.next_counter(".png") == NEXT_COUNTER_AFTER_TWO_FILES


def test_counter_scan_handles_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    plan = OutputPlan(tmp_path, missing, "", "prefix")
    assert plan.next_counter(".png") == 1


def test_counter_scan_is_scoped_to_selected_extension(tmp_path: Path) -> None:
    (tmp_path / "image_00003_.png").write_bytes(b"png")
    (tmp_path / "image_00007_.jpg").write_bytes(b"jpeg")
    plan = OutputPlan(tmp_path, tmp_path, "", "image")
    assert plan.next_counter(".png") == NEXT_PNG_COUNTER
    assert plan.next_counter(".jpg") == NEXT_JPEG_COUNTER
    assert plan.next_counter(".webp") == 1


def test_counter_scan_rejects_invalid_extension(tmp_path: Path) -> None:
    plan = OutputPlan(tmp_path, tmp_path, "", "image")
    with pytest.raises(UnsafePathError, match="output_extension_invalid"):
        plan.next_counter("../png")


def test_custom_counter_scan_matches_literal_names_and_previous_padding(tmp_path: Path) -> None:
    for filename in (
        "scene.(draft)_2_Final.png",
        "scene.(draft)_00007_Final.PNG",
        "scene.(draft)_91_final.png",
        "Scene.(draft)_92_Final.png",
        "scene.Xdraft_99_Final.png",
        "scene.(draft)_100_Final.jpg",
        "scene.(draft)_100_Final.png.bak",
        "scene.(draft)_1000000000_Final.png",
    ):
        (tmp_path / filename).write_bytes(b"existing")
    (tmp_path / "scene.(draft)_99_Final.png").mkdir()
    plan = resolve_output_plan(tmp_path, "scene.(draft)_%counter:4%_Final", values=VALUES)
    expected_counter = 8
    assert plan.next_counter(".png") == expected_counter
    assert plan.filename(plan.next_counter(".png"), ".png") == "scene.(draft)_0008_Final.png"


def test_token_counter_can_continue_existing_default_suffix(tmp_path: Path) -> None:
    (tmp_path / "image_00003_.png").write_bytes(b"old default")
    plan = resolve_output_plan(tmp_path, "image_%counter:2%_", values=VALUES)
    assert plan.filename(plan.next_counter(".png"), ".png") == "image_04_.png"


@given(
    marker=st.sampled_from(["..", "."]),
    suffix=st.text(alphabet="abc", min_size=1, max_size=12),
)
def test_traversal_components_never_resolve(marker: str, suffix: str) -> None:
    with (
        TemporaryDirectory() as temporary_directory,
        pytest.raises(UnsafePathError),
    ):
        resolve_output_plan(
            Path(temporary_directory),
            f"safe/{marker}/{suffix}",
            values=VALUES,
        )
