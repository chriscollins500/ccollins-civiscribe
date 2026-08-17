from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from civiscribe.domain import ResourceRole, WorkflowKind
from civiscribe.workflow import scan_workflow

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "workflows"
BASIC_SEED = 123
BASIC_STEPS = 20
BASIC_CFG = 7.0
BASIC_WIDTH = 1024
BASIC_HEIGHT = 768
DISCONNECTED_WIDTH = 832
DISCONNECTED_HEIGHT = 1216
SECOND_STAGE_SEED = 2
SECOND_STAGE_STEPS = 4
FLUX_SEED = 1234
FLUX_STEPS = 14
FLUX_GUIDANCE = 4.0
FLUX_DENOISE = 0.8
FLUX_WIDTH = 768
FLUX_HEIGHT = 1024
FLUX_BATCH_SIZE = 2
EXPECTED_CLIP_SKIP = 2
CUSTOM_SEED = 99
CUSTOM_STEPS = 8
CUSTOM_CFG = 3.0
CUSTOM_DENOISE = 0.9
CUSTOM_BATCH_SIZE = 2
PIPE_SEED = 44
PIPE_STEPS = 12
PIPE_CFG = 5.5
STEP1X_SEED = 772
STEP1X_STEPS = 28
STEP1X_CFG = 6.0
IMPACT_SEED = 5150
IMPACT_STEPS = 24
IMPACT_CFG = 6.5
IMPACT_DENOISE = 0.85
WAN_SETTINGS_SEED = 765
WAN_SETTINGS_STEPS = 18
WAN_SETTINGS_CFG = 4.5
WAN_SETTINGS_DENOISE = 0.9
WAN_FORCING_SEED = 987654321
WAN_FORCING_STEPS = 24
WAN_FORCING_CFG = 4.5
WAN_FORCING_DENOISE = 0.9
ANTROBOTS_SAMPLE_SEED = 731
ANTROBOTS_SAMPLE_STEPS = 24
ANTROBOTS_SAMPLE_DENOISE = 0.85
ANTROBOTS_REFINE_STEPS = 30
ANTROBOTS_REFINE_DENOISE = 0.9
HYPERNETWORK_STRENGTH = 0.65
EASY_UNSAMPLER_STEPS = 12
EASY_UNSAMPLER_CFG = 4.5
EASY_UNSAMPLER_WIDTH = 640
EASY_UNSAMPLER_HEIGHT = 832
CUSTOM_SIGMA_SEED = 12345
CUSTOM_SIGMA_STEPS = 16
HOOK_MODEL_STRENGTH = 0.8
HOOK_CLIP_STRENGTH = 0.6
type Prompt = dict[str, dict[str, object]]
type Fixture = dict[str, object]


def _load_fixture(name: str) -> tuple[Prompt, dict[str, object]]:
    payload = cast(
        Fixture,
        json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8")),
    )
    assert payload["schemaName"] == "ccollins-civiscribe.workflow-fixture"
    assert payload["schemaVersion"] == "1.0.0"
    return cast(Prompt, payload["prompt"]), cast(dict[str, object], payload["expected"])


def _issue_codes(prompt: object, *, save_node_id: str | None = None) -> set[str]:
    return {issue.code for issue in scan_workflow(prompt, save_node_id=save_node_id).issues}


def test_basic_checkpoint_fixture_extracts_shared_generation_facts() -> None:
    prompt, expected = _load_fixture("basic_checkpoint.json")

    result = scan_workflow(prompt)

    assert list(result.active_node_ids) == expected["activeNodeIds"]
    assert result.selected_stage_node_id == expected["selectedStageNodeId"]
    assert result.workflow_kind == WorkflowKind(cast(str, expected["workflowKind"]))
    assert result.prompts.positive.text == expected["positive"]
    assert result.prompts.negative.text == expected["negative"]
    assert result.primary_resource_key == expected["primaryResourceKey"]
    assert [resource.filename for resource in result.resources] == expected["resourceFilenames"]
    assert result.settings.seed == BASIC_SEED
    assert result.settings.steps == BASIC_STEPS
    assert result.settings.sampler == "euler"
    assert result.settings.scheduler == "normal"
    assert result.settings.cfg_scale == BASIC_CFG
    assert result.settings.denoise == 1.0
    assert result.settings.width == BASIC_WIDTH
    assert result.settings.height == BASIC_HEIGHT
    assert result.settings.batch_size == 1
    assert result.issues == ()


def test_linked_sampler_constants_are_resolved_without_mutating_graph() -> None:
    prompt, expected = _load_fixture("linked_sampler_constants.json")

    result = scan_workflow(prompt)

    assert list(result.active_node_ids) == expected["activeNodeIds"]
    assert result.settings.seed == expected["seed"]
    assert result.settings.steps == expected["steps"]
    assert result.settings.width == expected["width"]
    assert result.settings.height == expected["height"]
    assert result.settings.sampler == "dpmpp_2m"
    assert result.settings.scheduler == "karras"


def test_disconnected_resources_are_excluded_and_zeroed_negative_stays_empty() -> None:
    prompt, expected = _load_fixture("disconnected_loader_exclusion.json")

    result = scan_workflow(prompt)
    filenames = [resource.filename for resource in result.resources]

    assert list(result.active_node_ids) == expected["activeNodeIds"]
    assert filenames == expected["resourceFilenames"]
    assert set(filenames).isdisjoint(cast(list[str], expected["excludedResourceFilenames"]))
    assert result.primary_resource_key == expected["primaryResourceKey"]
    assert result.selected_vae_resource_key == expected["selectedVaeResourceKey"]
    assert result.prompts.negative.branch_present is expected["negativeBranchPresent"]
    assert result.prompts.negative.text is expected["negativeText"]
    assert result.prompts.positive.text == "portrait with Unicode snow: 雪"
    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.settings.width == DISCONNECTED_WIDTH
    assert result.settings.height == DISCONNECTED_HEIGHT


def test_krea2_core_switch_preview_chain_resolves_selected_prompt() -> None:
    prompt, expected = _load_fixture("krea2_switch_prompt.json")

    result = scan_workflow(prompt)
    issue_codes = {issue.code for issue in result.issues}

    assert list(result.active_node_ids) == expected["activeNodeIds"]
    assert set(cast(list[str], expected["inactiveNodeIds"])).isdisjoint(result.active_node_ids)
    assert result.selected_stage_node_id == expected["selectedStageNodeId"]
    assert result.workflow_kind == WorkflowKind(cast(str, expected["workflowKind"]))
    assert result.prompts.positive.text == expected["positive"]
    assert result.prompts.negative.text is expected["negative"]
    assert result.primary_resource_key == expected["primaryResourceKey"]
    assert result.selected_vae_resource_key == expected["selectedVaeResourceKey"]
    assert [resource.filename for resource in result.resources] == expected["resourceFilenames"]
    assert "positive_prompt_missing" not in issue_codes
    assert "positive_prompt_ambiguous" not in issue_codes
    assert "unknown_active_node_class" not in issue_codes


def test_rgthree_power_lora_fixture_honors_enabled_state_and_strengths() -> None:
    prompt, expected = _load_fixture("rgthree_power_lora.json")

    result = scan_workflow(prompt)
    filenames = [resource.filename for resource in result.resources]
    loras = [resource for resource in result.resources if resource.role is ResourceRole.LORA]

    assert filenames == expected["resourceFilenames"]
    assert set(filenames).isdisjoint(cast(list[str], expected["excludedResourceFilenames"]))
    assert [(item.strengths.model, item.strengths.clip) for item in loras] == [
        (0.75, 0.5),
        (0.25, None),
    ]


def test_nd_super_lora_fixture_decodes_active_bundle_entries() -> None:
    prompt, expected = _load_fixture("nd_super_lora_loader.json")

    result = scan_workflow(prompt)
    filenames = [resource.filename for resource in result.resources]
    loras = [resource for resource in result.resources if resource.role is ResourceRole.LORA]

    assert filenames == expected["resourceFilenames"]
    assert set(filenames).isdisjoint(cast(list[str], expected["excludedResourceFilenames"]))
    assert [[item.strengths.model, item.strengths.clip] for item in loras] == expected[
        "loraStrengths"
    ]
    assert {item.detection_rule_id for item in loras} == {"nd_super_lora_bundle"}
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


def _simple_tail(
    *,
    model: list[object],
    latent: list[object] | None = None,
    sampler_id: str = "20",
) -> Prompt:
    latent_source = latent or ["10", 0]
    return {
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        sampler_id: {
            "class_type": "KSampler",
            "inputs": {
                "model": model,
                "latent_image": latent_source,
                "seed": 1,
                "steps": 2,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "normal",
            },
        },
        "30": {
            "class_type": "VAEDecode",
            "inputs": {"samples": [sampler_id, 0]},
        },
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }


