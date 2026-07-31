from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.compare_civitai_parser_result import compare_parser_result, main

EXPECTED_RESOURCE_COUNT = 2
INPUT_ERROR_EXIT = 2


def _sidecar() -> dict[str, object]:
    return {
        "projections": {
            "civitai": {
                "prompt": {
                    "positive": "private positive prompt",
                    "negative": "private negative prompt",
                },
                "generation": {
                    "seed": 42,
                    "steps": 20,
                    "sampler": "euler",
                    "scheduler": "normal",
                    "cfgScale": 7.0,
                    "guidance": None,
                    "clipSkip": 2,
                    "width": 1024,
                    "height": 768,
                },
                "civitaiResources": [
                    {"modelVersionId": 200},
                    {"modelVersionId": 300},
                ],
            }
        }
    }


def _api_image() -> dict[str, object]:
    return {
        "id": 10,
        "meta": {
            "prompt": "private positive prompt",
            "negativePrompt": "private negative prompt",
            "seed": 42,
            "steps": 20,
            "sampler": "euler",
            "scheduler": "normal",
            "cfgScale": 7.0,
            "clipSkip": 2,
            "Size": "1024x768",
            "resources": [
                {"modelVersionId": 200},
                {"modelVersionId": 300},
            ],
        },
    }


def test_compare_parser_result_reports_matches_without_metadata_values() -> None:
    report = compare_parser_result(_sidecar(), _api_image())

    assert report.valid
    assert report.resource_status == "match"
    assert report.expected_resource_count == EXPECTED_RESOURCE_COUNT
    assert report.observed_resource_count == EXPECTED_RESOURCE_COUNT
    assert report.field_status["prompt"] == "match"
    assert report.field_status["guidance"] == "not_expected"
    serialized = json.dumps(report.as_dict())
    assert "private positive prompt" not in serialized
    assert "private negative prompt" not in serialized


def test_compare_parser_result_reports_missing_different_and_partial() -> None:
    image = _api_image()
    meta = image["meta"]
    assert isinstance(meta, dict)
    meta.pop("prompt")
    meta["steps"] = 19
    meta["resources"] = [
        {"modelVersionId": 200},
        {"modelVersionId": 400},
    ]

    report = compare_parser_result(_sidecar(), image)

    assert report.field_status["prompt"] == "missing"
    assert report.field_status["steps"] == "different"
    assert report.resource_status == "partial"


def test_compare_parser_result_selects_requested_image_from_items() -> None:
    response = {
        "items": [
            {"id": 9, "meta": {}},
            _api_image(),
        ]
    }

    ambiguous = compare_parser_result(_sidecar(), response)
    selected = compare_parser_result(_sidecar(), response, image_id=10)

    assert ambiguous.errors == ("api_image_ambiguous",)
    assert selected.resource_status == "match"


def test_compare_parser_result_rejects_invalid_projection() -> None:
    report = compare_parser_result({"projections": {}}, _api_image())

    assert report.errors == ("sidecar_projection_invalid",)


def test_cli_outputs_only_sanitized_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sidecar = tmp_path / "sidecar.json"
    response = tmp_path / "response.json"
    sidecar.write_text(json.dumps(_sidecar()), encoding="utf-8")
    response.write_text(json.dumps(_api_image()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["compare_civitai_parser_result.py", str(sidecar), str(response)],
    )

    assert main() == 0
    output = capsys.readouterr().out
    assert json.loads(output)["resourceStatus"] == "match"
    assert "private positive prompt" not in output
    assert str(tmp_path) not in output


def test_cli_rejects_invalid_input_without_echoing_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid = tmp_path / "private-path.json"
    invalid.write_text("{", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["compare_civitai_parser_result.py", str(invalid), str(invalid)],
    )

    assert main() == INPUT_ERROR_EXIT
    output = capsys.readouterr().out
    assert json.loads(output) == {"errors": ["input_invalid"], "valid": False}
    assert str(tmp_path) not in output
