from __future__ import annotations

from typing import cast

import pytest

from civiscribe.domain import ResourceKind, ResourceRole, WorkflowKind, WorkflowScan
from civiscribe.workflow import scan_workflow

type Prompt = dict[str, dict[str, object]]

FLUX_TRAINER_SEED = 123
FLUX_TRAINER_STEPS = 18
WITH_ANYONE_SEED = 987
WITH_ANYONE_STEPS = 12
EASY_DETAILER_SEED = 456
EASY_DETAILER_STEPS = 23
DIRECT_API_SEED = 12345
DIRECT_EDIT_SEED = 6789
DIRECT_EDIT_STEPS = 18
LINEAR_QUADRATIC_STEPS = 24
SAGE_SAMPLER_SEED = 2468
SAGE_SAMPLER_STEPS = 17
ECLIPSE_CONTEXT_SEED = 44
ECLIPSE_CONTEXT_STEPS = 24
IGMV_SEED = 66
IGMV_STEPS = 30


def _resource_filenames(result: WorkflowScan) -> set[str]:
    return {resource.filename for resource in result.resources}


def _issue_codes(result: WorkflowScan) -> set[str]:
    return {issue.code for issue in result.issues}


def test_flux_trainer_integrated_sampler_extracts_resources_settings_and_primary() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "FluxTrainModelSelect",
            "inputs": {
                "transformer": "diffusion_models/flux-dev.safetensors",
                "vae": "vae/ae.safetensors",
                "clip_l": "text_encoders/clip_l.safetensors",
                "t5": "text_encoders/t5xxl_fp16.safetensors",
            },
        },
        "2": {
            "class_type": "FluxKohyaInferenceSampler",
            "inputs": {
                "flux_models": ["1", 0],
                "lora_name": "loras/subject.safetensors",
                "lora_weight": 0.65,
                "seed": FLUX_TRAINER_SEED,
                "num_steps": FLUX_TRAINER_STEPS,
                "guidance_scale": 3.5,
                "width": 1024,
                "height": 768,
            },
        },
        "3": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "2"
    assert result.primary_resource_key == "1:transformer"
    assert _resource_filenames(result) == {
        "flux-dev.safetensors",
        "ae.safetensors",
        "clip_l.safetensors",
        "t5xxl_fp16.safetensors",
        "subject.safetensors",
    }
    lora = next(resource for resource in result.resources if resource.role is ResourceRole.LORA)
    assert lora.strengths.weight == pytest.approx(0.65)
    assert result.settings.seed == FLUX_TRAINER_SEED
    assert result.settings.steps == FLUX_TRAINER_STEPS
    assert result.settings.guidance == pytest.approx(3.5)
    assert (result.settings.width, result.settings.height) == (1024, 768)


def test_withanyone_tracks_files_but_not_siglip_directory() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "WithAnyoneModelLoaderNode",
            "inputs": {
                "flux_name": "diffusion_models/flux-dev.safetensors",
                "ipa_name": "ipadapter/with-anyone.safetensors",
                "siglip_name": "text_encoders/siglip-directory",
                "lora_name": "loras/identity.safetensors",
                "lora_weight": 0.8,
            },
        },
        "2": {
            "class_type": "WithAnyoneSamplerNode",
            "inputs": {
                "withAnyone_pipeline": ["1", 0],
                "seed": WITH_ANYONE_SEED,
                "num_steps": WITH_ANYONE_STEPS,
                "width": 832,
                "height": 1216,
            },
        },
        "3": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.primary_resource_key == "1:flux_name"
    assert _resource_filenames(result) == {
        "flux-dev.safetensors",
        "with-anyone.safetensors",
        "identity.safetensors",
    }
    assert result.settings.seed == WITH_ANYONE_SEED
    assert result.settings.steps == WITH_ANYONE_STEPS
    assert (result.settings.width, result.settings.height) == (832, 1216)


def test_zimage_integrated_loader_tracks_only_consumed_outputs() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "ZImageModelLoader",
            "inputs": {
                "model_name": "diffusion_models/z-image.safetensors",
                "vae_name": "vae/ae.safetensors",
                "clip_name": "text_encoders/qwen.gguf",
            },
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 2], "text": "positive"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 2], "text": "negative"},
        },
        "4": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 768, "height": 1024},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 1]},
        },
        "7": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["6", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.primary_resource_key == "1:model_name"
    assert result.selected_vae_resource_key == "1:vae_name"
    assert _resource_filenames(result) == {
        "z-image.safetensors",
        "ae.safetensors",
        "qwen.gguf",
    }


def test_zimage_unused_vae_and_clip_outputs_are_excluded() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "ZImageModelLoader",
            "inputs": {
                "model_name": "diffusion_models/z-image.safetensors",
                "vae_name": "vae/unused.safetensors",
                "clip_name": "text_encoders/unused.gguf",
            },
        },
        "2": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "vae/active.safetensors"},
        },
        "3": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 768, "height": 1024},
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

    assert _resource_filenames(result) == {"z-image.safetensors", "active.safetensors"}


