# Save Image with Civitai Metadata

Saves images with Civitai-friendly metadata while preserving standard ComfyUI prompt and workflow metadata.

The node can be used as a terminal save node or chained through its right-side `images` IMAGE passthrough output.

## Recommended normal settings

- `write_sidecar_json`: false
- `strict_mode`: false
- `include_workflow`: true
- `include_civitai_manifest`: true
- `enable_civitai_lookup`: enable for maximum automatic resource resolution; disable temporarily for fast/offline/manual-pinned saves
- `lookup_prefer_sha256`: true
- `lookup_timeout_seconds`: 4
- `lookup_cache_results`: true
- `use_persistent_hash_cache`: true
- `hashing_mode`: cached_or_fast
- `advanced_manual_identities_enabled`: false

## Civitai lookup

Civitai lookup is a supported core feature. When enabled, the node sends only resource hashes or modelVersionId values to Civitai to retrieve official model identity data. It never sends images, prompts, workflows, sidecars, local paths, or tokens.

The node is still pixels-first. If lookup fails because of SSL, timeout, network, API, or rate-limit problems, the image still saves and metadata is marked partial.

## Preferred AIR or URL

Use this field when you want the active primary model to point at a specific Civitai listing.

Best input:

```text
urn:air:flux2:checkpoint:civitai:2432159@2734704
```

Civitai URLs with `modelVersionId` and plain modelVersionId values are accepted, but may remain partial if lookup is disabled or fails.

## Advanced resource JSON

Hidden by default. Enable only for multiple pinned resources, non-primary resources, or unusual workflow debugging. When enabled, use the compact `Edit JSON` control to open the editor. Invalid JSON never blocks image saving.

## Sidecar diagnostics

When `write_sidecar_json` is enabled, the sidecar includes `resourceLifecycle` with raw, active, normalized, resolved, unresolved, and final resource stages.

## SSL troubleshooting

Browser access to Civitai does not prove Python can validate the same TLS chain. Run:

```text
tools/diagnose_civitai_lookup_ssl.py
```

Do not disable SSL verification.

## Privacy and safety

No images, prompts, workflows, sidecars, local paths, or tokens are sent for lookup. Local absolute paths are omitted or redacted from metadata, sidecars, warnings, cache files, and exported cache JSON.
