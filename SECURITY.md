# Security Notes

This package saves ComfyUI images with human-readable and structured metadata. It treats prompts, workflows, cache files, API responses, filenames, node labels, and metadata as untrusted data.

## Threat Model

Primary risks reviewed:

- path traversal or absolute-path writes outside ComfyUI output directories,
- local model path disclosure through PNG metadata, sidecars, validation output, or generated caches,
- cache poisoning through malformed or conflicting Civitai identity records,
- unsafe parsing or execution of metadata,
- unexpectedly large metadata payloads,
- accidental network disclosure of prompts, workflows, images, sidecars, filenames, or local paths,
- token-like secret leakage in metadata, sidecars, warnings, errors, or generated caches.

## Network Behavior

Civitai lookup is off by default. When `enable_civitai_lookup` is enabled, the node sends only resource hash values to the configured HTTPS Civitai hash lookup endpoint.

It does not send:

- prompts,
- negative prompts,
- workflow JSON,
- image files or image bytes,
- sidecar JSON,
- local paths,
- filenames,
- node labels,
- user metadata.

API responses are parsed as untrusted JSON. A response must include the queried hash in returned file hashes before it can resolve a resource. If Civitai IDs are present but there is not enough trusted data to build a full AIR URN, the IDs may be kept with warnings, but no fake AIR ecosystem is invented.

API token support is not implemented in this phase.

## Local Cache Behavior

The manual cache is `save_node/config/civitai_identity_cache.json`. The optional generated cache is `save_node/config/civitai_identity_cache.generated.json`.

Cache records are accepted only from strict JSON. Filename-only identity is rejected. Malformed hashes are rejected. Conflicting records that map the same hash to different Civitai identities are rejected. Generated cache writes use an atomic replace where the platform supports it.

Cache files must stay under the package config directory unless tests inject a temporary allowed root. Cache output is sanitized and must not contain prompts, workflows, images, sidecars, absolute local paths, or token-like secrets.

## Metadata Safety

Metadata is serialized as deterministic JSON. The package does not use eval, exec, unsafe YAML, pickle, marshal, subprocess, os.system, dynamic import loading, or executable metadata behavior.

Metadata text is sanitized before being written to A1111 parameters, JSON metadata, sidecars, validation output, and PNG text chunks:

- absolute Windows, UNC, and POSIX paths are redacted,
- token-like assignments and sensitive dict keys are redacted,
- null bytes and non-printing control characters are removed,
- very large individual metadata strings are truncated with a marker,
- oversized PNG text chunks are omitted with a metadata marker.

## Dependencies and License Risk

The implementation uses Python standard library modules plus ComfyUI runtime APIs and Pillow PNG writing behavior already expected in ComfyUI image save nodes. No GPL-licensed code was copied into this package during these phases.

No project license file is included yet. Add one before wider distribution so downstream users know their rights and obligations.

## Known Limitations

- Civitai endpoint behavior should be checked against current official docs before release.
- AIR ecosystem/type mapping is conservative and may need expansion as real Civitai responses are observed.
- Symlink escape behavior is tested where the local platform permits symlink creation.
- Metadata size limits are defensive caps; extremely large workflows may be represented by an omission marker rather than embedded in full.
- API token support is intentionally absent.

## Reporting Security Issues

For local development, report security issues in the project tracker or directly to the package maintainer. Include:

- the affected node settings,
- whether Civitai lookup was enabled,
- whether sidecars were enabled,
- a minimal workflow or cache snippet with secrets and private paths removed,
- expected versus observed behavior.
