# Changelog

All notable CiviScribe changes are documented here.

## 2.0.8 - 2026-09-15

- Fixed metadata detection in workflows with multiple CiviScribe save nodes by
  requesting the executing node's unique ID from ComfyUI. Each save now resolves
  its own upstream prompts, resources, and generation settings instead of
  reporting `save_node_ambiguous`.

## 2.0.7 - 2026-09-12

- Fixed workflow scanning so nested literal data cannot pull disconnected models
  into resource metadata; current V3 dynamic inputs use their flattened socket
  names, including Sage's model picker.
- Removed image-runtime imports from Registry TLS setup and verified clean
  publishing-helper imports before immutable version creation.
- Added bounded Registry version pagination, with duplicate and inconsistent
  pages rejected rather than selecting the wrong latest version.
- Refreshed synthetic JPEG/WebP goldens with required EXIF fields and assertions.
- Added unitless JPEG resolution tags for independent EXIF readers, without
  claiming a physical print size or changing image pixels.
- Corrected the independent conformance helper for disabled workflow embedding;
  an absent graph no longer produces a misleading empty PNG prompt carrier.
- Added main-only, approval-gated publishing of checksum-verified, once-built
  artifacts, plus an exact-package Windows/Linux/macOS matrix, isolated V3
  browser/Axe checks, mandatory independent image readers, supply-chain reports,
  and opt-in process-interruption and performance checks.
- Added authoritative post-publish Comfy Registry description synchronization,
  verified system-certificate fallback, and bounded public readback so stale
  catalog descriptions or active-version pointers are detected instead of
  silently surviving a successful version publication.

## 2.0.6 - 2026-08-20

- Added first-class handling for Civitai's observed `VisionLanguage`, `CLIP`,
  and `AestheticGradient` AIR resource types so compatible text encoders and
  style resources can resolve and reach parser-facing metadata.
- Added conservative explicit-AIR support for `CLIPVision` resources and the
  current `ComfyWorkflows` enum without inventing identities from model types
  that Civitai still reports with an `unknown` AIR type.

## 2.0.5 - 2026-08-19

- Added final-prompt guidance and diagnostics for LLM-enhanced, wildcard, and
  dynamically built prompt paths. A connected final prompt override now clears
  the corresponding unresolved scanner warning while remaining metadata-only.
- Added a focused guide for wiring the final active prompt from Krea 2, Ernie,
  and similar runtime enhancement or subgraph patterns.
- Added deterministic Comfy Registry update-note publication from each
  version's matching `CHANGELOG.md` section, with validation for missing,
  empty, or duplicate release sections.
- Replaced the terse Comfy Registry summary with a plain-language description
  of CiviScribe's Civitai-ready formats, captured generation details, active
  resource filtering, and reloadable PNG workflows.

## 2.0.4 - 2026-08-18

- Added purpose-built square icon and 21:9 banner artwork for the Comfy
  Registry listing. This release changes branding and package metadata only;
  image saving and metadata behavior are unchanged.

## 2.0.3 - 2026-08-17

- Added an explicit current rgthree `Seed (rgthree)` scalar contract so a
  fixed or frontend-resolved seed consistently reaches `%seed%`, A1111/EXIF,
  Civitai metadata, and sidecars. Unresolved `-1`, `-2`, and `-3` rgthree
  execution sentinels remain unknown instead of being published as real seeds.

## 2.0.2 - 2026-08-16

- Removed Comfy Registry scanner false positives without changing image-save,
  metadata, lookup, cache, or frontend behavior.
- Replaced optional dynamic imports with ordinary guarded imports and replaced
  the preview wrapper's method binding with an explicitly received call.
- Moved CiviScribe-owned compiled frontend modules from `web/dist` to
  `web/runtime` so the Registry provenance scanner does not classify them as
  unknown vendored dependencies.
- Added release-gate coverage for the exact Registry scanner patterns that
  incorrectly flagged 2.0.0.

## 2.0.1 - 2026-08-16

- Added bounded, source-contract-compatible resource extraction for active ND
  Super LoRA Loader bundles, including enable state and separate model/CLIP
  strengths.
- Fixed the workflow-embedding toggle so disabling it omits both the ComfyUI
  API prompt graph and UI workflow graph from image metadata and sidecars.
- Updated GitHub validation to Node.js 24.19 and current Node 24 action
  runtimes, and replaced the stale publishing wrapper with the same Registry
  operation through pinned `comfy-cli` 1.16.0.

## 2.0.0 - 2026-08-16

- Rebuilt the public README as a friendly product introduction with clear
  installation, one-minute usage, format, privacy, and troubleshooting guides.
- Fixed release packaging from clean checkouts by tracking the compiled
  ComfyUI V3 frontend while continuing to ignore root build artifacts.
- Made native cache-lock tests cover both Windows and POSIX adapters on every
  CI operating system while retaining the 100 percent coverage gate.
- Updated the pinned GitHub checkout action to its current Node.js 24 release.
- Rebuilt the unreleased prototype as one current ComfyUI V3 image-save node.
- Added PNG, JPEG, and WebP writers with shared A1111 and Civitai projections.
- Added active workflow scanning, prompt extraction, resource detection, and
  deterministic primary model and VAE selection.
- Added AIR parsing, approved-root hashing, bounded local caches, explicit
  identity overrides, and optional privacy-safe Civitai lookup.
- Added pixels-first fallbacks, deterministic sidecars, native progressive UI,
  localization, release auditing, and full Python line and branch coverage.
- Promoted CiviScribe V2 to the repository root. The complete 0.22.11
  prototype is preserved on `codex/archive-prototype-0.22.11`.