def test_easyuse_pipe_extracts_prompts_settings_dimensions_and_resources() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "easy fullLoader",
            "inputs": {
                "ckpt_name": "checkpoints/easy.safetensors",
                "vae_name": "vae/easy.safetensors",
                "positive": "easy positive",
                "negative": "easy negative",
            },
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 896, "height": 1152, "batch_size": 2},
        },
        "3": {
            "class_type": "easy preSamplingAdvanced",
            "inputs": {
                "pipe": ["1", 0],
                "latent": ["2", 0],
                "seed": 77,
                "steps": 23,
                "cfg": 5.25,
                "sampler_name": "dpmpp_3m_sde",
                "scheduler": "karras",
                "denoise": 0.8,
            },
        },
        "4": {
            "class_type": "easy kSampler",
            "inputs": {"pipe": ["3", 0]},
        },
        "5": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["4", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.prompts.positive.text == "easy positive"
    assert result.prompts.negative.text == "easy negative"
    assert (
        result.settings.seed,
        result.settings.steps,
        result.settings.sampler,
        result.settings.scheduler,
        result.settings.cfg_scale,
        result.settings.denoise,
        result.settings.width,
        result.settings.height,
        result.settings.batch_size,
    ) == (77, 23, "dpmpp_3m_sde", "karras", 5.25, 0.8, 896, 1152, 2)
    assert [resource.filename for resource in result.resources] == [
        "easy.safetensors",
        "easy.safetensors",
    ]
    assert result.primary_resource_key == "1:ckpt_name"
    assert result.selected_vae_resource_key == "1:vae_name"
    assert result.issues == ()


def test_easy_pipe_edit_extracts_literal_prompts_and_clip_skip() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "easy pipeEdit",
            "inputs": {
                "model": ["1", 0],
                "optional_positive": "edited positive",
                "optional_negative": "edited negative",
                "clip_skip": -2,
            },
        },
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 768, "batch_size": 1},
        },
        "20": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 1],
                "positive": ["2", 2],
                "negative": ["2", 3],
                "latent_image": ["10", 0],
                "seed": 1,
                "steps": 2,
            },
        },
        "30": {"class_type": "VAEDecode", "inputs": {"samples": ["20", 0]}},
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.prompts.positive.text == "edited positive"
    assert result.prompts.negative.text == "edited negative"
    assert result.settings.clip_skip == EXPECTED_CLIP_SKIP
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


def test_linked_diffusion_selector_and_multigpu_gguf_loader_resolve_primary() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "DiffusionModelSelector",
            "inputs": {"model_name": "diffusion_models/selected-Q8_0.gguf"},
        },
        "2": {
            "class_type": "UnetLoaderGGUFDisTorchMultiGPU",
            "inputs": {"unet_name": ["1", 0]},
        },
        **_simple_tail(model=["2", 0]),
    }

    result = scan_workflow(prompt)

    assert [resource.filename for resource in result.resources] == ["selected-Q8_0.gguf"]
    assert result.primary_resource_key == "2:unet_name"
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


def test_wan_qwen_loader_is_captured_without_guessing_generated_prompt() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "QwenLoader",
            "inputs": {"model": "text_encoders/qwen_7b.safetensors"},
        },
        "2": {
            "class_type": "WanVideoPromptExtender",
            "inputs": {"qwen": ["1", 0], "prompt": "source prompt"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": ["2", 0]},
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        **_simple_tail(model=["4", 0]),
    }
    cast(dict[str, object], prompt["20"]["inputs"])["positive"] = ["3", 0]

    result = scan_workflow(prompt)

    assert {(resource.role, resource.filename) for resource in result.resources} == {
        (ResourceRole.BASE_MODEL, "base.safetensors"),
        (ResourceRole.TEXT_ENCODER, "qwen_7b.safetensors"),
    }
    assert result.prompts.positive.text is None
    assert "positive_prompt_missing" in {issue.code for issue in result.issues}
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


def test_multi_prompt_provider_preserves_temporal_prompt_source() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/model.safetensors"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "text_encoders/encoder.safetensors"},
        },
        "3": {
            "class_type": "MultiPromptProvider",
            "inputs": {
                "prompts": "opening scene | closing scene",
                "clip": ["2", 0],
            },
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 768, "height": 512},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["3", 0],
                "latent_image": ["4", 0],
                "seed": 1,
                "steps": 2,
                "cfg": 3.0,
                "sampler_name": "euler",
                "scheduler": "normal",
            },
        },
        "6": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["5", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.prompts.positive.text == "opening scene | closing scene"
    assert {resource.role for resource in result.resources} == {
        ResourceRole.BASE_MODEL,
        ResourceRole.TEXT_ENCODER,
    }
    assert result.issues == ()


def test_comfyroll_model_merge_keeps_all_enabled_models_and_no_fake_primary() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CR Model Merge Stack",
            "inputs": {
                "switch_1": "On",
                "ckpt_name1": "checkpoints/first.safetensors",
                "model_ratio1": 0.6,
                "clip_ratio1": 0.6,
                "switch_2": "On",
                "ckpt_name2": "checkpoints/second.safetensors",
                "model_ratio2": 0.4,
                "clip_ratio2": 0.4,
                "switch_3": "Off",
                "ckpt_name3": "checkpoints/inactive.safetensors",
            },
        },
        "2": {
            "class_type": "CR Apply Model Merge",
            "inputs": {"model_stack": ["1", 0]},
        },
        **_simple_tail(model=["2", 0]),
    }

    result = scan_workflow(prompt)

    assert [resource.filename for resource in result.resources] == [
        "first.safetensors",
        "second.safetensors",
    ]
    assert result.primary_resource_key is None
    assert "primary_model_ambiguous" in {issue.code for issue in result.issues}
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


def test_hypernetwork_loader_is_an_active_resolvable_resource() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/model.safetensors"},
        },
        "2": {
            "class_type": "HypernetworkLoader",
            "inputs": {
                "model": ["1", 0],
                "hypernetwork_name": "hypernetworks/detail.pt",
                "strength": HYPERNETWORK_STRENGTH,
            },
        },
        **_simple_tail(model=["2", 0]),
    }

    result = scan_workflow(prompt)
    hypernetwork = next(
        resource for resource in result.resources if resource.role is ResourceRole.HYPERNETWORK
    )

    assert hypernetwork.filename == "detail.pt"
    assert hypernetwork.strengths.weight == HYPERNETWORK_STRENGTH
    assert hypernetwork.detection_rule_id == "core_hypernetwork_loader"
    assert result.primary_resource_key == "1:ckpt_name"
    assert {issue.code for issue in result.issues} == {"positive_prompt_missing"}


def test_comfyroll_aspect_latent_is_txt2img_and_supplies_dimensions() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/model.safetensors"},
        },
        "2": {
            "class_type": "CR Aspect Ratio",
            "inputs": {
                "width": 512,
                "height": 768,
                "aspect_ratio": "custom",
                "swap_dimensions": "Off",
                "prescale_factor": 2.0,
            },
        },
        **_simple_tail(model=["1", 0], latent=["2", 5]),
    }

    result = scan_workflow(prompt)

    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert (result.settings.width, result.settings.height) == (1024, 1536)
    assert {issue.code for issue in result.issues} == {"positive_prompt_missing"}


@pytest.mark.parametrize(
    ("class_type", "aspect_ratio", "expected_width", "expected_height"),
    [
        ("CR Aspect Ratio Banners", "Banner - 468x60", 168, 60),
        (
            "CR Aspect Ratio Social Media",
            "LinkedIn Page Cover - 1128x191",
            1584,
            396,
        ),
    ],
)
def test_comfyroll_specialized_aspect_latents_match_runtime_dimensions(
    class_type: str,
    aspect_ratio: str,
    expected_width: int,
    expected_height: int,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/model.safetensors"},
        },
        "2": {
            "class_type": class_type,
            "inputs": {
                "width": 512,
                "height": 512,
                "aspect_ratio": aspect_ratio,
                "swap_dimensions": "Off",
                "prescale_factor": 1.0,
            },
        },
        **_simple_tail(model=["1", 0], latent=["2", 5]),
    }

    result = scan_workflow(prompt)

    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert (result.settings.width, result.settings.height) == (
        expected_width,
        expected_height,
    )
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


def test_literal_index_switch_keeps_only_selected_model_branch() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/first.safetensors"},
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/second.safetensors"},
        },
        "3": {
            "class_type": "ImpactSwitch",
            "inputs": {"select": 2, "input1": ["1", 0], "input2": ["2", 0]},
        },
        **_simple_tail(model=["3", 0]),
    }

    result = scan_workflow(prompt)

    assert [resource.filename for resource in result.resources] == ["second.safetensors"]
    assert result.primary_resource_key == "2:ckpt_name"
    assert "1" not in result.active_node_ids
    assert "switch_selection_ambiguous" not in {issue.code for issue in result.issues}


