from __future__ import annotations

import math
from types import MappingProxyType
from typing import cast

import pytest

from civiscribe.domain import (
    ResourceKind,
    ResourceRecord,
    ResourceRole,
    ResourceStrengths,
    ScanIssue,
    WorkflowKind,
)
from civiscribe.workflow import (
    ActiveGraph,
    PromptNode,
    build_graph_index,
    normalize_api_prompt,
    scan_workflow,
    trace_active_upstream,
)
from civiscribe.workflow.classify import (
    compact_class,
    is_base_model_loader,
    is_decode_node,
    is_empty_latent_node,
    is_image_latent_node,
    is_image_source_node,
    is_known_active_node,
    is_primitive_node,
    is_runtime_text_generator_node,
    is_sampler_node,
    is_text_encode_node,
    resource_input_specs,
)
from civiscribe.workflow.extract import (
    _antrobots_prompt_roots,
    _antrobots_refiner_denoise,
    _branch_nodes,
    _dimensions_from_node,
    _extract_clip_skip,
    _find_guidance,
    _latent_source,
    _linked_node,
    _linked_prompt_root,
    _pipe_prompt_root,
    _prompt_field,
    _prompt_input_names,
    _prompt_root,
    extract_generation_settings,
    extract_prompts,
)
from civiscribe.workflow.graph import GraphIndex
from civiscribe.workflow.lineage import (
    StageSelection,
    classify_workflow_kind,
    select_generation_stage,
    select_primary_resource,
    select_vae_resource,
)
from civiscribe.workflow.model import FrozenValue
from civiscribe.workflow.resources import (
    _MAX_ND_SUPER_LORA_BUNDLE_CHARS,
    _bool_value,
    _direct_resources,
    _float_value,
    _indexed_resource_records,
    _inline_lora_resources,
    _lora_record,
    _LoraRecordSpec,
    _nd_super_float,
    _nd_super_lora_entries,
    _nd_super_lora_resources,
    _power_lora_resources,
    _safe_resource_value,
    _stack_candidates,
    _stack_count_limit,
    _stack_lora_resources,
    _stack_mode,
    _stack_strengths,
    _structured_lora_resources,
    _text_lora_resources,
    extract_active_resources,
)
from civiscribe.workflow.routing import (
    RoutingStatus,
    _literal_bool,
    _literal_index,
    _resolve_selector_value,
    selected_upstream_edges,
)
from civiscribe.workflow.scalar import (
    literal_scalar,
    resolve_node_input,
    resolve_node_output,
    resolve_scalar,
    scalar_float,
    scalar_int,
    scalar_string,
)
from civiscribe.workflow.scan import _deduplicate_issues

EXPECTED_FLOAT = 2.5
EXPECTED_INT = 2
LORA_WEIGHT = 0.5
LORA_MODEL_STRENGTH = 0.75
LORA_CLIP_STRENGTH = 0.25
RESOLVED_SCALAR = 99
RGTHREE_SEED = 987654321
MAX_STACK_LORAS = 64
FALLBACK_SELECTOR = 7
RESOLUTION_SELECTOR_SIZE = (1344, 768)
SEEDED_DIMENSIONS = (1120, 928)
CM_DIMENSIONS = (1024, 768)
BASE_DIMENSIONS = (800, 600)
SCALED_DIMENSIONS = (1200, 900)
IDEOGRAM_DIMENSIONS = (832, 1216)


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


def _active(*node_ids: str) -> ActiveGraph:
    return ActiveGraph(
        "save",
        node_ids,
        MappingProxyType({node_id: index + 1 for index, node_id in enumerate(node_ids)}),
        (),
        (),
    )


@pytest.mark.parametrize(
    ("class_type", "input_name", "role", "kind"),
    [
        ("ControlNetLoader", "control_net_name", ResourceRole.CONTROLNET, ResourceKind.CONTROLNET),
        ("IPAdapterModelLoader", "ipadapter_file", ResourceRole.IPADAPTER, ResourceKind.IPADAPTER),
        ("UpscaleModelLoader", "model_name", ResourceRole.UPSCALER, ResourceKind.UPSCALER),
        ("EmbeddingLoader", "embedding_name", ResourceRole.EMBEDDING, ResourceKind.EMBEDDING),
        (
            "CLIPVisionLoader",
            "clip_name",
            ResourceRole.VISION_ENCODER,
            ResourceKind.VISION_ENCODER,
        ),
        (
            "ModelPatchLoader",
            "name",
            ResourceRole.MODEL_PATCH,
            ResourceKind.MODEL_PATCH,
        ),
        ("GLIGENLoader", "gligen_name", ResourceRole.GLIGEN, ResourceKind.GLIGEN),
    ],
)
def test_remaining_resource_families_are_classified(
    class_type: str,
    input_name: str,
    role: ResourceRole,
    kind: ResourceKind,
) -> None:
    node = _node("1", class_type, {input_name: "models/resource.bin"})

    assert [(spec.input_name, spec.role, spec.kind) for spec in resource_input_specs(node)] == [
        (input_name, role, kind)
    ]
    assert not is_base_model_loader(node)


@pytest.mark.parametrize(
    ("class_type", "inputs", "expected"),
    [
        (
            "LoaderGGUFAdvanced",
            {"gguf_name": "diffusion_models/model.gguf"},
            [
                (
                    "gguf_name",
                    ResourceRole.BASE_MODEL,
                    ResourceKind.DIFFUSION_MODEL,
                    "advanced_gguf_loader",
                )
            ],
        ),
        (
            "LTXVGemmaCLIPModelLoader",
            {
                "ltxv_path": "diffusion_models/ltxv.safetensors",
                "gemma_path": "text_encoders/gemma.safetensors",
            },
            [
                (
                    "ltxv_path",
                    ResourceRole.BASE_MODEL,
                    ResourceKind.DIFFUSION_MODEL,
                    "ltx_gemma_integrated_loader",
                ),
                (
                    "gemma_path",
                    ResourceRole.TEXT_ENCODER,
                    ResourceKind.CLIP,
                    "ltx_gemma_integrated_loader",
                ),
            ],
        ),
        (
            "LTXAVTextEncoderLoader",
            {"ckpt_name": "text_encoders/ltx_av.safetensors"},
            [
                (
                    "ckpt_name",
                    ResourceRole.TEXT_ENCODER,
                    ResourceKind.CLIP,
                    "ltx_av_text_encoder_loader",
                )
            ],
        ),
        (
            "FluxLoader",
            {
                "model_name": "diffusion_models/flux.safetensors",
                "clip_name": "text_encoders/clip.safetensors",
                "vae_name": "vae/ae.safetensors",
            },
            [
                (
                    "model_name",
                    ResourceRole.BASE_MODEL,
                    ResourceKind.DIFFUSION_MODEL,
                    "integrated_diffusion_loader",
                ),
                (
                    "clip_name",
                    ResourceRole.TEXT_ENCODER,
                    ResourceKind.CLIP,
                    "integrated_diffusion_loader",
                ),
                (
                    "vae_name",
                    ResourceRole.VAE,
                    ResourceKind.VAE,
                    "integrated_diffusion_loader",
                ),
            ],
        ),
        (
            "UnetLoaderGGUFDisTorchMultiGPU",
            {"unet_name": "diffusion_models/model.gguf"},
            [
                (
                    "unet_name",
                    ResourceRole.BASE_MODEL,
                    ResourceKind.DIFFUSION_MODEL,
                    "multigpu_gguf_unet_loader",
                )
            ],
        ),
        (
            "DualCLIPLoaderGGUFDisTorch2MultiGPU",
            {
                "clip_name1": "text_encoders/clip-l.gguf",
                "clip_name2": "text_encoders/t5xxl.gguf",
            },
            [
                (
                    "clip_name1",
                    ResourceRole.TEXT_ENCODER,
                    ResourceKind.CLIP,
                    "multigpu_gguf_text_encoder_loader",
                ),
                (
                    "clip_name2",
                    ResourceRole.TEXT_ENCODER,
                    ResourceKind.CLIP,
                    "multigpu_gguf_text_encoder_loader",
                ),
            ],
        ),
        (
            "QwenLoader",
            {"model": "text_encoders/qwen_7b.safetensors"},
            [
                (
                    "model",
                    ResourceRole.TEXT_ENCODER,
                    ResourceKind.CLIP,
                    "wan_qwen_text_encoder_loader",
                )
            ],
        ),
        (
            "CreateHookLora",
            {
                "lora_name": "loras/hook.safetensors",
                "strength_model": 0.8,
                "strength_clip": 0.6,
            },
            [
                (
                    "lora_name",
                    ResourceRole.LORA,
                    ResourceKind.LORA,
                    "core_hook_lora",
                )
            ],
        ),
        (
            "CreateHookModelAsLoraModelOnly",
            {
                "ckpt_name": "checkpoints/patch.safetensors",
                "strength_model": 0.4,
            },
            [
                (
                    "ckpt_name",
                    ResourceRole.MODEL_PATCH,
                    ResourceKind.MODEL_PATCH,
                    "core_hook_model_patch",
                )
            ],
        ),
        (
            "Diffusers Hub Model Down-Loader",
            {
                "repo_id": "organization/repository",
                "revision": "main",
            },
            [
                (
                    "repo_id",
                    ResourceRole.BASE_MODEL,
                    ResourceKind.EXTERNAL_MODEL,
                    "was_diffusers_hub_loader",
                )
            ],
        ),
    ],
)
def test_exact_loader_rules_are_classified_with_provenance(
    class_type: str,
    inputs: dict[str, FrozenValue],
    expected: list[tuple[str, ResourceRole, ResourceKind, str]],
) -> None:
    node = _node("1", class_type, inputs)

    specs = resource_input_specs(node)
    assert [(spec.input_name, spec.role, spec.kind, spec.rule_id) for spec in specs] == expected

    records, issues = _direct_resources(node)
    assert issues == ()
    assert [record.detection_rule_id for record in records] == [
        rule_id for _, _, _, rule_id in expected
    ]


@pytest.mark.parametrize(
    "class_type",
    [
        "UnetLoaderGGUFDisTorchMultiGPU",
        "UnetLoaderGGUFAdvancedDisTorchMultiGPU",
        "UnetLoaderGGUFDisTorch2MultiGPU",
        "UnetLoaderGGUFAdvancedDisTorch2MultiGPU",
        "UnetLoaderGGUFMultiGPU",
        "UnetLoaderGGUFAdvancedMultiGPU",
        "CLIPLoaderGGUFDisTorchMultiGPU",
        "DualCLIPLoaderGGUFDisTorchMultiGPU",
        "TripleCLIPLoaderGGUFDisTorchMultiGPU",
        "QuadrupleCLIPLoaderGGUFDisTorchMultiGPU",
        "CLIPLoaderGGUFDisTorch2MultiGPU",
        "DualCLIPLoaderGGUFDisTorch2MultiGPU",
        "TripleCLIPLoaderGGUFDisTorch2MultiGPU",
        "QuadrupleCLIPLoaderGGUFDisTorch2MultiGPU",
        "CLIPLoaderGGUFMultiGPU",
        "DualCLIPLoaderGGUFMultiGPU",
        "TripleCLIPLoaderGGUFMultiGPU",
        "QuadrupleCLIPLoaderGGUFMultiGPU",
    ],
)
def test_multigpu_gguf_aliases_are_known_without_serialized_widget_values(
    class_type: str,
) -> None:
    assert is_known_active_node(_node("1", class_type))


