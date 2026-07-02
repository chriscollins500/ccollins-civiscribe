# Changelog

## 0.9.17 - Civitai-style EXIF UserComment layer

- Adds always-on Civitai-style EXIF `UserComment` metadata for PNG output, encoded with the EXIF `UNICODE` prefix and UTF-16BE text.
- Preserves default 0.9.15/0.9.16 PNG compatibility behavior: `parameters` remains PNG `tEXt`, `Software` remains PNG `tEXt`, and `prompt`/`workflow`/`civitai` remain PNG `iTXt` when enabled.
- Adds the single user-facing `civitai_exif_minimal` / `Civitai EXIF Minimal` toggle, default `false`; only this explicit mode omits the PNG text/iTXt chunks and writes EXIF-only metadata.
- Keeps EXIF pixels-first and best-effort: EXIF build/write failures warn but do not block image saving.
- Adds `save_node/metadata/exif_user_comment.py`, EXIF decode support in `tools/inspect_png_chunks.py`, and `tools/analyze_civitai_generator_metadata.py` for local sample analysis.
- Extends the Civitai recognition harness with EXIF-focused variants `U` through `Y`.
- Updates sidecar PNG metadata summaries to report the eXIf/UserComment layer while keeping sidecar schema behavior backward-compatible.
- Preserves lookup defaults, hash/cache behavior, preferred AIR/manual identity behavior, advanced JSON UI behavior, sidecar writing, IMAGE passthrough, terminal save-node behavior, and privacy/path/token redaction.

## 0.9.16 - Production-readiness audit candidate

- Adds production-readiness audit documentation for codebase layout, ComfyUI standards compliance, security/privacy posture, quality checks, and release readiness.
- Adds `tools/run_quality_checks.py` for local compile, unit test, JS syntax, Ruff, sidecar validation, PNG inspection, and import-smoke checks.
- Adds conservative optional dev tooling configuration for Ruff and JSON Schema validation without making those tools runtime requirements.
- Runs Ruff lint/format cleanup across the package while preserving save-node behavior.
- Adds release-readiness tests for version consistency and tool entrypoints.
- Keeps legacy phase-one wrapper names for compatibility but documents them as deprecated compatibility surface.
- Preserves PNG chunk behavior, Civitai/A1111 compatibility, lookup behavior, pixels-first saving, IMAGE passthrough, and terminal save-node behavior.

## 0.9.15 - JSON sidecar standards audit

- Replaces the legacy sidecar top-level shape with a versioned `comfyui-civitai-save-node.sidecar` JSON document.
- Adds `sidecarSchemaVersion: 1.0.0`, non-null generator metadata, RFC3339 UTC `createdAt`, image summary, PNG metadata summary, A1111 diagnostics, resource summaries, lookup diagnostics, safe settings, normalized warnings/errors, and privacy flags.
- Moves the old `schema_version: phase-1` marker under `legacy.schema_version` instead of using it as the primary schema marker.
- Adds `schemas/comfyui-civitai-save-node-sidecar.schema.json` using JSON Schema Draft 2020-12.
- Adds `tools/validate_sidecar.py` for local UTF-8/strict-JSON/required-field/schema validation without network access or file mutation.
- Documents the custom sidecar format and standards basis while keeping sidecars optional diagnostics.
- Preserves PNG chunk behavior, embedded Civitai/A1111 metadata, lookup behavior, hashing behavior, pixels-first saving, terminal save behavior, and IMAGE passthrough output.

## 0.9.14 - PNG metadata standards audit

- Audits PNG metadata behavior against PNG Specification Third Edition, preserving the existing Civitai/A1111-compatible chunk layout.
- Adds a standard Latin-1-safe `Software` tEXt chunk.
- Keeps `parameters` as PNG `tEXt` and `prompt`/`workflow`/`civitai` as uncompressed UTF-8 `iTXt`.
- Records a manifest/sidecar warning when non-Latin text requires a compatibility fallback in the `parameters` tEXt chunk while preserving full Unicode in iTXt metadata.
- Adds stricter PNG text keyword normalization and regression coverage for keyword validity.
- Adds `tools/inspect_png_chunks.py` for chunk order, text keyword, iTXt compression, CRC, and metadata summary inspection.
- Documents deferred Exif, XMP, tIME, color/HDR, and C2PA behavior.
- Preserves Civitai lookup behavior, hashing behavior, pixels-first saving, terminal save behavior, and IMAGE passthrough output.

