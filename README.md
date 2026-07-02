# Save Image with Civitai Metadata

Pre-release 0.9.17 ComfyUI custom node for saving PNG images with gold-standard, Civitai-compatible metadata.

## What It Does

`SaveImageWithCivitaiMetadata` is an output node that saves images through ComfyUI's normal output directory system and writes:

- A1111-style `parameters` text.
- ComfyUI API `prompt` JSON.
- ComfyUI `workflow` JSON when enabled.
- Structured `civitai` manifest JSON.
- Civitai-style EXIF `UserComment` metadata.
- Optional sidecar JSON next to the PNG.
- An `IMAGE` passthrough output so the workflow can continue after saving.

The node scans the actual ComfyUI graph for prompts, sampler settings, dimensions, seeds, checkpoints/base models, UNET/diffusion models, LoRAs, VAEs, text encoders, ControlNet/IPAdapter models, upscalers, hashes, AIR URNs, and Civitai identity data where available.

## Installation

Copy this folder into ComfyUI's `custom_nodes` directory:

```text
ComfyUI/custom_nodes/comfyui-civitai-save-node
```

Restart ComfyUI. The node should appear as:

```text
Save Image with Civitai Metadata
```

Python 3.10 or newer is expected. ComfyUI normally provides Pillow and numpy; `requirements.txt` lists them for local import/test use.

## Basic Usage

Use this node in place of a normal save-image output node:

1. Connect an `IMAGE` output to `images`.
2. Set `filename_prefix`.
3. Enable `enable_civitai_lookup` when you want maximum automatic resource resolution from Civitai hashes and modelVersionId values.
4. Enable `write_sidecar_json` if you want a readable JSON file next to each image.

The node can still be used as a terminal save node. If you want to continue the workflow after saving, connect its right-side `images` output to the next image node.

## Node Options

- `filename_prefix`: where to save the image and how to name it. Supports tokens like `%date:yyyy-MM-dd%`, `%date:hhmmss%`, `%model%`, `%seed%`, `%width%`, and `%height%`.
- `write_sidecar_json`: also save a JSON sidecar next to the image. Useful for debugging or checking exactly what metadata was written. The image still saves if the sidecar fails.
- `strict_mode`: debug option. When off, the image saves even if metadata has problems. Recommended: off.
- `include_workflow`: embed the ComfyUI workflow in the image so it can be reloaded later.
- `include_civitai_manifest`: embed structured Civitai-focused metadata, including resources, hashes, lookup status, and warnings.
- `civitai_exif_minimal` / `Civitai EXIF Minimal`: writes only the Civitai-style EXIF metadata layer and omits the extra PNG text/iTXt metadata chunks. Default is off.
- `enable_civitai_lookup`: ask Civitai to identify models from hashes or model version IDs. Sends only hash values or model version IDs, never images, prompts, workflows, or local paths. Enable it for maximum automatic metadata resolution.
- `lookup_prefer_sha256`: when multiple hashes are available, try SHA256 first because it is the strongest match.
- `lookup_timeout_seconds`: how long to wait for Civitai lookup before giving up and saving anyway. Metadata lookup never blocks the image from saving permanently.
- `lookup_cache_results`: remember successful Civitai lookup results so future saves can resolve the same resource without asking Civitai again.
- `use_persistent_hash_cache`: remember model file hashes so large checkpoints, GGUFs, LoRAs, and VAEs do not need to be rehashed every save.
- `hashing_mode`: controls how much model hashing happens during save. `cached_only` is fastest, `cached_or_fast` is recommended, and `full` is slowest but most complete.
- `preferred_primary_model_air` / `Preferred AIR or URL`: optional AIR, Civitai model URL, or model version ID to force the active primary model to use that Civitai listing. Use this first when Civitai identifies a mirror, reupload, quant, or alternate listing.
- `advanced_manual_identities_enabled` / `Advanced JSON`: enables the advanced JSON identity override box. Most users should leave this off and use Preferred AIR or URL instead.
- `manual_resource_identities_json` / `Advanced resource JSON`: advanced optional JSON list of pinned AIR/modelVersionId mappings for multiple resources. Most users should use Preferred AIR or URL. Empty means automatic behavior. Invalid JSON never blocks saving.

