from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from civiscribe.workflow import GraphLimits, scan_workflow

LONG_PROMPT_LENGTH = 100_000

json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=64),
)
json_value = st.recursive(
    json_scalar,
    lambda children: st.one_of(
        st.lists(children, max_size=8),
        st.dictionaries(st.text(max_size=24), children, max_size=8),
    ),
    max_leaves=32,
)
prompt_like = st.dictionaries(st.text(max_size=24), json_value, max_size=20)


@given(prompt_like)
@settings(max_examples=100, deadline=None)
def test_scanner_is_total_and_deterministic_for_bounded_json_values(prompt: object) -> None:
    limits = GraphLimits(
        max_nodes=20,
        max_inputs_per_node=16,
        max_edges=100,
        max_depth=8,
        max_nested_items=256,
        max_string_chars=256,
    )

    first = scan_workflow(prompt, limits=limits)
    second = scan_workflow(prompt, limits=limits)

    assert first == second
    assert all("\\" not in issue.code and "/" not in issue.code for issue in first.issues)


@given(st.integers(min_value=1, max_value=64))
@settings(max_examples=25, deadline=None)
def test_active_cycle_traversal_is_bounded_by_node_count(node_count: int) -> None:
    prompt: dict[str, dict[str, object]] = {}
    for index in range(1, node_count + 1):
        next_id = str((index % node_count) + 1)
        prompt[str(index)] = {
            "class_type": "Reroute",
            "inputs": {"value": [next_id, 0]},
        }
    prompt["save"] = {
        "class_type": "CCollins_CiviScribe_SaveImage",
        "inputs": {"images": ["1", 0]},
    }

    result = scan_workflow(prompt)

    assert len(result.active_node_ids) == node_count
    assert len(set(result.active_node_ids)) == node_count


def test_long_unicode_prompt_is_preserved_within_explicit_limit() -> None:
    prompt_text = "雪" * LONG_PROMPT_LENGTH
    prompt = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text}},
        "2": {"class_type": "EmptyLatentImage", "inputs": {}},
        "3": {
            "class_type": "KSampler",
            "inputs": {"positive": ["1", 0], "latent_image": ["2", 0]},
        },
        "4": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["3", 0]},
        },
    }

    result = scan_workflow(prompt)

    assert result.prompts.positive.text == prompt_text


def test_duplicate_resource_basenames_keep_distinct_lineage_records() -> None:
    prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "models/base.safetensors"},
        },
        "2": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["1", 0],
                "lora_name": "loras/first/duplicate.safetensors",
            },
        },
        "3": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["2", 0],
                "lora_name": "loras/second/duplicate.safetensors",
            },
        },
        "4": {"class_type": "EmptyLatentImage", "inputs": {}},
        "5": {
            "class_type": "KSampler",
            "inputs": {"model": ["3", 0], "latent_image": ["4", 0]},
        },
        "6": {
            "class_type": "CCollins_CiviScribe_SaveImage",
            "inputs": {"images": ["5", 0]},
        },
    }

    result = scan_workflow(prompt)
    duplicates = [
        resource for resource in result.resources if resource.filename == "duplicate.safetensors"
    ]

    assert [resource.key for resource in duplicates] == ["2:lora_name", "3:lora_name"]
    assert [resource.selected_value for resource in duplicates] == [
        "loras/first/duplicate.safetensors",
        "loras/second/duplicate.safetensors",
    ]
