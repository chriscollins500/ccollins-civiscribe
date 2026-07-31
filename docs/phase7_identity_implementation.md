# Phase 7 Identity Implementation

Phase 7 adds local resource identity enrichment to the private CiviScribe V2
candidate. It does not register a node, alter the accepted PNG carrier layout,
or make network access part of the default save path.

## Runtime Flow

For every active resource selected by the workflow scanner:

1. resolve the exact selected value beneath role-approved ComfyUI model roots;
2. consult the persistent hash cache;
3. compute only hashes permitted by the selected hashing mode;
4. apply explicit per-resource manual identity;
5. apply preferred primary identity;
6. validate any workflow-supplied identity;
7. consult the local identity cache;
8. optionally query Civitai when lookup is explicitly enabled;
9. finalize resolved, partial, unresolved, or conflict status; and
10. project the resulting shared resource record into both A1111 and structured
    Civitai metadata.

Lower-precedence identity may fill missing compatible fields. It cannot replace
or silently contradict a higher-precedence identity.

## Approved File Boundary

The model locator derives roots from current ComfyUI `folder_paths` categories.
It accepts only exact scanner-selected relative values and role-appropriate
categories. It rejects:

- absolute or drive-qualified paths;
- traversal, empty, dot, colon, and control-character segments;
- missing or non-file targets;
- configured roots that cannot be resolved; and
- resolved targets, including symlinks, that escape their approved root.

Resolved filesystem paths exist only inside the adapter and hashing boundary.
They are never written to projections, diagnostics, or caches.

## Hashing Modes

`cached_only`

- reads no model bytes after a cache miss;
- records a nonfatal skipped status.

`cached_or_fast`

- checks the persistent cache first;
- computes only the weak compatibility AutoV1 slice on a cache miss;
- records that full hashing was deferred.

`full`

- checks the persistent cache first;
- performs one bounded file pass;
- computes full SHA-256 and derives AutoV2;
- computes AutoV1 from the same pass; and
- computes AutoV3 from the safetensors tensor payload when a valid bounded
  header identifies that payload.

The file is statted before and after hashing. A changed file invalidates the
result. Hash failures remain warnings and never block image publication.

## Persistent Stores

Hash and identity data use separate versioned JSON stores over one bounded,
locked, atomic transaction primitive.

Hash cache identity consists of:

- safe model category;
- Comfy-relative selected value;
- file size; and
- nanosecond modification time.

Identity cache entries contain validated hashes and identity facts. Neither
store accepts absolute paths, non-finite numbers, oversized/deep values, or
secret-bearing keys. Corrupt, oversized, contended, and unwritable stores are
ignored or reported through sanitized issues without failing the save.

## AIR And Explicit Identity

The AIR parser:

- accepts canonical `urn:air:`, documented `air:`, and documented bare forms;
- preserves the exact raw value;
- emits a normalized canonical `urn:air:` value;
- parses ecosystem, type, source, ID, version, file ID, and format;
- maps numeric Civitai IDs only when the AIR source is `civitai`; and
- returns sanitized issues instead of raising for malformed input.

Manual mappings can select resources by stable resource key, node ID, safe
filename, safe selected value, or validated hash. Equal-strength conflicting
mappings produce a conflict rather than an arbitrary winner. Preferred primary
identity accepts a full AIR, approved Civitai model URL with one version ID, or
a positive model-version ID.

## Optional Civitai Lookup

Lookup is disabled by default. When enabled, the HTTPX client:

- permits only verified HTTPS requests to the configured Civitai API base;
- uses system trust first, then optional truststore and certifi contexts;
- requires hostname verification and TLS 1.2 or newer;
- sends GET requests containing only a validated hash or model-version ID;
- sends a normal versioned User-Agent and no authentication header;
- rejects redirects;
- bounds timeout and streamed response size;
- validates response schema, matching file hash, resource type, IDs, and AIR;
- prefers official API-returned AIR;
- rejects conflicts across hash attempts; and
- sanitizes HTTP, network, DNS, proxy, timeout, TLS, JSON, and response-shape
  failures.

Tests use mocked HTTP transports. Phase 7 validation performs no real network
calls.

## Pixels First

Identity enrichment runs before metadata projection, but it is not a
prerequisite for saving. Locator, hash, cache, manual parsing, AIR, and API
exceptions are converted into safe issues. The save transaction still attempts:

1. rich compatibility metadata;
2. reduced parser-compatible metadata;
3. pixels only; and
4. the safe root-level output fallback.

Only failure to publish pixels to every valid output candidate can fail the save.
