"""Conservative switch and router semantics for active graph traversal."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .classify import is_primitive_node
from .graph import GraphIndex, as_link_reference
from .model import FrozenValue, GraphEdge, PromptNode, ScalarValue

_BOOLEAN_SELECTORS = ("switch", "cond", "condition", "boolean")
_INDEX_SELECTORS = ("select", "input", "index", "idx")
_CONTROL_INPUTS = frozenset((*_BOOLEAN_SELECTORS, *_INDEX_SELECTORS, "sel_mode"))
_TRUE_BRANCHES = frozenset({"ontrue", "true", "ttvalue", "valuetrue", "inputtrue"})
_FALSE_BRANCHES = frozenset({"onfalse", "false", "ffvalue", "valuefalse", "inputfalse"})
_INDEXED_BRANCH = re.compile(
    r"^(?:input|model|clip|vae|image|images|latent|conditioning|text|"
    r"controlnet|mask|any|ctx|on|cond|value|pipe)(\d+)(?:opt)?$"
)
_WAS_AB_SWITCH_CLASSES = frozenset(
    {
        "clipinputswitch",
        "conditioninginputswitch",
        "controlnetmodelinputswitch",
        "latentinputswitch",
        "lorainputswitch",
        "modelinputswitch",
        "upscalemodelswitch",
        "vaeinputswitch",
    }
)
_SCALAR_SELECTOR_CLASSES = frozenset({"impactstringselector"})
_RUNTIME_PAYLOAD_SOURCE_CLASSES = frozenset(
    {
        "reloadimage",
        "reloadlatent",
        "reloadmodel",
    }
)
_MAX_SELECTOR_DEPTH = 8
_A1R_SEPARATE_LORA_CLASSES = frozenset(
    {
        "a1rsixloraloaderseparate",
        "a1rstackloraloaderseparate",
    }
)
_A1R_TWO_OUTPUT_LORA_CLASSES = frozenset(
    {
        "a1rsixloraloader2p",
        "a1rstackloraloader2p",
    }
)
_CONDITIONING_PAIR_LATENT_CLASSES = frozenset(
    {
        "addlatentguide",
        "hunyuanrefinerlatent",
        "ltxvaddguide",
        "ltxvaddguideadvanced",
        "ltxvaddguidemulti",
        "ltxvaddguidesfrombatch",
        "ltxvaddlatentguide",
        "ltxvcropguides",
        "ltxvimgtovideo",
        "ltxvimgtovideoadvanced",
        "ltxvsetaudiovideomaskbytime",
        "wan22funcontroltovideo",
        "wananimatetovideo",
        "wanhumoimagetovideo",
        "wanimagetovideosvipro",
        "wanscailtovideo",
        "wansoundimagetovideo",
        "wansoundimagetovideoextend",
        "wanvacetovideo",
    }
)
_MODEL_CONDITIONING_PAIR_LATENT_CLASSES = frozenset(
    {
        "clowninpaint",
        "clowninpaintsimple",
        "hunyuanvideoencodekeyframestocond",
    }
)
_CONDITIONING_BRANCH_PROJECTOR_CLASSES = frozenset(
    {
        *_CONDITIONING_PAIR_LATENT_CLASSES,
        *_MODEL_CONDITIONING_PAIR_LATENT_CLASSES,
        "ltxvreferenceaudio",
        "setprecisionuniversal",
        "wanmovenative",
        "wanphantomsubjecttovideo",
    }
)
_POSITIVE_BRANCH_INPUTS = frozenset({"cond_pos", "positive"})
_NEGATIVE_BRANCH_INPUTS = frozenset({"cond_neg", "negative"})


class RoutingStatus(StrEnum):
    """How a routing node was handled."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Explain which upstream inputs were traversed for one switch."""

    node_id: str
    status: RoutingStatus
    selected_input_names: tuple[str, ...] = ()
    selector_input_name: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class UpstreamRoute:
    """One selected upstream edge plus an optional pipe component."""

    edge: GraphEdge
    component: str | None = None


