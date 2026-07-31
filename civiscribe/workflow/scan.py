"""Public phase-four workflow scanner orchestration."""

from __future__ import annotations

from collections.abc import Iterable

from ..domain import (
    GenerationSettings,
    PromptRecord,
    ScanIssue,
    WorkflowScan,
)
from .active import ActiveGraph, trace_active_upstream
from .classify import compact_class, is_known_active_node
from .extract import extract_generation_settings, extract_prompts
from .graph import GraphIndex, build_graph_index
from .lineage import (
    classify_workflow_kind,
    select_generation_stage,
    select_primary_resource,
    select_vae_resource,
)
from .model import DEFAULT_GRAPH_LIMITS, GraphLimits
from .normalize import normalize_api_prompt
from .resources import extract_active_resources

_SIMPLE_SEMANTIC_ISSUES = {
    "easyimagechooser": "runtime_image_selection_ambiguous",
    "easylatentcompositemaskedwithcond": "prompt_composition_runtime_dependent",
    "loadcache": "runtime_payload_provenance_unavailable",
    "lyingsigmasampler": "sampler_wrapper_present",
    "reloadimage": "runtime_payload_provenance_unavailable",
    "reloadlatent": "runtime_payload_provenance_unavailable",
    "reloadmodel": "runtime_payload_provenance_unavailable",
}


def _selected_style_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "none", "disabled", "off"}
    if isinstance(value, tuple):
        return any(_selected_style_value(item) for item in value)
    return True


def _deduplicate_issues(groups: Iterable[Iterable[ScanIssue]]) -> tuple[ScanIssue, ...]:
    issues: list[ScanIssue] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for group in groups:
        for issue in group:
            identity = (
                issue.code,
                issue.severity.value,
                issue.node_id,
                issue.input_name,
            )
            if identity in seen:
                continue
            seen.add(identity)
            issues.append(issue)
    return tuple(issues)


def _unknown_active_node_issues(
    index: GraphIndex,
    active: ActiveGraph,
) -> tuple[ScanIssue, ...]:
    routing_node_ids = {decision.node_id for decision in active.routing_decisions}
    return tuple(
        ScanIssue("unknown_active_node_class", node_id=node_id)
        for node_id in active.node_ids
        if node_id not in routing_node_ids
        and (node := index.node(node_id)) is not None
        and not is_known_active_node(node)
    )


def _active_semantic_issues(
    index: GraphIndex,
    active: ActiveGraph,
) -> tuple[ScanIssue, ...]:
    issues: list[ScanIssue] = []
    for node_id in active.node_ids:
        node = index.node(node_id)
        if node is None:
            continue
        compact = compact_class(node)
        if compact == "easyxyinputscheckpoint":
            issues.append(ScanIssue("dynamic_resource_selection_ambiguous", node_id=node_id))
        elif compact == "clownoptionsswapsamplerbeta":
            issues.append(ScanIssue("sampler_swap_schedule_present", node_id=node_id))
        elif compact == "crcyclemodels":
            mode = node.input_value("mode")
            if not isinstance(mode, str) or mode.strip().casefold() not in {
                "disabled",
                "none",
                "off",
            }:
                issues.append(ScanIssue("dynamic_resource_selection_ambiguous", node_id=node_id))
        elif compact == "crloadscheduledmodels":
            mode = node.input_value("mode")
            if not isinstance(mode, str) or mode.strip().casefold() != "load default model":
                issues.append(ScanIssue("dynamic_resource_selection_ambiguous", node_id=node_id))
        elif compact in {
            "easystylesselector",
            "promptmultiplestylesselector",
            "promptstylesselector",
        }:
            style_inputs = tuple(
                value for name, value in node.inputs.items() if "style" in name.casefold()
            )
            if any(_selected_style_value(value) for value in style_inputs):
                issues.append(ScanIssue("prompt_style_expansion_unavailable", node_id=node_id))
        elif compact == "textparsea1111embeddings":
            issues.append(ScanIssue("implicit_embedding_expansion_unavailable", node_id=node_id))
        elif (issue_code := _SIMPLE_SEMANTIC_ISSUES.get(compact)) is not None:
            issues.append(ScanIssue(issue_code, node_id=node_id))
    return tuple(issues)


def scan_workflow(
    prompt: object,
    *,
    save_node_id: str | None = None,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> WorkflowScan:
    """Scan one untrusted API prompt into active generation facts."""

    graph = normalize_api_prompt(prompt, limits=limits)
    index = build_graph_index(graph, limits=limits)
    active = trace_active_upstream(index, save_node_id=save_node_id)
    if active.save_node_id is None or not active.node_ids:
        return WorkflowScan(
            save_node_id=active.save_node_id,
            active_node_ids=active.node_ids,
            selected_stage_node_id=None,
            stage_candidate_ids=(),
            workflow_kind=None,
            prompts=PromptRecord(),
            settings=GenerationSettings(),
            resources=(),
            primary_resource_key=None,
            selected_vae_resource_key=None,
            issues=_deduplicate_issues((active.issues,)),
        )

    stage = select_generation_stage(index, active)
    resources, resource_issues = extract_active_resources(index, active)
    primary_key, primary_issues = select_primary_resource(
        index,
        active,
        stage,
        resources,
    )
    selected_vae_key, vae_issues = select_vae_resource(
        index,
        active,
        stage,
        resources,
    )
    workflow_kind, kind_issues = classify_workflow_kind(index, active, stage)
    settings, setting_issues = extract_generation_settings(index, active, stage)
    prompts, prompt_issues = extract_prompts(index, active, stage)
    unknown_issues = _unknown_active_node_issues(index, active)
    semantic_issues = _active_semantic_issues(index, active)
    issues = _deduplicate_issues(
        (
            active.issues,
            stage.issues,
            resource_issues,
            primary_issues,
            vae_issues,
            kind_issues,
            setting_issues,
            prompt_issues,
            unknown_issues,
            semantic_issues,
        )
    )
    return WorkflowScan(
        save_node_id=active.save_node_id,
        active_node_ids=active.node_ids,
        selected_stage_node_id=stage.selected_node_id,
        stage_candidate_ids=stage.candidate_node_ids,
        workflow_kind=workflow_kind,
        prompts=prompts,
        settings=settings,
        resources=resources,
        primary_resource_key=primary_key,
        selected_vae_resource_key=selected_vae_key,
        issues=issues,
    )


__all__ = ["scan_workflow"]
