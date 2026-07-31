from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

from civiscribe.domain import (
    GenerationSettings,
    HashRecord,
    PromptField,
    PromptRecord,
    ResourceStatus,
    WorkflowKind,
)
from civiscribe.projections import build_a1111
from tests.projection_support import (
    LORA_WEIGHT,
    MODEL_AUTO_V2,
    MODEL_VERSION_ID,
    VAE_AUTO_V2,
    complete_record,
    model_resource,
    vae_resource,
)


def _json_setting(parameters: str, name: str, *, terminal: bool = False) -> object:
    marker = f"{name}: "
    start = parameters.index(marker) + len(marker)
    if terminal:
        encoded = parameters[start:]
    else:
        encoded = parameters[start : parameters.index(", Civitai resources:", start)]
    return json.loads(encoded)


def test_complete_a1111_parameters_are_human_readable_and_parser_consistent() -> None:
    parameters = build_a1111(complete_record())

    assert parameters.startswith(
        "portrait of café 雪\ncinematic light\nNegative prompt: low quality, watermark\n"
    )
    assert "Steps: 20" in parameters
    assert "Sampler: DPM++ 2M" in parameters
    assert "Schedule type: Karras" in parameters
    assert "CFG scale: 7" in parameters
    assert "Seed: 123456789" in parameters
    assert "Size: 1024x768" in parameters
    assert "Batch size: 1" in parameters
    assert "Model: swiftFastAndDetailed_neo.gguf" in parameters
    assert f"Model hash: {MODEL_AUTO_V2}" in parameters
    assert "VAE: ae.safetensors" in parameters
    assert f"VAE hash: {VAE_AUTO_V2}" in parameters
    assert "Clip skip: 2" in parameters
    assert "Denoising strength:" not in parameters

    hashes = cast(dict[str, str], _json_setting(parameters, "Hashes"))
    assert hashes["model"] == MODEL_AUTO_V2
    assert hashes["vae"] == VAE_AUTO_V2
    assert hashes["model:swiftFastAndDetailed_neo.gguf"] == MODEL_AUTO_V2
    assert hashes["VAE:ae.safetensors"] == VAE_AUTO_V2

    resources = cast(
        list[dict[str, object]],
        _json_setting(parameters, "Civitai resources", terminal=True),
    )
    assert resources[0]["air"] == resources[0]["urn"]
    assert resources[0]["modelVersionId"] == MODEL_VERSION_ID
    assert resources[1]["weight"] == LORA_WEIGHT


def test_flux_guidance_is_not_relabelled_as_cfg() -> None:
    record = complete_record()
    record = replace(
        record,
        prompts=replace(
            record.prompts,
            negative=PromptField(branch_present=True),
        ),
        settings=replace(
            record.settings,
            cfg_scale=None,
            guidance=4.0,
            sampler="custom_sampler",
            scheduler="custom_schedule",
        ),
    )

    parameters = build_a1111(record)

    assert "\nNegative prompt:\n" in parameters
    assert "Guidance: 4" in parameters
    assert "CFG scale:" not in parameters
    assert "Sampler: custom_sampler" in parameters
    assert "Schedule type: custom_schedule" in parameters


def test_img2img_emits_denoise_while_unknown_optional_fields_remain_absent() -> None:
    record = complete_record()
    record = replace(
        record,
        workflow_kind=WorkflowKind.IMG2IMG,
        prompts=PromptRecord(),
        settings=GenerationSettings(denoise=0.625),
        resources=(),
        primary_resource_key=None,
        selected_vae_resource_key=None,
    )

    parameters = build_a1111(record)

    assert parameters.startswith("\nNegative prompt:\n")
    assert "Size: 1024x768" in parameters
    assert "Denoising strength: 0.625" in parameters
    assert "Steps:" not in parameters
    assert "Model:" not in parameters
    assert "Hashes:" not in parameters
    assert "Civitai resources:" not in parameters


def test_cfg_takes_precedence_when_cfg_and_guidance_are_both_known() -> None:
    record = complete_record()
    record = replace(
        record,
        settings=replace(record.settings, cfg_scale=5.5, guidance=3.0),
    )

    parameters = build_a1111(record)

    assert "CFG scale: 5.5" in parameters
    assert "Guidance:" not in parameters


def test_model_and_vae_fields_are_omitted_when_selected_keys_are_invalid() -> None:
    record = replace(
        complete_record(),
        primary_resource_key="missing-model",
        selected_vae_resource_key="missing-vae",
    )

    parameters = build_a1111(record)

    assert "Model:" not in parameters
    assert "Model hash:" not in parameters
    assert ", VAE: " not in parameters
    assert "VAE hash:" not in parameters


def test_selected_model_without_hash_never_emits_misleading_model_hash() -> None:
    model = replace(
        model_resource(),
        hashes=HashRecord(),
        status=ResourceStatus.UNRESOLVED,
        identity=None,
    )
    vae = vae_resource()
    record = replace(
        complete_record(),
        resources=(model, vae),
        primary_resource_key=model.key,
        selected_vae_resource_key=vae.key,
    )

    parameters = build_a1111(record)

    assert "Model: swiftFastAndDetailed_neo.gguf" in parameters
    assert "Model hash:" not in parameters


def test_boolean_runtime_number_is_not_serialized_as_integer() -> None:
    record = complete_record()
    unsafe_settings = replace(
        record.settings,
        seed=cast(int, True),
        steps=cast(int, False),
    )

    parameters = build_a1111(replace(record, settings=unsafe_settings))

    assert "Seed:" not in parameters
    assert "Steps:" not in parameters
