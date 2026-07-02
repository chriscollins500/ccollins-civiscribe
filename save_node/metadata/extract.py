"""Conservative extraction from ComfyUI API prompt metadata."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from .schema import GenerationSettings, PromptMetadata


def extract_prompt_metadata(prompt: Any) -> PromptMetadata:
    nodes = _as_node_mapping(prompt)
    if not nodes:
        return PromptMetadata()

    sampler = _first_sampler_node(nodes)
    if sampler is not None:
        inputs = sampler.get("inputs", {})
        positive = _resolve_text_input(nodes, inputs.get("positive"))
        negative = _resolve_text_input(nodes, inputs.get("negative"))
        if positive or negative:
            return PromptMetadata(positive=positive, negative=negative)

    text_nodes = [
        _string_or_none(node.get("inputs", {}).get("text"))
        for node in nodes.values()
        if "text" in node.get("inputs", {})
    ]
    text_nodes = [text for text in text_nodes if text]
    if text_nodes:
        return PromptMetadata(positive=text_nodes[0])

    return PromptMetadata()


def extract_generation_settings(prompt: Any) -> GenerationSettings:
    nodes = _as_node_mapping(prompt)
    if not nodes:
        return GenerationSettings()

    sampler = _first_sampler_node(nodes)
    sampler_inputs = sampler.get("inputs", {}) if sampler else {}
    latent_inputs = _first_node_inputs(nodes, "EmptyLatentImage")
    checkpoint_inputs = _first_node_inputs(nodes, "CheckpointLoader")
    vae_inputs = _first_node_inputs(nodes, "VAELoader")

    return GenerationSettings(
        steps=_int_or_none(sampler_inputs.get("steps")),
        sampler=_string_or_none(sampler_inputs.get("sampler_name")),
        scheduler=_string_or_none(sampler_inputs.get("scheduler")),
        cfg_scale=_float_or_none(sampler_inputs.get("cfg")),
        seed=_int_or_none(sampler_inputs.get("seed")),
        width=_int_or_none(latent_inputs.get("width")),
        height=_int_or_none(latent_inputs.get("height")),
        model=_basename_or_none(_string_or_none(checkpoint_inputs.get("ckpt_name"))),
        vae=_basename_or_none(_string_or_none(vae_inputs.get("vae_name"))),
        denoising_strength=_float_or_none(sampler_inputs.get("denoise")),
    )


def _as_node_mapping(prompt: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(prompt, dict):
        return {}

    nodes: dict[str, dict[str, Any]] = {}
    for key, value in prompt.items():
        if isinstance(value, dict) and isinstance(value.get("inputs", {}), dict):
            nodes[str(key)] = value
    return nodes


def _first_sampler_node(nodes: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for node in nodes.values():
        class_type = str(node.get("class_type", "")).lower()
        if "ksampler" in class_type or "sampler" in class_type:
            return node
    return None


def _first_node_inputs(nodes: dict[str, dict[str, Any]], class_type_part: str) -> dict[str, Any]:
    needle = class_type_part.lower()
    for node in nodes.values():
        if needle in str(node.get("class_type", "")).lower():
            inputs = node.get("inputs", {})
            if isinstance(inputs, dict):
                return inputs
    return {}


def _resolve_text_input(nodes: dict[str, dict[str, Any]], reference: Any) -> str | None:
    if isinstance(reference, str):
        return reference
    if not isinstance(reference, list) or not reference:
        return None
    node = nodes.get(str(reference[0]))
    if not node:
        return None
    return _string_or_none(node.get("inputs", {}).get("text"))


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _basename_or_none(value: str | None) -> str | None:
    if not value:
        return None
    windows_name = PureWindowsPath(value).name
    posix_name = PurePosixPath(windows_name).name
    return posix_name or windows_name or None


__all__ = ["extract_generation_settings", "extract_prompt_metadata"]
