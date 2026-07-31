# CCollins' CiviScribe V2 Feature Disposition

Status: Complete prototype-history audit
History reviewed: `0.9.0` through `0.22.11`
Recorded changelog releases: 101

## 1. Evidence and Limits

This disposition is based on:

- every release entry in `CHANGELOG.md`;
- the current `0.22.11` source tree;
- current tests, tools, schemas, fixtures, and developer documents;
- the V2 product decisions in `docs/product_contract.md`.

The repository has one Git commit and no release tags. Historical release source
snapshots cannot be reconstructed from Git. The changelog is therefore treated
as a product-history narrative, not proof that every historical implementation
remains reproducible.

## 2. Disposition Terms

- **Keep**: product behavior remains a V2 requirement.
- **Redesign**: retain the user or domain outcome, replace the prototype
  implementation.
- **Remove**: omit from V2 runtime and normal documentation.
- **Developer-only**: retain only scoped research, fixtures, or release tooling;
  do not ship it as product functionality.
- **Archive**: preserve historical evidence outside the installed package.

No prototype implementation is grandfathered into V2 merely because it works.

## 3. Product-Level Decisions

### Keep

- PNG, JPEG, and WebP image saving.
- Exact proven PNG A1111/ComfyUI/Civitai carrier behavior.
- JPEG/WebP EXIF UserComment compatibility.
- Active upstream graph filtering.
- Prompt, sampler, scheduler, guidance/CFG, seed, dimensions, model, LoRA, VAE,
  encoder, embedding, ControlNet, IPAdapter, and upscaler extraction when
  supported by graph evidence.
- Switch/router-aware scanner behavior.
- One consistent primary model and hash selection.
- Full AIR parsing and canonicalization.
- Preferred/manual identities and explicit identity precedence.
- Privacy-safe hash and identity caches.
- Optional Civitai lookup, disabled by default.
- Windows system trust support and sanitized lookup diagnostics.
- Safe filename templates, output confinement, and atomic writes.
- Pixels-first fallback.
- Optional deterministic sidecar JSON.
- Compact progressive UI, stable preview sizing, accessibility, and
  localization.
- Security, dependency, package, and privacy release gates.

### Redesign

- Replace the universal metadata envelope with one focused typed
  `GenerationRecord`.
- Replace monolithic node execution with native V3 adapters and cohesive
  scanner, identity, projection, writer, and storage modules.
- Replace V1-derived V3 schemas with directly authored V3 schemas.
- Replace the large sidecar with a smaller purpose-built V2 schema.
- Replace raw advanced JSON as the primary override UX with native structured
  controls; retain a power-user import path only if it remains necessary.
- Replace broad format/profile frameworks with three thin writer adapters.
- Replace general capability probing with focused startup/runtime checks.
- Replace hard-coded worker counts with bounded workload-aware concurrency.

### Remove

- V1 nodes, legacy mappings, fallback imports, compatibility aliases, and
  widget migrations.
- Experimental and universal-media nodes.
- IMAGE/VIDEO/AUDIO passthrough sockets and save-receipt outputs.
- `civitai_exif_minimal`.
- GIF, animated WebP, APNG, video, audio, sequences, AVIF, JPEG XL, TIFF,
  OpenEXR, MKV, MOV, MP4, and WebM.
- Full PNG/JPEG/WebP standards-authoring controls.
- XMP/ICC/HDR/source-metadata helper nodes and user metadata authoring.
- C2PA and provenance framework.
- Asset ledger, SQLite catalog, captions, companion files, and save receipts.
- Broad media profile, plugin, codec, and precision frameworks.
- Runtime corpus downloading, model installation, upload, or download behavior.

### Developer-Only or Archive

- Sanitized workflow fixtures and scanner rule coverage.
- External metadata analyzers.
- Civitai corpus/AIR research results that directly support tested resolver
  rules.
- Independent PNG/JPEG/WebP inspection and sidecar validation tools.
- Package/privacy/security/accessibility release tooling.
- Prototype release reports and removed-format feasibility studies in a
  research archive.