_OUTPUT_COMPONENTS: dict[str, dict[int, str]] = {
    **{
        class_name: {0: "positive", 1: "negative", 2: "latent"}
        for class_name in _CONDITIONING_PAIR_LATENT_CLASSES
    },
    **{
        class_name: {0: "model", 1: "positive", 2: "negative", 3: "latent"}
        for class_name in _MODEL_CONDITIONING_PAIR_LATENT_CLASSES
    },
    "condpassthrough": {0: "positive", 1: "negative"},
    "crmoduleinput": {
        0: "pipe",
        1: "model",
        2: "positive",
        3: "negative",
        4: "latent",
        5: "vae",
        6: "clip",
        7: "controlnet",
        8: "image",
        9: "seed",
    },
    "easypipeout": {
        0: "pipe",
        1: "model",
        2: "positive",
        3: "negative",
        4: "latent",
        5: "vae",
        6: "clip",
        7: "image",
        8: "seed",
    },
    "frombasicpipe": {
        0: "model",
        1: "clip",
        2: "vae",
        3: "positive",
        4: "negative",
    },
    "frombasicpipev2": {
        0: "pipe",
        1: "model",
        2: "clip",
        3: "vae",
        4: "positive",
        5: "negative",
    },
    "fromdetailerpipe": {
        0: "model",
        1: "clip",
        2: "vae",
        3: "positive",
        4: "negative",
    },
    "fromdetailerpipev2": {
        0: "pipe",
        1: "model",
        2: "clip",
        3: "vae",
        4: "positive",
        5: "negative",
    },
    "fromdetailerpipesdxl": {
        0: "pipe",
        1: "model",
        2: "clip",
        3: "vae",
        4: "positive",
        5: "negative",
        10: "refiner_model",
        11: "refiner_clip",
        12: "refiner_positive",
        13: "refiner_negative",
    },
    "ltxvreferenceaudio": {0: "model", 1: "positive", 2: "negative"},
    "setprecisionuniversal": {
        0: "positive",
        1: "negative",
        2: "sigmas",
        3: "latent",
    },
    "wanmovenative": {0: "positive"},
    "wanphantomsubjecttovideo": {
        0: "positive",
        1: "negative",
        2: "negative",
        3: "latent",
    },
}
_PIPE_EXTRACTOR_INPUTS = {
    "crmoduleinput": "pipe",
    "easypipeout": "pipe",
    "frombasicpipe": "basic_pipe",
    "frombasicpipev2": "basic_pipe",
    "fromdetailerpipe": "detailer_pipe",
    "fromdetailerpipev2": "detailer_pipe",
    "fromdetailerpipesdxl": "detailer_pipe",
}
_DIRECT_COMPONENT_BUILDERS = frozenset({"crmodulepipeloader", "tobasicpipe"})
_EDIT_COMPONENT_BUILDERS: dict[str, str] = {
    "crmoduleoutput": "pipe",
    "easypipeedit": "pipe",
    "easypipein": "pipe",
    "editbasicpipe": "basic_pipe",
}
_COMPONENT_INPUT_NAMES = {
    "clip": ("clip",),
    "controlnet": ("controlnet",),
    "image": ("image",),
    "latent": ("latent", "samples"),
    "model": ("model",),
    "negative": ("negative", "neg"),
    "positive": ("positive", "pos"),
    "refiner_clip": ("clip",),
    "refiner_model": ("model",),
    "refiner_negative": ("negative", "neg"),
    "refiner_positive": ("positive", "pos"),
    "seed": ("seed",),
    "vae": ("vae",),
}