## Recommended Normal Settings

- `write_sidecar_json`: `false`
- `strict_mode`: `false`
- `include_workflow`: `true`
- `include_civitai_manifest`: `true`
- `civitai_exif_minimal`: `false`
- `enable_civitai_lookup`: `false`
- `lookup_prefer_sha256`: `true`
- `lookup_timeout_seconds`: `4`
- `lookup_cache_results`: `true`
- `use_persistent_hash_cache`: `true`
- `hashing_mode`: `cached_or_fast`
- `advanced_manual_identities_enabled`: `false`

## Deep Metadata / Debugging Settings

- `write_sidecar_json`: `true`
- `strict_mode`: `false`
- `include_workflow`: `true`
- `include_civitai_manifest`: `true`
- `civitai_exif_minimal`: `false`, unless you are specifically testing EXIF-only exports
- `enable_civitai_lookup`: `true`
- `lookup_prefer_sha256`: `true`
- `lookup_timeout_seconds`: `10` to `30`
- `lookup_cache_results`: `true`
- `use_persistent_hash_cache`: `true`
- `hashing_mode`: `cached_or_fast` or `full`
- `advanced_manual_identities_enabled`: only if needed

Supported filename tokens include `%date:yyyy-MM-dd%`, `%date:hhmmss%`, `%date:HHmmss%`, `%date_yyyy-MM-dd%`, `%date_hhmmss%`, `%seed%`, `%model%`, `%sampler%`, `%width%`, `%height%`, and `%counter%`. Expanded token values are sanitized as filename components, so model names cannot create unintended subfolders.

## Privacy Guarantees

Network lookup is disabled by default.

When lookup is enabled, the node sends only resource hash values to the configured HTTPS hash lookup endpoint. It does not send prompts, negative prompts, workflow JSON, images, sidecars, local paths, filenames, node labels, environment variables, or user metadata.

The node does not upload images, download models, install models, or modify model files.

Metadata and sidecars are sanitized to remove absolute Windows, UNC, and POSIX paths, token-like assignments, sensitive metadata keys, null bytes, and non-printing control characters.

Local absolute paths are not written to PNG metadata. Sidecars, cache files, and readable cache exports omit or redact absolute paths. Comfy-relative model names and basenames may appear. Tokens are never written to metadata, sidecars, warnings, caches, or exported cache JSON.

## Metadata Fields

PNG metadata writes A1111 `parameters` as classic PNG tEXt when possible for older parsers. `prompt`, `workflow`, `civitai`, and full Unicode `parameters_utf8` fallback metadata use UTF-8-capable iTXt chunks when Pillow supports them.

Civitai-style EXIF `UserComment` is always written in normal output. This mirrors Civitai generator exports: the `UserComment` value uses the EXIF `UNICODE` prefix and UTF-16BE text containing prompt/settings plus compact `Civitai resources` and `Civitai metadata` JSON when known.

Expected PNG metadata keys:

- `parameters`
- `Software`
- `prompt`
- `workflow`, when `include_workflow` is enabled
- `civitai`, when `include_civitai_manifest` is enabled
- PNG `eXIf` with EXIF `UserComment`

`civitai_exif_minimal` is opt-in. When it is `false`, the node preserves the normal PNG tEXt/iTXt compatibility layers above and adds EXIF. When it is `true`, the node writes only PNG `eXIf`/EXIF `UserComment` and omits `parameters`, `Software`, `prompt`, `workflow`, and `civitai` PNG text chunks. Minimal mode is useful for clean Civitai-style exports, but it removes ComfyUI reload metadata from the PNG.

