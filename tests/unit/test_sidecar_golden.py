from __future__ import annotations

from pathlib import Path

from civiscribe.domain import ImageFormat
from civiscribe.projections import (
    SidecarArtifact,
    SidecarPolicy,
    build_sidecar_projection,
)
from tests.projection_support import complete_record
from tools.validate_sidecar import validate_sidecar

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "sidecar" / "complete_v2.json"


def _complete_projection_text() -> str:
    return build_sidecar_projection(
        complete_record(),
        SidecarArtifact(
            filename="complete_record_v1.png",
            sidecar_filename="complete_record_v1.json",
            subfolder="samples",
            output_format=ImageFormat.PNG,
            width=1024,
            height=768,
            batch_index=0,
            mode="RGB",
            channels=3,
            incoming_tensor_dtype="float32",
            encoded_sample_bits=8,
            file_size_bytes=12345,
            metadata_status="complete",
        ),
        SidecarPolicy(
            prompt={
                "6": {
                    "class_type": "KSampler",
                    "inputs": {"seed": 123456789},
                }
            },
            workflow={"nodes": [{"id": 6, "type": "KSampler"}]},
        ),
    ).json_text


def test_complete_sidecar_matches_immutable_golden_bytes() -> None:
    assert GOLDEN.read_bytes() == _complete_projection_text().encode("utf-8")
    assert validate_sidecar(GOLDEN).valid
