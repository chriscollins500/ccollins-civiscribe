"""Active local resource extraction without file reads or identity guesses."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from ..domain import (
    ResourceKind,
    ResourceRecord,
    ResourceRole,
    ResourceStrengths,
    ScanIssue,
)
from .active import ActiveGraph
from .classify import (
    ResourceInputSpec,
    compact_class,
    fixed_resource_specs,
    resource_input_specs,
)
from .graph import GraphIndex, as_link_reference
from .model import FrozenValue, PromptNode, node_sort_key
from .scalar import resolve_scalar

_MAX_RESOURCE_VALUE_CHARS = 512
_ASCII_CONTROL_BOUNDARY = 32
_MODEL_OUTPUT_INDEX = 0
_CLIP_OUTPUT_INDEX = 1
_VAE_OUTPUT_INDEX = 2
_DISABLED_RESOURCE_VALUES = frozenset(
    {
        "baked vae",
        "baked-vae",
        "baked / none",
        "__create_new__",
        "default",
        "none",
    }
)
_EMPTY_STRENGTHS = ResourceStrengths()


@dataclass(frozen=True, slots=True)
class _LoraRecordSpec:
    strengths: ResourceStrengths
    rule_id: str
    allow_zero_strength: bool = False


@dataclass(frozen=True, slots=True)
class _NamedResourceSpec:
    role: ResourceRole
    kind: ResourceKind
    rule_id: str


_INLINE_LORA = re.compile(
    r"<lora:([^<>:\r\n]{1,384}):"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"(?::([+-]?(?:\d+(?:\.\d*)?|\.\d+)))?>",
    re.IGNORECASE,
)
_INLINE_EMBEDDING = re.compile(
    r"(?<![A-Za-z0-9_])embedding:([^\s,;:()<>\[\]{}]{1,384})",
    re.IGNORECASE,
)
_PROMPT_TEXT_INPUTS = frozenset(
    {
        "negative",
        "negative_prompt",
        "optional_negative",
        "optional_positive",
        "populated_text",
        "positive",
        "positive_prompt",
        "prompt",
        "prompt_g",
        "prompt_l",
        "text",
        "wildcard_text",
    }
)
_MAX_STACK_LORAS = 64
_JAKE_EMBEDDING_MIN_EMPHASIS = 0.05
_TA_MODEL_PREFIXES: dict[str, tuple[ResourceRole, ResourceKind]] = {
    "[C] ": (ResourceRole.BASE_MODEL, ResourceKind.CHECKPOINT),
    "[D] ": (ResourceRole.BASE_MODEL, ResourceKind.DIFFUSION_MODEL),
    "[G] ": (ResourceRole.BASE_MODEL, ResourceKind.DIFFUSION_MODEL),
}


def _float_value(value: FrozenValue) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    return None


def _bool_value(value: FrozenValue) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on", "enabled"}:
            return True
        if normalized in {"false", "0", "no", "off", "disabled"}:
            return False
    return None


def _safe_resource_value(value: FrozenValue) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value or len(value) > _MAX_RESOURCE_VALUE_CHARS:
        return None
    normalized = unicodedata.normalize("NFC", value).replace("\\", "/")
    windows = PureWindowsPath(normalized)
    posix = PurePosixPath(normalized)
    if (
        windows.drive
        or windows.root
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in posix.parts)
        or ":" in normalized
        or any(ord(character) < _ASCII_CONTROL_BOUNDARY for character in normalized)
    ):
        return None
    return normalized, posix.name


def _resource_value_disabled(value: FrozenValue) -> bool:
    return isinstance(value, str) and value.strip().casefold() in _DISABLED_RESOURCE_VALUES


def _direct_strengths(node: PromptNode) -> ResourceStrengths:
    def first_value(*names: str) -> float | None:
        for name in names:
            value = _float_value(node.input_value(name))
            if value is not None:
                return value
        return None

    return ResourceStrengths(
        weight=first_value("strength", "lora_strength", "lora_weight"),
        model=first_value("strength_model", "lora_model_strength"),
        clip=first_value("strength_clip", "lora_clip_strength"),
    )


def _lora_disabled(strengths: ResourceStrengths) -> bool:
    values = tuple(
        value for value in (strengths.weight, strengths.model, strengths.clip) if value is not None
    )
    return bool(values) and all(value == 0 for value in values)


def _lora_record(
    node: PromptNode,
    *,
    input_name: str,
    value: FrozenValue,
    spec: _LoraRecordSpec,
) -> tuple[ResourceRecord | None, ScanIssue | None]:
    if _resource_value_disabled(value) or (
        not spec.allow_zero_strength and _lora_disabled(spec.strengths)
    ):
        return None, None
    safe = _safe_resource_value(value)
    if safe is None:
        return (
            None,
            ScanIssue(
                "resource_value_unsafe_or_invalid",
                node_id=node.node_id,
                input_name=input_name,
            ),
        )
    selected_value, filename = safe
    return (
        ResourceRecord(
            key=f"{node.node_id}:{input_name}",
            role=ResourceRole.LORA,
            kind=ResourceKind.LORA,
            node_id=node.node_id,
            node_class=node.class_type,
            filename=filename,
            selected_value=selected_value,
            strengths=spec.strengths,
            detection_rule_id=spec.rule_id,
        ),
        None,
    )


def _first_float_input(node: PromptNode, *input_names: str) -> float | None:
    for input_name in input_names:
        value = _float_value(node.input_value(input_name))
        if value is not None:
            return value
    return None


def _direct_resources(
    node: PromptNode,
    *,
    index: GraphIndex | None = None,
    active: ActiveGraph | None = None,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    specs = _active_direct_specs(node, resource_input_specs(node), active)
    for spec in specs:
        value = node.input_value(spec.input_name)
        if as_link_reference(value) is not None:
            if index is None or active is None:
                continue
            value = resolve_scalar(
                index,
                active,
                value,
                preferred_input_names=(spec.input_name, "model_name", "value"),
            )
        if (
            compact_class(node) == "samloader"
            and spec.input_name == "model_name"
            and isinstance(value, str)
            and value.strip().casefold() == "esam"
        ):
            continue
        if _resource_value_disabled(value):
            continue
        safe = _safe_resource_value(value)
        if safe is None:
            issues.append(
                ScanIssue(
                    "resource_value_unsafe_or_invalid",
                    node_id=node.node_id,
                    input_name=spec.input_name,
                )
            )
            continue
        selected_value, filename = safe
        strengths = _direct_strengths(node)
        if spec.role is ResourceRole.LORA and _lora_disabled(strengths):
            continue
        records.append(
            ResourceRecord(
                key=f"{node.node_id}:{spec.input_name}",
                role=spec.role,
                kind=spec.kind,
                node_id=node.node_id,
                node_class=node.class_type,
                filename=filename,
                selected_value=selected_value,
                strengths=strengths,
                detection_rule_id=spec.rule_id,
            )
        )
    for fixed_spec in fixed_resource_specs(node):
        safe = _safe_resource_value(fixed_spec.selected_value)
        if safe is None:
            issues.append(
                ScanIssue(
                    "fixed_resource_value_invalid",
                    node_id=node.node_id,
                )
            )
            continue
        selected_value, filename = safe
        records.append(
            ResourceRecord(
                key=f"{node.node_id}:fixed:{fixed_spec.rule_id}",
                role=fixed_spec.role,
                kind=fixed_spec.kind,
                node_id=node.node_id,
                node_class=node.class_type,
                filename=filename,
                selected_value=selected_value,
                detection_rule_id=fixed_spec.rule_id,
            )
        )
    ta_record, ta_issue = _ta_prefixed_model_resource(node, index=index, active=active)
    if ta_record is not None:
        records.append(ta_record)
    if ta_issue is not None:
        issues.append(ta_issue)
    return tuple(records), tuple(issues)


def _ta_prefixed_model_resource(
    node: PromptNode,
    *,
    index: GraphIndex | None,
    active: ActiveGraph | None,
) -> tuple[ResourceRecord | None, ScanIssue | None]:
    """Parse the current TA unified loader's source-defined model prefixes."""

    if compact_class(node) != "taloadmodelwithname":
        return None, None
    value = node.input_value("model_file")
    if as_link_reference(value) is not None:
        if index is None or active is None:
            return None, None
        value = resolve_scalar(
            index,
            active,
            value,
            preferred_input_names=("model_file", "value"),
        )
    if not isinstance(value, str) or value.strip().casefold() == "no models found":
        return None, None
    for prefix, (role, kind) in _TA_MODEL_PREFIXES.items():
        if not value.startswith(prefix):
            continue
        safe = _safe_resource_value(value[len(prefix) :])
        if safe is None:
            return (
                None,
                ScanIssue(
                    "resource_value_unsafe_or_invalid",
                    node_id=node.node_id,
                    input_name="model_file",
                ),
            )
        selected_value, filename = safe
        return (
            ResourceRecord(
                key=f"{node.node_id}:model_file",
                role=role,
                kind=kind,
                node_id=node.node_id,
                node_class=node.class_type,
                filename=filename,
                selected_value=selected_value,
                detection_rule_id="ta_unified_model_loader",
            ),
            None,
        )
    return (
        None,
        ScanIssue(
            "resource_selector_unrecognized",
            node_id=node.node_id,
            input_name="model_file",
        ),
    )


