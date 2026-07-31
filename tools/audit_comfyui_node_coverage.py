"""Audit metadata-relevant ComfyUI node coverage without loading custom-node code.

The report is deliberately structural. It records class names, aggregate counts,
input names/types, scanner recognition, and generic workflow-root labels. It
never records widget values, prompts, model selections, workflow filenames,
source URLs, or filesystem paths.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import ssl
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from civiscribe.identity.civitai_client import create_tls_contexts  # noqa: E402
from civiscribe.workflow.classify import (  # noqa: E402
    compact_class,
    is_generated_latent_node,
    is_image_latent_node,
    is_image_source_node,
    is_known_active_node,
    is_sampler_node,
    is_text_encode_node,
    resource_input_specs,
)
from civiscribe.workflow.model import PromptNode  # noqa: E402

DEFAULT_OBJECT_INFO_URL = "http://127.0.0.1:8000/object_info"
DEFAULT_REGISTRY_COMFY_NODES_URL = "https://api.comfy.org/comfy-nodes"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_REGISTRY_PAGE_SIZE = 5_000
DEFAULT_REGISTRY_WORKERS = 16
DEFAULT_REGISTRY_MAX_RECORDS = 500_000

MAX_WORKFLOW_FILE_BYTES = 16 * 1024 * 1024
MAX_WORKFLOW_FILES_PER_ROOT = 5_000
MAX_DIRECTORY_DEPTH = 12
MAX_JSON_DEPTH = 64
MAX_JSON_ITEMS = 1_000_000
MAX_DOCUMENT_DEPTH = 8
MAX_DOCUMENTS_PER_FILE = 512
MAX_NODES_PER_FILE = 50_000
MAX_INPUTS_PER_NODE = 256
MAX_INPUT_SHAPES_PER_CLASS = 64
LINK_ITEM_COUNT = 2
MAX_REGISTRY_PAGE_SIZE = 10_000
MAX_REGISTRY_WORKERS = 32
MAX_REGISTRY_PAGES = 256
MAX_REGISTRY_RECORDS = 1_000_000
MAX_REGISTRY_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_REGISTRY_SCHEMA_BYTES = 512 * 1024
MIN_REGISTRY_TIMEOUT_SECONDS = 0.1
MAX_REGISTRY_TIMEOUT_SECONDS = 300.0

_SAFE_CLASS_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:+()\[\] -]{0,159}$")
_SAFE_INPUT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
_SAFE_TYPE_RE = re.compile(r"^[A-Za-z0-9_*?,.|:+()\[\] -]{1,127}$")
_SUBGRAPH_REFERENCE_CLASS_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)

_CLASS_FAMILY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "resource_loader",
        (
            "checkpoint",
            "controlnet",
            "diffusionmodel",
            "embedding",
            "gguf",
            "ipadapter",
            "lora",
            "modeloader",
            "modelloader",
            "textencoder",
            "unet",
            "upscalemodel",
            "upscaler",
            "vae",
        ),
    ),
    (
        "sampling",
        (
            "guider",
            "ksampler",
            "noise",
            "sampler",
            "scheduler",
            "sigmas",
        ),
    ),
    (
        "prompt_conditioning",
        (
            "cliptext",
            "conditioning",
            "guidance",
            "promptencode",
            "textencode",
        ),
    ),
    (
        "latent_source",
        (
            "emptylatent",
            "emptyresolution",
            "latentfromimage",
            "resolutioncalc",
            "vaeencode",
        ),
    ),
    (
        "routing",
        (
            "bypass",
            "chooser",
            "router",
            "select",
            "switch",
        ),
    ),
    (
        "save_output",
        (
            "exportimage",
            "previewimage",
            "saveimage",
            "savevideo",
        ),
    ),
)

_RELEVANT_OUTPUT_MARKERS = (
    "CLIP",
    "CONDITIONING",
    "CONTROL_NET",
    "GUIDER",
    "IPADAPTER",
    "LATENT",
    "MODEL",
    "NOISE",
    "SAMPLER",
    "SIGMAS",
    "UPSCALE_MODEL",
    "VAE",
)
_RESOURCE_OUTPUT_TYPES = frozenset(
    {
        "CLIP",
        "CONTROL_NET",
        "IPADAPTER",
        "MODEL",
        "STYLE_MODEL",
        "UPSCALE_MODEL",
        "VAE",
    }
)
_PROMPT_OUTPUT_TYPES = frozenset({"CONDITIONING"})
_LATENT_OUTPUT_TYPES = frozenset({"LATENT"})

_STRONG_ACTIONABLE_CLASS_MARKERS = (
    "checkpointloader",
    "cliploader",
    "controlnetloader",
    "emptylatent",
    "ipadapterloader",
    "ksampler",
    "loadcheckpoint",
    "loaddiffusionmodel",
    "loraloader",
    "promptencode",
    "samplercustom",
    "textencode",
    "textencoderloader",
    "unetloader",
    "upscalemodelloader",
    "vaeencode",
    "vaeloader",
)

_RESOURCE_SELECTOR_INPUT_MARKERS = (
    "checkpoint_name",
    "ckpt_name",
    "clip_name",
    "control_net_name",
    "controlnet_name",
    "diffusion_model",
    "embedding_name",
    "hypernetwork_name",
    "ipadapter_file",
    "ipadapter_name",
    "lora_name",
    "model_name",
    "style_model_name",
    "text_encoder",
    "unet_name",
    "upscale_model_name",
    "vae_name",
)
_SAMPLING_INPUT_NAMES = frozenset(
    {
        "cfg",
        "cfg_scale",
        "denoise",
        "guidance",
        "noise_seed",
        "sampler_name",
        "scheduler",
        "seed",
        "steps",
        "total_steps",
    }
)
_STRUCTURAL_SAMPLING_REQUIRED_INPUTS = frozenset({"sampler_name", "steps"})
_STRUCTURAL_SAMPLING_EXECUTION_INPUTS = frozenset(
    {
        "cfg",
        "cfg_scale",
        "denoise",
        "noise_seed",
        "scheduler",
        "seed",
    }
)
_STRUCTURAL_DIRECT_IMAGE_EXECUTION_INPUTS = frozenset(
    {
        "aspect_ratio",
        "cfg_scale",
        "guidance",
        "guidance_scale",
        "height",
        "model",
        "resolution",
        "seed",
        "size",
        "steps",
        "width",
    }
)
_PROMPT_INPUT_MARKERS = (
    "negative",
    "positive",
    "prompt",
    "text",
)
_DIRECT_IMAGE_PROMPT_INPUT_NAMES = frozenset(
    {
        "positive",
        "positive_prompt",
        "prompt",
    }
)
_DIMENSION_INPUT_NAMES = frozenset(
    {
        "batch_size",
        "height",
        "image",
        "latent_image",
        "width",
    }
)

_WRAPPER_KEYS = ("prompt", "workflow", "output", "graph", "graphs")
_REPORT_SCHEMA_VERSION = "2.2.0"

type CandidateTier = Literal[
    "actionable_metadata",
    "broad_heuristic",
    "other_observed",
]
type InputShape = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class WorkflowAuditLimits:
    """Hard limits for untrusted workflow-corpus input."""

    max_file_bytes: int = MAX_WORKFLOW_FILE_BYTES
    max_files_per_root: int = MAX_WORKFLOW_FILES_PER_ROOT
    max_directory_depth: int = MAX_DIRECTORY_DEPTH
    max_json_depth: int = MAX_JSON_DEPTH
    max_json_items: int = MAX_JSON_ITEMS
    max_document_depth: int = MAX_DOCUMENT_DEPTH
    max_documents_per_file: int = MAX_DOCUMENTS_PER_FILE
    max_nodes_per_file: int = MAX_NODES_PER_FILE
    max_inputs_per_node: int = MAX_INPUTS_PER_NODE
    max_shapes_per_class: int = MAX_INPUT_SHAPES_PER_CLASS


DEFAULT_WORKFLOW_LIMITS = WorkflowAuditLimits()


@dataclass(frozen=True, slots=True)
class RegistryFetchOptions:
    """Bounded controls for the optional official Registry catalog scan."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    page_size: int = DEFAULT_REGISTRY_PAGE_SIZE
    workers: int = DEFAULT_REGISTRY_WORKERS
    max_records: int = DEFAULT_REGISTRY_MAX_RECORDS


