# Phase 11 Release Validation

Phase 11 promotes CiviScribe V2 from an isolated candidate to one registered
ComfyUI V3 image-save node. The validation used the current ComfyUI Desktop
runtime, the exact packaged custom-node root, and independent media readers.

## Public Contract

- Native V3 node ID: `CCollins_CiviScribe_SaveImage`
- Display name: `CiviScribe - Save Image for Civitai`
- Category: `CCollins/CiviScribe`
- Required source: current ComfyUI `IMAGE`
- Formats: PNG, JPEG, and WebP
- Output behavior: output node with native previews for exact committed files
- Lookup default: disabled
- Hashing default: `cached_or_fast`
- Sidecar default: disabled

The source package now registers exactly this node through `comfy_entrypoint`.
The prototype package remains outside the V2 import boundary.

## Live ComfyUI And Browser Validation

The exact private-test ZIP was unpacked under a fresh isolated ComfyUI base and
loaded through its shipped root `__init__.py`. Live `/object_info`, native
workflow queueing, exact-file preview, persistent user resizing, progressive
disclosure, widget serialization, keyboard focus, and all 12 shipped locales
passed.

The five browser UAT cases passed independently in Microsoft Edge and Google
Chrome. Axe found no accessibility violation added by CiviScribe relative to
the host ComfyUI page baseline.

## Independent Media Conformance

Fresh live saves with sidecars were checked by:

- Pillow full decode and metadata readback;
- ExifTool 13.59;
- Exiv2 0.28.8;
- ImageMagick 7.1.2 under a restrictive read-only policy;
- PNGCheck for PNG;
- libjpeg-turbo `djpeg` 3.2.0 for JPEG; and
- libwebp `webpinfo` and `dwebp` 1.6.0 for WebP.

All checks passed. PNG preserved the exact classic `tEXt`, UTF-8 `iTXt`, and
`eXIf` carrier policy. JPEG validation reports `0 0 0` after authoring the
required compressed-image EXIF field set without camera, GPS, author, or
provenance claims. WebP lossless decode and EXIF readback passed.

The audit also confirmed that built-in `EmptyImage` is recognized as an image
source and no longer produces an unknown-active-node warning.

## Release Artifacts

The release process builds:

- a source distribution;
- a pure-Python wheel; and
- a deterministic `ccollins-civiscribe/` custom-node ZIP.

The ZIP audit enforces one package root, an explicit runtime allowlist,
deterministic timestamps and permissions, bounded members, no symlinks or
duplicate/case-colliding names, no caches or development artifacts, and no
private paths or token-like secrets. A clean virtual-environment wheel import
smoke also passes.

## Quality Gate

The final gate produced this evidence:

- 683 Python tests passed with 100% line and branch coverage;
- 20 frontend tests passed;
- five live browser UAT cases passed in Microsoft Edge and the same five
  passed in Google Chrome;
- npm reported zero known vulnerabilities;
- wheel, source distribution, and custom-node ZIP builds passed;
- the private-test ZIP contains 92 files under one
  `ccollins-civiscribe/` root, is 131,547 bytes, and has SHA256
  `c402ab6688259c9d7c80fc42e0a0cb35a142d9c143c3445b734edacbfbcec1d8`;
- an independent ZIP listing and privacy scan found no forbidden development
  artifacts, private paths, or token-like values; and
- the installed package imported through ComfyUI's V3 entrypoint as
  `CiviScribeExtension` version `2.0.0.dev0`.

Ruff, mypy, locale parity, immutable golden manifests, sidecar validation,
TypeScript, ESLint, Prettier, frontend tests, npm audit, wheel inspection, and
release-ZIP audit are orchestrated through Nox. A running ComfyUI process must
be restarted after installation before the newly copied node is registered.

No real Civitai request, upload, download, model installation, or C2PA claim is
part of this gate. Metadata, lookup, cache, EXIF, and sidecar failures remain
subordinate to the pixels-first save ladder.
