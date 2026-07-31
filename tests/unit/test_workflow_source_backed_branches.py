from __future__ import annotations

from types import MappingProxyType
from typing import cast

import pytest

import civiscribe.workflow.resources as resource_module
from civiscribe.domain import ResourceKind, ResourceRole
from civiscribe.workflow import (
    ActiveGraph,
    PromptNode,
    build_graph_index,
    normalize_api_prompt,
)
from civiscribe.workflow.classify import (
    FixedResourceSpec,
    fixed_resource_specs,
    resource_input_specs,
)
from civiscribe.workflow.extract import (
    _custom_sampler_hook_provider,
    _detailer_hook_sampler,
    _literal_sigma_steps,
    _nearest_sigma_steps,
    _prompt_ancestor_distances,
    _prompt_candidates,
    _prompt_input_names,
    _sage_combined_prompt_text,
    _sigma_text_steps,
)
from civiscribe.workflow.graph import GraphIndex
from civiscribe.workflow.model import FrozenValue
from civiscribe.workflow.resources import (
    _a1r_checkpoint_inputs,
    _a1r_double_checkpoint_inputs,
    _a1r_separate_checkpoint_inputs,
    _allowed_direct_inputs,
    _apt_loader_inputs,
    _direct_resources,
    _embedding_picker_multi_jk_resources,
    _h4_loader_inputs,
    _inline_embedding_resources,
    _sage_dynamic_mapping,
    _sage_flexible_selector_resources,
    _sage_lora_stack_resources,
)
from civiscribe.workflow.routing import (
    RoutingStatus,
    _conditioning_component_routes,
    _first_linked_component_input,
    _impact_nth_item_routes,
    _numbered_slot_sort_key,
    _pipe_component_routes,
    _pipe_conversion_routes,
    _sage_special_edges,
    _static_list_component_routes,
    routed_upstream_edges,
    selected_upstream_edges,
)
from civiscribe.workflow.scalar import resolve_node_output
from civiscribe.workflow.scan import (
    _active_semantic_issues,
    _selected_style_value,
)


def _frozen(value: object) -> FrozenValue:
    return cast(FrozenValue, value)


def _node(
    node_id: str,
    class_type: str,
    inputs: dict[str, FrozenValue] | None = None,
) -> PromptNode:
    return PromptNode(
        node_id,
        class_type,
        MappingProxyType(inputs or {}),
    )


def _index(prompt: object) -> GraphIndex:
    return build_graph_index(normalize_api_prompt(prompt))


def _active(
    *node_ids: str,
    consumed_outputs: dict[str, tuple[int, ...]] | None = None,
) -> ActiveGraph:
    return ActiveGraph(
        "save",
        node_ids,
        MappingProxyType({node_id: index + 1 for index, node_id in enumerate(node_ids)}),
        (),
        (),
        MappingProxyType(consumed_outputs or {}),
    )


def _scalar_output(class_type: str, inputs: dict[str, object], output_index: int) -> object:
    index = _index({"1": {"class_type": class_type, "inputs": inputs}})
    return resolve_node_output(index, _active("1"), index.nodes["1"], output_index)


def test_selected_resource_classifiers_cover_safe_alternate_modes() -> None:
    randomized = _node(
        "1",
        "LF_DiffusionModelSelector",
        {"randomize": "true", "diffusion_model": "models/random.safetensors"},
    )
    deterministic = _node(
        "2",
        "LF_DiffusionModelSelector",
        {"randomize": False, "diffusion_model": "models/selected.safetensors"},
    )
    full_checkpoint = _node(
        "3",
        "ModelAssembler",
        {"load_mode": "full_checkpoint", "ckpt_name": "models/base.safetensors"},
    )
    components = _node(
        "4",
        "ModelAssembler",
        {
            "load_mode": "separate_components",
            "base_model": "models/base.gguf",
            "vae_model": "vae/ae.safetensors",
            "clip_model_1": "text/clip.safetensors",
        },
    )

    assert resource_input_specs(randomized) == ()
    assert [spec.input_name for spec in resource_input_specs(deterministic)] == ["diffusion_model"]
    assert [spec.input_name for spec in resource_input_specs(full_checkpoint)] == ["ckpt_name"]
    assert {spec.input_name for spec in resource_input_specs(components)} == {
        "base_model",
        "vae_model",
        "clip_model_1",
    }
    assert resource_input_specs(_node("5", "ModelAssembler", {"load_mode": 1})) == ()
    assert resource_input_specs(_node("6", "ModelAssembler", {"load_mode": "unsupported"})) == ()
    assert resource_input_specs(_node("7", "H4_CompleteLoader", {"load_mode": 1})) == ()
    assert resource_input_specs(_node("8", "H4_CompleteLoader", {"load_mode": "unsupported"})) == ()