## 4. Complete Release Ledger

### 0.9 Series

| Release | Historical contribution | V2 disposition |
|---|---|---|
| 0.9.0 | Initial PNG node, A1111 parameters, Comfy prompt/workflow, Civitai manifest, safe paths | **Keep behavior; redesign implementation** around one native V3 node and typed record |
| 0.9.1 | PNG parser compatibility and import-path fixes | **Keep outcomes**; obsolete import fallbacks **remove** |
| 0.9.2 | Active graph traversal and filename token fixes | **Keep** |
| 0.9.3 | Pixels-first fallbacks and lookup diagnostics | **Keep** |
| 0.9.4 | Full AIR and broader Civitai hash support | **Keep** |
| 0.9.5 | API diagnostics and metadata status hardening | **Redesign** as typed, deduplicated diagnostics |
| 0.9.6 | Resource and unresolved-resource lookup status propagation | **Keep behavior; simplify schema** |
| 0.9.7 | Manual pinned identity precedence | **Keep** |
| 0.9.8 | Preferred primary AIR/URL input | **Keep** |
| 0.9.9 | Preferred URL/cache lifecycle cleanup | **Keep identity semantics**; lifecycle trace becomes optional sidecar diagnostics |
| 0.9.10 | Partial identity cleanup and advanced JSON UX | **Keep partial-identity truthfulness**; raw JSON UX **redesign** |
| 0.9.11 | Frontend toggle and SSL diagnostics | **Keep TLS diagnostics**; frontend compatibility machinery **remove** |
| 0.9.12 | Advanced JSON frontend cleanup | Advanced override need **redesign**; old widget code **remove** |
| 0.9.13 | Advanced JSON editor and IMAGE passthrough | Editor objective **redesign**; passthrough socket **remove** |
| 0.9.14 | PNG metadata standards audit | **Keep** exact proven PNG carriers and independent structural checks |
| 0.9.15 | JSON sidecar standards audit | **Keep** strict deterministic sidecar; replace oversized schema |
| 0.9.16 | Production-readiness audit candidate | **Developer-only** release checks |
| 0.9.17 | EXIF UserComment and EXIF-minimal mode | UserComment **keep**; minimal mode **remove** |

### 0.10 Series

| Release | Historical contribution | V2 disposition |
|---|---|---|
| 0.10.0 | Compatibility freeze and internal seams | Clean boundaries **redesign**; compatibility freeze machinery **remove** |
| 0.10.1 | Format-aware save orchestration | **Redesign** as three thin writer adapters |
| 0.10.2 | Experimental JPEG writer | **Keep** JPEG |
| 0.10.3 | Experimental WebP writer | **Keep** WebP |
| 0.10.4 | JPEG/WebP EXIF and active-resource cleanup | **Keep** |
| 0.10.5 | SaveImage filename parity and automatic scanner diagnostics | **Keep** safe native naming and conservative scanner inference |
| 0.10.6 | Private test RC packaging and scanner audit | **Developer-only** |
| 0.10.7 | UI layout and widget order cleanup | UX principles **keep**; fixed legacy widget-order contract **remove** |
| 0.10.8 | Regression, security, and release audit | **Developer-only** gates |
| 0.10.9 | Package hygiene hotfix | **Developer-only** packaging/privacy checks |
| 0.10.10 | Widget-order migration | **Remove** |
| 0.10.11 | Canonical image metadata sidecar model | **Replace** with focused `GenerationRecord` and lean sidecar |
| 0.10.12 | Frontend widget serialization migration | **Remove** |

### 0.11 Series, Foundation and Media Expansion

