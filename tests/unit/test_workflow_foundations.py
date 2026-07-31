from __future__ import annotations

import math
from types import MappingProxyType
from typing import cast

import pytest

from civiscribe.domain import IssueSeverity, ScanIssue
from civiscribe.workflow import (
    GraphLimits,
    PromptGraph,
    PromptNode,
    as_link_reference,
    build_graph_index,
    normalize_api_prompt,
    trace_active_upstream,
)
from civiscribe.workflow.graph import GraphIndex, iter_link_references
from civiscribe.workflow.model import FrozenValue, GraphEdge, node_sort_key
from civiscribe.workflow.normalize import canonical_node_id

MUTED_MODE = 2
EXPECTED_OUTPUT_INDEX = 3


def _codes(graph: PromptGraph) -> set[str]:
    return {issue.code for issue in graph.issues}


@pytest.mark.parametrize("value", [True, None, 1.5, object()])
def test_canonical_node_id_rejects_non_integer_non_string_values(value: object) -> None:
    assert canonical_node_id(value) is None


def test_canonical_node_id_preserves_safe_values_and_hashes_unsafe_values() -> None:
    assert canonical_node_id(12) == "12"
    assert canonical_node_id("node-a.1") == "node-a.1"
    assert canonical_node_id("") is None
    assert canonical_node_id("abcd", GraphLimits(max_node_id_chars=3)) is None
    unsafe = canonical_node_id(r"C:\private\workflow")
    assert unsafe is not None
    assert unsafe.startswith("node-")
    assert "private" not in unsafe


def test_normalizer_rejects_non_object_and_node_limit() -> None:
    assert _codes(normalize_api_prompt([])) == {"prompt_not_object"}
    limited = normalize_api_prompt(
        {"1": {}, "2": {}},
        limits=GraphLimits(max_nodes=1),
    )
    assert _codes(limited) == {"prompt_node_limit_exceeded"}


def test_normalizer_handles_invalid_duplicate_and_non_object_nodes() -> None:
    graph = normalize_api_prompt(
        {
            1.5: {"class_type": "Ignored"},
            1: {"class_type": "PrimitiveInt", "inputs": {"value": 1}},
            "1": {"class_type": "PrimitiveInt", "inputs": {"value": 2}},
            "2": "not a node",
        }
    )

    assert _codes(graph) == {
        "prompt_node_id_invalid",
        "prompt_node_id_duplicate",
        "prompt_node_not_object",
    }
    assert graph.node("1") is not None
    assert graph.node("missing") is None
    assert graph.node_ids == ("1",)


def test_normalizer_uses_type_fallback_and_sanitizes_invalid_class() -> None:
    graph = normalize_api_prompt(
        {
            "1": {"type": "PrimitiveInt", "inputs": {"value": 1}},
            "2": {"class_type": "bad/class", "inputs": {}},
        }
    )

    assert graph.nodes["1"].class_type == "PrimitiveInt"
    assert graph.nodes["2"].class_type == "UnknownNode"
    assert "prompt_node_class_invalid" in _codes(graph)


def test_normalizer_records_input_shape_name_and_count_errors() -> None:
    graph = normalize_api_prompt(
        {
            "1": {"class_type": "Node", "inputs": []},
            "2": {"class_type": "Node", "inputs": {"bad/name": 1}},
            "3": {"class_type": "Node", "inputs": {"a": 1, "b": 2}},
            "4": {"class_type": "Node", "inputs": {1: "invalid name type"}},
        },
        limits=GraphLimits(max_inputs_per_node=1),
    )

    assert _codes(graph) == {
        "prompt_node_inputs_not_object",
        "prompt_input_name_invalid",
        "prompt_input_limit_exceeded",
    }