def test_direct_resources_validate_fixed_and_ta_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_fixed_specs = fixed_resource_specs
    monkeypatch.setattr(
        resource_module,
        "fixed_resource_specs",
        lambda _node: (
            FixedResourceSpec(
                "../escape.bin",
                ResourceRole.VISION_ENCODER,
                ResourceKind.VISION_ENCODER,
                "test_invalid_fixed_resource",
            ),
        ),
    )
    records, issues = _direct_resources(_node("1", "FixedResource"))
    assert records == ()
    assert [issue.code for issue in issues] == ["fixed_resource_value_invalid"]
    monkeypatch.setattr(resource_module, "fixed_resource_specs", original_fixed_specs)

    linked = _node("2", "TA_LoadModelWithName", {"model_file": ("1", 0)})
    assert _direct_resources(linked) == ((), ())

    index = _index(
        {
            "1": {"class_type": "PrimitiveString", "inputs": {"value": "[D] models/base.gguf"}},
            "2": {
                "class_type": "TA_LoadModelWithName",
                "inputs": {"model_file": ["1", 0]},
            },
        }
    )
    records, issues = _direct_resources(
        index.nodes["2"],
        index=index,
        active=_active("1", "2"),
    )
    assert issues == ()
    assert [record.filename for record in records] == ["base.gguf"]
    assert _direct_resources(
        _node("3", "TA_LoadModelWithName", {"model_file": "No models found"})
    ) == ((), ())
    records, issues = _direct_resources(
        _node("4", "TA_LoadModelWithName", {"model_file": "[C] ../escape.safetensors"})
    )
    assert records == ()
    assert [issue.code for issue in issues] == ["resource_value_unsafe_or_invalid"]


def test_sage_resource_helpers_cover_disabled_invalid_and_raw_dynamic_inputs() -> None:
    assert _sage_dynamic_mapping(_frozen("not a mapping")) is None
    raw = _frozen({"clip_name_1": "text/clip.safetensors"})
    assert _sage_dynamic_mapping(raw) == raw

    records, issues = _sage_flexible_selector_resources(
        _node(
            "1",
            "Sage_FlexibleClipSelector",
            {
                "num_of_clips": {
                    "clip_name_1": "text/clip.safetensors",
                    "clip_name_2": "../escape.safetensors",
                }
            },
        )
    )
    assert [record.filename for record in records] == ["clip.safetensors"]
    assert [issue.code for issue in issues] == ["resource_value_unsafe_or_invalid"]

    assert _sage_lora_stack_resources(_node("2", "Sage_LoraStack", {"enabled": False})) == ((), ())
    assert _sage_lora_stack_resources(_node("3", "Sage_LoraStack")) == ((), ())
    quick_records, quick_issues = _sage_lora_stack_resources(
        _node(
            "4",
            "Sage_QuickLoraStack",
            {
                "enabled": True,
                "lora_name": "../escape.safetensors",
                "model_weight": 0.5,
            },
        )
    )
    assert quick_records == ()
    assert [issue.code for issue in quick_issues] == ["resource_value_unsafe_or_invalid"]

    embedding_records, embedding_issues = _embedding_picker_multi_jk_resources(
        _node(
            "5",
            "Embedding Picker Multi JK",
            {
                "embedding_1": True,
                "embedding_name_1": "../escape.pt",
                "emphasis_1": 0.5,
            },
        )
    )
    assert embedding_records == ()
    assert [issue.code for issue in embedding_issues] == ["resource_value_unsafe_or_invalid"]


