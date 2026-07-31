# CCollins' CiviScribe V2 Product Contract

Status: Proposed V2 authority
Prototype baseline reviewed: `0.9.0` through `0.22.11`
Target runtime: current ComfyUI Desktop

## 0. Governing Engineering Standard

Every V2 decision follows `docs/dev/engineering_principles.md`: use the most
correct process and implementation throughout discovery, requirements,
architecture, implementation, review, verification, packaging, release,
operation, maintenance, and retirement.

Correctness, safety, privacy, standards compliance, and preservation of user
data outrank schedule, convenience, metrics, historical code, and stylistic
preference.

AI-assisted implementation follows the same authority plus its explicit
inspection, source-verification, privacy, licensing, scoped-change, and
truthful-test-reporting requirements.

## 1. Product Identity

- Product name: **CCollins' CiviScribe**
- Distribution name: `ccollins-civiscribe`
- Python package: `civiscribe`
- ComfyUI V3 node ID: `CCollins_CiviScribe_SaveImage`
- Display name: `CiviScribe - Save Image for Civitai`
- Category: `CCollins/CiviScribe`

## 2. Purpose

CiviScribe is a focused ComfyUI image output node that saves a valid image and
authors accurate, Civitai-readable generation metadata.

The product exists to solve five problems well:

1. Save PNG, JPEG, or WebP through ComfyUI's configured output system.
2. Capture the active generation path rather than every loader visible in a
   workflow.
3. Project one truthful generation record into A1111, ComfyUI, Civitai, EXIF,
   and optional sidecar representations.
4. Resolve resource identities from explicit AIR data, safe local caches, or
   optional Civitai lookup without guessing.
5. Preserve the generated pixels even when optional metadata work fails.

## 3. Non-Goals

V2 will not be a universal media framework or standards-authoring suite.

The following are explicitly out of scope:

- video, audio, GIF, animated WebP, APNG, sequences, and standalone captions;
- AVIF, JPEG XL, TIFF, OpenEXR, MKV, MOV, MP4, and WebM;
- source-image metadata preservation or editing;
- ICC/HDR/color-science authoring controls;
- comprehensive PNG, JPEG, WebP, XMP, or EXIF editors;
- C2PA signing, provenance claims, uploads, downloads, or model installation;
- asset ledgers, save receipts, SQLite catalogs, and media-library management;
- compatibility with old ComfyUI APIs, old widget layouts, or prototype
  workflows;
- an EXIF-minimal mode;
- camera, lens, GPS, author, copyright, or provenance data not explicitly
  supplied by a trustworthy source.

Historical research and corpus tools may remain in a separate development
archive, but they are not installed product features.

## 4. Support Policy

CiviScribe follows a rolling-current support policy:

- Support the current ComfyUI Desktop release and current ComfyUI V3 API.
- Use `comfy_api.latest` and native V3 schemas.
- Do not ship V1 `INPUT_TYPES`, `NODE_CLASS_MAPPINGS`, compatibility aliases,
  widget-order migrations, fallback imports, or duplicate implementations.
- When ComfyUI changes its current API, update CiviScribe rather than preserving
  an obsolete runtime path.
- Preserve media interoperability, security, and user data, not prototype
  implementation details.

## 5. Node Contract

V2 exposes one terminal output node.

### Required input

- `images`: ComfyUI `IMAGE`

### Optional connected inputs

- `positive_prompt_override`: text used only when connected or explicitly set
- `negative_prompt_override`: text used only when connected or explicitly set

### Core widgets

- filename/subfolder template
- output format: PNG, JPEG, or WebP
- format quality/lossless controls shown only when relevant
- write sidecar JSON
- embed ComfyUI workflow
- embed structured Civitai manifest
- enable Civitai lookup, default off
- preferred primary AIR, Civitai URL, or model-version ID
- hashing mode, default cache-first and non-blocking

### Proposed defaults

| Control | Default |
|---|---|
| filename template | `ComfyUI` |
| output format | PNG |
| PNG encoding | lossless Pillow encoding; 8-bit per channel for ComfyUI RGB/RGBA images |
| JPEG quality | 100, optimized, 4:4:4 chroma; still inherently lossy |
| JPEG alpha handling | flatten over an explicit default background, with the control visible only for alpha-capable input |
| WebP mode | lossless with exact transparent-pixel RGB preservation when supported |
| WebP effort | highest practical deterministic encoding effort |
| write sidecar | off |
| embed workflow | on |
| embed Civitai manifest | on |
| Civitai lookup | off |
| cache successful lookup | on |
| persistent hash cache | on |
| hashing mode | cache first, fast metadata/hash work only |
| strict/debug validation | not a normal control; validation is always non-blocking |