def test_linked_primitive_switch_selector_keeps_only_selected_branch() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/first.safetensors"},
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/second.safetensors"},
        },
        "3": {
            "class_type": "ImpactSwitch",
            "inputs": {"select": ["4", 0], "input1": ["1", 0], "input2": ["2", 0]},
        },
        "4": {"class_type": "PrimitiveInt", "inputs": {"value": 2}},
        **_simple_tail(model=["3", 0]),
    }

    result = scan_workflow(prompt)

    assert [resource.filename for resource in result.resources] == ["second.safetensors"]
    assert result.primary_resource_key == "2:ckpt_name"
    assert "switch_selection_ambiguous" not in {issue.code for issue in result.issues}


def test_linked_dynamic_switch_selector_remains_conservative() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/first.safetensors"},
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/second.safetensors"},
        },
        "3": {
            "class_type": "ImpactSwitch",
            "inputs": {"select": ["4", 0], "input1": ["1", 0], "input2": ["2", 0]},
        },
        "4": {"class_type": "CalculatedSelector", "inputs": {"seed": 2}},
        **_simple_tail(model=["3", 0]),
    }

    result = scan_workflow(prompt)

    assert {resource.filename for resource in result.resources} == {
        "first.safetensors",
        "second.safetensors",
    }
    assert result.primary_resource_key is None
    assert {"switch_selection_ambiguous", "primary_model_ambiguous"} <= {
        issue.code for issue in result.issues
    }


def test_selector_de_imagenes_excludes_resources_from_disabled_image_branches() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/disabled.safetensors"},
        },
        "2": {"class_type": "ImageFromModel", "inputs": {"model": ["1", 0]}},
        "3": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/enabled.safetensors"},
        },
        "4": {"class_type": "ImageFromModel", "inputs": {"model": ["3", 0]}},
        "5": {"class_type": "MaskSource", "inputs": {}},
        "6": {"class_type": "MaskSource", "inputs": {}},
        "7": {
            "class_type": "SelectorDeImagenes",
            "inputs": {
                "fallback": "error",
                "mode": "auto",
                "img1": ["2", 0],
                "mask1": ["5", 0],
                "on1": False,
                "img2": ["4", 0],
                "mask2": ["6", 0],
                "on2": True,
            },
        },
        "8": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["7", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert [resource.filename for resource in result.resources] == ["enabled.safetensors"]
    assert "1" not in result.active_node_ids
    assert "3" in result.active_node_ids
    assert "switch_selection_ambiguous" not in {issue.code for issue in result.issues}


def test_runtime_reload_model_reports_unknown_provenance_without_fallback_resource() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/fallback.safetensors"},
        },
        "2": {
            "class_type": "ReloadModel",
            "inputs": {
                "filename": "cycle/model",
                "fallback_m": ["1", 0],
            },
        },
        **_simple_tail(model=["2", 0]),
    }

    result = scan_workflow(prompt)
    issue_codes = {issue.code for issue in result.issues}

    assert result.resources == ()
    assert "1" not in result.active_node_ids
    assert "runtime_payload_provenance_unavailable" in issue_codes
    assert "unknown_active_node_class" not in issue_codes


def test_load_cache_reports_payload_provenance_without_reading_paths() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "Load Cache",
            "inputs": {
                "latent_path": "untrusted/cache.latent",
                "image_path": "",
                "conditioning_path": "",
            },
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 1]},
        },
    }

    result = scan_workflow(prompt)
    issue_codes = {issue.code for issue in result.issues}

    assert result.resources == ()
    assert "runtime_payload_provenance_unavailable" in issue_codes
    assert "unknown_active_node_class" not in issue_codes


def test_boolean_switch_and_label_router_resolve_named_branches() -> None:
    boolean_prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/false.safetensors"},
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/true.safetensors"},
        },
        "3": {
            "class_type": "BooleanSwitch",
            "inputs": {"switch": "enabled", "on_false": ["1", 0], "on_true": ["2", 0]},
        },
        **_simple_tail(model=["3", 0]),
    }
    label_prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/red.safetensors"},
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/blue.safetensors"},
        },
        "3": {
            "class_type": "ModelRouter",
            "inputs": {"select": "blue", "red": ["1", 0], "blue": ["2", 0]},
        },
        **_simple_tail(model=["3", 0]),
    }

    boolean_result = scan_workflow(boolean_prompt)
    label_result = scan_workflow(label_prompt)

    assert [resource.filename for resource in boolean_result.resources] == ["true.safetensors"]
    assert [resource.filename for resource in label_result.resources] == ["blue.safetensors"]


def test_serial_samplers_choose_stage_nearest_saved_pixels() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/base.safetensors"},
        },
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "20": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "latent_image": ["10", 0],
                "seed": 1,
                "steps": 10,
            },
        },
        "21": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["1", 0],
                "latent_image": ["20", 0],
                "noise_seed": 2,
                "steps": 4,
            },
        },
        "30": {"class_type": "VAEDecode", "inputs": {"samples": ["21", 0]}},
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "21"
    assert result.stage_candidate_ids == ("20", "21")
    assert result.settings.seed == SECOND_STAGE_SEED
    assert result.settings.steps == SECOND_STAGE_STEPS


def test_equal_distance_sampler_stages_are_reported_as_ambiguous() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/base.safetensors"},
        },
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "20": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", 0], "latent_image": ["10", 0]},
        },
        "21": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", 0], "latent_image": ["10", 0]},
        },
        "30": {
            "class_type": "ImageBatch",
            "inputs": {"image1": ["20", 0], "image2": ["21", 0]},
        },
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id is None
    assert result.stage_candidate_ids == ("20", "21")
    assert "sampler_stage_ambiguous" in {issue.code for issue in result.issues}


def test_img2img_classification_uses_only_selected_latent_lineage() -> None:
    prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/base.safetensors"},
        },
        "8": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
        "9": {"class_type": "VAEEncode", "inputs": {"pixels": ["8", 0]}},
        **_simple_tail(model=["1", 0], latent=["9", 0]),
    }

    result = scan_workflow(prompt)

    assert result.workflow_kind is WorkflowKind.IMG2IMG


def test_unrelated_image_encoder_does_not_turn_txt2img_into_img2img() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/base.safetensors"},
        },
        "8": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
        "9": {"class_type": "VAEEncode", "inputs": {"pixels": ["8", 0]}},
        **_simple_tail(model=["1", 0]),
    }

    result = scan_workflow(prompt)

    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert "8" not in result.active_node_ids
    assert "9" not in result.active_node_ids


def test_custom_sampler_chain_extracts_flux_settings_and_primary_model() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": "diffusion_models/flux.gguf"},
        },
        "2": {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": "clip/t5.gguf"}},
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": "a glass city"},
        },
        "4": {
            "class_type": "FluxGuidance",
            "inputs": {"conditioning": ["3", 0], "guidance": 4.0},
        },
        "5": {
            "class_type": "BasicGuider",
            "inputs": {"model": ["1", 0], "conditioning": ["4", 0]},
        },
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1234}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {
            "class_type": "BasicScheduler",
            "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": 14, "denoise": 0.8},
        },
        "9": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 768, "height": 1024, "batch_size": 2},
        },
        "10": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "guider": ["5", 0],
                "noise": ["6", 0],
                "sampler": ["7", 0],
                "sigmas": ["8", 0],
                "latent_image": ["9", 0],
            },
        },
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0]}},
        "12": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["11", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "10"
    assert result.primary_resource_key == "1:unet_name"
    assert result.settings.seed == FLUX_SEED
    assert result.settings.steps == FLUX_STEPS
    assert result.settings.sampler == "euler"
    assert result.settings.scheduler == "simple"
    assert result.settings.guidance == FLUX_GUIDANCE
    assert result.settings.cfg_scale is None
    assert result.settings.denoise == FLUX_DENOISE
    assert result.settings.width == FLUX_WIDTH
    assert result.settings.height == FLUX_HEIGHT
    assert result.settings.batch_size == FLUX_BATCH_SIZE
    assert result.prompts.positive.text == "a glass city"


def test_multiple_prompt_texts_and_unknown_active_node_are_sanitized_warnings() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/base.safetensors"},
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "first"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "second"}},
        "4": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["2", 0], "conditioning_2": ["3", 0]},
        },
        "5": {"class_type": "TotallyCustomNode", "inputs": {"value": ["4", 0]}},
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "20": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["5", 0],
                "latent_image": ["10", 0],
            },
        },
        "30": {"class_type": "VAEDecode", "inputs": {"samples": ["20", 0]}},
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }

    result = scan_workflow(prompt)
    issues = {issue.code: issue for issue in result.issues}

    assert result.prompts.positive.text is None
    assert result.prompts.positive.candidates == ("first", "second")
    assert "positive_prompt_ambiguous" in issues
    assert issues["unknown_active_node_class"].node_id == "5"
    assert all("TotallyCustomNode" not in issue.code for issue in result.issues)


def test_clip_skip_is_normalized_to_positive_layer_count() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/base.safetensors"},
        },
        "2": {
            "class_type": "CLIPSetLastLayer",
            "inputs": {"clip": ["1", 1], "stop_at_clip_layer": -2},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": "clip skip"},
        },
        **_simple_tail(model=["1", 0]),
    }
    cast(dict[str, object], prompt["20"]["inputs"])["positive"] = ["3", 0]

    result = scan_workflow(prompt)

    assert result.settings.clip_skip == EXPECTED_CLIP_SKIP


