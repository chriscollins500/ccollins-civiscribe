from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from PIL import Image

from civiscribe.adapters.model_files import ModelRootLocator
from civiscribe.domain import (
    GenerationRecord,
    HashRecord,
    IdentitySource,
    ImageFormat,
    ImageFrame,
    ResourceIdentity,
    WriteError,
)
from civiscribe.identity import (
    HashingMode,
    IdentityResolutionOptions,
    IdentityServices,
)
from civiscribe.identity.hashing import HashCache
from civiscribe.identity.local_cache import IdentityCache
from civiscribe.orchestration import (
    MetadataRequest,
    SaveRequest,
    SidecarStatus,
    pipeline,
    save_image_batch,
)
from civiscribe.projections import WriterMetadata
from civiscribe.storage.paths import OutputPlan
from civiscribe.writers import JpegWriter, PngWriter, WebpWriter
from civiscribe.writers.exif import read_exif
from civiscribe.writers.protocol import WriteResult
from tools.validate_sidecar import validate_sidecar

RGB_CHANNELS = 3


def _frame(value: float = 0.5) -> ImageFrame:
    return ImageFrame(np.full((2, 3, 3), value, dtype=np.float32))


def _metadata_request() -> MetadataRequest:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "workflows" / "basic_checkpoint.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    return MetadataRequest(
        prompt=fixture["prompt"],
        workflow={"nodes": [{"id": 7, "type": "CCollins_CiviScribe_SaveImage"}]},
        save_node_id="7",
    )


def test_pipeline_saves_batch_with_no_metadata_or_temporary_files(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(0.0), _frame(1.0)),
            output_root=tmp_path,
            filename_prefix="batch",
        )
    )
    assert [item.filename for item in outcome.saved_images] == [
        "batch_00001_.png",
        "batch_00002_.png",
    ]
    assert outcome.warnings == ()
    assert all(image.metadata_status == "minimal" for image in outcome.saved_images)
    assert not list(tmp_path.glob(".civiscribe-*"))


def test_invalid_custom_template_falls_back_to_default_root(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="../escape",
        )
    )
    assert outcome.saved_images[0].filename == "ComfyUI_00001_.png"
    assert outcome.saved_images[0].subfolder == ""
    assert [warning.code for warning in outcome.warnings] == ["filename_traversal_rejected"]


class _FailOnceWriter(PngWriter):
    def __init__(self) -> None:
        self.calls = 0

    def write(
        self,
        frame: ImageFrame,
        destination: Path,
        metadata: WriterMetadata | None = None,
    ) -> WriteResult:
        self.calls += 1
        if self.calls == 1:
            raise OSError
        return super().write(frame, destination, metadata)


class _AlwaysFailWriter(PngWriter):
    def write(
        self,
        frame: ImageFrame,
        destination: Path,
        metadata: WriterMetadata | None = None,
    ) -> WriteResult:
        raise RuntimeError


class _TierFailWriter(PngWriter):
    def __init__(self, *tiers: str | None) -> None:
        self.tiers = set(tiers)

    def write(
        self,
        frame: ImageFrame,
        destination: Path,
        metadata: WriterMetadata | None = None,
    ) -> WriteResult:
        tier = metadata.tier.value if metadata is not None else None
        if tier in self.tiers:
            raise WriteError(f"injected_{tier or 'pixels'}_write_failure")
        return super().write(frame, destination, metadata)


def test_custom_subfolder_failure_uses_root_fallback(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="custom/name",
        ),
        writer=_FailOnceWriter(),
    )
    assert outcome.saved_images[0].filename == "ComfyUI_00001_.png"
    assert [warning.code for warning in outcome.warnings] == [
        "filesystem_operation_failed",
        "fallback_output_used",
    ]


