"""Bounded scalar resolution through current primitive and reroute nodes."""

from __future__ import annotations

import csv
import io
import math
import random
import re
from dataclasses import dataclass

from .active import ActiveGraph
from .classify import compact_class, is_primitive_node
from .graph import GraphIndex, as_link_reference
from .model import FrozenValue, PromptNode, ScalarValue
from .routing import RoutingStatus, selected_upstream_edges

_MAX_SCALAR_REFERENCE_DEPTH = 8
_IDEOGRAM_WIDTH_OUTPUT = 3
_SCALED_OUTPUT_OFFSET = 2
_DIMENSION_PAIR = re.compile(r"(?<!\d)(\d{1,6})\s*[xX\u00d7]\s*(\d{1,6})(?!\d)")
_ASPECT_RATIO = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")
_SCALAR_PASSTHROUGHS: dict[str, tuple[str, frozenset[int]]] = {
    "checkpointnameselector": ("ckpt_name", frozenset({0, 1})),
    "checkpointselectornode": ("ckpt_name", frozenset({0, 1})),
    "crprompttext": ("prompt", frozenset({0})),
    "crtext": ("text", frozenset({0})),
    "diffusionmodelselector": ("model_name", frozenset({0})),
    "diffusionmodelselectornode": ("model_name", frozenset({0, 1})),
    "easyprompt": ("text", frozenset({0})),
    "textbox1": ("text1", frozenset({0})),
    "textbox2": ("text2", frozenset({0})),
    "vaeselectornode": ("vae_name", frozenset({0, 1})),
    "yogurtdiffusionmodelselector": ("diffusion_model", frozenset({0})),
}
_COMFYROLL_DIMENSION_OVERRIDES = {
    ("craspectratiobanners", "Banner - 468x60"): (168, 60),
    ("craspectratiosocialmedia", "LinkedIn Page Cover - 1128x191"): (1584, 396),
}
_COMFYROLL_PRESCALE_CLASSES = frozenset(
    {
        "craspectratio",
        "craspectratiobanners",
        "craspectratioforprint",
        "craspectratiosocialmedia",
    }
)
_ECLIPSE_SAFE_SCALAR_OUTPUTS = {
    3: "width",
    4: "height",
    5: "text_pos",
    6: "text_neg",
    7: "steps",
    8: "cfg",
    9: "sampler_name",
    10: "scheduler",
    11: "seed",
    12: "model_name",
}


def literal_scalar(value: FrozenValue) -> ScalarValue:
    """Return a literal scalar, excluding collection and link values."""

    if as_link_reference(value) is not None:
        return None
    return value if value is None or isinstance(value, (bool, int, float, str)) else None