DEFAULT_REGISTRY_FETCH_OPTIONS = RegistryFetchOptions()


@dataclass(slots=True)
class _ClassObservation:
    count: int = 0
    shapes: Counter[InputShape] = field(default_factory=Counter)
    document_kinds: Counter[str] = field(default_factory=Counter)
    roots: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class _RegistryObservation:
    classes: dict[str, _ClassObservation] = field(default_factory=dict)
    output_types: dict[str, set[str]] = field(default_factory=dict)
    records_observed: int = 0
    invalid_class_names: int = 0
    invalid_schemas: int = 0
    deprecated_records: int = 0
    experimental_records: int = 0


@dataclass(frozen=True, slots=True)
class _RegistryReportStats:
    total_records_reported: int | None
    pages_requested: int
    pages_succeeded: int
    page_size: int


@dataclass(slots=True)
class _RootObservation:
    label: str
    files_discovered: int = 0
    files_parsed: int = 0
    files_skipped: int = 0
    document_kinds: Counter[str] = field(default_factory=Counter)
    node_occurrences: int = 0
    issue_counts: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class _FileScanState:
    root_label: str
    limits: WorkflowAuditLimits
    classes: dict[str, _ClassObservation]
    root: _RootObservation
    documents: int = 0
    nodes: int = 0


class _AuditLimitError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _safe_class_name(value: object) -> str | None:
    if not isinstance(value, str) or not value.isascii():
        return None
    if "/" in value or "\\" in value or ".." in value:
        return None
    return value if _SAFE_CLASS_RE.fullmatch(value) else None


def _safe_input_name(value: object) -> str | None:
    if not isinstance(value, str) or not value.isascii():
        return None
    if "/" in value or "\\" in value or ".." in value:
        return None
    return value if _SAFE_INPUT_RE.fullmatch(value) else None


def _safe_type_name(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return "COMBO"
    if not isinstance(value, str) or not value.isascii():
        return "UNKNOWN"
    if "/" in value or "\\" in value or ".." in value:
        return "UNKNOWN"
    return value if _SAFE_TYPE_RE.fullmatch(value) else "UNKNOWN"


def _input_types(payload: Mapping[str, Any]) -> dict[str, str]:
    input_schema = _mapping(payload.get("input"))
    result: dict[str, str] = {}
    for section_name in ("required", "optional", "hidden"):
        for raw_name, raw_spec in _mapping(input_schema.get(section_name)).items():
            input_name = _safe_input_name(raw_name)
            if input_name is None or not isinstance(raw_spec, (list, tuple)):
                continue
            descriptor = raw_spec[0] if raw_spec else None
            result[input_name] = _safe_type_name(descriptor)
    return dict(sorted(result.items()))


def _output_types(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                safe_type
                for raw_type in _strings(payload.get("output"))
                for safe_type in [_safe_type_name(raw_type)]
                if safe_type != "UNKNOWN"
            }
        )
    )


def _families(class_name: str, output_types: Iterable[str] = ()) -> tuple[str, ...]:
    compact = compact_class(class_name)
    families = {
        family
        for family, markers in _CLASS_FAMILY_MARKERS
        if any(marker in compact for marker in markers)
    }
    outputs = tuple(output_types)
    if any(
        any(marker in output.upper() for marker in _RELEVANT_OUTPUT_MARKERS) for output in outputs
    ):
        families.add("typed_metadata_producer")
    return tuple(sorted(families))


def _placeholder_node(class_name: str, input_names: Iterable[str]) -> PromptNode:
    return PromptNode(
        node_id="audit",
        class_type=class_name,
        inputs=MappingProxyType(dict.fromkeys(input_names, "audit-placeholder")),
    )


def _scanner_recognized(class_name: str, input_names: Iterable[str]) -> bool:
    node = _placeholder_node(class_name, input_names)
    return bool(
        is_known_active_node(node)
        or is_sampler_node(node)
        or is_text_encode_node(node)
        or is_generated_latent_node(node)
        or is_image_latent_node(node)
        or is_image_source_node(node)
        or resource_input_specs(node)
    )


