from __future__ import annotations

import pytest

from civiscribe.domain import ImageFormat, SerializationError
from civiscribe.projections import (
    ExifMetadataProjection,
    MetadataTier,
    PngMetadataProjection,
    build_reduced_writer_projection,
    build_rich_writer_projection,
)
from civiscribe.projections import exif as exif_projection
from tests.projection_support import complete_record


def test_rich_projection_dispatch_preserves_png_carriers_only_for_png() -> None:
    png = build_rich_writer_projection(
        complete_record(),
        ImageFormat.PNG,
        prompt={"1": {"inputs": {"text": "雪"}}},
        workflow={"nodes": []},
    )
    jpeg = build_rich_writer_projection(
        complete_record(),
        ImageFormat.JPEG,
        prompt={"private": "not embedded"},
        workflow={"nodes": []},
    )
    webp = build_rich_writer_projection(
        complete_record(),
        ImageFormat.WEBP,
        prompt={"private": "not embedded"},
        workflow={"nodes": []},
    )

    assert isinstance(png, PngMetadataProjection)
    assert png.prompt_json is not None
    assert png.workflow_json is not None
    assert png.civitai_json is not None
    assert isinstance(jpeg, ExifMetadataProjection)
    assert isinstance(webp, ExifMetadataProjection)
    assert jpeg == webp
    assert jpeg.tier is MetadataTier.RICH
    assert jpeg.write_dimensions is True


@pytest.mark.parametrize("output_format", list(ImageFormat))
def test_reduced_projection_dispatch_uses_selected_container(
    output_format: ImageFormat,
) -> None:
    projection = build_reduced_writer_projection(complete_record(), output_format)
    expected_type = (
        PngMetadataProjection if output_format is ImageFormat.PNG else ExifMetadataProjection
    )
    assert isinstance(projection, expected_type)
    assert projection.tier is MetadataTier.REDUCED


def test_exif_projection_rejects_oversized_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(exif_projection, "MAX_PARAMETERS_CHARS", 4)
    monkeypatch.setattr(exif_projection, "build_a1111", lambda _record: "12345")
    with pytest.raises(SerializationError, match="parameters_output_too_large"):
        build_reduced_writer_projection(complete_record(), ImageFormat.JPEG)