@pytest.mark.parametrize(
    ("class_type", "inputs", "expected"),
    [
        (
            "Efficient Loader",
            {
                "ckpt_name": "checkpoints/base.safetensors",
                "vae_name": "vae/main.safetensors",
                "lora_name": "loras/style.safetensors",
            },
            {
                ("ckpt_name", ResourceRole.BASE_MODEL),
                ("vae_name", ResourceRole.VAE),
                ("lora_name", ResourceRole.LORA),
            },
        ),
        (
            "ttN pipeLoaderSDXL_v2",
            {
                "base_ckpt_name": "checkpoints/base.safetensors",
                "refiner_ckpt_name": "checkpoints/refiner.safetensors",
                "vae_name": "vae/main.safetensors",
            },
            {
                ("base_ckpt_name", ResourceRole.BASE_MODEL),
                ("refiner_ckpt_name", ResourceRole.BASE_MODEL),
                ("vae_name", ResourceRole.VAE),
            },
        ),
        (
            "LoadTextEncoderShared //Inspire",
            {
                "model_name1": "text_encoders/one.safetensors",
                "model_name2": "text_encoders/two.safetensors",
            },
            {
                ("model_name1", ResourceRole.TEXT_ENCODER),
                ("model_name2", ResourceRole.TEXT_ENCODER),
            },
        ),
        (
            "WanVideoTextEncodeCached",
            {"model_name": "text_encoders/umt5.safetensors"},
            {("model_name", ResourceRole.TEXT_ENCODER)},
        ),
        (
            "LTXVQ8LoraModelLoader",
            {"lora_name": "loras/video.safetensors"},
            {("lora_name", ResourceRole.LORA)},
        ),
    ],
)
def test_audited_custom_loader_families_accumulate_resources(
    class_type: str,
    inputs: dict[str, FrozenValue],
    expected: set[tuple[str, ResourceRole]],
) -> None:
    specs = resource_input_specs(_node("1", class_type, inputs))

    assert {(spec.input_name, spec.role) for spec in specs} == expected


def test_easy_integrated_loader_honors_linked_overrides_and_selected_lora() -> None:
    loader = _node(
        "1",
        "easy fullLoader",
        {
            "ckpt_name": "checkpoints/unused.safetensors",
            "vae_name": "vae/unused.safetensors",
            "clip_name": "text_encoders/unused.safetensors",
            "model_override": ("90", 0),
            "vae_override": ("91", 0),
            "clip_override": ("92", 0),
        },
    )
    switcher = _node(
        "2",
        "easy loraSwitcher",
        {
            "toggle": True,
            "select": 2,
            "lora_strength": 0.65,
            "lora_1_name": "loras/unused.safetensors",
            "lora_2_name": "loras/selected.safetensors",
        },
    )

    assert resource_input_specs(loader) == ()
    records, issues = _direct_resources(switcher)
    assert issues == ()
    assert [(item.filename, item.strengths.weight) for item in records] == [
        ("selected.safetensors", 0.65)
    ]


def test_audited_selector_and_integrated_loader_contract_branches() -> None:
    easy_loader = _node(
        "1",
        "easy fullLoader",
        {
            "ckpt_name": "checkpoints/base.safetensors",
            "unet_name": "diffusion_models/unet.safetensors",
            "clip_name": "text_encoders/clip.safetensors",
            "vae_name": "vae/main.safetensors",
            "lora_name": "loras/style.safetensors",
        },
    )
    specs = resource_input_specs(easy_loader)
    assert {(spec.input_name, spec.role) for spec in specs} >= {
        ("ckpt_name", ResourceRole.BASE_MODEL),
        ("unet_name", ResourceRole.BASE_MODEL),
        ("clip_name", ResourceRole.TEXT_ENCODER),
        ("vae_name", ResourceRole.VAE),
        ("lora_name", ResourceRole.LORA),
    }

    selected_model = resource_input_specs(
        _node(
            "2",
            "CR Select Model",
            {
                "select_model": 2,
                "ckpt_name1": "checkpoints/unused.safetensors",
                "ckpt_name2": "checkpoints/selected.safetensors",
            },
        )
    )
    assert [(spec.input_name, spec.rule_id) for spec in selected_model] == [
        ("ckpt_name2", "comfyroll_selected_model")
    ]
    assert (
        resource_input_specs(
            _node(
                "3", "CR Select Model", {"select_model": True, "ckpt_name1": "unused.safetensors"}
            )
        )
        == ()
    )

    scheduled_model = resource_input_specs(
        _node(
            "4",
            "CR Load Scheduled Models",
            {"mode": "Load default model", "default_model": "checkpoints/default.safetensors"},
        )
    )
    scheduled_lora = resource_input_specs(
        _node(
            "5",
            "CR Load Scheduled LoRAs",
            {"mode": "Load default lora", "default_lora": "loras/default.safetensors"},
        )
    )
    assert scheduled_model[0].rule_id == "comfyroll_default_scheduled_model"
    assert scheduled_lora[0].rule_id == "comfyroll_default_scheduled_lora"
    assert (
        resource_input_specs(
            _node("6", "CR Load Scheduled Models", {"mode": "Schedule", "default_model": "unused"})
        )
        == ()
    )
    assert (
        resource_input_specs(
            _node("7", "CR Load Scheduled LoRAs", {"mode": "Schedule", "default_lora": "unused"})
        )
        == ()
    )
    assert resource_input_specs(_node("8", "CR Unknown Selector", {})) == ()


def test_audited_easy_adapter_lora_and_kj_gguf_contract_branches() -> None:
    assert (
        resource_input_specs(
            _node(
                "1",
                "easy loraSwitcher",
                {"toggle": False, "select": 1, "lora_1_name": "loras/unused.safetensors"},
            )
        )
        == ()
    )
    assert (
        resource_input_specs(
            _node(
                "2",
                "easy loraSwitcher",
                {"toggle": True, "select": 0, "lora_1_name": "loras/unused.safetensors"},
            )
        )
        == ()
    )

    adapter = resource_input_specs(
        _node(
            "3",
            "easy instantIDApply",
            {
                "instantid_file": "ipadapter/instantid.bin",
                "control_net_name": "controlnet/instantid.safetensors",
            },
        )
    )
    assert {(spec.input_name, spec.role) for spec in adapter} == {
        ("instantid_file", ResourceRole.IPADAPTER),
        ("control_net_name", ResourceRole.CONTROLNET),
    }
    linked_adapter = resource_input_specs(
        _node(
            "4",
            "easy instantIDApplyADV",
            {
                "instantid_file": "ipadapter/instantid.bin",
                "control_net": ("9", 0),
                "control_net_name": "controlnet/unused.safetensors",
            },
        )
    )
    assert {(spec.input_name, spec.role) for spec in linked_adapter} == {
        ("instantid_file", ResourceRole.IPADAPTER)
    }
    assert resource_input_specs(_node("5", "NotEasyInstantID", {})) == ()

    connector = resource_input_specs(
        _node(
            "6",
            "GGUFLoaderKJ",
            {
                "model_name": "diffusion_models/base.gguf",
                "extra_model_name": "text_encoders/connector.gguf",
            },
        )
    )
    second_model = resource_input_specs(
        _node(
            "7",
            "GGUFLoaderKJ",
            {
                "model_name": "diffusion_models/base.gguf",
                "extra_model_name": "diffusion_models/refiner.gguf",
            },
        )
    )
    assert {(spec.input_name, spec.role) for spec in connector} == {
        ("model_name", ResourceRole.BASE_MODEL),
        ("extra_model_name", ResourceRole.TEXT_ENCODER),
    }
    assert {(spec.input_name, spec.role) for spec in second_model} == {
        ("model_name", ResourceRole.BASE_MODEL),
        ("extra_model_name", ResourceRole.BASE_MODEL),
    }


def test_rgthree_context_big_is_passthrough_not_checkpoint_loader() -> None:
    node = _node(
        "1",
        "Context Big (rgthree)",
        {"ckpt_name": "checkpoints/not_loaded_here.safetensors"},
    )

    assert resource_input_specs(node) == ()
    assert is_known_active_node(node)


def test_dynamic_resource_stacks_honor_selection_switches_and_strengths() -> None:
    rgthree = _node(
        "1",
        "Lora Loader Stack (rgthree)",
        {
            "lora_01": "loras/active.safetensors",
            "strength_01": 0.75,
            "lora_02": "loras/disabled.safetensors",
            "strength_02": 0.0,
        },
    )
    easy_controlnet = _node(
        "2",
        "easy controlnetStack",
        {
            "toggle": True,
            "num_controlnet": 2,
            "controlnet_1": "controlnet/active.safetensors",
            "controlnet_1_strength": 0.6,
            "controlnet_2": "controlnet/other.safetensors",
        },
    )
    comfyroll_upscale = _node(
        "3",
        "CR Multi Upscale Stack",
        {
            "switch_1": "On",
            "upscale_model_1": "upscale_models/active.pth",
            "switch_2": "Off",
            "upscale_model_2": "upscale_models/inactive.pth",
        },
    )

    loras, lora_issues = _stack_lora_resources(rgthree)
    controls, control_issues = _indexed_resource_records(easy_controlnet)
    upscalers, upscale_issues = _indexed_resource_records(comfyroll_upscale)

    assert lora_issues == control_issues == upscale_issues == ()
    assert [(item.filename, item.strengths.model) for item in loras] == [
        ("active.safetensors", 0.75)
    ]
    assert [(item.filename, item.strengths.weight) for item in controls] == [
        ("active.safetensors", 0.6),
        ("other.safetensors", None),
    ]
    assert [item.filename for item in upscalers] == ["active.pth"]