def test_modern_cached_encoder_extracts_both_prompts_and_text_encoder_resource() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "WanVideoTextEncodeCached",
            "inputs": {
                "model_name": "text_encoders/umt5.safetensors",
                "positive_prompt": "bright city",
                "negative_prompt": "fog",
            },
        },
        **_simple_tail(model=["1", 0]),
    }
    cast(dict[str, object], prompt["20"]["inputs"])["positive"] = ["2", 0]
    cast(dict[str, object], prompt["20"]["inputs"])["negative"] = ["2", 1]

    result = scan_workflow(prompt)

    assert result.prompts.positive.text == "bright city"
    assert result.prompts.negative.text == "fog"
    assert {(resource.role, resource.filename) for resource in result.resources} >= {
        (ResourceRole.TEXT_ENCODER, "umt5.safetensors"),
        (ResourceRole.BASE_MODEL, "base.safetensors"),
    }


def test_impact_wildcard_prompt_prefers_realized_text() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "ImpactWildcardEncode",
            "inputs": {
                "wildcard_text": "__subject__ in a studio",
                "populated_text": "portrait in a studio",
            },
        },
        **_simple_tail(model=["1", 0]),
    }
    cast(dict[str, object], prompt["20"]["inputs"])["positive"] = ["2", 0]

    result = scan_workflow(prompt)

    assert result.prompts.positive.text == "portrait in a studio"
    assert result.prompts.positive.candidates == ("portrait in a studio",)


def test_custom_sampler_provider_and_source_free_noise_extract_settings() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "diffusion_models/model.safetensors"},
        },
        "2": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "cfg": 3.0}},
        "3": {"class_type": "RandomNoise", "inputs": {"noise_seed": 99}},
        "4": {
            "class_type": "SamplerDPMPP_3M_SDE",
            "inputs": {"eta": 1.0, "s_noise": 1.0},
        },
        "5": {
            "class_type": "KarrasScheduler",
            "inputs": {"steps": 8, "denoise": 0.9},
        },
        "6": {
            "class_type": "GenerateNoise",
            "inputs": {"width": 640, "height": 896, "batch_size": 2, "seed": 5},
        },
        "7": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "guider": ["2", 0],
                "noise": ["3", 0],
                "sampler": ["4", 0],
                "sigmas": ["5", 0],
                "latent_image": ["6", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0]}},
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.settings.seed == CUSTOM_SEED
    assert result.settings.steps == CUSTOM_STEPS
    assert result.settings.sampler == "dpmpp_3m_sde"
    assert result.settings.scheduler == "karras"
    assert result.settings.cfg_scale == CUSTOM_CFG
    assert result.settings.denoise == CUSTOM_DENOISE
    assert (result.settings.width, result.settings.height) == (640, 896)
    assert result.settings.batch_size == CUSTOM_BATCH_SIZE


def test_sampler_with_base_and_refiner_inputs_selects_base_model_path() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/refiner.safetensors"},
        },
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "20": {
            "class_type": "SeargeSDXLSampler2",
            "inputs": {
                "base_model": ["1", 0],
                "refiner_model": ["2", 0],
                "latent_image": ["10", 0],
                "steps": 20,
            },
        },
        "30": {"class_type": "VAEDecode", "inputs": {"samples": ["20", 0]}},
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.primary_resource_key == "1:ckpt_name"
    assert {resource.filename for resource in result.resources} == {
        "base.safetensors",
        "refiner.safetensors",
    }


def test_pipe_sampler_follows_integrated_model_prompt_and_sampler_settings() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "pipe prompt"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "pipe negative"}},
        "4": {
            "class_type": "BusPipe",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
            },
        },
        "5": {
            "class_type": "SamplerPipe",
            "inputs": {"cfg": 5.5, "sampler_name": "euler", "scheduler": "karras"},
        },
        "6": {
            "class_type": "sample_pipe",
            "inputs": {
                "pipe": ["4", 0],
                "sampler_pipe": ["5", 0],
                "seed": 44,
                "steps": 12,
                "denoise": 1.0,
                "image": ["7", 0],
                "use_image": False,
            },
        },
        "7": {
            "class_type": "EmptyImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "8": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["6", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "6"
    assert result.primary_resource_key == "1:ckpt_name"
    assert result.prompts.positive.text == "pipe prompt"
    assert result.prompts.negative.text == "pipe negative"
    assert result.settings.seed == PIPE_SEED
    assert result.settings.steps == PIPE_STEPS
    assert result.settings.sampler == "euler"
    assert result.settings.scheduler == "karras"
    assert result.settings.cfg_scale == PIPE_CFG
    assert result.settings.denoise == 1.0


@pytest.mark.parametrize(
    ("prompt", "expected_code"),
    [
        (None, "prompt_not_object"),
        ({}, "save_node_not_found"),
        (
            {
                "1": {"class_type": "CCollins_CiviScribe_SaveImage", "inputs": {}},
            },
            "save_images_link_missing",
        ),
    ],
)
def test_malformed_or_incomplete_workflows_do_not_crash(
    prompt: object,
    expected_code: str,
) -> None:
    result = scan_workflow(prompt)

    assert result.resources == ()
    assert expected_code in {issue.code for issue in result.issues}


def test_explicit_save_node_disambiguates_multiple_outputs() -> None:
    prompt = {
        "1": {"class_type": "EmptyLatentImage", "inputs": {}},
        "2": {"class_type": "KSampler", "inputs": {"latent_image": ["1", 0]}},
        "3": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 0]},
        },
        "4": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 0]},
        },
    }

    assert "save_node_ambiguous" in _issue_codes(prompt)
    assert scan_workflow(prompt, save_node_id="4").save_node_id == "4"


def test_selected_vae_is_nearest_resource_on_final_decode_lineage() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "vae/nearest.safetensors"},
        },
        "2": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "vae/farther.safetensors"},
        },
        "3": {"class_type": "VAEPassThrough", "inputs": {"vae": ["2", 0]}},
        "4": {
            "class_type": "VAEMerge",
            "inputs": {"nearest": ["1", 0], "farther": ["3", 0]},
        },
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "20": {"class_type": "KSampler", "inputs": {"latent_image": ["10", 0]}},
        "30": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["20", 0], "vae": ["4", 0]},
        },
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_vae_resource_key == "1:vae_name"
    assert {resource.filename for resource in result.resources} == {
        "nearest.safetensors",
        "farther.safetensors",
    }


def test_equal_distance_vae_resources_are_reported_as_ambiguous() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "vae/first.safetensors"},
        },
        "2": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "vae/second.safetensors"},
        },
        "4": {
            "class_type": "VAEMerge",
            "inputs": {"first": ["1", 0], "second": ["2", 0]},
        },
        "10": {"class_type": "EmptyLatentImage", "inputs": {}},
        "20": {"class_type": "KSampler", "inputs": {"latent_image": ["10", 0]}},
        "30": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["20", 0], "vae": ["4", 0]},
        },
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_vae_resource_key is None
    assert "vae_resource_ambiguous" in {issue.code for issue in result.issues}


def test_equal_distance_decode_stages_are_reported_as_ambiguous() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "vae/model.safetensors"},
        },
        "10": {"class_type": "EmptyLatentImage", "inputs": {}},
        "20": {"class_type": "KSampler", "inputs": {"latent_image": ["10", 0]}},
        "30": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["20", 0], "vae": ["1", 0]},
        },
        "31": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["20", 0], "vae": ["1", 0]},
        },
        "35": {
            "class_type": "ImageBatch",
            "inputs": {"first": ["30", 0], "second": ["31", 0]},
        },
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["35", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_vae_resource_key is None
    assert "vae_decode_stage_ambiguous" in {issue.code for issue in result.issues}


def test_vae_gguf_and_apt_gguf_loaders_are_detected_from_registered_inputs() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "load_GGUF",
            "inputs": {"unet_name": "diffusion_models/base-Q8_0.gguf"},
        },
        "2": {
            "class_type": "VaeGGUF",
            "inputs": {"vae_name": "vae/model-Q8_0.gguf"},
        },
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 768},
        },
        "20": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", 0], "latent_image": ["10", 0]},
        },
        "30": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["20", 0], "vae": ["2", 0]},
        },
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.primary_resource_key == "1:unet_name"
    assert result.selected_vae_resource_key == "2:vae_name"
    assert {
        (resource.role, resource.filename, resource.detection_rule_id)
        for resource in result.resources
    } == {
        (ResourceRole.BASE_MODEL, "base-Q8_0.gguf", "apt_gguf_loader"),
        (ResourceRole.VAE, "model-Q8_0.gguf", "vae_gguf_loader"),
    }


