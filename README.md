# CCollins' CiviScribe

This repository contains the clean CiviScribe V2 implementation. The original
prototype is preserved in Git history as a behavioral reference, but it is not
part of the runtime or release package.

Runtime code may not import the prototype's `save_node` package or copy a
prototype module as a compatibility layer.

## Current State

- The native ComfyUI V3 root entry point registers one public CiviScribe node.
- The V3 node accepts a current ComfyUI `IMAGE` batch and
  returns previews for the exact committed files.
- The format-aware save transaction supports PNG, JPEG, and WebP through three
  thin Pillow adapters without changing the accepted PNG carrier contract.
- PNG and lossless WebP preserve decoded 8-bit samples; WebP also preserves
  alpha and RGB beneath transparent pixels. JPEG defaults to quality 100,
  optimized coding, and 4:4:4 chroma, with explicit alpha flattening over
  white.
- Filename templates support current ComfyUI `%date:FORMAT%`,
  `%Node name.widget_name%`, time, dimension, and batch replacements, plus
  CiviScribe `%model%`, `%seed%`, and `%sampler%` aliases. Expanded paths are
  normalized below ComfyUI's configured output directory; unsafe absolute,
  traversal, device-name, colon, symlink, and unresolved-token paths are
  rejected.
- Completed temporary files are flushed and published without overwriting
  existing numbered outputs. A safe root-level fallback is attempted when a
  custom template or custom output location fails.
- Synthetic RGB and RGBA PNG goldens define the initial decoded-pixel contract.
- The phase-four workflow scanner normalizes untrusted API prompts into immutable,
  bounded graph values; starts from this save node's `images` input; follows the
  selected active upstream branch; and excludes disconnected resources.
- Scanner output includes selected-stage lineage, txt2img/img2img classification,
  positive and negative prompt facts, common and Flux-style sampler settings,
  active resource records, primary-model and final-decode VAE selection, and
  sanitized diagnostics.
- Exact rules cover current common ComfyUI loaders, GGUF and integrated loaders,
  rgthree Power Lora Loader entries, Nunchaku resources, Impact Pack sampler
  pipes, Wan/Step1X/RES4LYF families, antrobots base/refiner sampling, linked
  scalar widgets, and conservative topology-backed custom samplers. Unknown
  data remains unknown.
- Project-authored workflow fixtures plus malformed, cyclic, oversized,
  Unicode, routing, duplicate-resource, and property-based cases enforce the
  scanner contract at 100% line and branch coverage.
- One immutable `GenerationRecord` now feeds deterministic A1111 parameters and
  a lean structured Civitai manifest. Both projections share model, VAE,
  resource, identity, and hash facts so parser-facing values cannot disagree.
- The A1111 projection preserves an explicit negative-prompt line, uses actual
  final image dimensions, distinguishes Flux guidance from CFG, and omits
  unresolved identities from `Civitai resources`.
- The structured manifest retains active unresolved resources, null unknowns,
  sanitized validation diagnostics, and strict deterministic UTF-8 JSON.
- A project-authored projection golden pins the exact UTF-8 output digests.
- The scanner and shared projections now feed the save transaction through
  current ComfyUI V3 hidden prompt, workflow, and unique-node values.
- Rich PNG output writes `parameters` and `Software` as classic `tEXt`,
  `prompt`, optional `workflow`, optional `civitai`, and Unicode fallback
  `parameters_utf8` as uncompressed UTF-8 `iTXt`, plus an EXIF UserComment in
  the PNG `eXIf` chunk.
- A parser-safe Latin-1 `parameters` value remains available when the full
  parameters text contains Unicode. The full text is preserved separately in
  UTF-8 and EXIF carriers.
- The save transaction retries every image with reduced parser-compatible
  metadata and then pixels only before trying the safe root-level output
  fallback. Metadata, scanning, serialization, EXIF, and post-write
  verification failures therefore cannot discard writable pixels.
- The phase-six golden contract pins the exact PNG carrier types and explicitly
  forbids an iTXt-only `parameters` field.
- Phase seven resolves only scanner-selected files beneath current ComfyUI
  model roots. Absolute, traversing, malformed, missing, and symlink-escaping
  selections are rejected without reading arbitrary files.
- Separate bounded JSON stores provide cache-first model hashes and local
  identities. Cache keys contain only a model category, Comfy-relative
  selection, size, and nanosecond modification time; cache records reject
  absolute paths and secret-bearing fields.
- Hashing modes are typed as `cached_only`, `cached_or_fast`, and `full`.
  Ordinary saves use cache-first fast work and never force an uncached
  full-file pass. Full mode computes SHA-256, derives AutoV2, and computes
  safetensors payload AutoV3 in one bounded pass.
- AIR parsing accepts canonical and documented abbreviated forms, emits a
  canonical `urn:air:` value, preserves raw input, and never invents Civitai
  IDs. Manual mappings, preferred-primary identity, workflow identity, local
  cache, optional API lookup, and unresolved status follow one deterministic
  precedence chain.
- The HTTPX Civitai client is disabled by default. When explicitly enabled it
  uses verified HTTPS, bounded GET requests containing only a hash or model
  version ID, operating-system trust first, sanitized failures, and official
  API AIR as the authority.
- HTTP 429 responses start a bounded process-local cooldown instead of sleeping
  or retrying in the save path. Safe lookup diagnostics retain the delay and
  failure class while pixels continue saving.