def test_resource_extractors_cover_disabled_invalid_and_stack_policy_branches() -> None:
    invalid_record, invalid_issue = _lora_record(
        _node("1", "LoraLoader"),
        input_name="lora_name",
        value="../private.safetensors",
        spec=_LoraRecordSpec(ResourceStrengths(), "test"),
    )
    assert invalid_record is None
    assert invalid_issue == ScanIssue(
        "resource_value_unsafe_or_invalid",
        node_id="1",
        input_name="lora_name",
    )

    assert _direct_resources(_node("2", "VAELoader", {"vae_name": "None"})) == ((), ())
    assert _direct_resources(
        _node(
            "3",
            "LoraLoader",
            {"lora_name": "loras/disabled.safetensors", "strength_model": 0.0},
        )
    ) == ((), ())

    power_records, power_issues = _power_lora_resources(
        _node(
            "4",
            "Power Lora Loader (rgthree)",
            {
                "lora_disabled_value": {"on": True, "lora": "None"},
                "lora_zero": {
                    "on": True,
                    "lora": "loras/zero.safetensors",
                    "strength": 0.0,
                    "strengthTwo": 0.0,
                },
            },
        )
    )
    assert power_records == ()
    assert power_issues == ()

    assert _stack_lora_resources(
        _node(
            "5",
            "LoraStacker",
            {"toggle": False, "lora_1_name": "loras/unused.safetensors"},
        )
    ) == ((), ())
    stack_records, stack_issues = _stack_lora_resources(
        _node(
            "6",
            "LoraStacker",
            {
                "input_mode": "advanced",
                "lora_count": 3,
                "switch_1": False,
                "lora_1_name": "loras/switched-off.safetensors",
                "lora_2_name": "../private.safetensors",
                "model_str_2": 0.4,
                "clip_str_2": 0.2,
                "lora_3_name": "loras/active.safetensors",
                "model_str_3": 0.7,
                "clip_str_3": 0.3,
            },
        )
    )
    assert [
        (item.filename, item.strengths.model, item.strengths.clip) for item in stack_records
    ] == [("active.safetensors", 0.7, 0.3)]
    assert stack_issues == (
        ScanIssue(
            "resource_value_unsafe_or_invalid",
            node_id="6",
            input_name="lora_2_name",
        ),
    )

    assert _stack_mode(_node("7", "LoraStacker", {"mode": " Simple "})) == "simple"
    assert _stack_mode(_node("8", "LoraStacker")) is None
    assert _stack_count_limit(_node("9", "LoraStacker", {"lora_count": 999})) == MAX_STACK_LORAS
    assert _stack_count_limit(_node("10", "LoraStacker")) == MAX_STACK_LORAS
    assert _stack_candidates(
        _node(
            "11",
            "WanVideoLoraSelectMulti",
            {"lora_0_name": "loras/zero.safetensors", "lora_65_name": "loras/too-many.safetensors"},
        ),
        "wanvideoloraselectmulti",
    ) == ((0, "lora_0_name", "loras/zero.safetensors"),)
    strengths = _stack_strengths(
        _node(
            "12",
            "LoraStacker",
            {"model_weight_1": 0.6, "clip_weight_1": 0.2},
        ),
        1,
        "lora_name_1",
        "advanced",
    )
    assert (strengths.weight, strengths.model, strengths.clip) == (None, 0.6, 0.2)


def test_structured_and_inline_lora_lists_are_data_only() -> None:
    structured = _node(
        "1",
        "Lora Loader (LoraManager)",
        {
            "loras": {
                "__value__": (
                    {
                        "name": "loras/active.safetensors",
                        "strength": 0.8,
                        "clipStrength": 0.4,
                        "active": True,
                    },
                    {
                        "name": "loras/off.safetensors",
                        "strength": 1.0,
                        "active": False,
                    },
                )
            }
        },
    )
    inline = _node(
        "2",
        "ttN pipeLoader",
        {"loras": "<lora:loras/style.safetensors:0.7:0.3>"},
    )

    structured_records, structured_issues = _inline_lora_resources(structured)
    inline_records, inline_issues = _inline_lora_resources(inline)

    assert structured_issues == inline_issues == ()
    assert [
        (item.filename, item.strengths.model, item.strengths.clip) for item in structured_records
    ] == [("active.safetensors", 0.8, 0.4)]
    assert [
        (item.filename, item.strengths.model, item.strengths.clip) for item in inline_records
    ] == [("style.safetensors", 0.7, 0.3)]


def test_structured_text_and_indexed_resources_cover_edge_contracts() -> None:
    structured_records, structured_issues = _structured_lora_resources(
        _node("1", "Lora Loader (LoraManager)"),
        (
            "not-a-mapping",
            {"name": "loras/default-clip.safetensors", "strength": 0.8},
            {"name": "../private.safetensors", "strength": 1.0},
        ),
    )
    assert [
        (item.filename, item.strengths.model, item.strengths.clip) for item in structured_records
    ] == [("default-clip.safetensors", 0.8, 0.8)]
    assert structured_issues == (
        ScanIssue(
            "resource_value_unsafe_or_invalid",
            node_id="1",
            input_name="loras_3",
        ),
    )


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (None, 0.5, 0.5),
        (True, 0.5, None),
        (2, 0.5, 2.0),
        (0.25, 0.5, 0.25),
        (" 0.75 ", 0.5, 0.75),
        ("not-a-number", 0.5, None),
        (float("inf"), 0.5, None),
        (object(), 0.5, None),
    ],
)
def test_nd_super_float_matches_source_numeric_contract(
    value: object,
    default: float,
    expected: float | None,
) -> None:
    assert _nd_super_float(value, default=default) == expected


def test_nd_super_lora_bundle_is_bounded_strict_and_source_compatible() -> None:
    assert _nd_super_lora_resources(_node("0", "LoraLoader")) == ((), ())

    node = _node(
        "1",
        "NdSuperLoraLoader",
        {
            "lora_bundle": (
                '[null,{"lora":"loras/first.safetensors","enabled":true,'
                '"strength":"0.75","strengthTwo":"0.25"},'
                '{"lora":"second.safetensors","on":true},'
                '{"lora":"disabled.safetensors","enabled":false},'
                '{"lora":"zero.safetensors","enabled":true,"strength":0,'
                '"strengthClip":0},{"enabled":true},'
                '{"lora":"bad-strength.safetensors","enabled":true,'
                '"strength":"bad"},{"lora":"../private.safetensors",'
                '"enabled":true}]'
            )
        },
    )

    records, issues = _nd_super_lora_resources(node)

    assert [record.filename for record in records] == ["first.safetensors", "second.safetensors"]
    assert [
        (record.strengths.weight, record.strengths.model, record.strengths.clip)
        for record in records
    ] == [(0.75, 0.75, 0.0), (1.0, 1.0, 0.0)]
    assert issues == (
        ScanIssue(
            "nd_super_lora_strength_invalid",
            node_id="1",
            input_name="lora_bundle_7",
        ),
        ScanIssue(
            "resource_value_unsafe_or_invalid",
            node_id="1",
            input_name="lora_bundle_8",
        ),
    )

    malformed_entries, malformed_issues = _nd_super_lora_entries(
        _node("2", "NdSuperLoraLoader", {"lora_bundle": "[{"})
    )
    assert malformed_entries == ()
    assert malformed_issues == (ScanIssue("nd_super_lora_bundle_invalid", node_id="2"),)

    constant_entries, constant_issues = _nd_super_lora_entries(
        _node("3", "NdSuperLoraLoader", {"lora_bundle": "[NaN]"})
    )
    assert constant_entries == ()
    assert constant_issues == (ScanIssue("nd_super_lora_bundle_invalid", node_id="3"),)

    object_entries, object_issues = _nd_super_lora_entries(
        _node("4", "NdSuperLoraLoader", {"lora_bundle": "{}"})
    )
    assert object_entries == ()
    assert object_issues == (ScanIssue("nd_super_lora_bundle_not_list", node_id="4"),)

    large_entries, large_issues = _nd_super_lora_entries(
        _node(
            "5",
            "NdSuperLoraLoader",
            {"lora_bundle": " " + "x" * _MAX_ND_SUPER_LORA_BUNDLE_CHARS},
        )
    )
    assert large_entries == ()
    assert large_issues == (ScanIssue("nd_super_lora_bundle_too_large", node_id="5"),)


def test_nd_super_lora_legacy_mapping_remains_supported() -> None:
    records, issues = _nd_super_lora_resources(
        _node(
            "6",
            "NdSuperLoraLoader",
            {
                "clip": _frozen(["1", 1]),
                "lora_bundle": "",
                "lora_2": _frozen(
                    {
                        "lora": "legacy.safetensors",
                        "enabled": True,
                        "strength": 0.6,
                        "strengthClip": 0.4,
                    }
                ),
                "not_a_lora": _frozen({"lora": "ignored.safetensors", "enabled": True}),
            },
        )
    )
    assert issues == ()
    assert [
        (record.filename, record.strengths.model, record.strengths.clip) for record in records
    ] == [("legacy.safetensors", 0.6, 0.4)]


def test_text_and_indexed_resources_cover_edge_contracts() -> None:
    assert _text_lora_resources(_node("2", "ttN pipeLoader")) == ((), ())

    tags = " ".join(f"<lora:loras/item-{index}.safetensors:0.5>" for index in range(1, 67))
    text_records, text_issues = _text_lora_resources(
        _node(
            "3",
            "ttN pipeLoader",
            {
                "text": (
                    "<lora:loras/duplicate.safetensors:0.5> "
                    "<lora:loras/duplicate.safetensors:0.5> "
                    f"{tags}"
                )
            },
        )
    )
    assert text_issues == ()
    assert len(text_records) == MAX_STACK_LORAS
    assert text_records[0].filename == "duplicate.safetensors"
    invalid_text_records, invalid_text_issues = _text_lora_resources(
        _node(
            "31",
            "ttN pipeLoader",
            {"text": "<lora:../private.safetensors:0.5>"},
        )
    )
    assert invalid_text_records == ()
    assert invalid_text_issues == (
        ScanIssue(
            "resource_value_unsafe_or_invalid",
            node_id="31",
            input_name="inline_lora_1",
        ),
    )

    assert _indexed_resource_records(
        _node(
            "4",
            "CR Multi ControlNet Stack",
            {"toggle": False, "controlnet_1": "controlnet/unused.safetensors"},
        )
    ) == ((), ())
    indexed_records, indexed_issues = _indexed_resource_records(
        _node(
            "5",
            "CR Multi ControlNet Stack",
            {
                "num_controlnet": 3,
                "controlnet_1": "None",
                "controlnet_2": "../private.safetensors",
                "controlnet_3": "controlnet/active.safetensors",
                "controlnet_strength_3": 0.55,
            },
        )
    )
    assert [(item.filename, item.strengths.weight) for item in indexed_records] == [
        ("active.safetensors", 0.55)
    ]
    assert indexed_issues == (
        ScanIssue(
            "resource_value_unsafe_or_invalid",
            node_id="5",
            input_name="controlnet_2",
        ),
    )