def test_partial_batch_survives_one_unsaved_frame(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(), _frame()),
            output_root=tmp_path,
            filename_prefix="ComfyUI",
        ),
        writer=_FailOnceWriter(),
    )
    assert len(outcome.saved_images) == 1
    assert [warning.code for warning in outcome.warnings] == [
        "filesystem_operation_failed",
        "image_not_saved",
    ]


def test_all_pixel_writes_failed_raises_stable_error(tmp_path: Path) -> None:
    with pytest.raises(WriteError, match="no_image_saved"):
        save_image_batch(
            SaveRequest(
                images=(_frame(),),
                output_root=tmp_path,
                filename_prefix="custom/name",
            ),
            writer=_AlwaysFailWriter(),
        )


def test_empty_request_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(WriteError, match="image_batch_empty"):
        save_image_batch(SaveRequest((), tmp_path, "ComfyUI"))


def test_fallback_plan_failure_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "_plan",
        lambda *_: (_ for _ in ()).throw(OSError("private path")),
    )
    with pytest.raises(WriteError, match="no_image_saved"):
        save_image_batch(SaveRequest((_frame(),), tmp_path, "../escape"))


def test_root_fallback_plan_failure_after_write_failure_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_plan = pipeline._plan

    def fail_only_root_fallback(
        request: SaveRequest,
        frame: ImageFrame,
        batch_index: int,
        prefix: str,
        record: GenerationRecord | None = None,
    ) -> OutputPlan:
        if prefix == pipeline.FALLBACK_PREFIX:
            raise OSError("private path")
        return original_plan(request, frame, batch_index, prefix, record)

    monkeypatch.setattr(pipeline, "_plan", fail_only_root_fallback)

    with pytest.raises(WriteError, match="no_image_saved"):
        save_image_batch(
            SaveRequest((_frame(),), tmp_path, "custom/name"),
            writer=_AlwaysFailWriter(),
        )


def test_timestamp_is_injected_into_template(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="%date:yyyy-MM-dd%/image",
            timestamp=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )
    assert outcome.saved_images[0].subfolder == "2026-07-18"


def test_generation_metadata_tokens_drive_requested_filename(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="%date:yyyy-MM-dd%/%date:hhmmss%_%model%_%seed%_%sampler%",
            timestamp=datetime(2026, 7, 18, 14, 5, 6, tzinfo=UTC),
            metadata=_metadata_request(),
        )
    )
    saved = outcome.saved_images[0]
    assert saved.subfolder == "2026-07-18"
    assert saved.filename == ("140506_basic_sdxl.safetensors_123_euler_00001_.png")
    assert outcome.warnings == ()


def test_metadata_rich_save_stays_on_requested_path(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="rich/image",
            metadata=_metadata_request(),
        )
    )
    saved = outcome.saved_images[0]
    assert saved.subfolder == "rich"
    assert saved.metadata_status == "complete"
    assert outcome.warnings == ()


def test_rich_failure_retries_reduced_metadata_before_location_fallback(
    tmp_path: Path,
) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="custom/image",
            metadata=_metadata_request(),
        ),
        writer=_TierFailWriter("rich"),
    )
    saved = outcome.saved_images[0]
    assert saved.subfolder == "custom"
    assert saved.metadata_status == "partial"
    assert [warning.code for warning in outcome.warnings] == [
        "injected_rich_write_failure",
        "metadata_reduced_fallback_used",
    ]


def test_rich_and_reduced_failures_still_save_pixels(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="ComfyUI",
            metadata=_metadata_request(),
        ),
        writer=_TierFailWriter("rich", "reduced"),
    )
    assert outcome.saved_images[0].metadata_status == "minimal"
    assert [warning.code for warning in outcome.warnings] == [
        "injected_rich_write_failure",
        "injected_reduced_write_failure",
        "metadata_pixels_only_fallback_used",
    ]


