# Civitai Site API Alignment

## Scope

CiviScribe uses the public Civitai Site API only for optional resource identity
resolution. Lookup is disabled by default. When enabled, the node sends only a
resource hash or a model-version ID needed for that lookup. It does not send
images, prompts, workflows, filenames, local paths, sidecars, or credentials.

The implementation was reviewed against the current official:

- [AIR specification](https://developer.civitai.com/site/guide/air)
- [model-version endpoints](https://developer.civitai.com/site/reference/model-versions)
- [image metadata reference](https://developer.civitai.com/site/reference/images)
- [enum endpoint](https://developer.civitai.com/site/reference/enums)

OAuth, MCP, uploads, generation orchestration, Buzz, downloads, and model
installation are outside CiviScribe's save-path identity contract.

## Hash Lookup Contract

The single-resource endpoint accepts the following identifiers, in CiviScribe's
strongest-to-weakest lookup order:

1. SHA256
2. BLAKE3
3. AutoV3
4. AutoV2
5. CRC32
6. AutoV1

The bulk `POST /api/v1/model-versions/by-hash` endpoint accepts full SHA256
values only. CiviScribe therefore uses bulk results solely to disambiguate a
SHA256 lookup when the direct response does not match the scanned resource
role. AutoV1, AutoV2, AutoV3, CRC32, and BLAKE3 never enter that bulk path.

Local identity mappings retain precedence over API results. Conflicting hash
results remain conflicts; no result is selected by filename.

## Model And File Identity

A model-version response describes a parent Civitai listing. Its `air`,
`modelId`, and version `id` are authoritative for that listing. A response can
also contain multiple `files[]`, each with its own:

- `id`
- `type`
- `primary` status
- format
- hashes

This distinction matters because one version can bundle a checkpoint plus a
VAE, text encoder, workflow, or other auxiliary file. The same auxiliary bytes
can also be reused by many unrelated model versions.

CiviScribe applies these rules:

1. A direct hash result must match the scanned resource role through the
   parent AIR/model type.
2. For SHA256 only, bulk candidates may use an exact matching file's current
   `ModelFileType` as additional role evidence.
3. A unique, role-compatible non-primary file is represented with its exact
   file qualifier, such as `+{fileId}`, in canonical structured identity.
4. Multiple compatible candidates or conflicting file IDs remain unresolved.
5. A parent checkpoint or LoRA discovered only through an auxiliary file is
   not promoted into parser-facing `Civitai resources`.
6. A standalone VAE, text encoder, upscaler, or other compatible AIR can be
   emitted normally when the API identifies that resource directly.

These rules prevent a bundled text encoder or VAE from appearing as a second
checkpoint while preserving useful file-level evidence in the structured
manifest and local identity cache.

`baseModel` is retained as sanitized diagnostic context when the API supplies
it. It is not treated as an identity key, parser-facing resource proof, or a
replacement for AIR, model ID, model-version ID, file ID, or a matching hash.

Each structured resource reports its identity scope:

- `model_version` means the evidence identifies the Civitai model version.
- `exact_file` means the evidence also identifies a non-primary file within
  that version.
- `null` means the identity is incomplete or unavailable.

The same record reports `parserFacing` and a sanitized
`parserExclusionReason`. These fields explain why exact evidence may be kept in
the manifest without being emitted as a misleading A1111 `Civitai resources`
entry.

## Rate Limits

CiviScribe does not sleep or retry inside the save path. If Civitai returns
HTTP 429, the client:

1. parses a valid `Retry-After` delta or HTTP date;
2. falls back to a bounded local default when the header is absent or invalid;
3. starts a thread-safe process-local cooldown; and
4. skips later API requests during that cooldown.

The image save continues. Safe diagnostics expose only the status,
`retryAfterSeconds`, attempted hash types, and sanitized reason. Response
bodies, request identifiers, paths, prompts, workflows, filenames, and tokens
are not retained in diagnostics.

## Current Enum Boundary

`civiscribe.identity.civitai_contract` is the single reviewed normalization
boundary for current `ModelType` and `ModelFileType` values. Known values that
do not map safely to an AIR/resource role remain `unknown`. New API enum values
also remain untrusted until reviewed; the scanner does not guess their meaning.

Run the explicit read-only drift audit with:

```powershell
python tools/audit_civitai_api_contract.py
```

The command performs one anonymous HTTPS GET to
`https://civitai.com/api/v1/enums`, uses the same verified trust-context order
as resource lookup, and emits deterministic JSON. It sends no authorization
header or request body and is not part of image saving or release tests.

An explicit deeper check can validate fields CiviScribe consumes from one
public model-version or by-hash response:

```powershell
python tools/audit_civitai_api_contract.py --model-version-id 2734704
python tools/audit_civitai_api_contract.py --hash 09d005300dd8dcbbd489bb75ada6254145c84c2c9c3d7cc1829e3c5dedcb42ce
```

The supplied identifier is used only in the selected public GET. Reports
contain shape/status findings and counts, never the identifier or raw response
values. These live checks are informational because the remote API is mutable
and may be unavailable.

## Image Metadata Projection

CiviScribe's immutable generation record supplies the parser-facing fields used
by the Site API image metadata model when known, including:

- prompt and negative prompt
- seed
- steps
- sampler and scheduler
- CFG scale or Flux guidance without conflating them
- clip skip
- final image size
- hashes
- resolved Civitai resources

Unavailable fields remain absent or null in structured metadata. Unresolved
resources remain explicit in the manifest and are omitted from the
parser-facing Civitai resource list. AIR, model IDs, and version IDs are never
invented.

Controlled manual upload comparisons are documented in
[`civitai_parser_validation.md`](civitai_parser_validation.md). The comparison
tool is offline and reports only match/missing/different statuses and resource
counts.

## Documentation Drift

The Site API is live and mutable. Generated reference pages and narrative pages
can briefly disagree during an API rollout. CiviScribe treats the authoritative
endpoint behavior and generated model-version schema as the implementation
contract, pins the reviewed enum vocabulary in tests, and uses the drift auditor
to make future changes explicit.
