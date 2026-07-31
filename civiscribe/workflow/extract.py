"""Prompt and generation-setting extraction from selected active lineage."""

from __future__ import annotations

import math
import re
from collections import deque
from collections.abc import Mapping
from typing import cast

from ..domain import GenerationSettings, PromptField, PromptRecord, ScanIssue
from .active import ActiveGraph
from .classify import (
    compact_class,
    is_antrobots_refiner_node,
    is_antrobots_refiner_pipe_node,
    is_direct_image_generator_node,
    is_generated_latent_node,
    is_image_latent_node,
    is_text_encode_node,
)
from .graph import GraphIndex, as_link_reference
from .lineage import StageSelection, upstream_node_distances
from .model import FrozenValue, PromptNode, node_sort_key
from .routing import routed_upstream_edges
from .scalar import (
    resolve_node_input,
    resolve_node_output,
    resolve_scalar,
    scalar_float,
    scalar_int,
    scalar_string,
)

_SCHEDULER_NODE_NAMES = {
    "alignyourstepsscheduler": "align_your_steps",
    "betasamplingscheduler": "beta",
    "constantscheduler": "constant",
    "customsigmas": "custom_sigmas",
    "exponentialscheduler": "exponential",
    "extendintermediatesigmas": "extended_intermediate",
    "flux2scheduler": "flux2",
    "gitsscheduler": "gits",
    "ideogram4scheduler": "ideogram4",
    "karrasscheduler": "karras",
    "laplacescheduler": "laplace",
    "linearquadraticadvanced": "linear_quadratic",
    "ltxvscheduler": "ltxv",
    "manualsigmas": "manual_sigmas",
    "floattosigmas": "custom",
    "optimalstepsscheduler": "optimal_steps",
    "polyexponentialscheduler": "polyexponential",
    "sigmasconwaysequence": "res4lyf_conway_sequence",
    "sigmasgilbreathsequence": "res4lyf_gilbreath_sequence",
    "sigmasharmonicdecay": "res4lyf_harmonic_decay",
    "sigmaslangevindynamics": "res4lyf_langevin_dynamics",
    "sigmasmath1": "custom",
    "sigmasmath3": "custom",
    "sigmasnormalizingflows": "res4lyf_normalizing_flows",
    "sigmaspersistenthomology": "res4lyf_persistent_homology",
    "sigmasriemannianflow": "res4lyf_riemannian_flow",
    "sigmasstepwisemultirate": "res4lyf_stepwise_multirate",
    "sigmasfromtext": "custom",
    "sdturboscheduler": "sd_turbo",
    "tanscheduler": "tan",
    "tanscheduler2": "tan_2",
    "tanscheduler2simple": "tan_2_simple",
    "vpscheduler": "vp",
}
_SAMPLER_NODE_NAMES = {
    "samplerdpmadaptative": "dpm_adaptive",
    "samplerdpmpp2msde": "dpmpp_2m_sde",
    "samplerdpmpp2sancestral": "dpmpp_2s_ancestral",
    "samplerdpmpp3msde": "dpmpp_3m_sde",
    "samplerdpmppsde": "dpmpp_sde",
    "samplerersde": "er_sde",
    "samplerarvideo": "ar_video",
    "samplereulerancestral": "euler_ancestral",
    "samplereulerancestralcfgpp": "euler_ancestral_cfg_pp",
    "samplereulercfgpp": "euler_cfg_pp",
    "samplerlcm": "lcm",
    "samplerlms": "lms",
    "samplersasolver": "sa_solver",
    "samplerseeds2": "seeds_2",
    "voidsampler": "void_ddim",
}
_DEVICE_SPECIFIC_SAMPLERS = frozenset(
    {
        "samplerdpmpp2msde",
        "samplerdpmpp3msde",
        "samplerdpmppsde",
    }
)
_DIMENSIONS = re.compile(r"^\s*(\d{1,6})\s*[xX\u00d7]\s*(\d{1,6})(?:\D.*)?$")
_MIN_SIGMA_VALUES = 2
_MAX_STATIC_SIGMA_VALUES = 100_000
_MAX_HOOK_DEPTH = 16
_POSITIVE_PROMPT_FIELDS = (
    "positive_prompt",
    "positive",
    "pos",
    "optional_positive",
    "current_prompt",
    "next_prompt",
    "populated_text",
    "wildcard_text",
    "user_prompt",
    "text",
    "prompt",
    "prompt_g",
    "prompt_l",
    "pos_g",
    "pos_l",
    "positive_g",
    "positive_l",
    "text_g",
    "text_l",
    "clip_g",
    "clip_l",
    "t5xxl",
    "llama",
    "bert",
    "mt5xl",
    "qwen25_7b",
)
_NEGATIVE_PROMPT_FIELDS = (
    "negative_prompt",
    "negative",
    "neg",
    "optional_negative",
    "current_prompt",
    "next_prompt",
    "neg_g",
    "neg_l",
    "negative_g",
    "negative_l",
    "prompt_g",
    "prompt_l",
    "text",
    "prompt",
)
_PROMPT_CHANNEL_CLASSES = frozenset(
    {
        "adepromptscheduling",
        "adepromptschedulinglatents",
        "crsdxlbasepromptencoder",
        "seargesdxlbasepromptencoder",
        "seargesdxlpromptencoder",
        "seargesdxlrefinerpromptencoder",
        "sdxlpowerpromptpositivergthree",
        "sdxlpowerpromptsimplenegativergthree",
        "sagecombinecliptextencode",
    }
)
_MULTI_CHANNEL_PROMPT_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "sagedualcliptextencode": {
        "positive": ("pos",),
        "negative": ("neg",),
    },
    "sagedualcliptextencodelumina2": {
        "positive": ("pos",),
        "negative": ("neg",),
    },
    "sagedualcliptextencodeqwen": {
        "positive": ("pos",),
        "negative": ("neg",),
    },
    "crsdxlbasepromptencoder": {
        "positive": ("pos_g", "pos_l"),
        "negative": ("neg_g", "neg_l"),
    },
    "seargesdxlbasepromptencoder": {
        "positive": ("pos_g", "pos_l"),
        "negative": ("neg_g", "neg_l"),
    },
    "seargesdxlrefinerpromptencoder": {
        "positive": ("pos_r",),
        "negative": ("neg_r",),
    },
}
_SEARGE_PROMPT_OUTPUT_FIELDS: dict[int, tuple[str, ...]] = {
    0: ("pos_g", "pos_l"),
    1: ("neg_g", "neg_l"),
    2: ("pos_r",),
    3: ("neg_r",),
}