def _candidate_tier(
    class_name: str,
    input_names: Iterable[str],
    output_types: Iterable[str] = (),
    *,
    input_type_pairs: Iterable[tuple[str, str]] = (),
) -> tuple[CandidateTier, tuple[str, ...], bool]:
    if _SUBGRAPH_REFERENCE_CLASS_RE.fullmatch(class_name):
        return "other_observed", ("ui_subgraph_reference",), True
    names = tuple(input_names)
    families = _families(class_name, output_types)
    recognized = _scanner_recognized(class_name, names)
    compact = compact_class(class_name)
    has_actionable_class = any(marker in compact for marker in _STRONG_ACTIONABLE_CLASS_MARKERS)
    family_set = set(families)
    lowered_names = {input_name.casefold() for input_name in names}
    normalized_outputs = {output_type.upper() for output_type in output_types}
    normalized_input_type_pairs = {
        (name.casefold(), input_type.upper()) for name, input_type in input_type_pairs
    }
    has_resource_selector = any(
        marker in input_name
        for input_name in lowered_names
        for marker in _RESOURCE_SELECTOR_INPUT_MARKERS
    )
    has_prompt_input = any(
        marker in input_name for input_name in lowered_names for marker in _PROMPT_INPUT_MARKERS
    )
    has_structural_sampling_contract = _STRUCTURAL_SAMPLING_REQUIRED_INPUTS.issubset(
        lowered_names
    ) and bool(lowered_names & _STRUCTURAL_SAMPLING_EXECUTION_INPUTS)
    has_structural_resource_contract = (
        bool(normalized_outputs & _RESOURCE_OUTPUT_TYPES) and has_resource_selector
    )
    has_structural_prompt_contract = (
        bool(normalized_outputs & _PROMPT_OUTPUT_TYPES) and has_prompt_input
    )
    has_structural_latent_contract = bool(normalized_outputs & _LATENT_OUTPUT_TYPES) and bool(
        lowered_names & _DIMENSION_INPUT_NAMES
    )
    has_structural_direct_image_contract = (
        "IMAGE" in normalized_outputs
        and any(
            name in _DIRECT_IMAGE_PROMPT_INPUT_NAMES and input_type == "STRING"
            for name, input_type in normalized_input_type_pairs
        )
        and bool(lowered_names & _STRUCTURAL_DIRECT_IMAGE_EXECUTION_INPUTS)
    )
    has_semantic_metadata_input = (
        ("resource_loader" in family_set and has_resource_selector)
        or (
            ("sampling" in family_set and bool(lowered_names & _SAMPLING_INPUT_NAMES))
            or has_structural_sampling_contract
        )
        or ("prompt_conditioning" in family_set and has_prompt_input)
        or ("latent_source" in family_set and bool(lowered_names & _DIMENSION_INPUT_NAMES))
        or has_structural_resource_contract
        or has_structural_prompt_contract
        or has_structural_latent_contract
        or has_structural_direct_image_contract
    )
    if has_actionable_class or has_semantic_metadata_input:
        return "actionable_metadata", families, recognized
    if families:
        return "broad_heuristic", families, recognized
    return "other_observed", (), recognized


def _shape_payload(shape: InputShape, count: int) -> dict[str, object]:
    return {
        "count": count,
        "inputs": [{"name": name, "type": input_type} for name, input_type in shape],
    }


def _observation_record(
    class_name: str,
    observation: _ClassObservation,
    *,
    output_types: Iterable[str] = (),
    source_count: int | None = None,
    max_shapes: int = MAX_INPUT_SHAPES_PER_CLASS,
) -> dict[str, object]:
    input_names = {input_name for shape in observation.shapes for input_name, _input_type in shape}
    input_type_pairs = {
        (input_name, input_type) for shape in observation.shapes for input_name, input_type in shape
    }
    tier, families, recognized = _candidate_tier(
        class_name,
        input_names,
        output_types,
        input_type_pairs=input_type_pairs,
    )
    ranked_shapes = sorted(
        observation.shapes.items(),
        key=lambda item: (-item[1], item[0]),
    )
    record: dict[str, object] = {
        "className": class_name,
        "count": observation.count,
        "classification": tier,
        "families": list(families),
        "scannerRecognized": recognized,
        "inputShapes": [
            _shape_payload(shape, count) for shape, count in ranked_shapes[:max_shapes]
        ],
        "truncatedInputShapeCount": max(0, len(ranked_shapes) - max_shapes),
    }
    if observation.document_kinds:
        record["documentKinds"] = dict(sorted(observation.document_kinds.items()))
    if observation.roots:
        record["roots"] = dict(sorted(observation.roots.items()))
    if source_count is not None:
        record["sourceCount"] = source_count
    return record