### Advanced widgets

Advanced controls use native V3 progressive disclosure and remain hidden until
enabled:

- manual resource identity mappings;
- lookup timeout and cache policy;
- diagnostic sidecar detail;
- format-specific encoding controls that materially affect image output.

There is no raw JSON field in the normal interface.

### Output behavior

- The node is a terminal output node.
- It returns native ComfyUI preview UI for saved images.
- Each preview references the exact final file committed to disk rather than a
  separately encoded thumbnail or the pre-encode tensor.
- The preview respects user resizing and does not mutate the node dimensions on
  unrelated interactions.
- The preview preserves the saved aspect ratio, never crops by default, and
  uses normal high-quality browser resampling when displayed below native size.
- Opening or expanding the preview exposes the saved image at its available
  native resolution.
- It does not expose IMAGE, VIDEO, AUDIO, receipt, or ledger output sockets.

## 6. One Source of Truth

All metadata projections are built from one typed `GenerationRecord`.

The record contains:

- positive and negative prompt values plus their source;
- seed, steps, sampler, scheduler, CFG, guidance, denoise, dimensions, and
  batch index when known;
- workflow classification such as `txt2img` or `img2img` only when supported by
  graph evidence;
- active resources and their graph lineage;
- normalized hashes;
- AIR and Civitai identity data;
- warnings, errors, and per-stage status;
- the final image format and dimensions.

Unknown values remain `None`. CiviScribe does not invent values to satisfy a
parser.

The A1111 parameters block, Civitai manifest, sidecar, EXIF UserComment, filename
tokens, and preview diagnostics must not maintain separate competing copies of
the same fact.

## 7. Workflow Scanning Contract

The scanner starts at the CiviScribe node's `images` input and traverses the
active upstream graph.

It must:

- ignore disconnected and inactive resource branches;
- resolve common switch, router, bypass, reroute, and composite-node patterns;
- select the generation stage that produced the saved pixels;
- distinguish positive and negative conditioning paths;
- support standard samplers, advanced/custom samplers, Flux-style guider and
  scheduler chains, and current common custom-node equivalents;
- detect checkpoints, diffusion models, UNET/GGUF models, LoRAs, VAEs, text
  encoders, embeddings, ControlNet, IPAdapter, and upscalers when active;
- preserve node IDs and class names for diagnostics without exposing private
  paths;
- report ambiguity instead of silently selecting an unrelated candidate.

Scanner rules and fixtures are domain assets. Corpus downloaders and broad
research scripts are development tools, not runtime dependencies.

## 8. Resource Identity Contract

Identity precedence is:

1. explicit per-resource manual identity;
2. preferred primary identity;
3. explicit workflow AIR or identity;
4. validated local identity cache;
5. validated Civitai API response;
6. unresolved.

Rules:

- Full canonical AIR is preferred.
- API-returned AIR is authoritative when internally consistent.
- Civitai IDs may be retained without AIR when incomplete identity is explicit.
- AIR, model IDs, and version IDs are never guessed from filenames.
- Conflicting identities remain unresolved or partially resolved with a warning.
- Parser-facing `Civitai resources` includes only identities safe to emit.
- Active unresolved resources remain visible in the structured manifest and
  sidecar.

## 9. Hashing Contract

- Use the persistent cache before reading model files.
- Cache keys use model category, Comfy-relative selected value, size, and mtime.
- Cache entries never contain absolute paths, prompts, workflows, images, or
  tokens.
- Support Civitai hash names needed for identity resolution.
- Prefer strong/full hashes already available in cache.
- Define AutoV3 as the first 12 hexadecimal characters of SHA-256 over the
  safetensors tensor payload after its bounded header.
- Treat AutoV3 as tensor-content identity, not exact-file identity.
- Accept a trustworthy embedded payload hash only after validating its format
  and semantics; do not reinterpret `sshs_legacy_hash` as AutoV3.
- Treat AutoV1 as a weak fallback.
- Do not force full-file hashing during an ordinary save.
- Hash failures are warnings and never block the image.

## 10. Civitai Lookup Contract

- Lookup is disabled by default.
- Local identity data is consulted first.
- Requests are HTTPS-only and send only a hash or model-version ID required for
  identity lookup.
- Requests never include prompts, workflows, images, sidecars, tokens, or local
  paths.