def test_core_style_model_loader_is_an_active_resolvable_resource() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "styled portrait"},
        },
        "3": {
            "class_type": "StyleModelLoader",
            "inputs": {"style_model_name": "style_models/style_model.safetensors"},
        },
        "4": {
            "class_type": "StyleModelApply",
            "inputs": {
                "conditioning": ["2", 0],
                "style_model": ["3", 0],
                "clip_vision_output": ["2", 0],
                "strength": 1.0,
                "strength_type": "multiply",
            },
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["4", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["6", 0], "vae": ["1", 2]},
        },
        "8": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["7", 0]},
        },
    }

    result = scan_workflow(prompt)
    style_model = next(
        resource for resource in result.resources if resource.role is ResourceRole.STYLE_MODEL
    )

    assert style_model.filename == "style_model.safetensors"
    assert style_model.selected_value == "style_models/style_model.safetensors"
    assert style_model.detection_rule_id == "core_style_model_loader"
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


def test_hook_and_reference_resources_are_active_and_prompt_text_passes_through() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "CreateHookLora",
            "inputs": {
                "lora_name": "loras/hook-style.safetensors",
                "strength_model": HOOK_MODEL_STRENGTH,
                "strength_clip": HOOK_CLIP_STRENGTH,
            },
        },
        "3": {
            "class_type": "SetClipHooks",
            "inputs": {"clip": ["1", 1], "hooks": ["2", 0]},
        },
        "4": {
            "class_type": "easy stylesSelector",
            "inputs": {
                "styles": "none",
                "select_styles": (),
                "positive": "embedding:detail.pt styled portrait",
                "negative": "blur",
            },
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["3", 0], "text": ["4", 0]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["3", 0], "text": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": "clip_vision/vision.safetensors"},
        },
        "8": {
            "class_type": "StyleModelLoader",
            "inputs": {"style_model_name": "style_models/style.safetensors"},
        },
        "9": {
            "class_type": "StyleModelApplyAdvanced",
            "inputs": {
                "conditioning": ["5", 0],
                "style_model": ["8", 0],
                "clip_vision_output": ["7", 0],
                "strength": 0.7,
            },
        },
        "10": {
            "class_type": "ModelPatchLoader",
            "inputs": {"name": "model_patches/reference.safetensors"},
        },
        "11": {
            "class_type": "USOStyleReference",
            "inputs": {
                "model": ["1", 0],
                "model_patch": ["10", 0],
                "clip_vision_output": ["7", 0],
            },
        },
        "12": {
            "class_type": "GLIGENLoader",
            "inputs": {"gligen_name": "gligen/gligen.safetensors"},
        },
        "13": {
            "class_type": "GLIGENTextBoxApply",
            "inputs": {
                "conditioning_to": ["9", 0],
                "clip": ["3", 0],
                "gligen_textbox_model": ["12", 0],
            },
        },
        "14": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "15": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["11", 0],
                "positive": ["13", 0],
                "negative": ["6", 0],
                "latent_image": ["14", 0],
            },
        },
        "16": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["15", 0], "vae": ["1", 2]},
        },
        "17": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["16", 0]},
        },
    }

    result = scan_workflow(prompt)
    resources = {(resource.role, resource.filename): resource for resource in result.resources}

    assert result.prompts.positive.text == "embedding:detail.pt styled portrait"
    assert result.prompts.negative.text == "blur"
    assert (ResourceRole.LORA, "hook-style.safetensors") in resources
    assert (
        resources[(ResourceRole.LORA, "hook-style.safetensors")].strengths.model
        == HOOK_MODEL_STRENGTH
    )
    assert (
        resources[(ResourceRole.LORA, "hook-style.safetensors")].strengths.clip
        == HOOK_CLIP_STRENGTH
    )
    assert (ResourceRole.EMBEDDING, "detail.pt") in resources
    assert (ResourceRole.VISION_ENCODER, "vision.safetensors") in resources
    assert (ResourceRole.STYLE_MODEL, "style.safetensors") in resources
    assert (ResourceRole.MODEL_PATCH, "reference.safetensors") in resources
    assert (ResourceRole.GLIGEN, "gligen.safetensors") in resources
    assert "prompt_style_expansion_unavailable" not in {issue.code for issue in result.issues}
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


def test_easy_unsampler_extracts_its_reverse_sampling_settings() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": EASY_UNSAMPLER_WIDTH,
                "height": EASY_UNSAMPLER_HEIGHT,
            },
        },
        "3": {
            "class_type": "easy unSampler",
            "inputs": {
                "model": ["1", 0],
                "latent_image": ["2", 0],
                "steps": EASY_UNSAMPLER_STEPS,
                "end_at_step": 0,
                "cfg": EASY_UNSAMPLER_CFG,
                "sampler_name": "euler",
                "scheduler": "normal",
            },
        },
        "4": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["1", 2]},
        },
        "5": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["4", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "3"
    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.settings.steps == EASY_UNSAMPLER_STEPS
    assert result.settings.cfg_scale == EASY_UNSAMPLER_CFG
    assert result.settings.sampler == "euler"
    assert result.settings.scheduler == "normal"
    assert result.settings.width == EASY_UNSAMPLER_WIDTH
    assert result.settings.height == EASY_UNSAMPLER_HEIGHT


@pytest.mark.parametrize(
    ("class_type", "expected_scheduler"),
    [
        ("Sigmas ConwaySequence", "res4lyf_conway_sequence"),
        ("Sigmas GilbreathSequence", "res4lyf_gilbreath_sequence"),
        ("Sigmas HarmonicDecay", "res4lyf_harmonic_decay"),
        ("Sigmas LangevinDynamics", "res4lyf_langevin_dynamics"),
        ("Sigmas NormalizingFlows", "res4lyf_normalizing_flows"),
        ("Sigmas PersistentHomology", "res4lyf_persistent_homology"),
        ("Sigmas RiemannianFlow", "res4lyf_riemannian_flow"),
        ("Sigmas StepwiseMultirate", "res4lyf_stepwise_multirate"),
        ("ExtendIntermediateSigmas", "extended_intermediate"),
    ],
)
def test_custom_sigma_generators_supply_scheduler_name_and_steps(
    class_type: str,
    expected_scheduler: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "3": {
            "class_type": "BasicGuider",
            "inputs": {"model": ["1", 0]},
        },
        "4": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "dpmpp_2m"},
        },
        "5": {
            "class_type": class_type,
            "inputs": {"steps": CUSTOM_SIGMA_STEPS},
        },
        "6": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": CUSTOM_SIGMA_SEED},
        },
        "7": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["6", 0],
                "guider": ["3", 0],
                "sampler": ["4", 0],
                "sigmas": ["5", 0],
                "latent_image": ["2", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["1", 2]},
        },
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.seed == CUSTOM_SIGMA_SEED
    assert result.settings.steps == CUSTOM_SIGMA_STEPS
    assert result.settings.sampler == "dpmpp_2m"
    assert result.settings.scheduler == expected_scheduler


def test_sigma_transform_does_not_misreport_upstream_scheduler() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "3": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
        "4": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "5": {
            "class_type": "KarrasScheduler",
            "inputs": {"steps": CUSTOM_SIGMA_STEPS},
        },
        "6": {
            "class_type": "FlipSigmas",
            "inputs": {"sigmas": ["5", 0]},
        },
        "7": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "guider": ["3", 0],
                "sampler": ["4", 0],
                "sigmas": ["6", 0],
                "latent_image": ["2", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0]}},
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.steps == CUSTOM_SIGMA_STEPS
    assert result.settings.scheduler == "custom"
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    ("provider_class", "expected_sampler"),
    [
        ("SamplerEulerCFGpp", "euler_cfg_pp"),
        ("SamplerLCM", "lcm"),
        ("VOIDSampler", "void_ddim"),
    ],
)
def test_current_sampler_providers_emit_stable_names(
    provider_class: str,
    expected_sampler: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "3": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
        "4": {"class_type": provider_class, "inputs": {}},
        "5": {"class_type": "KarrasScheduler", "inputs": {"steps": 12}},
        "6": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "guider": ["3", 0],
                "sampler": ["4", 0],
                "sigmas": ["5", 0],
                "latent_image": ["2", 0],
            },
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0]}},
        "8": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["7", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.sampler == expected_sampler
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    ("provider_class", "noise_device", "expected_sampler"),
    [
        ("SamplerDPMPP_2M_SDE", "cpu", "dpmpp_2m_sde"),
        ("SamplerDPMPP_2M_SDE", "gpu", "dpmpp_2m_sde_gpu"),
        ("SamplerDPMPP_3M_SDE", "cpu", "dpmpp_3m_sde"),
        ("SamplerDPMPP_3M_SDE", "gpu", "dpmpp_3m_sde_gpu"),
        ("SamplerDPMPP_SDE", "cpu", "dpmpp_sde"),
        ("SamplerDPMPP_SDE", "gpu", "dpmpp_sde_gpu"),
    ],
)
def test_device_specific_sampler_providers_preserve_gpu_variant(
    provider_class: str,
    noise_device: str,
    expected_sampler: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "3": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
        "4": {
            "class_type": provider_class,
            "inputs": {"noise_device": noise_device},
        },
        "5": {"class_type": "KarrasScheduler", "inputs": {"steps": 12}},
        "6": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "guider": ["3", 0],
                "sampler": ["4", 0],
                "sigmas": ["5", 0],
                "latent_image": ["2", 0],
            },
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0]}},
        "8": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["7", 0]},
        },
    }

    assert scan_workflow(prompt).settings.sampler == expected_sampler


