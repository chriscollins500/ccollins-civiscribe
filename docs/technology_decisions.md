# CCollins' CiviScribe V2 Technology Decisions

Status: accepted for V2 implementation.

This document closes the technology and dependency audits that precede the V2
compatibility freeze. Measurements are development-machine observations, not
product performance guarantees. Product behavior remains governed by
`product_contract.md`.

## 1. Runtime Dependency Boundary

The V2 runtime is intentionally small:

- Pillow is the only image encoder and EXIF implementation.
- NumPy is used only at the ComfyUI image boundary when needed to preserve the
  input tensor's supported precision and avoid unnecessary copies.
- The Python standard library owns JSON, hashing, paths, atomic replacement,
  platform file locks, and TLS policy where it is adequate.
- HTTPX is the sole runtime HTTP client and transport boundary for optional
  Civitai lookup. No other module performs network requests.
- `truststore` is permitted only when the supported ComfyUI/Python runtime does
  not reliably expose the operating-system trust store.

Runtime dependencies are added only when conformance or fault-injection tests
prove that the standard-library implementation is insufficient.

## 2. Hashing Audit

### Candidates

The focused audit compared:

- manual `hashlib.sha256()` read loops;
- `hashlib.file_digest()`;
- reusable-buffer `readinto()` loops;
- whole-file `mmap`;
- optional `blake3` streaming, memory-mapped, single-threaded, and automatic
  multithreaded modes.

Other fast hashes were excluded because Civitai does not use them as identity
fields. An algorithm that is fast but cannot resolve a Civitai resource adds no
product value.

### Evidence

On a warm 512 MiB local-file sample:

| Candidate | Best observed throughput |
| --- | ---: |
| SHA-256 manual 256 KiB reads | 604.5 MiB/s |
| SHA-256 `hashlib.file_digest()` | 593.8 MiB/s |
| SHA-256 reusable `readinto()` | 592.8 MiB/s |
| SHA-256 whole-file `mmap` | 506.0 MiB/s |

On a warm 1 GiB sample:

| Candidate | Best observed throughput |
| --- | ---: |
| SHA-256 `hashlib.file_digest()` | 562.1 MiB/s |
| BLAKE3 streaming, one thread | 1687.8 MiB/s |
| BLAKE3 streaming, automatic threads | 2161.2 MiB/s |
| BLAKE3 mmap, automatic threads | 5396.8 MiB/s |

BLAKE3 is substantially faster than SHA-256 in isolation. That does not make it
a better required dependency for this product. Computing SHA-256 and BLAKE3 in
one pass still added work, and CiviScribe needs SHA-256 for the strongest,
broadest Civitai identity match and AutoV2 derivation.

The local 78-family Civitai catalog contained 3,672 primary-file records:

- 3,665 had SHA256;
- 3,665 had BLAKE3;
- zero had BLAKE3 without SHA256;
- zero had SHA256 without BLAKE3.

This corpus does not establish a universal Civitai guarantee, but it shows no
identity coverage gained by computing BLAKE3 locally.

### Decision

- Use `hashlib.file_digest()` for full-file SHA-256 when available in the
  supported Python runtime. Keep a small chunked standard-library fallback for
  testability and unusual file objects.
- Derive AutoV2 from SHA-256.
- Define AutoV3 as the first 12 hexadecimal characters of SHA-256 over the
  safetensors tensor payload: all bytes after the 8-byte header-length field
  and bounded JSON header. It is tensor-content identity, not exact-file
  identity.
- Accept an optional `0x` prefix on a validated embedded tensor-payload SHA-256.
  Do not map `sshs_legacy_hash` to AutoV3 without independent proof of matching
  semantics.
- Parse, validate, store, serialize, and use trusted BLAKE3 values received
  from Civitai or an explicit identity cache.
- Do not require `blake3`, and do not compute BLAKE3 during the V2 save path.
- Do not use whole-file `mmap` for model hashing. It provided no SHA-256 benefit
  in the audit and complicates very-large-file and Windows file-lifetime
  behavior.
