# ComfyUI Standards Audit

Version audited: 0.9.17

References:

- Backend custom node properties: https://docs.comfy.org/custom-nodes/backend/server_overview
- Hidden inputs: https://docs.comfy.org/custom-nodes/backend/more_on_inputs
- JavaScript extensions: https://docs.comfy.org/custom-nodes/js/javascript_overview
- Registry pyproject metadata: https://docs.comfy.org/registry/specifications

## Backend Checklist

| Item | Status | Notes |
| --- | --- | --- |
| `NODE_CLASS_MAPPINGS` | Pass | Root and package mappings expose `SaveImageWithCivitaiMetadata`. |
| `NODE_DISPLAY_NAME_MAPPINGS` | Pass | Display name is `Save Image with Civitai Metadata`. |
| `WEB_DIRECTORY = "./js"` | Pass | Exported from root `__init__.py` and included in `__all__`. |
| `INPUT_TYPES` shape | Pass | Uses `required` and `hidden`. No user-editable advanced settings are hidden. |
| Hidden inputs | Pass | Only `PROMPT` and `EXTRA_PNGINFO` are hidden execution context. |
| Manual JSON input | Pass | Remains a normal widget/value for workflow compatibility. |
| Tooltips/help text | Pass | Visible inputs have plain-language tooltip metadata. |
| `RETURN_TYPES` | Pass | `("IMAGE",)` for passthrough. |
| `RETURN_NAMES` | Pass | `("images",)`. |
| `FUNCTION` | Pass | `save_images`. |
| `OUTPUT_NODE` | Pass | `True`, matching save/preview-node execution behavior. |
| UI return payload | Pass | Returns `{"ui": {"images": results}, "result": (images,)}`. |
| Terminal save-node behavior | Pass | Still works as an output node even if passthrough output is unused. |
| Existing workflows | Pass | Backend widget keys are preserved; new `civitai_exif_minimal` input is appended with default `false`. |

## Frontend Checklist

| Item | Status | Notes |
| --- | --- | --- |
| JS location | Pass | `js/civitai_save_node_ui.js`. |
| Registration | Pass | Uses `app.registerExtension`. |
| Defensive widget handling | Pass | Missing widgets and ComfyUI frontend differences are guarded. |
| Network calls | Pass | No `fetch`, `XMLHttpRequest`, or websocket calls in the extension. |
| Debug logging | Pass | `DEBUG = false`; logs are gated. |
| Modal editor | Pass | Scoped overlay, escape/click close, apply/cancel behavior, value survives hide/show. |
| Hidden textarea issue | Pass | Raw advanced JSON widget is collapsed; compact editor button is visible only when enabled. |

## Registry / Packaging

| Item | Status | Notes |
| --- | --- | --- |
| PEP 621 `[project]` metadata | Pass | Name, version, description, readme, Python requirement, license, authors, dependencies, classifiers. |
| Runtime dependencies | Pass | Minimal runtime dependencies: Pillow, numpy, certifi. |
| Dev/optional dependencies | Pass | `jsonschema` and `ruff` are optional `dev` dependencies. |
| `[tool.comfy]` | Deferred | Registry publishing needs a real `PublisherId`. Do not invent one locally. |
| Package data | Pass | Example config JSON is included for packaged installs. |

## V3 Schema / Frontend Migration

Current node UI remains compatible with existing workflows and current widget behavior. A deeper V3 schema migration should be planned for 0.10.x because it may change node definition semantics and needs manual ComfyUI UI regression testing.

## Deviations / Rationale

- `nodes.py` still orchestrates several metadata subsystems. A deeper service-layer extraction is possible, but broad refactoring risks pixels-first behavior and should wait for 0.10.x.
- Standalone tools manipulate `sys.path` so they can run directly from the repository or custom node folder. This is isolated to tools and documented in Ruff per-file ignores.