| Release | Historical contribution | V2 disposition |
|---|---|---|
| 0.11.0 | Broad standards capability probe | Narrow to focused PNG/JPEG/WebP dependency checks; **developer-only** |
| 0.11.1 | XMP and ICC pass-through | **Remove** from V2 product surface |
| 0.11.2 | GIF and animated WebP | **Remove** |
| 0.11.3 | MP4 and WebM output | **Remove** |
| 0.11.4 | Video audio muxing and runtime audit | **Remove** |
| 0.11.5 | VIDEO graph I/O | **Remove** |
| 0.11.6 | Video/audio socket RC audit | **Archive** |
| 0.11.7 | Video metadata and C2PA read detection | **Remove**; archive findings |
| 0.11.8 | Video upload harness and RC audit | **Archive** |
| 0.11.9 | Media source runtime validation | Image input lessons **keep**; media contract **remove** |
| 0.11.10 | MP4 prompt JSON and audio metadata | **Remove** |
| 0.11.11 | Video preview and media-meta normalization | Video **remove**; preview UX lesson **keep** |
| 0.11.12 | Parser-facing resource dedupe | **Keep** |
| 0.11.13 | VIDEO early-validation hotfix | **Remove** |
| 0.11.14 | VIDEO save-source hotfix | **Remove** |

### 0.11 Series, Scanner and Identity Core

| Release | Historical contribution | V2 disposition |
|---|---|---|
| 0.11.15 | rgthree LoRA support, type guards, sampler normalization | **Keep** scanner knowledge |
| 0.11.16 | External metadata inspection and scanner fixtures | Fixtures/analyzer **developer-only** |
| 0.11.17 | Portability and package hygiene | Generic package/privacy checks **keep as tooling**; video portions **remove** |
| 0.11.18 | MP4 post-save verification | **Remove** |
| 0.11.19 | MP4 status and workflow corpus tooling | Video **remove**; reusable sanitized scanner fixtures **developer-only** |
| 0.11.20 | MP4 unsupported status | **Remove** |
| 0.11.21 | MP4 capability plumbing | **Remove** |
| 0.11.22 | MP4 unavailable-vs-failed status | Typed status lesson **keep**; video code **remove** |
| 0.11.23 | Full application audit and release hardening | **Developer-only** gates |
| 0.11.24 | Static and dependency scan cleanup | **Developer-only** gates |
| 0.11.25 | Civitai matched-file resource resolution | **Keep** |
| 0.11.26 | Prompt override and source diagnostics | **Keep**, using native optional V3 inputs |
| 0.11.27 | Windows trust-store HTTPS lookup | **Keep** |
| 0.11.28 | Civitai API identity field enrichment | **Keep** attribution-relevant fields only |
| 0.11.29 | Corpus compatibility and switch-node scanner | Switch behavior **keep**; corpus tooling **developer-only** |
| 0.11.30 | Sampler and scheduler display compatibility | **Keep** |
| 0.11.31 | Unknown AIR parser-facing resource fix | **Keep** |
| 0.11.32 | PNG workflow fallback and AutoV3 preference | **Keep** |
| 0.11.33 | Standards-facing EXIF/XMP layer | Small truthful EXIF set **keep**; custom XMP framework **remove** |
| 0.11.34 | Video auto format/codec and preview | Video **remove**; stable preview lesson **keep** |
| 0.11.35 | Video codec/container compatibility | **Remove** |
| 0.11.36 | MP4 workflow metadata and video analyzer | **Remove/archive** |
| 0.11.37 | Dead-code and optimization pass | **Keep as engineering policy**, not ported code |
| 0.11.38 | AIR catalog and major-family resolver hardening | Resolver rules **keep**; collectors/data **developer-only** |
| 0.11.39 | Top-model identity corpus and AIR type hardening | Type rules **keep**; corpus **developer-only** |

### 0.11 Series, Generic Standards Expansion

| Release | Historical contribution | V2 disposition |
|---|---|---|
| 0.11.40 | Generic media framework and generated PNG controls | Generic framework and advanced authoring **remove**; retain clean boundaries |
| 0.11.41 | Source metadata and advanced PNG color controls | **Remove** |
| 0.11.42 | Compact default UI visibility | **Keep** progressive disclosure principle |
| 0.11.43 | Preview resize preservation | **Keep** behavior; rewrite against current frontend API |
| 0.11.44 | Full GIF89a controls | **Remove** |
| 0.11.45 | GIF UI cleanup | **Remove** |
| 0.11.46 | ComfyUI locale support | **Keep**, current V3-native only |