## 0.9.13 - Advanced JSON editor and image passthrough

- Replaces the fragile embedded advanced JSON textarea with a compact `Advanced resource JSON` / `Edit JSON` control and a frontend-only modal editor.
- Keeps `manual_resource_identities_json` as a hidden backend value carrier so workflow serialization and old workflow compatibility remain unchanged.
- Hides the raw JSON widget in all normal node layouts to avoid detached textarea slivers and preview overlap.
- Adds a right-side `images` IMAGE passthrough output while preserving terminal save-node behavior and saved-image UI reporting.
- Sets a wider default node width for fresh nodes without continuously overriding user resizing.
- Preserves PNG chunk layout, metadata behavior, lookup defaults, hashing behavior, and pixels-first saving.

## 0.9.12 - Advanced JSON frontend cleanup

- Fixes the advanced manual JSON frontend toggle so the hidden JSON widget restores from its original size/draw state instead of staying collapsed after being shown.
- Hides any DOM-backed JSON widget elements while advanced mode is off, preventing detached text-area slivers or blank gaps below the node.
- Clears cached widget layout positions and resizes/marks the node dirty after hide/show so the JSON box appears inside the node body when enabled.
- Shortens visible labels to `Preferred AIR or URL`, `Advanced JSON`, and `Advanced resource JSON` while keeping backend input keys and workflow serialization unchanged.
- Keeps PNG chunk behavior, pixels-first saving, lookup defaults, hashing, metadata generation, and backend manual-identity safety unchanged.

## 0.9.11 - Frontend toggle and Civitai lookup SSL diagnostics

- Adds a ComfyUI frontend extension under `js/` and exports `WEB_DIRECTORY = "./js"` so the advanced manual JSON widget hides/collapses by default and reappears when enabled.
- Keeps advanced JSON backend safety unchanged: disabled means ignored, enabled means strict JSON parsing, malformed JSON never blocks image saving, and old workflows without the toggle remain compatible.
- Uses a verified certifi-backed SSL context for Civitai lookup when certifi is available, with system default trust as the verified fallback.
- Adds safe lookup diagnostics: `lookupFailureClass`, `lookupFailureDetailSanitized`, `lookupClient`, `sslContextSource`, and `apiEndpointKind`.
- Keeps backward-compatible `lookupFailureReason` values while classifying certificate verification, TLS EOF, timeout, DNS, connection, HTTP, rate-limit, server, and malformed JSON failures more precisely.
- Adds `tools/diagnose_civitai_lookup_ssl.py` for by-hash and by-modelVersionId smoke tests from the ComfyUI Python environment.
- Accepts `civitai.red` model URLs as parse-only aliases while keeping API requests on `civitai.com`; URLs without `modelVersionId` warn and do not guess latest versions.
- Adds `js/docs/SaveImageWithCivitaiMetadata.md` and `docs/dev/civitai_lookup_comparison.md`.
- Documents Civitai lookup as a supported core feature, with preferred AIR/URL as an override and identity cache as a resilience layer.
- Preserves PNG chunk layout, pixels-first saving, lookup defaults, hashing defaults, preferred AIR behavior, active graph filtering, and resource lifecycle diagnostics.

## 0.9.10 - Real-output cleanup and advanced JSON UX

- Populates sidecar-only `resourceLifecycle` with empty-safe raw, active, normalized, resolved, unresolved, and final resource stages.
- Keeps lifecycle diagnostics out of embedded PNG metadata while preserving pixels-first image saving if lifecycle construction fails.
- Adds `advanced_manual_identities_enabled`, default off, so stale advanced JSON is ignored unless explicitly enabled or loaded from an older workflow without the toggle.
- Adds plain-language tooltips for visible node fields and keeps `preferred_primary_model_air` as the normal user-facing pin field.
- Emits partial preferred URL/modelVersionId identities with `identityIncomplete: true` and a safe Civitai-facing `checkpoint` type for the primary model when AIR is missing.
- Keeps full AIR preferred identities unchanged, including `air`, `urn`, model IDs, file IDs, and formats where available.
- Separates failed modelVersionId AIR completion into `apiCompletionStatus` and `apiCompletionFailureReason` so pinned identities do not look like failed lookups.
- Preserves PNG chunk layout, lookup defaults, preferred full AIR behavior, active resource filtering, and pixels-first saving.

## 0.9.9 - Preferred URL/cache/lifecycle cleanup