- Reconsider optional BLAKE3 computation only if a real Civitai identity corpus
  contains BLAKE3-only resources that cannot be resolved by official AIR,
  model-version ID, SHA-256, AutoV2, or AutoV3.

The 3,665 catalog AutoV2 values all matched the first 10 characters of their
SHA256 values. AutoV1 had 15 values shared by distinct SHA256 files, including
one shared by 18 files. AutoV3 had four values shared by distinct full files.
Accordingly:

| Hash | Parse/store | V2 local computation | Authority |
| --- | --- | --- | --- |
| SHA256 | Yes | Explicit or background full mode | Strong exact-file identity |
| AutoV2 | Yes | Derived from SHA256 | Compatibility; strong only with SHA256 |
| AutoV3 | Yes | Safetensors payload when requested | Tensor-content candidate |
| BLAKE3 | Yes | No | Strong when supplied by a trusted source |
| CRC32 | Yes | No by default | Weak compatibility value |
| AutoV1 | Yes | Optional compatibility only | Never authoritative alone |

When SHA256 and AutoV3 are requested together, use one bounded pass with two
SHA-256 contexts: the full-file context receives every byte and the AutoV3
context receives only the safetensors payload. Stat the file before and after
hashing and discard the result if its size or modification identity changed.
Never perform an uncached full-file pass on the critical pixel-save path.

The supported Civitai hash names are corroborated by Civitai's current
model-file scanning documentation:
<https://github.com/civitai/civitai/blob/main/docs/features/model-file-scanning.md>.
The payload boundary follows the safetensors format:
<https://github.com/safetensors/safetensors#format>.

## 3. Cache Locking Audit

### Candidates

The audit compared:

- native `msvcrt.locking` on Windows and `fcntl.flock` on POSIX;
- `filelock`;
- `portalocker`;
- `fasteners`;
- `locket`.

`flufl.lock` and `zc.lockfile` were screened but not load-tested. Their
distributed or stale-lock-file semantics do not improve a local, best-effort
ComfyUI cache. SQLite, Redis, and `multiprocessing.Lock` do not fit the product
boundary.

### Evidence

Each tested candidate completed:

- 32 spawned writers;
- 800 total read-merge-replace operations;
- a bounded contention timeout;
- immediate lock recovery after a child exited with `os._exit()` while holding
  the lock.

Observed 32-process stress times:

| Candidate | 800 operations | Crash recovery | Timeout behavior |
| --- | ---: | ---: | ---: |
| Native | 1.802 s | 0.0006 s | 0.204 s |
| `filelock` | 2.250 s | 0.0012 s | 0.205 s |
| `portalocker` | 2.555 s | 0.0038 s | 0.251 s |
| `fasteners` | 2.032 s | 0.0006 s | 0.201 s |
| `locket` | 1.785 s | 0.0005 s | 0.201 s |

All candidates were correct in this test. The third-party packages mostly wrap
the same platform primitives. `portalocker` also introduced `pywin32` in the
isolated Windows audit environment.

### Decision

Do not add a runtime locking dependency.

V2 implements one internal local cache transaction primitive shared by the hash
and identity caches:

1. Acquire a per-process reentrant lock.
2. Acquire a persistent sibling lock file with `msvcrt` or `fcntl`.
3. Hold the lock across the complete read, validate, merge, serialize, flush,
   and replace transaction.
4. Write a securely named temporary file in the destination directory.
5. Flush and `fsync` the temporary file.
6. Replace the cache atomically with `os.replace`.
7. Return a sanitized, nonfatal warning on failure.

The lock retries only recognized contention errors. Permission errors,
read-only filesystems, invalid handles, and unsupported platforms fail quickly
without blocking image saving. Caches are local application state, not a
network-filesystem coordination mechanism.

`filelock` is the approved contingency only if Windows, macOS, and Linux
fault-injection CI later proves the internal adapter incorrect or too costly to
maintain.

Required V2 tests include:

- concurrent hash- and identity-cache merges;
- independent-process same-key, distinct-key, and conflict writes;
- crash points before serialization, before replace, and after replace;
- unlocked readers observing only valid old-or-new JSON;
- timeout, permission, disk-full, and unsupported-platform failures;
- path aliases, reentrancy, temporary-file recovery, and no private data;
- pixels-first continuation for every cache failure.

## 4. Scanner Traversal Audit

### Candidates

The scanner review compared:

- list-backed breadth-first traversal using `pop(0)`;
- `collections.deque` breadth-first traversal;
- list-backed iterative depth-first traversal;
- a prebuilt adjacency index versus repeated graph searches;
- a general graph dependency.

NetworkX was used only as an audit oracle for 2,000 generated directed graphs.
It is not a runtime or planned development dependency.

### Evidence

All custom iterative traversals matched the oracle for reachable nodes and
shortest distances across 2,000 randomized graphs containing cycles, duplicate
edges, multiple roots, and disconnected nodes.

Representative 50,000-node observations:

| Shape | `list.pop(0)` | `deque.popleft()` | stack `pop()` |
| --- | ---: | ---: | ---: |
| Chain | 8.319 ms | 8.957 ms | 7.785 ms |
| Wide star | 126.310 ms | 7.735 ms | 5.827 ms |
| Cyclic layered graph | 16.099 ms | 15.464 ms | 22.170 ms |

The prototype also performs repeated reachability searches in some lineage
paths. V2 must not inherit that structure.

### Decision

Implement a small typed `GraphIndex`, not a graph framework:

- node lookup by normalized node ID;
- labeled upstream and downstream edges, including output slot information;
- one-pass index construction in `O(V + E)`;
- iterative, cycle-safe traversal;
- `deque` breadth-first traversal where shortest distance or nearest-stage
  selection matters;
- iterative stack traversal only where order and distance do not matter;
- visited-on-enqueue behavior to bound duplicate work;
- route and switch resolution before candidate edges enter the active queue;
- one active set rooted only at the executing CiviScribe node's `images` input;
- precomputed distance maps for stage and primary-model selection;
- deterministic diagnostics and explicit ambiguity instead of arbitrary
  tie-breaking.

Graph input is untrusted data. Normalization enforces bounded node, edge, string,
and nesting limits. Unknown nodes remain traversable by links but cannot become
known resources from filename-like text alone.

No NetworkX, rustworkx, igraph, SciPy graph, or custom-node imports enter the
runtime.

## 5. Remove Without Further Comparison

The following prototype capabilities are outside the V2 product contract and
are not migration candidates:

- `defusedxml` and source-XMP parsing;
- source metadata, custom XMP, ICC, HDR, and broad color-authoring frameworks;
- `imagecodecs`, `tifffile`, OpenEXR, and `pillow-jxl-plugin`;
- PyAV, ImageIO, `imageio-ffmpeg`, FFmpeg discovery, video, and audio;
- GIF, animated WebP, APNG, AVIF, JPEG XL, TIFF, OpenEXR, MP4, WebM, MOV, MKV,
  sequences, archival formats, and professional-media profiles;
- SQLite asset ledger and media-library behavior;
- captions, companions, receipts, provenance, and C2PA surfaces;
- the generic media envelope/profile/plugin framework built for those removed
  formats.

The V2 installable package contains no optional extras for these capabilities.
Their runtime modules, UI fields, localization, schemas, tests, and dependencies
are absent rather than hidden.

Useful sanitized scanner fixtures and behavioral evidence may be copied into a
source-only research archive. Prototype reports, corpora, generated media,
legacy tests, and broad tools are excluded from the installable ZIP and wheel.

Boundary tests must prove that:

- removed imports and dependencies are absent;
- removed nodes, sockets, widgets, and format values are absent;
- unsupported formats create no files;
- source XMP, ICC, and EXIF are not propagated;
- no SQLite database, video process, caption, receipt, or sequence manifest is
  created;
- package artifacts follow an explicit allowlist;
- the SBOM and license report contain none of the removed dependencies.

