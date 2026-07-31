# Phase 10 Native UI, Preview, Localization, And Accessibility

Phase 10 gives the private CiviScribe V2 candidate its native ComfyUI V3 user
interface contract. The node remains unregistered and is not live-synced during
this phase. Media bytes, metadata carriers, output paths, sidecars, lookup
precedence, and the pixels-first save ladder are unchanged.

## Native V3 Boundary

The Python node uses current `comfy_api.latest.io` inputs and native ComfyUI
saved-image UI results. Every input has a stable internal identifier, an
English display name, and a plain-language tooltip.

The frozen serialized input order is:

1. `images`
2. `positive_prompt_override`
3. `negative_prompt_override`
4. `filename_prefix`
5. `output_format`
6. `jpeg_quality`
7. `jpeg_alpha_background`
8. `webp_lossless`
9. `webp_quality`
10. `write_sidecar_json`
11. `include_workflow`
12. `include_civitai_manifest`
13. `enable_civitai_lookup`
14. `preferred_primary_model_air`
15. `hashing_mode`
16. `lookup_timeout_seconds`
17. `lookup_cache_results`
18. `advanced_manual_identities_enabled`
19. `manual_resource_identities_json`

The two prompt overrides are optional text sockets. They replace scanner prompt
facts only for metadata projections, never generation. Empty values retain
automatic graph detection. Each override is bounded to the workflow scanner's
one-million-character string limit; an oversized value is ignored with a
sanitized warning.

Identity widgets configure the already implemented phase-seven services:

- lookup remains disabled by default;
- hashing defaults to `cached_or_fast`;
- successful API identities are cached by default;
- preferred AIR, Civitai URL, and model-version ID work without enabling the
  advanced JSON editor;
- manual JSON is ignored unless its explicit advanced toggle is enabled; and
- lookup timeout is bounded to 1 through 30 seconds.

## Progressive Disclosure

The frontend never reorders widgets, rewrites hidden values, changes defaults,
or calls `setSize()` during visibility updates.

| State | Controls shown |
|---|---|
| PNG | No JPEG or WebP encoding controls |
| JPEG | JPEG quality and alpha-flattening background |
| WebP | Lossless mode and WebP effort/quality |
| Lookup off | Timeout and lookup-cache policy hidden |
| Lookup on | Timeout and lookup-cache policy eligible for native advanced display |
| Manual identities off | Manual JSON hidden |
| Manual identities on | Manual JSON eligible for native advanced display |

ComfyUI's legacy canvas renderer reads `widget.hidden`, while its current Vue
node renderer reads the merged widget option. CiviScribe therefore writes the
same boolean to both `widget.hidden` and `widget.options.hidden`. Missing or
unknown widgets fail open.

Original widget callbacks are chained once. Visibility refreshes mark only the
canvas dirty; they do not recompute or force node dimensions.

## Exact Saved-File Preview

The backend returns native `SavedResult` records for the final committed
artifact. The frontend does not create a thumbnail, base64 copy, alternate
encoding, or pre-save tensor preview.

The frontend recognizes only ComfyUI's native `$$canvas-image-preview` widget.
Its sizing policy is deliberately one-shot:

1. capture a newly created node's initial dimensions;
2. wait for the first native saved-image preview widget;
3. if the node is new and its dimensions are still exactly untouched, expand
   once to at least 420 pixels wide and add one additional 220-pixel native
   preview allowance;
4. if the user resized before the first output, preserve that size;
5. if the node came from a loaded workflow, preserve its serialized size; and
6. after the preview is handled, never size the node again.

A node that never receives a preview never receives a size call. Widget clicks,
format changes, lookup changes, repeated outputs, and unrelated canvas
interactions cannot shrink or grow it one step at a time.

The native renderer remains responsible for aspect-fit display, browser
resampling, image menus, and opening the committed artifact at available
resolution.

## Localization

English is canonical. ComfyUI-native `nodeDefs.json` catalogs ship for the 12
locales exposed by the supported Desktop frontend:

- Arabic;
- English;
- Spanish;
- Persian;
- French;
- Japanese;
- Korean;
- Brazilian Portuguese;
- Russian;
- Turkish;
- Simplified Chinese; and
- Traditional Chinese.

`tools/validate_locales.py` rejects:

- a missing or extra shipped locale;
- malformed JSON or duplicate keys;
- recursive key or leaf-type drift;
- blank strings;
- control characters;
- unsafe bidi override/isolate characters in shipped values; and
- placeholder differences from English.

Frontend tests also generate expanded `en-XA` and right-to-left `ar-XB` style
pseudo-locales without shipping them. Structural validation does not certify
translation meaning, so human language review remains a release task.

## Accessibility

Phase 10 uses native ComfyUI widgets and native advanced controls instead of a
custom DOM form or modal. This retains current keyboard, focus, tooltip, and
screen-reader behavior. Every visible field has a nonblank accessible label and
tooltip in every shipped catalog.

No localized label is serialized as a workflow value. Widget IDs and option
values remain stable English machine identifiers.

## Behavioral Reference

The implementation was checked against the currently installed ComfyUI Desktop
backend and frontend APIs, including:

- current V3 `io` input support for `display_name`, `tooltip`, `optional`,
  `advanced`, and socket-only text input;
- current extension hooks for `nodeCreated` and `loadedGraphNode`;
- current native saved-image preview widget behavior; and
- current custom-node localization loading.

Official references:

- <https://docs.comfy.org/custom-nodes/js/javascript_objects_and_hijacking>
- <https://docs.comfy.org/interface/nodes-2>
- <https://github.com/Comfy-Org/ComfyUI_frontend>

The official frontend source was used only as an API and behavioral reference.
No GPL implementation was copied.

## Automated Contract

Deterministic tests cover:

- format, lookup, and manual-identity visibility matrices;
- both current widget-visibility fields;
- callback chaining and idempotent setup;
- widget order and value preservation;
- absence of size calls during visibility changes;
- one-time untouched-node preview expansion;
- manual resize before output;
- loaded-workflow size preservation;
- repeated preview and no-preview behavior;
- exact target-node filtering;
- all locale keys, labels, tooltips, Unicode, and pseudo-locales;
- V3 schema names, tooltips, defaults, advanced flags, and ordering;
- identity-policy request threading; and
- prompt override projection and size limits.

## Validation Evidence

The completed Phase 10 gate produced:

- 647 Python tests passed with 100% line and branch coverage for `civiscribe`;
- Ruff formatting and lint checks passed;
- mypy passed across 117 Python source files;
- 20 deterministic frontend tests passed after Prettier, ESLint, and TypeScript
  checks;
- all 12 locale catalogs passed exact 40-leaf structural and safety parity;
- all seven golden fixtures and the complete sidecar fixture validated;
- locked Nox `python` and `frontend` sessions passed;
- npm reported zero known vulnerabilities in the locked frontend dependency
  tree;
- the source distribution and wheel built successfully; and
- `check-wheel-contents` and the root V3 import smoke passed.

Nox directs uv and npm caches to project-local temporary directories. This
avoids depending on a writable or correctly shaped user-profile cache and
reduces interference from Windows profile policy or endpoint security tools.

No real Civitai network request, ComfyUI live registration, live workflow
execution, or live install was part of this phase. Those are intentionally
independent Phase 11 gates.

## Completed In Phase 11

Phase 11 independently validated the frozen candidate with:

- public registration in an isolated test copy;
- live `/object_info` and native workflow queueing;
- Playwright and Axe keyboard, focus, directionality, narrow-width, progressive
  disclosure, serialization, and resize checks;
- PNG, JPEG, WebP, EXIF, sidecar, privacy, and package inspection;
- build and installation artifact audits; and
- final release-gate review.

Those checks passed, and V2 now registers the public V3 node. See
`phase11_release_validation.md`.