def test_node_family_classifiers_are_conservative() -> None:
    assert compact_class("Power Lora Loader (rgthree)") == "powerloraloaderrgthree"
    assert is_sampler_node(_node("1", "KSampler"))
    assert not is_sampler_node(_node("1", "KSamplerSelect"))
    assert is_decode_node(_node("1", "VAEDecode"))
    assert is_text_encode_node(_node("1", "CustomTextEncode"))
    assert is_empty_latent_node(_node("1", "EmptySD3LatentImage"))
    assert is_image_latent_node(_node("1", "InpaintModelConditioning"))
    assert is_image_source_node(_node("1", "EmptyImage"))
    assert is_image_source_node(_node("1", "LoadImage"))
    assert not is_image_source_node(_node("1", "CustomImageProvider"))
    assert is_primitive_node(_node("1", "FloatValue"))
    assert is_primitive_node(_node("1", "PromptLoraManager"))
    assert is_primitive_node(_node("1", "StringConstantMultiline"))
    assert is_runtime_text_generator_node(_node("1", "TextGenerate"))
    assert not is_runtime_text_generator_node(_node("1", "UnrelatedNode"))
    assert is_base_model_loader(
        _node("1", "CheckpointLoaderSimple", {"ckpt_name": "model.safetensors"})
    )
    assert resource_input_specs(_node("1", "Power Lora Loader (rgthree)")) == ()
    assert resource_input_specs(_node("1", "UnrelatedNode")) == ()
    assert is_known_active_node(_node("1", "BasicScheduler"))
    assert is_known_active_node(_node("1", "HiDreamO1ReferenceImages"))
    assert is_known_active_node(_node("1", "ReferenceLatent"))
    assert is_known_active_node(_node("1", "ClownSampler_Beta"))
    assert not is_known_active_node(_node("1", "UnrelatedNode"))


@pytest.mark.parametrize(
    "class_type",
    (
        "GeminiNodeV2",
        "ImpactWildcardProcessor",
        "LTXVGemmaEnhancePrompt",
        "LTXVPromptEnhancer",
        "PMS_GeminiChatV3",
        "TextGenerate",
        "TextGenerateLTX2Prompt",
        "WanVideoPromptExtender",
        "WanVideoPromptExtenderSelect",
    ),
)
def test_verified_runtime_text_generators_are_known(class_type: str) -> None:
    node = _node("1", class_type)

    assert is_runtime_text_generator_node(node)
    assert is_known_active_node(node)


@pytest.mark.parametrize(
    "class_type",
    (
        "BLIP Model Loader",
        "CheckpointPerturbWeights",
        "CLIPSeg Model Loader",
        "ClownStyle_UNet",
        "FantasyTalkingModelLoader",
        "LTXVPatcherVAE",
        "MiDaS Model Loader",
        "MultiTalkModelLoader",
        "SAM Model Loader",
        "SelectVAEDevice",
        "TorchCompileVAE",
        "UNetCrossAttentionMultiply",
        "VAEStyleTransferLatent",
        "WanCameraEmbedding",
        "Wav2VecModelLoader",
        "WhisperModelLoader",
    ),
)
def test_source_reviewed_non_resource_nodes_are_known_without_resource_specs(
    class_type: str,
) -> None:
    node = _node("1", class_type)

    assert is_known_active_node(node)
    assert resource_input_specs(node) == ()


def test_generic_sampler_requires_topology_evidence() -> None:
    assert is_sampler_node(
        _node(
            "1",
            "VendorSamplerStage",
            {"model_input": ("model", 0), "steps_to_run": 12},
        )
    )
    assert not is_sampler_node(_node("1", "VendorSamplerStage", {"model_input": ("model", 0)}))
    assert not is_sampler_node(_node("1", "VendorSamplerStage", {"steps_to_run": 12}))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, None),
        (2, 2.0),
        (math.inf, None),
        ("2", None),
    ],
)
def test_resource_float_conversion(value: object, expected: float | None) -> None:
    assert _float_value(_frozen(value)) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (" YES ", True),
        ("disabled", False),
        ("maybe", None),
        (1, None),
    ],
)
def test_resource_boolean_conversion(value: object, expected: bool | None) -> None:
    assert _bool_value(_frozen(value)) is expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "",
        "x" * 513,
        r"C:\private\model.safetensors",
        r"\rooted\model.safetensors",
        "/rooted/model.safetensors",
        "../model.safetensors",
        "folder/../model.safetensors",
        "folder:model.safetensors",
        "folder/control\nmodel.safetensors",
    ],
)
def test_resource_value_rejects_private_or_unsafe_values(value: object) -> None:
    assert _safe_resource_value(_frozen(value)) is None


def test_resource_value_normalizes_relative_windows_separator_and_unicode() -> None:
    assert _safe_resource_value("loras\\cafe\u0301.safetensors") == (
        "loras/café.safetensors",
        "café.safetensors",
    )


def test_direct_resource_skips_links_and_reports_unsafe_value() -> None:
    linked = _node(
        "1",
        "CheckpointLoaderSimple",
        {"ckpt_name": ("2", 0)},
    )
    unsafe = _node(
        "2",
        "CheckpointLoaderSimple",
        {"ckpt_name": "../private.safetensors"},
    )

    linked_records, linked_issues = _direct_resources(linked)
    unsafe_records, unsafe_issues = _direct_resources(unsafe)

    assert linked_records == ()
    assert linked_issues == ()
    assert unsafe_records == ()
    assert unsafe_issues == (
        ScanIssue(
            "resource_value_unsafe_or_invalid",
            node_id="2",
            input_name="ckpt_name",
        ),
    )


def test_direct_resource_preserves_all_explicit_lora_strengths() -> None:
    node = _node(
        "1",
        "LoraLoader",
        {
            "lora_name": "loras/a.safetensors",
            "strength": 0.5,
            "strength_model": 0.75,
            "strength_clip": 0.25,
        },
    )

    records, issues = _direct_resources(node)

    assert issues == ()
    assert records[0].strengths.weight == LORA_WEIGHT
    assert records[0].strengths.model == LORA_MODEL_STRENGTH
    assert records[0].strengths.clip == LORA_CLIP_STRENGTH


def test_power_lora_ignores_non_entries_and_reports_invalid_enabled_entry() -> None:
    node = _node(
        "1",
        "Power Lora Loader (rgthree)",
        {
            "other": "not an entry",
            "lora_text": "not a mapping",
            "lora_disabled": MappingProxyType({"on": "off", "lora": "loras/disabled.safetensors"}),
            "lora_invalid": MappingProxyType({"on": "on", "lora": "../private.safetensors"}),
        },
    )

    records, issues = _power_lora_resources(node)

    assert records == ()
    assert issues == (
        ScanIssue(
            "resource_value_unsafe_or_invalid",
            node_id="1",
            input_name="lora_invalid",
        ),
    )
    assert _power_lora_resources(_node("2", "LoraLoader")) == ((), ())


def test_extract_active_resources_orders_nodes_numerically() -> None:
    nodes = {
        "10": _node(
            "10",
            "VAELoader",
            {"vae_name": "vae/second.safetensors"},
        ),
        "2": _node(
            "2",
            "CheckpointLoaderSimple",
            {"ckpt_name": "models/first.safetensors"},
        ),
    }

    index = GraphIndex(
        MappingProxyType(nodes),
        MappingProxyType({}),
        MappingProxyType({}),
        (),
    )
    resources, issues = extract_active_resources(index, _active("10", "2"))

    assert issues == ()
    assert [resource.node_id for resource in resources] == ["2", "10"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (0, False),
        (1, True),
        (" enable ", True),
        ("disabled", False),
        ("unknown", None),
    ],
)
def test_routing_boolean_literals(value: object, expected: bool | None) -> None:
    assert _literal_bool(_frozen(value)) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, None),
        (2, 2),
        (" 3 ", 3),
        ("-1", None),
        ("blue", None),
        (1.5, None),
    ],
)
def test_routing_index_literals(value: object, expected: int | None) -> None:
    assert _literal_index(_frozen(value)) == expected


def _routing_index(prompt: object) -> GraphIndex:
    return build_graph_index(normalize_api_prompt(prompt))


@pytest.mark.parametrize(
    ("node", "reason"),
    [
        (
            {"class_type": "LonelySwitch", "inputs": {"input1": ["1", 0]}},
            "selector_missing",
        ),
        (
            {
                "class_type": "BooleanSwitch",
                "inputs": {"switch": 3, "on_true": ["1", 0], "on_false": ["1", 0]},
            },
            "selector_value_unresolved",
        ),
        (
            {
                "class_type": "ModelChooser",
                "inputs": {"select": 1, "input1": "literal"},
            },
            "selected_input_not_linked",
        ),
        (
            {
                "class_type": "ModelSelector",
                "inputs": {"select": 1.5, "input1": ["1", 0]},
            },
            "selector_value_unresolved",
        ),
    ],
)
def test_routing_ambiguity_reasons_are_stable(
    node: dict[str, object],
    reason: str,
) -> None:
    prompt = {
        "1": {"class_type": "PrimitiveInt", "inputs": {"value": 1}},
        "2": node,
    }
    index = _routing_index(prompt)
    _, decision = selected_upstream_edges(index, index.nodes["2"])

    assert decision is not None
    assert decision.status is RoutingStatus.AMBIGUOUS
    assert decision.reason == reason


def test_routing_false_boolean_and_string_index_select_expected_edges() -> None:
    false_prompt = {
        "1": {"class_type": "PrimitiveInt", "inputs": {"value": 1}},
        "2": {"class_type": "PrimitiveInt", "inputs": {"value": 2}},
        "3": {
            "class_type": "BooleanSwitch",
            "inputs": {"switch": False, "on_true": ["1", 0], "on_false": ["2", 0]},
        },
    }
    index_prompt = {
        "1": {"class_type": "PrimitiveInt", "inputs": {"value": 1}},
        "2": {
            "class_type": "ModelSelector",
            "inputs": {"index": "1", "input1opt": ["1", 0]},
        },
    }

    false_index = _routing_index(false_prompt)
    selected_false, _ = selected_upstream_edges(false_index, false_index.nodes["3"])
    string_index = _routing_index(index_prompt)
    selected_index, _ = selected_upstream_edges(string_index, string_index.nodes["2"])

    assert [edge.source_node_id for edge in selected_false] == ["2"]
    assert [edge.source_node_id for edge in selected_index] == ["1"]


def test_routing_supports_boolean_alias_was_ab_and_extra_index_prefixes() -> None:
    was_prompt = {
        "1": {"class_type": "PrimitiveInt", "inputs": {"value": 1}},
        "2": {"class_type": "PrimitiveInt", "inputs": {"value": 2}},
        "3": {
            "class_type": "Model Input Switch",
            "inputs": {
                "boolean": True,
                "model_a": ["1", 0],
                "model_b": ["2", 0],
            },
        },
    }
    indexed_prompt = {
        "1": {"class_type": "PrimitiveInt", "inputs": {"value": 1}},
        "2": {"class_type": "PrimitiveInt", "inputs": {"value": 2}},
        "3": {
            "class_type": "CR Pipe Switch",
            "inputs": {
                "select": ["4", 0],
                "pipe1": ["1", 0],
                "pipe2": ["2", 0],
            },
        },
        "4": {"class_type": "PrimitiveInt", "inputs": {"value": 2}},
    }

    was_index = _routing_index(was_prompt)
    selected_was, was_decision = selected_upstream_edges(was_index, was_index.nodes["3"])
    indexed_index = _routing_index(indexed_prompt)
    selected_indexed, indexed_decision = selected_upstream_edges(
        indexed_index,
        indexed_index.nodes["3"],
    )

    assert [edge.source_node_id for edge in selected_was] == ["1"]
    assert was_decision is not None
    assert was_decision.status is RoutingStatus.RESOLVED
    assert [edge.source_node_id for edge in selected_indexed] == ["2"]
    assert indexed_decision is not None
    assert indexed_decision.status is RoutingStatus.RESOLVED


