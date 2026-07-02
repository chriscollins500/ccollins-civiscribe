# Quality Checks

Use the local runner:

```text
python tools/run_quality_checks.py
```

Optional ComfyUI venv pass:

```text
python tools/run_quality_checks.py --comfy-python C:\Users\Chris\Documents\ComfyUI\.venv\Scripts\python.exe
```

The runner is local-only and does not require internet access. It writes only temporary sample files.

## Checks

- Python `compileall` for `save_node` and `tools`.
- Unit tests via `python -m unittest discover -s tests`.
- JavaScript syntax check via `node --check` when Node is available.
- Ruff lint check when Ruff is installed.
- Ruff format check when Ruff is installed.
- Sidecar sample generation and `tools/validate_sidecar.py`.
- PNG sample generation and `tools/inspect_png_chunks.py`.
- Import smoke for node mappings and package version.
- Optional ComfyUI Python test pass when `--comfy-python` is provided.

## Expected Optional Skips

- Node.js check skips if `node` is unavailable.
- Ruff checks skip if Ruff is unavailable.
- JSON Schema validation inside `validate_sidecar.py` skips if `jsonschema` is unavailable.
- Tests may skip optional BLAKE3/Pillow paths if those packages are not installed.

For release-candidate checks on Chris's current machine, install:

```text
python -m pip install -r requirements.txt jsonschema ruff blake3
C:\Users\Chris\Documents\ComfyUI\.venv\Scripts\python.exe -m pip install jsonschema ruff blake3
```

## Non-goals

The quality runner does not:

- contact Civitai.
- install dependencies.
- modify production files.
- inspect private ComfyUI output folders.
- validate real uploads.