The `parameters` block can include:

- positive prompt
- `Negative prompt:` line
- steps
- sampler
- scheduler
- CFG scale
- seed
- size
- model and model hash
- VAE and VAE hash
- denoising strength
- hash map
- Civitai resources, only for resources with resolved Civitai identity data

Resource detection is active-graph based when the API prompt contains `SaveImageWithCivitaiMetadata`: only loader nodes upstream of the node's `images` input are used for A1111 hashes and Civitai resource metadata. Disconnected template loaders and unused branches are ignored.

The `civitai` manifest includes:

- `schemaName`
- `schemaVersion`
- `generator`
- `prompt`
- `generation`
- `resources`
- `unresolvedResources`
- `hashes`
- `workflowRefs`
- `identityCache`
- `metadataStatus`
- `lookupDebugSummary`, when optional lookup was attempted
- `validation`

`metadataStatus` values are `complete`, `partial`, `minimal`, or `failed`. Unresolved active resources make the manifest partial; metadata failures never block pixel saving.

The node follows a pixels-first rule: metadata systems are best-effort. Workflow scanning, hashing, identity cache loading, optional Civitai lookup, manifest writing, PNG metadata writing, and sidecar writing should not prevent the main image from being saved. When custom metadata cannot be built, the image is retried with minimal or no custom metadata.

## PNG Metadata Standards

The node targets PNG Specification Third Edition behavior for text metadata.

- `parameters` is written as PNG `tEXt` with the exact keyword `parameters` for Civitai/A1111 compatibility.
- `prompt`, `workflow`, `civitai`, and `parameters_utf8` are written as UTF-8 `iTXt` metadata.
- Full Unicode prompt data is preserved in `prompt` iTXt even when the compatibility `parameters` tEXt chunk needs a Latin-1 fallback.
- A standard `Software` tEXt chunk is written in normal mode with a concise Latin-1 value such as `ComfyUI; comfyui-civitai-save-node 0.9.17`.
- PNG `eXIf` is written with only EXIF `UserComment`; the node does not write fake camera, lens, GPS, or origin/provenance EXIF tags.
- XMP, `tIME`, and color/HDR chunks are not written by default because they have privacy, provenance, or color-management implications.
- C2PA/Content Credentials is not implemented. It is a signed provenance system, not ordinary PNG text metadata.

Use the local inspection tool to audit saved PNGs:

```text
python tools/inspect_png_chunks.py path/to/image.png
```

The tool prints chunk order, chunk lengths, text keywords, text encoding type, iTXt compression status, CRC status, an EXIF `UserComment` preview, parsed EXIF settings/resources summaries, and CRC status.

For controlled Civitai upload experiments, use:

```text
python tools/make_civitai_metadata_recognition_variants.py path/to/image.png
```

This writes same-pixel PNG variants that isolate A1111 hashes, workflow metadata, the structured `civitai` manifest, explicit `Civitai resources`, EXIF-only metadata, and negative controls. See [docs/dev/civitai_upload_recognition_test_plan.md](docs/dev/civitai_upload_recognition_test_plan.md).

## Tools And Developer Audits

Useful local tools:

- `tools/inspect_png_chunks.py`: inspect PNG chunk types, keywords, positions, and CRCs.
- `tools/inspect_png_metadata.py`: preview saved PNG metadata and privacy scan obvious paths.
- `tools/analyze_civitai_generator_metadata.py`: summarize Civitai generator sample EXIF metadata from images or zip files.
- `tools/validate_sidecar.py`: validate sidecar JSON and schema when `jsonschema` is installed.
- `tools/diagnose_civitai_lookup_ssl.py`: test verified HTTPS lookup from the ComfyUI Python environment.
- `tools/export_identity_cache.py` / `tools/import_identity_cache.py`: review or migrate readable identity cache records.
- `tools/make_civitai_metadata_recognition_variants.py`: create controlled Civitai upload parser variants.
- `tools/run_quality_checks.py`: run local compile, tests, JS, Ruff, sidecar, PNG, and import checks.

