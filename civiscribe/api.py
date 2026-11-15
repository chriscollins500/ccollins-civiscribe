"""Versioned, host-independent projections for ComfyUI API and MCP clients."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from importlib.resources import files
from typing import cast

from . import schemas
from .domain import ScanIssue, WorkflowScan
from .orchestration.outcome import SaveOutcome
from .projections.resources import resource_manifest_item
from .projections.sanitize import metadata_scalar
from .version import __version__
from .workflow import scan_workflow
from .workflow.model import GraphLimits
from .workflow.normalize import canonical_node_id, normalize_api_prompt

API_PREFIX = "/civiscribe/v1"
API_VERSION = "1.0.0"
MAX_REQUEST_BYTES = 1024 * 1024
MAX_REQUEST_DEPTH = 32
MAX_PREFLIGHT_NODES = 4096
MAX_SAVE_NODES = 32
PREFLIGHT_LIMITS = GraphLimits(max_nodes=MAX_PREFLIGHT_NODES)


class ApiError(ValueError):
    """An HTTP-safe error containing a fixed code, never supplied payload values."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def capabilities(node_id: str) -> dict[str, object]:
    """Describe this installed version without inspecting files or opening a network."""

    return {
        "schema": "ccollins-civiscribe.api",
        "schemaVersion": API_VERSION,
        "version": __version__,
        "nodeId": node_id,
        "formats": ["png", "jpeg", "webp"],
        "endpoints": {
            "capabilities": f"{API_PREFIX}/capabilities",
            "preflight": f"{API_PREFIX}/preflight",
            "openapi": f"{API_PREFIX}/openapi.json",
            "nodeSchema": f"/object_info/{node_id}",
        },
        "execution": {
            "submit": "/prompt",
            "history": "/history/{prompt_id}",
            "view": "/view",
            "events": "/ws",
        },
        "mcp": {
            "provider": "Comfy-Org/comfy-mcp",
            "tools": ["nodes", "validate_workflow", "run_workflow", "job", "fetch_outputs"],
            "saveReports": "job.text_outputs[save_node_id][]",
        },
        "preflight": {
            "readOnly": True,
            "networkRequests": False,
            "modelFileReads": False,
            "runtimeValuesResolved": False,
            "maxRequestBytes": MAX_REQUEST_BYTES,
            "maxDepth": MAX_REQUEST_DEPTH,
            "maxNodes": MAX_PREFLIGHT_NODES,
            "maxSaveNodes": MAX_SAVE_NODES,
        },
    }


def openapi_document() -> dict[str, object]:
    """Load the packaged public contract, using the installed product version."""

    document = cast(
        dict[str, object],
        json.loads(files(schemas).joinpath("api-v1.openapi.json").read_text("utf-8")),
    )
    cast(dict[str, object], document["info"])["version"] = __version__
    return document


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ApiError("duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> object:
    raise ApiError("invalid_json_constant")


def _check_json_depth(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_REQUEST_DEPTH:
                raise ApiError("request_nesting_too_deep")
        elif character in "]}":
            depth -= 1


def parse_request(payload: bytes) -> object:
    """Decode bounded strict UTF-8 JSON; reject duplicates and nonfinite numbers."""

    if len(payload) > MAX_REQUEST_BYTES:
        raise ApiError("request_too_large", 413)
    try:
        text = payload.decode("utf-8")
        _check_json_depth(text)
        value: object = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ApiError):
            raise
        raise ApiError("invalid_json") from exc
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ApiError("invalid_json_constant")
    return value


def _issue(issue: ScanIssue) -> dict[str, object]:
    return {
        "code": metadata_scalar(issue.code) or "metadata_issue",
        "severity": issue.severity.value,
        "nodeId": metadata_scalar(issue.node_id),
        "inputName": metadata_scalar(issue.input_name),
    }


def _scan_report(scan: WorkflowScan) -> dict[str, object]:
    return {
        "saveNodeId": scan.save_node_id,
        "activeNodeIds": list(scan.active_node_ids),
        "selectedStageNodeId": scan.selected_stage_node_id,
        "workflowType": scan.workflow_kind.value if scan.workflow_kind is not None else None,
        "settings": {
            key: metadata_scalar(value) if isinstance(value, str) else value
            for key, value in asdict(scan.settings).items()
        },
        "resources": [resource_manifest_item(resource) for resource in scan.resources],
        "issues": [_issue(issue) for issue in scan.issues],
    }


def preflight(payload: object, *, node_id: str) -> dict[str, object]:
    """Scan each selected save branch without executing, hashing, lookup, or writes.

    This is metadata preflight. ComfyUI remains responsible for executable graph
    validation. Connected runtime strings and final pixel dimensions remain unknown.
    """

    if not isinstance(payload, dict) or set(payload) - {"prompt", "save_node_id"}:
        raise ApiError("request_fields_invalid")
    prompt = payload.get("prompt")
    if not isinstance(prompt, dict) or not prompt:
        raise ApiError("prompt_object_required")
    if len(prompt) > MAX_PREFLIGHT_NODES:
        raise ApiError("prompt_node_limit_exceeded", 413)
    requested = payload.get("save_node_id")
    if requested is not None and (
        not isinstance(requested, str)
        or not requested
        or len(requested) > PREFLIGHT_LIMITS.max_node_id_chars
    ):
        raise ApiError("save_node_id_invalid")
    graph = normalize_api_prompt(prompt, limits=PREFLIGHT_LIMITS)
    selected = [
        key
        for key in graph.node_ids
        if graph.nodes[key].class_type == node_id
        and not graph.nodes[key].muted
        and not graph.nodes[key].bypassed
    ]
    if requested is not None:
        selected_id = canonical_node_id(requested)
        if selected_id not in selected:
            raise ApiError("save_node_not_found", 404)
        selected = [selected_id]
    if not selected:
        raise ApiError("save_node_not_found", 404)
    if len(selected) > MAX_SAVE_NODES:
        raise ApiError("save_node_limit_exceeded", 413)
    return {
        "schema": "ccollins-civiscribe.preflight",
        "schemaVersion": API_VERSION,
        "phase": "static",
        "committed": False,
        "nodes": [
            _scan_report(scan_workflow(prompt, save_node_id=key, limits=PREFLIGHT_LIMITS))
            for key in selected
        ],
    }


def save_report(outcome: SaveOutcome) -> dict[str, object]:
    """Project committed facts; never rescan a workflow or claim a requested format."""

    return {
        "schema": "ccollins-civiscribe.save-result",
        "schemaVersion": API_VERSION,
        "version": __version__,
        "images": [
            {
                "filename": image.filename,
                "subfolder": image.subfolder,
                "type": "output",
                "format": image.output_format.value,
                "width": image.width,
                "height": image.height,
                "metadataStatus": image.metadata_status,
                "sidecarStatus": image.sidecar_status.value,
                "sidecarFilename": image.sidecar_filename,
            }
            for image in outcome.saved_images
        ],
        "warnings": [
            {
                "code": metadata_scalar(warning.code) or "save_warning",
                "batchIndex": warning.batch_index,
            }
            for warning in outcome.warnings
        ],
    }