def test_normalizer_freezes_supported_values_and_node_modes() -> None:
    decomposed = "e\u0301"
    graph = normalize_api_prompt(
        {
            "1": {
                "class_type": "Node",
                "mode": 2,
                "inputs": {
                    "none": None,
                    "boolean": True,
                    "integer": 4,
                    "number": 2.5,
                    "text": decomposed,
                    "array": [1, "two"],
                    "object": {"nested": False},
                },
            },
            "2": {"class_type": "Node", "mode": 4, "inputs": {}},
            "3": {
                "class_type": "Node",
                "mode": True,
                "muted": True,
                "bypassed": True,
                "inputs": {},
            },
        }
    )

    first = graph.nodes["1"]
    assert first.inputs["text"] == "é"
    assert first.inputs["array"] == (1, "two")
    assert first.inputs["object"] == MappingProxyType({"nested": False})
    assert first.mode == MUTED_MODE
    assert first.muted
    assert not first.bypassed
    assert graph.nodes["2"].bypassed
    assert graph.nodes["3"].mode is None
    assert graph.nodes["3"].muted
    assert graph.nodes["3"].bypassed


@pytest.mark.parametrize(
    ("value", "limits", "expected_code"),
    [
        ([[[1]]], GraphLimits(max_depth=1), "prompt_value_depth_limit_exceeded"),
        ([1, 2], GraphLimits(max_nested_items=1), "prompt_nested_item_limit_exceeded"),
        (math.inf, GraphLimits(), "prompt_value_nonfinite"),
        ("long", GraphLimits(max_string_chars=3), "prompt_string_limit_exceeded"),
        ({"bad/key": 1}, GraphLimits(), "prompt_object_key_invalid"),
        ({1, 2}, GraphLimits(), "prompt_value_type_unsupported"),
    ],
)
def test_normalizer_rejects_unsafe_or_oversized_nested_values(
    value: object,
    limits: GraphLimits,
    expected_code: str,
) -> None:
    graph = normalize_api_prompt(
        {"1": {"class_type": "Node", "inputs": {"value": value}}},
        limits=limits,
    )

    assert expected_code in _codes(graph)
    assert "value" not in graph.nodes["1"].inputs


@pytest.mark.parametrize(
    "value",
    [
        (),
        ("1",),
        ("1", 0, "extra"),
        (True, 0),
        ("1", True),
        ("1", 1.5),
        ("1", -1),
    ],
)
def test_link_parser_rejects_noncanonical_links(value: object) -> None:
    assert as_link_reference(cast_frozen(value)) is None


def test_link_parser_and_recursive_iterator_accept_current_link_shape() -> None:
    direct = as_link_reference(("2", 3))
    nested = tuple(iter_link_references((("2", 3), (("4", 0),))))
    structured = tuple(
        iter_link_references(
            MappingProxyType(
                {
                    "model_2": ("6", 1),
                    "model_1": MappingProxyType({"source": ("5", 0)}),
                }
            )
        )
    )

    assert direct is not None
    assert direct.source_node_id == "2"
    assert direct.output_index == EXPECTED_OUTPUT_INDEX
    assert [(item.source_node_id, item.output_index) for item in nested] == [
        ("2", 3),
        ("4", 0),
    ]
    assert [(item.source_node_id, item.output_index) for item in structured] == [
        ("5", 0),
        ("6", 1),
    ]
    assert tuple(iter_link_references("literal")) == ()


def test_graph_index_sorts_edges_and_exposes_both_directions() -> None:
    graph = normalize_api_prompt(
        {
            "10": {"class_type": "Source", "inputs": {}},
            "2": {"class_type": "Source", "inputs": {}},
            "20": {
                "class_type": "Consumer",
                "inputs": {"z": ["10", 1], "a": ["2", 0]},
            },
        }
    )
    index = build_graph_index(graph)

    assert [(edge.input_name, edge.source_node_id) for edge in index.upstream_edges("20")] == [
        ("a", "2"),
        ("z", "10"),
    ]
    assert index.downstream_edges("2")[0].consumer_node_id == "20"
    assert index.downstream_edges("missing") == ()
    assert index.node("missing") is None