def _linked_node(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode | None,
    input_name: str,
) -> PromptNode | None:
    if node is None:
        return None
    reference = as_link_reference(node.input_value(input_name))
    if reference is None or not active.contains(reference.source_node_id):
        return None
    return index.node(reference.source_node_id)


def _stage_node(index: GraphIndex, stage: StageSelection) -> PromptNode | None:
    return index.node(stage.selected_node_id) if stage.selected_node_id is not None else None


def _branch_nodes(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode | None,
    input_names: tuple[str, ...],
) -> tuple[tuple[int, PromptNode], ...]:
    if node is None:
        return ()
    distances = upstream_node_distances(
        index,
        active,
        consumer_node_id=node.node_id,
        input_names=input_names,
    )
    return tuple(
        (distances[node_id], candidate)
        for node_id in sorted(
            distances,
            key=lambda value: (distances[value], node_sort_key(value)),
        )
        if (candidate := index.node(node_id)) is not None
    )


def _nearest_branch_int(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode | None,
    branch_inputs: tuple[str, ...],
    value_inputs: tuple[str, ...],
) -> int | None:
    found: list[tuple[int, int]] = []
    for distance, candidate in _branch_nodes(index, active, node, branch_inputs):
        value = scalar_int(resolve_node_input(index, active, candidate, value_inputs))
        if value is not None:
            found.append((distance, value))
    if not found:
        return None
    nearest = min(distance for distance, _value in found)
    values = {value for distance, value in found if distance == nearest}
    return next(iter(values)) if len(values) == 1 else None


def _nearest_branch_float(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode | None,
    branch_inputs: tuple[str, ...],
    value_inputs: tuple[str, ...],
) -> float | None:
    found: list[tuple[int, float]] = []
    for distance, candidate in _branch_nodes(index, active, node, branch_inputs):
        value = scalar_float(resolve_node_input(index, active, candidate, value_inputs))
        if value is not None:
            found.append((distance, value))
    if not found:
        return None
    nearest = min(distance for distance, _value in found)
    values = {value for distance, value in found if distance == nearest}
    return next(iter(values)) if len(values) == 1 else None


def _nearest_scheduler(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
) -> str | None:
    found: list[tuple[int, str]] = []
    for distance, candidate in _branch_nodes(
        index,
        active,
        sampler,
        (
            "base_sampler",
            "pipe",
            "sampler_inputs",
            "scheduler",
            "sigmas",
            "sampler_pipe",
            "sampler_info",
        ),
    ):
        value = scalar_string(
            resolve_node_input(
                index,
                active,
                candidate,
                ("scheduler", "scheduler_name"),
            )
        )
        if value is None:
            value = _SCHEDULER_NODE_NAMES.get(compact_class(candidate))
        if (
            value is None
            and "sigma" in compact_class(candidate)
            and any("sigma" in input_name.casefold() for input_name in candidate.inputs)
        ):
            value = "custom"
        if value is not None:
            found.append((distance, value))
    if not found:
        return None
    nearest = min(distance for distance, _value in found)
    values = {value for distance, value in found if distance == nearest}
    return next(iter(values)) if len(values) == 1 else None