- Use the operating-system trust store first on supported platforms.
- Bound lookup time and response size.
- Do not follow unsafe redirects or downgrade TLS.
- Deduplicate failures per resource and sanitize all diagnostics.
- External API availability is never a prerequisite for saving.

## 11. File and Metadata Contract

### PNG

Normal PNG output preserves the proven compatibility layout:

- `parameters` as classic PNG `tEXt`;
- `Software` as PNG `tEXt`;
- `prompt` as UTF-8 `iTXt`;
- `workflow` as UTF-8 `iTXt` when enabled;
- `civitai` as UTF-8 `iTXt` when enabled;
- EXIF UserComment as an additional compatibility carrier.

PNG is encoded losslessly with Pillow. For normal multichannel ComfyUI RGB/RGBA
images, the supported Pillow path encodes 8-bit samples per channel. The
ComfyUI tensor remains in its incoming dtype until the PNG writer boundary,
where one explicit and tested conversion prepares the Pillow image.

PNG as a file format supports 16-bit RGB/RGBA, but Pillow does not provide the
required multichannel 16-bit writer path. V2 does not add a custom PNG codec or
a second image-encoding dependency solely to provide it. Multichannel 16-bit
PNG is therefore unsupported, not silently claimed.

Compression settings may optimize size and encoding effort but may not alter
decoded samples.

If `parameters` cannot be represented safely in Latin-1, write a sanitized
parser-compatible `parameters` value and preserve full Unicode only in an
appropriate UTF-8 carrier.

### JPEG

- Encode with Pillow.
- Default to the highest practical fidelity: quality 100, optimized coding, and
  4:4:4 chroma with no chroma subsampling.
- Store A1111/Civitai-compatible text in EXIF UserComment.
- Write only the small set of truthful standard fields needed for software and
  dimensions.
- Do not synthesize camera metadata.

Standard JPEG is inherently lossy. CiviScribe must never label it lossless.
Users requiring decoded-pixel preservation should select PNG or lossless WebP.

### WebP

- Encode with Pillow.
- Default to lossless mode and the highest practical deterministic encoding
  effort.
- Store A1111/Civitai-compatible text in EXIF UserComment.
- Preserve alpha when the selected WebP mode supports it.
- Preserve RGB values under transparent pixels when the installed WebP backend
  exposes exact-lossless behavior.
- Do not claim unsupported embedded ComfyUI conventions.

### Image quality policy

All image defaults prioritize fidelity over file size or encoding speed.

- Lossless is the default whenever the selected format supports it.
- Preserve incoming values and dtype until the selected Pillow writer boundary.
- Tensor conversion must not quantize to 8-bit before format and bit-depth
  selection.
- Working tensor dtype is recorded separately from declared or measured
  effective image precision; a float tensor is not automatically labeled a
  32-bit image.
- Encoder optimization may reduce file size but may not change decoded pixels
  in a lossless mode.
- A format limitation is reported honestly rather than hidden behind a
  misleading option name.
- Lossy modes remain explicit opt-ins, except JPEG, whose format is inherently
  lossy and is therefore presented as maximum-fidelity rather than lossless.
- The current Pillow-backed PNG, JPEG, and WebP multichannel paths encode 8-bit
  components. CiviScribe reports that writer-boundary precision conversion
  rather than claiming the encoded file retained the tensor's working dtype.
- Metadata compatibility and pixels-first fallback may not silently lower image
  quality.
- Preview generation may not introduce another lossy encode or display a
  different format variant.

### Preview fidelity

The preview is a view of the saved artifact, not a second output.

- PNG previews display the committed lossless PNG.
- WebP previews display the committed lossless WebP.
- JPEG previews display the committed maximum-fidelity JPEG, including its
  actual compression and chroma behavior.
- Alpha flattening, transparency, orientation, dimensions, and color metadata
  therefore match the saved file as closely as the browser and display system
  permit.
- If pixels-first fallback writes reduced-metadata or pixel-only output, the
  preview points to that actual fallback file.
- Batch previews preserve one-to-one correspondence with the final saved files.
- Browser scaling is presentation-only and never rewrites the file.

### Precision diagnostics

The sidecar and diagnostics distinguish:

- incoming tensor dtype;
- declared source bit depth when trustworthy metadata supplies it;
- measured effective precision when it can be determined safely;
- encoded sample depth;
- whether a precision conversion occurred and why.

Unknown precision remains unknown. CiviScribe does not infer source bit depth
from tensor dtype alone.

### Sidecar