def test_loader_output_projection_helpers_cover_all_safe_modes() -> None:
    assert _a1r_checkpoint_inputs(set()) == {"ckpt_name", "vae_name"}
    assert _a1r_checkpoint_inputs({0}) == {"ckpt_name"}
    assert _a1r_separate_checkpoint_inputs(
        _node("1", "A1R", {"separate_mode": True}),
        {0},
    ) == {"ckpt_name_b"}
    assert _a1r_separate_checkpoint_inputs(
        _node("1", "A1R", {"separate_mode": False}),
        {2},
    ) == {"ckpt_name_a", "vae_name"}
    assert _a1r_double_checkpoint_inputs(
        _node("1", "A1R", {"enable_second": True}),
        {5},
    ) == {"ckpt_name_b", "vae_name"}
    assert (
        _a1r_double_checkpoint_inputs(
            _node("1", "A1R", {"enable_second": False}),
            {4},
        )
        == set()
    )

    assert _allowed_direct_inputs(
        _node("1", "A1RCheckpointLoader"),
        "a1rcheckpointloader",
        {0},
    ) == {"ckpt_name"}
    assert _h4_loader_inputs(_node("1", "H4"), set()) == {
        "ckpt_name",
        "unet_name",
        "clip_name",
        "vae_name",
        "lora_name",
    }
    assert _h4_loader_inputs(_node("1", "H4"), {3}) == set()
    assert _h4_loader_inputs(_node("1", "H4", {"load_mode": 1}), {0}) == set()
    assert _h4_loader_inputs(
        _node("1", "H4", {"load_mode": "Diffusers (Component)"}),
        {0, 1, 2},
    ) == {"unet_name", "clip_name", "vae_name", "lora_name"}
    assert _h4_loader_inputs(
        _node("1", "H4", {"load_mode": "unsupported"}),
        {0},
    ) == {"lora_name"}
    assert _apt_loader_inputs({1}) == {"ckpt_name", "unet_name", "lora"}
    assert _apt_loader_inputs({2}) == set()


def test_inline_embeddings_deduplicate_and_reject_unsafe_values() -> None:
    records, issues = _inline_embedding_resources(
        _node(
            "1",
            "CLIPTextEncode",
            {"text": ("embedding:portrait.pt embedding:PORTRAIT.pt embedding:../escape.pt")},
        )
    )

    assert [record.filename for record in records] == ["portrait.pt"]
    assert [issue.code for issue in issues] == ["resource_value_unsafe_or_invalid"]


def test_sage_routing_handles_false_missing_and_unresolved_selectors() -> None:
    logical = _index(
        {
            "1": {"class_type": "Source", "inputs": {}},
            "2": {"class_type": "Source", "inputs": {}},
            "3": {
                "class_type": "Sage_LogicalSwitch",
                "inputs": {
                    "condition": False,
                    "true_value": ["1", 0],
                    "false_value": ["2", 0],
                },
            },
            "4": {
                "class_type": "Sage_LogicalSwitch",
                "inputs": {"condition": True, "false_value": ["2", 0]},
            },
            "5": {
                "class_type": "Sage_LogicalSwitch",
                "inputs": {
                    "condition": ["6", 0],
                    "true_value": ["1", 0],
                    "false_value": ["2", 0],
                },
            },
            "6": {"class_type": "RuntimeBoolean", "inputs": {}},
        }
    )
    selected, decision = selected_upstream_edges(logical, logical.nodes["3"])
    assert [edge.source_node_id for edge in selected] == ["2"]
    assert decision is not None and decision.reason == "sage_logical_branch_selected"
    selected, decision = selected_upstream_edges(logical, logical.nodes["4"])
    assert [edge.source_node_id for edge in selected] == ["2"]
    assert decision is not None and decision.reason == "sage_logical_missing_branch_fallback"
    selected, decision = selected_upstream_edges(logical, logical.nodes["5"])
    assert {edge.source_node_id for edge in selected} == {"1", "2", "6"}
    assert decision is not None and decision.status is RoutingStatus.AMBIGUOUS

    text = _index(
        {
            "1": {"class_type": "Source", "inputs": {}},
            "2": {
                "class_type": "Sage_TextSwitch",
                "inputs": {"active": False, "str": ["1", 0]},
            },
            "3": {
                "class_type": "Sage_TextSwitch",
                "inputs": {"active": ["4", 0], "str": ["1", 0]},
            },
            "4": {"class_type": "RuntimeBoolean", "inputs": {}},
        }
    )
    selected, decision = selected_upstream_edges(text, text.nodes["2"])
    assert selected == ()
    assert decision is not None and decision.reason == "sage_text_disabled"
    selected, decision = selected_upstream_edges(text, text.nodes["3"])
    assert {edge.source_node_id for edge in selected} == {"1", "4"}
    assert decision is not None and decision.status is RoutingStatus.AMBIGUOUS