### 0.12 and 0.13

| Release | Historical contribution | V2 disposition |
|---|---|---|
| 0.12.0 | Full JPEG standards profile | Basic JPEG and required metadata **keep**; full standards UI **remove** |
| 0.13.0 | Full WebP profile and primary still formats | Basic WebP and PNG/JPEG/WebP boundary **keep**; animation/advanced UI **remove** |
| 0.13.1 | Large workflow scanner corpus | Rules and sanitized fixtures **keep/developer-only**; do not ship corpus |

### 0.14 through 0.21

| Release | Historical contribution | V2 disposition |
|---|---|---|
| 0.14.0 | Production V3 contract plus V1 fallback | Rebuild as **V3-only**; all V1/fallback paths **remove** |
| 0.15.0 | Named profiles and adaptive media execution | Broad profiles **remove**; one Civitai-first UX **redesign** |
| 0.16.0 | Precision, color, and post-write foundations | Precision/color framework **remove**; focused post-write checks **keep in tests** |
| 0.17.0 | 16-bit PNG, APNG, TIFF, OpenEXR | **Remove** |
| 0.18.0 | Sequences, companions, receipts, SQLite ledger | **Remove** |
| 0.19.0 | Professional video and standalone audio | **Remove** |
| 0.20.0 | Typed user/source metadata interoperability | General source/user metadata **remove**; typed-domain lesson **keep** |
| 0.21.0 | AVIF and JPEG XL | **Remove** |

### 0.22 Series

| Release | Historical contribution | V2 disposition |
|---|---|---|
| 0.22.0 | Release hardening and public distribution readiness | Applicable security/accessibility/package gates **keep**; migration matrix **remove** |
| 0.22.1 | Security and correctness hardening | **Keep** applicable protections and negative tests |
| 0.22.2 | Cross-version, concurrency, media conformance | Current-version/concurrency/image checks **keep**; cross-version and removed-media matrix **remove** |
| 0.22.3 | Extended compatibility and endurance validation | Relevant image endurance checks **developer-only**; legacy compatibility **remove** |
| 0.22.4 | Whole-codebase technical-debt elimination | **Keep as V2 policy**; do not port prototype architecture |
| 0.22.5 | Unified Civitai field lineage and projection correctness | **Keep** as core domain behavior |
| 0.22.6 | Prompt lineage and txt2img classification | **Keep** |
| 0.22.7 | VAE identity conflict handling | **Keep** |
| 0.22.8 | EXIF-minimal and preview sizing | Preview behavior **keep**; minimal mode **remove** |
| 0.22.9 | Exact Civitai EXIF-minimal payload | **Remove** |
| 0.22.10 | Rich EXIF-minimal restoration | **Remove** |
| 0.22.11 | Advanced GGUF identity and AIR model names | **Keep** scanner and identity fixes; distribution cleanup **developer-only** |

## 5. Current Source Disposition by Area

| Current area | V2 action |
|---|---|
| Root dual V1/V3 entry point | Replace with one V3 `comfy_entrypoint` |
| `save_node/nodes.py` | Do not port whole; mine verified orchestration behavior |
| `save_node/comfy/v3_extension.py` | Replace V1-contract adapter with directly authored V3 schema |
| `save_node/comfy/workflow_*` | Mine scanner rules and fixtures into focused scanner package |
| `save_node/civitai/` | Port AIR, identity precedence, compact client, and cache behavior into clearer modules |
| `save_node/hashing/` | Port only required hash/cache algorithms with one typed API |
| `save_node/metadata/` | Replace bundle/canonical layers with domain projections |
| `save_node/io/png_writer.py` | Preserve verified carrier behavior through a thin V2 adapter |
| `save_node/io/jpeg_writer.py` | Preserve basic encoder and EXIF behavior; remove standards suite |
| `save_node/io/webp_writer.py` | Preserve basic encoder and EXIF behavior; remove standards suite |
| Other `save_node/io/` writers | Remove |
| `save_node/media/` | Remove generic framework; no compatibility wrapper |
| `save_node/application/` | Replace with small request/pipeline/outcome transaction |
| `save_node/provenance/` | Remove |
| `save_node/security/` | Port bounded redaction and path/privacy rules into focused modules |
| `js/` | Replace with minimal V3 progressive UI and preview behavior |
| `locales/` | Keep only current-node translations and current ComfyUI localization shape |
| `schemas/` | Replace with one lean sidecar V2 schema |
| `tools/` | Keep only image inspector, sidecar validator, scanner fixture runner, and release builder |
| `tests/` | Rebuild around V2 ownership; port relevant cases, delete removed-feature tests |
| Historical docs | Archive as prototype history; V2 documents become authority |

