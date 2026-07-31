# Phase 8 Image Writers

Phase 8 completes the retained PNG, JPEG, and WebP output boundary for the
private CiviScribe V2 candidate. It does not register the node, live-sync it,
add sidecars, or alter the accepted PNG metadata layout.

## Shared Save Transaction

One format-neutral transaction now owns:

1. workflow scanning and identity enrichment;
2. canonical generation-record construction;
3. rich, reduced, and pixels-only metadata candidates;
4. safe filename and subfolder planning;
5. extension-aware temporary files and counters;
6. format-writer dispatch;
7. flush, post-write verification, and atomic publication;
8. safe root-level output fallback; and
9. previews that reference the exact committed artifact.

The writer registry accepts only the typed `ImageFormat` values `png`, `jpeg`,
and `webp`. A writer whose declared format disagrees with the request is
rejected before publication.

## Writer Boundary

The incoming ComfyUI tensor remains in its numeric dtype through scanning,
identity, projection, and orchestration. One shared conversion helper performs
the currently supported 8-bit conversion at the selected Pillow writer
boundary. Non-finite values are rejected, integer samples are clipped without
rescaling, and floating samples are clipped from normalized `[0, 1]` values.

Pillow remains the sole runtime image encoder and EXIF implementation.

## JPEG

The JPEG adapter defaults to:

- quality 100;
- optimized entropy coding;
- subsampling 0, or 4:4:4 chroma; and
- explicit alpha flattening over `#FFFFFF`.

JPEG remains truthfully identified as lossy. The writer reopens the completed
temporary file and verifies format, dimensions, mode, and requested EXIF before
the transaction may publish it.

## WebP

The WebP adapter defaults to:

- lossless encoding;
- quality 100;
- method 6; and
- exact transparent-pixel RGB preservation.

RGB, RGBA, and grayscale inputs are supported. Alpha and RGB values beneath
fully transparent pixels are verified by an exact decoded-pixel golden.
Explicit lossy WebP remains available through typed writer options.

## EXIF Projection

JPEG and WebP consume one `ExifMetadataProjection` built from the same
`GenerationRecord` used by PNG, A1111, and the structured Civitai manifest.

Rich output writes:

- A1111/Civitai-compatible parameters in EXIF UserComment using the established
  Unicode encoding;
- truthful Software; and
- final PixelXDimension and PixelYDimension values.

Reduced output writes only the parser-compatible UserComment. Pixels-only
output writes no custom metadata. No camera, lens, GPS, timestamp, authorship,
or provenance fields are invented.

## Pixels First

For every frame and format, the transaction attempts:

1. rich metadata;
2. reduced parser-compatible metadata;
3. pixels only; and
4. a safe root-level output plan when the requested plan cannot publish.

Each attempt receives a fresh temporary file. Metadata construction, EXIF
authoring, serialization, post-check, and custom-path failures therefore cannot
discard otherwise writable pixels. Only exhaustion of every valid publication
attempt fails the batch.

## Evidence

Phase 8 adds project-authored immutable fixtures for:

- maximum-fidelity RGB JPEG with rich EXIF; and
- exact lossless RGBA WebP with rich EXIF.

The manifest pins fixture identity. Tests assert semantic decode behavior
rather than cross-platform byte equality for compressed media. The complete
suite covers:

- typed option validation;
- writer registry dispatch;
- alpha flattening and preservation;
- transparent RGB;
- rich and reduced EXIF round trips;
- malformed projection rejection;
- post-write format, dimension, mode, and EXIF mismatch rejection;
- metadata and location fallbacks;
- exact output extensions and previews;
- extension-scoped counters;
- unchanged PNG carriers; and
- 100% line and branch coverage.

Phase 8 validation uses mocked network transports and performs no real network
calls.

## Subsequent Work

Phase 9 supplies the additive sidecar schema and deterministic save diagnostics
described in `phase9_sidecars.md`. Phase 10 implements native progressive
disclosure, localization, and the static accessibility contract. Phase 11
completed public registration, live ComfyUI and Axe validation, and release
packaging.