def test_graph_index_reports_missing_source_and_deduplicates_repeated_edge() -> None:
    graph = normalize_api_prompt(
        {
            "1": {"class_type": "Source", "inputs": {}},
            "2": {
                "class_type": "Consumer",
                "inputs": {
                    "many": [["1", 0], ["1", 0]],
                    "missing": ["404", 0],
                },
            },
        }
    )
    index = build_graph_index(graph)

    assert len(index.upstream_edges("2")) == 1
    assert {issue.code for issue in index.issues} == {"prompt_link_source_missing"}


def test_graph_index_stops_at_configured_edge_limit() -> None:
    graph = normalize_api_prompt(
        {
            "1": {"class_type": "Source", "inputs": {}},
            "2": {
                "class_type": "Consumer",
                "inputs": {"first": ["1", 0], "second": ["1", 1]},
            },
        }
    )
    index = build_graph_index(graph, limits=GraphLimits(max_edges=1))

    assert index.upstream_by_consumer == {}
    assert index.downstream_by_source == {}
    assert "prompt_edge_limit_exceeded" in {issue.code for issue in index.issues}


def test_active_trace_validates_explicit_save_node_id_and_class() -> None:
    graph = normalize_api_prompt(
        {
            "1": {"class_type": "PrimitiveInt", "inputs": {"value": 1}},
            "2": {
                "class_type": "CCollins_CiviScribe_SaveImage",
                "inputs": {"images": ["1", 0]},
            },
        }
    )
    index = build_graph_index(graph)

    assert {issue.code for issue in trace_active_upstream(index, save_node_id="").issues} == {
        "save_node_id_invalid"
    }
    assert {issue.code for issue in trace_active_upstream(index, save_node_id="404").issues} == {
        "save_node_not_found"
    }
    assert {issue.code for issue in trace_active_upstream(index, save_node_id="1").issues} == {
        "save_node_class_mismatch"
    }


def test_active_trace_handles_multiple_image_edges_modes_and_cycle() -> None:
    graph = normalize_api_prompt(
        {
            "1": {
                "class_type": "Reroute",
                "mode": 2,
                "inputs": {"value": ["2", 0]},
            },
            "2": {
                "class_type": "Reroute",
                "mode": 4,
                "inputs": {"value": ["1", 0]},
            },
            "3": {"class_type": "PrimitiveInt", "inputs": {"value": 3}},
            "4": {
                "class_type": "CCollins_CiviScribe_SaveImage",
                "inputs": {"images": [["1", 0], ["3", 0]]},
            },
        }
    )
    active = trace_active_upstream(build_graph_index(graph))
    codes = {issue.code for issue in active.issues}

    assert active.node_ids == ("1", "2", "3")
    assert active.contains("2")
    assert not active.contains("4")
    assert {
        "save_images_link_ambiguous",
        "muted_node_on_active_path",
        "bypassed_node_on_active_path",
    } <= codes


def test_active_trace_tolerates_inconsistent_index_without_dereference() -> None:
    save = PromptNode(
        "save",
        "CCollins_CiviScribe_SaveImage",
        MappingProxyType({}),
    )
    edge = GraphEdge("missing", 0, "save", "images")
    index = GraphIndex(
        MappingProxyType({"save": save}),
        MappingProxyType({"save": (edge,)}),
        MappingProxyType({}),
        (ScanIssue("preexisting"),),
    )

    active = trace_active_upstream(index)

    assert active.node_ids == ("missing",)
    assert active.issues == (ScanIssue("preexisting"),)


def test_model_helpers_sort_numeric_ids_before_lexical_ids() -> None:
    graph = PromptGraph(
        MappingProxyType(
            {
                "node": PromptNode("node", "Node", MappingProxyType({})),
                "10": PromptNode("10", "Node", MappingProxyType({})),
                "2": PromptNode("2", "Node", MappingProxyType({})),
            }
        )
    )

    assert graph.node_ids == ("2", "10", "node")
    assert node_sort_key("node") == (1, 0, "node")
    assert ScanIssue("error", IssueSeverity.ERROR).severity is IssueSeverity.ERROR


def cast_frozen(value: object) -> FrozenValue:
    """Narrow project-authored malformed values for parser boundary tests."""

    return cast(FrozenValue, value)