@pytest.mark.parametrize(
    ("class_type", "loader_inputs", "output_index", "expected_checkpoint"),
    [
        (
            "A1rSeparateCheckpointLoader",
            {
                "ckpt_name_a": "checkpoints/a.safetensors",
                "ckpt_name_b": "checkpoints/b.safetensors",
                "vae_name": "vae/unused.safetensors",
                "separate_mode": True,
            },
            0,
            "b.safetensors",
        ),
        (
            "A1rDoubleCheckpointLoader",
            {
                "ckpt_name_a": "checkpoints/a.safetensors",
                "ckpt_name_b": "checkpoints/b.safetensors",
                "vae_name": "vae/unused.safetensors",
                "enable_second": True,
            },
            3,
            "b.safetensors",
        ),
        (
            "A1rDoubleCheckpointLoader",
            {
                "ckpt_name_a": "checkpoints/a.safetensors",
                "ckpt_name_b": "checkpoints/b.safetensors",
                "vae_name": "vae/unused.safetensors",
                "enable_second": False,
            },
            0,
            "a.safetensors",
        ),
        (
            "A1r Conditional CheckpointLoader",
            {
                "ckpt_name_a": "checkpoints/a.safetensors",
                "ckpt_name_b": "checkpoints/b.safetensors",
                "enable_second": True,
            },
            3,
            "b.safetensors",
        ),
        (
            "A1r Conditional CheckpointLoader",
            {
                "ckpt_name_a": "checkpoints/a.safetensors",
                "ckpt_name_b": "checkpoints/b.safetensors",
                "enable_second": False,
            },
            0,
            "a.safetensors",
        ),
    ],
)
def test_a1r_checkpoint_loaders_follow_selected_branch(
    class_type: str,
    loader_inputs: dict[str, object],
    output_index: int,
    expected_checkpoint: str,
) -> None:
    prompt: Prompt = {
        "1": {"class_type": class_type, "inputs": loader_inputs},
        "2": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", output_index], "latent_image": ["2", 0]},
        },
        "4": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["3", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {expected_checkpoint}
    assert result.primary_resource_key is not None


def test_a1r_six_lora_loader_omits_disabled_slot_and_keeps_strengths() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "diffusion_models/base.safetensors"},
        },
        "2": {
            "class_type": "A1rSixLoraLoader",
            "inputs": {
                "model_a": ["1", 0],
                "lora_name_1": "loras/active.safetensors",
                "enable_lora_1": True,
                "model_strength_1": 0.7,
                "clip_strength_1": 0.4,
                "lora_name_2": "loras/disabled.safetensors",
                "enable_lora_2": False,
                "model_strength_2": 1.0,
                "clip_strength_2": 1.0,
            },
        },
        "3": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "4": {
            "class_type": "KSampler",
            "inputs": {"model": ["2", 0], "latent_image": ["3", 0]},
        },
        "5": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["4", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {"base.safetensors", "active.safetensors"}
    lora = next(resource for resource in result.resources if resource.role is ResourceRole.LORA)
    assert lora.strengths.model == pytest.approx(0.7)
    assert lora.strengths.clip == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("selected_index", "expected_filename"),
    [(1, "b.safetensors"), (-1, "c.safetensors"), (999, "c.safetensors")],
)
def test_impact_static_list_selection_follows_runtime_semantics(
    selected_index: int,
    expected_filename: str,
) -> None:
    prompt: Prompt = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "a.safetensors"}},
        "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "b.safetensors"}},
        "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "c.safetensors"}},
        "4": {
            "class_type": "ImpactMakeAnyList",
            "inputs": {"value1": ["1", 0], "value2": ["2", 0], "value3": ["3", 0]},
        },
        "5": {
            "class_type": "ImpactSelectNthItemOfAnyList",
            "inputs": {"any_list": ["4", 0], "index": selected_index},
        },
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {"model": ["5", 0], "latent_image": ["6", 0]},
        },
        "8": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["7", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {expected_filename}


def test_impact_dynamic_list_selection_stays_conservatively_ambiguous() -> None:
    prompt: Prompt = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "a.safetensors"}},
        "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "b.safetensors"}},
        "3": {
            "class_type": "ImpactMakeAnyList",
            "inputs": {"value1": ["1", 0], "value2": ["2", 0]},
        },
        "4": {"class_type": "RuntimeIndex", "inputs": {}},
        "5": {
            "class_type": "ImpactSelectNthItemOfAnyList",
            "inputs": {"any_list": ["3", 0], "index": ["4", 0]},
        },
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {"model": ["5", 0], "latent_image": ["6", 0]},
        },
        "8": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["7", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {"a.safetensors", "b.safetensors"}
    assert "switch_selection_ambiguous" in _issue_codes(result)


def test_impact_static_list_uses_numeric_slot_order_past_nine() -> None:
    loaders: Prompt = {
        str(index): {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": f"slot-{index}.safetensors"},
        }
        for index in range(1, 11)
    }
    prompt: Prompt = {
        **loaders,
        "20": {
            "class_type": "ImpactMakeAnyList",
            "inputs": {f"value{index}": [str(index), 0] for index in range(1, 11)},
        },
        "21": {
            "class_type": "ImpactSelectNthItemOfAnyList",
            "inputs": {"any_list": ["20", 0], "index": 9},
        },
        "22": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "23": {
            "class_type": "KSampler",
            "inputs": {"model": ["21", 0], "latent_image": ["22", 0]},
        },
        "24": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["23", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {"slot-10.safetensors"}


def test_basic_pipe_model_output_does_not_activate_clip_or_vae_components() -> None:
    prompt: Prompt = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "active-model.safetensors"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "unused-clip.safetensors"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "unused-vae.safetensors"}},
        "4": {
            "class_type": "ToBasicPipe",
            "inputs": {"model": ["1", 0], "clip": ["2", 0], "vae": ["3", 0]},
        },
        "5": {"class_type": "FromBasicPipe", "inputs": {"basic_pipe": ["4", 0]}},
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {"model": ["5", 0], "latent_image": ["6", 0]},
        },
        "8": {"class_type": "VAELoader", "inputs": {"vae_name": "decode-vae.safetensors"}},
        "9": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["8", 0]},
        },
        "10": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["9", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {"active-model.safetensors", "decode-vae.safetensors"}


def test_conditioning_passthrough_output_is_branch_specific() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "base.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "positive"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "inactive negative"},
        },
        "4": {
            "class_type": "CondPassThrough",
            "inputs": {"positive": ["2", 0], "negative": ["3", 0]},
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
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["6", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert "2" in result.active_node_ids
    assert "3" not in result.active_node_ids
    assert result.prompts.positive.text == "positive"


def test_reencode_latent_pipe_tracks_both_vae_components_only() -> None:
    prompt: Prompt = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "unused-a.safetensors"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "unused-a-clip.safetensors"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "input-vae.safetensors"}},
        "4": {
            "class_type": "ToBasicPipe",
            "inputs": {"model": ["1", 0], "clip": ["2", 0], "vae": ["3", 0]},
        },
        "5": {"class_type": "UNETLoader", "inputs": {"unet_name": "unused-b.safetensors"}},
        "6": {"class_type": "CLIPLoader", "inputs": {"clip_name": "unused-b-clip.safetensors"}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": "output-vae.safetensors"}},
        "8": {
            "class_type": "ToBasicPipe",
            "inputs": {"model": ["5", 0], "clip": ["6", 0], "vae": ["7", 0]},
        },
        "9": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "10": {
            "class_type": "ReencodeLatentPipe",
            "inputs": {
                "samples": ["9", 0],
                "input_basic_pipe": ["4", 0],
                "output_basic_pipe": ["8", 0],
            },
        },
        "11": {"class_type": "UNETLoader", "inputs": {"unet_name": "active.safetensors"}},
        "12": {
            "class_type": "KSampler",
            "inputs": {"model": ["11", 0], "latent_image": ["10", 0]},
        },
        "13": {"class_type": "VAELoader", "inputs": {"vae_name": "decode-vae.safetensors"}},
        "14": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["12", 0], "vae": ["13", 0]},
        },
        "15": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["14", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {
        "input-vae.safetensors",
        "output-vae.safetensors",
        "active.safetensors",
        "decode-vae.safetensors",
    }


def _custom_sampler_prompt(sigma_class: str, sigma_inputs: dict[str, object]) -> Prompt:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "base.safetensors"}},
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
        "7": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["6", 0]},
        },
    }