def _provider_sampler_name(
    index: GraphIndex,
    active: ActiveGraph,
    candidate: PromptNode,
) -> str | None:
    compact = compact_class(candidate)
    value = _SAMPLER_NODE_NAMES.get(compact)
    if value is None or compact not in _DEVICE_SPECIFIC_SAMPLERS:
        return value
    noise_device = scalar_string(resolve_node_input(index, active, candidate, ("noise_device",)))
    if noise_device is not None and noise_device.casefold() == "gpu":
        return f"{value}_gpu"
    return value


def _nearest_sampler(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
) -> str | None:
    found: list[tuple[int, str]] = []
    for distance, candidate in _branch_nodes(
        index,
        active,
        sampler,
        (
            "base_sampler",
            "pipe",
            "sampler",
            "sampler_inputs",
            "sampler_pipe",
            "sampler_info",
        ),
    ):
        value = scalar_string(
            resolve_node_input(index, active, candidate, ("sampler_name", "sampler"))
        )
        if value is None:
            value = _provider_sampler_name(index, active, candidate)
        if value is not None:
            found.append((distance, value))
    if not found:
        return None
    nearest = min(distance for distance, _value in found)
    values = {value for distance, value in found if distance == nearest}
    return next(iter(values)) if len(values) == 1 else None


def _sage_no_cfg_sampler_info(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
) -> bool:
    return any(
        compact_class(candidate) == "sagesamplerinfonocfg"
        for _distance, candidate in _branch_nodes(
            index,
            active,
            sampler,
            (
                "base_sampler",
                "guider",
                "pipe",
                "sampler_inputs",
                "sampler_pipe",
                "sampler_info",
            ),
        )
    )


def _resolve_cfg(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
) -> float | None:
    cfg = scalar_float(
        resolve_node_input(
            index,
            active,
            sampler,
            ("cfg", "cfg_scale", "cfg_guidance"),
        )
    )
    if cfg is not None:
        return cfg
    cfg = _nearest_branch_float(
        index,
        active,
        sampler,
        (
            "base_sampler",
            "guider",
            "pipe",
            "sampler_inputs",
            "sampler_pipe",
            "sampler_info",
        ),
        ("cfg", "cfg_scale"),
    )
    return 1.0 if cfg is None and _sage_no_cfg_sampler_info(index, active, sampler) else cfg


def _sigma_text_steps(value: str | None) -> int | None:
    if value is None:
        return None
    tokens = value.replace(",", " ").split()
    if not _MIN_SIGMA_VALUES <= len(tokens) <= _MAX_STATIC_SIGMA_VALUES:
        return None
    try:
        values = tuple(float(token) for token in tokens)
    except ValueError:
        return None
    return len(values) - 1 if all(math.isfinite(item) for item in values) else None


def _literal_sigma_steps(value: FrozenValue) -> int | None:
    if not isinstance(value, tuple) or as_link_reference(value) is not None:
        return None
    if not _MIN_SIGMA_VALUES <= len(value) <= _MAX_STATIC_SIGMA_VALUES:
        return None
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        number = float(item)
        if not math.isfinite(number):
            return None
        numbers.append(number)
    return len(numbers) - 1


def _nearest_sigma_steps(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
) -> int | None:
    found: list[tuple[int, int]] = []
    for distance, candidate in _branch_nodes(
        index,
        active,
        sampler,
        ("base_sampler", "pipe", "sampler_inputs", "sigmas"),
    ):
        compact = compact_class(candidate)
        value: int | None = None
        if compact == "customsigmas":
            value = scalar_int(
                resolve_node_input(index, active, candidate, ("interpolate_to_steps",))
            )
        elif compact == "manualsigmas":
            value = _sigma_text_steps(
                scalar_string(resolve_node_input(index, active, candidate, ("sigmas",)))
            )
        elif compact == "sigmasfromtext":
            value = _sigma_text_steps(
                scalar_string(resolve_node_input(index, active, candidate, ("text",)))
            )
        elif compact == "floattosigmas":
            value = _literal_sigma_steps(candidate.input_value("float_list"))
        if value is not None and value >= 0:
            found.append((distance, value))
    if not found:
        return None
    nearest = min(distance for distance, _value in found)
    values = {value for distance, value in found if distance == nearest}
    return next(iter(values)) if len(values) == 1 else None


def _has_opaque_sigma_transform(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
) -> bool:
    return any(
        compact_class(candidate) in {"sigmasmath1", "sigmasmath3"}
        for _distance, candidate in _branch_nodes(
            index,
            active,
            sampler,
            ("base_sampler", "pipe", "sampler_inputs", "sigmas"),
        )
    )