def test_sage_model_picker_and_image_selector_cover_empty_runtime_results() -> None:
    index = _index(
        {
            "1": {"class_type": "RuntimeIndex", "inputs": {}},
            "2": {
                "class_type": "Sage_MultiModelPicker",
                "inputs": {"index": ["1", 0], "model_template": {}},
            },
            "3": {
                "class_type": "Sage_MultiModelPicker",
                "inputs": {"index": 2, "model_template": {}},
            },
            "4": {
                "class_type": "SelectorDeImagenes",
                "inputs": {"fallback": 2, "mode": "auto", "on1": False},
            },
            "5": {
                "class_type": "SelectorDeImagenes",
                "inputs": {"fallback": "error", "mode": "auto", "on1": False},
            },
        }
    )
    _, decision = _sage_special_edges(index, index.nodes["2"]) or ((), None)
    assert decision is not None and decision.status is RoutingStatus.AMBIGUOUS
    selected, decision = selected_upstream_edges(index, index.nodes["3"])
    assert selected == ()
    assert decision is not None and decision.reason == "sage_model_index_unconnected"
    _, decision = selected_upstream_edges(index, index.nodes["4"])
    assert decision is not None and decision.status is RoutingStatus.AMBIGUOUS
    selected, decision = selected_upstream_edges(index, index.nodes["5"])
    assert selected == ()
    assert decision is not None and decision.reason == "no_output_runtime_error"


def test_component_route_helpers_cover_projection_and_empty_paths() -> None:
    index = _index(
        {
            "1": {"class_type": "Source", "inputs": {}},
            "2": {
                "class_type": "ToBasicPipe",
                "inputs": {"model": ["1", 0]},
            },
            "3": {
                "class_type": "EditBasicPipe",
                "inputs": {"model": ["1", 0], "basic_pipe": ["1", 1]},
            },
            "4": {
                "class_type": "EditBasicPipe",
                "inputs": {"basic_pipe": ["1", 1]},
            },
            "5": {"class_type": "ImpactMakeAnyList", "inputs": {}},
        }
    )

    assert _first_linked_component_input(index, index.nodes["2"], "vae") == ()
    assert _numbered_slot_sort_key("value") == ("value", -1, "value")
    routes, decision = _static_list_component_routes(
        index,
        index.nodes["5"],
        "impactmakeanylist",
        "list_index:0",
    ) or ((), None)
    assert routes == ()
    assert decision is not None and decision.reason == "empty_static_list"

    routes, decision = _pipe_component_routes(
        index,
        index.nodes["2"],
        "tobasicpipe",
        "model",
    ) or ((), None)
    assert [route.edge.source_node_id for route in routes] == ["1"]
    assert decision is not None and decision.reason == "pipe_component_projection"

    routes, decision = _pipe_component_routes(
        index,
        index.nodes["3"],
        "editbasicpipe",
        "model",
    ) or ((), None)
    assert [route.edge.input_name for route in routes] == ["model"]
    assert decision is not None and decision.reason == "pipe_override_projection"
    routes, _decision = _pipe_component_routes(
        index,
        index.nodes["4"],
        "editbasicpipe",
        "vae",
    ) or ((), None)
    assert [(route.edge.input_name, route.component) for route in routes] == [("basic_pipe", "vae")]
    assert _pipe_component_routes(index, index.nodes["1"], "source", "model") is None
    assert (
        _pipe_conversion_routes(
            index,
            index.nodes["1"],
            "source",
            "model",
            output_index=0,
        )
        is None
    )

    conversion_index = _index(
        {
            "1": {"class_type": "Source", "inputs": {}},
            "2": {
                "class_type": "AnyPipeToBasic",
                "inputs": {"any_pipe": ["1", 0]},
            },
        }
    )
    routes, decision = routed_upstream_edges(
        conversion_index,
        conversion_index.nodes["2"],
        output_index=0,
        component="model",
    )
    assert [(route.edge.input_name, route.component) for route in routes] == [("any_pipe", "model")]
    assert decision is not None