@pytest.mark.parametrize(
    ("class_type", "inputs", "expected_steps"),
    [
        ("Sigmas From Text", {"text": "4, 2 1\n0"}, 3),
        ("FloatToSigmas", {"float_list": [4.0, 2.0, 0.0]}, 2),
        ("Sigmas From Text", {"text": "NaN, 1, 0"}, None),
        ("Sigmas From Text", {"text": "not-a-schedule"}, None),
    ],
)
def test_literal_sigma_nodes_extract_only_finite_well_formed_steps(
    class_type: str,
    inputs: dict[str, object],
    expected_steps: int | None,
) -> None:
    result = scan_workflow(_custom_sampler_prompt(class_type, inputs))

    assert result.settings.scheduler == "custom"
    assert result.settings.steps == expected_steps


@pytest.mark.parametrize(
    ("hook1_class", "hook1_sampler", "expected_sampler"),
    [
        ("CustomSamplerDetailerHookProvider", "dpmpp_2m", "dpmpp_2m"),
        ("PreviewDetailerHookProvider", None, "euler"),
    ],
)
def test_impact_detailer_custom_hook_precedence(
    hook1_class: str,
    hook1_sampler: str | None,
    expected_sampler: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/active.safetensors"}},
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "detail positive"},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "detail negative"},
        },
        "5": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
        "6": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "dpmpp_2m"}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {
            "class_type": hook1_class,
            "inputs": {"sampler": ["6", 0]} if hook1_sampler is not None else {"quality": 80},
        },
        "9": {
            "class_type": "CustomSamplerDetailerHookProvider",
            "inputs": {"sampler": ["7", 0]},
        },
        "10": {
            "class_type": "DetailerHookCombine",
            "inputs": {"hook1": ["8", 0], "hook2": ["9", 0]},
        },
        "11": {
            "class_type": "DetailerForEach",
            "inputs": {
                "image": ["5", 0],
                "model": ["1", 0],
                "clip": ["1", 1],
                "vae": ["2", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "seed": 42,
                "steps": 14,
                "cfg": 5.0,
                "sampler_name": "heun",
                "scheduler": "normal",
                "denoise": 0.45,
                "detailer_hook": ["10", 0],
            },
        },
        "12": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["11", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "11"
    assert result.workflow_kind is WorkflowKind.IMG2IMG
    assert result.settings.sampler == expected_sampler
    assert result.prompts.positive.text == "detail positive"
    assert result.prompts.negative.text == "detail negative"
    assert result.primary_resource_key == "1:ckpt_name"
    assert result.selected_vae_resource_key == "2:vae_name"
    assert "unknown_active_node_class" not in _issue_codes(result)


def test_unresolved_detailer_custom_sampler_does_not_report_stale_direct_value() -> None:
    prompt = cast(
        Prompt,
        {
            "1": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
            "2": {"class_type": "UnknownSamplerProvider", "inputs": {}},
            "3": {
                "class_type": "CustomSamplerDetailerHookProvider",
                "inputs": {"sampler": ["2", 0]},
            },
            "4": {
                "class_type": "DetailerForEach",
                "inputs": {
                    "image": ["1", 0],
                    "seed": 1,
                    "steps": 2,
                    "cfg": 3.0,
                    "sampler_name": "heun",
                    "scheduler": "normal",
                    "detailer_hook": ["3", 0],
                },
            },
            "5": {
                "class_type": "CCollins_CiviScribe_SaveImage",
                "inputs": {"images": ["4", 0]},
            },
        },
    )

    result = scan_workflow(prompt)

    assert result.settings.sampler is None
    assert "detailer_sampler_override_unresolved" in _issue_codes(result)


@pytest.mark.parametrize(
    "class_type",
    ["easy preDetailerFix", "easy preMaskDetailerFix"],
)
def test_easyuse_pre_detailer_is_the_sampling_stage_with_pipe_lineage(
    class_type: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/active.safetensors"}},
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "easy detail positive"},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "easy detail negative"},
        },
        "5": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
        "6": {
            "class_type": "ToBasicPipe",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "vae": ["2", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
            },
        },
        "7": {
            "class_type": class_type,
            "inputs": {
                "pipe": ["6", 0],
                "optional_image": ["5", 0],
                "mask": ["5", 1],
                "seed": EASY_DETAILER_SEED,
                "steps": EASY_DETAILER_STEPS,
                "cfg": 6.5,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 0.4,
            },
        },
        "8": {"class_type": "easy detailerFix", "inputs": {"pipe": ["7", 0]}},
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 1]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "7"
    assert result.workflow_kind is WorkflowKind.IMG2IMG
    assert result.settings.seed == EASY_DETAILER_SEED
    assert result.settings.steps == EASY_DETAILER_STEPS
    assert result.settings.cfg_scale == pytest.approx(6.5)
    assert result.settings.sampler == "dpmpp_2m"
    assert result.settings.scheduler == "karras"
    assert result.settings.denoise == pytest.approx(0.4)
    assert result.prompts.positive.text == "easy detail positive"
    assert result.prompts.negative.text == "easy detail negative"
    assert result.primary_resource_key == "1:ckpt_name"
    assert result.selected_vae_resource_key == "2:vae_name"
    assert "unknown_active_node_class" not in _issue_codes(result)