Developer audit docs live under `docs/dev/`, including codebase layout, PNG metadata, sidecar schema, ComfyUI standards, security/privacy, Civitai lookup comparison, recognition testing, and quality checks.

## Civitai Lookup

Civitai lookup is a supported core feature. When enabled, the node uses resource hashes or modelVersionId values to request official identity data from Civitai. This can resolve checkpoints, LoRAs, VAEs, upscalers, and other resources without manual entry.

The node is still pixels-first. If lookup fails because of SSL, timeout, network, API, or rate-limit problems, the image still saves. Metadata is marked partial and the sidecar explains what failed.

Preferred AIR or Civitai URL is not a replacement for lookup. It is an override for cases where you want a specific listing, such as a mirror, reupload, quant, or byte-identical alternate resource.

Identity cache is not a replacement for lookup either. It is a resilience layer that stores successful lookups so future saves are faster and less fragile.

If lookup fails, troubleshoot it. Run this from the same Python environment that launches ComfyUI:

```text
python tools/diagnose_civitai_lookup_ssl.py
```

Do not disable SSL verification.

## Offline Identity Cache

Most users do not need to edit cache files or write JSON. For the common case where Civitai lookup finds a valid but non-preferred listing, paste the preferred listing into `preferred_primary_model_air`.

The best input is the full AIR, because it contains the ecosystem, type, source, model ID, and version ID even when lookup is disabled or fails.

Flux.2 example:

```text
urn:air:flux2:checkpoint:civitai:2432159@2734704
```

Equivalent URL-style input can also be used:

```text
https://civitai.com/models/2432159?modelVersionId=2734704
```

Plain modelVersionId input is also accepted:

```text
2734704
```

Use this when the active primary model hash resolves to a mirror, reupload, quant, or alternate listing but you want your image metadata to point at a specific trusted listing, such as preferring an Unsloth listing over a City96 listing for the same effective model.

When lookup is disabled, URL/modelVersionId input is recorded as a partial pinned identity without inventing AIR. If lookup fails, the partial pinned identity is kept and the API completion failure is recorded separately. When lookup is enabled, the node may fetch Civitai model-version details by modelVersionId to retrieve official AIR. It still sends no prompts, workflows, images, sidecars, local paths, filenames, or tokens.

Identity precedence is:

1. explicit workflow/user AIR or modelVersionId
2. `preferred_primary_model_air`
3. user-pinned advanced JSON from `manual_resource_identities_json`
4. user-pinned local identity cache records
5. embedded metadata discovered locally
6. non-pinned local identity cache records
7. optional Civitai API lookup, only when enabled
8. unresolved

Preferred and manual pinned node inputs are authoritative. If optional lookup returns a different AIR for the same hash, the node keeps the pinned AIR and records the alternate API match as sanitized diagnostics.

Advanced `manual_resource_identities_json` is normally disabled. Turn on `advanced_manual_identities_enabled` only when you need multiple pinned resources, want to pin LoRAs, VAEs, upscalers, or text encoders, or are debugging an unusual workflow. When advanced mode is off, stale JSON is ignored. When it is on, invalid JSON is a warning only and never blocks saving.

In the ComfyUI node UI, the raw advanced JSON field is hidden/collapsed by default and preserved only as the backend value carrier. When `Advanced JSON` is enabled, the node shows a compact `Advanced resource JSON` row with an `Edit JSON` button. The button opens a modal editor instead of placing a large textarea inside the node body, which keeps image previews from being covered. If a browser cache still shows the old embedded JSON field, restart ComfyUI and hard-refresh the browser tab; if needed, remove and re-add the node so the frontend extension and labels are rebuilt.

The ComfyUI frontend extension hides/collapses the raw JSON widget by default. It does not clear the value, modify metadata, make network calls, or affect queued execution. Existing workflows that had advanced JSON before the toggle was added remain compatible.