def _dimensions_from_node(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode | None,
) -> tuple[int | None, int | None]:
    output_width = scalar_int(resolve_node_output(index, active, node, 0))
    output_height = scalar_int(resolve_node_output(index, active, node, 1))
    if output_width is not None and output_height is not None:
        return output_width, output_height
    width = scalar_int(
        resolve_node_input(
            index,
            active,
            node,
            (
                "width",
                "custom_width",
                "empty_latent_width",
                "width_override",
                "dimension_width",
                "output_width",
            ),
        )
    )
    height = scalar_int(
        resolve_node_input(
            index,
            active,
            node,
            (
                "height",
                "custom_height",
                "empty_latent_height",
                "height_override",
                "dimension_height",
                "output_height",
            ),
        )
    )
    if width is not None and height is not None:
        return width, height
    packed = scalar_string(
        resolve_node_input(
            index,
            active,
            node,
            ("dimensions", "resolution", "size", "size_preset"),
        )
    )
    match = _DIMENSIONS.match(packed) if packed is not None else None
    if match is None:
        return width, height
    return width or int(match.group(1)), height or int(match.group(2))


def _latent_source(
    index: GraphIndex,
    active: ActiveGraph,
    stage: StageSelection,
) -> tuple[PromptNode | None, tuple[ScanIssue, ...]]:
    if stage.selected_node_id is None:
        return None, ()
    distances = upstream_node_distances(
        index,
        active,
        consumer_node_id=stage.selected_node_id,
        input_names=(
            "image_embeds",
            "latent_image",
            "latent",
            "pipe",
            "sampler_inputs",
            "samples",
        ),
    )
    candidates = tuple(
        node_id
        for node_id in sorted(distances, key=node_sort_key)
        if (node := index.node(node_id)) is not None
        and (
            is_generated_latent_node(node)
            or is_image_latent_node(node)
            or (
                "latent" in compact_class(node)
                and ("source" in compact_class(node) or "image" in compact_class(node))
            )
        )
    )
    if not candidates:
        return None, ()
    nearest_distance = min(distances[node_id] for node_id in candidates)
    nearest = tuple(node_id for node_id in candidates if distances[node_id] == nearest_distance)
    if len(nearest) != 1:
        return None, (ScanIssue("latent_source_ambiguous"),)
    return index.node(nearest[0]), ()


def _find_guidance(
    index: GraphIndex,
    active: ActiveGraph,
    stage: StageSelection,
) -> float | None:
    if stage.selected_node_id is None:
        return None
    sampler = index.node(stage.selected_node_id)
    found: list[float] = []
    for _distance, node in _branch_nodes(
        index,
        active,
        sampler,
        ("positive", "conditioning", "guider"),
    ):
        compact = compact_class(node)
        if "guidance" not in compact and "cliptextencodeflux" not in compact:
            continue
        value = scalar_float(resolve_node_input(index, active, node, ("guidance",)))
        if value is not None:
            found.append(value)
    values = set(found)
    return next(iter(values)) if len(values) == 1 else None


def _custom_sampler_hook_provider(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode,
    *,
    seen: frozenset[str] = frozenset(),
    depth: int = 0,
) -> PromptNode | None:
    if depth >= _MAX_HOOK_DEPTH or node.node_id in seen:
        return None
    compact = compact_class(node)
    if compact == "customsamplerdetailerhookprovider":
        return node
    if compact != "detailerhookcombine":
        return None
    visited = seen | {node.node_id}
    for input_name in ("hook1", "hook2"):
        candidate = _linked_node(index, active, node, input_name)
        if candidate is None:
            continue
        provider = _custom_sampler_hook_provider(
            index,
            active,
            candidate,
            seen=visited,
            depth=depth + 1,
        )
        if provider is not None:
            return provider
    return None


def _detailer_hook_sampler(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
) -> tuple[str | None, bool]:
    hook = next(
        (
            candidate
            for input_name in ("detailer_hook", "detailer_hook_opt", "hook")
            if (candidate := _linked_node(index, active, sampler, input_name)) is not None
        ),
        None,
    )
    if hook is None:
        return None, False
    provider = _custom_sampler_hook_provider(index, active, hook)
    if provider is None:
        return None, False
    return _nearest_sampler(index, active, provider), True