def test_conditioning_pair_projection_keeps_ltx_prompt_branches_separate() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/active.safetensors"}},
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "ltx positive"},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "ltx negative"},
        },
        "5": {"class_type": "LoadImage", "inputs": {"image": "guide.png"}},
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 768, "height": 512},
        },
        "7": {
            "class_type": "LTXVAddGuide",
            "inputs": {
                "positive": ["3", 0],
                "negative": ["4", 0],
                "vae": ["2", 0],
                "latent": ["6", 0],
                "image": ["5", 0],
            },
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["7", 0],
                "negative": ["7", 1],
                "latent_image": ["7", 2],
                "seed": 1,
                "steps": 2,
                "cfg": 3.0,
                "sampler_name": "euler",
                "scheduler": "normal",
            },
        },
        "9": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["8", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.prompts.positive.text == "ltx positive"
    assert result.prompts.negative.text == "ltx negative"
    assert "positive_prompt_ambiguous" not in _issue_codes(result)
    assert "negative_prompt_ambiguous" not in _issue_codes(result)
    assert "unknown_active_node_class" not in _issue_codes(result)
    assert _resource_filenames(result) == {"base.safetensors", "active.safetensors"}


def test_easyuse_runtime_prompt_composition_is_reported_explicitly() -> None:
    prompt: Prompt = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
        "2": {
            "class_type": "easy latentCompositeMaskedWithCond",
            "inputs": {
                "source_latent": ["1", 0],
                "text_combine": ["runtime", 0],
                "text_combine_mode": "replace",
                "replace_text": "subject",
            },
        },
        "3": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 1]},
        },
    }

    result = scan_workflow(prompt)

    assert "prompt_composition_runtime_dependent" in _issue_codes(result)
    assert "unknown_active_node_class" not in _issue_codes(result)


def test_direct_api_text_to_image_is_a_generation_stage_without_local_resource() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "Flux2ProImageNode",
            "inputs": {
                "prompt": "remote generated prompt",
                "model": "remote-service-model",
                "seed": DIRECT_API_SEED,
                "width": 1024,
                "height": 768,
                "images": None,
            },
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.selected_stage_node_id == "1"
    assert result.workflow_kind is WorkflowKind.TXT2IMG
    assert result.prompts.positive.text == "remote generated prompt"
    assert result.prompts.negative.text is None
    assert result.settings.seed == DIRECT_API_SEED
    assert (result.settings.width, result.settings.height) == (1024, 768)
    assert result.resources == ()
    assert result.primary_resource_key is None
    assert "primary_model_not_found" not in _issue_codes(result)


def test_direct_api_image_edit_extracts_only_safe_generation_fields() -> None:
    prompt: Prompt = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
        "2": {
            "class_type": "BriaImageEditNode",
            "inputs": {
                "model": "remote-service-model",
                "image": ["1", 0],
                "prompt": "edit prompt",
                "negative_prompt": "edit negative",
                "seed": DIRECT_EDIT_SEED,
                "guidance_scale": 4.25,
                "steps": DIRECT_EDIT_STEPS,
                "api_key": "DO_NOT_RECORD_API_KEY",
                "auth": "DO_NOT_RECORD_AUTH",
            },
        },
        "3": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.workflow_kind is WorkflowKind.IMG2IMG
    assert result.prompts.positive.text == "edit prompt"
    assert result.prompts.negative.text == "edit negative"
    assert result.settings.seed == DIRECT_EDIT_SEED
    assert result.settings.steps == DIRECT_EDIT_STEPS
    assert result.settings.cfg_scale is None
    assert result.settings.guidance == pytest.approx(4.25)
    assert result.resources == ()
    assert "DO_NOT_RECORD_API_KEY" not in repr(result)
    assert "DO_NOT_RECORD_AUTH" not in repr(result)