def _compact(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _input_by_compact_name(
    node: PromptNode, names: tuple[str, ...]
) -> tuple[str, FrozenValue] | None:
    by_name = {_compact(name): (name, value) for name, value in node.inputs.items()}
    for name in names:
        found = by_name.get(_compact(name))
        if found is not None:
            return found
    return None


def _literal_bool(value: FrozenValue) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on", "enable", "enabled"}:
            return True
        if normalized in {"false", "0", "no", "off", "disable", "disabled"}:
            return False
    return None


def _literal_index(value: FrozenValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdecimal():
            return int(stripped)
    return None


def _is_switch_like(node: PromptNode) -> bool:
    compact = _compact(node.class_type)
    if compact in _SCALAR_SELECTOR_CLASSES:
        return False
    if "switch" in compact or "conditionalbranch" in compact:
        return True
    has_selector = _input_by_compact_name(
        node,
        (*_BOOLEAN_SELECTORS, *_INDEX_SELECTORS),
    )
    return has_selector is not None and any(
        marker in compact for marker in ("selector", "chooser", "router")
    )


def _branch_input_names(node: PromptNode) -> tuple[str, ...]:
    return tuple(
        name
        for name in node.inputs
        if _compact(name) not in {_compact(control) for control in _CONTROL_INPUTS}
    )


def _selected_boolean_names(node: PromptNode, selected: bool) -> tuple[str, ...]:
    if _compact(node.class_type) in _WAS_AB_SWITCH_CLASSES:
        selected_suffix = "a" if selected else "b"
        return tuple(
            name for name in _branch_input_names(node) if _compact(name).endswith(selected_suffix)
        )
    candidates = _TRUE_BRANCHES if selected else _FALSE_BRANCHES
    return tuple(name for name in _branch_input_names(node) if _compact(name) in candidates)


def _selected_index_names(node: PromptNode, selected: int) -> tuple[str, ...]:
    names: list[str] = []
    for name in _branch_input_names(node):
        match = _INDEXED_BRANCH.fullmatch(_compact(name))
        if match is not None and int(match.group(1)) == selected:
            names.append(name)
    return tuple(names)


def _selected_label_names(node: PromptNode, selected: str) -> tuple[str, ...]:
    compact_selected = _compact(selected)
    return tuple(name for name in _branch_input_names(node) if _compact(name) == compact_selected)


def _edges_for_inputs(
    index: GraphIndex,
    node: PromptNode,
    input_names: tuple[str, ...],
) -> tuple[GraphEdge, ...]:
    selected = set(input_names)
    return tuple(edge for edge in index.upstream_edges(node.node_id) if edge.input_name in selected)


def _ambiguous(
    index: GraphIndex,
    node: PromptNode,
    *,
    selector_name: str | None,
    reason: str,
) -> tuple[tuple[GraphEdge, ...], RoutingDecision]:
    return (
        index.upstream_edges(node.node_id),
        RoutingDecision(
            node.node_id,
            RoutingStatus.AMBIGUOUS,
            selector_input_name=selector_name,
            reason=reason,
        ),
    )


def _selector_de_imagenes_edges(
    index: GraphIndex,
    node: PromptNode,
) -> tuple[tuple[GraphEdge, ...], RoutingDecision] | None:
    if _compact(node.class_type) != "selectordeimagenes":
        return None

    active_slots: list[int] = []
    for slot in range(1, 13):
        input_name = f"on{slot}"
        if input_name not in node.inputs:
            continue
        selected = _literal_bool(
            _resolve_selector_value(
                index,
                node.inputs[input_name],
                preferred_input_names=(input_name, "value"),
            )
        )
        if selected is None:
            return _ambiguous(
                index,
                node,
                selector_name=input_name,
                reason="selector_value_unresolved",
            )
        if selected:
            active_slots.append(slot)

    if not active_slots:
        fallback = _resolve_selector_value(
            index,
            node.input_value("fallback"),
            preferred_input_names=("fallback", "value"),
        )
        if not isinstance(fallback, str):
            return _ambiguous(
                index,
                node,
                selector_name="fallback",
                reason="selector_value_unresolved",
            )
        if fallback.strip().casefold() != "slot1":
            return (
                (),
                RoutingDecision(
                    node.node_id,
                    RoutingStatus.RESOLVED,
                    selector_input_name="fallback",
                    reason="no_output_runtime_error",
                ),
            )
        active_slots.append(1)

    selected_names = tuple(
        name
        for slot in active_slots
        for name in (f"img{slot}", f"mask{slot}")
        if name in node.inputs
    )
    return (
        _edges_for_inputs(index, node, selected_names),
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            selected_input_names=selected_names,
            selector_input_name="enabled_slots",
        ),
    )


def _runtime_payload_source_edges(
    node: PromptNode,
) -> tuple[tuple[GraphEdge, ...], RoutingDecision] | None:
    if _compact(node.class_type) not in _RUNTIME_PAYLOAD_SOURCE_CLASSES:
        return None
    return (
        (),
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            reason="runtime_payload_provenance_unavailable",
        ),
    )