def extract_generation_settings(
    index: GraphIndex,
    active: ActiveGraph,
    stage: StageSelection,
) -> tuple[GenerationSettings, tuple[ScanIssue, ...]]:
    """Extract settings from a KSampler or custom sampler helper chain."""

    sampler = _stage_node(index, stage)
    if sampler is None:
        return GenerationSettings(), ()
    latent, issues = _latent_source(index, active, stage)

    seed = scalar_int(resolve_node_input(index, active, sampler, ("seed", "noise_seed")))
    if seed is None:
        seed = _nearest_branch_int(
            index,
            active,
            sampler,
            ("base_sampler", "noise", "pipe", "sampler_inputs", "sampler_info"),
            ("noise_seed", "seed"),
        )
    steps = scalar_int(
        resolve_node_input(
            index,
            active,
            sampler,
            ("steps", "steps_to_run", "num_steps", "total_steps"),
        )
    )
    opaque_sigma_transform = _has_opaque_sigma_transform(index, active, sampler)
    if steps is None and not opaque_sigma_transform:
        steps = _nearest_branch_int(
            index,
            active,
            sampler,
            (
                "base_sampler",
                "pipe",
                "sampler_inputs",
                "sampler_info",
                "scheduler",
                "sigmas",
            ),
            ("steps", "total_steps"),
        )
    if steps is None and not opaque_sigma_transform:
        steps = _nearest_sigma_steps(index, active, sampler)
    hook_sampler, hook_override = _detailer_hook_sampler(index, active, sampler)
    sampler_name = hook_sampler
    if not hook_override:
        sampler_name = scalar_string(resolve_node_input(index, active, sampler, ("sampler_name",)))
        if sampler_name is None:
            sampler_name = _nearest_sampler(index, active, sampler)
    hook_issues = (
        (ScanIssue("detailer_sampler_override_unresolved", node_id=sampler.node_id),)
        if hook_override and sampler_name is None
        else ()
    )
    scheduler = scalar_string(resolve_node_input(index, active, sampler, ("scheduler",)))
    if scheduler is None:
        scheduler = _nearest_scheduler(index, active, sampler)
    cfg = _resolve_cfg(index, active, sampler)
    guidance_inputs = (
        ("guidance", "guidance_scale")
        if is_direct_image_generator_node(sampler)
        else (
            ("guidance_scale",)
            if compact_class(sampler) == "fluxkohyainferencesampler"
            else ("guidance",)
        )
    )
    guidance = scalar_float(resolve_node_input(index, active, sampler, guidance_inputs))
    if guidance is None:
        guidance = _find_guidance(index, active, stage)
    denoise, denoise_issues = _antrobots_refiner_denoise(
        index,
        active,
        sampler,
    )
    if denoise is None and not denoise_issues:
        denoise = scalar_float(
            resolve_node_input(index, active, sampler, ("denoise", "denoise_strength"))
        )
    if denoise is None and not denoise_issues and not opaque_sigma_transform:
        denoise = _nearest_branch_float(
            index,
            active,
            sampler,
            ("base_sampler", "pipe", "sampler_inputs", "scheduler", "sigmas"),
            ("denoise", "denoise_strength"),
        )
    width, height = _dimensions_from_node(index, active, latent)
    if width is None or height is None:
        sampler_width, sampler_height = _dimensions_from_node(index, active, sampler)
        width = width if width is not None else sampler_width
        height = height if height is not None else sampler_height
    batch_node = sampler if is_direct_image_generator_node(sampler) else latent
    batch_size = scalar_int(
        resolve_node_input(
            index,
            active,
            batch_node,
            (
                "batch_size",
                "batch",
                "max_images",
                "n",
                "num_images",
                "number_of_images",
                "series_amount",
            ),
        )
    )
    clip_skip, clip_skip_issues = _extract_clip_skip_details(index, active)
    return (
        GenerationSettings(
            seed=seed,
            steps=steps,
            sampler=sampler_name,
            scheduler=scheduler,
            cfg_scale=cfg,
            guidance=guidance,
            denoise=denoise,
            width=width,
            height=height,
            batch_size=batch_size,
            clip_skip=clip_skip,
        ),
        (*issues, *hook_issues, *denoise_issues, *clip_skip_issues),
    )


def _antrobots_refiner_denoise(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
) -> tuple[float | None, tuple[ScanIssue, ...]]:
    if not (is_antrobots_refiner_node(sampler) or is_antrobots_refiner_pipe_node(sampler)):
        return None, ()
    total_steps = scalar_int(resolve_node_input(index, active, sampler, ("total_steps",)))
    refine_step = scalar_int(resolve_node_input(index, active, sampler, ("refine_step",)))
    base_denoise = scalar_float(resolve_node_input(index, active, sampler, ("base_denoise",)))
    refine_denoise = scalar_float(resolve_node_input(index, active, sampler, ("refine_denoise",)))
    if total_steps is not None and refine_step is not None:
        if refine_step >= total_steps:
            return base_denoise, ()
        if refine_step == 0:
            return refine_denoise, ()
    if base_denoise == refine_denoise:
        return base_denoise, ()
    return None, (ScanIssue("denoise_ambiguous", node_id=sampler.node_id),)