def test_hidream_cross_attention_prompt_fields_follow_consumed_output() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "CrossAttn_EraseReplace_HiDream",
            "inputs": {
                "clip": ["1", 1],
                "t5xxl_replace": "replacement",
                "llama_replace": "replacement",
                "t5xxl_erase": "erasure",
                "llama_erase": "erasure",
                "t5xxl_replace_token": "PRIVATE_TOKEN_FIELD",
                "llama_replace_token": "PRIVATE_TOKEN_FIELD",
                "t5xxl_erase_token": "PRIVATE_TOKEN_FIELD",
                "llama_erase_token": "PRIVATE_TOKEN_FIELD",
            },
        },
        "3": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
        "4": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["2", 1],
                "latent_image": ["3", 0],
            },
        },
        "5": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["4", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.prompts.positive.text == "replacement"
    assert result.prompts.negative.text == "erasure"
    assert "PRIVATE_TOKEN_FIELD" not in repr(result)


def test_linear_quadratic_scheduler_and_ar_video_sampler_are_extracted() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
        "3": {
            "class_type": "Linear Quadratic Advanced",
            "inputs": {
                "model": ["1", 0],
                "steps": LINEAR_QUADRATIC_STEPS,
                "denoise": 0.75,
                "inflection_percent": 0.5,
                "threshold_noise": 0.025,
            },
        },
        "4": {
            "class_type": "SamplerARVideo",
            "inputs": {"num_frame_per_block": 1},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 640, "height": 384},
        },
        "6": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "guider": ["2", 0],
                "sampler": ["4", 0],
                "sigmas": ["3", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["6", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.steps == LINEAR_QUADRATIC_STEPS
    assert result.settings.scheduler == "linear_quadratic"
    assert result.settings.sampler == "ar_video"
    assert result.settings.denoise == pytest.approx(0.75)


def test_sigma_math_blocks_unsafe_upstream_step_inference() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
        "3": {
            "class_type": "Linear Quadratic Advanced",
            "inputs": {
                "model": ["1", 0],
                "steps": LINEAR_QUADRATIC_STEPS,
                "denoise": 0.75,
            },
        },
        "4": {
            "class_type": "Sigmas Math1",
            "inputs": {"a": ["3", 0], "formula": "a[::2]"},
        },
        "5": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {"guider": ["2", 0], "sigmas": ["4", 0]},
        },
        "6": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["5", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.steps is None
    assert result.settings.denoise is None
    assert result.settings.scheduler == "custom"


def test_layer_patcher_and_auxiliary_loader_resources_are_honest() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "LayerPatcher",
            "inputs": {
                "model": ["1", 0],
                "embedder": "donors/embedder.safetensors",
                "gates": "donors/gates.safetensors",
                "last_layer": "donors/last-layer.safetensors",
            },
        },
        "3": {
            "class_type": "SAMLoader",
            "inputs": {"model_name": "sam_vit_b.pth", "device_mode": "AUTO"},
        },
        "4": {
            "class_type": "FaceDetailer",
            "inputs": {
                "image": ["2", 0],
                "model": ["2", 0],
                "sam_model_opt": ["3", 0],
            },
        },
        "5": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["4", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.primary_resource_key == "1:ckpt_name"
    assert _resource_filenames(result) == {
        "base.safetensors",
        "embedder.safetensors",
        "gates.safetensors",
        "last-layer.safetensors",
        "sam_vit_b.pth",
    }
    auxiliary = next(
        resource for resource in result.resources if resource.role is ResourceRole.AUXILIARY_MODEL
    )
    assert auxiliary.detection_rule_id == "auxiliary_model_loader"


def test_sam_loader_esam_sentinel_is_not_a_file_resource() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "SAMLoader",
            "inputs": {"model_name": "ESAM", "device_mode": "AUTO"},
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.resources == ()


@pytest.mark.parametrize("class_type", ["PulidFluxModelLoader", "PuLIDModelLoader"])
def test_pulid_model_loaders_capture_selected_local_adapter(class_type: str) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": class_type,
            "inputs": {"pulid_file": "pulid/identity.safetensors"},
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert len(result.resources) == 1
    resource = result.resources[0]
    assert resource.filename == "identity.safetensors"
    assert resource.role is ResourceRole.IPADAPTER
    assert resource.detection_rule_id == "pulid_adapter_loader"


def test_pulid_create_new_sentinel_is_not_a_file_resource() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "PuLIDModelLoader",
            "inputs": {"pulid_file": "__create_new__"},
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.resources == ()


def test_pulid_flux_fixed_eva_clip_resource_is_source_backed() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "PulidFluxEvaClipLoader",
            "inputs": {},
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert len(result.resources) == 1
    resource = result.resources[0]
    assert resource.filename == "EVA02_CLIP_L_336_psz14_s6B.pt"
    assert resource.role is ResourceRole.VISION_ENCODER
    assert resource.detection_rule_id == "pulid_flux_eva_clip_fixed"


@pytest.mark.parametrize(
    ("model_file", "expected_kind"),
    [
        ("[C] checkpoints/portrait.safetensors", ResourceKind.CHECKPOINT),
        ("[D] diffusion/flux.safetensors", ResourceKind.DIFFUSION_MODEL),
        ("[G] gguf/flux-Q5_K_M.gguf", ResourceKind.DIFFUSION_MODEL),
    ],
)
def test_ta_unified_loader_parses_source_defined_model_prefixes(
    model_file: str,
    expected_kind: ResourceKind,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "TALoadModelWithName",
            "inputs": {"model_file": model_file, "weight_dtype": "auto"},
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert len(result.resources) == 1
    resource = result.resources[0]
    assert resource.role is ResourceRole.BASE_MODEL
    assert resource.kind is expected_kind
    assert resource.selected_value == model_file[4:]
    assert resource.detection_rule_id == "ta_unified_model_loader"


def test_ta_unified_loader_rejects_unknown_prefix_without_guessing() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "TALoadModelWithName",
            "inputs": {"model_file": "[X] unknown.safetensors", "weight_dtype": "auto"},
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.resources == ()
    assert any(issue.code == "resource_selector_unrecognized" for issue in result.issues)


@pytest.mark.parametrize(
    ("load_mode", "output_index", "expected"),
    [
        (
            "Checkpoint (Standard)",
            0,
            {"portrait.safetensors", "detail.safetensors"},
        ),
        ("Checkpoint (Standard)", 2, {"portrait.safetensors"}),
        (
            "Diffusers (Component)",
            0,
            {"flux.gguf", "detail.safetensors"},
        ),
        (
            "Diffusers (Component)",
            1,
            {"encoder.gguf", "detail.safetensors"},
        ),
        ("Diffusers (Component)", 2, {"ae.safetensors"}),
    ],
)
def test_h4_integrated_loader_tracks_only_resources_for_consumed_output(
    load_mode: str,
    output_index: int,
    expected: set[str],
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "H4_UniversalLoader",
            "inputs": {
                "load_mode": load_mode,
                "ckpt_name": "checkpoints/portrait.safetensors",
                "unet_name": "diffusion/flux.gguf",
                "clip_name": "text_encoders/encoder.gguf",
                "vae_name": "vae/ae.safetensors",
                "lora_name": "loras/detail.safetensors",
                "lora_strength": 0.75,
            },
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", output_index]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == expected


def test_h4_complete_loader_image_output_does_not_claim_model_resources() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "H4_CompleteLoader",
            "inputs": {
                "load_mode": "Diffusers (Component)",
                "unet_name": "diffusion/unused.gguf",
                "clip_name": "text_encoders/unused.gguf",
                "vae_name": "vae/unused.safetensors",
                "lora_name": "loras/unused.safetensors",
                "image_1": "source.png",
            },
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 3]},
        },
    }

    result = scan_workflow(prompt)

    assert result.resources == ()