def _named_resource_record(
    node: PromptNode,
    *,
    input_name: str,
    value: FrozenValue,
    spec: _NamedResourceSpec,
    strengths: ResourceStrengths = _EMPTY_STRENGTHS,
) -> tuple[ResourceRecord | None, ScanIssue | None]:
    if _resource_value_disabled(value):
        return None, None
    safe = _safe_resource_value(value)
    if safe is None:
        return (
            None,
            ScanIssue(
                "resource_value_unsafe_or_invalid",
                node_id=node.node_id,
                input_name=input_name,
            ),
        )
    selected_value, filename = safe
    return (
        ResourceRecord(
            key=f"{node.node_id}:{input_name}",
            role=spec.role,
            kind=spec.kind,
            node_id=node.node_id,
            node_class=node.class_type,
            filename=filename,
            selected_value=selected_value,
            strengths=strengths,
            detection_rule_id=spec.rule_id,
        ),
        None,
    )


def _sage_dynamic_mapping(value: FrozenValue) -> Mapping[str, FrozenValue] | None:
    if not isinstance(value, Mapping):
        return None
    wrapped = value.get("__value__")
    return wrapped if isinstance(wrapped, Mapping) else value


def _sage_flexible_selector_resources(
    node: PromptNode,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    compact = compact_class(node)
    if compact not in {"sageflexibleclipselector", "sagemultiselectorflexibleclip"}:
        return (), ()

    candidates: list[tuple[str, FrozenValue, ResourceRole, ResourceKind]] = []
    if compact == "sagemultiselectorflexibleclip":
        candidates.extend(
            (
                (
                    "unet_name",
                    node.input_value("unet_name"),
                    ResourceRole.BASE_MODEL,
                    ResourceKind.DIFFUSION_MODEL,
                ),
                (
                    "vae_name",
                    node.input_value("vae_name"),
                    ResourceRole.VAE,
                    ResourceKind.VAE,
                ),
            )
        )
    nested = _sage_dynamic_mapping(node.input_value("num_of_clips"))
    if nested is not None:
        candidates.extend(
            (
                f"num_of_clips.{input_name}",
                value,
                ResourceRole.TEXT_ENCODER,
                ResourceKind.CLIP,
            )
            for input_name, value in sorted(nested.items())
            if re.fullmatch(r"clip_name_\d+", input_name)
        )

    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    for input_name, value, role, kind in candidates:
        record, issue = _named_resource_record(
            node,
            input_name=input_name,
            value=value,
            spec=_NamedResourceSpec(
                role,
                kind,
                "sage_flexible_model_selector",
            ),
        )
        if record is not None:
            records.append(record)
        if issue is not None:
            issues.append(issue)
    return tuple(records), tuple(issues)


_SAGE_QUICK_LORA_STACKS = frozenset(
    {
        "sagequicklorastack",
        "sagequickninelorastack",
        "sagequicksixlorastack",
        "sagetriplequicklorastack",
    }
)
_SAGE_NUMBERED_LORA_STACKS = frozenset(
    {
        "sageninelorastack",
        "sagequickninelorastack",
        "sagequicksixlorastack",
        "sagesixlorastack",
        "sagetriplelorastack",
        "sagetriplequicklorastack",
    }
)


def _sage_lora_stack_resources(
    node: PromptNode,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    compact = compact_class(node)
    if compact not in _SAGE_NUMBERED_LORA_STACKS | {
        "sagelorastack",
        "sagequicklorastack",
    }:
        return (), ()

    quick = compact in _SAGE_QUICK_LORA_STACKS
    candidates: list[tuple[str, FrozenValue, ResourceStrengths]] = []
    if compact in {"sagelorastack", "sagequicklorastack"}:
        enabled = _bool_value(node.input_value("enabled"))
        if enabled is False or (compact == "sagelorastack" and enabled is not True):
            return (), ()
        model_strength = _float_value(node.input_value("model_weight"))
        clip_strength = model_strength if quick else _float_value(node.input_value("clip_weight"))
        candidates.append(
            (
                "lora_name",
                node.input_value("lora_name"),
                ResourceStrengths(
                    weight=model_strength,
                    model=model_strength,
                    clip=clip_strength,
                ),
            )
        )
    else:
        for input_name, value in sorted(node.inputs.items()):
            match = re.fullmatch(r"lora_(\d+)_name", input_name)
            if match is None:
                continue
            index = int(match.group(1))
            if _bool_value(node.input_value(f"enabled_{index}")) is False:
                continue
            model_strength = _float_value(node.input_value(f"model_{index}_weight"))
            clip_strength = (
                model_strength if quick else _float_value(node.input_value(f"clip_{index}_weight"))
            )
            candidates.append(
                (
                    input_name,
                    value,
                    ResourceStrengths(
                        weight=model_strength,
                        model=model_strength,
                        clip=clip_strength,
                    ),
                )
            )

    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    for input_name, value, strengths in candidates:
        record, issue = _lora_record(
            node,
            input_name=input_name,
            value=value,
            spec=_LoraRecordSpec(
                strengths,
                "sage_lora_stack",
                allow_zero_strength=True,
            ),
        )
        if record is not None:
            records.append(record)
        if issue is not None:
            issues.append(issue)
    return tuple(records), tuple(issues)


def _embedding_picker_multi_jk_resources(
    node: PromptNode,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    if compact_class(node) != "embeddingpickermultijk":
        return (), ()

    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    for index in range(1, 7):
        if _bool_value(node.input_value(f"embedding_{index}")) is not True:
            continue
        emphasis = _float_value(node.input_value(f"emphasis_{index}"))
        if emphasis is None or emphasis < _JAKE_EMBEDDING_MIN_EMPHASIS:
            continue
        input_name = f"embedding_name_{index}"
        record, issue = _named_resource_record(
            node,
            input_name=input_name,
            value=node.input_value(input_name),
            spec=_NamedResourceSpec(
                ResourceRole.EMBEDDING,
                ResourceKind.EMBEDDING,
                "jake_embedding_picker_multi",
            ),
            strengths=ResourceStrengths(weight=emphasis),
        )
        if record is not None:
            records.append(record)
        if issue is not None:
            issues.append(issue)
    return tuple(records), tuple(issues)


def _active_direct_specs(
    node: PromptNode,
    specs: tuple[ResourceInputSpec, ...],
    active: ActiveGraph | None,
) -> tuple[ResourceInputSpec, ...]:
    if active is None:
        return specs
    compact = compact_class(node)
    outputs = set(active.consumed_output_indexes.get(node.node_id, ()))
    allowed = _allowed_direct_inputs(node, compact, outputs)

    if allowed is None:
        return specs
    return tuple(spec for spec in specs if spec.input_name in allowed)


def _allowed_direct_inputs(
    node: PromptNode,
    compact: str,
    outputs: set[int],
) -> set[str] | None:
    if compact == "a1rcheckpointloader":
        return _a1r_checkpoint_inputs(outputs)
    if compact == "a1rseparatecheckpointloader":
        return _a1r_separate_checkpoint_inputs(node, outputs)
    if compact in {"a1rconditionalcheckpointloader", "a1rdoublecheckpointloader"}:
        return _a1r_double_checkpoint_inputs(node, outputs)
    if compact == "zimagemodelloader" and outputs:
        return _zimage_loader_inputs(outputs)
    return _researched_loader_inputs(node, compact, outputs)


def _researched_loader_inputs(
    node: PromptNode,
    compact: str,
    outputs: set[int],
) -> set[str] | None:
    if compact in {"h4completeloader", "h4universalloader"}:
        return _h4_loader_inputs(node, outputs)
    if compact in {"loadnanchaku", "sumloadadv"}:
        return _apt_loader_inputs(outputs)
    return None


def _a1r_checkpoint_inputs(outputs: set[int]) -> set[str]:
    vae_output = 2
    allowed = {"ckpt_name"}
    if not outputs or vae_output in outputs:
        allowed.add("vae_name")
    return allowed


def _a1r_separate_checkpoint_inputs(
    node: PromptNode,
    outputs: set[int],
) -> set[str]:
    vae_output = 2
    selected = _bool_value(node.input_value("separate_mode"))
    allowed = (
        {"ckpt_name_b"}
        if selected is True
        else ({"ckpt_name_a"} if selected is False else {"ckpt_name_a", "ckpt_name_b"})
    )
    if not outputs or vae_output in outputs:
        allowed.add("vae_name")
    return allowed


def _a1r_double_checkpoint_inputs(
    node: PromptNode,
    outputs: set[int],
) -> set[str]:
    first_outputs = frozenset({0, 1, 2})
    second_outputs = frozenset({3, 4, 5})
    vae_outputs = frozenset({2, 5})
    allowed: set[str] = set()
    if not outputs or outputs.intersection(first_outputs):
        allowed.add("ckpt_name_a")
    if _bool_value(node.input_value("enable_second")) is True and (
        not outputs or outputs.intersection(second_outputs)
    ):
        allowed.add("ckpt_name_b")
    if not outputs or outputs.intersection(vae_outputs):
        allowed.add("vae_name")
    return allowed


def _zimage_loader_inputs(outputs: set[int]) -> set[str]:
    output_inputs = {
        0: "model_name",
        1: "vae_name",
        2: "clip_name",
    }
    return {input_name for output, input_name in output_inputs.items() if output in outputs}


def _h4_loader_inputs(node: PromptNode, outputs: set[int]) -> set[str]:
    if not outputs:
        return {
            "ckpt_name",
            "unet_name",
            "clip_name",
            "vae_name",
            "lora_name",
        }
    model_outputs = outputs.intersection(
        {_MODEL_OUTPUT_INDEX, _CLIP_OUTPUT_INDEX, _VAE_OUTPUT_INDEX}
    )
    if not model_outputs:
        return set()
    mode = node.input_value("load_mode")
    if not isinstance(mode, str):
        return set()
    normalized = mode.strip().casefold()
    allowed: set[str] = set()
    if normalized == "checkpoint (standard)":
        allowed.add("ckpt_name")
    elif normalized == "diffusers (component)":
        if _MODEL_OUTPUT_INDEX in model_outputs:
            allowed.add("unet_name")
        if _CLIP_OUTPUT_INDEX in model_outputs:
            allowed.add("clip_name")
        if _VAE_OUTPUT_INDEX in model_outputs:
            allowed.add("vae_name")
    if model_outputs.intersection({_MODEL_OUTPUT_INDEX, _CLIP_OUTPUT_INDEX}):
        allowed.add("lora_name")
    return allowed


def _apt_loader_inputs(outputs: set[int]) -> set[str]:
    all_inputs = {
        "ckpt_name",
        "unet_name",
        "clip1",
        "clip2",
        "clip3",
        "clip4",
        "vae",
        "lora",
    }
    if not outputs or 0 in outputs:
        return all_inputs
    if 1 in outputs:
        return {"ckpt_name", "unet_name", "lora"}
    return set()


def _power_lora_resources(
    node: PromptNode,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    if "powerloraloader" not in compact_class(node):
        return (), ()
    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    for input_name in sorted(node.inputs):
        value = node.inputs[input_name]
        if not input_name.casefold().startswith("lora_") or not isinstance(
            value,
            Mapping,
        ):
            continue
        entry = value
        enabled = _bool_value(entry.get("on"))
        if enabled is False:
            continue
        if _resource_value_disabled(entry.get("lora")):
            continue
        safe = _safe_resource_value(entry.get("lora"))
        if safe is None:
            issues.append(
                ScanIssue(
                    "resource_value_unsafe_or_invalid",
                    node_id=node.node_id,
                    input_name=input_name,
                )
            )
            continue
        selected_value, filename = safe
        strength = _float_value(entry.get("strength"))
        strength_two = _float_value(entry.get("strengthTwo"))
        if strength == 0 and strength_two in {None, 0}:
            continue
        records.append(
            ResourceRecord(
                key=f"{node.node_id}:{input_name}",
                role=ResourceRole.LORA,
                kind=ResourceKind.LORA,
                node_id=node.node_id,
                node_class=node.class_type,
                filename=filename,
                selected_value=selected_value,
                strengths=ResourceStrengths(
                    weight=strength,
                    model=strength,
                    clip=strength_two,
                ),
                detection_rule_id="rgthree_power_lora",
            )
        )
    return tuple(records), tuple(issues)


def _stack_lora_resources(
    node: PromptNode,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    compact = compact_class(node)
    if compact not in {
        "a1rsixloraloader",
        "a1rsixloraloader2p",
        "a1rsixloraloaderseparate",
        "crlorastack",
        "easylorastack",
        "loraloaderstackrgthree",
        "lorastacker",
        "lorastackered",
        "nunchakufluxlorastack",
        "ttnpipelorastack",
        "wanvideoloraselectmulti",
    }:
        return (), ()
    toggle = _bool_value(node.input_value("toggle"))
    if toggle is False:
        return (), ()
    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    mode = _stack_mode(node)
    for index, input_name, value in _stack_candidates(node, compact):
        switch = _bool_value(node.input_value(f"switch_{index}"))
        if switch is None:
            switch = _bool_value(node.input_value(f"enable_lora_{index}"))
        if switch is False:
            continue
        record, issue = _lora_record(
            node,
            input_name=input_name,
            value=value,
            spec=_LoraRecordSpec(
                _stack_strengths(node, index, input_name, mode),
                "numbered_lora_stack",
            ),
        )
        if record is not None:
            records.append(record)
        if issue is not None:
            issues.append(issue)
    return tuple(records), tuple(issues)


def _stack_mode(node: PromptNode) -> str | None:
    for input_name in ("input_mode", "mode"):
        value = node.input_value(input_name)
        if isinstance(value, str):
            return value.strip().casefold()
    return None


def _stack_count_limit(node: PromptNode) -> int:
    for input_name in ("lora_count", "num_loras"):
        value = node.input_value(input_name)
        if isinstance(value, int) and not isinstance(value, bool):
            return min(max(value, 0), _MAX_STACK_LORAS)
    return _MAX_STACK_LORAS


def _stack_candidates(
    node: PromptNode,
    compact: str,
) -> tuple[tuple[int, str, FrozenValue], ...]:
    candidates: list[tuple[int, str, FrozenValue]] = []
    minimum_index = 0 if compact == "wanvideoloraselectmulti" else 1
    count_limit = _stack_count_limit(node)
    for input_name, value in sorted(node.inputs.items()):
        match = re.fullmatch(
            r"(?:lora_(\d+)|lora_name_(\d+)|lora_(\d+)_name)",
            input_name.casefold(),
        )
        if match is None:
            continue
        index = int(next(group for group in match.groups() if group is not None))
        if minimum_index <= index <= count_limit:
            candidates.append((index, input_name, value))
    return tuple(candidates)


def _stack_strengths(
    node: PromptNode,
    index: int,
    input_name: str,
    mode: str | None,
) -> ResourceStrengths:
    suffix = input_name.rsplit("_", maxsplit=1)[-1]
    if not suffix.isdecimal():
        suffix = str(index)
    simple = _first_float_input(
        node,
        f"strength_{suffix}",
        f"lora_wt_{index}",
        f"lora_strength_{index}",
        f"lora_{index}_strength",
    )
    model_strength = _first_float_input(
        node,
        f"model_str_{index}",
        f"model_strength_{index}",
        f"model_weight_{index}",
        f"lora_{index}_model_strength",
    )
    clip_strength = _first_float_input(
        node,
        f"clip_str_{index}",
        f"clip_strength_{index}",
        f"clip_weight_{index}",
        f"lora_{index}_clip_strength",
    )
    if mode == "simple" or (model_strength is None and clip_strength is None):
        model_strength = simple
        clip_strength = simple
    return ResourceStrengths(
        weight=simple,
        model=model_strength,
        clip=clip_strength,
    )


def _inline_lora_resources(
    node: PromptNode,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    compact = compact_class(node)
    if compact not in {
        "impactwildcardencode",
        "loraloaderloramanager",
        "lorastackerloramanager",
        "powerpromptrgthree",
        "powerpromptsimplergthree",
        "sdxlpowerpromptpositivergthree",
        "sdxlpowerpromptsimplenegativergthree",
        "ttnpipeloader",
        "ttnpipeloadersdxl",
        "ttnpipeloadersdxlv2",
        "ttnpipeloaderv2",
        "wanvideoloraselectfromtextloramanager",
        "wanvideoloraselectloramanager",
    }:
        return (), ()
    entries = _structured_lora_entries(node.input_value("loras"))
    if entries:
        return _structured_lora_resources(node, entries)
    return _text_lora_resources(node)


def _inline_embedding_resources(
    node: PromptNode,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    text_values = tuple(
        value
        for input_name, value in node.inputs.items()
        if input_name.casefold() in _PROMPT_TEXT_INPUTS and isinstance(value, str)
    )
    if not text_values:
        return (), ()

    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    seen: set[str] = set()
    for text in text_values:
        for match in _INLINE_EMBEDDING.finditer(text):
            raw_value = match.group(1)
            identity = raw_value.casefold()
            if identity in seen:
                continue
            seen.add(identity)
            safe = _safe_resource_value(raw_value)
            if safe is None:
                issues.append(
                    ScanIssue(
                        "resource_value_unsafe_or_invalid",
                        node_id=node.node_id,
                        input_name="inline_embedding",
                    )
                )
                continue
            selected_value, filename = safe
            records.append(
                ResourceRecord(
                    key=f"{node.node_id}:inline_embedding_{len(records) + 1}",
                    role=ResourceRole.EMBEDDING,
                    kind=ResourceKind.EMBEDDING,
                    node_id=node.node_id,
                    node_class=node.class_type,
                    filename=filename,
                    selected_value=selected_value,
                    detection_rule_id="explicit_embedding_syntax",
                )
            )
    return tuple(records), tuple(issues)


def _structured_lora_entries(value: FrozenValue) -> tuple[FrozenValue, ...]:
    if isinstance(value, Mapping):
        wrapped = value.get("__value__")
        return wrapped if isinstance(wrapped, tuple) else ()
    return value if isinstance(value, tuple) else ()


def _structured_lora_resources(
    node: PromptNode,
    entries: tuple[FrozenValue, ...],
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    for index, entry in enumerate(entries[:_MAX_STACK_LORAS], start=1):
        if not isinstance(entry, Mapping):
            continue
        enabled = _bool_value(entry.get("active"))
        if enabled is False:
            continue
        model_strength = _float_value(entry.get("strength"))
        clip_strength = _float_value(entry.get("clipStrength"))
        if clip_strength is None:
            clip_strength = model_strength
        record, issue = _lora_record(
            node,
            input_name=f"loras_{index}",
            value=entry.get("name"),
            spec=_LoraRecordSpec(
                ResourceStrengths(
                    weight=model_strength,
                    model=model_strength,
                    clip=clip_strength,
                ),
                "structured_lora_list",
            ),
        )
        if record is not None:
            records.append(record)
        if issue is not None:
            issues.append(issue)
    return tuple(records), tuple(issues)


def _text_lora_resources(
    node: PromptNode,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    text_values = tuple(
        value
        for name in (
            "text",
            "loras",
            "lora_syntax",
            "populated_text",
            "prompt",
            "prompt_g",
            "prompt_l",
            "wildcard_text",
        )
        if isinstance((value := node.input_value(name)), str)
    )
    if not text_values:
        return (), ()
    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    seen: set[tuple[str, float, float]] = set()
    record_index = 0
    for text in text_values:
        for match in _INLINE_LORA.finditer(text):
            model_strength = float(match.group(2))
            clip_strength = float(match.group(3)) if match.group(3) is not None else model_strength
            identity = (match.group(1), model_strength, clip_strength)
            if identity in seen:
                continue
            seen.add(identity)
            record_index += 1
            if record_index > _MAX_STACK_LORAS:
                break
            record, issue = _lora_record(
                node,
                input_name=f"inline_lora_{record_index}",
                value=match.group(1),
                spec=_LoraRecordSpec(
                    ResourceStrengths(
                        weight=model_strength,
                        model=model_strength,
                        clip=clip_strength,
                    ),
                    "inline_lora_syntax",
                ),
            )
            if record is not None:
                records.append(record)
            if issue is not None:
                issues.append(issue)
        if record_index >= _MAX_STACK_LORAS:
            break
    return tuple(records), tuple(issues)


def _indexed_resource_records(
    node: PromptNode,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    compact = compact_class(node)
    if compact not in {
        "crmulticontrolnetstack",
        "crmultiupscalestack",
        "easycontrolnetstack",
    }:
        return (), ()
    if _bool_value(node.input_value("toggle")) is False:
        return (), ()

    if compact == "crmultiupscalestack":
        field_prefix = "upscale_model"
        role = ResourceRole.UPSCALER
        kind = ResourceKind.UPSCALER
        rule_id = "comfyroll_upscale_stack"
        strength_prefixes: tuple[str, ...] = ()
    else:
        field_prefix = "controlnet"
        role = ResourceRole.CONTROLNET
        kind = ResourceKind.CONTROLNET
        rule_id = (
            "easy_controlnet_stack"
            if compact == "easycontrolnetstack"
            else "comfyroll_controlnet_stack"
        )
        strength_prefixes = ("controlnet_strength", "controlnet")

    count = node.input_value("num_controlnet")
    count_limit = (
        min(max(count, 0), _MAX_STACK_LORAS)
        if isinstance(count, int) and not isinstance(count, bool)
        else _MAX_STACK_LORAS
    )
    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    for index in range(1, count_limit + 1):
        input_name = f"{field_prefix}_{index}"
        if input_name not in node.inputs:
            continue
        if _bool_value(node.input_value(f"switch_{index}")) is False:
            continue
        value = node.input_value(input_name)
        if _resource_value_disabled(value):
            continue
        safe = _safe_resource_value(value)
        if safe is None:
            issues.append(
                ScanIssue(
                    "resource_value_unsafe_or_invalid",
                    node_id=node.node_id,
                    input_name=input_name,
                )
            )
            continue
        selected_value, filename = safe
        strength: float | None = None
        for prefix in strength_prefixes:
            strength = _float_value(node.input_value(f"{prefix}_{index}_strength"))
            if strength is None:
                strength = _float_value(node.input_value(f"{prefix}_strength_{index}"))
            if strength is not None:
                break
        records.append(
            ResourceRecord(
                key=f"{node.node_id}:{input_name}",
                role=role,
                kind=kind,
                node_id=node.node_id,
                node_class=node.class_type,
                filename=filename,
                selected_value=selected_value,
                strengths=ResourceStrengths(weight=strength),
                detection_rule_id=rule_id,
            )
        )
    return tuple(records), tuple(issues)


def extract_active_resources(
    index: GraphIndex,
    active: ActiveGraph,
) -> tuple[tuple[ResourceRecord, ...], tuple[ScanIssue, ...]]:
    """Extract high-confidence resource inputs from active nodes only."""

    records: list[ResourceRecord] = []
    issues: list[ScanIssue] = []
    for node_id in sorted(active.node_ids, key=node_sort_key):
        node = index.nodes[node_id]
        direct, direct_issues = _direct_resources(node, index=index, active=active)
        power_loras, power_issues = _power_lora_resources(node)
        stack_loras, stack_issues = _stack_lora_resources(node)
        inline_loras, inline_issues = _inline_lora_resources(node)
        inline_embeddings, embedding_issues = _inline_embedding_resources(node)
        indexed, indexed_issues = _indexed_resource_records(node)
        sage_selectors, sage_selector_issues = _sage_flexible_selector_resources(node)
        sage_loras, sage_lora_issues = _sage_lora_stack_resources(node)
        jake_embeddings, jake_embedding_issues = _embedding_picker_multi_jk_resources(node)
        records.extend(direct)
        records.extend(power_loras)
        records.extend(stack_loras)
        records.extend(inline_loras)
        records.extend(inline_embeddings)
        records.extend(indexed)
        records.extend(sage_selectors)
        records.extend(sage_loras)
        records.extend(jake_embeddings)
        issues.extend(direct_issues)
        issues.extend(power_issues)
        issues.extend(stack_issues)
        issues.extend(inline_issues)
        issues.extend(embedding_issues)
        issues.extend(indexed_issues)
        issues.extend(sage_selector_issues)
        issues.extend(sage_lora_issues)
        issues.extend(jake_embedding_issues)
    return tuple(records), tuple(issues)


__all__ = ["extract_active_resources"]