def _sage_special_edges(
    index: GraphIndex,
    node: PromptNode,
) -> tuple[tuple[GraphEdge, ...], RoutingDecision] | None:
    compact = _compact(node.class_type)
    if compact == "sagelogicalswitch":
        return _sage_logical_switch_edges(index, node)
    if compact == "sagetextswitch":
        return _sage_text_switch_edges(index, node)
    return _sage_model_picker_edges(index, node) if compact == "sagemultimodelpicker" else None


def _sage_logical_switch_edges(
    index: GraphIndex,
    node: PromptNode,
) -> tuple[tuple[GraphEdge, ...], RoutingDecision]:
    selected = _resolve_selector_value(
        index,
        node.input_value("condition"),
        preferred_input_names=("condition", "value"),
    )
    condition = _literal_bool(selected)
    if condition is None:
        return _ambiguous(
            index,
            node,
            selector_name="condition",
            reason="selector_value_unresolved",
        )
    selected_name = "true_value" if condition else "false_value"
    fallback_name = "false_value" if condition else "true_value"
    selected_edges = _edges_for_inputs(index, node, (selected_name,))
    used_name = selected_name
    reason = "sage_logical_branch_selected"
    if not selected_edges:
        selected_edges = _edges_for_inputs(index, node, (fallback_name,))
        used_name = fallback_name
        reason = "sage_logical_missing_branch_fallback"
    return (
        selected_edges,
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            selected_input_names=(used_name,) if selected_edges else (),
            selector_input_name="condition",
            reason=reason,
        ),
    )


def _sage_text_switch_edges(
    index: GraphIndex,
    node: PromptNode,
) -> tuple[tuple[GraphEdge, ...], RoutingDecision]:
    selected = _resolve_selector_value(
        index,
        node.input_value("active"),
        preferred_input_names=("active", "value"),
    )
    active = _literal_bool(selected)
    if active is None:
        return _ambiguous(
            index,
            node,
            selector_name="active",
            reason="selector_value_unresolved",
        )
    selected_edges = _edges_for_inputs(index, node, ("str",)) if active else ()
    return (
        selected_edges,
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            selected_input_names=("str",) if selected_edges else (),
            selector_input_name="active",
            reason="sage_text_enabled" if active else "sage_text_disabled",
        ),
    )


def _sage_model_picker_edges(
    index: GraphIndex,
    node: PromptNode,
) -> tuple[tuple[GraphEdge, ...], RoutingDecision]:
    selected = _resolve_selector_value(
        index,
        node.input_value("index"),
        preferred_input_names=("index", "value"),
    )
    selected_index = _literal_index(selected)
    values = node.input_value("model_template")
    if selected_index is None or not isinstance(values, Mapping):
        return _ambiguous(
            index,
            node,
            selector_name="index",
            reason="selector_value_unresolved",
        )
    wrapped_values = values.get("__value__")
    if isinstance(wrapped_values, Mapping):
        values = wrapped_values
    reference = as_link_reference(values.get(f"model_{selected_index}"))
    if reference is None:
        return (
            (),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selector_input_name="index",
                reason="sage_model_index_unconnected",
            ),
        )
    selected_edges = tuple(
        edge
        for edge in index.upstream_edges(node.node_id)
        if edge.input_name == "model_template"
        and edge.source_node_id == reference.source_node_id
        and edge.output_index == reference.output_index
    )
    return (
        selected_edges,
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            selected_input_names=(f"model_template.model_{selected_index}",),
            selector_input_name="index",
            reason="sage_model_index_selected",
        ),
    )