@pytest.mark.parametrize("class_type", ["sum_load_adv", "load_Nanchaku"])
def test_apt_integrated_loaders_capture_current_component_resources(
    class_type: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": class_type,
            "inputs": {
                "ckpt_name": "None",
                "unet_name": "diffusion/flux.safetensors",
                "clip1": "text_encoders/clip-l.safetensors",
                "clip2": "text_encoders/t5.safetensors",
                "clip3": "None",
                "clip4": "None",
                "vae": "vae/ae.safetensors",
                "lora": "loras/detail.safetensors",
                "lora_strength": 0.8,
            },
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    expected = {
        "flux.safetensors",
        "clip-l.safetensors",
        "t5.safetensors",
        "ae.safetensors",
        "detail.safetensors",
    }
    assert _resource_filenames(result) == expected


def test_apt_integrated_loader_respects_model_and_clip_overrides() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/upstream.safetensors"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "text_encoders/upstream.safetensors"},
        },
        "3": {
            "class_type": "sum_load_adv",
            "inputs": {
                "over_model": ["1", 0],
                "over_clip": ["2", 0],
                "ckpt_name": "checkpoints/ignored.safetensors",
                "unet_name": "None",
                "clip1": "text_encoders/ignored.safetensors",
                "vae": "vae/active.safetensors",
                "lora": "None",
            },
        },
        "4": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["3", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {
        "upstream.safetensors",
        "active.safetensors",
    }
    assert all(resource.selected_value.find("ignored") < 0 for resource in result.resources)


@pytest.mark.parametrize(
    ("download", "download_url", "expected"),
    [
        (False, "", "local.safetensors"),
        (True, "", "local.safetensors"),
        (True, "https://models.example.invalid/file", "downloaded.safetensors"),
    ],
)
def test_sdvn_checkpoint_loader_records_effective_filename_without_url(
    download: bool,
    download_url: str,
    expected: str,
) -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "SDVN Load Checkpoint",
            "inputs": {
                "Download": download,
                "Download_url": download_url,
                "Ckpt_url_name": f"downloads/{expected}",
                "Ckpt_name": "checkpoints/local.safetensors",
            },
        },
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {expected}
    assert "models.example.invalid" not in repr(result)