@pytest.mark.parametrize(
    ("sigma_class", "sigma_inputs", "expected_scheduler", "expected_steps"),
    [
        (
            "CustomSigmas",
            {
                "sigmas_string": "14.6, 6.4, 3.8, 0",
                "interpolate_to_steps": 9,
            },
            "custom_sigmas",
            9,
        ),
        (
            "ManualSigmas",
            {"sigmas": "14.6, 6.4, 3.8, 0"},
            "manual_sigmas",
            3,
        ),
    ],
)
def test_explicit_sigma_generators_preserve_schedule_and_steps(
    sigma_class: str,
    sigma_inputs: dict[str, object],
    expected_scheduler: str,
    expected_steps: int,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "3": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
        "4": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "5": {"class_type": sigma_class, "inputs": sigma_inputs},
        "6": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "guider": ["3", 0],
                "sampler": ["4", 0],
                "sigmas": ["5", 0],
                "latent_image": ["2", 0],
            },
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0]}},
        "8": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["7", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.scheduler == expected_scheduler
    assert result.settings.steps == expected_steps


def test_malformed_manual_sigmas_leave_steps_unknown_without_crashing() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "3": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
        "4": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "5": {"class_type": "ManualSigmas", "inputs": {"sigmas": "not numbers"}},
        "6": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "guider": ["3", 0],
                "sampler": ["4", 0],
                "sigmas": ["5", 0],
                "latent_image": ["2", 0],
            },
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0]}},
        "8": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["7", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.scheduler == "manual_sigmas"
    assert result.settings.steps is None


def test_lying_sigma_sampler_preserves_upstream_sampler_name() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "3": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
        "4": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "5": {
            "class_type": "LyingSigmaSampler",
            "inputs": {"sampler": ["4", 0], "dishonesty_factor": -0.05},
        },
        "6": {"class_type": "KarrasScheduler", "inputs": {"steps": 12}},
        "7": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "guider": ["3", 0],
                "sampler": ["5", 0],
                "sigmas": ["6", 0],
                "latent_image": ["2", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0]}},
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.sampler == "euler"
    assert "sampler_wrapper_present" in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    ("class_type", "inputs", "issue_code"),
    [
        ("easy XYInputs: Checkpoint", {}, "dynamic_resource_selection_ambiguous"),
        ("ClownOptions_SwapSampler_Beta", {}, "sampler_swap_schedule_present"),
        (
            "CR Cycle Models",
            {"mode": "Sequential"},
            "dynamic_resource_selection_ambiguous",
        ),
        (
            "CR Load Scheduled Models",
            {"mode": "Load schedule"},
            "dynamic_resource_selection_ambiguous",
        ),
        (
            "easy stylesSelector",
            {"styles": "cinematic"},
            "prompt_style_expansion_unavailable",
        ),
        (
            "Prompt Styles Selector",
            {"style": "cinematic"},
            "prompt_style_expansion_unavailable",
        ),
        (
            "Prompt Multiple Styles Selector",
            {"style_1": "cinematic"},
            "prompt_style_expansion_unavailable",
        ),
        (
            "Text Parse A1111 Embeddings",
            {},
            "implicit_embedding_expansion_unavailable",
        ),
        ("LyingSigmaSampler", {}, "sampler_wrapper_present"),
    ],
)
def test_dynamic_controls_emit_sanitized_semantic_warnings(
    class_type: str,
    inputs: dict[str, object],
    issue_code: str,
) -> None:
    prompt: Prompt = {
        "1": {"class_type": class_type, "inputs": inputs},
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert issue_code in {issue.code for issue in result.issues}
    assert "unknown_active_node_class" not in {issue.code for issue in result.issues}


def test_style_selector_without_selected_style_does_not_warn() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "easy stylesSelector",
            "inputs": {
                "styles": "none",
                "select_styles": (),
                "positive": "base positive",
                "negative": "base negative",
            },
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert "prompt_style_expansion_unavailable" not in {issue.code for issue in result.issues}


def test_static_comfyroll_default_model_does_not_emit_dynamic_warning() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CR Load Scheduled Models",
            "inputs": {
                "mode": "Load default model",
                "default_model": "checkpoints/default.safetensors",
            },
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert "dynamic_resource_selection_ambiguous" not in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    ("loader_class", "generate_class"),
    [
        ("Step1XEditModelLoader", "Step1XEditGenerate"),
        ("Step1XEditTeaCacheModelLoader", "Step1XEditTeaCacheGenerate"),
    ],
)
def test_step1x_integrated_generator_extracts_resources_prompts_and_settings(
    loader_class: str,
    generate_class: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": loader_class,
            "inputs": {
                "diffusion_model": "diffusion_models/step1x.safetensors",
                "vae": "vae/step1x-vae.safetensors",
                "text_encoder": "text_encoders/Qwen2.5-VL-7B-Instruct",
            },
        },
        "2": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
        "3": {
            "class_type": generate_class,
            "inputs": {
                "model": ["1", 0],
                "input_image": ["2", 0],
                "prompt": "replace the sky with aurora",
                "negative_prompt": "compression artifacts",
                "num_steps": STEP1X_STEPS,
                "cfg_guidance": STEP1X_CFG,
                "seed": STEP1X_SEED,
                "size_level": 512,
            },
        },
        "4": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["3", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "3"
    assert result.workflow_kind is WorkflowKind.IMG2IMG
    assert result.primary_resource_key == "1:diffusion_model"
    assert result.selected_vae_resource_key == "1:vae"
    assert result.prompts.positive.text == "replace the sky with aurora"
    assert result.prompts.negative.text == "compression artifacts"
    assert result.settings.seed == STEP1X_SEED
    assert result.settings.steps == STEP1X_STEPS
    assert result.settings.cfg_scale == STEP1X_CFG
    assert {(resource.role, resource.filename) for resource in result.resources} == {
        (ResourceRole.BASE_MODEL, "step1x.safetensors"),
        (ResourceRole.VAE, "step1x-vae.safetensors"),
        (ResourceRole.TEXT_ENCODER, "Qwen2.5-VL-7B-Instruct"),
    }


def test_searge_sdxl_prompt_encoder_uses_connected_output_channels() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/sdxl.safetensors"},
        },
        "2": {
            "class_type": "SeargeSDXLPromptEncoder",
            "inputs": {
                "pos_g": "global positive",
                "pos_l": "local positive",
                "pos_r": "refiner positive",
                "neg_g": "global negative",
                "neg_l": "local negative",
                "neg_r": "refiner negative",
            },
        },
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 1024},
        },
        "20": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["2", 1],
                "latent_image": ["10", 0],
            },
        },
        "30": {"class_type": "VAEDecode", "inputs": {"samples": ["20", 0]}},
        "40": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["30", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.prompts.positive.text == "global positive\nlocal positive"
    assert result.prompts.negative.text == "global negative\nlocal negative"
    assert "positive_prompt_ambiguous" not in {issue.code for issue in result.issues}
    assert "negative_prompt_ambiguous" not in {issue.code for issue in result.issues}


def test_wan_multigpu_wrappers_preserve_model_and_prompt_detection() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "WanVideoModelLoaderMultiGPU",
            "inputs": {"model": "diffusion_models/wan2.2.safetensors"},
        },
        "2": {
            "class_type": "WanVideoTextEncodeMultiGPU",
            "inputs": {
                "positive_prompt": "cinematic ocean",
                "negative_prompt": "flicker",
            },
        },
        "3": {"class_type": "EmptyLatentImage", "inputs": {}},
        "4": {
            "class_type": "WanVideoSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["2", 1],
                "latent_image": ["3", 0],
                "seed": 4,
                "steps": 12,
            },
        },
        "5": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0]}},
        "6": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["5", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.primary_resource_key == "1:model"
    assert result.prompts.positive.text == "cinematic ocean"
    assert result.prompts.negative.text == "flicker"
    assert any(
        resource.filename == "wan2.2.safetensors" and resource.role is ResourceRole.BASE_MODEL
        for resource in result.resources
    )


def test_smart_resolution_calc_is_known_and_supplies_dimensions() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "diffusion_models/model.safetensors"},
        },
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/model.safetensors"}},
        "3": {
            "class_type": "SmartResolutionCalc",
            "inputs": {
                "vae": ["2", 0],
                "width": 832,
                "height": 1216,
                "batch_size": 1,
            },
        },
        "4": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", 0], "latent_image": ["3", 0]},
        },
        "5": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["4", 0], "vae": ["2", 0]},
        },
        "6": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["5", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert (result.settings.width, result.settings.height) == (832, 1216)
    assert not any(
        issue.code == "unknown_active_node_class" and issue.node_id == "3"
        for issue in result.issues
    )


@pytest.mark.parametrize(
    ("stage_class", "extra_inputs"),
    [
        (
            "RegionalSampler",
            {
                "seed_2nd": 0,
                "seed_2nd_mode": "ignore",
                "base_only_steps": 2,
                "regional_prompts": ["7", 0],
            },
        ),
        (
            "TwoAdvancedSamplersForMask",
            {
                "mask_sampler": ["6", 0],
                "mask": ["8", 0],
            },
        ),
    ],
)
def test_impact_regional_sampler_follows_base_sampler_provider(
    stage_class: str,
    extra_inputs: dict[str, object],
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/impact-base.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "regional base prompt"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "regional negative"},
        },
        "4": {
            "class_type": "ToBasicPipe",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "vae": ["1", 2],
                "positive": ["2", 0],
                "negative": ["3", 0],
            },
        },
        "5": {
            "class_type": "KSamplerAdvancedProvider",
            "inputs": {
                "basic_pipe": ["4", 0],
                "cfg": IMPACT_CFG,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "sigma_factor": 1.0,
            },
        },
        "6": {
            "class_type": "KSamplerAdvancedProvider",
            "inputs": {
                "basic_pipe": ["4", 0],
                "cfg": IMPACT_CFG,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "sigma_factor": 1.0,
            },
        },
        "7": {"class_type": "RegionalPrompt", "inputs": {"advanced_sampler": ["6", 0]}},
        "8": {"class_type": "SolidMask", "inputs": {"value": 1.0}},
        "9": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 896, "height": 1152, "batch_size": 1},
        },
        "10": {
            "class_type": stage_class,
            "inputs": {
                "seed": IMPACT_SEED,
                "steps": IMPACT_STEPS,
                "denoise": IMPACT_DENOISE,
                "samples": ["9", 0],
                "base_sampler": ["5", 0],
                **extra_inputs,
            },
        },
        "11": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["10", 0], "vae": ["1", 2]},
        },
        "12": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["11", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "10"
    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.primary_resource_key == "1:ckpt_name"
    assert result.prompts.positive.text == "regional base prompt"
    assert result.prompts.negative.text == "regional negative"
    assert result.settings.seed == IMPACT_SEED
    assert result.settings.steps == IMPACT_STEPS
    assert result.settings.sampler == "dpmpp_2m"
    assert result.settings.scheduler == "karras"
    assert result.settings.cfg_scale == IMPACT_CFG
    assert result.settings.denoise == IMPACT_DENOISE
    assert (result.settings.width, result.settings.height) == (896, 1152)


def test_wan_sampler_settings_chain_extracts_active_metadata() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "WanVideoModelLoader",
            "inputs": {"model": "diffusion_models/wan2.2.safetensors"},
        },
        "2": {
            "class_type": "LoadWanVideoT5TextEncoder",
            "inputs": {"model_name": "text_encoders/umt5-xxl.safetensors"},
        },
        "3": {
            "class_type": "WanVideoTextEncode",
            "inputs": {
                "t5": ["2", 0],
                "positive_prompt": "a quiet ocean at dawn",
                "negative_prompt": "flicker",
            },
        },
        "4": {
            "class_type": "WanVideoEmptyEmbeds",
            "inputs": {"width": 832, "height": 480, "num_frames": 33},
        },
        "5": {
            "class_type": "WanVideoSamplerSettings",
            "inputs": {
                "model": ["1", 0],
                "text_embeds": ["3", 0],
                "image_embeds": ["4", 0],
                "steps": WAN_SETTINGS_STEPS,
                "cfg": WAN_SETTINGS_CFG,
                "seed": WAN_SETTINGS_SEED,
                "scheduler": "unipc",
                "denoise_strength": WAN_SETTINGS_DENOISE,
            },
        },
        "6": {
            "class_type": "WanVideoSamplerFromSettings",
            "inputs": {"sampler_inputs": ["5", 0]},
        },
        "7": {
            "class_type": "WanVideoTinyVAELoader",
            "inputs": {"model_name": "vae_approx/taef1_decoder.pth"},
        },
        "8": {
            "class_type": "WanVideoDecode",
            "inputs": {"samples": ["6", 0], "vae": ["7", 0]},
        },
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "6"
    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.primary_resource_key == "1:model"
    assert result.selected_vae_resource_key == "7:model_name"
    assert result.prompts.positive.text == "a quiet ocean at dawn"
    assert result.prompts.negative.text == "flicker"
    assert result.settings.seed == WAN_SETTINGS_SEED
    assert result.settings.steps == WAN_SETTINGS_STEPS
    assert result.settings.scheduler == "unipc"
    assert result.settings.cfg_scale == WAN_SETTINGS_CFG
    assert result.settings.denoise == WAN_SETTINGS_DENOISE
    assert (result.settings.width, result.settings.height) == (832, 480)
    assert {(resource.role, resource.filename) for resource in result.resources} == {
        (ResourceRole.BASE_MODEL, "wan2.2.safetensors"),
        (ResourceRole.TEXT_ENCODER, "umt5-xxl.safetensors"),
        (ResourceRole.VAE, "taef1_decoder.pth"),
    }