@pytest.mark.parametrize(
    ("class_type", "input_name", "component", "output_index", "next_component"),
    [
        ("AnyPipeToBasic", "any_pipe", "model", 0, "model"),
        ("easy pipeToBasicPipe", "pipe", "vae", 0, "vae"),
        ("BasicPipeToDetailerPipe", "basic_pipe", "clip", 0, "clip"),
        ("BasicPipeToDetailerPipeSDXL", "refiner_basic_pipe", "refiner_model", 0, "model"),
        ("DetailerPipeToBasicPipe", "detailer_pipe", "positive", 0, "positive"),
        ("DetailerPipeToBasicPipe", "detailer_pipe", "positive", 1, "refiner_positive"),
    ],
)
def test_pipe_conversion_routes_preserve_selected_component(
    class_type: str,
    input_name: str,
    component: str,
    output_index: int,
    next_component: str,
) -> None:
    index = _index(
        {
            "1": {"class_type": "Source", "inputs": {}},
            "2": {"class_type": class_type, "inputs": {input_name: ["1", 0]}},
        }
    )

    routes, decision = _pipe_conversion_routes(
        index,
        index.nodes["2"],
        "".join(character for character in class_type.casefold() if character.isalnum()),
        component,
        output_index=output_index,
    ) or ((), None)

    assert [(route.edge.input_name, route.component) for route in routes] == [
        (input_name, next_component)
    ]
    assert decision is not None


def test_conditioning_projection_and_runtime_list_source_alternates() -> None:
    index = _index(
        {
            "1": {"class_type": "Source", "inputs": {}},
            "2": {
                "class_type": "SetPrecisionUniversal",
                "inputs": {"positive": ["1", 0], "negative": ["1", 1]},
            },
            "3": {
                "class_type": "ImpactSelectNthItemOfAnyList",
                "inputs": {"any_list": ["1", 0], "index": 0},
            },
        }
    )
    assert (
        _conditioning_component_routes(
            index,
            index.nodes["2"],
            "setprecisionuniversal",
            "model",
        )
        is None
    )
    routes, decision = _impact_nth_item_routes(index, index.nodes["3"]) or ((), None)
    assert [route.edge.source_node_id for route in routes] == ["1"]
    assert decision is not None and decision.reason == "list_source_runtime_opaque"


def test_a1r_routing_handles_separate_two_output_and_unresolved_sources() -> None:
    index = _index(
        {
            "1": {"class_type": "Source", "inputs": {}},
            "2": {
                "class_type": "A1RStackLoraLoaderSeparate",
                "inputs": {
                    "separate_mode": True,
                    "model_a": ["1", 0],
                    "model_b": ["1", 1],
                    "clip_a": ["1", 2],
                    "clip_b": ["1", 3],
                },
            },
            "3": {
                "class_type": "A1RStackLoraLoader2P",
                "inputs": {
                    "output2_source": 2,
                    "model_a": ["1", 0],
                    "model_b": ["1", 1],
                    "clip_a": ["1", 2],
                    "clip_b": ["1", 3],
                },
            },
            "4": {
                "class_type": "A1RStackLoraLoaderSeparate",
                "inputs": {"separate_mode": ["5", 0], "model_a": ["1", 0]},
            },
            "5": {"class_type": "RuntimeBoolean", "inputs": {}},
        }
    )
    routes, decision = routed_upstream_edges(index, index.nodes["2"], output_index=0)
    assert {route.edge.input_name for route in routes} == {"model_b", "clip_b"}
    assert decision is not None and decision.reason == "a1r_lora_source_selected"
    routes, decision = routed_upstream_edges(index, index.nodes["3"], output_index=2)
    assert {route.edge.input_name for route in routes} == {"model_b", "clip_b"}
    assert decision is not None and decision.reason == "a1r_lora_source_selected"
    routes, decision = routed_upstream_edges(index, index.nodes["4"], output_index=0)
    assert {route.edge.source_node_id for route in routes} == {"1", "5"}
    assert decision is None