def _literal_scalar(value: FrozenValue) -> ScalarValue:
    if as_link_reference(value) is not None:
        return None
    return value if value is None or isinstance(value, (bool, int, float, str)) else None


def _resolve_selector_value(
    index: GraphIndex,
    value: FrozenValue,
    *,
    preferred_input_names: tuple[str, ...],
    seen: frozenset[str] = frozenset(),
    depth: int = 0,
) -> ScalarValue:
    literal = _literal_scalar(value)
    if literal is not None:
        return literal
    if depth >= _MAX_SELECTOR_DEPTH:
        return None
    reference = as_link_reference(value)
    if reference is None or reference.source_node_id in seen:
        return None
    node = index.node(reference.source_node_id)
    if node is None or not is_primitive_node(node):
        return None
    visited = seen | {reference.source_node_id}
    candidate_names = tuple(dict.fromkeys((*preferred_input_names, "value", *node.inputs)))
    for input_name in candidate_names:
        if input_name not in node.inputs:
            continue
        candidate = _resolve_selector_value(
            index,
            node.inputs[input_name],
            preferred_input_names=preferred_input_names,
            seen=visited,
            depth=depth + 1,
        )
        if candidate is not None:
            return candidate
    return None


def _selected_switch_edges(
    index: GraphIndex,
    node: PromptNode,
) -> tuple[tuple[GraphEdge, ...], RoutingDecision | None]:
    if not _is_switch_like(node):
        return index.upstream_edges(node.node_id), None

    selector = _input_by_compact_name(node, _BOOLEAN_SELECTORS)
    selector_kind = "boolean"
    if selector is None:
        selector = _input_by_compact_name(node, _INDEX_SELECTORS)
        selector_kind = "index_or_label"
    if selector is None:
        return _ambiguous(index, node, selector_name=None, reason="selector_missing")

    selector_name, selector_value = selector
    resolved_selector = _resolve_selector_value(
        index,
        selector_value,
        preferred_input_names=(selector_name, "value"),
    )
    if resolved_selector is None and as_link_reference(selector_value) is not None:
        return _ambiguous(
            index,
            node,
            selector_name=selector_name,
            reason="selector_linked",
        )

    selected_names: tuple[str, ...] = ()
    if selector_kind == "boolean":
        selected_bool = _literal_bool(resolved_selector)
        if selected_bool is not None:
            selected_names = _selected_boolean_names(node, selected_bool)
    else:
        selected_index = _literal_index(resolved_selector)
        if selected_index is not None:
            selected_names = _selected_index_names(node, selected_index)
        elif isinstance(resolved_selector, str):
            selected_names = _selected_label_names(node, resolved_selector)

    if not selected_names:
        return _ambiguous(
            index,
            node,
            selector_name=selector_name,
            reason="selector_value_unresolved",
        )

    selected_edges = _edges_for_inputs(index, node, selected_names)
    if not selected_edges:
        return _ambiguous(
            index,
            node,
            selector_name=selector_name,
            reason="selected_input_not_linked",
        )
    return (
        selected_edges,
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            selected_input_names=selected_names,
            selector_input_name=selector_name,
        ),
    )


def selected_upstream_edges(
    index: GraphIndex,
    node: PromptNode,
) -> tuple[tuple[GraphEdge, ...], RoutingDecision | None]:
    """Return proven active switch inputs or all inputs when selection is unclear."""

    selected = _selector_de_imagenes_edges(index, node)
    if selected is None:
        selected = _runtime_payload_source_edges(node)
    if selected is None:
        selected = _sage_special_edges(index, node)
    return selected if selected is not None else _selected_switch_edges(index, node)


def _first_linked_component_input(
    index: GraphIndex,
    node: PromptNode,
    component: str,
) -> tuple[GraphEdge, ...]:
    names = _COMPONENT_INPUT_NAMES.get(component, ())
    for name in names:
        selected = _edges_for_inputs(index, node, (name,))
        if selected:
            return selected
    return ()


