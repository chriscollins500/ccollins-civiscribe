"""Immutable normalized ComfyUI prompt graph values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..domain import ScanIssue

type ScalarValue = None | bool | int | float | str
type FrozenValue = ScalarValue | tuple[FrozenValue, ...] | Mapping[str, FrozenValue]


@dataclass(frozen=True, slots=True)
class GraphLimits:
    """Security and resource bounds for untrusted prompt graphs."""

    max_nodes: int = 10_000
    max_inputs_per_node: int = 512
    max_edges: int = 100_000
    max_depth: int = 16
    max_nested_items: int = 250_000
    max_node_id_chars: int = 128
    max_class_type_chars: int = 256
    max_input_name_chars: int = 128
    max_string_chars: int = 1_000_000


DEFAULT_GRAPH_LIMITS = GraphLimits()


@dataclass(frozen=True, slots=True)
class PromptNode:
    """One normalized API-prompt node."""

    node_id: str
    class_type: str
    inputs: Mapping[str, FrozenValue]
    mode: int | None = None
    muted: bool = False
    bypassed: bool = False

    def input_value(self, name: str) -> FrozenValue:
        """Return a normalized input value or ``None`` when absent."""

        return self.inputs.get(name)


@dataclass(frozen=True, slots=True)
class LinkReference:
    """A source node output referenced by one consumer input."""

    source_node_id: str
    output_index: int


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """Directed data edge from a producer to a consumer."""

    source_node_id: str
    output_index: int
    consumer_node_id: str
    input_name: str


@dataclass(frozen=True, slots=True)
class PromptGraph:
    """Normalized prompt nodes plus sanitization and validation issues."""

    nodes: Mapping[str, PromptNode]
    issues: tuple[ScanIssue, ...] = ()

    def node(self, node_id: str) -> PromptNode | None:
        """Return a node by canonical ID."""

        return self.nodes.get(node_id)

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Return IDs in deterministic numeric-aware order."""

        return tuple(sorted(self.nodes, key=node_sort_key))


def node_sort_key(value: str) -> tuple[int, int, str]:
    """Sort numeric IDs numerically and all other IDs lexically."""

    if value.isdecimal():
        return (0, int(value), "")
    return (1, 0, value)


__all__ = [
    "DEFAULT_GRAPH_LIMITS",
    "FrozenValue",
    "GraphEdge",
    "GraphLimits",
    "LinkReference",
    "PromptGraph",
    "PromptNode",
    "ScalarValue",
    "node_sort_key",
]