def test_sage_sampler_info_and_nested_prompt_bundle_are_extracted() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "Sage_CombineCLIPTextEncode",
            "inputs": {
                "clip": ["1", 1],
                "texts": {
                    "__value__": {
                        "text_2": "second prompt segment",
                        "text_1": "first prompt segment",
                    }
                },
            },
        },
        "3": {
            "class_type": "Sage_ZeroConditioning",
            "inputs": {"clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 640, "height": 896, "batch_size": 1},
        },
        "5": {
            "class_type": "Sage_SamplerInfoNoCFG",
            "inputs": {
                "seed": SAGE_SAMPLER_SEED,
                "steps": SAGE_SAMPLER_STEPS,
                "sampler_name": "dpmpp_2m",
                "scheduler": "beta",
            },
        },
        "6": {
            "class_type": "Sage_KSampler",
            "inputs": {
                "model": ["1", 0],
                "sampler_info": ["5", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "denoise": 0.85,
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

    assert result.settings.seed == SAGE_SAMPLER_SEED
    assert result.settings.steps == SAGE_SAMPLER_STEPS
    assert result.settings.sampler == "dpmpp_2m"
    assert result.settings.scheduler == "beta"
    assert result.settings.cfg_scale == pytest.approx(1.0)
    assert result.settings.denoise == pytest.approx(0.85)
    assert (result.settings.width, result.settings.height) == (640, 896)
    assert result.prompts.positive.text == "first prompt segment\nsecond prompt segment"
    assert result.prompts.negative.branch_present
    assert result.prompts.negative.text is None
    assert "negative_prompt_missing" not in _issue_codes(result)


def test_sage_multi_model_picker_routes_only_selected_nested_model() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/unused.safetensors"},
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/selected.safetensors"},
        },
        "3": {
            "class_type": "Sage_MultiModelPicker",
            "inputs": {
                "index": 1,
                "model_template": {
                    "__value__": {
                        "model_0": ["1", 0],
                        "model_1": ["2", 0],
                    }
                },
            },
        },
        "4": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["3", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {"selected.safetensors"}
    assert "1" not in result.active_node_ids
    assert "2" in result.active_node_ids


def test_sage_flexible_selector_and_lora_stack_preserve_source_semantics() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "Sage_MultiSelectorFlexibleClip",
            "inputs": {
                "unet_name": "diffusion_models/model.gguf",
                "vae_name": "vae/ae.safetensors",
                "num_of_clips": {
                    "__value__": {
                        "clip_name_2": "text_encoders/t5.safetensors",
                        "clip_name_1": "text_encoders/clip-l.safetensors",
                        "clip_type": "flux",
                    }
                },
            },
        },
        "2": {
            "class_type": "Sage_TripleLoraStack",
            "inputs": {
                "enabled_1": True,
                "lora_1_name": "loras/zero.safetensors",
                "model_1_weight": 0.0,
                "clip_1_weight": 0.0,
                "enabled_2": False,
                "lora_2_name": "loras/disabled.safetensors",
                "model_2_weight": 1.0,
                "clip_2_weight": 1.0,
                "enabled_3": True,
                "lora_3_name": "loras/active.safetensors",
                "model_3_weight": 0.7,
                "clip_3_weight": 0.4,
                "lora_stack": ["1", 0],
            },
        },
        "3": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["2", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert _resource_filenames(result) == {
        "model.gguf",
        "ae.safetensors",
        "t5.safetensors",
        "clip-l.safetensors",
        "zero.safetensors",
        "active.safetensors",
    }
    loras = {
        resource.filename: resource.strengths
        for resource in result.resources
        if resource.role is ResourceRole.LORA
    }
    assert (loras["zero.safetensors"].model, loras["zero.safetensors"].clip) == (0.0, 0.0)
    assert (loras["active.safetensors"].model, loras["active.safetensors"].clip) == (
        0.7,
        0.4,
    )


@pytest.mark.parametrize(
    ("class_type", "inputs", "expected"),
    [
        (
            "chx_IPA_adv",
            {
                "ipadapter_file": "ipadapter/faceid.safetensors",
                "clip_vision": "clip_vision/vit-h.safetensors",
            },
            {
                ("faceid.safetensors", ResourceRole.IPADAPTER),
                ("vit-h.safetensors", ResourceRole.VISION_ENCODER),
            },
        ),
        (
            "SDVN Apply Style Model",
            {
                "style_model": "style_models/style.safetensors",
                "clip_vision_model": "clip_vision/vit-g.safetensors",
            },
            {
                ("style.safetensors", ResourceRole.STYLE_MODEL),
                ("vit-g.safetensors", ResourceRole.VISION_ENCODER),
            },
        ),
        (
            "ADE_LoadAnimateDiffModel",
            {"model_name": "animatediff_models/motion.ckpt"},
            {("motion.ckpt", ResourceRole.MOTION_MODULE)},
        ),
    ],
)
def test_current_adapter_and_motion_resources_are_typed_from_source(
    class_type: str,
    inputs: dict[str, object],
    expected: set[tuple[str, ResourceRole]],
) -> None:
    prompt: Prompt = {
        "1": {"class_type": class_type, "inputs": inputs},
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert {(item.filename, item.role) for item in result.resources} == expected


def test_sage_single_clip_text_image_encode_supplies_prompt_text() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "Sage_SingleCLIPTextImageEncode",
            "inputs": {
                "clip": ["1", 1],
                "clean": True,
                "text": "a source-backed Sage prompt",
            },
        },
        "3": {
            "class_type": "ConditioningZeroOut",
            "inputs": {"conditioning": ["2", 0]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 768, "height": 1024, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": 11,
                "steps": 20,
                "cfg": 4.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
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

    assert result.prompts.positive.text == "a source-backed Sage prompt"
    assert "unknown_active_node_class" not in _issue_codes(result)


def test_jake_sampler_loader_outputs_supply_sampler_and_scheduler() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "Sampler Loader JK",
            "inputs": {"sampler": "dpmpp_3m_sde", "scheduler": "karras"},
        },
        "3": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 768, "batch_size": 1},
        },
        "4": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "latent_image": ["3", 0],
                "seed": 22,
                "steps": 18,
                "cfg": 5.0,
                "sampler_name": ["2", 0],
                "scheduler": ["2", 2],
                "denoise": 1.0,
            },
        },
        "5": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["4", 0], "vae": ["1", 2]},
        },
        "6": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["5", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.sampler == "dpmpp_3m_sde"
    assert result.settings.scheduler == "karras"
    assert "unknown_active_node_class" not in _issue_codes(result)


def test_jake_wan_wrapper_default_supplies_scheduler() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "Wan Wrapper Sampler Default JK",
            "inputs": {"scheduler": "unipc"},
        },
        "3": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "4": {
            "class_type": "WanVideoSampler",
            "inputs": {
                "model": ["1", 0],
                "latent_image": ["3", 0],
                "seed": 33,
                "steps": 12,
                "cfg": 3.0,
                "sampler_name": "euler",
                "scheduler": ["2", 0],
            },
        },
        "5": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["4", 0], "vae": ["1", 2]},
        },
        "6": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["5", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.settings.scheduler == "unipc"
    assert "unknown_active_node_class" not in _issue_codes(result)


def test_eclipse_context_outputs_supply_safe_prompt_and_generation_scalars() -> None:
    private_path = "C:/Users/private/models/do-not-emit.safetensors"
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "IO Load Image [Eclipse]",
            "inputs": {
                "width": 832,
                "height": 1216,
                "text_pos": "Eclipse context prompt",
                "text_neg": "Eclipse negative prompt",
                "steps": ECLIPSE_CONTEXT_STEPS,
                "cfg": 4.5,
                "sampler_name": "dpmpp_2m",
                "scheduler": "beta",
                "seed": ECLIPSE_CONTEXT_SEED,
                "base_path": "C:/Users/private",
                "filepath": private_path,
            },
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": ["2", 5]},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": ["2", 6]},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": ["2", 3],
                "height": ["2", 4],
                "batch_size": 1,
            },
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
                "seed": ["2", 11],
                "steps": ["2", 7],
                "cfg": ["2", 8],
                "sampler_name": ["2", 9],
                "scheduler": ["2", 10],
                "denoise": 1.0,
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

    assert result.prompts.positive.text == "Eclipse context prompt"
    assert result.prompts.negative.text == "Eclipse negative prompt"
    assert result.settings.seed == ECLIPSE_CONTEXT_SEED
    assert result.settings.steps == ECLIPSE_CONTEXT_STEPS
    assert result.settings.cfg_scale == pytest.approx(4.5)
    assert result.settings.sampler == "dpmpp_2m"
    assert result.settings.scheduler == "beta"
    assert (result.settings.width, result.settings.height) == (832, 1216)
    assert private_path not in repr(result)
    assert "unknown_active_node_class" not in _issue_codes(result)