def test_selector_de_imagenes_routes_only_enabled_image_and_mask_slots() -> None:
    prompt = {str(slot): {"class_type": "Source", "inputs": {}} for slot in range(1, 7)}
    prompt["10"] = {
        "class_type": "SelectorDeImagenes",
        "inputs": {
            "fallback": "error",
            "mode": "auto",
            "img1": ["1", 0],
            "mask1": ["2", 0],
            "on1": False,
            "img2": ["3", 0],
            "mask2": ["4", 0],
            "on2": True,
            "img3": ["5", 0],
            "mask3": ["6", 0],
            "on3": False,
        },
    }
    index = _routing_index(prompt)

    selected, decision = selected_upstream_edges(index, index.nodes["10"])

    assert [(edge.source_node_id, edge.input_name) for edge in selected] == [
        ("3", "img2"),
        ("4", "mask2"),
    ]
    assert decision is not None
    assert decision.status is RoutingStatus.RESOLVED
    assert decision.selected_input_names == ("img2", "mask2")


def test_selector_de_imagenes_slot1_fallback_and_linked_control_ambiguity() -> None:
    fallback_prompt = {
        "1": {"class_type": "Source", "inputs": {}},
        "2": {"class_type": "Source", "inputs": {}},
        "3": {
            "class_type": "SelectorDeImagenes",
            "inputs": {
                "fallback": "slot1",
                "mode": "auto",
                "img1": ["1", 0],
                "mask1": ["2", 0],
                "on1": False,
            },
        },
    }
    ambiguous_prompt = {
        **fallback_prompt,
        "3": {
            "class_type": "SelectorDeImagenes",
            "inputs": {
                "fallback": "slot1",
                "mode": "auto",
                "img1": ["1", 0],
                "mask1": ["2", 0],
                "on1": ["4", 0],
            },
        },
        "4": {"class_type": "RuntimeBoolean", "inputs": {}},
    }

    fallback_index = _routing_index(fallback_prompt)
    selected, decision = selected_upstream_edges(fallback_index, fallback_index.nodes["3"])
    ambiguous_index = _routing_index(ambiguous_prompt)
    ambiguous, ambiguous_decision = selected_upstream_edges(
        ambiguous_index,
        ambiguous_index.nodes["3"],
    )

    assert [(edge.source_node_id, edge.input_name) for edge in selected] == [
        ("1", "img1"),
        ("2", "mask1"),
    ]
    assert decision is not None
    assert decision.status is RoutingStatus.RESOLVED
    assert {edge.source_node_id for edge in ambiguous} == {"1", "2", "4"}
    assert ambiguous_decision is not None
    assert ambiguous_decision.status is RoutingStatus.AMBIGUOUS
    assert ambiguous_decision.reason == "selector_value_unresolved"


def test_runtime_reload_nodes_do_not_claim_unproven_fallback_lineage() -> None:
    index = _routing_index(
        {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
            "2": {
                "class_type": "ReloadModel",
                "inputs": {
                    "filename": "cycle/model",
                    "fallback_m": ["1", 0],
                },
            },
        }
    )

    selected, decision = selected_upstream_edges(index, index.nodes["2"])

    assert selected == ()
    assert decision is not None
    assert decision.status is RoutingStatus.RESOLVED
    assert decision.reason == "runtime_payload_provenance_unavailable"


def _scalar_graph(
    prompt: dict[str, dict[str, object]],
    *active_node_ids: str,
) -> tuple[GraphIndex, ActiveGraph]:
    index = _routing_index(prompt)
    return index, _active(*active_node_ids)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (4, 4),
        (2.5, 2.5),
        ("text", "text"),
        ((1, 2, 3), None),
        (("1", 0), None),
    ],
)
def test_literal_scalar_values(value: object, expected: object) -> None:
    assert literal_scalar(_frozen(value)) == expected


def test_scalar_resolver_rejects_inactive_missing_nonprimitive_and_cycle() -> None:
    index, active = _scalar_graph(
        {
            "1": {"class_type": "PrimitiveInt", "inputs": {"value": 5}},
            "2": {"class_type": "Unknown", "inputs": {"value": 6}},
            "3": {"class_type": "Reroute", "inputs": {"value": ["3", 0]}},
            "4": {"class_type": "Reroute", "inputs": {}},
        },
        "2",
        "3",
        "4",
        "404",
    )

    assert resolve_scalar(index, active, ("1", 0)) is None
    assert resolve_scalar(index, active, ("404", 0)) is None
    assert resolve_scalar(index, active, ("2", 0)) is None
    assert resolve_scalar(index, active, ("3", 0)) is None
    assert resolve_scalar(index, active, ("4", 0)) is None
    assert resolve_scalar(index, active, ("not-a-link",)) is None


def test_scalar_resolver_enforces_reference_depth_and_fallback_input_order() -> None:
    prompt: dict[str, dict[str, object]] = {
        str(index): {
            "class_type": "Reroute",
            "inputs": {"other": [str(index + 1), 0]},
        }
        for index in range(1, 10)
    }
    prompt["10"] = {"class_type": "PrimitiveInt", "inputs": {"value": RESOLVED_SCALAR}}
    index, active = _scalar_graph(prompt, *(str(item) for item in range(1, 11)))

    assert resolve_scalar(index, active, ("1", 0), preferred_input_names=("missing",)) is None
    assert (
        resolve_scalar(index, active, ("3", 0), preferred_input_names=("missing",))
        == RESOLVED_SCALAR
    )


def test_resolve_node_input_handles_none_missing_and_unresolved_before_value() -> None:
    node = _node(
        "1",
        "Node",
        {"first": ("404", 0), "second": "resolved"},
    )
    index = GraphIndex(
        MappingProxyType({"1": node}),
        MappingProxyType({}),
        MappingProxyType({}),
        (),
    )
    active = _active("1")

    assert resolve_node_input(index, active, None, ("value",)) is None
    assert resolve_node_input(index, active, node, ("missing",)) is None
    assert resolve_node_input(index, active, node, ("first", "second")) == "resolved"


def _deterministic_output(
    class_type: str,
    inputs: dict[str, object],
    output_index: int = 0,
) -> object:
    index, active = _scalar_graph(
        {"1": {"class_type": class_type, "inputs": inputs}},
        "1",
    )
    return resolve_node_output(index, active, index.nodes["1"], output_index)


@pytest.mark.parametrize(
    ("class_type", "inputs", "output_index", "expected"),
    [
        ("easy prompt", {"text": "plain prompt"}, 0, "plain prompt"),
        ("easy prompt", {"text": "plain prompt"}, 1, None),
        (
            "easy promptConcat",
            {"prompt1": "one", "prompt2": "two", "separator": " + "},
            0,
            "one + two",
        ),
        (
            "CR Text Concatenate",
            {"text1": "one", "text2": "two", "separator": "\n"},
            0,
            "one\ntwo",
        ),
        (
            "easy promptReplace",
            {
                "prompt": "cat red sky",
                "find1": "cat",
                "replace1": "dog",
                "find2": "red",
                "replace2": "blue",
                "find3": "sky",
                "replace3": "room",
            },
            0,
            "dog blue room",
        ),
        (
            "CR Text Replace",
            {
                "text": "cat",
                "find1": "cat",
                "replace1": "dog",
                "find2": "",
                "replace2": "",
                "find3": "",
                "replace3": "",
            },
            0,
            "dog",
        ),
        (
            "CR Combine Prompt",
            {
                "part1": "one",
                "part2": "two",
                "part3": "",
                "part4": "four",
                "separator": ", ",
            },
            0,
            "one, two, , four",
        ),
        ("TextBox1", {"text1": "box"}, 0, "box"),
        ("TextBox2", {"text2": "box"}, 0, "box"),
        (
            "DiffusionModelSelector",
            {"model_name": "diffusion_models/selected.safetensors"},
            0,
            "diffusion_models/selected.safetensors",
        ),
        ("UnknownCustomNode", {"value": "do not execute"}, 0, None),
    ],
)
def test_deterministic_text_provider_outputs(
    class_type: str,
    inputs: dict[str, object],
    output_index: int,
    expected: object,
) -> None:
    assert _deterministic_output(class_type, inputs, output_index) == expected


def test_rgthree_seed_output_resolves_fixed_seed_only() -> None:
    assert _deterministic_output("Seed (rgthree)", {"seed": RGTHREE_SEED}) == RGTHREE_SEED
    assert _deterministic_output("Seed (rgthree)", {"seed": RGTHREE_SEED}, 1) is None


@pytest.mark.parametrize("sentinel", [-1, -2, -3])
def test_rgthree_dynamic_seed_sentinels_remain_unknown(sentinel: int) -> None:
    assert _deterministic_output("Seed (rgthree)", {"seed": sentinel}) is None


def test_impact_string_selector_matches_installed_line_and_block_semantics() -> None:
    assert (
        _deterministic_output(
            "ImpactStringSelector",
            {
                "strings": "zero\none\ntwo",
                "multiline": False,
                "select": 4,
            },
        )
        == "one"
    )
    assert (
        _deterministic_output(
            "ImpactStringSelector",
            {
                "strings": "#first\nline one\n#second\nline two",
                "multiline": True,
                "select": 1,
            },
        )
        == "second\nline two"
    )
    index = _routing_index(
        {
            "1": {"class_type": "PrimitiveString", "inputs": {"value": "prompt"}},
            "2": {
                "class_type": "ImpactStringSelector",
                "inputs": {
                    "strings": ["1", 0],
                    "multiline": False,
                    "select": 0,
                },
            },
        }
    )
    selected, decision = selected_upstream_edges(index, index.nodes["2"])
    assert [edge.source_node_id for edge in selected] == ["1"]
    assert decision is None


def test_selector_de_prompts_combines_enabled_nonempty_slots_and_fallback() -> None:
    base: dict[str, object] = {
        "fallback": "p1",
        "join_with": r"\n",
        "mode": "auto",
        **{f"on{slot}": slot in {1, 3} for slot in range(1, 13)},
        **{f"p{slot}": "" for slot in range(1, 13)},
        "p1": " first ",
        "p3": " third ",
    }
    assert _deterministic_output("SelectorDePrompts", base) == "first\nthird"

    fallback = {
        **base,
        **{f"on{slot}": False for slot in range(1, 13)},
        "p1": " fallback text ",
    }
    assert _deterministic_output("SelectorDePrompts", fallback) == "fallback text"
    assert _deterministic_output("SelectorDePrompts", {**base, "mode": "single_only"}) is None
    assert _deterministic_output("SelectorDePrompts", {**base, "on2": ["404", 0]}) is None