def _partition_records(
    records: Iterable[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    actionable: list[dict[str, object]] = []
    broad: list[dict[str, object]] = []
    other: list[dict[str, object]] = []
    for record in records:
        classification = record["classification"]
        if classification == "actionable_metadata":
            actionable.append(record)
        elif classification == "broad_heuristic":
            broad.append(record)
        else:
            other.append(record)
    return actionable, broad, other


def _recognized_count(records: Iterable[dict[str, object]]) -> int:
    return sum(bool(record["scannerRecognized"]) for record in records)


def analyze_object_info(payload: object) -> dict[str, object]:
    """Analyze sanitized live `/object_info` schema data."""

    if not isinstance(payload, Mapping):
        raise ValueError("object_info_not_object")
    invalid_class_names = 0
    records: list[dict[str, object]] = []
    for raw_class_name in sorted(payload, key=str):
        class_name = _safe_class_name(raw_class_name)
        if class_name is None:
            invalid_class_names += 1
            continue
        node_payload = _mapping(payload[raw_class_name])
        input_types = _input_types(node_payload)
        observation = _ClassObservation(
            count=1,
            shapes=Counter({tuple(input_types.items()): 1}),
        )
        records.append(
            _observation_record(
                class_name,
                observation,
                output_types=_output_types(node_payload),
            )
        )
    actionable, broad, other = _partition_records(records)
    unrecognized_actionable = [
        record for record in actionable if not bool(record["scannerRecognized"])
    ]
    return {
        "totalNodeClasses": len(payload),
        "safeNodeClasses": len(records),
        "invalidClassNameCount": invalid_class_names,
        "actionableMetadataNodeClasses": len(actionable),
        "recognizedActionableNodeClasses": len(actionable) - len(unrecognized_actionable),
        "unrecognizedActionableNodeClasses": len(unrecognized_actionable),
        "broadHeuristicCandidateClasses": len(broad),
        "recognizedBroadHeuristicClasses": _recognized_count(broad),
        "unrecognizedBroadHeuristicClasses": len(broad) - _recognized_count(broad),
        "otherObservedClasses": len(other),
        "actionableMetadataNodes": actionable,
        "broadHeuristicCandidates": broad,
        "otherNodes": other,
        "unrecognizedActionableNodes": unrecognized_actionable,
    }


def analyze_extension_map(payload: object) -> dict[str, object]:
    """Analyze a Manager/Registry class map without retaining source identifiers."""

    if not isinstance(payload, Mapping):
        raise ValueError("extension_node_map_not_object")
    class_source_counts: Counter[str] = Counter()
    invalid_class_names = 0
    for raw_entry in payload.values():
        if not isinstance(raw_entry, list) or not raw_entry:
            continue
        for raw_class_name in _strings(raw_entry[0]):
            class_name = _safe_class_name(raw_class_name)
            if class_name is None:
                invalid_class_names += 1
                continue
            class_source_counts[class_name] += 1

    records = []
    for class_name, source_count in sorted(class_source_counts.items()):
        observation = _ClassObservation(count=source_count)
        records.append(
            _observation_record(
                class_name,
                observation,
                source_count=source_count,
            )
        )
    actionable, broad, other = _partition_records(records)
    recognized_actionable = _recognized_count(actionable)
    return {
        "packageEntries": len(payload),
        "safeClassNames": len(records),
        "invalidClassNameCount": invalid_class_names,
        "actionableMetadataNodeClasses": len(actionable),
        "recognizedActionableNodeClasses": recognized_actionable,
        "unrecognizedActionableNodeClasses": len(actionable) - recognized_actionable,
        "broadHeuristicCandidateClasses": len(broad),
        "recognizedBroadHeuristicClasses": _recognized_count(broad),
        "unrecognizedBroadHeuristicClasses": len(broad) - _recognized_count(broad),
        "otherObservedClasses": len(other),
        "actionableMetadataNodes": actionable,
        "broadHeuristicCandidates": broad,
        "otherNodes": other,
    }


def _decode_registry_field(value: object) -> object:
    if isinstance(value, (Mapping, list)):
        return value
    if not isinstance(value, str):
        return None
    encoded = value.encode("utf-8", errors="ignore")
    if len(encoded) > MAX_REGISTRY_SCHEMA_BYTES:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, RecursionError):
        return None


def _registry_input_shape(payload: Mapping[str, Any]) -> InputShape | None:
    decoded = _decode_registry_field(payload.get("input_types"))
    if not isinstance(decoded, Mapping):
        return None
    return tuple(_input_types({"input": decoded}).items())


def _registry_output_types(payload: Mapping[str, Any]) -> tuple[str, ...] | None:
    decoded = _decode_registry_field(payload.get("return_types"))
    if not isinstance(decoded, list):
        return None
    return tuple(
        sorted(
            {
                safe_type
                for raw_type in decoded
                for safe_type in [_safe_type_name(raw_type)]
                if safe_type != "UNKNOWN"
            }
        )
    )


def _ingest_registry_entries(
    entries: object,
    observation: _RegistryObservation,
) -> None:
    if not isinstance(entries, list):
        raise ValueError("registry_comfy_nodes_not_array")
    for raw_entry in entries:
        observation.records_observed += 1
        entry = _mapping(raw_entry)
        if entry.get("deprecated") is True:
            observation.deprecated_records += 1
        if entry.get("experimental") is True:
            observation.experimental_records += 1
        class_name = _safe_class_name(entry.get("comfy_node_name"))
        if class_name is None:
            observation.invalid_class_names += 1
            continue
        shape = _registry_input_shape(entry)
        outputs = _registry_output_types(entry)
        if shape is None or outputs is None:
            observation.invalid_schemas += 1
        class_observation = observation.classes.setdefault(
            class_name,
            _ClassObservation(),
        )
        class_observation.count += 1
        if shape is not None:
            class_observation.shapes[shape] += 1
        if outputs:
            observation.output_types.setdefault(class_name, set()).update(outputs)


def _merge_registry_observation(
    target: _RegistryObservation,
    source: _RegistryObservation,
) -> None:
    target.records_observed += source.records_observed
    target.invalid_class_names += source.invalid_class_names
    target.invalid_schemas += source.invalid_schemas
    target.deprecated_records += source.deprecated_records
    target.experimental_records += source.experimental_records
    _merge_class_observations(target.classes, source.classes)
    for class_name, outputs in source.output_types.items():
        target.output_types.setdefault(class_name, set()).update(outputs)


def _registry_report(
    observation: _RegistryObservation,
    *,
    stats: _RegistryReportStats,
    issue_counts: Mapping[str, int] | None = None,
) -> dict[str, object]:
    records = [
        _observation_record(
            class_name,
            class_observation,
            output_types=observation.output_types.get(class_name, ()),
        )
        for class_name, class_observation in sorted(observation.classes.items())
    ]
    actionable, broad, other = _partition_records(records)
    unrecognized_actionable = [
        record for record in actionable if not bool(record["scannerRecognized"])
    ]
    total = (
        stats.total_records_reported
        if isinstance(stats.total_records_reported, int) and stats.total_records_reported >= 0
        else observation.records_observed
    )
    return {
        "source": "official_comfy_registry",
        "totalRecordsReported": total,
        "recordsObserved": observation.records_observed,
        "pageSize": stats.page_size,
        "pagesRequested": stats.pages_requested,
        "pagesSucceeded": stats.pages_succeeded,
        "complete": (
            stats.pages_requested == stats.pages_succeeded and observation.records_observed >= total
        ),
        "safeUniqueClassNames": len(records),
        "duplicateRecordCount": max(
            0,
            observation.records_observed - observation.invalid_class_names - len(records),
        ),
        "invalidClassNameCount": observation.invalid_class_names,
        "invalidSchemaCount": observation.invalid_schemas,
        "deprecatedRecordCount": observation.deprecated_records,
        "experimentalRecordCount": observation.experimental_records,
        "issueCounts": dict(sorted((issue_counts or {}).items())),
        "actionableMetadataNodeClasses": len(actionable),
        "recognizedActionableNodeClasses": len(actionable) - len(unrecognized_actionable),
        "unrecognizedActionableNodeClasses": len(unrecognized_actionable),
        "broadHeuristicCandidateClasses": len(broad),
        "recognizedBroadHeuristicClasses": _recognized_count(broad),
        "unrecognizedBroadHeuristicClasses": len(broad) - _recognized_count(broad),
        "otherObservedClasses": len(other),
        "actionableMetadataNodes": actionable,
        "broadHeuristicCandidates": broad,
        "otherNodes": other,
        "unrecognizedActionableNodes": unrecognized_actionable,
    }


def analyze_registry_comfy_nodes(payload: object) -> dict[str, object]:
    """Analyze one saved response from the official Registry class catalog."""

    if not isinstance(payload, Mapping):
        raise ValueError("registry_comfy_nodes_not_object")
    observation = _RegistryObservation()
    _ingest_registry_entries(payload.get("comfy_nodes"), observation)
    total = payload.get("total")
    return _registry_report(
        observation,
        stats=_RegistryReportStats(
            total_records_reported=total if isinstance(total, int) else None,
            pages_requested=1,
            pages_succeeded=1,
            page_size=observation.records_observed,
        ),
    )


def _looks_like_link(value: object) -> bool:
    if not isinstance(value, list) or len(value) != LINK_ITEM_COUNT:
        return False
    node_id, output_index = value
    valid_node_id = isinstance(node_id, str) or (
        isinstance(node_id, int) and not isinstance(node_id, bool)
    )
    return valid_node_id and isinstance(output_index, int) and not isinstance(output_index, bool)


def _literal_type(value: object) -> str:
    if value is None:
        result = "NULL"
    elif isinstance(value, bool):
        result = "BOOLEAN"
    elif isinstance(value, int):
        result = "INTEGER"
    elif isinstance(value, float):
        result = "FLOAT"
    elif isinstance(value, str):
        result = "STRING"
    elif _looks_like_link(value):
        result = "LINK"
    elif isinstance(value, list):
        result = "ARRAY"
    elif isinstance(value, Mapping):
        result = "OBJECT"
    else:
        result = "UNKNOWN"
    return result


def _api_input_shape(
    raw_inputs: object,
    state: _FileScanState,
) -> InputShape:
    if not isinstance(raw_inputs, Mapping):
        return ()
    if len(raw_inputs) > state.limits.max_inputs_per_node:
        state.root.issue_counts["node_input_limit_exceeded"] += 1
    shape: dict[str, str] = {}
    for raw_name, value in list(raw_inputs.items())[: state.limits.max_inputs_per_node]:
        input_name = _safe_input_name(raw_name)
        if input_name is None:
            state.root.issue_counts["unsafe_input_name_omitted"] += 1
            continue
        shape[input_name] = _literal_type(value)
    return tuple(sorted(shape.items()))


def _ui_input_shape(
    raw_inputs: object,
    state: _FileScanState,
) -> InputShape:
    if not isinstance(raw_inputs, list):
        return ()
    if len(raw_inputs) > state.limits.max_inputs_per_node:
        state.root.issue_counts["node_input_limit_exceeded"] += 1
    shape: dict[str, str] = {}
    for raw_input in raw_inputs[: state.limits.max_inputs_per_node]:
        input_payload = _mapping(raw_input)
        input_name = _safe_input_name(input_payload.get("name"))
        if input_name is None:
            state.root.issue_counts["unsafe_input_name_omitted"] += 1
            continue
        shape[input_name] = _safe_type_name(input_payload.get("type"))
    return tuple(sorted(shape.items()))


def _record_workflow_node(
    raw_class_name: object,
    shape: InputShape,
    document_kind: str,
    state: _FileScanState,
) -> None:
    class_name = _safe_class_name(raw_class_name)
    if class_name is None:
        state.root.issue_counts["unsafe_class_name_omitted"] += 1
        return
    observation = state.classes.setdefault(class_name, _ClassObservation())
    observation.count += 1
    observation.shapes[shape] += 1
    observation.document_kinds[document_kind] += 1
    observation.roots[state.root_label] += 1
    state.root.node_occurrences += 1


def _claim_workflow_node(state: _FileScanState) -> None:
    if state.nodes >= state.limits.max_nodes_per_file:
        raise _AuditLimitError("workflow_node_limit_exceeded")
    state.nodes += 1


def _api_nodes(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if "nodes" in payload:
        return []
    return [
        raw_node
        for raw_node in payload.values()
        if isinstance(raw_node, Mapping) and "class_type" in raw_node
    ]


def _scan_api_prompt(
    nodes: Sequence[Mapping[str, Any]],
    document_kind: str,
    state: _FileScanState,
) -> None:
    state.documents += 1
    state.root.document_kinds[document_kind] += 1
    if state.documents > state.limits.max_documents_per_file:
        raise _AuditLimitError("workflow_document_limit_exceeded")
    for node in nodes:
        _claim_workflow_node(state)
        class_name = _safe_class_name(node.get("class_type"))
        if class_name is None:
            state.root.issue_counts["unsafe_class_name_omitted"] += 1
            continue
        _record_workflow_node(
            class_name,
            _api_input_shape(node.get("inputs"), state),
            document_kind,
            state,
        )


def _scan_ui_workflow(
    raw_nodes: Sequence[object],
    document_kind: str,
    state: _FileScanState,
) -> None:
    state.documents += 1
    state.root.document_kinds[document_kind] += 1
    if state.documents > state.limits.max_documents_per_file:
        raise _AuditLimitError("workflow_document_limit_exceeded")
    for raw_node in raw_nodes:
        _claim_workflow_node(state)
        node = _mapping(raw_node)
        if not node:
            state.root.issue_counts["invalid_ui_node_omitted"] += 1
            continue
        class_name = _safe_class_name(node.get("type"))
        if class_name is None:
            state.root.issue_counts["unsafe_class_name_omitted"] += 1
            continue
        _record_workflow_node(
            class_name,
            _ui_input_shape(node.get("inputs"), state),
            document_kind,
            state,
        )


def _looks_like_document_mapping(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if isinstance(payload.get("nodes"), list) or _api_nodes(payload):
        return True
    definitions = _mapping(payload.get("definitions"))
    if isinstance(definitions.get("subgraphs"), (list, Mapping)):
        return True
    if isinstance(payload.get("subgraphs"), (list, Mapping)):
        return True
    return any(isinstance(payload.get(key), (list, Mapping)) for key in _WRAPPER_KEYS)


def _walk_subgraph_collections(
    payload: Mapping[str, Any],
    state: _FileScanState,
    depth: int,
) -> None:
    definitions = _mapping(payload.get("definitions"))
    for collection in (definitions.get("subgraphs"), payload.get("subgraphs")):
        if isinstance(collection, (list, Mapping)):
            _walk_documents(
                collection,
                state,
                depth=depth + 1,
                document_kind="subgraph",
            )


def _walk_wrappers_or_keyed_subgraphs(
    payload: Mapping[str, Any],
    state: _FileScanState,
    *,
    depth: int,
    document_kind: str,
) -> None:
    wrapper_found = False
    for key in _WRAPPER_KEYS:
        child = payload.get(key)
        if isinstance(child, (list, Mapping)):
            wrapper_found = True
            _walk_documents(
                child,
                state,
                depth=depth + 1,
                document_kind=document_kind,
            )
    if wrapper_found or document_kind != "subgraph":
        return

    # Some workflow versions store subgraphs in an ID-keyed object rather than
    # a list. Traverse only children that structurally resemble documents; IDs
    # and unrelated metadata remain uninspected and unreported.
    for child in payload.values():
        if _looks_like_document_mapping(child):
            _walk_documents(
                child,
                state,
                depth=depth + 1,
                document_kind="subgraph",
            )


def _walk_documents(
    payload: object,
    state: _FileScanState,
    *,
    depth: int = 0,
    document_kind: str = "workflow",
) -> None:
    if depth > state.limits.max_document_depth:
        raise _AuditLimitError("workflow_document_depth_exceeded")
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, (Mapping, list)):
                _walk_documents(
                    item,
                    state,
                    depth=depth + 1,
                    document_kind=document_kind,
                )
        return
    if not isinstance(payload, Mapping):
        return

    api_nodes = _api_nodes(payload)
    if api_nodes:
        api_kind = "api_subgraph" if document_kind == "subgraph" else "api_prompt"
        _scan_api_prompt(api_nodes, api_kind, state)
        return

    raw_nodes = payload.get("nodes")
    if isinstance(raw_nodes, list):
        ui_kind = "ui_subgraph" if document_kind == "subgraph" else "ui_workflow"
        _scan_ui_workflow(raw_nodes, ui_kind, state)

    _walk_subgraph_collections(payload, state, depth)

    if isinstance(raw_nodes, list):
        return
    _walk_wrappers_or_keyed_subgraphs(
        payload,
        state,
        depth=depth,
        document_kind=document_kind,
    )


def _validate_json_limits(payload: object, limits: WorkflowAuditLimits) -> None:
    stack: list[tuple[object, int]] = [(payload, 0)]
    item_count = 0
    while stack:
        value, depth = stack.pop()
        if depth > limits.max_json_depth:
            raise _AuditLimitError("json_depth_limit_exceeded")
        if isinstance(value, Mapping):
            item_count += len(value)
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            item_count += len(value)
            stack.extend((item, depth + 1) for item in value)
        if item_count > limits.max_json_items:
            raise _AuditLimitError("json_item_limit_exceeded")


def _read_workflow_json(path: Path, limits: WorkflowAuditLimits) -> object:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limits.max_file_bytes + 1)
    except OSError as error:
        raise _AuditLimitError("workflow_file_read_failed") from error
    if len(raw) > limits.max_file_bytes:
        raise _AuditLimitError("workflow_file_size_limit_exceeded")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise _AuditLimitError("workflow_json_invalid") from error
    _validate_json_limits(payload, limits)
    return payload


def _walk_json_files(
    root: Path,
    observation: _RootObservation,
    limits: WorkflowAuditLimits,
) -> list[Path]:
    discovered: list[Path] = []
    try:
        for current, raw_directories, raw_files in os.walk(root, followlinks=False):
            current_path = Path(current)
            try:
                depth = len(current_path.relative_to(root).parts)
            except ValueError:
                observation.issue_counts["workflow_root_escape_rejected"] += 1
                continue
            safe_directories = []
            for directory_name in sorted(raw_directories):
                directory = current_path / directory_name
                if directory.is_symlink():
                    observation.issue_counts["workflow_directory_symlink_skipped"] += 1
                elif depth >= limits.max_directory_depth:
                    observation.issue_counts["workflow_directory_depth_exceeded"] += 1
                else:
                    safe_directories.append(directory_name)
            raw_directories[:] = safe_directories
            for file_name in sorted(raw_files):
                candidate = current_path / file_name
                if candidate.suffix.casefold() != ".json":
                    continue
                if candidate.is_symlink():
                    observation.issue_counts["workflow_file_symlink_skipped"] += 1
                    continue
                discovered.append(candidate)
                if len(discovered) >= limits.max_files_per_root:
                    observation.issue_counts["workflow_file_count_limit_exceeded"] += 1
                    observation.files_discovered = len(discovered)
                    return discovered
    except OSError:
        observation.issue_counts["workflow_root_scan_failed"] += 1
    observation.files_discovered = len(discovered)
    return discovered


def _discover_workflow_files(
    root: Path,
    observation: _RootObservation,
    limits: WorkflowAuditLimits,
) -> list[Path]:
    if root.is_symlink():
        observation.issue_counts["workflow_root_symlink_rejected"] += 1
        return []
    if root.is_file():
        if root.suffix.casefold() != ".json":
            observation.issue_counts["workflow_root_not_json"] += 1
            return []
        observation.files_discovered = 1
        return [root]
    if not root.is_dir():
        observation.issue_counts["workflow_root_unavailable"] += 1
        return []
    return _walk_json_files(root, observation, limits)


def _root_payload(observation: _RootObservation) -> dict[str, object]:
    return {
        "rootLabel": observation.label,
        "filesDiscovered": observation.files_discovered,
        "filesParsed": observation.files_parsed,
        "filesSkipped": observation.files_skipped,
        "documentKinds": dict(sorted(observation.document_kinds.items())),
        "nodeOccurrences": observation.node_occurrences,
        "issueCounts": dict(sorted(observation.issue_counts.items())),
    }


def _workflow_limits_payload(limits: WorkflowAuditLimits) -> dict[str, int]:
    return {
        "maxFileBytes": limits.max_file_bytes,
        "maxFilesPerRoot": limits.max_files_per_root,
        "maxDirectoryDepth": limits.max_directory_depth,
        "maxJsonDepth": limits.max_json_depth,
        "maxJsonItems": limits.max_json_items,
        "maxDocumentDepth": limits.max_document_depth,
        "maxDocumentsPerFile": limits.max_documents_per_file,
        "maxNodesPerFile": limits.max_nodes_per_file,
        "maxInputsPerNode": limits.max_inputs_per_node,
        "maxInputShapesPerClass": limits.max_shapes_per_class,
    }


def _merge_class_observations(
    target: dict[str, _ClassObservation],
    source: Mapping[str, _ClassObservation],
) -> None:
    for class_name, source_observation in source.items():
        target_observation = target.setdefault(class_name, _ClassObservation())
        target_observation.count += source_observation.count
        target_observation.shapes.update(source_observation.shapes)
        target_observation.document_kinds.update(source_observation.document_kinds)
        target_observation.roots.update(source_observation.roots)


def _merge_file_observation(
    target: _RootObservation,
    source: _RootObservation,
) -> None:
    target.document_kinds.update(source.document_kinds)
    target.node_occurrences += source.node_occurrences
    target.issue_counts.update(source.issue_counts)


def analyze_workflow_roots(
    roots: Iterable[Path],
    *,
    limits: WorkflowAuditLimits = DEFAULT_WORKFLOW_LIMITS,
) -> dict[str, object]:
    """Analyze API prompts, UI workflows, and nested subgraphs under roots."""

    classes: dict[str, _ClassObservation] = {}
    root_results: list[dict[str, object]] = []
    for index, root in enumerate(roots, start=1):
        label = f"workflow-root-{index:03d}"
        root_observation = _RootObservation(label=label)
        files = _discover_workflow_files(root, root_observation, limits)
        for path in files:
            file_classes: dict[str, _ClassObservation] = {}
            file_observation = _RootObservation(label=label)
            state = _FileScanState(
                root_label=label,
                limits=limits,
                classes=file_classes,
                root=file_observation,
            )
            try:
                payload = _read_workflow_json(path, limits)
                _walk_documents(payload, state)
            except _AuditLimitError as error:
                root_observation.files_skipped += 1
                root_observation.issue_counts.update(file_observation.issue_counts)
                root_observation.issue_counts[error.code] += 1
                continue
            _merge_class_observations(classes, file_classes)
            _merge_file_observation(root_observation, file_observation)
            root_observation.files_parsed += 1
        root_results.append(_root_payload(root_observation))

    records = [
        _observation_record(
            class_name,
            observation,
            max_shapes=limits.max_shapes_per_class,
        )
        for class_name, observation in sorted(classes.items())
    ]
    actionable, broad, other = _partition_records(records)
    recognized_actionable = _recognized_count(actionable)
    return {
        "limits": _workflow_limits_payload(limits),
        "roots": root_results,
        "rootCount": len(root_results),
        "observedNodeClasses": len(records),
        "nodeOccurrences": sum(observation.count for observation in classes.values()),
        "actionableMetadataNodeClasses": len(actionable),
        "recognizedActionableNodeClasses": recognized_actionable,
        "unrecognizedActionableNodeClasses": len(actionable) - recognized_actionable,
        "broadHeuristicCandidateClasses": len(broad),
        "recognizedBroadHeuristicClasses": _recognized_count(broad),
        "unrecognizedBroadHeuristicClasses": len(broad) - _recognized_count(broad),
        "otherObservedClasses": len(other),
        "actionableMetadataNodes": actionable,
        "broadHeuristicCandidates": broad,
        "otherNodes": other,
    }


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _fetch_json(url: str, timeout_seconds: float) -> object:
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False, trust_env=False) as client:
        response = client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()