def _component_routes(
    index: GraphIndex,
    node: PromptNode,
    *,
    output_index: int,
    component: str | None,
) -> tuple[tuple[UpstreamRoute, ...], RoutingDecision] | None:
    compact = _compact(node.class_type)
    selected_component = component or _OUTPUT_COMPONENTS.get(compact, {}).get(output_index)
    selected = _static_list_component_routes(index, node, compact, selected_component)
    if selected is not None:
        return selected
    if compact == "reencodelatentpipe":
        return _reencode_latent_pipe_routes(index, node)
    if selected_component is None or selected_component == "pipe":
        return None
    selected = _pipe_component_routes(index, node, compact, selected_component)
    if selected is not None:
        return selected
    return _pipe_conversion_routes(
        index,
        node,
        compact,
        selected_component,
        output_index=output_index,
    )


def _numbered_slot_sort_key(input_name: str) -> tuple[str, int, str]:
    compact = _compact(input_name)
    match = re.search(r"(\d+)$", compact)
    if match is None:
        return compact, -1, compact
    return compact[: match.start()], int(match.group(1)), compact


def _static_list_component_routes(
    index: GraphIndex,
    node: PromptNode,
    compact: str,
    selected_component: str | None,
) -> tuple[tuple[UpstreamRoute, ...], RoutingDecision] | None:
    if compact not in {"impactmakeanylist", "impactmakeimagelist"} or (
        selected_component is None or not selected_component.startswith("list_index:")
    ):
        return None
    selected_index = int(selected_component.partition(":")[2])
    candidates = tuple(
        name
        for name, value in sorted(
            node.inputs.items(),
            key=lambda item: _numbered_slot_sort_key(item[0]),
        )
        if value is not None and _compact(name).startswith(("value", "image"))
    )
    if not candidates:
        return (
            (),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                reason="empty_static_list",
            ),
        )
    normalized_index = (
        len(candidates) - 1
        if selected_index >= len(candidates) or selected_index < -len(candidates)
        else selected_index % len(candidates)
    )
    selected_name = candidates[normalized_index]
    edges = _edges_for_inputs(index, node, (selected_name,))
    return (
        tuple(UpstreamRoute(edge) for edge in edges),
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            selected_input_names=(selected_name,),
            selector_input_name="index",
            reason="static_list_item_selected",
        ),
    )


def _reencode_latent_pipe_routes(
    index: GraphIndex,
    node: PromptNode,
) -> tuple[tuple[UpstreamRoute, ...], RoutingDecision]:
    routes = tuple(
        UpstreamRoute(
            edge,
            "vae" if edge.input_name in {"input_basic_pipe", "output_basic_pipe"} else None,
        )
        for edge in index.upstream_edges(node.node_id)
        if edge.input_name in {"samples", "input_basic_pipe", "output_basic_pipe"}
    )
    return (
        routes,
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            selected_input_names=tuple(route.edge.input_name for route in routes),
            reason="two_vae_pipe_projection",
        ),
    )


def _pipe_component_routes(
    index: GraphIndex,
    node: PromptNode,
    compact: str,
    selected_component: str,
) -> tuple[tuple[UpstreamRoute, ...], RoutingDecision] | None:

    extractor_input = _PIPE_EXTRACTOR_INPUTS.get(compact)
    if extractor_input is not None:
        edges = _edges_for_inputs(index, node, (extractor_input,))
        return (
            tuple(UpstreamRoute(edge, selected_component) for edge in edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selected_input_names=(extractor_input,),
                reason="output_component_projection",
            ),
        )

    conditioning_routes = _conditioning_component_routes(
        index,
        node,
        compact,
        selected_component,
    )
    if conditioning_routes is not None:
        return conditioning_routes

    if compact in _DIRECT_COMPONENT_BUILDERS:
        edges = _first_linked_component_input(index, node, selected_component)
        return (
            tuple(UpstreamRoute(edge) for edge in edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selected_input_names=tuple(edge.input_name for edge in edges),
                reason="pipe_component_projection",
            ),
        )

    carrier_input = _EDIT_COMPONENT_BUILDERS.get(compact)
    if carrier_input is not None:
        override_edges = _first_linked_component_input(index, node, selected_component)
        if override_edges:
            routes = tuple(UpstreamRoute(edge) for edge in override_edges)
        else:
            routes = tuple(
                UpstreamRoute(edge, selected_component)
                for edge in _edges_for_inputs(index, node, (carrier_input,))
            )
        return (
            routes,
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selected_input_names=tuple(route.edge.input_name for route in routes),
                reason="pipe_override_projection",
            ),
        )
    return None


