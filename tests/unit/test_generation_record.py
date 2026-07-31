from __future__ import annotations

from dataclasses import replace

import pytest

from civiscribe.domain import (
    GENERATOR_NAME,
    Diagnostics,
    GenerationSettings,
    GeneratorRecord,
    HashRecord,
    ImageFormat,
    ImageRecord,
    IssueSeverity,
    PromptRecord,
    ScanIssue,
    WorkflowScan,
    generation_record_from_scan,
)
from tests.projection_support import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    complete_record,
    model_resource,
)


@pytest.mark.parametrize(
    ("image_format", "expected"),
    [
        (ImageFormat.PNG, "png"),
        (ImageFormat.JPEG, "jpeg"),
        (ImageFormat.WEBP, "webp"),
    ],
)
def test_image_record_preserves_supported_format(
    image_format: ImageFormat,
    expected: str,
) -> None:
    assert ImageRecord(image_format, 1, 2).format.value == expected


@pytest.mark.parametrize(
    ("width", "height", "batch_index", "message"),
    [
        (0, 1, 0, "image_dimensions_invalid"),
        (1, 0, 0, "image_dimensions_invalid"),
        (1, 1, -1, "batch_index_invalid"),
    ],
)
def test_image_record_rejects_invalid_facts(
    width: int,
    height: int,
    batch_index: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ImageRecord(ImageFormat.PNG, width, height, batch_index)


def test_hash_record_and_diagnostics_have_explicit_empty_semantics() -> None:
    warning = ScanIssue("warning")
    error = ScanIssue("error", IssueSeverity.ERROR)

    assert HashRecord().is_empty
    assert not HashRecord(auto_v2="1234567890").is_empty
    assert Diagnostics(warnings=(warning,), errors=(error,)).all_issues == (
        error,
        warning,
    )


def test_generation_record_from_scan_filters_inactive_and_uses_final_dimensions() -> None:
    active = model_resource()
    inactive = replace(active, key="2:unet_name", node_id="2", active=False)
    warning = ScanIssue("scanner_warning")
    error = ScanIssue("scanner_error", IssueSeverity.ERROR)
    scan = WorkflowScan(
        save_node_id="40",
        active_node_ids=("1", "40"),
        selected_stage_node_id="20",
        stage_candidate_ids=("20",),
        workflow_kind=None,
        prompts=PromptRecord(),
        settings=GenerationSettings(width=512, height=512),
        resources=(active, inactive),
        primary_resource_key=active.key,
        selected_vae_resource_key=None,
        issues=(warning, error),
    )
    generator = GeneratorRecord(name="Generator", version="1.2.3")

    record = generation_record_from_scan(
        scan,
        image=ImageRecord(
            ImageFormat.WEBP,
            IMAGE_WIDTH,
            IMAGE_HEIGHT,
            batch_index=2,
        ),
        generator=generator,
    )

    assert record.resources == (active,)
    assert record.generator is generator
    assert record.image.width == IMAGE_WIDTH
    assert record.image.height == IMAGE_HEIGHT
    assert record.diagnostics.errors == (error,)
    assert {issue.code for issue in record.diagnostics.warnings} == {
        "scanner_warning",
        "generation_dimensions_differ_from_final_image",
    }


def test_generation_record_from_scan_uses_default_generator_without_false_mismatch() -> None:
    baseline = complete_record()
    scan = WorkflowScan(
        save_node_id="40",
        active_node_ids=("1", "40"),
        selected_stage_node_id="20",
        stage_candidate_ids=("20",),
        workflow_kind=baseline.workflow_kind,
        prompts=baseline.prompts,
        settings=baseline.settings,
        resources=baseline.resources,
        primary_resource_key=baseline.primary_resource_key,
        selected_vae_resource_key=baseline.selected_vae_resource_key,
        issues=(),
    )

    record = generation_record_from_scan(scan, image=baseline.image)

    assert record.generator.name == GENERATOR_NAME
    assert record.diagnostics == Diagnostics()