def _extract_clip_skip_details(
    index: GraphIndex,
    active: ActiveGraph,
) -> tuple[int | None, tuple[ScanIssue, ...]]:
    values: set[int] = set()
    for node_id in active.node_ids:
        node = index.node(node_id)
        if node is None:
            continue
        compact = compact_class(node)
        field_names = (
            ("stop_at_clip_layer",)
            if "clipsetlastlayer" in compact
            else (("clip_skip",) if "loader" in compact or compact == "easypipeedit" else ())
        )
        if not field_names:
            continue
        value = scalar_int(
            resolve_node_input(
                index,
                active,
                node,
                field_names,
            )
        )
        if value is not None:
            values.add(abs(value))
    if len(values) == 1:
        return next(iter(values)), ()
    if len(values) > 1:
        return None, (ScanIssue("clip_skip_ambiguous"),)
    return None, ()


def _extract_clip_skip(index: GraphIndex, active: ActiveGraph) -> int | None:
    return _extract_clip_skip_details(index, active)[0]


type _PromptRoot = tuple[str | None, str | None, int | None]
type _PresentPromptRoot = tuple[str, str | None, int | None]


def _linked_prompt_root(
    active: ActiveGraph,
    node: PromptNode,
    input_name: str,
) -> _PromptRoot:
    reference = as_link_reference(node.input_value(input_name))
    if reference is None or not active.contains(reference.source_node_id):
        return None, None, None
    return reference.source_node_id, input_name, reference.output_index


def _literal_prompt_root(sampler: PromptNode, kind: str) -> _PromptRoot:
    return (
        (sampler.node_id, None, None) if _prompt_input_names(sampler, kind) else (None, None, None)
    )


def _pipe_prompt_root(
    active: ActiveGraph,
    pipe: PromptNode,
    kind: str,
) -> _PromptRoot:
    input_names = (kind, "conditioning") if kind == "positive" else (kind, "negative_conditioning")
    for input_name in input_names:
        root = _linked_prompt_root(active, pipe, input_name)
        if root[0] is not None:
            return root
    return pipe.node_id, "pipe", None


def _guider_prompt_root(
    active: ActiveGraph,
    guider: PromptNode,
    kind: str,
) -> _PromptRoot:
    input_name = (
        kind
        if kind in guider.inputs
        else ("conditioning" if kind == "positive" and "conditioning" in guider.inputs else "")
    )
    return _linked_prompt_root(active, guider, input_name) if input_name else (None, None, None)


def _sampler_pipe_prompt_root(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
    kind: str,
) -> _PromptRoot | None:
    for pipe_input_name in ("pipe", "basic_pipe", "detailer_pipe"):
        pipe = _linked_node(index, active, sampler, pipe_input_name)
        if pipe is not None:
            return _pipe_prompt_root(active, pipe, kind)
    return None


def _prompt_root(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
    kind: str,
) -> _PromptRoot:
    direct_input_names = (
        (kind, "conditioning", "text_embeds", "positive_embeds")
        if kind == "positive"
        else (kind, "negative_conditioning", "text_embeds", "negative_embeds")
    )
    direct_input_name = next(
        (name for name in direct_input_names if name in sampler.inputs),
        None,
    )
    if direct_input_name is not None:
        return _linked_prompt_root(active, sampler, direct_input_name)
    sampler_settings = _linked_node(index, active, sampler, "sampler_inputs")
    if sampler_settings is not None:
        settings_input_name = next(
            (
                name
                for name in (
                    kind,
                    "text_embeds",
                    f"{kind}_embeds",
                    "conditioning" if kind == "positive" else "negative_conditioning",
                )
                if name in sampler_settings.inputs
            ),
            None,
        )
        if settings_input_name is not None:
            return _linked_prompt_root(active, sampler_settings, settings_input_name)
    base_sampler = _linked_node(index, active, sampler, "base_sampler")
    if base_sampler is not None:
        basic_pipe = _linked_node(index, active, base_sampler, "basic_pipe")
        if basic_pipe is not None:
            return _pipe_prompt_root(active, basic_pipe, kind)
        provider_input_name = next(
            (
                name
                for name in (
                    kind,
                    "conditioning" if kind == "positive" else "negative_conditioning",
                )
                if name in base_sampler.inputs
            ),
            None,
        )
        if provider_input_name is not None:
            return _linked_prompt_root(active, base_sampler, provider_input_name)
    guider = _linked_node(index, active, sampler, "guider")
    if guider is not None:
        root = _guider_prompt_root(active, guider, kind)
        return root if root[0] is not None else _literal_prompt_root(sampler, kind)
    pipe_root = _sampler_pipe_prompt_root(index, active, sampler, kind)
    return pipe_root if pipe_root is not None else _literal_prompt_root(sampler, kind)


