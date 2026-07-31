"""Bounded normalization for untrusted ComfyUI API prompt graphs."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from ..domain import IssueSeverity, ScanIssue
from .model import (
    DEFAULT_GRAPH_LIMITS,
    FrozenValue,
    GraphLimits,
    PromptGraph,
    PromptNode,
    node_sort_key,
)

_SAFE_NODE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_SCHEMA_NAME = re.compile(r"^[A-Za-z0-9_.:+() \-\[\]]+$")
_MUTED_NODE_MODE = 2
_BYPASSED_NODE_MODE = 4


class _FreezeError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class _FreezeBudget:
    remaining_items: int

    def consume(self, amount: int = 1) -> None:
        self.remaining_items -= amount
        if self.remaining_items < 0:
            raise _FreezeError("prompt_nested_item_limit_exceeded")


def canonical_node_id(value: object, limits: GraphLimits = DEFAULT_GRAPH_LIMITS) -> str | None:
    """Return a private-path-safe ID shared by nodes and link references."""

    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    text = unicodedata.normalize("NFC", str(value))
    if not text or len(text) > limits.max_node_id_chars:
        return None
    if _SAFE_NODE_ID.fullmatch(text) is not None:
        return text
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"node-{digest}"


def _schema_name(
    value: object,
    *,
    limit: int,
) -> str | None:
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFC", value).strip()
    if not text or len(text) > limit or _SAFE_SCHEMA_NAME.fullmatch(text) is None:
        return None
    return text


def _freeze_value(
    value: object,
    *,
    limits: GraphLimits,
    budget: _FreezeBudget,
    depth: int = 0,
) -> FrozenValue:
    if depth > limits.max_depth:
        raise _FreezeError("prompt_value_depth_limit_exceeded")
    budget.consume()
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _FreezeError("prompt_value_nonfinite")
        return value
    if isinstance(value, str):
        if len(value) > limits.max_string_chars:
            raise _FreezeError("prompt_string_limit_exceeded")
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_value(item, limits=limits, budget=budget, depth=depth + 1) for item in value
        )
    if isinstance(value, dict):
        items: list[tuple[str, FrozenValue]] = []
        for raw_key in sorted(value, key=str):
            key = _schema_name(raw_key, limit=limits.max_input_name_chars)
            if key is None:
                raise _FreezeError("prompt_object_key_invalid")
            items.append(
                (
                    key,
                    _freeze_value(
                        value[raw_key],
                        limits=limits,
                        budget=budget,
                        depth=depth + 1,
                    ),
                )
            )
        return MappingProxyType(dict(items))
    raise _FreezeError("prompt_value_type_unsupported")


def _node_mode(raw_node: dict[object, object]) -> int | None:
    mode = raw_node.get("mode")
    return mode if isinstance(mode, int) and not isinstance(mode, bool) else None


def _node_flags(raw_node: dict[object, object], mode: int | None) -> tuple[bool, bool]:
    muted = raw_node.get("muted") is True or mode == _MUTED_NODE_MODE
    bypassed = raw_node.get("bypassed") is True or mode == _BYPASSED_NODE_MODE
    return muted, bypassed


def _normalize_inputs(
    raw_inputs: object,
    *,
    node_id: str,
    limits: GraphLimits,
    budget: _FreezeBudget,
) -> tuple[Mapping[str, FrozenValue], tuple[ScanIssue, ...]]:
    if not isinstance(raw_inputs, dict):
        return (
            MappingProxyType({}),
            (ScanIssue("prompt_node_inputs_not_object", node_id=node_id),),
        )
    if len(raw_inputs) > limits.max_inputs_per_node:
        return (
            MappingProxyType({}),
            (
                ScanIssue(
                    "prompt_input_limit_exceeded",
                    IssueSeverity.ERROR,
                    node_id=node_id,
                ),
            ),
        )

    values: dict[str, FrozenValue] = {}
    issues: list[ScanIssue] = []
    for raw_name in sorted(raw_inputs, key=str):
        input_name = _schema_name(raw_name, limit=limits.max_input_name_chars)
        if input_name is None:
            issues.append(ScanIssue("prompt_input_name_invalid", node_id=node_id))
            continue
        try:
            values[input_name] = _freeze_value(
                raw_inputs[raw_name],
                limits=limits,
                budget=budget,
            )
        except _FreezeError as exc:
            issues.append(
                ScanIssue(
                    exc.code,
                    IssueSeverity.ERROR,
                    node_id=node_id,
                    input_name=input_name,
                )
            )
    return MappingProxyType(values), tuple(issues)


def normalize_api_prompt(
    prompt: object,
    *,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> PromptGraph:
    """Normalize a current ComfyUI API prompt without executing graph data."""

    if not isinstance(prompt, dict):
        return PromptGraph(
            MappingProxyType({}),
            (ScanIssue("prompt_not_object", IssueSeverity.ERROR),),
        )
    if len(prompt) > limits.max_nodes:
        return PromptGraph(
            MappingProxyType({}),
            (ScanIssue("prompt_node_limit_exceeded", IssueSeverity.ERROR),),
        )

    raw_prompt = cast(dict[object, object], prompt)
    budget = _FreezeBudget(limits.max_nested_items)
    nodes: dict[str, PromptNode] = {}
    issues: list[ScanIssue] = []
    for raw_id, raw_node_value in sorted(
        raw_prompt.items(),
        key=lambda item: node_sort_key(str(item[0])),
    ):
        node_id = canonical_node_id(raw_id, limits)
        if node_id is None:
            issues.append(ScanIssue("prompt_node_id_invalid", IssueSeverity.ERROR))
            continue
        if node_id in nodes:
            issues.append(
                ScanIssue(
                    "prompt_node_id_duplicate",
                    IssueSeverity.ERROR,
                    node_id=node_id,
                )
            )
            continue
        if not isinstance(raw_node_value, dict):
            issues.append(
                ScanIssue(
                    "prompt_node_not_object",
                    IssueSeverity.ERROR,
                    node_id=node_id,
                )
            )
            continue

        raw_node = cast(dict[object, object], raw_node_value)
        class_type = _schema_name(
            raw_node.get("class_type") or raw_node.get("type"),
            limit=limits.max_class_type_chars,
        )
        if class_type is None:
            class_type = "UnknownNode"
            issues.append(ScanIssue("prompt_node_class_invalid", node_id=node_id))
        inputs, input_issues = _normalize_inputs(
            raw_node.get("inputs", {}),
            node_id=node_id,
            limits=limits,
            budget=budget,
        )
        issues.extend(input_issues)
        mode = _node_mode(raw_node)
        muted, bypassed = _node_flags(raw_node, mode)
        nodes[node_id] = PromptNode(
            node_id=node_id,
            class_type=class_type,
            inputs=inputs,
            mode=mode,
            muted=muted,
            bypassed=bypassed,
        )

    return PromptGraph(MappingProxyType(nodes), tuple(issues))


__all__ = ["canonical_node_id", "normalize_api_prompt"]
