# Changelog

All notable CiviScribe changes are documented here.

## Unreleased

- Fixed release packaging from clean checkouts by tracking the compiled
  ComfyUI V3 frontend while continuing to ignore root build artifacts.
- Made native cache-lock tests cover both Windows and POSIX adapters on every
  CI operating system while retaining the 100 percent coverage gate.
- Updated the pinned GitHub checkout action to its current Node.js 24 release.

## 2.0.0.dev0 - 2026-07-30

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
