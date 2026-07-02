# Release Readiness Report

Version: 0.9.17

Recommendation: ready with caveats.

## Summary

0.9.17 adds the Civitai-style EXIF `UserComment` compatibility layer while preserving the working PNG text/iTXt behavior in default mode.

## Audits Completed

- Codebase/module map: `docs/dev/codebase_audit.md`
- ComfyUI standards audit: `docs/dev/comfyui_standards_audit.md`
- Security/privacy audit: `docs/dev/security_privacy_audit.md`
- PNG metadata audit: `docs/dev/png_metadata_spec_audit.md`
- Sidecar schema audit: `docs/dev/sidecar_schema_audit.md`
- Civitai lookup comparison: `docs/dev/civitai_lookup_comparison.md`
- Civitai upload recognition test plan: `docs/dev/civitai_upload_recognition_test_plan.md`
- Civitai generator EXIF sample notes: `docs/dev/civitai_generator_metadata_sample.md`
- Civitai EXIF compatibility design: `docs/dev/civitai_generator_exif_compatibility_design.md`
- Quality checks: `docs/dev/quality_checks.md`

## Tests And Checks

Latest focused local result during the 0.9.17 implementation pass:

```text
Default Python:
Ran 266 tests
OK (skipped=1)

ComfyUI venv:
Ran 266 tests
OK (skipped=1)
```

Skipped test:

- `test_rejects_symlink_escape_when_supported`: skipped because symlink creation is unavailable in the current Windows test environment.

Quality runner:

```text
[pass] compileall
[pass] unit tests
[pass] JS syntax check
[pass] ruff check
[pass] ruff format --check
[pass] sidecar sample validation
[pass] PNG chunk sample inspection
[pass] import smoke
[pass] ComfyUI venv unit tests
```

## Behavior Preservation

Confirmed by tests and audit:

- `parameters` remains PNG `tEXt`.
- `Software` remains PNG `tEXt`.
- `prompt`, `workflow`, and `civitai` remain PNG `iTXt`.
- PNG `eXIf` / EXIF `UserComment` is added in normal mode.
- `civitai_exif_minimal` defaults to false and is the only mode that omits PNG text/iTXt chunks.
- PNG CRCs remain valid in inspected fixtures.
- A1111/Civitai-style parameters remain parseable.
- Full Unicode prompt data remains in `prompt` iTXt and `parameters_utf8` when needed.
- Civitai manifest remains in `civitai` iTXt.
- Workflow metadata remains in `workflow` iTXt when enabled.
- Civitai lookup remains optional and uses verified SSL.
- Lookup sends hashes/modelVersionId values only.
- Preferred AIR/URL/modelVersionId override remains.
- Advanced manual JSON compatibility remains.
- Sidecar remains strict UTF-8 JSON and validates against JSON Schema when `jsonschema` is installed.
- Sidecar failure does not block image saving.
- IMAGE passthrough remains.
- Terminal output-node behavior remains.

## Cleanup Completed

- Ruff lint/format applied across the repository.
- Stale public docstring wording was cleaned without renaming legacy compatibility functions.
- Optional `dev` dependencies were declared in `pyproject.toml`.
- `.gitignore` now covers generated recognition variant folders and manifests.
- `tools/run_quality_checks.py` was added for local no-network validation.
- Release-readiness tests cover version consistency and tool help entrypoints.

## Known Limitations / Caveats

- `[tool.comfy]` registry metadata is not added because a real `PublisherId` has not been chosen. Do not invent one.
- `nodes.py` still acts as a broad orchestration layer. A deeper service extraction should be 0.10.x work.
- Legacy compatibility wrappers with `phase_one` in function names remain to avoid breaking external imports.
- Civitai upload parser behavior is external and can change. Use the recognition harness before changing resource-emission behavior.
- V3 node schema migration is deferred to 0.10.x because it needs focused UI/manual workflow compatibility testing.

## Deferred Items

- ComfyUI V3 schema migration.
- Helper pin/combine nodes.
- Further sampler formatting niceties.
- Optional XMP/tIME/color chunks.
- C2PA/Content Credentials.
- Deeper Civitai parser recognition research using the controlled upload harness.
- Optional `tool.comfy` registry metadata once publisher identity is known.

## Manual QA Checklist

1. Restart ComfyUI.
2. Hard refresh the browser.
3. Add a fresh Save Image with Civitai Metadata node.
4. Confirm normal fields and tooltips are visible.
5. Confirm Advanced resource JSON is hidden/collapsed by default.
6. Enable Advanced JSON and confirm the modal editor opens, applies, cancels, and preserves values.
7. Queue a normal image save with default lookup off.
8. Confirm pixels save and `images` passthrough can feed another image node.
9. Inspect PNG chunks with `tools/inspect_png_chunks.py`.
10. Upload a test image to Civitai and confirm prompt/settings/resources still parse as before.
11. Enable `write_sidecar_json` and validate the sidecar with `tools/validate_sidecar.py`.
12. For lookup issues, run `tools/diagnose_civitai_lookup_ssl.py` with the ComfyUI Python environment.
