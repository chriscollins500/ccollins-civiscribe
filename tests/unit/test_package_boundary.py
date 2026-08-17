from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_FILES = (ROOT / "__init__.py", *sorted((ROOT / "civiscribe").rglob("*.py")))
FORBIDDEN_TOP_LEVEL_IMPORTS = {"save_node"}


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.partition(".")[0])
    return imports


def test_runtime_never_imports_prototype_package() -> None:
    violations = {
        str(path.relative_to(ROOT)): sorted(_top_level_imports(path) & FORBIDDEN_TOP_LEVEL_IMPORTS)
        for path in RUNTIME_FILES
        if _top_level_imports(path) & FORBIDDEN_TOP_LEVEL_IMPORTS
    }
    assert violations == {}


def test_root_exports_only_native_v3_entrypoint_contract() -> None:
    source = (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "WEB_DIRECTORY" in source
    assert "comfy_entrypoint" in source
    assert "NODE_CLASS_MAPPINGS" not in source
    assert "NODE_DISPLAY_NAME_MAPPINGS" not in source


def test_compiled_frontend_identity_module_is_present() -> None:
    assert (ROOT / "web" / "runtime" / "civiscribe.js").is_file()