def test_deterministic_text_providers_reject_unresolved_or_wrong_outputs() -> None:
    assert (
        _deterministic_output(
            "easy promptConcat",
            {"prompt1": "one", "prompt2": "two", "separator": " "},
            1,
        )
        is None
    )
    assert (
        _deterministic_output(
            "easy promptConcat",
            {"prompt1": ["404", 0], "prompt2": "two", "separator": " "},
        )
        is None
    )
    assert (
        _deterministic_output(
            "easy promptReplace",
            {"prompt": "cat", "find1": "cat", "replace1": "dog"},
            1,
        )
        is None
    )
    assert (
        _deterministic_output(
            "easy promptReplace",
            {"prompt": ["404", 0], "find1": "cat", "replace1": "dog"},
        )
        is None
    )
    assert (
        _deterministic_output(
            "easy promptReplace",
            {
                "prompt": "cat",
                "find1": ["404", 0],
                "replace1": "dog",
            },
        )
        is None
    )
    assert (
        _deterministic_output(
            "CR Combine Prompt",
            {"part1": ["404", 0], "separator": ", "},
        )
        is None
    )
    assert _deterministic_output("CR Combine Prompt", {}, 1) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("'one', 'two'", "one\ntwo"),
        ('"one", "two"', "one\ntwo"),
        ("one,'two'", "one\ntwo"),
        ('one,"two"', "one\ntwo"),
        ("one", ""),
    ],
)
def test_cr_multiline_split_variants(text: str, expected: str) -> None:
    assert (
        _deterministic_output(
            "CR Multiline Text",
            {
                "text": text,
                "convert_from_csv": False,
                "split_string": True,
                "remove_chars": False,
                "csv_quote_char": "'",
                "chars_to_remove": "",
            },
        )
        == expected
    )


def test_cr_multiline_csv_plain_and_invalid_options() -> None:
    assert _deterministic_output("CR Multiline Text", {"text": "one"}, 1) is None
    assert (
        _deterministic_output(
            "CR Multiline Text",
            {
                "text": "'one','two'",
                "convert_from_csv": True,
                "split_string": False,
                "remove_chars": False,
                "csv_quote_char": "'",
                "chars_to_remove": "",
            },
        )
        == "one\ntwo"
    )
    assert (
        _deterministic_output(
            "CR Multiline Text",
            {
                "text": "\n# comment\none!\ntwo!\n",
                "convert_from_csv": "invalid",
                "split_string": "invalid",
                "remove_chars": True,
                "csv_quote_char": "'",
                "chars_to_remove": "!",
            },
        )
        == "one\ntwo"
    )
    assert _deterministic_output("CR Multiline Text", {"text": 1}) is None
    assert (
        _deterministic_output(
            "CR Multiline Text",
            {"text": "one", "csv_quote_char": "|"},
        )
        is None
    )
    assert (
        _deterministic_output(
            "CR Multiline Text",
            {
                "text": "'unterminated",
                "convert_from_csv": True,
                "csv_quote_char": "'",
            },
        )
        is None
    )


def test_deterministic_dimension_providers() -> None:
    assert (
        _deterministic_output(
            "ResolutionSelector",
            {"aspect_ratio": "16:9", "megapixels": 1.0, "multiple": 64},
            0,
        ),
        _deterministic_output(
            "ResolutionSelector",
            {"aspect_ratio": "16:9", "megapixels": 1.0, "multiple": 64},
            1,
        ),
    ) == RESOLUTION_SELECTOR_SIZE
    assert (
        _deterministic_output(
            "DimensionSelectorWithSeedNode",
            {
                "resolution": 1024,
                "min_ratio": 0.6,
                "max_ratio": 1.6,
                "multiples": 32,
                "seed": 42,
            },
            0,
        ),
        _deterministic_output(
            "DimensionSelectorWithSeedNode",
            {
                "resolution": 1024,
                "min_ratio": 0.6,
                "max_ratio": 1.6,
                "multiples": 32,
                "seed": 42,
            },
            1,
        ),
    ) == SEEDED_DIMENSIONS
    assert (
        _deterministic_output("CM_SDXLResolution", {"resolution": "1024 x 768"}, 0),
        _deterministic_output(
            "CM_SDXLExtendedResolution",
            {"resolution": "1024 x 768"},
            1,
        ),
    ) == CM_DIMENSIONS
    assert (
        _deterministic_output("SetImageSize", {"width": 800, "height": 600}, 0),
        _deterministic_output("SetImageSize", {"width": 800, "height": 600}, 1),
    ) == BASE_DIMENSIONS
    assert (
        _deterministic_output(
            "SetImageSizeWithScale",
            {"width": 800, "height": 600, "scale_by": 1.5},
            2,
        ),
        _deterministic_output(
            "SetImageSizeWithScale",
            {"width": 800, "height": 600, "scale_by": 1.5},
            3,
        ),
    ) == SCALED_DIMENSIONS
    assert (
        _deterministic_output(
            "SetImageSizeWithScale",
            {"width": 800, "height": 600, "scale_by": 1.5},
            0,
        ),
        _deterministic_output(
            "SetImageSizeWithScale",
            {"width": 800, "height": 600, "scale_by": 1.5},
            1,
        ),
    ) == BASE_DIMENSIONS
    assert (
        _deterministic_output(
            "Ideogram4PromptBuilderKJ",
            {"width": 832, "height": 1216},
            3,
        ),
        _deterministic_output(
            "Ideogram4PromptBuilderKJ",
            {"width": 832, "height": 1216},
            4,
        ),
    ) == IDEOGRAM_DIMENSIONS


def test_seeded_dimensions_cover_both_rounding_adjustments() -> None:
    assert (
        _deterministic_output(
            "DimensionSelectorWithSeedNode",
            {
                "resolution": 1024,
                "min_ratio": 0.6,
                "max_ratio": 1.6,
                "multiples": 32,
                "seed": 0,
            },
            0,
        ),
        _deterministic_output(
            "DimensionSelectorWithSeedNode",
            {
                "resolution": 1024,
                "min_ratio": 0.6,
                "max_ratio": 1.6,
                "multiples": 32,
                "seed": 0,
            },
            1,
        ),
    ) == (1216, 832)


@pytest.mark.parametrize(
    ("class_type", "inputs", "expected"),
    [
        (
            "CR Aspect Ratio",
            {
                "width": 512,
                "height": 768,
                "aspect_ratio": "custom",
                "swap_dimensions": "Off",
                "prescale_factor": 2.0,
            },
            (1024, 1536),
        ),
        (
            "CR Aspect Ratio",
            {
                "width": 1,
                "height": 1,
                "aspect_ratio": "Landscape - 16:9 - 1024x576",
                "swap_dimensions": "On",
                "prescale_factor": 1.0,
            },
            (576, 1024),
        ),
        (
            "CR SDXL Aspect Ratio",
            {
                "width": 1,
                "height": 1,
                "aspect_ratio": "Portrait - 832x1216",
                "swap_dimensions": "Off",
            },
            (832, 1216),
        ),
        (
            "CR Aspect Ratio Banners",
            {
                "width": 1,
                "height": 1,
                "aspect_ratio": "Banner - 468x60",
                "swap_dimensions": "Off",
                "prescale_factor": 2.0,
            },
            (336, 120),
        ),
        (
            "CR Aspect Ratio Social Media",
            {
                "width": 1,
                "height": 1,
                "aspect_ratio": "LinkedIn Page Cover - 1128x191",
                "swap_dimensions": "On",
                "prescale_factor": 1.0,
            },
            (396, 1584),
        ),
        ("CR Select ISO Size", {"iso_size": "A4 - 2480x3508"}, (2480, 3508)),
    ],
)
def test_comfyroll_dimension_outputs(
    class_type: str,
    inputs: dict[str, object],
    expected: tuple[int, int],
) -> None:
    assert (
        _deterministic_output(class_type, inputs, 0),
        _deterministic_output(class_type, inputs, 1),
    ) == expected


@pytest.mark.parametrize(
    ("class_type", "inputs", "output_index"),
    [
        ("ResolutionSelector", {"aspect_ratio": "bad", "megapixels": 1.0, "multiple": 64}, 0),
        ("ResolutionSelector", {"aspect_ratio": "1:1", "megapixels": 0, "multiple": 64}, 0),
        ("ResolutionSelector", {"aspect_ratio": "1:1", "megapixels": 1, "multiple": 0}, 0),
        ("ResolutionSelector", {"aspect_ratio": "1:1", "megapixels": 1, "multiple": 64}, 2),
        (
            "DimensionSelectorWithSeedNode",
            {
                "resolution": 0,
                "min_ratio": 1.0,
                "max_ratio": 1.0,
                "multiples": 32,
                "seed": 1,
            },
            0,
        ),
        (
            "DimensionSelectorWithSeedNode",
            {
                "resolution": 1,
                "min_ratio": 2_000_000.0,
                "max_ratio": 2_000_000.0,
                "multiples": 1,
                "seed": 1,
            },
            0,
        ),
        (
            "DimensionSelectorWithSeedNode",
            {
                "resolution": 32,
                "min_ratio": 1.0,
                "max_ratio": 1.0,
                "multiples": 64,
                "seed": 1,
            },
            0,
        ),
        (
            "DimensionSelectorWithSeedNode",
            {
                "resolution": 1024,
                "min_ratio": 0.6,
                "max_ratio": 1.6,
                "multiples": 32,
                "seed": 1,
            },
            2,
        ),
        ("CM_SDXLResolution", {"resolution": "bad"}, 0),
        ("CM_SDXLResolution", {"resolution": "1024 x 768"}, 2),
        ("SetImageSize", {"width": 1, "height": 1}, 2),
        ("SetImageSizeWithScale", {"width": 1, "height": 1}, 4),
        ("SetImageSizeWithScale", {"width": 1, "height": 1}, 2),
        ("SetImageSizeWithScale", {"width": ["404", 0], "height": 1, "scale_by": 2}, 0),
        ("SetImageSizeWithScale", {"width": 1, "height": ["404", 0], "scale_by": 2}, 0),
        ("Ideogram4PromptBuilderKJ", {"width": 1, "height": 1}, 2),
        ("CR Select ISO Size", {"iso_size": "bad"}, 0),
        ("CR Select ISO Size", {"iso_size": "A4 - 2480x3508"}, 2),
        (
            "CR Aspect Ratio",
            {"width": 1, "height": 1, "aspect_ratio": "bad", "prescale_factor": 1.0},
            0,
        ),
        (
            "CR Aspect Ratio",
            {
                "width": ["404", 0],
                "height": 1,
                "aspect_ratio": "custom",
                "prescale_factor": 1.0,
            },
            0,
        ),
        (
            "CR Aspect Ratio",
            {
                "width": 1,
                "height": ["404", 0],
                "aspect_ratio": "custom",
                "prescale_factor": 1.0,
            },
            0,
        ),
        (
            "CR Aspect Ratio",
            {
                "width": 1,
                "height": 1,
                "aspect_ratio": ["404", 0],
                "prescale_factor": 1.0,
            },
            0,
        ),
        (
            "CR Aspect Ratio",
            {"width": 1, "height": 1, "aspect_ratio": "custom"},
            0,
        ),
    ],
)
def test_deterministic_dimension_providers_reject_invalid_contracts(
    class_type: str,
    inputs: dict[str, object],
    output_index: int,
) -> None:
    assert _deterministic_output(class_type, inputs, output_index) is None