def _validate_official_registry_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.comfy.org"
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/comfy-nodes"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("official_registry_url_rejected")


def _registry_page_payload(
    client: httpx.Client,
    url: str,
    *,
    page: int,
    page_size: int,
) -> Mapping[str, Any]:
    response = client.get(
        url,
        params={"page": page, "pageSize": page_size},
        headers={
            "Accept": "application/json",
            "User-Agent": "CCollins-CiviScribe-Node-Audit/2.0",
        },
    )
    if response.status_code != httpx.codes.OK:
        raise ValueError("official_registry_http_error")
    if len(response.content) > MAX_REGISTRY_RESPONSE_BYTES:
        raise ValueError("official_registry_response_too_large")
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
        raise ValueError("official_registry_json_invalid") from error
    if not isinstance(payload, Mapping):
        raise ValueError("official_registry_response_not_object")
    return payload


def _summarize_registry_page(
    client: httpx.Client,
    url: str,
    *,
    page: int,
    page_size: int,
    remaining_records: int,
) -> tuple[_RegistryObservation, int | None]:
    payload = _registry_page_payload(
        client,
        url,
        page=page,
        page_size=page_size,
    )
    raw_entries = payload.get("comfy_nodes")
    if not isinstance(raw_entries, list):
        raise ValueError("registry_comfy_nodes_not_array")
    observation = _RegistryObservation()
    _ingest_registry_entries(raw_entries[:remaining_records], observation)
    total = payload.get("total")
    return observation, total if isinstance(total, int) else None