@pytest.mark.parametrize(
    ("stage_class", "latent_input"),
    [
        ("RegionalSamplerAdvanced", "latent_image"),
        ("TwoSamplersForMask", "latent_image"),
    ],
)
def test_impact_sampler_variants_extract_provider_settings(
    stage_class: str,
    latent_input: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/impact-variant.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "provider positive"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "provider negative"},
        },
        "4": {
            "class_type": "ToBasicPipe",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "vae": ["1", 2],
                "positive": ["2", 0],
                "negative": ["3", 0],
            },
        },
        "5": {
            "class_type": "KSamplerProvider",
            "inputs": {
                "basic_pipe": ["4", 0],
                "seed": IMPACT_SEED,
                "steps": IMPACT_STEPS,
                "cfg": IMPACT_CFG,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": IMPACT_DENOISE,
            },
        },
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 640, "height": 960, "batch_size": 1},
        },
        "7": {
            "class_type": stage_class,
            "inputs": {
                latent_input: ["6", 0],
                "base_sampler": ["5", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["1", 2]},
        },
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "7"
    assert result.primary_resource_key == "1:ckpt_name"
    assert result.prompts.positive.text == "provider positive"
    assert result.prompts.negative.text == "provider negative"
    assert result.settings.seed == IMPACT_SEED
    assert result.settings.steps == IMPACT_STEPS
    assert result.settings.sampler == "euler"
    assert result.settings.scheduler == "normal"
    assert result.settings.cfg_scale == IMPACT_CFG
    assert result.settings.denoise == IMPACT_DENOISE


@pytest.mark.parametrize("loader_class", ["DiffusersLoader", "Diffusers Model Loader"])
def test_diffusers_pipeline_loader_is_recorded_without_guessing_file_identity(
    loader_class: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": loader_class,
            "inputs": {"model_path": "diffusers/example-pipeline"},
        },
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", 0], "latent_image": ["2", 0]},
        },
        "4": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["3", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.primary_resource_key == "1:model_path"
    assert len(result.resources) == 1
    assert result.resources[0].filename == "example-pipeline"
    assert result.resources[0].detection_rule_id == "diffusers_pipeline_loader"


@pytest.mark.parametrize("loader_class", ["ClownModelLoader", "FluxLoader"])
def test_res4lyf_integrated_loader_tracks_optional_text_encoders(
    loader_class: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": loader_class,
            "inputs": {
                "model_name": "diffusion_models/model.safetensors",
                "clip_name1_opt": "text_encoders/clip-l.safetensors",
                "clip_name2_opt": "text_encoders/t5xxl.safetensors",
                "vae_name": "vae/ae.safetensors",
            },
        },
        "2": {"class_type": "EmptyLatentImage", "inputs": {}},
        "3": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", 0], "latent_image": ["2", 0]},
        },
        "4": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["3", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.primary_resource_key == "1:model_name"
    assert {(resource.role, resource.filename) for resource in result.resources} == {
        (ResourceRole.BASE_MODEL, "model.safetensors"),
        (ResourceRole.TEXT_ENCODER, "clip-l.safetensors"),
        (ResourceRole.TEXT_ENCODER, "t5xxl.safetensors"),
        (ResourceRole.VAE, "ae.safetensors"),
    }


@pytest.mark.parametrize(
    "loader_class",
    ["NunchakuQwenImageDiTLoader", "NunchakuZImageDiTLoader"],
)
def test_current_nunchaku_diffusion_loaders_are_primary_resources(
    loader_class: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": loader_class,
            "inputs": {"model_name": "diffusion_models/nunchaku-model.safetensors"},
        },
        "2": {"class_type": "EmptyLatentImage", "inputs": {}},
        "3": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", 0], "latent_image": ["2", 0]},
        },
        "4": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["3", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.primary_resource_key == "1:model_name"
    assert len(result.resources) == 1
    assert result.resources[0].filename == "nunchaku-model.safetensors"
    assert result.resources[0].detection_rule_id == "nunchaku_diffusion_loader"


def test_current_nunchaku_auxiliary_resources_are_detected_conservatively() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "NunchakuQwenImageDiTLoader",
            "inputs": {"model_name": "diffusion_models/nunchaku-model.safetensors"},
        },
        "2": {
            "class_type": "NunchakuTextEncoderLoaderV2",
            "inputs": {
                "text_encoder1": "text_encoders/clip-l.safetensors",
                "text_encoder2": "text_encoders/t5xxl.safetensors",
            },
        },
        "3": {
            "class_type": "NunchakuFluxLoraStack",
            "inputs": {
                "model": ["1", 0],
                "lora_name_1": "loras/style.safetensors",
                "lora_strength_1": 0.75,
                "lora_name_2": "None",
                "lora_strength_2": 1.0,
            },
        },
        "4": {
            "class_type": "NunchakuPuLIDLoaderV2",
            "inputs": {
                "model": ["3", 0],
                "pulid_file": "pulid/pulid_flux_v0.9.1.safetensors",
                "eva_clip_file": "clip/eva_clip.safetensors",
            },
        },
        "5": {"class_type": "EmptyLatentImage", "inputs": {}},
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": "nunchaku positive"},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": "nunchaku negative"},
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert {
        (
            resource.role,
            resource.filename,
            resource.strengths.weight,
            resource.detection_rule_id,
        )
        for resource in result.resources
    } == {
        (
            ResourceRole.BASE_MODEL,
            "nunchaku-model.safetensors",
            None,
            "nunchaku_diffusion_loader",
        ),
        (
            ResourceRole.TEXT_ENCODER,
            "clip-l.safetensors",
            None,
            "nunchaku_text_encoder_loader",
        ),
        (
            ResourceRole.TEXT_ENCODER,
            "t5xxl.safetensors",
            None,
            "nunchaku_text_encoder_loader",
        ),
        (
            ResourceRole.LORA,
            "style.safetensors",
            0.75,
            "numbered_lora_stack",
        ),
        (
            ResourceRole.IPADAPTER,
            "pulid_flux_v0.9.1.safetensors",
            None,
            "nunchaku_pulid_loader",
        ),
    }


