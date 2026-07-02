# Civitai Lookup Comparison and ComfyUI Standards Audit

Date: 2026-07-01

## Sources Reviewed

- ComfyUI Javascript Extensions docs: https://docs.comfy.org/custom-nodes/js/javascript_overview
- ComfyUI backend properties docs: https://docs.comfy.org/custom-nodes/backend/server_overview
- ComfyUI Registry standards: https://docs.comfy.org/registry/standards
- ComfyUI pyproject guidance: https://docs.comfy.org/registry/specifications
- Civitai REST wiki redirect note, confirming the old wiki is deprecated in favor of developer.civitai.com: https://github.com/civitai/civitai/wiki/REST-API-Reference
- `civitai/civitai-comfy-nodes`, cloned read-only to `C:\tmp\civitai-comfy-nodes`
- `X-T-E-R/ComfyUI-EasyCivitai-XTNodes`, cloned read-only to `C:\tmp\ComfyUI-EasyCivitai-XTNodes`

## Adopted Safe Ideas

- Use `WEB_DIRECTORY = "./js"` and `app.registerExtension(...)` for frontend UI behavior.
- Keep advanced JSON as a normal user widget and hide/collapse it in frontend JS instead of moving it to hidden execution context.
- Use explicit `User-Agent` headers for Civitai API requests.
- Keep bounded timeouts for network calls.
- Use `/api/v1/model-versions/{modelVersionId}` for modelVersionId completion.
- Use `/api/v1/model-versions/by-hash/{hash}` for hash identity lookup.
- Treat 429 as rate-limited and retryable.
- Treat 5xx as server-side and retryable.
- Cache successful identities separately from lookup execution.
- Preserve AIR type from API/AIR data rather than blindly lowercasing Civitai model type.
- Accept Civitai URLs as user-facing identity inputs, but keep API requests on `civitai.com`.

## Not Adopted

- Requests/httpx migration: deferred. The current stdlib client now uses a verified certifi-backed context when certifi is available, which is the lowest-risk SSL reliability improvement.
- API token support: not added. Public hash/modelVersion lookup remains token-free. If token support is added later, it must be optional and never written to PNG metadata, sidecars, caches, warnings, logs, or workflows.
- Download/install/model-manager behavior: not adopted. This package remains a save/metadata node.
- Runtime dependency installation: not adopted. ComfyUI standards prohibit subprocess-based pip installs.
- Insecure SSL fallback: not adopted. Verification remains mandatory.
- Long retry loops: not adopted. Pixels-first saving means lookup should be bounded and non-blocking.

## Project Notes

### civitai/civitai-comfy-nodes

Relevant behavior:
- Uses `requests`.
- Uses `https://civitai.com/api/v1/models` and `https://civitai.com/api/v1/model-versions/{version_id}`.
- Sends explicit `User-Agent`.
- Accepts optional bearer tokens for its own orchestration/catalog use.
- Builds AIR/resource metadata from official version/model data.
- Has ComfyUI frontend JS extensions.

Applicability:
- Useful as a behavioral reference for User-Agent, modelVersion lookup, AIR type mapping, and frontend extension conventions.
- Not copied. Its orchestration, auth, download, gallery, and model-selector behavior is out of scope.

### X-T-E-R/ComfyUI-EasyCivitai-XTNodes

Relevant behavior:
- Uses `requests`.
- Stores Civitai API endpoint as `https://civitai.com/api/v1`.
- Parses model URLs and modelVersionId.
- Computes BLAKE3 for local-file lookup.
- Uses `/model-versions/by-hash/{hash}` and `/models/{modelId}`.
- Has download/install/model-loading behavior and token-in-URL download helpers.

Applicability:
- Useful as a behavioral reference that BLAKE3 and by-hash lookup are practical Civitai identity paths.
- Not copied. Download/install, subprocess/aria2, token-in-URL handling, and model-manager behavior are out of scope and not appropriate for this save node.

## ComfyUI Standards Audit

- `NODE_CLASS_MAPPINGS`: present.
- `NODE_DISPLAY_NAME_MAPPINGS`: present.
- `WEB_DIRECTORY`: added at package root and included in `__all__`.
- Frontend JS: added under `js/` and registered with `app.registerExtension`.
- Hidden inputs: limited to ComfyUI execution context (`PROMPT`, `EXTRA_PNGINFO`).
- Advanced JSON: remains a user-editable widget; frontend JS hides/collapses it by default.
- Tooltips: visible node fields include tooltip/help text.
- Security standards: no `eval`, no `exec`, no pickle/YAML/subprocess model install behavior.
- pyproject: version is consistent with package version. Registry `[tool.comfy]` metadata is not filled in yet because publisher/repository metadata is not finalized.
- V3 schema: deferred. Current class-style node schema is stable and already compatible with the working ComfyUI tests. A V3 migration should be evaluated for a later `0.10.x` release because it would touch node registration, docs, and workflow compatibility.

## SSL/Network Audit

- API calls remain HTTPS-only.
- SSL verification is mandatory.
- `certifi` is tried as a verified CA bundle when available.
- System default SSL context is used if certifi is unavailable or certifi cannot validate the active certificate chain.
- Lookup diagnostics now distinguish broad `lookupFailureReason` from detailed `lookupFailureClass`.
- Diagnostics avoid prompts, workflows, images, sidecars, tokens, and local paths.