def _registry_client(
    options: RegistryFetchOptions,
    verify: bool | ssl.SSLContext,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    return httpx.Client(
        timeout=options.timeout_seconds,
        follow_redirects=False,
        trust_env=False,
        verify=verify,
        transport=transport,
        limits=httpx.Limits(
            max_connections=options.workers,
            max_keepalive_connections=options.workers,
        ),
    )


def _validate_registry_fetch_options(options: RegistryFetchOptions) -> None:
    if not 1 <= options.page_size <= MAX_REGISTRY_PAGE_SIZE:
        raise ValueError("official_registry_page_size_invalid")
    if not 1 <= options.workers <= MAX_REGISTRY_WORKERS:
        raise ValueError("official_registry_workers_invalid")
    if not 1 <= options.max_records <= MAX_REGISTRY_RECORDS:
        raise ValueError("official_registry_record_limit_invalid")
    if not (
        MIN_REGISTRY_TIMEOUT_SECONDS <= options.timeout_seconds <= MAX_REGISTRY_TIMEOUT_SECONDS
    ):
        raise ValueError("official_registry_timeout_invalid")


def _open_registry_client(
    url: str,
    options: RegistryFetchOptions,
    transport: httpx.BaseTransport | None = None,
) -> tuple[httpx.Client, Mapping[str, Any]]:
    client: httpx.Client | None = None
    first_page: Mapping[str, Any] | None = None
    verify_options: list[bool | ssl.SSLContext]
    if transport is not None:
        verify_options = [True]
    else:
        verify_options = [context for _label, context in create_tls_contexts()]
    for verify in verify_options:
        candidate = _registry_client(options, verify, transport)
        try:
            first_page = _registry_page_payload(
                candidate,
                url,
                page=1,
                page_size=options.page_size,
            )
        except (httpx.HTTPError, ValueError):
            candidate.close()
            continue
        client = candidate
        break
    if client is None or first_page is None:
        raise ValueError("official_registry_fetch_failed")
    return client, first_page


def _registry_page_plan(
    total_records: int,
    options: RegistryFetchOptions,
) -> tuple[int, Counter[str]]:
    total_pages = max(1, math.ceil(total_records / options.page_size))
    requested_pages = min(
        total_pages,
        MAX_REGISTRY_PAGES,
        math.ceil(options.max_records / options.page_size),
    )
    issues: Counter[str] = Counter()
    if requested_pages < total_pages:
        issues["registry_record_limit_reached"] += 1
    return requested_pages, issues


def _first_registry_observation(
    first_page: Mapping[str, Any],
    options: RegistryFetchOptions,
) -> _RegistryObservation:
    first_entries = first_page.get("comfy_nodes")
    if not isinstance(first_entries, list):
        raise ValueError("registry_comfy_nodes_not_array")
    observation = _RegistryObservation()
    _ingest_registry_entries(first_entries[: options.max_records], observation)
    return observation


def _collect_additional_registry_pages(
    client: httpx.Client,
    url: str,
    options: RegistryFetchOptions,
    requested_pages: int,
    expected_total: int,
) -> tuple[_RegistryObservation, int, Counter[str]]:
    combined = _RegistryObservation()
    issues: Counter[str] = Counter()
    if requested_pages <= 1:
        return combined, 0, issues

    succeeded = 0
    with ThreadPoolExecutor(
        max_workers=min(options.workers, requested_pages - 1),
        thread_name_prefix="civiscribe-registry-audit",
    ) as executor:
        futures = {
            executor.submit(
                _summarize_registry_page,
                client,
                url,
                page=page,
                page_size=options.page_size,
                remaining_records=max(
                    0,
                    min(
                        options.page_size,
                        options.max_records - ((page - 1) * options.page_size),
                    ),
                ),
            ): page
            for page in range(2, requested_pages + 1)
        }
        for future in as_completed(futures):
            try:
                page_observation, page_total = future.result()
            except (httpx.HTTPError, ValueError):
                issues["registry_page_fetch_failed"] += 1
                continue
            if page_total != expected_total:
                issues["registry_total_changed"] += 1
            _merge_registry_observation(combined, page_observation)
            succeeded += 1
    return combined, succeeded, issues


def fetch_registry_comfy_nodes(
    url: str = DEFAULT_REGISTRY_COMFY_NODES_URL,
    *,
    options: RegistryFetchOptions = DEFAULT_REGISTRY_FETCH_OPTIONS,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    """Fetch and structurally summarize the official Registry class catalog."""

    _validate_official_registry_url(url)
    _validate_registry_fetch_options(options)
    client, first_page = _open_registry_client(url, options, transport)

    try:
        raw_total = first_page.get("total")
        if not isinstance(raw_total, int) or raw_total < 0:
            raise ValueError("official_registry_total_invalid")
        requested_pages, issue_counts = _registry_page_plan(raw_total, options)
        combined = _first_registry_observation(first_page, options)
        additional, additional_succeeded, additional_issues = _collect_additional_registry_pages(
            client,
            url,
            options,
            requested_pages,
            raw_total,
        )
        _merge_registry_observation(combined, additional)
        issue_counts.update(additional_issues)

        return _registry_report(
            combined,
            stats=_RegistryReportStats(
                total_records_reported=raw_total,
                pages_requested=requested_pages,
                pages_succeeded=additional_succeeded + 1,
                page_size=options.page_size,
            ),
            issue_counts=issue_counts,
        )
    finally:
        client.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--object-info-url", default=None)
    source.add_argument("--object-info-file", type=Path)
    parser.add_argument("--extension-node-map", type=Path)
    registry_source = parser.add_mutually_exclusive_group()
    registry_source.add_argument(
        "--registry-comfy-nodes-url",
        nargs="?",
        const=DEFAULT_REGISTRY_COMFY_NODES_URL,
        default=None,
        help=(
            "Audit the official Registry class catalog. With no value, uses "
            "https://api.comfy.org/comfy-nodes."
        ),
    )
    registry_source.add_argument("--registry-comfy-nodes-file", type=Path)
    parser.add_argument(
        "--registry-page-size",
        type=int,
        default=DEFAULT_REGISTRY_PAGE_SIZE,
    )
    parser.add_argument(
        "--registry-workers",
        type=int,
        default=DEFAULT_REGISTRY_WORKERS,
    )
    parser.add_argument(
        "--registry-max-records",
        type=int,
        default=DEFAULT_REGISTRY_MAX_RECORDS,
    )
    parser.add_argument(
        "--workflow-root",
        action="append",
        type=Path,
        default=[],
        help="Workflow JSON file or directory; may be supplied more than once.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def _build_report(args: argparse.Namespace) -> dict[str, object]:
    if (
        args.object_info_url is None
        and args.object_info_file is None
        and args.extension_node_map is None
        and args.registry_comfy_nodes_url is None
        and args.registry_comfy_nodes_file is None
        and not args.workflow_root
    ):
        raise ValueError("at_least_one_audit_source_required")

    if args.object_info_url is not None:
        object_info = _fetch_json(args.object_info_url, args.timeout_seconds)
        live: dict[str, object] | None = analyze_object_info(object_info)
    elif args.object_info_file is not None:
        live = analyze_object_info(_read_json(args.object_info_file))
    else:
        live = None

    if args.registry_comfy_nodes_url is not None:
        official_registry: dict[str, object] | None = fetch_registry_comfy_nodes(
            args.registry_comfy_nodes_url,
            options=RegistryFetchOptions(
                timeout_seconds=args.timeout_seconds,
                page_size=args.registry_page_size,
                workers=args.registry_workers,
                max_records=args.registry_max_records,
            ),
        )
    elif args.registry_comfy_nodes_file is not None:
        official_registry = analyze_registry_comfy_nodes(_read_json(args.registry_comfy_nodes_file))
    else:
        official_registry = None

    return {
        "schemaName": "ccollins-civiscribe.comfyui-node-coverage-audit",
        "schemaVersion": _REPORT_SCHEMA_VERSION,
        "privacy": {
            "classNamesOnly": True,
            "genericWorkflowRootLabels": True,
            "inputValuesRecorded": False,
            "pathsRecorded": False,
            "promptsRecorded": False,
            "workflowFileNamesRecorded": False,
        },
        "live": live,
        "registry": (
            analyze_extension_map(_read_json(args.extension_node_map))
            if args.extension_node_map is not None
            else None
        ),
        "officialRegistry": official_registry,
        "workflowCorpus": (
            analyze_workflow_roots(args.workflow_root) if args.workflow_root else None
        ),
    }


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    try:
        report = _build_report(args)
    except ValueError as error:
        parser.error(str(error))

    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)

    live = _mapping(report["live"])
    if live:
        print(
            "coverage:"
            f" {live.get('recognizedActionableNodeClasses', 0)}/"
            f"{live.get('actionableMetadataNodeClasses', 0)} actionable live classes "
            "recognized",
            file=sys.stderr,
        )
    official_registry = _mapping(report["officialRegistry"])
    if official_registry:
        print(
            "official registry:"
            f" {official_registry.get('recordsObserved', 0)} records, "
            f"{official_registry.get('safeUniqueClassNames', 0)} safe unique classes",
            file=sys.stderr,
        )
    workflow_corpus = _mapping(report["workflowCorpus"])
    if workflow_corpus:
        print(
            "workflow corpus:"
            f" {workflow_corpus.get('nodeOccurrences', 0)} node occurrences across "
            f"{workflow_corpus.get('rootCount', 0)} generic roots",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
