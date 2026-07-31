from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NODE_SOURCE = ROOT / "civiscribe" / "node.py"


def _constant_strings() -> dict[str, str]:
    tree = ast.parse(NODE_SOURCE.read_text(encoding="utf-8"))
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            constants[target.id] = node.value.value
    return constants


def test_frozen_public_node_identity_matches_product_contract() -> None:
    constants = _constant_strings()
    assert constants["NODE_ID"] == "CCollins_CiviScribe_SaveImage"
    assert constants["NODE_DISPLAY_NAME"] == "CiviScribe - Save Image for Civitai"
    assert constants["NODE_CATEGORY"] == "CCollins/CiviScribe"