Example advanced JSON value:

```json
[
  {
    "match": {
      "name": "flux2-dev-Q8_0.gguf",
      "AutoV2": "09d005300d",
      "SHA256": "09d005300dd8dcbbd489bb75ada6254145c84c2c9c3d7cc1829e3c5dedcb42ce",
      "role": "base_model",
      "type": "diffusion_model"
    },
    "air": "urn:air:flux2:checkpoint:civitai:2432159@2734704",
    "modelId": 2432159,
    "modelVersionId": 2734704,
    "pinned": true,
    "confidence": "user_pinned",
    "note": "Prefer trusted listing"
  }
]
```

Manual matching uses hashes first in this order: SHA256, BLAKE3, AutoV2, AutoV3, CRC32, AutoV1. Filename basename matching is only used when hash data is unavailable, and role/type can narrow a match. Conflicting equally strong manual entries are ignored with a warning.

Helper pin nodes are intentionally not included in this low-risk patch. The direct preferred AIR field covers the common UI case, and advanced JSON remains available for multi-resource pinning.

Manual identity cache path:

```text
save_node/config/civitai_identity_cache.json
```

Copy `save_node/config/civitai_identity_cache.example.json` or `examples/sample_identity_cache.json` to that path and add trusted records keyed by Civitai-supported hashes such as SHA256, AutoV2, AutoV1, AutoV3, CRC32, or BLAKE3.

Filenames are never sufficient identity proof. Do not guess Civitai IDs from filenames.

Example record:

```json
{
  "air": "urn:air:sdxl:checkpoint:civitai:100000@200000",
  "civitaiModelId": 100000,
  "civitaiModelVersionId": 200000,
  "resourceType": "checkpoint",
  "baseModel": "SDXL",
  "hashes": {
    "SHA256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "AutoV2": "aaaaaaaaaa"
  }
}
```

When a resource resolves through the cache, the full AIR URN appears in both A1111 `Civitai resources` and the structured manifest resource.

AIR parsing accepts the current Civitai form:

```text
urn:air:{ecosystem}:{type}:{source}:{id}[@{version}][+{fileId}][.{format}]
```

Documented `air:` and bare AIR strings are accepted as input, but emitted metadata is normalized to canonical `urn:air:...`. The original value is preserved as `rawAir`; the normalized value is stored as `canonicalAir`. For `source: civitai`, AIR `id` and `version` are mapped to `modelId` and `modelVersionId`. For non-Civitai sources such as `civitai-r2`, `dockerhub`, or `ghcr`, IDs are preserved without pretending they are Civitai model IDs.

## Optional Civitai Lookup

Turn on `enable_civitai_lookup` to resolve still-unresolved hashed resources through Civitai's public hash lookup endpoint.

Lookup order:

1. preferred primary model AIR and advanced manual node input
2. manual local identity cache
3. generated local identity cache
4. optional API hash lookup, only when enabled

If `lookup_cache_results` is enabled, validated identities with full AIR URNs are written to:

```text
save_node/config/civitai_identity_cache.generated.json
```

API responses are treated as untrusted JSON. Returned file hashes must match the queried hash before a resource can be resolved. If the response includes official AIR, that AIR is validated and used as the source of truth. If the hash response lacks AIR and lookup is enabled, the node may fetch model-version details by modelVersionId to retrieve official AIR. If there is not enough trusted data to build a full AIR URN, Civitai IDs may be preserved with warnings, but no fake AIR is invented.

Lookup diagnostics are sanitized. They can include filename basenames, role/type, attempted hash types, lookup status, result, HTTP status, retryability, timeout, malformed JSON, hash mismatch, missing model IDs, and type mismatch. They never include prompts, workflows, image bytes, sidecars, tokens, local absolute paths, or environment data.