@pytest.mark.parametrize(
    ("class_type", "inputs", "output_index", "expected"),
    [
        ("Sage_SamplerSelector", {"sampler_name": "euler"}, 0, "euler"),
        ("Sage_SamplerSelector", {"sampler_name": "euler"}, 1, None),
        ("Sage_SchedulerSelector", {"steps": 12, "scheduler_name": "beta"}, 0, 12),
        ("Sage_SchedulerSelector", {"steps": 12, "scheduler_name": "beta"}, 1, "beta"),
        ("Sage_TextSwitch", {"active": True, "str": "enabled"}, 0, "enabled"),
        ("Sage_TextSwitch", {"active": False, "str": "enabled"}, 0, ""),
        ("Sage_TextSwitch", {"active": "not-bool", "str": "enabled"}, 0, None),
        ("Wan Wrapper Sampler Default JK", {"scheduler": "beta"}, 2, None),
        ("Sampler Loader JK", {"sampler": "euler", "scheduler": "beta"}, 9, None),
        ("IO Load Image [Eclipse]", {"filepath": "private"}, 13, None),
        ("ComfySwitchNode", {}, 0, None),
        ("ComfySwitchNode", {}, 1, None),
        ("PreviewAny", {"source": "text"}, 1, None),
        ("StringConcatenate", {"string_a": "a", "string_b": "b", "delimiter": "-"}, 1, None),
        (
            "StringConcatenate",
            {"string_a": ["404", 0], "string_b": "b", "delimiter": "-"},
            0,
            None,
        ),
    ],
)
def test_source_backed_scalar_outputs_cover_valid_and_unavailable_fields(
    class_type: str,
    inputs: dict[str, object],
    output_index: int,
    expected: object,
) -> None:
    assert _scalar_output(class_type, inputs, output_index) == expected


def test_prompt_selector_scalar_outputs_cover_invalid_and_fallback_states() -> None:
    assert (
        _scalar_output(
            "ImpactStringSelector",
            {"strings": "one\ntwo", "multiline": False, "select": 0},
            1,
        )
        is None
    )
    assert (
        _scalar_output(
            "ImpactStringSelector",
            {"strings": "one\ntwo", "multiline": "invalid", "select": 0},
            0,
        )
        is None
    )

    disabled_slots = {f"on{slot}": False for slot in range(1, 13)}
    assert (
        _scalar_output(
            "SelectorDePrompts",
            {
                "fallback": "p1",
                "join_with": r"\n",
                "mode": "combine",
                **disabled_slots,
            },
            1,
        )
        is None
    )
    assert (
        _scalar_output(
            "SelectorDePrompts",
            {"fallback": True, "join_with": r"\n", "mode": "combine"},
            0,
        )
        is None
    )
    assert (
        _scalar_output(
            "SelectorDePrompts",
            {
                "fallback": "error",
                "join_with": r"\n",
                "mode": "combine",
                **disabled_slots,
            },
            0,
        )
        is None
    )

    one_active = {
        "fallback": "p1",
        "join_with": r"\n",
        "mode": "combine",
        **disabled_slots,
        "on1": True,
        "p1": "selected",
    }
    assert _scalar_output("SelectorDePrompts", one_active, 0) == "selected"
    assert (
        _scalar_output(
            "SelectorDePrompts",
            {**one_active, "p1": _frozen(("404", 0))},
            0,
        )
        is None
    )
    assert (
        _scalar_output(
            "SelectorDePrompts",
            {**one_active, "p1": "   "},
            0,
        )
        == ""
    )