The optional sidecar is deterministic UTF-8 JSON with a small versioned schema.
It includes the complete `GenerationRecord`, prompt/workflow payloads according
to the user's embed policy, diagnostics, and parser projections where useful.
It contains no absolute paths or secrets.

Prompt and workflow JSON appear at most once in the sidecar. Canonical fields
refer to that copy rather than duplicating large payloads.

## 12. A1111 and Civitai Compatibility

The parameters block remains human-readable and parser-friendly:

1. positive prompt;
2. `Negative prompt:` line, including an empty line when compatibility requires
   it;
3. one settings line with only known values.

Supported settings include prompt, steps, sampler, scheduler, CFG or Flux
guidance, seed, size, model, model hash, VAE, VAE hash, clip skip, denoise,
hashes, and Civitai resources.

`Model`, `Model hash`, and `Hashes["model"]` must refer to the same active
primary model. Resource names, roles, hashes, AIR, and Civitai IDs must agree
across all projections.

## 13. Pixels-First Transaction

The save transaction has one hard requirement: save the valid image to a valid
ComfyUI output location.

Metadata scanning, serialization, hashing, lookup, caches, EXIF, manifests, and
sidecars are best-effort stages. Failures produce sanitized diagnostics and
degrade metadata status from complete to partial or minimal.

If a metadata-rich write fails, CiviScribe retries with reduced metadata. If
that fails, it writes the pixels without custom metadata. Only an invalid image
or inability to write any safe output path may fail the node.

Main-image and cache writes are atomic where the platform permits. Temporary
files stay in the destination directory and are cleaned safely.

## 14. Security and Privacy

- Treat graph data, filenames, templates, metadata, API responses, and cache
  files as untrusted data.
- Normalize paths and confine writes to ComfyUI's configured output directory.
- Reject traversal, absolute paths, device names, and unsafe path components.
- Never use `eval`, `exec`, pickle, unsafe YAML, subprocesses, or shell commands.
- Never deserialize image metadata as executable objects.
- Bound metadata sizes, JSON depth, API responses, and cache entries.
- Redact tokens, authorization values, usernames, and absolute paths from
  metadata, warnings, logs, fixtures, and release artifacts.
- Do not read arbitrary files outside ComfyUI-approved model roots.

## 15. Performance Contract

- Keep the critical path synchronous only where ComfyUI requires it.
- Reuse cached graph normalization, hashes, and identities.
- Avoid copying large tensors or metadata payloads unnecessarily.
- Use bounded concurrency for independent resource work.
- Scale worker count to the host and workload rather than hard-coding a large
  thread count.
- Never use GPU resources for file hashing or metadata work.
- Profile before optimizing and retain deterministic results across worker
  counts.

Complexity grades are review guidance, not hard design limits. A/B is the
normal aspiration. C is acceptable when a cohesive implementation is clearer
than an artificial split. D is acceptable only in extraordinary, documented
cases where decomposition would make correctness, performance, or ownership
worse. E/F demands critical review, but no grade overrides the requirement to
use the most correct, secure, cohesive, and maintainable implementation.

## 16. Quality Gates

V2 release gates include:

- unit and integration tests for the domain model, scanner, projections,
  writers, paths, caches, lookup, and pixels-first fallbacks;
- golden PNG/JPEG/WebP fixtures inspected by Pillow and independent tools;
- property and fuzz tests for untrusted metadata, paths, AIR, and graph shapes;
- native V3 import and `/object_info` contract checks against current ComfyUI
  Desktop;
- frontend syntax, accessibility, keyboard, progressive-disclosure, resize, and
  serialization tests;
- static typing, linting, dependency, license, secret, and package audits;
- package import smoke and privacy scan.

External Civitai upload checks remain manual and informational because Civitai's
parser and API are external, mutable services.

The test plan also defines explicit performance budgets for:

- a warm-cache single-image save;
- a large active workflow scan;
- an uncached resource in each hashing mode;
- a normal image batch;
- bounded Civitai timeout behavior.

## 17. Definition of Done

V2 is ready when:

- one native V3 node saves PNG, JPEG, and WebP;
- active workflow metadata is truthful on the supported fixture corpus;
- normal PNG retains the proven Civitai/A1111/ComfyUI chunk behavior;
- JPEG and WebP carry parser-compatible EXIF metadata;
- unresolved resources remain honest and non-blocking;
- optional lookup and all caches satisfy the privacy contract;
- metadata failures cannot lose valid pixels;
- the UI is compact, accessible, and stable under resizing;
- no legacy node, migration, video/audio, universal-media, or minimal-mode code
  remains in the installed package.
