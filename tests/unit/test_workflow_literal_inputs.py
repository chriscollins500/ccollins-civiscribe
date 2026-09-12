"""Literal structured inputs cannot create graph edges or resource claims."""

from __future__ import annotations

import pytest

from civiscribe.workflow.scan import scan_workflow


@pytest.mark.parametrize(
    "literal",
    [
        {"ordinary_pair": ["1", 0]},
        [["1", 0], ["1", 1]],
        {"__value__": ["1", 0]},
        [1, 0],
    ],
)
def test_literal_pairs_do_not_attribute_a_disconnected_checkpoint(literal: object) -> None:
    prompt = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ghost.safetensors"}},
        "2": {"class_type": "EmptyImage", "inputs": {"settings": literal}},
        "3": {"class_type": "CCollins_CiviScribe_SaveImage", "inputs": {"images": ["2", 0]}},
    }
    result = scan_workflow(prompt, save_node_id="3")
    assert result.active_node_ids == ("2",)
    assert result.resources == ()


def test_flattened_v3_dynamic_input_retains_real_connection() -> None:
    prompt = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "active.safetensors"},
        },
        "2": {"class_type": "CustomImageNode", "inputs": {"option.model": ["1", 0]}},
        "3": {"class_type": "CCollins_CiviScribe_SaveImage", "inputs": {"images": ["2", 0]}},
    }
    result = scan_workflow(prompt, save_node_id="3")
    assert result.active_node_ids == ("1", "2")
    assert [resource.filename for resource in result.resources] == ["active.safetensors"]