def test_resolve_node_output_handles_missing_node_and_invalid_index() -> None:
    index, active = _scalar_graph({}, "1")

    assert resolve_node_output(index, active, None, 0) is None
    assert resolve_node_output(index, active, _node("1", "easy prompt", {"text": "x"}), -1) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        (2, 2),
        (2.0, 2),
        (2.5, None),
        (" +2 ", 2),
        ("2.5", None),
        ("bad", None),
    ],
)
def test_scalar_int_conversion(value: object, expected: int | None) -> None:
    assert scalar_int(cast(None | bool | int | float | str, value)) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        (2, 2.0),
        (2.5, 2.5),
        (" 2.5 ", 2.5),
        ("bad", None),
        ("inf", None),
    ],
)
def test_scalar_float_conversion(value: object, expected: float | None) -> None:
    assert scalar_float(cast(None | bool | int | float | str, value)) == expected


def test_scalar_float_rejects_non_scalar_runtime_value() -> None:
    assert scalar_float(cast(None | bool | int | float | str, ())) is None


def test_scalar_string_requires_nonempty_string() -> None:
    assert scalar_string("value") == "value"
    assert scalar_string("") is None
    assert scalar_string(1) is None


def test_extract_helpers_handle_missing_stage_and_node() -> None:
    index = GraphIndex(
        MappingProxyType({}),
        MappingProxyType({}),
        MappingProxyType({}),
        (),
    )
    active = _active()
    stage = StageSelection(None, ())

    assert _linked_node(index, active, None, "value") is None
    assert _latent_source(index, active, stage) == (None, ())
    assert _find_guidance(index, active, stage) is None
    assert extract_generation_settings(index, active, stage)[0].seed is None
    assert extract_prompts(index, active, stage)[0].positive.text is None


def test_extract_prompt_dimension_and_class_specific_helper_branches() -> None:
    index = _routing_index(
        {
            "1": {"class_type": "PrimitiveString", "inputs": {"value": "768 x 1024"}},
            "2": {
                "class_type": "EmptyLatentImage",
                "inputs": {"dimensions": ["1", 0]},
            },
            "3": {"class_type": "BasicPipe", "inputs": {}},
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "outside active graph"},
            },
            "5": {"class_type": "KSampler", "inputs": {"positive": ["4", 0]}},
        }
    )
    active = _active("1", "2", "3", "5")

    assert _branch_nodes(index, active, None, ("model",)) == ()
    assert _dimensions_from_node(index, active, index.nodes["2"]) == (768, 1024)
    assert _linked_prompt_root(active, index.nodes["5"], "positive") == (None, None, None)
    assert _linked_prompt_root(active, index.nodes["5"], "missing") == (None, None, None)
    assert _pipe_prompt_root(active, index.nodes["3"], "positive") == ("3", "pipe", None)

    assert _prompt_input_names(
        _node(
            "6",
            "SeargeSDXLPromptEncoder",
            {"pos_g": "g", "pos_l": "l", "pos_r": "r"},
        ),
        "positive",
        output_index=0,
    )
    assert _prompt_input_names(
        _node(
            "7",
            "ADE_PromptScheduling",
            {"prepend_text": "before", "prompts": "main", "append_text": "after"},
        ),
        "positive",
    ) == ("prepend_text", "prompts", "append_text")
    assert _prompt_input_names(
        _node(
            "8",
            "SDXL Power Prompt Positive (rgthree)",
            {"prompt_g": "g", "prompt_l": "l"},
        ),
        "positive",
    ) == ("prompt_g", "prompt_l")
    assert _prompt_input_names(
        _node(
            "9",
            "CR SDXL Base Prompt Encoder",
            {"pos_g": "g", "pos_l": "l", "neg_g": "ng", "neg_l": "nl"},
        ),
        "negative",
    ) == ("neg_g", "neg_l")
    assert _prompt_input_names(_node("10", "ImpactWildcardEncode"), "positive") == ()
    assert _extract_clip_skip(index, _active("404")) is None


def _antrobots_refiner_inputs(**overrides: FrozenValue) -> dict[str, FrozenValue]:
    values: dict[str, FrozenValue] = {
        "base_model": ("20", 0),
        "refiner_model": ("21", 0),
        "total_steps": 20,
        "refine_step": 10,
        "base_positive": ("22", 0),
        "base_negative": ("23", 0),
        "refine_positive": ("24", 0),
        "refine_negative": ("25", 0),
        "base_vae": ("26", 0),
        "refine_vae": ("27", 0),
        "base_denoise": 0.8,
        "refine_denoise": 0.6,
        "seed": 1,
        "cfg": 5.0,
        "sampler_name": "euler",
        "scheduler": "normal",
        "latent_image": ("28", 0),
    }
    values.update(overrides)
    return values


def test_antrobots_refiner_branch_selection_is_explicit_and_conservative() -> None:
    def evaluate(**overrides: FrozenValue) -> tuple[float | None, tuple[ScanIssue, ...]]:
        prompt = {"1": {"class_type": "refine", "inputs": _antrobots_refiner_inputs(**overrides)}}
        index = _routing_index(prompt)
        return _antrobots_refiner_denoise(index, _active("1"), index.nodes["1"])

    assert evaluate(refine_step=20) == (0.8, ())
    assert evaluate(refine_step=0) == (0.6, ())
    assert evaluate(base_denoise=0.7, refine_denoise=0.7) == (0.7, ())
    assert evaluate(
        total_steps=None,
        refine_step=None,
        base_denoise=0.7,
        refine_denoise=0.7,
    ) == (0.7, ())
    assert evaluate() == (None, (ScanIssue("denoise_ambiguous", node_id="1"),))

    prompt = {
        "1": {"class_type": "refine", "inputs": _antrobots_refiner_inputs(refine_step=20)},
        "22": {"class_type": "CLIPTextEncode", "inputs": {"text": "base"}},
        "24": {"class_type": "CLIPTextEncode", "inputs": {"text": "refine"}},
    }
    index = _routing_index(prompt)
    active = _active("1", "22", "24")
    assert _antrobots_prompt_roots(index, active, index.nodes["1"], "positive") == (
        ("22", "base_positive", 0),
    )

    zero_prompt = {
        "1": {"class_type": "refine", "inputs": _antrobots_refiner_inputs(refine_step=0)},
        "22": {"class_type": "CLIPTextEncode", "inputs": {"text": "base"}},
        "24": {"class_type": "CLIPTextEncode", "inputs": {"text": "refine"}},
    }
    zero_index = _routing_index(zero_prompt)
    assert _antrobots_prompt_roots(
        zero_index,
        _active("1", "22", "24"),
        zero_index.nodes["1"],
        "positive",
    ) == (("24", "refine_positive", 0),)

    unknown_prompt = {
        "1": {
            "class_type": "refine",
            "inputs": _antrobots_refiner_inputs(total_steps=None, refine_step=None),
        },
        "22": {"class_type": "CLIPTextEncode", "inputs": {"text": "base"}},
        "24": {"class_type": "CLIPTextEncode", "inputs": {"text": "refine"}},
    }
    unknown_index = _routing_index(unknown_prompt)
    assert _antrobots_prompt_roots(
        unknown_index,
        _active("1", "22", "24"),
        unknown_index.nodes["1"],
        "positive",
    ) == (
        ("22", "base_positive", 0),
        ("24", "refine_positive", 0),
    )


def test_prompt_root_provider_paths_and_missing_guidance_are_safe() -> None:
    index = _routing_index(
        {
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "prompt"}},
            "2": {"class_type": "SamplerSettings", "inputs": {}},
            "3": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {"sampler_inputs": ["2", 0]},
            },
            "4": {"class_type": "SamplerProvider", "inputs": {"positive": ["1", 0]}},
            "5": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {"base_sampler": ["4", 0]},
            },
            "6": {"class_type": "SamplerProvider", "inputs": {}},
            "7": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {"base_sampler": ["6", 0]},
            },
            "8": {
                "class_type": "FluxGuidance",
                "inputs": {"conditioning": ["1", 0], "guidance": "invalid"},
            },
            "9": {
                "class_type": "KSampler",
                "inputs": {"positive": ["8", 0]},
            },
        }
    )
    active = _active(*(str(value) for value in range(1, 10)))

    assert _prompt_root(index, active, index.nodes["3"], "positive") == (None, None, None)
    assert _prompt_root(index, active, index.nodes["5"], "positive") == (
        "1",
        "positive",
        0,
    )
    assert _prompt_root(index, active, index.nodes["7"], "positive") == (None, None, None)
    assert _find_guidance(index, active, StageSelection("9", ("9",))) is None


def test_routing_selector_resolution_depth_cycle_and_empty_primitive() -> None:
    index = _routing_index(
        {
            "1": {"class_type": "Reroute", "inputs": {"value": ["1", 0]}},
            "2": {"class_type": "PrimitiveInt", "inputs": {}},
            "3": {
                "class_type": "PrimitiveInt",
                "inputs": {"value": ["404", 0], "fallback": FALLBACK_SELECTOR},
            },
        }
    )
    assert (
        _resolve_selector_value(
            index,
            ("1", 0),
            preferred_input_names=("value",),
            seen=frozenset({"1"}),
        )
        is None
    )
    assert (
        _resolve_selector_value(
            index,
            ("3", 0),
            preferred_input_names=("value",),
        )
        == FALLBACK_SELECTOR
    )
    assert (
        _resolve_selector_value(
            index,
            ("2", 0),
            preferred_input_names=("value",),
        )
        is None
    )
    assert (
        _resolve_selector_value(
            index,
            ("2", 0),
            preferred_input_names=("value",),
            depth=8,
        )
        is None
    )


def test_lineage_missing_nodes_unique_model_and_vae_fallbacks() -> None:
    empty_index = GraphIndex(
        MappingProxyType({}),
        MappingProxyType({}),
        MappingProxyType({}),
        (),
    )
    assert select_primary_resource(
        empty_index,
        _active("404"),
        StageSelection("404", ("404",)),
        (),
    ) == (None, ())

    prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", 0]},
        },
        "3": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 0]},
        },
    }
    index = _routing_index(prompt)
    active = trace_active_upstream(index)
    resource = ResourceRecord(
        "1:unknown",
        ResourceRole.BASE_MODEL,
        ResourceKind.CHECKPOINT,
        "1",
        "CheckpointLoaderSimple",
        "base.safetensors",
        "checkpoints/base.safetensors",
    )
    assert select_primary_resource(
        index,
        active,
        StageSelection("2", ("2",)),
        (resource,),
    ) == ("1:unknown", ())
    assert select_vae_resource(
        index,
        active,
        StageSelection("2", ("2",)),
        (),
    ) == (None, ())