- Current Site API hash capabilities, model/file enums, file-specific AIR
  qualifiers, and parser-facing resource rules are centralized in one
  conservative contract. SHA256-only bulk lookup may disambiguate exact
  auxiliary files without promoting their parent checkpoint or LoRA into a
  misleading second parser-facing resource.
- Structured resources distinguish model-version from exact-file identity,
  explain parser-facing inclusion/exclusion, and preserve API `baseModel` only
  as diagnostic context.
- Hash, cache, AIR, manual identity, and lookup failures remain metadata
  warnings. They cannot prevent the rich, reduced, or pixels-only save ladder
  from publishing writable pixels.
- JPEG and WebP consume the same immutable generation record and A1111
  projection as PNG. Rich and reduced metadata are carried through EXIF
  UserComment; rich output adds only truthful Software and final-dimension
  fields.
- Rich JPEG EXIF also writes the complete required compressed-image field set:
  ExifVersion, ComponentsConfiguration, FlashpixVersion, ColorSpace,
  PixelXDimension, PixelYDimension, and YCbCrPositioning.
- Extension-aware temporary files, counter discovery, atomic publication,
  post-write verification, safe root fallback, and exact committed-file
  previews now apply uniformly to all three formats.
- Project-authored JPEG and WebP goldens enforce maximum-fidelity JPEG decode,
  exact lossless RGBA WebP decode, EXIF round trips, and transparent-RGB
  preservation.
- Optional sidecars are deterministic strict UTF-8 JSON validated by a packaged
  Draft 2020-12 schema. They contain the complete canonical record, one copy of
  the sanitized prompt and optional workflow payloads, parser projections,
  truthful committed-file facts, and stable save diagnostics.
- Sidecars are disabled by default and begin only after the final image is
  committed. Projection, serialization, flush, race, and filesystem failures
  cannot remove or retry the saved image.
- Sidecar publication is atomic and no-overwrite. The validator rejects
  duplicate JSON keys, schema or artifact inconsistencies, absolute paths, and
  secrets without echoing private values.
- The phase-ten native V3 schema exposes the implemented Civitai identity
  policy without adding a competing UI data model. Lookup stays off,
  cache-first hashing stays the default, prompt overrides are optional sockets,
  and the manual multi-resource JSON editor remains native-advanced and
  explicitly gated.
- Format, lookup, and manual-identity controls use value-preserving progressive
  disclosure. Visibility updates never reorder widgets or resize the node.
- The exact committed-file preview uses ComfyUI's native saved-image widget. A
  new untouched node receives one larger default preview allowance; user-sized
  and loaded-workflow dimensions are then persistent.
- English plus all 11 other current ComfyUI Desktop locales ship through native
  `nodeDefs.json` catalogs. Strict validation rejects duplicate keys, parity
  drift, blanks, control characters, bidi controls, and placeholder changes.
- Python, TypeScript, build, test, immutable-fixture, independent media
  conformance, and deterministic release-package foundations are active.
- Phase 11 validated and registered the public node through the exact packaged
  custom-node root in live ComfyUI, Edge, and Chrome.

## Development

From this directory:

```powershell
$env:UV_CACHE_DIR = (Join-Path (Resolve-Path "..") ".tmp\v2-uv-cache")
uv --system-certs sync --all-groups
uv --system-certs run pytest
uv --system-certs run ruff check .
uv --system-certs run mypy civiscribe tools tests
uv --system-certs run python tools/audit_civitai_api_contract.py
uv --system-certs run python tools/audit_civitai_api_contract.py --model-version-id 2734704
$env:NODE_USE_SYSTEM_CA = "1"
npm ci
npm run check
```

`--system-certs` and `NODE_USE_SYSTEM_CA=1` preserve TLS verification while
using the Windows trust store, including a locally installed HTTPS-inspection
certificate. Other platforms may omit those Windows-specific settings.
The Civitai contract audit is an explicit, anonymous, read-only drift check and
is not part of ordinary image saving.

For a controlled manual upload test, capture the public Civitai image response
and compare recognition offline:

```powershell
python tools/compare_civitai_parser_result.py `
  path\to\image.sidecar.json `
  path\to\civitai-image-response.json `
  --image-id 123456
```

See
[`docs/dev/civitai_parser_validation.md`](docs/dev/civitai_parser_validation.md)
for privacy boundaries and interpretation rules.

Nox is the provider-independent orchestration layer:

```powershell
uv run nox -s python frontend build
```

`nox -s e2e` targets an already-running isolated ComfyUI selected with
`CIVISCRIBE_E2E_BASE_URL`; `CIVISCRIBE_E2E_CHANNEL` selects `msedge` or
`chrome`. `nox -s conformance -- ...` forwards explicit image and validator
arguments to the independent conformance tool.

### Node Coverage Audit

The development-only node coverage auditor can combine live `/object_info`, a
local Manager extension map, and any number of workflow roots without retaining
prompts, model values, workflow filenames, source URLs, or local paths:

```powershell
python tools/audit_comfyui_node_coverage.py `
  --object-info-url http://127.0.0.1:8000/object_info `
  --workflow-root .\tests\fixtures\workflows `
  --output .\.tmp\comfyui-node-coverage.json
```

`--workflow-root` may be repeated. Its actionable and broad classifications are
review queues, not scanner-support claims. See
[`docs/dev/comfyui_node_coverage_audit.md`](docs/dev/comfyui_node_coverage_audit.md)
for limits, privacy rules, current observations, and interpretation guidance.
Manual resource identities can resolve an identity only after a resource is
detected; they do not substitute for graph reachability or a scanner rule.

The authoritative product and architecture documents are under [`docs/`](docs/).