def _conditioning_component_routes(
    index: GraphIndex,
    node: PromptNode,
    compact: str,
    selected_component: str,
) -> tuple[tuple[UpstreamRoute, ...], RoutingDecision] | None:
    if compact == "condpassthrough":
        edges = _first_linked_component_input(index, node, selected_component)
        return (
            tuple(UpstreamRoute(edge) for edge in edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selected_input_names=tuple(edge.input_name for edge in edges),
                reason="conditioning_output_projection",
            ),
        )

    if compact in _CONDITIONING_BRANCH_PROJECTOR_CLASSES:
        excluded_inputs: frozenset[str]
        if selected_component == "positive":
            excluded_inputs = _NEGATIVE_BRANCH_INPUTS
        elif selected_component == "negative":
            excluded_inputs = _POSITIVE_BRANCH_INPUTS
        elif selected_component in {"latent", "sigmas"}:
            excluded_inputs = _POSITIVE_BRANCH_INPUTS | _NEGATIVE_BRANCH_INPUTS
        else:
            return None
        edges = tuple(
            edge
            for edge in index.upstream_edges(node.node_id)
            if edge.input_name.casefold() not in excluded_inputs
        )
        return (
            tuple(UpstreamRoute(edge) for edge in edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selected_input_names=tuple(edge.input_name for edge in edges),
                reason="conditioning_branch_projection",
            ),
        )
    return None


def _pipe_conversion_routes(
    index: GraphIndex,
    node: PromptNode,
    compact: str,
    selected_component: str,
    *,
    output_index: int,
) -> tuple[tuple[UpstreamRoute, ...], RoutingDecision] | None:
    if compact in {"anypipetobasic", "easypipetobasicpipe"}:
        input_name = "any_pipe" if compact == "anypipetobasic" else "pipe"
        edges = _edges_for_inputs(index, node, (input_name,))
        return (
            tuple(UpstreamRoute(edge, selected_component) for edge in edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selected_input_names=(input_name,),
                reason="pipe_component_projection",
            ),
        )

    if compact == "basicpipetodetailerpipe":
        edges = _edges_for_inputs(index, node, ("basic_pipe",))
        return (
            tuple(UpstreamRoute(edge, selected_component) for edge in edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selected_input_names=("basic_pipe",),
                reason="detailer_pipe_component_projection",
            ),
        )

    if compact == "basicpipetodetailerpipesdxl":
        refiner = selected_component.startswith("refiner_")
        input_name = "refiner_basic_pipe" if refiner else "base_basic_pipe"
        next_component = selected_component.removeprefix("refiner_")
        edges = _edges_for_inputs(index, node, (input_name,))
        return (
            tuple(UpstreamRoute(edge, next_component) for edge in edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selected_input_names=(input_name,),
                reason="sdxl_detailer_pipe_component_projection",
            ),
        )

    if compact == "detailerpipetobasicpipe":
        next_component = (
            f"refiner_{selected_component}" if output_index == 1 else selected_component
        )
        edges = _edges_for_inputs(index, node, ("detailer_pipe",))
        return (
            tuple(UpstreamRoute(edge, next_component) for edge in edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.RESOLVED,
                selected_input_names=("detailer_pipe",),
                reason="detailer_pipe_component_projection",
            ),
        )
    return None