def test_jake_multi_embedding_picker_records_only_runtime_enabled_entries() -> None:
    prompt: Prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/base.safetensors"},
        },
        "2": {
            "class_type": "Embedding Picker Multi JK",
            "inputs": {
                "text_in": "portrait",
                "embedding_1": True,
                "embedding_name_1": "embeddings/active.pt",
                "emphasis_1": 0.75,
                "append_1": True,
                "embedding_2": False,
                "embedding_name_2": "embeddings/disabled.pt",
                "emphasis_2": 1.0,
                "append_2": True,
                "embedding_3": True,
                "embedding_name_3": "embeddings/too-low.pt",
                "emphasis_3": 0.04,
                "append_3": True,
                "embedding_4": True,
                "embedding_name_4": "None",
                "emphasis_4": 1.0,
                "append_4": True,
            },
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": ["2", 0]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["3", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": 55,
                "steps": 15,
                "cfg": 3.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
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

    embeddings = tuple(
        resource for resource in result.resources if resource.role is ResourceRole.EMBEDDING
    )
    assert len(embeddings) == 1
    assert embeddings[0].filename == "active.pt"
    assert embeddings[0].strengths.weight == pytest.approx(0.75)
    assert embeddings[0].detection_rule_id == "jake_embedding_picker_multi"
    assert "unknown_active_node_class" not in _issue_codes(result)


def test_diffusers_igmv_direct_generator_extracts_its_documented_fields() -> None:
    prompt: Prompt = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "position.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "normal.png"}},
        "3": {
            "class_type": "DiffusersIGMVSampler",
            "inputs": {
                "pipeline": ["1", 0],
                "position_map": ["1", 0],
                "normal_map": ["2", 0],
                "prompt": "a generated multiview texture",
                "negative_prompt": "artifacts",
                "width": 768,
                "height": 640,
                "steps": IGMV_STEPS,
                "cfg": 3.5,
                "reference_conditioning_scale": 1.0,
                "seed": IGMV_SEED,
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
    assert result.prompts.positive.text == "a generated multiview texture"
    assert result.prompts.negative.text == "artifacts"
    assert result.settings.seed == IGMV_SEED
    assert result.settings.steps == IGMV_STEPS
    assert result.settings.cfg_scale == pytest.approx(3.5)
    assert (result.settings.width, result.settings.height) == (768, 640)
    assert "unknown_active_node_class" not in _issue_codes(result)


@pytest.mark.parametrize(
    ("class_type", "inputs", "expected_filename", "expected_role"),
    [
        (
            "Hy3DModelLoader",
            {"model": "diffusion_models/hunyuan3d-dit.safetensors"},
            "hunyuan3d-dit.safetensors",
            ResourceRole.BASE_MODEL,
        ),
        (
            "Hy3DVAELoader",
            {"model_name": "vae/hunyuan3d-vae.safetensors"},
            "hunyuan3d-vae.safetensors",
            ResourceRole.VAE,
        ),
    ],
)
def test_hunyuan3d_loaders_emit_source_backed_resources(
    class_type: str,
    inputs: dict[str, object],
    expected_filename: str,
    expected_role: ResourceRole,
) -> None:
    prompt: Prompt = {
        "1": {"class_type": class_type, "inputs": inputs},
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert {(item.filename, item.role) for item in result.resources} == {
        (expected_filename, expected_role)
    }
    assert "unknown_active_node_class" not in _issue_codes(result)


@pytest.mark.parametrize(
    "class_type",
    [
        "BNK_GetSigma",
        "GroundingDinoModelLoader (segment anything)",
        "LLMSampler",
        "LLavaSamplerAdvanced",
        "SAMModelLoader (segment anything)",
        "VideoMaMaSampler",
    ],
)
def test_reviewed_non_generation_helpers_do_not_emit_unknown_class_issues(
    class_type: str,
) -> None:
    prompt: Prompt = {
        "1": {"class_type": class_type, "inputs": {}},
        "2": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert "unknown_active_node_class" not in _issue_codes(result)