- Extends `preferred_primary_model_air` to accept full AIR, Civitai model URLs with `modelVersionId`, or a plain modelVersionId.
- Completes preferred URL/modelVersionId identities with official AIR only when optional lookup is enabled; lookup remains disabled by default.
- Keeps lookup-disabled URL/modelVersionId input as a safe partial pinned identity without inventing AIR.
- Adds readable resource-cache import/export helpers and CLI scripts using `comfyui-civitai-save-node.resource-cache` JSON.
- Adds sidecar-only `resourceLifecycle` diagnostics with raw, active, normalized, resolved, unresolved, and final resource stages.
- Adds `airType`, `lookupMethod`, and `identityIncomplete` readability fields while preserving existing aliases.
- Documents redaction/privacy behavior for PNG metadata, sidecars, lookup, and cache export.
- Defers sampler formatting and visual helper pin nodes to a later, lower-risk release.

## 0.9.8 - Preferred primary AIR UI

- Adds `preferred_primary_model_air`, a simple optional node input for pinning the active primary model to a trusted Civitai AIR.
- Applies the preferred AIR before advanced manual JSON, local caches, and optional API lookup while still allowing future explicit workflow AIR to win.
- Records `identitySource: preferred_primary_model_air`, `confidence: user_pinned`, and `pinned: true` for preferred AIR resources.
- Preserves preferred AIR when optional Civitai lookup returns an alternate hash match, recording `apiAlternateMatch` and `apiReturnedAir` safely.
- Adds labels, tooltips, and placeholders for `preferred_primary_model_air` and `manual_resource_identities_json` where ComfyUI frontends support them.
- Keeps helper pin nodes out of this low-risk UI patch; advanced JSON remains available for multi-resource pins.
- Preserves PNG chunk behavior, hashing behavior, lookup defaults, pixels-first saving, and existing manual JSON behavior.

## 0.9.7 - Manual pinned identity precedence

- Adds an advanced `manual_resource_identities_json` node input for user-pinned resource identity mappings.
- Applies identity precedence so explicit/manual pinned identities win over local cache and optional API lookup.
- Keeps manual pinned AIR/model IDs authoritative when Civitai hash lookup returns an alternate listing for the same hash.
- Records safe `apiAlternateMatch`, `apiReturnedAir`, `identitySource`, and `confidence` diagnostics without exposing prompts, workflows, images, tokens, or local paths.
- Surfaces manifest aliases such as `urn`, `modelId`, `modelVersionId`, `fileId`, `format`, `identitySource`, `confidence`, and `pinned` while preserving existing parsed AIR data.
- Supports user-pinned local cache records with `identitySource: user_pinned_cache`.
- Preserves lookup disabled by default, pixels-first saving, PNG chunk layout, active graph filtering, persistent hash caching, and filename token expansion.

## 0.9.6 - Real-output status cleanup

- Promotes per-resource lookup status fields to top-level manifest resource entries.
- Carries lookup status, lookup failure reason, status code, retryability, and unresolved reason into `unresolvedResources`.
- Keeps `lookupDebugSummary` intact while making `resources` and `unresolvedResources` self-describing.
- Preserves `metadataStatus: partial` for unresolved resources and package-version generator/schema reporting.
- Documents normal default settings and deeper resolution/testing settings.

## 0.9.5 - Site API diagnostics and status hardening

- Adds sanitized Civitai Site API HTTP classification for 400, 401, 403, 404, 405, 429, and 500+ responses.
- Adds transport classification for timeout, DNS, TLS/SSL, connection, and unknown network failures.
- Parses Civitai error-body shapes with `error` or `code`/`message` fields without exposing prompts, workflows, images, sidecars, tokens, or absolute local paths.
- Adds retryability diagnostics for 429, 5xx, timeout, DNS, SSL, and connection failures while keeping save-time lookup one-pass and non-blocking.
- Expands per-resource lookup diagnostics with `lookupStatus`, `statusCode`, `reason`, `retryable`, `result`, filename basename, role/type, and attempted hash types.
- Adds explicit lookup statuses: `skipped_lookup_disabled`, `skipped_no_hash`, `resolved_by_cache`, `resolved`, `failed`, and `conflict`.
- Marks manifest `metadataStatus` as `partial` when active resources remain unresolved, `minimal` when PNG metadata falls back, and `failed` only when custom metadata building fully collapses.
- Ensures manifest `generator.version` is the package version.
- Treats `EmptySD3LatentImage` and similar latent-image nodes as known scanner nodes.

