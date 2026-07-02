# Codebase Audit

Version audited: 0.9.17

## Scope

This audit maps the package after the 0.9.17 EXIF compatibility layer. It focuses on production readiness while preserving default PNG text/iTXt metadata behavior.

## Package Layout

```text
__init__.py                         ComfyUI package entrypoint and WEB_DIRECTORY export
save_node/
  __init__.py                       NODE_CLASS_MAPPINGS / NODE_DISPLAY_NAME_MAPPINGS
  nodes.py                          ComfyUI node class and pixels-first orchestration
  version.py                        single package version constant
  civitai/
    air.py                          AIR and Civitai URL/modelVersionId parsing
    lookup.py                       optional verified-SSL Civitai API lookup
    identity_cache.py               local/generated identity cache parsing and writing
    identity_resolution.py          local cache resolution precedence
    manual_identities.py            preferred AIR/URL and advanced JSON identity pinning
    manifest.py                     structured Civitai manifest builder
    resource_cache_io.py            readable cache import/export format
  comfy/
    workflow_scan.py                workflow graph scanning and active-upstream filtering
    resource_detect.py              resource-like loader extraction helpers
    node_fields.py                  node input/display-name helper extraction
  hashing/
    autov2.py                       AutoV1/AutoV2 helpers
    hashes.py                       hash computation and persistent hash cache
    resolver.py                     model-root constrained file resolution
    resource_identity.py            hash attachment and primary model hash selection
  io/
    paths.py                        output path and filename-token safety
    png_writer.py                   PNG tEXt/iTXt metadata construction
    sidecar.py                      RFC8259 sidecar envelope and JSON writing
  metadata/
    a1111.py                        A1111-style parameters formatter
    exif_user_comment.py            Civitai-style EXIF UserComment construction/decoding
    extract.py                      conservative older extraction helpers
    schema.py                       dataclasses and JSON conversion
    serialize.py                    strict JSON serialization and redaction entrypoint
    validate.py                     validation warnings/errors
  security/
    redaction.py                    path/token/control-character redaction
js/
  civitai_save_node_ui.js           frontend Advanced JSON modal/editor extension
  docs/SaveImageWithCivitaiMetadata.md
tools/
  diagnose_civitai_lookup_ssl.py    safe HTTPS lookup diagnostics
  analyze_civitai_generator_metadata.py
  export_identity_cache.py          readable cache export
  import_identity_cache.py          readable cache import
  inspect_png_chunks.py             PNG chunk/CRC inspector
  inspect_png_metadata.py           saved metadata inspector
  make_civitai_metadata_recognition_variants.py
  validate_sidecar.py
  run_quality_checks.py
schemas/
  comfyui-civitai-save-node-sidecar.schema.json
tests/
  unittest suite covering metadata, lookup, hashing, sidecar, workflow scanning, UI contract, tools
```

## Public Entrypoints

- Root `__init__.py` exports `NODE_CLASS_MAPPINGS`, `NODE_DISPLAY_NAME_MAPPINGS`, and `WEB_DIRECTORY = "./js"`.
- `save_node.__init__` maps `SaveImageWithCivitaiMetadata` to display name `Save Image with Civitai Metadata`.
- `SaveImageWithCivitaiMetadata` has `RETURN_TYPES = ("IMAGE",)`, `RETURN_NAMES = ("images",)`, `FUNCTION = "save_images"`, `OUTPUT_NODE = True`, and a safe UI payload plus passthrough result tuple.

## Dependency Map

High-level flow:

```text
nodes.py
  -> comfy.workflow_scan
  -> hashing.resource_identity / hashing.hashes / hashing.resolver
  -> civitai.manual_identities / identity_cache / identity_resolution / lookup
  -> metadata.a1111 / exif_user_comment / validate / serialize
  -> civitai.manifest
  -> io.png_writer / io.sidecar / io.paths
```

Important boundaries:

- `png_writer.py` and `metadata/exif_user_comment.py` have no network logic.
- `lookup.py` has no prompt/workflow/image upload logic.
- `sidecar.py` has no network logic and writes only optional JSON.
- Frontend JS has no network calls and no metadata-generation authority.

## Generated / Local Files To Exclude

Covered by `.gitignore`:

- `__pycache__/`, `*.pyc`
- `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`
- local `output/`, `temp/`
- generated PNG/image/model files
- `save_node/config/civitai_identity_cache.json`
- `save_node/config/civitai_identity_cache.generated.json`
- `save_node/config/civitai_hash_cache.json`
- `*_civitai_recognition_variants/`
- `recognition_variants_manifest.json`
- `recognition_variants_manifest.csv`

## Dead Or Deferred Items

No confirmed dead production module was removed in this pass.

Legacy compatibility wrappers remain:

- `build_phase_one_parameters`
- `build_phase_one_manifest`
- `validate_phase_one_metadata`

They are unused internally, but removing them could break external imports from earlier pre-release experiments. Defer removal or formal deprecation to 0.10.x.

## Cleanup Findings

- Removed stale "phase-one" wording from public docstrings while retaining compatibility function names.
- Ruff found and fixed unused imports, duplicate imports, unnecessary f-string prefixes, and formatting drift.
- Remaining broad `except Exception` blocks are mostly in pixels-first orchestration, optional diagnostics, or UI-defense paths. They are intentionally scoped around metadata/diagnostic subsystems so pixel saving continues.
- Standalone tools bootstrap `sys.path`; Ruff E402 is narrowly ignored for those scripts.

## Naming And Schema Consistency

- Python internals use snake_case.
- JSON sidecar/schema fields use camelCase.
- ComfyUI widget/backend keys are preserved for workflow compatibility.
- `sidecarSchemaVersion` remains `1.0.0` and is intentionally independent of package `__version__`.
- `schema_version: phase-1` appears only under legacy/deprecated sidecar compatibility or in audit docs/tests.

## Risk Areas To Keep Testing

- Civitai parser behavior can change outside this package. Use the recognition harness before changing resource emission behavior.
- ComfyUI frontend widget APIs can change. The JS extension is defensive, but manual UI QA remains useful.
- Optional Civitai API lookup depends on Python TLS trust configuration. The SSL diagnostic tool remains the first troubleshooting step.
