"""Scan ComfyUI prompt/workflow graphs into shared metadata objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

from ..metadata.schema import (
    GenerationSettings,
    GeneratorMetadata,
    ModelResourceMetadata,
    PromptMetadata,
    ResolvedResource,
    UnresolvedResource,
    ValidationIssue,
)


PHASE3_UNRESOLVED_REASON = "hash_and_air_resolution_not_implemented_in_phase_3"
_CHECKPOINT_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
_UNET_EXTENSIONS = {".safetensors", ".pt", ".pth", ".bin"}
_DIFFUSION_MODEL_EXTENSIONS = {".gguf"}
_VIDEO_MODEL_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv"}


@dataclass(frozen=True)
class WorkflowScanResult:
    prompt: PromptMetadata
    generation: GenerationSettings
    resources: tuple[ResolvedResource, ...]
    unresolved_resources: tuple[UnresolvedResource, ...]
    warnings: tuple[ValidationIssue, ...]
    generator: GeneratorMetadata
    raw_resources: tuple[ResolvedResource, ...] = ()


@dataclass(frozen=True)
class NodeInfo:
    node_id: str
    class_type: str
    inputs: Mapping[str, Any]
    display_name: str | None = None


@dataclass(frozen=True)
class WorkflowNodeInfo:
    title: str | None = None
    class_type: str | None = None


def scan_workflow_graph(
    prompt: Any,
    extra_pnginfo: Mapping[str, Any] | None = None,
) -> WorkflowScanResult:
    """Extract known generation settings and resources from ComfyUI metadata."""

    warnings: list[ValidationIssue] = []
    workflow_lookup, generator, workflow_warnings = _workflow_lookup(extra_pnginfo or {})
    warnings.extend(workflow_warnings)

    nodes, prompt_warnings = _prompt_nodes(prompt, workflow_lookup)
    warnings.extend(prompt_warnings)

    if not nodes:
        return WorkflowScanResult(
            prompt=PromptMetadata(),
            generation=GenerationSettings(),
            resources=(),
            unresolved_resources=(),
            warnings=tuple(warnings),
            generator=generator,
            raw_resources=(),
        )

    active_node_ids = _active_upstream_node_ids(nodes)
    scan_nodes = _active_nodes(nodes, active_node_ids)
    raw_resources, _raw_unresolved, _raw_resource_warnings = _scan_resources(nodes)

    warnings.extend(_unknown_node_warnings(scan_nodes))
    prompt_metadata, prompt_scan_warnings = _scan_prompt_metadata(scan_nodes)
    warnings.extend(prompt_scan_warnings)

    primary_model_node_id = _primary_model_resource_node_id(scan_nodes)
    resources, unresolved_resources, resource_warnings = _scan_resources(scan_nodes, primary_model_node_id)
    warnings.extend(resource_warnings)
    if _has_ambiguous_base_models(resources):
        warnings.append(
            ValidationIssue(
                code="primary_model_ambiguous",
                message="Multiple base model resources were detected without a sampler-connected primary model",
                field="generation.model",
            )
        )
    generation = _scan_generation_settings(scan_nodes, resources)

    return WorkflowScanResult(
        prompt=prompt_metadata,
        generation=generation,
        resources=resources,
        unresolved_resources=unresolved_resources,
        warnings=tuple(warnings),
        generator=generator,
        raw_resources=raw_resources,
    )


def _prompt_nodes(
    prompt: Any,
    workflow_lookup: Mapping[str, WorkflowNodeInfo],
) -> tuple[dict[str, NodeInfo], tuple[ValidationIssue, ...]]:
    if not isinstance(prompt, dict):
        return {}, (
            ValidationIssue(
                code="malformed_prompt_graph",
                message="ComfyUI prompt metadata is not a node mapping",
                field="prompt",
            ),
        )

    nodes: dict[str, NodeInfo] = {}
    warnings: list[ValidationIssue] = []
    for raw_id, raw_node in prompt.items():
        node_id = str(raw_id)
        if not isinstance(raw_node, dict):
            warnings.append(
                ValidationIssue(
                    code="malformed_prompt_node",
                    message=f"Prompt node {node_id} is not an object",
                    field=f"prompt.{node_id}",
                )
            )
            continue

        inputs = raw_node.get("inputs", {})
        if not isinstance(inputs, dict):
            warnings.append(
                ValidationIssue(
                    code="malformed_prompt_node_inputs",
                    message=f"Prompt node {node_id} inputs are not an object",
                    field=f"prompt.{node_id}.inputs",
                )
            )
            inputs = {}

        class_type = str(raw_node.get("class_type") or "")
        workflow_info = workflow_lookup.get(node_id)
        display_name = _string_or_none(raw_node.get("_meta", {}).get("title"))
        if display_name is None and workflow_info is not None:
            display_name = workflow_info.title
        if not class_type and workflow_info is not None and workflow_info.class_type:
            class_type = workflow_info.class_type

        nodes[node_id] = NodeInfo(
            node_id=node_id,
            class_type=class_type,
            inputs=inputs,
            display_name=display_name,
        )

    return nodes, tuple(warnings)


def _workflow_lookup(
    extra_pnginfo: Mapping[str, Any],
) -> tuple[dict[str, WorkflowNodeInfo], GeneratorMetadata, tuple[ValidationIssue, ...]]:
    workflow = extra_pnginfo.get("workflow")
    version = _string_or_none(extra_pnginfo.get("comfyui_version"))
    warnings: list[ValidationIssue] = []
    lookup: dict[str, WorkflowNodeInfo] = {}

    if workflow is None:
        return lookup, GeneratorMetadata(version=version), ()

    if not isinstance(workflow, dict):
        return (
            lookup,
            GeneratorMetadata(version=version),
            (
                ValidationIssue(
                    code="malformed_workflow_metadata",
                    message="ComfyUI workflow metadata is not an object",
                    field="workflow",
                ),
            ),
        )

    if version is None:
        version = _string_or_none(workflow.get("comfyui_version")) or _string_or_none(workflow.get("version"))

    raw_nodes = workflow.get("nodes", [])
    if raw_nodes is None:
        raw_nodes = []
    if not isinstance(raw_nodes, list):
        warnings.append(
            ValidationIssue(
                code="malformed_workflow_nodes",
                message="ComfyUI workflow nodes metadata is not a list",
                field="workflow.nodes",
            )
        )
        raw_nodes = []

    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        node_id = raw_node.get("id")
        if node_id is None:
            continue
        lookup[str(node_id)] = WorkflowNodeInfo(
            title=_string_or_none(raw_node.get("title")),
            class_type=_string_or_none(raw_node.get("type")),
        )

    return lookup, GeneratorMetadata(version=version), tuple(warnings)


def _scan_prompt_metadata(
    nodes: Mapping[str, NodeInfo],
) -> tuple[PromptMetadata, tuple[ValidationIssue, ...]]:
    warnings: list[ValidationIssue] = []
    sampler = _first_node(nodes, _is_sampler_node)

    if sampler is not None:
        positive = _resolve_text_reference(nodes, sampler.inputs.get("positive"))
        negative = _resolve_text_reference(nodes, sampler.inputs.get("negative"))
        if positive or negative:
            return PromptMetadata(positive=positive, negative=negative), ()

    text_candidates = [
        text
        for text in (_string_or_none(node.inputs.get("text")) for node in nodes.values() if _is_clip_text_node(node))
        if text
    ]
    if len(text_candidates) > 1:
        warnings.append(
            ValidationIssue(
                code="ambiguous_prompt_candidates",
                message="Multiple CLIPTextEncode prompt candidates were found without a sampler link",
                field="prompt",
            )
        )
    if text_candidates:
        return PromptMetadata(positive=text_candidates[0]), tuple(warnings)

    return PromptMetadata(), tuple(warnings)


def _scan_generation_settings(
    nodes: Mapping[str, NodeInfo],
    resources: tuple[ResolvedResource, ...],
) -> GenerationSettings:
    sampler = _first_node(nodes, _is_sampler_node)
    sampler_inputs = sampler.inputs if sampler is not None else {}
    scheduler_node = _linked_or_first_node(
        nodes,
        sampler_inputs.get("sigmas"),
        _is_scheduler_node,
    )
    sampler_select = _linked_or_first_node(
        nodes,
        sampler_inputs.get("sampler"),
        lambda node: _class_contains(node, "ksamplerselect"),
    )
    noise_node = _linked_or_first_node(
        nodes,
        sampler_inputs.get("noise"),
        lambda node: _class_contains(node, "randomnoise"),
    )
    latent_inputs = _linked_or_first_inputs(
        nodes,
        _first_input_value(sampler_inputs, ("latent_image", "latent")),
        _is_empty_latent_node,
    )

    seed = _first_int_input(sampler_inputs, ("seed", "noise_seed"))
    if seed is None and noise_node is not None:
        seed = _first_int_input(noise_node.inputs, ("noise_seed", "seed"))

    cfg = _float_or_none(sampler_inputs.get("cfg"))
    if cfg is None:
        cfg_guider = _first_node(nodes, lambda node: _class_contains(node, "cfgguider"))
        cfg = _float_or_none(cfg_guider.inputs.get("cfg")) if cfg_guider else None

    sampler_name = _string_or_none(sampler_inputs.get("sampler_name"))
    if sampler_name is None and sampler_select is not None:
        sampler_name = _string_or_none(sampler_select.inputs.get("sampler_name"))

    scheduler = _string_or_none(sampler_inputs.get("scheduler"))
    if scheduler is None and scheduler_node is not None:
        scheduler = _first_string_input(scheduler_node.inputs, ("scheduler", "scheduler_name"))

    extra = _scan_generation_extra(nodes)
    first_model = _primary_or_single_resource_name(resources, {"checkpoint", "base_model"})
    first_vae = _first_resource_name(resources, {"vae"})
    steps = _first_int_input(sampler_inputs, ("steps", "steps_to_run"))
    if steps is None and scheduler_node is not None:
        steps = _first_int_input(scheduler_node.inputs, ("steps", "total_steps"))
    denoise = _float_or_none(sampler_inputs.get("denoise"))
    if denoise is None and scheduler_node is not None:
        denoise = _float_or_none(scheduler_node.inputs.get("denoise"))

    if sampler is not None and _class_contains(sampler, "ksampleradvanced"):
        _add_extra_if_present(extra, "startAtStep", _int_or_none(sampler_inputs.get("start_at_step")))
        _add_extra_if_present(extra, "endAtStep", _int_or_none(sampler_inputs.get("end_at_step")))
        _add_extra_if_present(extra, "addNoise", sampler_inputs.get("add_noise"))
        _add_extra_if_present(
            extra,
            "returnWithLeftoverNoise",
            sampler_inputs.get("return_with_leftover_noise"),
        )

    return GenerationSettings(
        steps=steps,
        sampler=sampler_name,
        scheduler=scheduler,
        cfg_scale=cfg,
        seed=seed,
        width=_int_or_none(latent_inputs.get("width")),
        height=_int_or_none(latent_inputs.get("height")),
        batch_size=_int_or_none(latent_inputs.get("batch_size")),
        model=first_model,
        vae=first_vae,
        denoising_strength=denoise,
        extra=extra,
    )


def _scan_generation_extra(nodes: Mapping[str, NodeInfo]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    flux_guidance = _first_node(nodes, lambda node: _class_contains(node, "fluxguidance"))
    if flux_guidance is not None:
        _add_extra_if_present(extra, "fluxGuidance", _float_or_none(flux_guidance.inputs.get("guidance")))

    model_sampling_flux = _first_node(nodes, lambda node: _class_contains(node, "modelsamplingflux"))
    if model_sampling_flux is not None:
        values = _primitive_inputs(model_sampling_flux.inputs)
        if values:
            extra["modelSamplingFlux"] = values

    model_sampling = _first_node(
        nodes,
        lambda node: _class_contains(node, "modelsampling") and not _class_contains(node, "modelsamplingflux"),
    )
    if model_sampling is not None:
        values = _primitive_inputs(model_sampling.inputs)
        if values:
            extra["modelSampling"] = values

    basic_guider = _first_node(nodes, lambda node: _class_contains(node, "basicguider"))
    if basic_guider is not None:
        direct_guidance = _float_or_none(basic_guider.inputs.get("guidance"))
        if direct_guidance is not None and "fluxGuidance" not in extra:
            extra["fluxGuidance"] = direct_guidance
        extra["basicGuider"] = True

    sampler_custom = _first_node(nodes, lambda node: _class_contains(node, "samplercustomadvanced"))
    if sampler_custom is not None:
        values = _primitive_inputs(sampler_custom.inputs)
        if values:
            extra["samplerCustomAdvanced"] = values

    return extra


def _scan_resources(
    nodes: Mapping[str, NodeInfo],
    primary_model_node_id: str | None = None,
) -> tuple[tuple[ResolvedResource, ...], tuple[UnresolvedResource, ...], tuple[ValidationIssue, ...]]:
    resources: list[ResolvedResource] = []
    unresolved: list[UnresolvedResource] = []
    warnings: list[ValidationIssue] = []
    controlnet_strengths = _controlnet_strengths(nodes)

    for node in nodes.values():
        class_lower = node.class_type.lower()
        resource_specs = _resource_specs_for_node(node)
        for spec in resource_specs:
            field_name, role, resource_type = spec
            raw_value = node.inputs.get(field_name)
            if raw_value is None or _is_link(raw_value):
                continue
            selected_value = _safe_selected_value(raw_value)
            filename = _basename(selected_value)
            role, resource_type, type_warning = _classify_resource_type(
                node=node,
                field_name=field_name,
                filename=filename,
                default_role=role,
                default_type=resource_type,
            )
            if type_warning is not None:
                warnings.append(type_warning)
            display_name = node.display_name
            strength = controlnet_strengths.get(node.node_id)
            strength_model = _float_or_none(node.inputs.get("strength_model"))
            strength_clip = _float_or_none(node.inputs.get("strength_clip"))

            if "lora" in class_lower:
                strength = strength_model if strength_model is not None else strength

            metadata_extra: dict[str, Any] = {}
            if node.node_id == primary_model_node_id and role in {"checkpoint", "base_model"}:
                metadata_extra["primaryModel"] = True
                metadata_extra["primarySelection"] = "sampler_model_path"

            metadata = ModelResourceMetadata(
                role=role,
                type=resource_type,
                node_id=node.node_id,
                node_class_type=node.class_type,
                display_name=display_name,
                name=filename,
                selected_value=selected_value,
                source_value=str(raw_value),
                filename=filename,
                local_path_basename=filename,
                strength=strength,
                strength_model=strength_model,
                strength_clip=strength_clip,
                metadata=metadata_extra,
            )
            resources.append(
                ResolvedResource(
                    resource=metadata,
                    resolved=False,
                    unresolved_reason=PHASE3_UNRESOLVED_REASON,
                )
            )
            unresolved.append(
                UnresolvedResource(
                    reason=PHASE3_UNRESOLVED_REASON,
                    role=role,
                    type=resource_type,
                    node_id=node.node_id,
                    node_class_type=node.class_type,
                    display_name=display_name,
                    name=filename,
                    selected_value=selected_value,
                    filename=filename,
                    local_path_basename=filename,
                    strength=strength,
                    strength_model=strength_model,
                    strength_clip=strength_clip,
                )
            )

    return tuple(resources), tuple(unresolved), tuple(warnings)


def _resource_specs_for_node(node: NodeInfo) -> tuple[tuple[str, str, str], ...]:
    class_lower = node.class_type.lower()
    inputs = node.inputs

    if "checkpointloader" in class_lower:
        return _available_specs(inputs, ("ckpt_name", "checkpoint", "model_name"), "checkpoint", "checkpoint")

    if _is_clip_loader_node(node):
        specs: list[tuple[str, str, str]] = []
        for field_name in ("clip_name", "clip_name1", "clip_name2", "clip_name3"):
            if field_name in inputs:
                specs.append((field_name, "text_encoder", "clip"))
        return tuple(specs)

    if "unetloader" in class_lower or ("gguf" in class_lower and "loader" in class_lower):
        return _available_specs(inputs, ("unet_name", "model_name", "ckpt_name"), "base_model", "unet")

    if "lora" in class_lower and "loader" in class_lower:
        return _available_specs(inputs, ("lora_name", "lora", "model_name"), "lora", "lora")

    if "vaeloader" in class_lower:
        return _available_specs(inputs, ("vae_name", "model_name"), "vae", "vae")

    if "controlnet" in class_lower and "loader" in class_lower:
        return _available_specs(
            inputs, ("control_net_name", "model_name", "controlnet_name"), "controlnet", "controlnet"
        )

    if "ipadapter" in class_lower and "loader" in class_lower:
        return _available_specs(inputs, ("ipadapter_file", "ipadapter_name", "model_name"), "ipadapter", "ipadapter")

    if "upscale" in class_lower and "loader" in class_lower:
        return _available_specs(inputs, ("model_name", "upscale_model_name"), "upscaler", "upscaler")

    if ("embedding" in class_lower or "textualinversion" in class_lower) and "loader" in class_lower:
        return _available_specs(inputs, ("embedding_name", "embedding", "model_name"), "embedding", "embedding")

    return ()


def _classify_resource_type(
    *,
    node: NodeInfo,
    field_name: str,
    filename: str,
    default_role: str,
    default_type: str,
) -> tuple[str, str, ValidationIssue | None]:
    class_lower = node.class_type.lower()
    extension = _file_extension(filename)

    if "checkpointloader" in class_lower and default_type == "checkpoint":
        if extension in _CHECKPOINT_EXTENSIONS:
            return default_role, "checkpoint", None
        if extension in _VIDEO_MODEL_EXTENSIONS:
            return (
                "base_model",
                "video_model",
                _uncertain_type_warning(node, field_name, filename, "checkpoint loader selected a video-like file"),
            )
        if extension in _DIFFUSION_MODEL_EXTENSIONS:
            return (
                "base_model",
                "diffusion_model",
                _uncertain_type_warning(
                    node, field_name, filename, "checkpoint loader selected a diffusion-model container"
                ),
            )
        return (
            "base_model",
            "unknown_model",
            _uncertain_type_warning(
                node, field_name, filename, "checkpoint loader selected an unsupported model extension"
            ),
        )

    if "unetloader" in class_lower:
        if extension in _VIDEO_MODEL_EXTENSIONS:
            return (
                "base_model",
                "video_model",
                _uncertain_type_warning(
                    node,
                    field_name,
                    filename,
                    "UNET loader selected a video-like file",
                ),
            )
        if extension in _DIFFUSION_MODEL_EXTENSIONS:
            return "base_model", "diffusion_model", None
        if extension in _UNET_EXTENSIONS:
            return "base_model", "unet", None

    if "gguf" in class_lower and "loader" in class_lower and default_role in {"checkpoint", "base_model"}:
        return "base_model", "diffusion_model", None

    return default_role, default_type, None


def _uncertain_type_warning(
    node: NodeInfo,
    field_name: str,
    filename: str,
    reason: str,
) -> ValidationIssue:
    return ValidationIssue(
        code="resource_type_uncertain",
        message=f"Resource type is conservative because {reason}: {_basename(filename)}",
        field=f"prompt.{node.node_id}.inputs.{field_name}",
    )


def _available_specs(
    inputs: Mapping[str, Any],
    field_names: Iterable[str],
    role: str,
    resource_type: str,
) -> tuple[tuple[str, str, str], ...]:
    return tuple((field_name, role, resource_type) for field_name in field_names if field_name in inputs)


def _controlnet_strengths(nodes: Mapping[str, NodeInfo]) -> dict[str, float]:
    strengths: dict[str, float] = {}
    for node in nodes.values():
        if not _class_contains(node, "controlnetapply"):
            continue
        control_ref = node.inputs.get("control_net")
        node_id = _linked_node_id(control_ref)
        if node_id is None:
            continue
        strength = _float_or_none(node.inputs.get("strength"))
        if strength is not None:
            strengths[node_id] = strength
    return strengths


def _unknown_node_warnings(nodes: Mapping[str, NodeInfo]) -> tuple[ValidationIssue, ...]:
    warnings: list[ValidationIssue] = []
    for node in nodes.values():
        if node.class_type and _is_known_node(node):
            continue
        warnings.append(
            ValidationIssue(
                code="unknown_node_class",
                message=f"Unknown or unsupported ComfyUI node class encountered: {node.class_type or '<missing>'}",
                field=f"prompt.{node.node_id}.class_type",
            )
        )
    return tuple(warnings)


def _active_upstream_node_ids(nodes: Mapping[str, NodeInfo]) -> set[str] | None:
    save_nodes = [node for node in nodes.values() if _is_our_save_node(node)]
    if not save_nodes:
        return None

    active: set[str] = set()
    queue: list[str] = []
    for save_node in save_nodes:
        queue.extend(_linked_node_ids(save_node.inputs.get("images")))

    while queue:
        node_id = queue.pop(0)
        if node_id in active:
            continue
        node = nodes.get(node_id)
        if node is None:
            continue
        active.add(node_id)
        for value in node.inputs.values():
            queue.extend(_linked_node_ids(value))

    return active


def _active_nodes(
    nodes: Mapping[str, NodeInfo],
    active_node_ids: set[str] | None,
) -> dict[str, NodeInfo]:
    if active_node_ids is None:
        return dict(nodes)
    return {node_id: node for node_id, node in nodes.items() if node_id in active_node_ids}


def _is_our_save_node(node: NodeInfo) -> bool:
    compact = "".join(character for character in node.class_type.lower() if character.isalnum())
    return compact == "saveimagewithcivitaimetadata"


def _is_known_node(node: NodeInfo) -> bool:
    if _is_empty_latent_node(node):
        return True
    class_lower = node.class_type.lower()
    known_fragments = (
        "ksampler",
        "samplercustomadvanced",
        "ksamplerselect",
        "randomnoise",
        "basicscheduler",
        "scheduler",
        "cliptextencode",
        "emptylatentimage",
        "checkpointloader",
        "loraloader",
        "vaeloader",
        "controlnetloader",
        "controlnetapply",
        "upscalemodelloader",
        "unetloader",
        "dualcliploader",
        "triplecliploader",
        "cliploader",
        "modelsamplingflux",
        "modelsampling",
        "smartresolution",
        "fluxguidance",
        "basicguider",
        "cfgguider",
        "gguf",
        "ipadapter",
        "embedding",
        "textualinversion",
        "saveimage",
        "previewimage",
        "loadimage",
        "vaedecode",
        "vaeencode",
        "clipsetlastlayer",
        "conditioning",
        "reroute",
    )
    return any(fragment in class_lower for fragment in known_fragments)


def _resolve_text_reference(nodes: Mapping[str, NodeInfo], reference: Any) -> str | None:
    node_id = _linked_node_id(reference)
    if node_id is None:
        return _string_or_none(reference)
    node = nodes.get(node_id)
    if node is None:
        return None
    if _is_clip_text_node(node):
        return _string_or_none(node.inputs.get("text"))
    return None


def _linked_or_first_inputs(
    nodes: Mapping[str, NodeInfo],
    reference: Any,
    predicate: Any,
) -> Mapping[str, Any]:
    node_id = _linked_node_id(reference)
    if node_id is not None:
        node = nodes.get(node_id)
        if node is not None and predicate(node):
            return node.inputs
    node = _first_node(nodes, predicate)
    return node.inputs if node is not None else {}


def _linked_or_first_node(
    nodes: Mapping[str, NodeInfo],
    reference: Any,
    predicate: Any,
) -> NodeInfo | None:
    node_id = _linked_node_id(reference)
    if node_id is not None:
        node = nodes.get(node_id)
        if node is not None and predicate(node):
            return node
    return _first_node(nodes, predicate)


def _primary_model_resource_node_id(nodes: Mapping[str, NodeInfo]) -> str | None:
    sampler = _first_node(nodes, _is_sampler_node)
    if sampler is None:
        return _single_base_resource_node_id(nodes)

    candidates = _trace_base_model_candidates(nodes, _sampler_model_references(sampler))
    if candidates:
        candidates.sort(key=lambda item: (item[0], _node_sort_key(item[1])))
        return candidates[0][1]

    return _single_base_resource_node_id(nodes)


def _trace_base_model_candidates(
    nodes: Mapping[str, NodeInfo],
    references: Iterable[Any],
) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    queue: list[tuple[str, int]] = []
    seen: set[str] = set()

    for reference in references:
        node_id = _linked_node_id(reference)
        if node_id is not None:
            queue.append((node_id, 0))

    while queue:
        node_id, distance = queue.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)

        node = nodes.get(node_id)
        if node is None:
            continue
        if _has_base_model_resource(node):
            candidates.append((distance, node_id))
            continue

        for linked_id in _model_linked_input_node_ids(node):
            queue.append((linked_id, distance + 1))

    return candidates


def _sampler_model_references(sampler: NodeInfo) -> tuple[Any, ...]:
    return tuple(
        sampler.inputs[key] for key in ("model", "guider", "model_input", "diffusion_model") if key in sampler.inputs
    )


def _model_linked_input_node_ids(node: NodeInfo) -> tuple[str, ...]:
    model_input_names = {
        "model",
        "unet",
        "guider",
        "model_input",
        "diffusion_model",
        "base_model",
    }
    linked: list[str] = []
    for key, value in node.inputs.items():
        if str(key) not in model_input_names:
            continue
        node_id = _linked_node_id(value)
        if node_id is not None:
            linked.append(node_id)
    return tuple(linked)


def _has_base_model_resource(node: NodeInfo) -> bool:
    for field_name, role, _resource_type in _resource_specs_for_node(node):
        if role not in {"checkpoint", "base_model"}:
            continue
        value = node.inputs.get(field_name)
        if value is not None and not _is_link(value):
            return True
    return False


def _single_base_resource_node_id(nodes: Mapping[str, NodeInfo]) -> str | None:
    node_ids = [node.node_id for node in nodes.values() if _has_base_model_resource(node)]
    return node_ids[0] if len(node_ids) == 1 else None


def _has_ambiguous_base_models(resources: tuple[ResolvedResource, ...]) -> bool:
    base_resources = [resource for resource in resources if resource.resource.role in {"checkpoint", "base_model"}]
    if len(base_resources) <= 1:
        return False
    return not any(resource.resource.metadata.get("primaryModel") for resource in base_resources)


def _linked_node_id(value: Any) -> str | None:
    ids = _linked_node_ids(value)
    return ids[0] if ids else None


def _linked_node_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)) and value:
        if isinstance(value[0], (list, tuple)):
            ids: list[str] = []
            for item in value:
                ids.extend(_linked_node_ids(item))
            return ids
        if len(value) < 2 or not isinstance(value[1], int):
            return []
        return [str(value[0])]
    return []


def _is_link(value: Any) -> bool:
    return _linked_node_id(value) is not None


def _first_node(
    nodes: Mapping[str, NodeInfo],
    predicate: Any,
) -> NodeInfo | None:
    for node_id in sorted(nodes, key=_node_sort_key):
        node = nodes[node_id]
        if predicate(node):
            return node
    return None


def _node_sort_key(node_id: str) -> tuple[int, str]:
    return (int(node_id), node_id) if node_id.isdigit() else (999999, node_id)


def _first_resource_name(resources: tuple[ResolvedResource, ...], roles: set[str]) -> str | None:
    for resource in resources:
        if resource.resource.role in roles and resource.resource.name:
            return resource.resource.name
    return None


def _primary_or_single_resource_name(resources: tuple[ResolvedResource, ...], roles: set[str]) -> str | None:
    matching = [resource for resource in resources if resource.resource.role in roles]
    for resource in matching:
        if resource.resource.metadata.get("primaryModel") and resource.resource.name:
            return resource.resource.name
    if len(matching) == 1:
        return matching[0].resource.name
    return None


def _is_sampler_node(node: NodeInfo) -> bool:
    class_lower = node.class_type.lower()
    if "ksamplerselect" in class_lower:
        return False
    return "ksampler" in class_lower or "samplercustomadvanced" in class_lower


def _is_scheduler_node(node: NodeInfo) -> bool:
    return "scheduler" in node.class_type.lower()


def _is_empty_latent_node(node: NodeInfo) -> bool:
    class_lower = node.class_type.lower()
    return "empty" in class_lower and "latent" in class_lower and "image" in class_lower


def _is_clip_text_node(node: NodeInfo) -> bool:
    return _class_contains(node, "cliptextencode")


def _is_clip_loader_node(node: NodeInfo) -> bool:
    class_lower = node.class_type.lower()
    return (
        "cliploader" in class_lower or "dualcliploader" in class_lower or "triplecliploader" in class_lower
    ) and "cliptextencode" not in class_lower


def _class_contains(node: NodeInfo, fragment: str) -> bool:
    return fragment in node.class_type.lower()


def _primitive_inputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in inputs.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            values[str(key)] = value
    return dict(sorted(values.items()))


def _first_input_value(inputs: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in inputs:
            return inputs[key]
    return None


def _first_int_input(inputs: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = _int_or_none(inputs.get(key))
        if value is not None:
            return value
    return None


def _first_string_input(inputs: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _string_or_none(inputs.get(key))
        if value is not None:
            return value
    return None


def _add_extra_if_present(data: dict[str, Any], key: str, value: Any | None) -> None:
    if value is not None:
        data[key] = value


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


def _safe_selected_value(value: Any) -> str:
    text = str(value).replace("\\", "/")
    if text.startswith("/") or _looks_windows_absolute(text):
        return _basename(text)
    parts = [part for part in text.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        return _basename(text)
    return "/".join(parts) or _basename(text)


def _looks_windows_absolute(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] == "/" and value[0].isalpha()


def _basename(value: str) -> str:
    windows_name = PureWindowsPath(value).name
    posix_name = PurePosixPath(windows_name).name
    return posix_name or windows_name or value


def _file_extension(value: str) -> str:
    name = _basename(value)
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[1].lower()


__all__ = ["PHASE3_UNRESOLVED_REASON", "WorkflowScanResult", "scan_workflow_graph"]