## 0.9.4 - AIR and hash compatibility

- Expands AIR parsing to the current Civitai form: `urn:air:{ecosystem}:{type}:{source}:{id}[@{version}][+{fileId}][.{format}]`.
- Accepts canonical `urn:air:`, documented `air:`, and bare AIR strings while preserving `rawAir` and emitting canonical `urn:air:...`.
- Adds AIR fields for `canonicalAir`, `id`, `version`, `fileId`, and `format`, with Civitai `id/version` mapped to model IDs only for `source: civitai`.
- Supports AIR resource types including `diffusionmodel`, `unet`, `other`, and OCI `image` without forcing Flux/GGUF resources to checkpoint AIR.
- Prefers API-returned AIR when optional lookup is enabled and can fetch model-version AIR details when the hash response lacks enough trusted AIR data.
- Extends hash schema, cache, and lookup order for AutoV1, AutoV2, AutoV3, SHA256, CRC32, and optional BLAKE3.
- Keeps default `cached_or_fast` hashing cache-first and avoids slow full-file hashes for large uncached files.
- Keeps unresolved resources out of A1111 `Civitai resources`; resolved entries include `air`, `urn`, `fileId`, and `format` when known.
- Adds regression coverage for expanded AIR parsing, API AIR preference, local AIR file IDs, hash modes, cache fields, AutoV3 safetensors metadata, and optional BLAKE3.

## 0.9.3 - Pixels-first hardening and lookup diagnostics

- Keeps image saving ahead of metadata work: scan, hash, lookup, manifest, PNG metadata, and sidecar failures now degrade to sanitized warnings instead of blocking the main image write.
- Adds `hashing_mode` with `cached_only`, `cached_or_fast`, and `full`; the default is `cached_or_fast`.
- Deduplicates Civitai API lookup failures across SHA256 and AutoV2 attempts into one safe warning per resource.
- Adds safe lookup diagnostics and manifest `lookupDebugSummary` without prompts, workflows, images, tokens, local paths, or sidecar data.
- Updates the optional API User-Agent to include the package version.
- Preserves resolved A1111 `Civitai resources` entries with both `air` and `urn` aliases.
- Keeps lookup disabled by default.

## 0.9.2 - Active graph and filename hotfix

- Filters scanned resources to nodes upstream of `SaveImageWithCivitaiMetadata.images`.
- Excludes disconnected loaders and unused upscale branches from A1111 hashes and Civitai resource metadata.
- Keeps active sampler-connected GGUF/UNET/checkpoint primary model selection for `Model`, `Model hash`, and `Hashes["model"]`.
- Adds safe filename token expansion for date, model, seed, sampler, dimensions, and counter tokens.
- Supports both `%date:yyyy-MM-dd%` and legacy sanitized `%date_yyyy-MM-dd%` style date tokens.

## 0.9.1 - Compatibility hotfix

- Writes A1111 `parameters` as classic PNG tEXt when possible, with UTF-8 preserved separately when needed.
- Falls back to final output image dimensions when workflow dimensions are linked or unavailable.
- Emits an empty `Negative prompt:` line in A1111-compatible output when settings are present and no negative text exists.
- Keeps primary `Model`, `Model hash`, and `Hashes["model"]` consistent for sampler-connected UNET/GGUF workflows.
- Adds a persistent local hash cache enabled by default without storing absolute paths.
- Omits unresolved local resources from the parser-facing `Civitai resources` field.

## 0.9.0 - Pre-release

- Added a working ComfyUI save-image node with PNG iTXt metadata.
- Preserved ComfyUI `prompt` and optional `workflow` metadata.
- Added A1111-style `parameters` output.
- Added structured `civitai` manifest output.
- Added workflow graph scanning for common ComfyUI, Flux, GGUF, LoRA, VAE, ControlNet, IPAdapter, upscaler, and text encoder resources.
- Added safe local model hashing with SHA256 and AutoV2 where appropriate.
- Added strict offline local AIR/Civitai identity cache support.
- Added optional Civitai hash lookup, disabled by default.
- Added security hardening for path confinement, redaction, metadata size limits, cache validation, and generated-cache writes.
- Added ComfyUI Python-environment PNG integration verification.
- Hardened resource type classification so video-like or uncertain base model files are not silently labeled as checkpoints.