def _impact_nth_item_routes(
    index: GraphIndex,
    node: PromptNode,
) -> tuple[tuple[UpstreamRoute, ...], RoutingDecision] | None:
    if _compact(node.class_type) != "impactselectnthitemofanylist":
        return None
    selected_index = _literal_index(
        _resolve_selector_value(
            index,
            node.input_value("index"),
            preferred_input_names=("index", "value"),
        )
    )
    list_edges = _edges_for_inputs(index, node, ("any_list",))
    if selected_index is None or len(list_edges) != 1:
        return (
            tuple(UpstreamRoute(edge) for edge in list_edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.AMBIGUOUS,
                selector_input_name="index",
                reason="list_index_or_source_unresolved",
            ),
        )
    source = index.node(list_edges[0].source_node_id)
    if source is None or _compact(source.class_type) not in {
        "impactmakeanylist",
        "impactmakeimagelist",
    }:
        return (
            tuple(UpstreamRoute(edge) for edge in list_edges),
            RoutingDecision(
                node.node_id,
                RoutingStatus.AMBIGUOUS,
                selector_input_name="index",
                reason="list_source_runtime_opaque",
            ),
        )
    return (
        (UpstreamRoute(list_edges[0], f"list_index:{selected_index}"),),
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            selected_input_names=("any_list",),
            selector_input_name="index",
            reason="static_list_selection",
        ),
    )


def _a1r_lora_routes(
    index: GraphIndex,
    node: PromptNode,
    *,
    output_index: int,
) -> tuple[tuple[UpstreamRoute, ...], RoutingDecision] | None:
    compact = _compact(node.class_type)
    selector_name: str
    selector_value: int | bool | None
    if compact in _A1R_SEPARATE_LORA_CLASSES:
        selector_name = "separate_mode"
        selector_value = _literal_bool(
            _resolve_selector_value(
                index,
                node.input_value(selector_name),
                preferred_input_names=(selector_name, "value"),
            )
        )
        selected_source = 2 if selector_value is True else (1 if selector_value is False else None)
    elif compact in _A1R_TWO_OUTPUT_LORA_CLASSES:
        output_number = 1 if output_index in {0, 1} else 2
        selector_name = f"output{output_number}_source"
        selector_value = _literal_index(
            _resolve_selector_value(
                index,
                node.input_value(selector_name),
                preferred_input_names=(selector_name, "value"),
            )
        )
        selected_source = selector_value if selector_value in {1, 2} else None
    else:
        return None

    if selected_source is None:
        return None
    suffix = "a" if selected_source == 1 else "b"
    selected_names = tuple(
        name for name in (f"model_{suffix}", f"clip_{suffix}", "lora_stack") if name in node.inputs
    )
    edges = _edges_for_inputs(index, node, selected_names)
    return (
        tuple(UpstreamRoute(edge) for edge in edges),
        RoutingDecision(
            node.node_id,
            RoutingStatus.RESOLVED,
            selected_input_names=selected_names,
            selector_input_name=selector_name,
            reason="a1r_lora_source_selected",
        ),
    )


def routed_upstream_edges(
    index: GraphIndex,
    node: PromptNode,
    *,
    output_index: int,
    component: str | None = None,
) -> tuple[tuple[UpstreamRoute, ...], RoutingDecision | None]:
    """Select upstream edges while preserving known pipe output semantics."""

    selected = _impact_nth_item_routes(index, node)
    if selected is None:
        selected = _a1r_lora_routes(index, node, output_index=output_index)
    if selected is not None:
        return selected
    projected = _component_routes(
        index,
        node,
        output_index=output_index,
        component=component,
    )
    if projected is not None:
        return projected
    edges, decision = selected_upstream_edges(index, node)
    return tuple(UpstreamRoute(edge) for edge in edges), decision


__all__ = [
    "RoutingDecision",
    "RoutingStatus",
    "UpstreamRoute",
    "routed_upstream_edges",
    "selected_upstream_edges",
]