def test_rich_projection_failure_still_saves_reduced_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "build_rich_writer_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError),
    )
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="ComfyUI",
            metadata=_metadata_request(),
        )
    )
    assert outcome.saved_images[0].metadata_status == "partial"
    assert [warning.code for warning in outcome.warnings] == [
        "metadata_rich_build_failed",
        "metadata_reduced_fallback_used",
    ]


def test_all_metadata_build_failures_still_save_pixels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "build_rich_writer_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError),
    )
    monkeypatch.setattr(
        pipeline,
        "build_reduced_writer_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError),
    )
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="ComfyUI",
            metadata=_metadata_request(),
        )
    )
    assert outcome.saved_images[0].metadata_status == "minimal"
    assert [warning.code for warning in outcome.warnings] == [
        "metadata_rich_build_failed",
        "metadata_reduced_build_failed",
        "metadata_pixels_only_fallback_used",
    ]


def test_scanner_failure_still_saves_pixels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "scan_workflow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError),
    )
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="ComfyUI",
            metadata=_metadata_request(),
        )
    )
    assert outcome.saved_images[0].metadata_status == "minimal"
    assert [warning.code for warning in outcome.warnings] == [
        "metadata_scan_failed",
        "metadata_pixels_only_fallback_used",
    ]


def test_prompt_overrides_feed_all_metadata_projections(tmp_path: Path) -> None:
    metadata = replace(
        _metadata_request(),
        positive_prompt_override="explicit positive",
        negative_prompt_override="explicit negative",
    )
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="overrides",
            metadata=metadata,
        )
    )
    path = tmp_path / outcome.saved_images[0].filename
    with Image.open(path) as image:
        text = cast(Mapping[str, str], getattr(image, "text", {}))
        manifest = cast(dict[str, object], json.loads(text["civitai"]))
    assert text["parameters"].startswith("explicit positive\nNegative prompt: explicit negative\n")
    assert manifest["prompt"] == {
        "positive": "explicit positive",
        "negative": "explicit negative",
        "positiveBranchPresent": True,
        "negativeBranchPresent": True,
    }


def test_krea2_switch_prompt_reaches_png_parameters_and_manifest(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "workflows" / "krea2_switch_prompt.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected = cast(dict[str, object], fixture["expected"])
    positive = cast(str, expected["positive"])
    metadata = MetadataRequest(
        prompt=fixture["prompt"],
        workflow={"nodes": [{"id": 18, "type": "CCollins_CiviScribe_SaveImage"}]},
        save_node_id="18",
    )

    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="krea2",
            metadata=metadata,
        )
    )

    path = tmp_path / outcome.saved_images[0].filename
    with Image.open(path) as image:
        text = cast(Mapping[str, str], getattr(image, "text", {}))
        manifest = cast(dict[str, object], json.loads(text["civitai"]))
    assert text["parameters"].startswith(f"{positive}\nNegative prompt:\n")
    assert "inactive prompt-engineering instructions" not in text["parameters"]
    assert cast(dict[str, object], manifest["prompt"])["positive"] == positive


def test_oversized_prompt_override_is_ignored_and_reported(tmp_path: Path) -> None:
    metadata = replace(
        _metadata_request(),
        positive_prompt_override="x" * (pipeline.MAX_PROMPT_OVERRIDE_CHARS + 1),
        negative_prompt_override="",
    )
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="bounded-override",
            metadata=metadata,
        )
    )
    path = tmp_path / outcome.saved_images[0].filename
    with Image.open(path) as image:
        text = cast(Mapping[str, str], getattr(image, "text", {}))
        manifest = cast(dict[str, object], json.loads(text["civitai"]))
    assert text["parameters"].startswith("a lighthouse at dawn\n")
    validation = cast(dict[str, object], manifest["validation"])
    warnings = cast(list[dict[str, object]], validation["warnings"])
    assert {item["code"] for item in warnings} >= {"positive_prompt_override_too_large"}


