from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator

from civiscribe import api
from civiscribe.domain import ImageFormat
from civiscribe.orchestration import SavedImage, SaveOutcome, SaveWarning, SidecarStatus

NODE_ID = "CCollins_CiviScribe_SaveImage"
ROOT = Path(__file__).resolve().parents[2]
BRANCH_COUNT = 5
DEMO_BRANCH_COUNT = 2


def validate_contract(name: str, value: object) -> None:
    document = api.openapi_document()
    schema = {"$ref": f"#/components/schemas/{name}", "components": document["components"]}
    Draft202012Validator(schema).validate(value)


def test_capabilities_and_packaged_openapi_describe_native_execution() -> None:
    result = api.capabilities(NODE_ID)
    validate_contract("Capabilities", result)
    assert result["execution"] == {
        "submit": "/prompt",
        "history": "/history/{prompt_id}",
        "view": "/view",
        "events": "/ws",
    }
    document = api.openapi_document()
    assert document["openapi"] == "3.1.0"
    assert set(cast(Mapping[str, object], document["paths"])) == {
        f"{api.API_PREFIX}/capabilities",
        f"{api.API_PREFIX}/preflight",
        f"{api.API_PREFIX}/openapi.json",
    }


def test_preflight_scans_all_branches_without_echoing_prompts() -> None:
    prompt: dict[str, object] = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "demo.safetensors"}},
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "private positive prompt"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "private negative prompt"},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 768, "batch_size": 1},
        },
    }
    for branch in range(BRANCH_COUNT):
        sampler, decode, save = (str(10 * branch + offset) for offset in (5, 6, 7))
        prompt[sampler] = {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": branch + 100,
                "steps": 20,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
            },
        }
        prompt[decode] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": [sampler, 0], "vae": ["1", 2]},
        }
        prompt[save] = {"class_type": NODE_ID, "inputs": {"images": [decode, 0]}}
    result = api.preflight({"prompt": prompt}, node_id=NODE_ID)
    validate_contract("Preflight", result)
    nodes = cast(list[dict[str, object]], result["nodes"])
    assert len(nodes) == BRANCH_COUNT
    assert [cast(dict[str, object], node["settings"])["seed"] for node in nodes] == list(
        range(100, 105)
    )
    assert "private positive prompt" not in json.dumps(result)
    assert "private negative prompt" not in json.dumps(result)
    assert "save_node_ambiguous" not in json.dumps(result)
    one = api.preflight({"prompt": prompt, "save_node_id": "27"}, node_id=NODE_ID)
    assert len(cast(list[object], one["nodes"])) == 1
    assert one["committed"] is False


def test_preflight_accepts_documented_demo_and_retains_unknowns() -> None:
    payload = json.loads((ROOT / "docs/examples/save-demo-api.json").read_text("utf-8"))
    validate_contract("PreflightRequest", payload)
    result = api.preflight(payload, node_id=NODE_ID)
    validate_contract("Preflight", result)
    assert len(cast(list[object], result["nodes"])) == DEMO_BRANCH_COUNT
    assert cast(list[dict[str, object]], result["nodes"])[0]["selectedStageNodeId"] is None


@pytest.mark.parametrize(
    "payload,code",
    [
        (None, "request_fields_invalid"),
        ({"unknown": 1}, "request_fields_invalid"),
        ({}, "prompt_object_required"),
        ({"prompt": []}, "prompt_object_required"),
        ({"prompt": {}}, "prompt_object_required"),
        ({"prompt": {"1": {}}, "save_node_id": True}, "save_node_id_invalid"),
        ({"prompt": {"1": {}}, "save_node_id": ""}, "save_node_id_invalid"),
        ({"prompt": {"1": {}}, "save_node_id": "x" * 129}, "save_node_id_invalid"),
        ({"prompt": {"1": {}}}, "save_node_not_found"),
        ({"prompt": {"1": {}}, "save_node_id": "9"}, "save_node_not_found"),
        ({"prompt": {"1": {"class_type": NODE_ID, "mode": 2}}}, "save_node_not_found"),
        ({"prompt": {"1": {"class_type": NODE_ID, "mode": 4}}}, "save_node_not_found"),
        (
            {"prompt": {str(i): {} for i in range(api.MAX_PREFLIGHT_NODES + 1)}},
            "prompt_node_limit_exceeded",
        ),
        (
            {"prompt": {str(i): {"class_type": NODE_ID} for i in range(api.MAX_SAVE_NODES + 1)}},
            "save_node_limit_exceeded",
        ),
    ],
)
def test_preflight_rejects_invalid_or_unbounded_requests(payload: object, code: str) -> None:
    with pytest.raises(api.ApiError, match=f"^{code}$"):
        api.preflight(payload, node_id=NODE_ID)


@pytest.mark.parametrize(
    "payload,code",
    [
        (b"{", "invalid_json"),
        (b"\xff", "invalid_json"),
        (b'{"x":1,"x":2}', "duplicate_json_key"),
        (b'{"x": NaN}', "invalid_json_constant"),
        (b'{"x": Infinity}', "invalid_json_constant"),
        (b'{"x": 1e999}', "invalid_json_constant"),
        (b"[" * 2000 + b"0" + b"]" * 2000, "request_nesting_too_deep"),
        (b"[" * 34 + b"0" + b"]" * 34, "request_nesting_too_deep"),
        (b" " * (api.MAX_REQUEST_BYTES + 1), "request_too_large"),
    ],
)
def test_request_parser_rejects_unsafe_json(payload: bytes, code: str) -> None:
    with pytest.raises(api.ApiError, match=f"^{code}$"):
        api.parse_request(payload)


def test_request_parser_preserves_strict_unicode_json() -> None:
    assert api.parse_request('{"text":"café", "values":[1, true, null]}'.encode()) == {
        "text": "café",
        "values": [1, True, None],
    }
    text = '"' + "[" * 40 + '\\"' + "\\\\" + '"'
    assert api.parse_request(text.encode()) == "[" * 40 + '"' + "\\"


def test_committed_report_uses_actual_fallback_format_and_sidecar_statuses() -> None:
    image = SavedImage("saved.png", "demo", ImageFormat.PNG, 64, 32, "minimal")
    outcome = SaveOutcome(
        (
            image,
            replace(image, sidecar_status=SidecarStatus.WRITTEN, sidecar_filename="saved.json"),
            replace(image, sidecar_status=SidecarStatus.FAILED),
        ),
        (SaveWarning("metadata_failed", 0), SaveWarning("\x00")),
    )
    result = api.save_report(outcome)
    validate_contract("SaveResult", result)
    assert cast(list[dict[str, object]], result["images"])[0]["format"] == "png"
    assert cast(list[dict[str, object]], result["warnings"])[1]["code"] == "save_warning"
    assert "prompt" not in result
    assert "workflow" not in result