def test_sigma_and_prompt_helpers_reject_malformed_runtime_values() -> None:
    assert _sigma_text_steps(None) is None
    assert _sigma_text_steps("0.1") is None
    assert _sigma_text_steps("0.1 invalid") is None
    assert _literal_sigma_steps(_frozen("not a tuple")) is None
    assert _literal_sigma_steps(_frozen((0.1,))) is None
    assert _literal_sigma_steps(_frozen((0.1, True))) is None
    assert _literal_sigma_steps(_frozen((0.1, float("inf")))) is None

    index = _index(
        {
            "1": {"class_type": "FloatToSigmas", "inputs": {"float_list": ["2", 0]}},
            "2": {"class_type": "RuntimeFloats", "inputs": {}},
            "3": {"class_type": "KSampler", "inputs": {"sigmas": ["1", 0]}},
        }
    )
    assert _nearest_sigma_steps(index, _active("1", "2", "3"), index.nodes["3"]) is None
    assert _prompt_input_names(
        _node("4", "TextParseA1111Embeddings", {"text": "prompt"}),
        "positive",
    ) == ("text",)


def test_custom_sampler_hook_and_prompt_helpers_cover_absent_data() -> None:
    index = _index(
        {
            "1": {"class_type": "DetailerHookCombine", "inputs": {"hook1": ["2", 0]}},
            "2": {"class_type": "UnknownHook", "inputs": {}},
            "3": {"class_type": "DetailerHookCombine", "inputs": {}},
            "4": {"class_type": "CustomSamplerDetailerHookProvider", "inputs": {}},
            "5": {
                "class_type": "Sage_CombineCLIPTextEncode",
                "inputs": {"texts": "invalid"},
            },
            "6": {
                "class_type": "Sage_CombineCLIPTextEncode",
                "inputs": {"texts": {"other": "ignored", "text_bad": "ignored"}},
            },
        }
    )
    active = _active("1", "2", "3", "4", "5", "6")
    assert _custom_sampler_hook_provider(index, active, index.nodes["1"]) is None
    assert _custom_sampler_hook_provider(index, active, index.nodes["3"]) is None
    assert _detailer_hook_sampler(
        index,
        active,
        _node("7", "Detailer", {"detailer_hook": ("2", 0)}),
    ) == (None, False)
    assert (
        _custom_sampler_hook_provider(
            index,
            active,
            index.nodes["4"],
            seen=frozenset({"4"}),
        )
        is None
    )
    assert _sage_combined_prompt_text(index, active, index.nodes["5"]) is None
    assert _sage_combined_prompt_text(index, active, index.nodes["6"]) is None

    missing_node_index = GraphIndex(
        MappingProxyType({}),
        MappingProxyType({}),
        MappingProxyType({}),
        (),
    )
    assert _prompt_ancestor_distances(
        missing_node_index,
        _active("missing"),
        "missing",
        0,
    ) == {"missing": 0}

    candidates = _prompt_candidates(
        index,
        active,
        root_id="6",
        root_output_index=0,
        kind="positive",
    )
    assert candidates == ()


def test_scan_semantic_helpers_cover_empty_tuple_and_inactive_ids() -> None:
    assert not _selected_style_value(None)
    assert _selected_style_value(1)
    assert not _selected_style_value((None, "disabled"))
    assert _selected_style_value((None, "selected"))

    index = _index(
        {
            "1": {"class_type": "CR Cycle Models", "inputs": {"mode": "disabled"}},
        }
    )
    assert _active_semantic_issues(index, _active("missing", "1")) == ()


def test_sage_flexible_selector_without_dynamic_mapping_is_empty() -> None:
    assert _sage_flexible_selector_resources(
        _node("1", "Sage_FlexibleClipSelector", {"num_of_clips": "none"})
    ) == ((), ())
