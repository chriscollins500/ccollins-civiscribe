"""Compare a CiviScribe sidecar with a manually captured Civitai image response.

This development tool is offline and observational. It performs no upload,
download, or API request and never prints prompts, filenames, paths, or tokens.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

MAX_INPUT_BYTES = 32 * 1024 * 1024
_FIELDS = (
    "prompt",
    "negativePrompt",
    "seed",
    "steps",
    "sampler",
    "scheduler",
    "cfgScale",
    "guidance",
    "clipSkip",
    "width",
    "height",
)
_REMOTE_ALIASES = {
    "negativePrompt": ("negativePrompt", "Negative prompt"),
    "cfgScale": ("cfgScale", "CFG scale"),
    "clipSkip": ("clipSkip", "Clip skip"),
    "width": ("width",),
    "height": ("height",),
}


@dataclass(frozen=True, slots=True)
class ParserComparisonReport:
    """Sanitized recognition comparison without metadata values."""

    field_status: dict[str, str]
    resource_status: str
    expected_resource_count: int
    observed_resource_count: int
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "errors": list(self.errors),
            "expectedResourceCount": self.expected_resource_count,
            "fieldStatus": dict(sorted(self.field_status.items())),
            "observedResourceCount": self.observed_resource_count,
            "resourceStatus": self.resource_status,
            "valid": self.valid,
        }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> object:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input_too_large")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("input_json_invalid") from exc


def _api_image(payload: object, image_id: int | None) -> Mapping[str, object] | None:
    if isinstance(payload, Mapping) and isinstance(payload.get("meta"), Mapping):
        return payload
    values: object = payload.get("items") if isinstance(payload, Mapping) else payload
    if not isinstance(values, list):
        return None
    candidates = [value for value in values if isinstance(value, Mapping)]
    if image_id is not None:
        candidates = [value for value in candidates if value.get("id") == image_id]
    return candidates[0] if len(candidates) == 1 else None


def _remote_value(meta: Mapping[str, object], field: str) -> object | None:
    aliases = _REMOTE_ALIASES.get(field, (field,))
    direct = next((meta[name] for name in aliases if name in meta), None)
    if direct is not None or field not in {"width", "height"}:
        return direct
    size = meta.get("Size")
    match = re.fullmatch(r"(\d+)x(\d+)", size.strip()) if isinstance(size, str) else None
    if match is None:
        return None
    return int(match.group(1 if field == "width" else 2))


def _local_values(sidecar: object) -> tuple[dict[str, object | None], set[int]] | None:
    if not isinstance(sidecar, Mapping):
        return None
    civitai = _mapping(_mapping(sidecar.get("projections")).get("civitai"))
    if not civitai:
        return None
    prompt = _mapping(civitai.get("prompt"))
    generation = _mapping(civitai.get("generation"))
    values: dict[str, object | None] = {
        "prompt": prompt.get("positive"),
        "negativePrompt": prompt.get("negative"),
    }
    values.update({field: generation.get(field) for field in _FIELDS[2:]})
    resources = civitai.get("civitaiResources")
    resource_items = resources if isinstance(resources, list) else []
    resource_ids = {
        value
        for item in resource_items
        if isinstance(item, Mapping)
        and isinstance((value := item.get("modelVersionId")), int)
        and not isinstance(value, bool)
        and value > 0
    }
    return values, resource_ids


def _remote_resource_ids(image: Mapping[str, object]) -> set[int]:
    meta = _mapping(image.get("meta"))
    resources = meta.get("resources")
    if not isinstance(resources, list):
        resources = meta.get("civitaiResources")
    if not isinstance(resources, list):
        resources = image.get("resources")
    if not isinstance(resources, list):
        return set()
    return {
        value
        for item in resources
        if isinstance(item, Mapping)
        and isinstance((value := item.get("modelVersionId")), int)
        and not isinstance(value, bool)
        and value > 0
    }


def _compare_field_status(
    expected: Mapping[str, object | None],
    meta: Mapping[str, object],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in _FIELDS:
        local_value = expected.get(field)
        remote_value = _remote_value(meta, field)
        if local_value is None:
            status = "not_expected"
        elif remote_value is None:
            status = "missing"
        elif remote_value == local_value:
            status = "match"
        else:
            status = "different"
        result[field] = status
    return result


def _compare_resource_status(expected: set[int], observed: set[int]) -> str:
    if not expected:
        return "not_expected"
    if not observed:
        return "missing"
    if expected == observed:
        return "match"
    if expected.issubset(observed):
        return "match_with_additional"
    if expected & observed:
        return "partial"
    return "different"


def compare_parser_result(
    sidecar: object,
    api_response: object,
    *,
    image_id: int | None = None,
) -> ParserComparisonReport:
    """Compare expected and observed parser fields without returning values."""

    local = _local_values(sidecar)
    if local is None:
        return ParserComparisonReport({}, "not_compared", 0, 0, ("sidecar_projection_invalid",))
    image = _api_image(api_response, image_id)
    if image is None:
        return ParserComparisonReport({}, "not_compared", 0, 0, ("api_image_ambiguous",))

    expected, expected_resource_ids = local
    meta = _mapping(image.get("meta"))
    field_status = _compare_field_status(expected, meta)
    observed_resource_ids = _remote_resource_ids(image)
    return ParserComparisonReport(
        field_status,
        _compare_resource_status(expected_resource_ids, observed_resource_ids),
        len(expected_resource_ids),
        len(observed_resource_ids),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", type=Path)
    parser.add_argument("api_response", type=Path)
    parser.add_argument("--image-id", type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.image_id is not None and args.image_id < 1:
        print(json.dumps({"errors": ["image_id_invalid"], "valid": False}, sort_keys=True))
        return 2
    try:
        sidecar = _load_json(args.sidecar)
        api_response = _load_json(args.api_response)
    except (OSError, ValueError):
        print(json.dumps({"errors": ["input_invalid"], "valid": False}, sort_keys=True))
        return 2
    report = compare_parser_result(sidecar, api_response, image_id=args.image_id)
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