def _antrobots_prompt_roots(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
    kind: str,
) -> tuple[_PromptRoot, ...] | None:
    is_pipe = is_antrobots_refiner_pipe_node(sampler)
    if not is_pipe and not is_antrobots_refiner_node(sampler):
        return None
    total_steps = scalar_int(resolve_node_input(index, active, sampler, ("total_steps",)))
    refine_step = scalar_int(resolve_node_input(index, active, sampler, ("refine_step",)))
    branches: tuple[str, ...]
    if total_steps is not None and refine_step is not None:
        if refine_step >= total_steps:
            branches = ("base",)
        elif refine_step == 0:
            branches = ("refine",)
        else:
            branches = ("base", "refine")
    else:
        branches = ("base", "refine")

    roots: list[_PromptRoot] = []
    for branch in branches:
        if is_pipe:
            pipe = _linked_node(index, active, sampler, f"{branch}_pipe")
            roots.append(
                _pipe_prompt_root(active, pipe, kind) if pipe is not None else (None, None, None)
            )
        else:
            roots.append(_linked_prompt_root(active, sampler, f"{branch}_{kind}"))
    return tuple(roots)


def _prompt_ancestor_distances(
    index: GraphIndex,
    active: ActiveGraph,
    root_id: str,
    root_output_index: int | None,
) -> dict[str, int]:
    distances = {root_id: 0}
    queue: deque[tuple[str, int, str | None, int]] = deque(
        [(root_id, root_output_index or 0, None, 0)]
    )
    state_distances: dict[tuple[str, int, str | None], int] = {}
    while queue:
        consumer_id, output_index, component, distance = queue.popleft()
        state = (consumer_id, output_index, component)
        known_state_distance = state_distances.get(state)
        if known_state_distance is not None and known_state_distance <= distance:
            continue
        state_distances[state] = distance
        node = index.node(consumer_id)
        if node is None:
            continue
        routes, _decision = routed_upstream_edges(
            index,
            node,
            output_index=output_index,
            component=component,
        )
        for route in routes:
            edge = route.edge
            if not active.contains(edge.source_node_id):
                continue
            candidate_distance = distance + 1
            if candidate_distance >= distances.get(edge.source_node_id, candidate_distance + 1):
                if (edge.source_node_id, edge.output_index, route.component) in state_distances:
                    continue
            else:
                distances[edge.source_node_id] = candidate_distance
            queue.append(
                (
                    edge.source_node_id,
                    edge.output_index,
                    route.component,
                    candidate_distance,
                )
            )
    return distances


def _prompt_candidates(
    index: GraphIndex,
    active: ActiveGraph,
    *,
    root_id: str,
    root_output_index: int | None,
    kind: str,
) -> tuple[tuple[str, str], ...]:
    distances = _prompt_ancestor_distances(
        index,
        active,
        root_id,
        root_output_index,
    )
    found: list[tuple[str, str]] = []
    for node_id in sorted(distances, key=lambda value: (distances[value], node_sort_key(value))):
        node = index.node(node_id)
        if node is None or not is_text_encode_node(node):
            continue
        if compact_class(node) == "sagecombinecliptextencode":
            combined = _sage_combined_prompt_text(index, active, node)
            if combined is not None:
                found.append((node_id, combined))
            continue
        names = _prompt_input_names(
            node,
            kind,
            output_index=root_output_index if node_id == root_id else None,
        )
        node_texts = tuple(
            text
            for input_name in names
            if (text := scalar_string(resolve_node_input(index, active, node, (input_name,))))
            is not None
        )
        unique_node_texts = tuple(dict.fromkeys(node_texts))
        if _combines_prompt_channels(node) and unique_node_texts:
            found.append((node_id, "\n".join(unique_node_texts)))
        else:
            found.extend((node_id, text) for text in unique_node_texts)
    return tuple(found)