def test_antrobots_lineage_selects_runtime_branch_or_reports_ambiguity() -> None:
    def evaluate(
        refine_step: FrozenValue,
    ) -> tuple[
        tuple[str | None, tuple[ScanIssue, ...]],
        tuple[str | None, tuple[ScanIssue, ...]],
    ]:
        prompt = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
            },
            "2": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "checkpoints/refiner.safetensors"},
            },
            "3": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": "vae/base.safetensors"},
            },
            "4": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": "vae/refiner.safetensors"},
            },
            "10": {
                "class_type": "refine",
                "inputs": _antrobots_refiner_inputs(
                    base_model=("1", 0),
                    refiner_model=("2", 0),
                    base_vae=("3", 0),
                    refine_vae=("4", 0),
                    refine_step=refine_step,
                ),
            },
            "11": {
                "class_type": "CCollins_CiviScribe_SaveImage",
                "inputs": {"images": ["10", 0]},
            },
        }
        index = _routing_index(prompt)
        active = trace_active_upstream(index)
        resources = tuple(
            record
            for node_id in ("1", "2", "3", "4")
            for record in _direct_resources(index.nodes[node_id])[0]
        )
        stage = StageSelection("10", ("10",))
        return (
            select_primary_resource(index, active, stage, resources),
            select_vae_resource(index, active, stage, resources),
        )

    primary, vae = evaluate(0)
    assert primary == ("2:ckpt_name", ())
    assert vae == ("4:vae_name", ())

    primary, vae = evaluate(20)
    assert primary == ("1:ckpt_name", ())
    assert vae == ("3:vae_name", ())

    primary, vae = evaluate(None)
    assert primary == (None, (ScanIssue("primary_model_ambiguous"),))
    assert vae == (None, (ScanIssue("vae_resource_ambiguous"),))


def test_antrobots_pipe_nonboolean_image_mode_falls_back_to_lineage() -> None:
    inputs: dict[str, FrozenValue] = {
        "base_pipe": ("1", 0),
        "refine_pipe": ("2", 0),
        "total_steps": 20,
        "refine_step": 10,
        "base_denoise": 1.0,
        "refine_denoise": 1.0,
        "seed": 1,
        "cfg": 5.0,
        "sampler_name": "euler",
        "scheduler": "normal",
        "image": ("3", 0),
        "use_image": "automatic",
    }
    index = _routing_index(
        {
            "1": {"class_type": "BasicPipe", "inputs": {}},
            "2": {"class_type": "BasicPipe", "inputs": {}},
            "3": {"class_type": "EmptyLatentImage", "inputs": {}},
            "4": {"class_type": "refine_pipe", "inputs": inputs},
        }
    )
    active = _active("1", "2", "3", "4")

    assert classify_workflow_kind(
        index,
        active,
        StageSelection("4", ("4",)),
    ) == (WorkflowKind.TXT2IMG, ())


def test_ambiguous_latent_sources_and_guidance_values_remain_unknown() -> None:
    prompt = {
        "1": {"class_type": "EmptyLatentImage", "inputs": {}},
        "2": {"class_type": "EmptySD3LatentImage", "inputs": {}},
        "3": {
            "class_type": "LatentBatch",
            "inputs": {"latent1": ["1", 0], "latent2": ["2", 0]},
        },
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "prompt"}},
        "5": {
            "class_type": "FluxGuidance",
            "inputs": {"conditioning": ["4", 0], "guidance": 3.0},
        },
        "6": {
            "class_type": "FluxGuidance",
            "inputs": {"conditioning": ["4", 0], "guidance": 4.0},
        },
        "7": {
            "class_type": "ConditioningCombine",
            "inputs": {"one": ["5", 0], "two": ["6", 0]},
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {"latent_image": ["3", 0], "positive": ["7", 0]},
        },
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 0]},
        },
    }
    graph_index = _routing_index(prompt)
    active = trace_active_upstream(graph_index)
    stage = StageSelection("8", ("8",))

    latent, issues = _latent_source(graph_index, active, stage)

    assert latent is None
    assert issues == (ScanIssue("latent_source_ambiguous"),)
    assert _find_guidance(graph_index, active, stage) is None


def test_conflicting_clip_skip_and_prompt_without_literal_text_remain_unknown() -> None:
    prompt = {
        "1": {"class_type": "CLIPSetLastLayer", "inputs": {"stop_at_clip_layer": -1}},
        "2": {"class_type": "CLIPSetLastLayer", "inputs": {"stop_at_clip_layer": -2}},
        "7": {"class_type": "CLIPSetLastLayer", "inputs": {"stop_at_clip_layer": "invalid"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": ["404", 0]}},
        "4": {
            "class_type": "ConditioningCombine",
            "inputs": {
                "one": ["1", 0],
                "two": ["2", 0],
                "invalid": ["7", 0],
                "prompt": ["3", 0],
            },
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "positive": ["4", 0],
                "latent_image": ["1", 0],
                "guidance": 6.0,
            },
        },
        "6": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["5", 0]},
        },
    }
    index = _routing_index(prompt)
    active = trace_active_upstream(index)
    stage = StageSelection("5", ("5",))

    settings, setting_issues = extract_generation_settings(index, active, stage)
    positive, issues = _prompt_field(index, active, index.nodes["5"], "positive")

    assert settings.clip_skip is None
    assert ScanIssue("clip_skip_ambiguous") in setting_issues
    assert positive.branch_present
    assert positive.text is None
    assert issues == (ScanIssue("positive_prompt_missing"),)


def test_prompt_traversal_ignores_edges_outside_active_set() -> None:
    prompt = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "active"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "inactive"}},
        "3": {
            "class_type": "ConditioningCombine",
            "inputs": {"one": ["1", 0], "two": ["2", 0]},
        },
        "4": {"class_type": "KSampler", "inputs": {"positive": ["3", 0]}},
    }
    index = _routing_index(prompt)
    active = _active("1", "3", "4")

    field, issues = _prompt_field(index, active, index.nodes["4"], "positive")

    assert field.text == "active"
    assert issues == ()


def test_lineage_handles_no_sampler_ambiguous_kind_and_unknown_kind() -> None:
    no_sampler_prompt = {
        "1": {"class_type": "PrimitiveInt", "inputs": {"value": 1}},
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }
    no_sampler_index = _routing_index(no_sampler_prompt)
    no_sampler_active = trace_active_upstream(no_sampler_index)
    no_stage = select_generation_stage(no_sampler_index, no_sampler_active)
    assert no_stage.issues == (ScanIssue("sampler_stage_not_found"),)

    ambiguous_prompt = {
        "1": {"class_type": "EmptyLatentImage", "inputs": {}},
        "2": {"class_type": "VAEEncode", "inputs": {}},
        "3": {
            "class_type": "LatentBatch",
            "inputs": {"one": ["1", 0], "two": ["2", 0]},
        },
        "4": {"class_type": "KSampler", "inputs": {"latent_image": ["3", 0]}},
        "5": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["4", 0]},
        },
    }
    ambiguous_index = _routing_index(ambiguous_prompt)
    ambiguous_active = trace_active_upstream(ambiguous_index)
    ambiguous_stage = StageSelection("4", ("4",))
    kind, issues = classify_workflow_kind(
        ambiguous_index,
        ambiguous_active,
        ambiguous_stage,
    )
    assert kind is None
    assert issues == (ScanIssue("workflow_kind_ambiguous"),)

    unknown_prompt = {
        "1": {"class_type": "LatentNoise", "inputs": {}},
        "2": {"class_type": "KSampler", "inputs": {"latent_image": ["1", 0]}},
        "3": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 0]},
        },
    }
    unknown_index = _routing_index(unknown_prompt)
    unknown_active = trace_active_upstream(unknown_index)
    unknown_kind, unknown_issues = classify_workflow_kind(
        unknown_index,
        unknown_active,
        StageSelection("2", ("2",)),
    )
    assert unknown_kind is None
    assert unknown_issues == ()


def test_primary_resource_returns_none_without_selected_stage() -> None:
    empty_index = GraphIndex(
        MappingProxyType({}),
        MappingProxyType({}),
        MappingProxyType({}),
        (),
    )

    assert select_primary_resource(
        empty_index,
        _active(),
        StageSelection(None, ()),
        (
            ResourceRecord(
                "key",
                ResourceRole.BASE_MODEL,
                ResourceKind.CHECKPOINT,
                "1",
                "CheckpointLoaderSimple",
                "model.safetensors",
                "model.safetensors",
            ),
        ),
    ) == (None, ())


def test_issue_deduplication_keeps_first_identical_diagnostic() -> None:
    issue = ScanIssue("same", node_id="1")

    assert _deduplicate_issues(((issue,), (issue,))) == (issue,)


def test_normalizer_accepts_current_comfyui_colon_and_plus_class_names() -> None:
    graph = normalize_api_prompt(
        {
            "1": {
                "class_type": "easy XYInputs: Checkpoint+Refiner",
                "inputs": {},
            }
        }
    )

    assert graph.nodes["1"].class_type == "easy XYInputs: Checkpoint+Refiner"
    assert graph.issues == ()


@pytest.mark.parametrize(
    "class_type",
    [
        "ClownOptions_SwapSampler_Beta",
        "CLIPSetLastLayer",
        "CR Cycle Models",
        "CR Load Scheduled Models",
        "CR Model List",
        "CR Model Merge Stack",
        "CR Select Model",
        "DetailDaemonGraphSigmasNode",
        "easy XYInputs: Checkpoint",
        "easy stylesSelector",
        "ExtendIntermediateSigmas",
        "FrameInterpolationModelLoader",
        "GLIGENTextBoxApply",
        "GLIGENTextBoxApplyBatchCoords",
        "LyingSigmaSampler",
        "OviMMAudioVAELoader",
        "Prompt Multiple Styles Selector",
        "Prompt Styles Selector",
        "SamplerEulerCFGpp",
        "SamplerLCM",
        "SetClipHooks",
        "Sigmas ConwaySequence",
        "Sigmas GilbreathSequence",
        "Sigmas HarmonicDecay",
        "Sigmas LangevinDynamics",
        "Sigmas NormalizingFlows",
        "Sigmas PersistentHomology",
        "Sigmas RiemannianFlow",
        "Sigmas StepwiseMultirate",
        "SigmasSchedulePreview",
        "StyleModelApply",
        "StyleModelApplyAdvanced",
        "StyleModelApplyStyle",
        "T5TokenizerOptions",
        "Text Parse A1111 Embeddings",
        "USOStyleReference",
        "VOIDSampler",
    ],
)
def test_second_pass_reviewed_classes_are_known(class_type: str) -> None:
    node = PromptNode("1", class_type, MappingProxyType({}))

    assert is_known_active_node(node)


def test_unmapped_sigma_transform_is_recognized_as_known() -> None:
    node = PromptNode(
        "1",
        "MultiplySigmas",
        MappingProxyType({"sigmas": ("2", 0), "multiplier": 0.5}),
    )

    assert is_known_active_node(node)


def test_scan_reports_missing_primary_model_without_crashing() -> None:
    prompt = {
        "1": {"class_type": "EmptyLatentImage", "inputs": {}},
        "2": {"class_type": "KSampler", "inputs": {"latent_image": ["1", 0]}},
        "3": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert "primary_model_not_found" in {issue.code for issue in result.issues}