HTTP and transport failures are classified without retries during image save. Statuses such as `bad_request`, `unauthorized`, `forbidden`, `not_found`, `method_not_allowed`, `rate_limited`, `server_error`, `timeout`, `dns_error`, `ssl_error`, `connection_error`, `malformed_json`, and `network_error` are warnings only. `rate_limited`, `server_error`, timeout, DNS, SSL, and connection failures are marked retryable for later repair workflows.

## Readable Identity Cache Export/Import

The node's normal local identity cache remains:

```text
save_node/config/civitai_identity_cache.json
```

For review, backup, or handoff, use readable JSON helpers:

```text
python tools/export_identity_cache.py --output civitai-save-node-resource-cache.json
python tools/import_identity_cache.py --input civitai-save-node-resource-cache.json
```

The readable export format is `comfyui-civitai-save-node.resource-cache`. Exports include AIR, model IDs, version IDs, file IDs/formats when known, resource type, hashes, aliases, identity source, confidence, pinned/locked flags, notes, and source URL when user-supplied. Exports are sanitized and do not contain prompts, workflows, images, tokens, or absolute local paths.

Imports use strict JSON only. Malformed imports are reported and do not affect image saving. Conflicting imports do not overwrite existing pinned or locked cache entries.

## Resource Lifecycle Sidecars

When `write_sidecar_json` is enabled, sidecars include a `resourceLifecycle` section for debugging metadata without changing PNG metadata behavior:

- `rawResourcesFound`: resource-like nodes detected before active graph filtering.
- `activeResources`: resources connected to the saved image path.
- `normalizedResources`: active resources after local normalization/hashing.
- `resolvedResources`: resources with resolved or pinned identity.
- `unresolvedResources`: active resources still unresolved, with reasons/status.
- `finalResources`: resolved resources emitted to A1111 `Civitai resources`/manifest identity fields.

The lifecycle also includes `finalA1111Parameters`, `lookupDebugSummary`, warnings, and `metadataStatus`. It is sidecar-only and sanitized.

## JSON Sidecar Format

Sidecars are optional diagnostics. The embedded PNG metadata remains the primary A1111/Civitai compatibility path, and a sidecar failure never blocks the image from saving.

Sidecars are written as UTF-8 `application/json`-style files using strict RFC 8259 JSON: no comments, no trailing commas, no `NaN`, no `Infinity`, deterministic key order, 2-space indentation, and a newline at EOF. The current sidecar format marker is:

```json
{
  "sidecarFormat": "comfyui-civitai-save-node.sidecar",
  "sidecarSchemaVersion": "1.0.0"
}
```

The sidecar includes:

- `generator`: non-null node/package/version information.
- `createdAt`: an RFC 3339 UTC timestamp ending in `Z`.
- `image`: PNG filename, format, dimensions, and mode, with no absolute path.
- `pngMetadata`: a summary of expected PNG chunks, not another copy of chunk payloads.
- `a1111`: the final diagnostic `parameters` string and Unicode fallback status.
- `civitai`: the same structured manifest written to the PNG `civitai` iTXt chunk when enabled.
- `resources` and `resourceLifecycle`: concise resource summary plus sidecar-only diagnostic lifecycle.
- `lookupDiagnostics`: safe lookup status when lookup was attempted or summarized.
- `settings`: safe node settings and a count-only manual identity summary.
- `warnings`, `errors`, and `privacy`: sanitized status fields.

The schema file is:

```text
schemas/comfyui-civitai-save-node-sidecar.schema.json
```

It uses JSON Schema Draft 2020-12. Validate a sidecar locally with:

```text
python tools/validate_sidecar.py path/to/image.json
```

Validation is local only and does not contact Civitai. If the optional `jsonschema` package is unavailable, the tool still checks UTF-8, strict JSON parsing, required fields, and the sidecar format marker, then skips schema validation cleanly.

Old `schema_version: phase-1` output is not used as the primary schema marker anymore. New sidecars keep that historical value only under `legacy.schema_version`.