def test_identity_resolution_feeds_a1111_and_manifest_from_same_resource(
    tmp_path: Path,
) -> None:
    model_root = tmp_path / "models" / "checkpoints"
    model_root.mkdir(parents=True)
    (model_root / "basic_sdxl.safetensors").write_bytes(b"small model")
    empty_auto_v1 = "e3b0c442"
    identity_cache = IdentityCache(tmp_path / "cache" / "identities.json")
    identity = ResourceIdentity(
        source=IdentitySource.CACHE,
        raw_air="urn:air:sdxl:checkpoint:civitai:10@20",
        canonical_air="urn:air:sdxl:checkpoint:civitai:10@20",
        ecosystem="sdxl",
        resource_type="checkpoint",
        identity_source="civitai",
        identity_id="10",
        identity_version="20",
        model_id=10,
        model_version_id=20,
    )
    assert (
        identity_cache.put(
            identity,
            HashRecord(auto_v1=empty_auto_v1),
        )
        == ()
    )
    metadata = replace(
        _metadata_request(),
        identity_options=IdentityResolutionOptions(hashing_mode=HashingMode.CACHED_OR_FAST),
        identity_services=IdentityServices(
            locator=ModelRootLocator({"checkpoints": [model_root]}),
            hash_cache=HashCache(tmp_path / "cache" / "hashes.json"),
            identity_cache=identity_cache,
        ),
    )

    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path / "output",
            filename_prefix="resolved",
            metadata=metadata,
        )
    )

    path = tmp_path / "output" / outcome.saved_images[0].filename
    with Image.open(path) as image:
        text = cast(Mapping[str, str], getattr(image, "text", {}))
        parameters = text["parameters"]
        manifest = json.loads(text["civitai"])
    expected_air = "urn:air:sdxl:checkpoint:civitai:10@20"
    assert expected_air in parameters
    assert manifest["resources"][0]["identity"]["canonicalAir"] == expected_air
    assert manifest["resources"][0]["hashStatus"] == "fast_partial"
    assert manifest["resources"][0]["lookupStatus"] == "resolved_by_cache"
    assert manifest["civitaiResources"][0]["air"] == expected_air


def test_identity_resolution_failure_keeps_rich_metadata_and_pixels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "resolve_scan_identities",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )

    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="ComfyUI",
            metadata=_metadata_request(),
        )
    )

    assert outcome.saved_images[0].metadata_status == "complete"
    assert [warning.code for warning in outcome.warnings] == ["metadata_identity_resolution_failed"]


@pytest.mark.parametrize(
    ("output_format", "extension", "format_name"),
    [
        (ImageFormat.PNG, ".png", "PNG"),
        (ImageFormat.JPEG, ".jpg", "JPEG"),
        (ImageFormat.WEBP, ".webp", "WEBP"),
    ],
)
def test_pipeline_dispatches_supported_format_and_records_actual_output(
    tmp_path: Path,
    output_format: ImageFormat,
    extension: str,
    format_name: str,
) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="image",
            output_format=output_format,
        )
    )
    saved = outcome.saved_images[0]
    assert saved.filename.endswith(extension)
    assert saved.output_format is output_format
    with Image.open(tmp_path / saved.filename) as image:
        assert image.format == format_name


@pytest.mark.parametrize("output_format", [ImageFormat.JPEG, ImageFormat.WEBP])
def test_pipeline_embeds_a1111_exif_for_non_png_formats(
    tmp_path: Path,
    output_format: ImageFormat,
) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="metadata",
            output_format=output_format,
            metadata=_metadata_request(),
        )
    )
    saved = outcome.saved_images[0]
    with Image.open(tmp_path / saved.filename) as image:
        values = read_exif(image)
        assert "Steps: 20" in (values.user_comment or "")
        assert values.software is not None
        assert (values.pixel_width, values.pixel_height) == (3, 2)
    assert saved.metadata_status == "complete"