@dataclass(frozen=True, slots=True)
class _ScalarResolver:
    index: GraphIndex
    active: ActiveGraph
    preferred_input_names: tuple[str, ...]

    def resolve(
        self,
        value: FrozenValue,
        *,
        seen: frozenset[str] = frozenset(),
        depth: int = 0,
    ) -> ScalarValue:
        literal = literal_scalar(value)
        if literal is not None or depth >= _MAX_SCALAR_REFERENCE_DEPTH:
            return literal
        reference = as_link_reference(value)
        node = (
            None
            if (
                reference is None
                or reference.source_node_id in seen
                or not self.active.contains(reference.source_node_id)
            )
            else self.index.node(reference.source_node_id)
        )
        if reference is None or node is None:
            return None
        visited = seen | {reference.source_node_id}
        exact, exact_value = self._exact_output(
            node,
            reference.output_index,
            seen=visited,
            depth=depth,
        )
        if exact or not is_primitive_node(node):
            return exact_value
        candidate_names = tuple(dict.fromkeys((*self.preferred_input_names, "value", *node.inputs)))
        for input_name in candidate_names:
            if input_name not in node.inputs:
                continue
            candidate = self.resolve(
                node.inputs[input_name],
                seen=visited,
                depth=depth + 1,
            )
            if candidate is not None:
                return candidate
        return None

    def _input(
        self,
        node: PromptNode,
        input_name: str,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> ScalarValue:
        if input_name not in node.inputs:
            return None
        return self.resolve(
            node.inputs[input_name],
            seen=seen,
            depth=depth + 1,
        )

    def _optional_string(
        self,
        node: PromptNode,
        input_name: str,
        *,
        seen: frozenset[str],
        depth: int,
        default: str = "",
    ) -> str | None:
        if input_name not in node.inputs:
            return default
        value = self._input(node, input_name, seen=seen, depth=depth)
        return value if isinstance(value, str) else None

    def _exact_output(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> tuple[bool, ScalarValue]:
        compact = compact_class(node)
        exact_output = self._current_comfy_output(
            node,
            compact,
            output_index,
            seen=seen,
            depth=depth,
        )
        if exact_output is None:
            exact_output = self._source_backed_output(
                node,
                compact,
                output_index,
                seen=seen,
                depth=depth,
            )
        if exact_output is not None:
            return exact_output
        if (passthrough := _SCALAR_PASSTHROUGHS.get(compact)) is not None:
            input_name, output_indexes = passthrough
            value = (
                self._input(node, input_name, seen=seen, depth=depth)
                if output_index in output_indexes
                else None
            )
            return True, value
        handlers = {
            "impactstringselector": self._impact_string_selector,
            "selectordeprompts": self._selector_de_prompts,
            "easypromptconcat": self._concatenated_text,
            "crtextconcatenate": self._concatenated_text,
            "stringconcatenate": self._string_concatenate,
            "easypromptreplace": self._replaced_text,
            "crtextreplace": self._replaced_text,
            "crcombineprompt": self._combined_prompt,
            "crmultilinetext": self._multiline_text,
            "resolutionselector": self._resolution_selector,
            "dimensionselectorwithseednode": self._seeded_dimensions,
            "setimagesize": self._size_output,
            "setimagesizewithscale": self._scaled_size_output,
            "craspectratio": self._comfyroll_dimensions,
            "craspectratiobanners": self._comfyroll_dimensions,
            "craspectratioforprint": self._comfyroll_dimensions,
            "craspectratiosocialmedia": self._comfyroll_dimensions,
            "crsd15aspectratio": self._comfyroll_dimensions,
            "crsdxlaspectratio": self._comfyroll_dimensions,
            "crselectisosize": self._comfyroll_dimensions,
        }
        if (handler := handlers.get(compact)) is not None:
            return True, handler(node, output_index, seen=seen, depth=depth)
        if compact in {"cmsdxlresolution", "cmsdxlextendedresolution"}:
            return True, self._parsed_dimension_output(
                node,
                output_index,
                "resolution",
                seen=seen,
                depth=depth,
            )
        if compact == "ideogram4promptbuilderkj":
            value = (
                self._input(
                    node,
                    "width" if output_index == _IDEOGRAM_WIDTH_OUTPUT else "height",
                    seen=seen,
                    depth=depth,
                )
                if output_index in {_IDEOGRAM_WIDTH_OUTPUT, _IDEOGRAM_WIDTH_OUTPUT + 1}
                else None
            )
            return True, value
        return False, None

    def _current_comfy_output(
        self,
        node: PromptNode,
        compact: str,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> tuple[bool, ScalarValue] | None:
        if compact == "comfyswitchnode":
            return True, self._comfy_switch_output(
                node,
                output_index,
                seen=seen,
                depth=depth,
            )
        if compact == "previewany":
            return True, self._preview_any_output(
                node,
                output_index,
                seen=seen,
                depth=depth,
            )
        return None

    def _comfy_switch_output(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> ScalarValue:
        if output_index != 0:
            return None
        edges, decision = selected_upstream_edges(self.index, node)
        if decision is None or decision.status is not RoutingStatus.RESOLVED or len(edges) != 1:
            return None
        return self._input(
            node,
            edges[0].input_name,
            seen=seen,
            depth=depth,
        )

    def _preview_any_output(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> str | None:
        if output_index != 0:
            return None
        value = self._input(node, "source", seen=seen, depth=depth)
        return None if value is None else str(value)

    def _source_backed_output(
        self,
        node: PromptNode,
        compact: str,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> tuple[bool, ScalarValue] | None:
        sage_output = self._sage_output(
            node,
            compact,
            output_index,
            seen=seen,
            depth=depth,
        )
        if sage_output is not None:
            return sage_output
        if compact == "samplerloaderjk":
            field = (
                "sampler"
                if output_index in {0, 1}
                else ("scheduler" if output_index in {2, 3} else None)
            )
            value = self._input(node, field, seen=seen, depth=depth) if field is not None else None
            return True, value
        if compact == "wanwrappersamplerdefaultjk":
            if output_index == 0:
                return True, self._input(
                    node,
                    "scheduler",
                    seen=seen,
                    depth=depth,
                )
            return True, "comfy" if output_index == 1 else None
        if compact == "ioloadimageeclipse":
            field = _ECLIPSE_SAFE_SCALAR_OUTPUTS.get(output_index)
            value = self._input(node, field, seen=seen, depth=depth) if field is not None else None
            return True, value
        return None

    def _sage_output(
        self,
        node: PromptNode,
        compact: str,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> tuple[bool, ScalarValue] | None:
        if compact == "sagesamplerselector":
            value = (
                self._input(node, "sampler_name", seen=seen, depth=depth)
                if output_index == 0
                else None
            )
            return True, value
        if compact == "sageschedulerselector":
            field = {0: "steps", 1: "scheduler_name"}.get(output_index)
            value = self._input(node, field, seen=seen, depth=depth) if field is not None else None
            return True, value
        if compact == "sagetextswitch":
            active = self._input(node, "active", seen=seen, depth=depth)
            if output_index != 0 or not isinstance(active, bool):
                return True, None
            return (
                True,
                self._input(node, "str", seen=seen, depth=depth) if active else "",
            )
        return None

    def _impact_string_selector(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> str | None:
        if output_index != 0:
            return None
        strings = self._optional_string(node, "strings", seen=seen, depth=depth)
        multiline = self._input(node, "multiline", seen=seen, depth=depth)
        selected_index = scalar_int(self._input(node, "select", seen=seen, depth=depth))
        if strings is None or not isinstance(multiline, bool) or selected_index is None:
            return None

        lines = strings.split("\n")
        if not multiline:
            return lines[selected_index % len(lines)]

        blocks: list[str] = []
        current = ""
        for line in lines:
            if line.startswith("#") and current:
                blocks.append(current.strip())
                current = ""
            current += line + "\n"
        blocks.append(current.strip())
        selected = strings if not blocks else blocks[selected_index % len(blocks)]
        return selected[1:] if selected.startswith("#") else selected

    def _selector_de_prompts(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> str | None:
        if output_index != 0:
            return None
        state = self._selector_de_prompts_state(node, seen=seen, depth=depth)
        if state is None:
            return None
        fallback, join_with, mode, active_prompts = state

        if not active_prompts:
            return self._selector_de_prompts_fallback(
                node,
                fallback,
                seen=seen,
                depth=depth,
            )
        if mode.strip().casefold() == "single_only" and len(active_prompts) > 1:
            return None
        if len(active_prompts) == 1:
            return active_prompts[0]
        separators = {
            r"\n\n": "\n\n",
            r"\n": "\n",
            "|": " | ",
            ",": ", ",
        }
        return separators.get(join_with, "\n\n").join(active_prompts)

    def _selector_de_prompts_fallback(
        self,
        node: PromptNode,
        fallback: str,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> str | None:
        if fallback.strip().casefold() != "p1":
            return None
        first = self._optional_string(node, "p1", seen=seen, depth=depth)
        return None if first is None else first.strip()

    def _selector_de_prompts_state(
        self,
        node: PromptNode,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> tuple[str, str, str, list[str]] | None:
        fallback = self._optional_string(node, "fallback", seen=seen, depth=depth)
        join_with = self._optional_string(node, "join_with", seen=seen, depth=depth)
        mode = self._optional_string(node, "mode", seen=seen, depth=depth)
        if fallback is None or join_with is None or mode is None:
            return None
        active_prompts: list[str] = []
        for slot in range(1, 13):
            enabled = self._input(node, f"on{slot}", seen=seen, depth=depth)
            if not isinstance(enabled, bool):
                return None
            if not enabled:
                continue
            text = self._optional_string(node, f"p{slot}", seen=seen, depth=depth)
            if text is None:
                return None
            if stripped := text.strip():
                active_prompts.append(stripped)
        return fallback, join_with, mode, active_prompts

    def _concatenated_text(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> str | None:
        if output_index != 0:
            return None
        first_name = "prompt1" if "prompt1" in node.inputs else "text1"
        second_name = "prompt2" if "prompt2" in node.inputs else "text2"
        first = self._optional_string(node, first_name, seen=seen, depth=depth)
        second = self._optional_string(node, second_name, seen=seen, depth=depth)
        separator = self._optional_string(node, "separator", seen=seen, depth=depth)
        if first is None or second is None or separator is None:
            return None
        return first + separator + second

    def _string_concatenate(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> str | None:
        if output_index != 0:
            return None
        first = self._optional_string(node, "string_a", seen=seen, depth=depth)
        second = self._optional_string(node, "string_b", seen=seen, depth=depth)
        delimiter = self._optional_string(node, "delimiter", seen=seen, depth=depth)
        if first is None or second is None or delimiter is None:
            return None
        return delimiter.join((first, second))

    def _replaced_text(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> str | None:
        if output_index != 0:
            return None
        text_name = "prompt" if "prompt" in node.inputs else "text"
        text = self._optional_string(node, text_name, seen=seen, depth=depth)
        if text is None:
            return None
        for index in range(1, 4):
            find = self._optional_string(node, f"find{index}", seen=seen, depth=depth)
            replacement = self._optional_string(
                node,
                f"replace{index}",
                seen=seen,
                depth=depth,
            )
            if find is None or replacement is None:
                return None
            text = text.replace(find, replacement)
        return text

    def _combined_prompt(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> str | None:
        if output_index != 0:
            return None
        parts = tuple(
            self._optional_string(node, f"part{index}", seen=seen, depth=depth)
            for index in range(1, 5)
        )
        separator = self._optional_string(node, "separator", seen=seen, depth=depth)
        if separator is None or any(part is None for part in parts):
            return None
        return separator.join(part for part in parts if part is not None)

    @staticmethod
    def _csv_lines(text: str, quote: str) -> list[str] | None:
        try:
            return [
                value
                for row in csv.reader(io.StringIO(text), quotechar=quote, strict=True)
                for value in row
            ]
        except csv.Error:
            return None

    @staticmethod
    def _split_quoted_lines(text: str) -> list[str]:
        if text.startswith("'") and text.endswith("'"):
            return [value.strip() for value in text[1:-1].split("', '")]
        if text.startswith('"') and text.endswith('"'):
            return [value.strip() for value in text[1:-1].split('", "')]
        if "," in text and "'" in text and text.count("'") % 2 == 0:
            return [value.strip() for value in text.replace("'", "").split(",")]
        if "," in text and '"' in text and text.count('"') % 2 == 0:
            return [value.strip() for value in text.replace('"', "").split(",")]
        return []

    @staticmethod
    def _plain_lines(text: str, *, remove: bool, chars: str) -> list[str]:
        result: list[str] = []
        for source_line in io.StringIO(text):
            if not source_line.strip() or source_line.strip().startswith("#"):
                continue
            line = source_line.rstrip("\r\n")
            result.append(line.replace(chars, "") if remove else line)
        return result

    def _multiline_text(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> str | None:
        if output_index != 0:
            return None
        text = self._optional_string(node, "text", seen=seen, depth=depth)
        if text is None:
            return None
        convert = self._input(node, "convert_from_csv", seen=seen, depth=depth)
        split = self._input(node, "split_string", seen=seen, depth=depth)
        remove = self._input(node, "remove_chars", seen=seen, depth=depth)
        quote = self._optional_string(
            node,
            "csv_quote_char",
            seen=seen,
            depth=depth,
            default="'",
        )
        chars = self._optional_string(
            node,
            "chars_to_remove",
            seen=seen,
            depth=depth,
        )
        if not isinstance(convert, bool):
            convert = False
        if not isinstance(split, bool):
            split = False
        if not isinstance(remove, bool):
            remove = False
        if quote not in {"'", '"'} or chars is None:
            return None

        text = text.rstrip(",")
        lines: list[str] = []
        if convert:
            converted = self._csv_lines(text, quote)
            if converted is None:
                return None
            lines.extend(converted)
        if split:
            lines.extend(self._split_quoted_lines(text))
        if not convert and not split:
            lines.extend(self._plain_lines(text, remove=remove, chars=chars))
        return "\n".join(lines)

    def _parsed_dimension_output(
        self,
        node: PromptNode,
        output_index: int,
        input_name: str,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> int | None:
        if output_index not in {0, 1}:
            return None
        value = self._input(node, input_name, seen=seen, depth=depth)
        match = _DIMENSION_PAIR.fullmatch(value.strip()) if isinstance(value, str) else None
        return int(match.group(output_index + 1)) if match is not None else None

    def _size_output(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> ScalarValue:
        if output_index not in {0, 1}:
            return None
        return self._input(
            node,
            "width" if output_index == 0 else "height",
            seen=seen,
            depth=depth,
        )

    def _scaled_size_output(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> int | None:
        if output_index not in {0, 1, 2, 3}:
            return None
        width = scalar_int(self._input(node, "width", seen=seen, depth=depth))
        height = scalar_int(self._input(node, "height", seen=seen, depth=depth))
        if width is None or height is None:
            return None
        if output_index < _SCALED_OUTPUT_OFFSET:
            return (width, height)[output_index]
        scale = scalar_float(self._input(node, "scale_by", seen=seen, depth=depth))
        if scale is None:
            return None
        return int((width, height)[output_index - _SCALED_OUTPUT_OFFSET] * scale)

    def _resolution_selector(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> int | None:
        if output_index not in {0, 1}:
            return None
        aspect = self._input(node, "aspect_ratio", seen=seen, depth=depth)
        megapixels = scalar_float(self._input(node, "megapixels", seen=seen, depth=depth))
        multiple = scalar_int(self._input(node, "multiple", seen=seen, depth=depth))
        match = _ASPECT_RATIO.match(aspect) if isinstance(aspect, str) else None
        if (
            match is None
            or megapixels is None
            or megapixels <= 0
            or multiple is None
            or multiple <= 0
        ):
            return None
        ratio_width = float(match.group(1))
        ratio_height = float(match.group(2))
        scale = math.sqrt(megapixels * 1024 * 1024 / (ratio_width * ratio_height))
        width = round(ratio_width * scale / multiple) * multiple
        height = round(ratio_height * scale / multiple) * multiple
        return (width, height)[output_index]

    def _seeded_dimensions(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> int | None:
        if output_index not in {0, 1}:
            return None
        resolution = scalar_int(self._input(node, "resolution", seen=seen, depth=depth))
        minimum = scalar_float(self._input(node, "min_ratio", seen=seen, depth=depth))
        maximum = scalar_float(self._input(node, "max_ratio", seen=seen, depth=depth))
        multiple = scalar_int(self._input(node, "multiples", seen=seen, depth=depth))
        seed = scalar_int(self._input(node, "seed", seen=seen, depth=depth))
        if (
            resolution is None
            or resolution <= 0
            or minimum is None
            or maximum is None
            or minimum <= 0
            or maximum < minimum
            or multiple is None
            or multiple <= 0
            or seed is None
        ):
            return None
        # This reproduces a deterministic sizing node; it is not used for security.
        generator = random.Random(seed)  # noqa: S311
        desired_area = resolution * resolution
        ratio = generator.uniform(minimum, maximum)
        height = int(math.sqrt(desired_area / ratio))
        if height <= 0:
            return None
        width = int(desired_area / height)
        height = round(height / multiple) * multiple
        width = round(width / multiple) * multiple
        if width * height > desired_area:
            if generator.choice((True, False)):
                width -= multiple
            else:
                height -= multiple
        if width <= 0 or height <= 0:
            return None
        return (width, height)[output_index]

    def _comfyroll_dimensions(
        self,
        node: PromptNode,
        output_index: int,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> int | None:
        dimensions: tuple[int, int] | None = None
        if output_index in {0, 1}:
            compact = compact_class(node)
            if compact == "crselectisosize":
                selected = self._input(node, "iso_size", seen=seen, depth=depth)
                matches = _DIMENSION_PAIR.findall(selected) if isinstance(selected, str) else []
                if matches:
                    dimensions = (int(matches[-1][0]), int(matches[-1][1]))
            else:
                dimensions = self._comfyroll_aspect_dimensions(
                    node,
                    compact,
                    seen=seen,
                    depth=depth,
                )
        return dimensions[output_index] if dimensions is not None else None

    def _comfyroll_aspect_dimensions(
        self,
        node: PromptNode,
        compact: str,
        *,
        seen: frozenset[str],
        depth: int,
    ) -> tuple[int, int] | None:
        width = scalar_int(self._input(node, "width", seen=seen, depth=depth))
        height = scalar_int(self._input(node, "height", seen=seen, depth=depth))
        selected = self._input(node, "aspect_ratio", seen=seen, depth=depth)
        if width is None or height is None or not isinstance(selected, str):
            return None
        if selected.strip().casefold() != "custom":
            overridden = _COMFYROLL_DIMENSION_OVERRIDES.get((compact, selected))
            if overridden is not None:
                width, height = overridden
            else:
                matches = _DIMENSION_PAIR.findall(selected)
                if not matches:
                    return None
                width, height = int(matches[-1][0]), int(matches[-1][1])
        swap = self._input(node, "swap_dimensions", seen=seen, depth=depth)
        if isinstance(swap, str) and swap.strip().casefold() == "on":
            width, height = height, width
        if compact not in _COMFYROLL_PRESCALE_CLASSES:
            return width, height
        scale = scalar_float(self._input(node, "prescale_factor", seen=seen, depth=depth))
        return None if scale is None else (int(width * scale), int(height * scale))


def resolve_scalar(
    index: GraphIndex,
    active: ActiveGraph,
    value: FrozenValue,
    *,
    preferred_input_names: tuple[str, ...] = ("value",),
) -> ScalarValue:
    """Resolve a scalar through a bounded chain of active primitive nodes."""

    return _ScalarResolver(index, active, preferred_input_names).resolve(value)


def resolve_node_input(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode | None,
    input_names: tuple[str, ...],
) -> ScalarValue:
    """Return the first resolvable scalar from named node inputs."""

    if node is None:
        return None
    for input_name in input_names:
        if input_name not in node.inputs:
            continue
        value = resolve_scalar(
            index,
            active,
            node.inputs[input_name],
            preferred_input_names=input_names,
        )
        if value is not None:
            return value
    return None


def resolve_node_output(
    index: GraphIndex,
    active: ActiveGraph,
    node: PromptNode | None,
    output_index: int,
) -> ScalarValue:
    """Resolve one deterministic scalar output from an active node."""

    if node is None or output_index < 0:
        return None
    return _ScalarResolver(index, active, ()).resolve((node.node_id, output_index))


def scalar_int(value: ScalarValue) -> int | None:
    """Convert an exact integer-like scalar without accepting booleans."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        signless = stripped.removeprefix("-").removeprefix("+")
        if signless.isdecimal():
            return int(stripped)
    return None


def scalar_float(value: ScalarValue) -> float | None:
    """Convert a finite numeric scalar without accepting booleans."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    if isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError:
            return None
        return result if math.isfinite(result) else None
    return None


def scalar_string(value: ScalarValue) -> str | None:
    """Return a non-empty literal string."""

    if not isinstance(value, str):
        return None
    return value if value else None


__all__ = [
    "literal_scalar",
    "resolve_node_input",
    "resolve_node_output",
    "resolve_scalar",
    "scalar_float",
    "scalar_int",
    "scalar_string",
]
