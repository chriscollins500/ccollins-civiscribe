# Golden Fixtures

Every file in this directory must be declared in `manifest.json`.

Fixtures are immutable evidence, not snapshots that tests may update
automatically. Each entry records its relative path, byte size, SHA-256,
provenance or consent, semantic expectations, byte-equality policy, and a
reviewed update reason.

The RGB and RGBA PNG fixtures are synthetic pixel references. Their encoded
bytes are immutable evidence, but writer tests assert semantic decode results
because compressed PNG bytes are not a cross-platform contract.

The JPEG and WebP fixtures are synthetic rich-metadata references. Their
manifest entries pin fixture identity while tests assert decoded pixels,
format, dimensions, alpha policy, and EXIF UserComment semantics. JPEG uses a
bounded decoded-pixel error; lossless WebP requires exact RGBA equality,
including RGB values under transparent pixels.

The phase-five projection fixture pins the exact UTF-8 byte sizes and SHA-256
digests of the A1111 parameters and structured Civitai manifest generated from
one project-authored canonical record.

The phase-six PNG carrier fixture pins the semantic mapping of parser-facing
text, UTF-8 JSON, Unicode fallback, and EXIF UserComment data to exact PNG
carrier types. It is a byte-equal JSON contract; generated PNG bytes remain a
semantic decode contract.

The phase-nine sidecar fixture pins the exact strict UTF-8 JSON projection of
one complete canonical record, its single prompt and workflow payloads,
parser-facing projections, artifact facts, and deterministic save diagnostics.

Prototype workflow and metadata fixtures are promoted separately only after
sanitization and explicit review.