class _RichFailWebpWriter(WebpWriter):
    def write(
        self,
        frame: ImageFrame,
        destination: Path,
        metadata: WriterMetadata | None = None,
    ) -> WriteResult:
        if metadata is not None and metadata.tier.value == "rich":
            raise WriteError("injected_rich_write_failure")
        return super().write(frame, destination, metadata)


def test_non_png_rich_failure_uses_reduced_exif_without_losing_pixels(
    tmp_path: Path,
) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="metadata",
            output_format=ImageFormat.WEBP,
            metadata=_metadata_request(),
        ),
        writer=_RichFailWebpWriter(),
    )
    saved = outcome.saved_images[0]
    with Image.open(tmp_path / saved.filename) as image:
        values = read_exif(image)
    assert values.user_comment is not None
    assert values.software is None
    assert saved.metadata_status == "partial"
    assert [warning.code for warning in outcome.warnings] == [
        "injected_rich_write_failure",
        "metadata_reduced_fallback_used",
    ]


@pytest.mark.parametrize("writer", [JpegWriter(), WebpWriter()])
def test_pipeline_rejects_injected_writer_for_different_format(
    tmp_path: Path,
    writer: JpegWriter | WebpWriter,
) -> None:
    with pytest.raises(WriteError, match="writer_format_mismatch"):
        save_image_batch(
            SaveRequest(
                images=(_frame(),),
                output_root=tmp_path,
                filename_prefix="image",
            ),
            writer=writer,
        )


def test_sidecar_is_off_by_default_and_does_not_change_image_bytes(tmp_path: Path) -> None:
    without_directory = tmp_path / "without"
    with_directory = tmp_path / "with"
    without = save_image_batch(
        SaveRequest((_frame(),), without_directory, "image"),
    )
    with_sidecar = save_image_batch(
        SaveRequest(
            (_frame(),),
            with_directory,
            "image",
            write_sidecar_json=True,
        ),
    )
    without_image = without.saved_images[0]
    with_image = with_sidecar.saved_images[0]
    assert without_image.sidecar_status is SidecarStatus.NOT_REQUESTED
    assert without_image.sidecar_filename is None
    assert not list(without_directory.glob("*.json"))
    assert with_image.sidecar_status is SidecarStatus.WRITTEN
    assert (without_directory / without_image.filename).read_bytes() == (
        with_directory / with_image.filename
    ).read_bytes()


@pytest.mark.parametrize(
    ("output_format", "expected_mode", "expected_channels"),
    [
        (ImageFormat.PNG, "RGB", 3),
        (ImageFormat.JPEG, "RGB", 3),
        (ImageFormat.WEBP, "RGB", 3),
    ],
)
def test_each_supported_format_writes_valid_sidecar_after_image(
    tmp_path: Path,
    output_format: ImageFormat,
    expected_mode: str,
    expected_channels: int,
) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix=output_format.value,
            output_format=output_format,
            write_sidecar_json=True,
            metadata=_metadata_request(),
        )
    )
    saved = outcome.saved_images[0]
    assert saved.sidecar_status is SidecarStatus.WRITTEN
    assert saved.sidecar_filename is not None
    sidecar = tmp_path / saved.sidecar_filename
    assert sidecar.is_file()
    assert validate_sidecar(sidecar).valid
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["artifact"]["fileName"] == saved.filename
    assert payload["artifact"]["mode"] == expected_mode
    assert payload["artifact"]["channels"] == expected_channels
    assert payload["artifact"]["fileSizeBytes"] == (tmp_path / saved.filename).stat().st_size
    assert payload["save"]["sidecarStatus"] == "written"


