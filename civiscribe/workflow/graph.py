"""Typed graph index construction over normalized prompt nodes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..domain import IssueSeverity, ScanIssue
from .model import (
    DEFAULT_GRAPH_LIMITS,
    FrozenValue,
    GraphEdge,
    GraphLimits,
    LinkReference,
    PromptGraph,
    PromptNode,
    node_sort_key,
)
from .normalize import canonical_node_id

_LINK_FIELD_COUNT = 2


def as_link_reference(
    value: FrozenValue,
    *,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> LinkReference | None:
    """Parse one exact current ComfyUI ``[node_id, output_index]`` link."""

    if not isinstance(value, tuple) or len(value) != _LINK_FIELD_COUNT:
        return None
    raw_source, raw_output = value
    source = canonical_node_id(raw_source, limits)
    if (
        source is None
        or isinstance(raw_output, bool)
        or not isinstance(raw_output, int)
        or raw_output < 0
    ):
        return None
    return LinkReference(source, raw_output)


def iter_link_references(
    value: FrozenValue,
    *,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> Iterator[LinkReference]:
    """Yield links from a normalized scalar, tuple, or V3 structured input."""

    direct = as_link_reference(value, limits=limits)
    if direct is not None:
        yield direct
        return
    if isinstance(value, tuple):
        for item in value:
            yield from iter_link_references(item, limits=limits)
    elif isinstance(value, Mapping):
        for key in sorted(value):
            yield from iter_link_references(value[key], limits=limits)


@dataclass(frozen=True, slots=True)
class GraphIndex:
    """Immutable incoming and outgoing edge indexes."""

    nodes: Mapping[str, PromptNode]
    upstream_by_consumer: Mapping[str, tuple[GraphEdge, ...]]
    downstream_by_source: Mapping[str, tuple[GraphEdge, ...]]
    issues: tuple[ScanIssue, ...]

    def node(self, node_id: str) -> PromptNode | None:
        """Return one normalized node."""

        return self.nodes.get(node_id)

    def upstream_edges(self, node_id: str) -> tuple[GraphEdge, ...]:
        """Return producer edges for one consumer."""

        return self.upstream_by_consumer.get(node_id, ())

    def downstream_edges(self, node_id: str) -> tuple[GraphEdge, ...]:
        """Return consumer edges for one producer."""

        return self.downstream_by_source.get(node_id, ())


def _freeze_edges(
    values: dict[str, list[GraphEdge]],
) -> Mapping[str, tuple[GraphEdge, ...]]:
    return MappingProxyType(
        {
            node_id: tuple(
                sorted(
                    edges,
                    key=lambda edge: (
                        edge.input_name,
                        node_sort_key(edge.source_node_id),
                        edge.output_index,
                    ),
                )
            )
            for node_id, edges in values.items()
        }
    )


def build_graph_index(
    graph: PromptGraph,
    *,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> GraphIndex:
    """Index valid links in ``O(V + E)`` while rejecting missing sources."""

    upstream: dict[str, list[GraphEdge]] = {}
    downstream: dict[str, list[GraphEdge]] = {}
    issues = list(graph.issues)
    edge_count = 0
    seen_edges: set[tuple[str, int, str, str]] = set()

    for consumer_id in graph.node_ids:
        consumer = graph.nodes[consumer_id]
        for input_name in sorted(consumer.inputs):
            for reference in iter_link_references(
                consumer.inputs[input_name],
                limits=limits,
            ):
                edge_count += 1
                if edge_count > limits.max_edges:
                    issues.append(
                        ScanIssue(
                            "prompt_edge_limit_exceeded",
                            IssueSeverity.ERROR,
                            node_id=consumer_id,
                            input_name=input_name,
                        )
                    )
                    return GraphIndex(
                        graph.nodes,
                        MappingProxyType({}),
                        MappingProxyType({}),
                        tuple(issues),
                    )
                if reference.source_node_id not in graph.nodes:
                    issues.append(
                        ScanIssue(
                            "prompt_link_source_missing",
                            node_id=consumer_id,
                            input_name=input_name,
                        )
                    )
                    continue
                identity = (
                    reference.source_node_id,
                    reference.output_index,
                    consumer_id,
                    input_name,
                )
                if identity in seen_edges:
                    continue
                seen_edges.add(identity)
                edge = GraphEdge(
                    source_node_id=reference.source_node_id,
                    output_index=reference.output_index,
                    consumer_node_id=consumer_id,
                    input_name=input_name,
                )
                upstream.setdefault(consumer_id, []).append(edge)
                downstream.setdefault(reference.source_node_id, []).append(edge)

    return GraphIndex(
        graph.nodes,
        _freeze_edges(upstream),
        _freeze_edges(downstream),
        tuple(issues),
    )


__all__ = [
    "GraphIndex",
    "as_link_reference",
    "build_graph_index",
    "iter_link_references",
]
