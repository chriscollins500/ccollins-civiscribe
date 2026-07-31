"""Active upstream traversal rooted at the CiviScribe image input."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ..domain import IssueSeverity, ScanIssue
from .graph import GraphIndex
from .model import node_sort_key
from .normalize import canonical_node_id
from .routing import RoutingDecision, RoutingStatus, routed_upstream_edges

SAVE_NODE_CLASS = "CCollins_CiviScribe_SaveImage"


@dataclass(frozen=True, slots=True)
class ActiveGraph:
    """Nodes proven upstream of one CiviScribe ``images`` input."""

    save_node_id: str | None
    node_ids: tuple[str, ...]
    distance_from_save: Mapping[str, int]
    routing_decisions: tuple[RoutingDecision, ...]
    issues: tuple[ScanIssue, ...]
    consumed_output_indexes: Mapping[str, tuple[int, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def contains(self, node_id: str) -> bool:
        """Return whether a node contributes to the selected save path."""

        return node_id in self.distance_from_save


def _resolve_save_node(
    index: GraphIndex,
    explicit_node_id: str | None,
) -> tuple[str | None, tuple[ScanIssue, ...]]:
    if explicit_node_id is not None:
        return _resolve_explicit_save_node(index, explicit_node_id)

    candidates = tuple(
        sorted(
            (node.node_id for node in index.nodes.values() if node.class_type == SAVE_NODE_CLASS),
            key=node_sort_key,
        )
    )
    if not candidates:
        return None, (ScanIssue("save_node_not_found", IssueSeverity.ERROR),)
    if len(candidates) > 1:
        return None, (ScanIssue("save_node_ambiguous", IssueSeverity.ERROR),)
    return candidates[0], ()


def _resolve_explicit_save_node(
    index: GraphIndex,
    explicit_node_id: str,
) -> tuple[str | None, tuple[ScanIssue, ...]]:
    node_id = canonical_node_id(explicit_node_id)
    issue: ScanIssue | None = None
    if node_id is None:
        issue = ScanIssue("save_node_id_invalid", IssueSeverity.ERROR)
    else:
        node = index.node(node_id)
        if node is None:
            issue = ScanIssue("save_node_not_found", IssueSeverity.ERROR, node_id=node_id)
        elif node.class_type != SAVE_NODE_CLASS:
            issue = ScanIssue(
                "save_node_class_mismatch",
                IssueSeverity.ERROR,
                node_id=node_id,
            )
    return (None, (issue,)) if issue is not None else (node_id, ())


def trace_active_upstream(
    index: GraphIndex,
    *,
    save_node_id: str | None = None,
) -> ActiveGraph:
    """Traverse only data contributing to the selected saved image."""

    resolved_save_id, save_issues = _resolve_save_node(index, save_node_id)
    issues = [*index.issues, *save_issues]
    if resolved_save_id is None:
        return ActiveGraph(None, (), MappingProxyType({}), (), tuple(issues))

    image_edges = tuple(
        edge for edge in index.upstream_edges(resolved_save_id) if edge.input_name == "images"
    )
    if not image_edges:
        issues.append(
            ScanIssue(
                "save_images_link_missing",
                IssueSeverity.ERROR,
                node_id=resolved_save_id,
                input_name="images",
            )
        )
        return ActiveGraph(
            resolved_save_id,
            (),
            MappingProxyType({}),
            (),
            tuple(issues),
        )
    if len(image_edges) > 1:
        issues.append(
            ScanIssue(
                "save_images_link_ambiguous",
                node_id=resolved_save_id,
                input_name="images",
            )
        )

    queue: deque[tuple[str, int, str | None, int]] = deque(
        (edge.source_node_id, edge.output_index, None, 1) for edge in image_edges
    )
    distances: dict[str, int] = {}
    state_distances: dict[tuple[str, int, str | None], int] = {}
    consumed_outputs: dict[str, set[int]] = {}
    decisions: list[RoutingDecision] = []
    while queue:
        node_id, output_index, component, distance = queue.popleft()
        state = (node_id, output_index, component)
        known_state_distance = state_distances.get(state)
        if known_state_distance is not None and known_state_distance <= distance:
            continue
        state_distances[state] = distance
        known_distance = distances.get(node_id)
        if known_distance is None or distance < known_distance:
            distances[node_id] = distance
        consumed_outputs.setdefault(node_id, set()).add(output_index)
        node = index.node(node_id)
        if node is None:
            continue
        if node.muted:
            issues.append(ScanIssue("muted_node_on_active_path", node_id=node_id))
        if node.bypassed:
            issues.append(ScanIssue("bypassed_node_on_active_path", node_id=node_id))

        upstream, decision = routed_upstream_edges(
            index,
            node,
            output_index=output_index,
            component=component,
        )
        if decision is not None:
            decisions.append(decision)
            if decision.status is RoutingStatus.AMBIGUOUS:
                issues.append(ScanIssue("switch_selection_ambiguous", node_id=node_id))
        for route in upstream:
            queue.append(
                (
                    route.edge.source_node_id,
                    route.edge.output_index,
                    route.component,
                    distance + 1,
                )
            )

    ordered_ids = tuple(sorted(distances, key=node_sort_key))
    ordered_distances = MappingProxyType({node_id: distances[node_id] for node_id in ordered_ids})
    ordered_outputs = MappingProxyType(
        {
            node_id: tuple(sorted(consumed_outputs[node_id]))
            for node_id in ordered_ids
            if node_id in consumed_outputs
        }
    )
    return ActiveGraph(
        resolved_save_id,
        ordered_ids,
        ordered_distances,
        tuple(decisions),
        tuple(issues),
        ordered_outputs,
    )


__all__ = ["SAVE_NODE_CLASS", "ActiveGraph", "trace_active_upstream"]