## SSL Troubleshooting

Browser access to Civitai does not prove Python lookup will work. ComfyUI's Python environment must also have a trusted TLS certificate chain.

The node uses verified SSL only. It tries certifi's CA bundle when available and can fall back to the verified system default trust store if certifi cannot validate the active certificate chain. It never disables hostname checking or certificate verification.

Run:

```text
python tools/diagnose_civitai_lookup_ssl.py
```

Check both endpoint shapes:

- `/api/v1/model-versions/by-hash/{hash}`
- `/api/v1/model-versions/{modelVersionId}`

Sidecar lookup diagnostics may include:

- `lookupFailureReason`
- `lookupFailureClass`
- `lookupFailureDetailSanitized`
- `lookupClient`
- `sslContextSource`
- `apiEndpointKind`
- `lookupRetryable`

If failures are certificate-related, install or update `certifi` in the ComfyUI Python environment. If failures mention a proxy, antivirus, or intercepted certificate chain, fix the Python trust store instead of disabling SSL verification.

## Frontend Refresh Note

Python/backend changes require restarting ComfyUI. Frontend JavaScript changes may require a browser hard refresh or cache clear.

If the Advanced resource JSON field still appears after updating while `Advanced JSON` is off:

1. Restart ComfyUI.
2. Hard refresh the browser tab.
3. Add a fresh Save Image with Civitai Metadata node.

Manual QA checklist:

1. Restart ComfyUI.
2. Hard refresh browser.
3. Add Save Image with Civitai Metadata node.
4. Confirm Advanced resource JSON is hidden/collapsed by default.
5. Enable Advanced JSON.
6. Confirm a compact Advanced resource JSON / Edit JSON control appears inside the node.
7. Open the editor, enter valid JSON, and apply.
8. Disable advanced toggle.
9. Confirm the compact control hides and the node shrinks.
10. Re-enable toggle.
11. Confirm JSON value survived in the editor.
12. Queue a save.
13. Confirm pixels save.
14. Confirm the right-side `images` output can feed another image node.
15. Confirm PNG chunk layout remains `parameters` tEXt and `prompt`/`workflow`/`civitai` iTXt.

## Persistent Hash Cache

`use_persistent_hash_cache` is enabled by default to avoid re-hashing large local model files on every save. `hashing_mode` defaults to `cached_or_fast`, so cached hashes are reused first and expensive uncached hashing is avoided unless `full` is selected. The cache is stored at:

```text
save_node/config/civitai_hash_cache.json
```

The cache stores only safe model category, Comfy-relative selected value, file size, modified time, known hashes, and hash timestamp. Supported hash fields are AutoV1, AutoV2, AutoV3, SHA256, CRC32, and BLAKE3 when available. It does not store prompts, workflows, images, sidecars, tokens, or absolute local paths. Entries automatically miss when the file size or modified time changes.

Hashing mode behavior:

- `cached_only`: reads no model files for hashing during save; uses existing cache and identity data only.
- `cached_or_fast`: uses cache first, then cheap/limited hash work such as AutoV1 and safetensors AutoV3 metadata; large uncached files are not full-hashed in the critical save path.
- `full`: computes AutoV1, safetensors AutoV3 when present, SHA256, derived AutoV2, CRC32, and optional BLAKE3 when the Python package is installed.

## Example A1111 Parameters

```text
example positive prompt
Negative prompt: example negative prompt
Steps: 20, Sampler: euler, Schedule type: normal, CFG scale: 7, Seed: 12345, Size: 768x768, Model: example-checkpoint.safetensors, Model hash: aaaaaaaaaa, Hashes: {"Model":"aaaaaaaaaa","model":"aaaaaaaaaa"}, Civitai resources: [{"air":"urn:air:sdxl:checkpoint:civitai:100000@200000","modelId":100000,"modelVersionId":200000,"type":"checkpoint","urn":"urn:air:sdxl:checkpoint:civitai:100000@200000"}]
```

