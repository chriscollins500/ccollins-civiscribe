"""Generation stage and primary model lineage selection."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from ..domain import ResourceRecord, ResourceRole, ScanIssue, WorkflowKind
from .active import ActiveGraph
from .classify import (
    is_antrobots_refiner_node,
    is_antrobots_refiner_pipe_node,
    is_decode_node,
    is_direct_image_generator_node,
    is_generated_latent_node,
    is_image_latent_node,
    is_image_source_node,
    is_sampler_node,
)
from .graph import GraphIndex, as_link_reference
from .model import PromptNode, node_sort_key
from .scalar import resolve_node_input, scalar_int

_PRIMARY_INPUT_PRIORITY = {
    "base_ckpt_name": 0,
    "model_name": 0,
    "gguf_name": 1,
    "unet_name": 2,
    "diffusion_model_name": 3,
    "ckpt_name": 4,
    "checkpoint_name": 5,
    "checkpoint": 6,
    "stage_c": 7,
    "stage_b": 8,
    "extra_model_name": 9,
    "model_path": 10,
    "refiner_ckpt_name": 11,
}
_VAE_INPUT_PRIORITY = {
    "decode_vae_name": 0,
    "vae_name": 0,
    "encode_vae_name": 1,
    "stage_a": 2,
    "model_name": 3,
    "ckpt_name": 4,
}
_DIRECT_IMAGE_SOURCE_INPUTS = frozenset(
    {
        "character_image",
        "character_mask",
        "files",
        "first_frame",
        "garment",
        "image",
        "image_1",
        "image_2",
        "image_3",
        "image_4",
        "image_5",
        "image_luma_ref",
        "image_prompt",
        "image_ref",
        "images",
        "init_image_or_video",
        "last_frame",
        "mask",
        "model_3d",
        "optional_image",
        "person",
        "normal_map",
        "position_map",
        "reference_image",
        "reference_image_1",
        "reference_image_2",
        "reference_image_3",
        "reference_images",
        "source",
        "style_image",
    }
)


@dataclass(frozen=True, slots=True)
class StageSelection:
    """Selected nearest sampler stage, or explicit ambiguity."""

    selected_node_id: str | None
    candidate_node_ids: tuple[str, ...]
    issues: tuple[ScanIssue, ...] = ()


def select_generation_stage(
    index: GraphIndex,
    active: ActiveGraph,
) -> StageSelection:
    """Select the sampler nearest to the saved pixels."""

    candidates = tuple(
        sorted(
            (
                node_id
                for node_id in active.node_ids
                if (node := index.node(node_id)) is not None and is_sampler_node(node)
            ),
            key=node_sort_key,
        )
    )
    if not candidates:
        return StageSelection(
            None,
            (),
            (ScanIssue("sampler_stage_not_found"),),
        )
    nearest_distance = min(active.distance_from_save[node_id] for node_id in candidates)
    nearest = tuple(
        node_id for node_id in candidates if active.distance_from_save[node_id] == nearest_distance
    )
    if len(nearest) != 1:
        return StageSelection(
            None,
            nearest,
            (ScanIssue("sampler_stage_ambiguous"),),
        )
    return StageSelection(nearest[0], candidates)


def upstream_node_distances(
    index: GraphIndex,
    active: ActiveGraph,
    *,
    consumer_node_id: str,
    input_names: tuple[str, ...],
) -> dict[str, int]:
    """Return active ancestors reachable from selected consumer inputs."""

    active_ids = set(active.node_ids)
    queue: deque[tuple[str, int]] = deque(
        (edge.source_node_id, 1)
        for edge in index.upstream_edges(consumer_node_id)
        if edge.input_name in input_names and edge.source_node_id in active_ids
    )
    distances: dict[str, int] = {}
    while queue:
        node_id, distance = queue.popleft()
        known = distances.get(node_id)
        if known is not None and known <= distance:
            continue
        distances[node_id] = distance
        for edge in index.upstream_edges(node_id):
            if edge.source_node_id in active_ids:
                queue.append((edge.source_node_id, distance + 1))
    return distances


def classify_workflow_kind(
    index: GraphIndex,
    active: ActiveGraph,
    stage: StageSelection,
) -> tuple[WorkflowKind | None, tuple[ScanIssue, ...]]:
    """Classify txt2img/img2img only from the selected latent lineage."""

    if stage.selected_node_id is None:
        return None, ()
    selected_stage = index.node(stage.selected_node_id)
    if selected_stage is not None and is_direct_image_generator_node(selected_stage):
        has_source_input = any(
            input_name.casefold() in _DIRECT_IMAGE_SOURCE_INPUTS
            and (reference := as_link_reference(value)) is not None
            and active.contains(reference.source_node_id)
            for input_name, value in selected_stage.inputs.items()
        )
        return (
            WorkflowKind.IMG2IMG if has_source_input else WorkflowKind.TXT2IMG,
            (),
        )
    if selected_stage is not None and is_antrobots_refiner_pipe_node(selected_stage):
        use_image = resolve_node_input(index, active, selected_stage, ("use_image",))
        if isinstance(use_image, bool):
            return (
                WorkflowKind.IMG2IMG if use_image else WorkflowKind.TXT2IMG,
                (),
            )
    ancestors = upstream_node_distances(
        index,
        active,
        consumer_node_id=stage.selected_node_id,
        input_names=(
            "image",
            "image_frames",
            "image_embeds",
            "latent_image",
            "latent",
            "optional_image",
            "pipe",
            "sampler_inputs",
            "samples",
            "upscaled_image",
        ),
    )
    has_empty = any(
        is_generated_latent_node(node)
        for node_id in ancestors
        if (node := index.node(node_id)) is not None
    )
    has_encoded_image = any(
        is_image_latent_node(node)
        for node_id in ancestors
        if (node := index.node(node_id)) is not None
    )
    has_input_pixels = any(
        is_image_source_node(node)
        for node_id in ancestors
        if (node := index.node(node_id)) is not None
    )
    if selected_stage is not None and is_image_latent_node(selected_stage):
        has_encoded_image = True
    if has_empty and (has_encoded_image or has_input_pixels):
        return None, (ScanIssue("workflow_kind_ambiguous"),)
    kind = (
        WorkflowKind.IMG2IMG
        if has_encoded_image or has_input_pixels
        else (WorkflowKind.TXT2IMG if has_empty else None)
    )
    return kind, ()


def select_primary_resource(
    index: GraphIndex,
    active: ActiveGraph,
    stage: StageSelection,
    resources: tuple[ResourceRecord, ...],
) -> tuple[str | None, tuple[ScanIssue, ...]]:
    """Select the nearest base model on the selected sampler model path."""

    if stage.selected_node_id is None:
        return None, ()
    sampler = index.node(stage.selected_node_id)
    if sampler is None:
        return None, ()
    if is_direct_image_generator_node(sampler):
        return None, ()
    model_inputs = _primary_model_input_names(index, active, sampler)
    distances = upstream_node_distances(
        index,
        active,
        consumer_node_id=stage.selected_node_id,
        input_names=model_inputs,
    )
    candidates = tuple(
        resource
        for resource in resources
        if resource.role is ResourceRole.BASE_MODEL and resource.node_id in distances
    )
    if not candidates:
        return None, (ScanIssue("primary_model_not_found"),)
    nearest_distance = min(distances[resource.node_id] for resource in candidates)
    nearest = tuple(
        resource for resource in candidates if distances[resource.node_id] == nearest_distance
    )
    selected = _select_same_node_resource(nearest, _PRIMARY_INPUT_PRIORITY)
    if selected is not None:
        return selected.key, ()
    return None, (ScanIssue("primary_model_ambiguous"),)


def _antrobots_refine_step(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode,
) -> tuple[int | None, int | None]:
    total_steps = scalar_int(resolve_node_input(index, active, node, ("total_steps",)))
    refine_step = scalar_int(resolve_node_input(index, active, node, ("refine_step",)))
    return total_steps, refine_step


def _primary_model_input_names(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode,
) -> tuple[str, ...]:
    inputs = node.inputs
    antrobots_inputs = _antrobots_primary_model_input_names(index, active, node)
    if antrobots_inputs is not None:
        return antrobots_inputs
    class_key = node.class_type.casefold()
    if class_key == "fluxkohyainferencesampler":
        return ("flux_models",)
    if class_key in {"withanyonesampler", "withanyonesamplernode"}:
        return ("withAnyone_pipeline",)
    for input_name in (
        "model",
        "base_model",
        "base_pipe",
        "base_sampler",
        "basic_pipe",
        "detailer_pipe",
        "guider",
        "model_input",
        "diffusion_model",
        "pipe",
        "refiner_model",
        "sampler_inputs",
    ):
        if input_name in inputs:
            return (input_name,)
    return (
        "model",
        "base_pipe",
        "base_sampler",
        "basic_pipe",
        "detailer_pipe",
        "guider",
        "model_input",
        "diffusion_model",
        "pipe",
        "sampler_inputs",
    )


def _antrobots_primary_model_input_names(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode,
) -> tuple[str, ...] | None:
    is_pipe = is_antrobots_refiner_pipe_node(node)
    if not is_pipe and not is_antrobots_refiner_node(node):
        return None
    _total_steps, refine_step = _antrobots_refine_step(index, active, node)
    base_name, refine_name = (
        ("base_pipe", "refine_pipe") if is_pipe else ("base_model", "refiner_model")
    )
    if refine_step == 0:
        return (refine_name,)
    if refine_step is not None:
        return (base_name,)
    return (base_name, refine_name)


def _resource_input_name(resource: ResourceRecord) -> str:
    return resource.key.rsplit(":", maxsplit=1)[-1]


def _select_same_node_resource(
    resources: tuple[ResourceRecord, ...],
    priorities: dict[str, int],
) -> ResourceRecord | None:
    if not resources or len({resource.node_id for resource in resources}) != 1:
        return None
    ranked = tuple(
        (priorities.get(_resource_input_name(resource), len(priorities)), resource)
        for resource in resources
    )
    best_rank = min(rank for rank, _resource in ranked)
    best = tuple(resource for rank, resource in ranked if rank == best_rank)
    return best[0] if len(best) == 1 else None


def select_vae_resource(
    index: GraphIndex,
    active: ActiveGraph,
    stage: StageSelection,
    resources: tuple[ResourceRecord, ...],
) -> tuple[str | None, tuple[ScanIssue, ...]]:
    """Select the VAE feeding the decode stage nearest to the saved pixels."""

    stage_node = index.node(stage.selected_node_id) if stage.selected_node_id is not None else None
    decode_nodes = tuple(
        node_id
        for node_id in active.node_ids
        if (node := index.node(node_id)) is not None and is_decode_node(node)
    )
    if not decode_nodes:
        if stage.selected_node_id is None or stage_node is None:
            return None, ()
        return _select_stage_vae_resource(
            index,
            active,
            stage_node,
            resources,
        )

    nearest_decode_distance = min(active.distance_from_save[node_id] for node_id in decode_nodes)
    nearest_decodes = tuple(
        node_id
        for node_id in decode_nodes
        if active.distance_from_save[node_id] == nearest_decode_distance
    )
    if len(nearest_decodes) != 1:
        return None, (ScanIssue("vae_decode_stage_ambiguous"),)

    selected_decode = nearest_decodes[0]
    if (
        stage_node is not None
        and is_antrobots_refiner_node(stage_node)
        and any(
            edge.input_name in {"vae", "vae_model", "vqvae"}
            and edge.source_node_id == stage_node.node_id
            and edge.output_index == 1
            for edge in index.upstream_edges(selected_decode)
        )
    ):
        antrobots_inputs = cast(
            tuple[str, ...],
            _antrobots_vae_input_names(index, active, stage_node),
        )
        distances = upstream_node_distances(
            index,
            active,
            consumer_node_id=stage_node.node_id,
            input_names=antrobots_inputs,
        )
        return _select_nearest_vae(resources, distances)

    distances = upstream_node_distances(
        index,
        active,
        consumer_node_id=selected_decode,
        input_names=("vae", "vae_model", "vqvae"),
    )
    return _select_nearest_vae(resources, distances)


def _select_stage_vae_resource(
    index: GraphIndex,
    active: ActiveGraph,
    stage_node: PromptNode,
    resources: tuple[ResourceRecord, ...],
) -> tuple[str | None, tuple[ScanIssue, ...]]:
    input_names = _antrobots_vae_input_names(index, active, stage_node)
    if input_names is None:
        input_names = tuple(
            name
            for name in ("vae", "basic_pipe", "detailer_pipe", "pipe")
            if name in stage_node.inputs
        )
    if not input_names:
        input_names = _primary_model_input_names(index, active, stage_node)
    distances = upstream_node_distances(
        index,
        active,
        consumer_node_id=stage_node.node_id,
        input_names=input_names,
    )
    return _select_nearest_vae(resources, distances)


def _antrobots_vae_input_names(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode,
) -> tuple[str, ...] | None:
    if not (is_antrobots_refiner_node(node) or is_antrobots_refiner_pipe_node(node)):
        return None
    total_steps, refine_step = _antrobots_refine_step(index, active, node)
    base_name, refine_name = (
        ("base_pipe", "refine_pipe")
        if is_antrobots_refiner_pipe_node(node)
        else ("base_vae", "refine_vae")
    )
    if total_steps is not None and refine_step is not None:
        return (base_name,) if refine_step >= total_steps else (refine_name,)
    return (base_name, refine_name)


def _select_nearest_vae(
    resources: tuple[ResourceRecord, ...],
    distances: Mapping[str, int],
) -> tuple[str | None, tuple[ScanIssue, ...]]:
    candidates = tuple(
        resource
        for resource in resources
        if resource.role is ResourceRole.VAE and resource.node_id in distances
    )
    if not candidates:
        return None, ()

    nearest_resource_distance = min(distances[resource.node_id] for resource in candidates)
    nearest_resources = tuple(
        resource
        for resource in candidates
        if distances[resource.node_id] == nearest_resource_distance
    )
    selected = _select_same_node_resource(nearest_resources, _VAE_INPUT_PRIORITY)
    if selected is not None:
        return selected.key, ()
    return None, (ScanIssue("vae_resource_ambiguous"),)


__all__ = [
    "StageSelection",
    "classify_workflow_kind",
    "select_generation_stage",
    "select_primary_resource",
    "select_vae_resource",
    "upstream_node_distances",
]
