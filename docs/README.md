# CiviScribe V2 Design Authority

These documents define the clean V2 rewrite of the unreleased
`comfyui-civitai-save-node` prototype.

Read them in this order:

1. `product_contract.md` - what CiviScribe is, supports, and refuses to become.
2. `feature_disposition.md` - the complete `0.9.0` through `0.22.11` audit.
3. `architecture.md` - how the retained product is rebuilt on current ComfyUI
   V3.
4. `technology_decisions.md` - accepted runtime, hashing, locking, traversal,
   removal-boundary, build, and validation decisions.
5. `documentation_tooling.md` - accepted documentation source, validation,
   localization, accessibility, and optional site-generation decisions.
6. `image_conformance_tooling.md` - accepted independent PNG, JPEG, and WebP
   release/deep validation profiles.
7. `development_quality_tooling.md` - accepted performance, fault injection,
   golden fixture, logging, localization QA, hosted CI, and release automation
   decisions.
8. `phase7_identity_implementation.md` - implemented hashing, cache, AIR,
   explicit identity, lookup, and pixels-first boundaries.
9. `phase8_image_writers.md` - implemented JPEG/WebP adapters, shared
   format-aware orchestration, EXIF projection, and conformance evidence.
10. `phase9_sidecars.md` - implemented deterministic sidecar schema, privacy
    validation, atomic companion publication, and save diagnostics.
11. `phase10_native_ui.md` - implemented native V3 widgets, progressive
    disclosure, exact preview sizing, localization, and accessibility policy.
12. `phase11_release_validation.md` - live registration, browser UAT,
    independent media conformance, and deterministic release evidence.

For current decisions, these documents supersede the broad prototype roadmaps
preserved on the `codex/archive-prototype-0.22.11` Git branch.

The implementation lives at the repository root. It exports a native V3 entry
point and registers the validated CiviScribe image-save node. Prototype runtime
modules are not present on the active branch and may not be imported by V2.

## Implementation Status

Implementation-order phases 1 through 11 are complete:

1. project-authored pixel and scanner fixtures freeze the accepted contracts;
2. the native V3-only package and typed domain boundaries are in place;
3. safe output paths, atomic commits, exact previews, and pixels-only PNG are
   executable; and
4. bounded API-prompt normalization, selected active-graph traversal, routing,
   stage lineage, prompt/settings extraction, and active resource detection are
   executable; and
5. one immutable `GenerationRecord` projects deterministically into
   A1111/Civitai-compatible parameters and a structured Civitai manifest through
   one strict UTF-8 JSON encoder; and
6. those shared projections now feed exact PNG compatibility carriers through
   the save transaction, with rich, reduced, and pixels-only retries; and
7. approved-root hashing, bounded persistent caches, AIR parsing, explicit
   identity precedence, and optional privacy-safe Civitai lookup now enrich the
   same shared resource records before projection; and
8. thin maximum-fidelity JPEG and lossless WebP adapters now share the PNG save
   transaction, EXIF projection, atomic publication, post-write verification,
   safe fallback, and exact committed-file preview contract; and
9. optional deterministic UTF-8 sidecars now project the complete canonical
   record, single prompt/workflow payload copies, parser projections, committed
   artifact facts, and sanitized save diagnostics through a packaged schema;
   and
10. the native V3 widget contract now provides value-preserving progressive
    disclosure, exact-file preview sizing that respects user dimensions,
    optional prompt overrides, accessible labels/tooltips, and strict native
    catalogs for all current ComfyUI Desktop locales; and
11. the exact custom-node release archive now passes live V3 registration,
    Edge and Chrome UAT, independent PNG/JPEG/WebP readers, strict package
    auditing, and clean-install smoke tests.

Phase 5 additionally selects the VAE nearest the final decode, keeps
`Model`/`Model hash`/`Hashes["model"]` coherent, distinguishes CFG from Flux
guidance, uses final image dimensions, retains unresolved resources in the
structured manifest, and omits unresolved identities from parser-facing
`Civitai resources`. A project-authored golden fixture pins both projection
digests. The V2 suite currently enforces 100% line and branch coverage.

Phase 6 writes parser-facing `parameters` and `Software` as classic PNG `tEXt`,
preserves UTF-8 prompt, optional workflow, optional Civitai manifest, and
Unicode parameter text as `iTXt`, and writes the A1111-compatible text into an
EXIF UserComment carried by PNG `eXIf`. Current ComfyUI V3 hidden execution
values are sanitized before embedding. A project-authored golden contract pins
the exact carrier types.

The save transaction now retries rich metadata, reduced parser-compatible
metadata, and pixels only using a fresh temporary file for every attempt.
Metadata construction, serialization, EXIF, and metadata post-check failures do
not prevent a writable image from being published.

Phase 7 keeps lookup disabled by default and ordinary saves cache-first. Model
files are read only after exact scanner-selected values resolve beneath
ComfyUI-approved model roots. Separate hash and identity stores reject absolute
paths and secret fields. Official API AIR is preferred when lookup is
explicitly enabled, while malformed, partial, conflicting, or unavailable
identity remains honestly represented and nonfatal.

Phase 8 leaves the exact PNG tEXt/iTXt/eXIf behavior unchanged. JPEG defaults
to quality 100, optimized coding, and 4:4:4 chroma; WebP defaults to lossless
method 6 with exact transparent RGB. Both formats carry A1111-compatible EXIF
UserComment metadata and only truthful Software and final-dimension fields.
Project-authored goldens and 100% line and branch coverage enforce those
contracts.

Phase 9 leaves all media bytes unchanged and keeps sidecar output disabled by
default. The final image is committed before sidecar projection or publication.
Sidecar failures therefore report a stable warning and failed sidecar status
without removing or retrying the saved image. The packaged validator rejects
duplicate JSON keys, schema violations, inconsistent artifact facts, absolute
paths, and secret values without echoing private input.

Phase 10 adds the frozen native V3 widget contract, format/lookup/manual
progressive disclosure, one-time untouched-node preview expansion, persistent
user and loaded-workflow sizing, optional prompt-override sockets, and strict
native catalogs for all 12 current ComfyUI Desktop locales. Frontend behavior
never rewrites widget values or order and never resizes during visibility
updates.

The source now registers the public V3 node. Live synchronization into the
user's primary ComfyUI install remains a separate explicit deployment action.