## Example Manifest Resource

```json
{
  "role": "checkpoint",
  "type": "checkpoint",
  "filename": "example-checkpoint.safetensors",
  "rawAir": "urn:air:sdxl:checkpoint:civitai:100000@200000",
  "canonicalAir": "urn:air:sdxl:checkpoint:civitai:100000@200000",
  "urn": "urn:air:sdxl:checkpoint:civitai:100000@200000",
  "modelId": 100000,
  "modelVersionId": 200000,
  "civitaiModelId": 100000,
  "civitaiModelVersionId": 200000,
  "identitySource": "local_cache",
  "confidence": "high",
  "resolutionSource": "local_identity_cache",
  "resolved": true
}
```

See `examples/sample_civitai_manifest.json` for a complete synthetic manifest.

## Verifying Metadata

Use the included helper:

```text
python tools/inspect_png_metadata.py path/to/image.png
```

Or inspect with Pillow:

```python
from PIL import Image
import json

with Image.open("image.png") as image:
    print(image.info.keys())
    print(image.info["parameters"])
    print(json.loads(image.info["civitai"])["schemaName"])
```

## Manual ComfyUI UI Queue Test

A final manual UI test should be run before public release:

1. Restart ComfyUI after installing the node.
2. Build a minimal graph:
   - `CheckpointLoaderSimple`
   - positive `CLIPTextEncode`
   - negative `CLIPTextEncode`
   - `EmptyLatentImage`
   - `KSampler`
   - `VAEDecode`
   - `Save Image with Civitai Metadata`
3. Set `write_sidecar_json`, `include_workflow`, and `include_civitai_manifest` to true.
4. Leave `enable_civitai_lookup` false for the first run.
5. Queue one image.
6. Inspect the PNG with `tools/inspect_png_metadata.py`.
7. Confirm metadata keys include `parameters`, `prompt`, `workflow`, and `civitai`.
8. Confirm sidecar JSON exists.
9. Confirm there are no absolute local paths or private values in the PNG metadata or sidecar.

Successful metadata should show the prompt text, sampler settings, dimensions, hashes, resources, and honest unresolved-resource reporting when no identity cache entry exists.

## Compatibility Notes

- `parameters` is intended to be readable by common A1111-style metadata parsers.
- `prompt` and `workflow` preserve ComfyUI-style metadata for ComfyUI readers.
- `civitai` is structured JSON for Civitai-compatible resource manifests.
- Resource role/type classification is conservative. For example, video-like files or uncertain base-model containers are not silently labeled as Civitai checkpoint AIR resources.
- Civitai upload behavior has been manually verified with real PNG uploads during pre-release testing.

## Troubleshooting

- Missing `workflow`: enable `include_workflow` and ensure ComfyUI provided workflow metadata.
- No resolved Civitai IDs: add a trusted local identity cache record or enable optional lookup.
- Resource remains unresolved: check that the local model file was found under approved ComfyUI model roots and that its hash matches the cache record.
- Strict mode reports errors: inspect validation errors in the sidecar or metadata, but image saving still continues.
- Optional lookup fails: confirm network access, HTTPS base URL, and timeout settings. The node remains fully functional offline.

## Security

See `SECURITY.md` for the threat model, network disclosure rules, cache behavior, dependency/license notes, known limitations, and local security reporting guidance.

## Known Limitations

- A true full UI queue diffusion run still needs final manual confirmation on the target ComfyUI install.
- Civitai endpoint behavior should be checked against current official docs before public release.
- AIR ecosystem/type mapping is intentionally conservative.
- API token support is intentionally absent.
- Some custom node classes may require scanner fixtures as they are encountered.
- Visual helper pin nodes and optional sampler/scheduler merge formatting are deferred to a later release.

## Development

Run tests from this folder:

```text
python -m unittest discover
```

On Windows, one symlink escape test may be skipped if symlink creation is unavailable.