def test_rgba_jpeg_sidecar_records_committed_rgb_not_source_alpha(tmp_path: Path) -> None:
    frame = ImageFrame(np.ones((2, 3, 4), dtype=np.float32))
    outcome = save_image_batch(
        SaveRequest(
            images=(frame,),
            output_root=tmp_path,
            filename_prefix="flattened",
            output_format=ImageFormat.JPEG,
            write_sidecar_json=True,
        )
    )
    saved = outcome.saved_images[0]
    payload = json.loads((tmp_path / cast(str, saved.sidecar_filename)).read_text("utf-8"))
    assert payload["artifact"]["mode"] == "RGB"
    assert payload["artifact"]["channels"] == RGB_CHANNELS
    assert payload["artifact"]["hasAlpha"] is False


def test_sidecar_records_pixels_only_fallback_diagnostics(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="fallback",
            write_sidecar_json=True,
            metadata=_metadata_request(),
        ),
        writer=_TierFailWriter("rich", "reduced"),
    )
    saved = outcome.saved_images[0]
    assert saved.metadata_status == "minimal"
    assert saved.sidecar_status is SidecarStatus.WRITTEN
    payload = json.loads((tmp_path / cast(str, saved.sidecar_filename)).read_text("utf-8"))
    assert payload["artifact"]["metadataStatus"] == "minimal"
    assert payload["save"]["warnings"] == [
        {"batchIndex": 0, "code": "injected_rich_write_failure"},
        {"batchIndex": 0, "code": "injected_reduced_write_failure"},
        {"batchIndex": 0, "code": "metadata_pixels_only_fallback_used"},
    ]


def test_sidecar_payload_redaction_warning_reaches_outcome(tmp_path: Path) -> None:
    metadata = replace(
        _metadata_request(),
        workflow={
            "authorization": "Bearer abcdefghijk",
            "privatePath": r"C:\Users\Person\private\workflow.json",
        },
    )
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="redacted",
            write_sidecar_json=True,
            metadata=metadata,
        )
    )
    saved = outcome.saved_images[0]
    assert [warning.code for warning in outcome.warnings] == [
        "embedded_metadata_private_values_redacted",
        "sidecar_payload_private_values_redacted",
    ]
    text = (tmp_path / cast(str, saved.sidecar_filename)).read_text("utf-8")
    assert "abcdefghijk" not in text
    assert "C:\\\\Users" not in text
    assert validate_sidecar(tmp_path / cast(str, saved.sidecar_filename)).valid


def test_sidecar_projection_failure_never_blocks_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "build_sidecar_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="image",
            write_sidecar_json=True,
        )
    )
    saved = outcome.saved_images[0]
    assert (tmp_path / saved.filename).is_file()
    assert saved.sidecar_status is SidecarStatus.FAILED
    assert saved.sidecar_filename is None
    assert [warning.code for warning in outcome.warnings] == ["sidecar_projection_failed"]


def test_sidecar_write_failure_never_blocks_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline,
        "write_sidecar_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("private")),
    )
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="image",
            write_sidecar_json=True,
        )
    )
    saved = outcome.saved_images[0]
    assert (tmp_path / saved.filename).is_file()
    assert saved.sidecar_status is SidecarStatus.FAILED
    assert [warning.code for warning in outcome.warnings] == ["sidecar_write_failed"]


class _UnsupportedReportedModeWriter(PngWriter):
    def write(
        self,
        frame: ImageFrame,
        destination: Path,
        metadata: WriterMetadata | None = None,
    ) -> WriteResult:
        return replace(super().write(frame, destination, metadata), mode="CMYK")


def test_unknown_committed_mode_fails_only_sidecar(tmp_path: Path) -> None:
    outcome = save_image_batch(
        SaveRequest(
            images=(_frame(),),
            output_root=tmp_path,
            filename_prefix="image",
            write_sidecar_json=True,
        ),
        writer=_UnsupportedReportedModeWriter(),
    )
    saved = outcome.saved_images[0]
    assert (tmp_path / saved.filename).is_file()
    assert saved.sidecar_status is SidecarStatus.FAILED
    assert [warning.code for warning in outcome.warnings] == ["sidecar_projection_failed"]