## 6. Tests and Tools to Retain

Retain or rewrite tests for:

- safe paths, templates, counters, and atomic recovery;
- exact PNG chunk types and EXIF UserComment;
- JPEG/WebP decode and EXIF compatibility;
- Unicode prompts and deterministic JSON;
- active-resource traversal and switch behavior;
- prompt/stage classification and ambiguity;
- primary model, VAE, LoRA, encoder, and hash consistency;
- AIR grammar, identity precedence, conflicts, and partial identities;
- cache corruption, invalidation, concurrency, and privacy;
- lookup TLS, timeouts, response limits, redirects, and redaction;
- pixels-first fault injection at every optional stage;
- V3 schema, preview UI, progressive disclosure, resize stability, keyboard use,
  and localization;
- package contents, dependencies, licenses, secrets, and private-path leakage.

Create missing V2 coverage for:

- a native V3-only schema and execution contract independent of `nodes.py`;
- byte-level golden metadata carriers for PNG, JPEG, and WebP;
- one deterministic graph-to-file-to-sidecar integration path;
- compact mocked Civitai responses for identities, conflicts, mirrors, missing
  AIR, malformed data, rate limits, and TLS failures;
- package exclusion of developer corpora and archived research;
- explicit cached-save, workflow-scan, batch, and hashing performance budgets.

Remove tests whose only subject is a removed feature. Do not preserve a dead
implementation to keep an obsolete test green.

## 7. Stale Authorities

The following prototype documents are historical, not V2 requirements:

- `docs/dev/current_implementation_plan.md`;
- `docs/dev/open_requirements_and_design_goals.md`;
- phase documents for broad media, sequences, ledgers, source metadata,
  standards authoring, and removed formats.

They are preserved in Git on the `codex/archive-prototype-0.22.11` branch and
are intentionally absent from the active V2 tree. `docs/product_contract.md`,
this document, `docs/architecture.md`, and `docs/technology_decisions.md` are
the active authorities.

## 8. Migration Rule

V2 is a new implementation, not a compatibility refactor.

For every retained feature:

1. identify the observable behavior and security invariant;
2. preserve or create a focused fixture;
3. implement it in the new architecture;
4. compare output with the fixture and current Civitai behavior;
5. delete the prototype dependency rather than wrapping it permanently.

If a historical feature is absent from this disposition, it is not implicitly
retained. It must earn inclusion against the V2 product contract.

## 9. Dependency Removal Boundary

The V2 runtime and installable artifacts exclude:

- `defusedxml` and source-XMP parsing;
- `imagecodecs`, `tifffile`, OpenEXR, and `pillow-jxl-plugin`;
- PyAV, ImageIO, `imageio-ffmpeg`, and FFmpeg integration;
- SQLite asset-ledger and media-library behavior;
- video, audio, archival, HDR, broad standards, and generic media-plugin
  dependencies.

These dependencies are not retained as optional extras. Historical research and
sanitized evidence may remain in a source-only archive, but are absent from the
V2 ComfyUI package, wheel, dependency metadata, SBOM, and runtime import graph.
The measured decisions are recorded in `technology_decisions.md`.