def _sage_combined_prompt_text(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode,
) -> str | None:
    raw = node.input_value("texts")
    if not isinstance(raw, Mapping):
        return None
    wrapped = raw.get("__value__")
    values = wrapped if isinstance(wrapped, Mapping) else raw
    indexed: list[tuple[int, FrozenValue]] = []
    for key, value in values.items():
        if not key.startswith("text_"):
            continue
        try:
            position = int(key.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            continue
        indexed.append((position, value))
    texts = tuple(
        text
        for _position, value in sorted(indexed)
        if (text := scalar_string(resolve_scalar(index, active, value))) is not None
    )
    return "\n".join(texts) if texts else None


def _prompt_field(
    index: GraphIndex,
    active: ActiveGraph,
    sampler: PromptNode,
    kind: str,
) -> tuple[PromptField, tuple[ScanIssue, ...]]:
    roots = _antrobots_prompt_roots(index, active, sampler, kind)
    if roots is None:
        roots = (_prompt_root(index, active, sampler, kind),)
    present_roots = tuple(cast(_PresentPromptRoot, root) for root in roots if root[0] is not None)
    if not present_roots:
        issue = ScanIssue(f"{kind}_prompt_missing") if kind == "positive" else None
        return PromptField(), (issue,) if issue is not None else ()
    found: list[tuple[str, str]] = []
    zeroed_ids: list[str] = []
    for root_id, _, root_output_index in present_roots:
        root = index.node(root_id)
        if root is not None and compact_class(root) in {
            "conditioningzeroout",
            "sagezeroconditioning",
        }:
            zeroed_ids.append(root_id)
            continue
        found.extend(
            _prompt_candidates(
                index,
                active,
                root_id=root_id,
                root_output_index=root_output_index,
                kind=kind,
            )
        )
    unique_texts = tuple(dict.fromkeys(text for _, text in found))
    source_ids = tuple(dict.fromkeys((*zeroed_ids, *(node_id for node_id, _ in found))))
    if len(unique_texts) == 1:
        return (
            PromptField(
                text=unique_texts[0],
                branch_present=True,
                source_node_ids=source_ids,
                candidates=unique_texts,
            ),
            (),
        )
    if len(unique_texts) > 1:
        return (
            PromptField(
                branch_present=True,
                source_node_ids=source_ids,
                candidates=unique_texts,
            ),
            (ScanIssue(f"{kind}_prompt_ambiguous"),),
        )
    issue = ScanIssue(f"{kind}_prompt_missing") if kind == "positive" else None
    return (
        PromptField(branch_present=True),
        (issue,) if issue is not None else (),
    )


def _combines_prompt_channels(node: PromptNode) -> bool:
    return compact_class(node) in _PROMPT_CHANNEL_CLASSES


def _prompt_input_names(
    node: PromptNode,
    kind: str,
    *,
    output_index: int | None = None,
) -> tuple[str, ...]:
    compact = compact_class(node)
    names: tuple[str, ...]
    if compact == "impactwildcardencode":
        found = next(
            (name for name in ("populated_text", "wildcard_text") if name in node.inputs),
            None,
        )
        names = (found,) if found is not None else ()
    elif (channel_fields := _MULTI_CHANNEL_PROMPT_FIELDS.get(compact)) is not None:
        names = channel_fields[kind]
    elif compact == "seargesdxlpromptencoder":
        fallback_names = (
            ("pos_g", "pos_l", "pos_r") if kind == "positive" else ("neg_g", "neg_l", "neg_r")
        )
        names = (
            _SEARGE_PROMPT_OUTPUT_FIELDS.get(output_index, fallback_names)
            if output_index is not None
            else fallback_names
        )
    elif compact in {"adepromptscheduling", "adepromptschedulinglatents"}:
        names = ("prepend_text", "prompts", "append_text")
    elif compact in {"ltxvmultipromptprovider", "multipromptprovider"}:
        names = ("prompts",)
    elif compact == "easystylesselector":
        names = ("positive",) if kind == "positive" else ("negative",)
    elif compact == "textparsea1111embeddings":
        names = ("text",)
    elif compact in {
        "sdxlpowerpromptpositivergthree",
        "sdxlpowerpromptsimplenegativergthree",
    }:
        names = ("prompt_g", "prompt_l")
    elif compact == "crossattnerasereplacehidream":
        names = (
            ("t5xxl_replace", "llama_replace")
            if output_index == 0 or (output_index is None and kind == "positive")
            else ("t5xxl_erase", "llama_erase")
        )
    elif is_direct_image_generator_node(node):
        names = (
            ("positive_prompt", "positive", "prompt", "user_prompt")
            if kind == "positive"
            else ("negative_prompt", "negative")
        )
    else:
        dedicated_names = (
            ("positive_prompt", "positive")
            if kind == "positive"
            else ("negative_prompt", "negative")
        )
        available_dedicated = tuple(name for name in dedicated_names if name in node.inputs)
        names = available_dedicated or (
            _POSITIVE_PROMPT_FIELDS if kind == "positive" else _NEGATIVE_PROMPT_FIELDS
        )
    return tuple(name for name in names if name in node.inputs)


def extract_prompts(
    index: GraphIndex,
    active: ActiveGraph,
    stage: StageSelection,
) -> tuple[PromptRecord, tuple[ScanIssue, ...]]:
    """Extract selected positive and negative conditioning text."""

    sampler = _stage_node(index, stage)
    if sampler is None:
        return PromptRecord(), ()
    positive, positive_issues = _prompt_field(index, active, sampler, "positive")
    negative, negative_issues = _prompt_field(index, active, sampler, "negative")
    return PromptRecord(positive, negative), (*positive_issues, *negative_issues)


__all__ = ["extract_generation_settings", "extract_prompts"]