def test_wan_diffusion_forcing_sampler_extracts_direct_settings() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "WanVideoModelLoader",
            "inputs": {"model": "diffusion_models/wan2.2.safetensors"},
        },
        "2": {
            "class_type": "WanVideoTextEncode",
            "inputs": {
                "positive_prompt": "a lantern drifting over water",
                "negative_prompt": "flicker",
            },
        },
        "3": {
            "class_type": "WanVideoEmptyEmbeds",
            "inputs": {"width": 768, "height": 432, "num_frames": 33},
        },
        "4": {
            "class_type": "WanVideoDiffusionForcingSampler",
            "inputs": {
                "model": ["1", 0],
                "text_embeds": ["2", 0],
                "image_embeds": ["3", 0],
                "steps": WAN_FORCING_STEPS,
                "cfg": WAN_FORCING_CFG,
                "seed": WAN_FORCING_SEED,
                "scheduler": "unipc",
                "denoise_strength": WAN_FORCING_DENOISE,
            },
        },
        "5": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["4", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "4"
    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.primary_resource_key == "1:model"
    assert result.prompts.positive.text == "a lantern drifting over water"
    assert result.prompts.negative.text == "flicker"
    assert result.settings.seed == WAN_FORCING_SEED
    assert result.settings.steps == WAN_FORCING_STEPS
    assert result.settings.scheduler == "unipc"
    assert result.settings.cfg_scale == WAN_FORCING_CFG
    assert result.settings.denoise == WAN_FORCING_DENOISE
    assert (result.settings.width, result.settings.height) == (768, 432)


def test_antrobots_sample_is_recognized_only_by_its_full_sampler_contract() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "source-backed sample prompt"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "source-backed sample negative"},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 832, "height": 1216, "batch_size": 1},
        },
        "5": {
            "class_type": "sample",
            "inputs": {
                "model": ["1", 0],
                "add_noise": True,
                "noise_seed": ANTROBOTS_SAMPLE_SEED,
                "steps": ANTROBOTS_SAMPLE_STEPS,
                "cfg": 6.5,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "start_at_step": 0,
                "end_at_step": ANTROBOTS_SAMPLE_STEPS,
                "return_with_leftover_noise": False,
                "denoise": ANTROBOTS_SAMPLE_DENOISE,
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["6", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "5"
    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.primary_resource_key == "1:ckpt_name"
    assert result.prompts.positive.text == "source-backed sample prompt"
    assert result.prompts.negative.text == "source-backed sample negative"
    assert result.settings.seed == ANTROBOTS_SAMPLE_SEED
    assert result.settings.steps == ANTROBOTS_SAMPLE_STEPS
    assert result.settings.denoise == ANTROBOTS_SAMPLE_DENOISE

    fake_result = scan_workflow(
        {
            "1": {
                "class_type": "sample",
                "inputs": {"model": ["2", 0]},
            },
            "2": {"class_type": "UnknownModelProvider", "inputs": {}},
            "3": {
                "class_type": "CCollins_CiviScribe_SaveImage",
                "inputs": {"images": ["1", 0]},
            },
        }
    )
    assert fake_result.selected_stage_node_id is None
    assert "sampler_stage_not_found" in {issue.code for issue in fake_result.issues}


def test_antrobots_refiner_tracks_both_models_and_selected_refiner_vae() -> None:
    prompt: Prompt = {
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
            "inputs": {"vae_name": "vae/base-vae.safetensors"},
        },
        "4": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "vae/refiner-vae.safetensors"},
        },
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "shared prompt"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "shared negative"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "shared prompt"}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": "shared negative"}},
        "9": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
        },
        "10": {
            "class_type": "refine",
            "inputs": {
                "base_model": ["1", 0],
                "refiner_model": ["2", 0],
                "total_steps": ANTROBOTS_REFINE_STEPS,
                "refine_step": 20,
                "base_positive": ["5", 0],
                "base_negative": ["6", 0],
                "refine_positive": ["7", 0],
                "refine_negative": ["8", 0],
                "base_vae": ["3", 0],
                "refine_vae": ["4", 0],
                "base_denoise": ANTROBOTS_REFINE_DENOISE,
                "refine_denoise": ANTROBOTS_REFINE_DENOISE,
                "seed": 991,
                "cfg": 5.5,
                "sampler_name": "dpmpp_2m_sde",
                "scheduler": "karras",
                "latent_image": ["9", 0],
            },
        },
        "11": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["10", 0], "vae": ["10", 1]},
        },
        "12": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["11", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "10"
    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.primary_resource_key == "1:ckpt_name"
    assert result.selected_vae_resource_key == "4:vae_name"
    assert result.prompts.positive.text == "shared prompt"
    assert result.prompts.negative.text == "shared negative"
    assert result.settings.steps == ANTROBOTS_REFINE_STEPS
    assert result.settings.denoise == ANTROBOTS_REFINE_DENOISE
    assert {resource.filename for resource in result.resources} == {
        "base.safetensors",
        "refiner.safetensors",
        "base-vae.safetensors",
        "refiner-vae.safetensors",
    }


@pytest.mark.parametrize(
    ("use_image", "expected_kind"),
    [(False, WorkflowKind.TXT2IMG), (True, WorkflowKind.IMG2IMG)],
)
def test_antrobots_refine_pipe_uses_runtime_image_mode(
    use_image: bool,
    expected_kind: WorkflowKind,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/refiner.safetensors"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/base.vae"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/refiner.vae"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "same prompt"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "same negative"}},
        "7": {
            "class_type": "ToBasicPipe",
            "inputs": {
                "model": ["1", 0],
                "vae": ["3", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
            },
        },
        "8": {
            "class_type": "ToBasicPipe",
            "inputs": {
                "model": ["2", 0],
                "vae": ["4", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
            },
        },
        "9": {
            "class_type": "EmptyImage",
            "inputs": {"width": 768, "height": 1152},
        },
        "10": {
            "class_type": "refine_pipe",
            "inputs": {
                "base_pipe": ["7", 0],
                "refine_pipe": ["8", 0],
                "total_steps": 28,
                "refine_step": 18,
                "base_denoise": 1.0,
                "refine_denoise": 1.0,
                "seed": 12345,
                "cfg": 6.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "image": ["9", 0],
                "use_image": use_image,
            },
        },
        "11": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["10", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "10"
    assert result.workflow_kind is expected_kind
    assert result.primary_resource_key == "1:ckpt_name"
    assert result.selected_vae_resource_key == "4:vae_name"
    assert result.prompts.positive.text == "same prompt"
    assert result.prompts.negative.text == "same negative"