## 6. Accepted Development Stack

These development choices do not expand the end-user runtime:

- `uv` for project environments, locking, and local/CI command execution;
- Hatchling as the build backend for the flat ComfyUI root entry point plus the
  `civiscribe` package;
- Nox only for explicit version/platform matrices;
- pytest, Hypothesis, pytest-xdist, pytest-cov, pytest-socket,
  pytest-randomly, and targeted pytest-timeout coverage;
- strict mypy with the Pydantic plugin, with Pyrefly advisory until it proves
  equivalent for this codebase;
- TypeScript native ES modules, `tsc`, ESLint with typescript-eslint,
  Prettier, and npm lockfile/`npm ci`;
- the Node 24.12 or newer native test runner for TypeScript tests;
- Playwright and Axe for live ComfyUI frontend validation;
- Ruff, check-jsonschema, OSV-Scanner, `uv audit`, `npm audit`, CycloneDX
  SBOMs, REUSE, Gitleaks, and release artifact audits;
- periodic HypoFuzz, mutmut, CrossHair, and Atheris jobs outside the ordinary
  fast test profile.

The installable custom-node package remains conventional and does not require
these development tools.

## 7. Documentation Tooling

The accepted documentation profile is defined in
`docs/documentation_tooling.md`.

In summary:

- ComfyUI-native Markdown remains the primary user-help surface.
- Repository Markdown remains authoritative source.
- `markdownlint-cli2`, `codespell`, Lychee, selected Sybil examples, local
  Mermaid validation, Playwright, and Axe form the validation stack.
- Vale remains advisory until a project vocabulary and scoped ruleset exist.
- No static-site generator is added until a standalone site is required.
- Sphinx/MyST/Furo is the preferred future site candidate, but publication is
  blocked until all assets are local and its remaining accessibility findings
  are corrected.
- API and schema documentation are generated only after V2 defines deliberate
  public APIs and stable authoritative schemas.

Documentation tools remain development-only and never enter the custom-node
runtime or installable artifacts.

## 8. Independent Image Conformance

The accepted image-conformance profile is defined in
`docs/image_conformance_tooling.md`.

In summary:

- Pillow performs the in-process post-write reopen and full pixel load.
- ExifTool performs batched JSON metadata readback with exact expected-field
  assertions.
- PNGCheck validates PNG chunks, CRC values, and decompressed image data.
- libjpeg-turbo `djpeg` fully decodes JPEG output.
- libwebp `webpinfo` validates WebP container and bitstream structure, and
  `dwebp` performs a full independent decode.
- Exiv2 and policy-restricted ImageMagick run in the periodic deep
  cross-reader profile.
- no conformance executable or library enters the runtime dependency set or
  release artifact.

The controlled 19-file audit demonstrated that no single candidate was
sufficient. The selected layered profile plus expected metadata assertions
detected every injected PNG, JPEG, and WebP defect.

## 9. Development Quality and Release Automation

The accepted performance, fault-injection, golden-fixture, privacy-safe
logging, localization-QA, hosted-CI, and release-automation profile is defined
in `docs/development_quality_tooling.md`.

In summary:

- `pytest-benchmark`, `py-spy`, `tracemalloc`, and optional Linux-only Memray
  have distinct development roles; Scalene is not selected.
- injected clocks, file operations, and HTTPX transports are the primary fault
  seams, backed by real temporary files, subprocess crash tests, and a local
  standard-library HTTP server.
- golden outputs are immutable plain files governed by a SHA-256 manifest and
  explicit review-only updates.
- standard-library logging is protected by one mandatory recursive privacy
  sanitizer; Structlog and Loguru are not added.
- locale catalogs receive strict structural validation, test-only
  pseudo-locales, TypeScript behavior tests, and Playwright/Axe UI coverage.
- GitHub Actions is the hosted provider, while Nox remains the
  provider-independent command authority.
- release artifacts are built once, tested as artifacts, audited, attested,
  manually approved, and then published unchanged.

None of these development tools enters the installable custom-node package.
