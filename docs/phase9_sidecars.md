# Phase 9 Sidecars And Save Diagnostics

Phase 9 adds an optional, additive JSON sidecar to the private CiviScribe V2
candidate. It does not alter PNG, JPEG, or WebP bytes, register the node, or
live-sync V2 into ComfyUI.

## Transaction Order

The sidecar stage begins only after a writer has:

1. encoded a complete temporary image;
2. reopened and verified the image;
3. flushed the temporary file; and
4. published the final image without overwriting an existing output.

Sidecar projection and publication are then best effort. A projection,
serialization, stat, flush, race, or filesystem failure records a sanitized
`sidecar_projection_failed` or `sidecar_write_failed` warning and a failed
sidecar status. It does not remove, retry, rename, or invalidate the committed
image.

## Schema

The packaged Draft 2020-12 schema is:

`v2/civiscribe/schemas/sidecar-v2.schema.json`

Every sidecar contains exactly these top-level sections:

- `schemaName` and `schemaVersion`;
- `artifact`, containing verified committed-file facts;
- `generationRecord`, containing the complete canonical record or `null`;
- `payloads`, containing the sanitized prompt and optional workflow JSON once;
- `projections`, containing the A1111 parameters and optional Civitai manifest;
  and
- `save`, containing the sidecar status, redaction count, and sanitized warning
  codes.

Unknown precision and identity values are explicit `null` values. Every
resource hash object contains `AutoV1`, `AutoV2`, `AutoV3`, `SHA256`, `CRC32`,
and `BLAKE3`, with unavailable values set to `null`.

The Civitai projection refers to raw payloads with JSON pointers under
`#/payloads/`. The full prompt and workflow JSON are not duplicated elsewhere
in the sidecar.

## Artifact Facts

Artifact values are taken from the committed result, not inferred from the
source tensor:

- final filename and sibling sidecar filename;
- safe relative subfolder;
- format and MIME type;
- width, height, and batch index;
- decoded output mode, channels, and alpha presence;
- incoming tensor dtype;
- encoded sample bits and explicit precision-conversion status;
- committed file byte size; and
- the rich, partial, or minimal metadata tier that actually survived.

For example, an RGBA tensor flattened to JPEG is recorded as an RGB artifact
with no alpha. The source tensor dtype remains separately visible.

## Privacy

Prompt and workflow payloads pass through the same bounded recursive sanitizer
used by embedded metadata. Sensitive keys, bearer values, and absolute private
paths are replaced before serialization. Sidecar warnings contain stable codes
and optional batch indexes only.

The sidecar never contains:

- an absolute output or model path;
- an API token or authorization value;
- a username or installation location added by CiviScribe; or
- invented camera, GPS, authorship, provenance, identity, hash, or precision
  facts.

## Storage

Sidecars are strict UTF-8 JSON without a byte-order mark. Serialization uses
one deterministic encoder with sorted keys, compact separators, no Python
representations, and no non-finite numbers.

Publication uses a sibling temporary file, flush, and no-overwrite companion
commit. An existing sidecar wins a race and is never replaced.

## Validation Evidence

`tools/validate_sidecar.py`:

- rejects malformed JSON and duplicate keys;
- validates the packaged Draft 2020-12 schema;
- checks artifact format, MIME type, filename, mode, channel, alpha, and
  generation-image consistency; and
- reports private-path, bearer, and sensitive-value findings with codes that do
  not echo the offending value.

The phase-nine immutable golden fixture pins the exact strict UTF-8 projection
of one complete record. Tests also prove:

- sidecar output is disabled by default;
- PNG, JPEG, and WebP sidecars validate;
- enabling a sidecar does not change image bytes;
- prompt and workflow payload markers occur once;
- privacy redaction is reported without leaking the value;
- rich-to-reduced-to-pixels fallback warnings are retained;
- sidecar projection and write failures preserve the image;
- committed JPEG channel and alpha facts are accurate; and
- the complete suite retains 100% line and branch coverage.

Phase 9 validation uses mocked network transports and performs no real network
calls.

## Next Gate

Phase 10 supplies the native progressive UI, exact preview behavior,
localization, and static accessibility contract. Phase 11 completed public
registration, live ComfyUI and Axe validation, and release packaging.
