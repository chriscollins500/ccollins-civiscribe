# CCollins' CiviScribe V2 Development Quality Tooling

Status: accepted for V2 implementation.

This document closes the remaining development-tooling decisions for
performance profiling, fault injection, golden fixtures, privacy-safe logging,
localization quality assurance, and hosted continuous integration. These tools
are development infrastructure. They do not enter the CiviScribe runtime or
installable custom-node package.

Measurements below are observations from one development machine, not product
performance guarantees. Timing regressions become release gates only when
measured on a controlled runner with an established baseline.

## 1. Decision Summary

| Area | Accepted approach | Not selected as the default |
| --- | --- | --- |
| Microbenchmarks | `pytest-benchmark` | Ad hoc timing as the only evidence |
| CPU profiling | `py-spy` | Scalene |
| Python allocation tests | Standard-library `tracemalloc` | Always-on external profilers |
| Native allocation profiling | Optional Linux-only Memray deep job | Memray on Windows or as a runtime dependency |
| Time faults | Injected `Clock` | `time-machine` as a routine dependency |
| File faults | Injected file operations plus real temporary files | `pyfakefs` for durability or atomicity claims |
| HTTP faults | HTTPX `MockTransport` plus a local standard-library HTTP server | A required HTTP test-server package |
| Golden fixtures | Plain immutable files plus a SHA-256 manifest | Syrupy or ApprovalTests |
| Logging | Standard-library `logging` plus one mandatory privacy sanitizer | Structlog or Loguru |
| Localization QA | Strict catalog validator, pseudo-locales, TypeScript tests, Playwright, and Axe | A separate runtime i18n framework |
| Hosted CI | GitHub Actions as a thin Nox/uv runner | Provider-specific duplicated test logic |
| Release | Build once, test the exact artifacts, attest, approve, then publish | Building again inside each publishing job |

The choices are layered rather than mutually exclusive. A microbenchmark,
sampling profiler, and allocation tracer answer different questions and should
not be treated as interchangeable.

## 2. Performance Profiling

### 2.1 Candidate evidence

The focused audit exercised the current deterministic PNG/JPEG/WebP writer
workload and AIR parser.

| Candidate | Result | Decision |
| --- | --- | --- |
| `pytest-benchmark` 5.2.3 | AIR parsing benchmark completed with stable JSON output and approximately 14,600 rounds | Select for focused microbenchmarks and trend artifacts |
| `py-spy` 0.4.2 | Collected 407 samples with no sampling errors from a direct Python process and emitted a valid Speedscope profile | Select for on-demand CPU profiling |
| Scalene 2.3.0 | CPU-only mode completed; full memory mode did not complete within 120 seconds on the audited Windows/Python runtime and brought a large dependency stack | Do not select |
| `tracemalloc` | Deterministic writer workload completed with a peak of about 3.45 MB of traced Python allocations and only a small observed throughput change | Select for in-test Python allocation checks |
| Memray | Officially supports Linux best and macOS, but not Windows | Permit only as an optional Linux deep-profile job |

The workload completed 19 iterations in about 3.10 seconds without
`tracemalloc` and 18 iterations in about 3.14 seconds with tracing. This is
useful feasibility evidence, not a portable overhead guarantee.

`py-spy` had difficulty discovering the interpreter version when launching a
Windows virtual-environment launcher directly. It worked when profiling the
base interpreter with the environment import path, and its subprocess mode
also worked with a harmless launcher warning. The V2 profiling command must
target the actual interpreter process or attach to its process ID instead of
assuming every virtual-environment launcher is directly inspectable.

### 2.2 Standard profiles

V2 defines these development profiles:

- `bench`: selected pure and I/O-isolated microbenchmarks under
  `pytest-benchmark`, with machine-readable JSON retained as a CI artifact.
- `profile-cpu`: `py-spy record --format speedscope` around a deterministic
  scanner, projection, or writer workload.
- `profile-memory-python`: focused `tracemalloc` snapshot and peak-allocation
  assertions inside pytest.
- `profile-memory-native`: optional Memray run on Linux for Pillow/NumPy/native
  allocations that `tracemalloc` cannot observe.
- `profile-save-path`: an integration workload that separates scan, project,
  encode, flush, replace, sidecar, hashing, and lookup timings.

Ordinary pull requests do not fail because a shared hosted runner is a few
percent slower. Pull requests fail only for deterministic resource limits such
as unbounded allocation growth, unexpected full-file hashing, or an excessive
operation count. Timing thresholds run on a controlled baseline runner or
produce advisory trend artifacts. Release candidates receive a reviewed
profile rather than an opaque aggregate duration.

References:

- <https://pytest-benchmark.readthedocs.io/en/latest/usage.html>
- <https://github.com/benfred/py-spy>
- <https://docs.python.org/3/library/tracemalloc.html>
- <https://bloomberg.github.io/memray/supported_environments.html>
- <https://github.com/plasma-umass/scalene>

## 3. Fault Injection

### 3.1 Primary design

Fault injection is designed into ownership boundaries:

- `Clock` supplies monotonic and wall-clock time.
- `FileOperations` owns open, stat, flush, sync, replace, remove, and directory
  creation used by transactions.
- `CivitaiTransport` owns the HTTPX request boundary.
- `Sleeper` or a retry policy owns waits without tests sleeping in real time.
- cache and sidecar transactions expose named failpoints before write, after
  flush, before replace, and after replace.

Unit tests use small deterministic fakes for these interfaces. Integration
tests use real temporary directories and real operating-system file semantics.
Crash-recovery tests use subprocess termination, because an exception is not a
substitute for a process disappearing between flush and replace.

The local prototype demonstrated:

- deterministic injected wall-clock output;
- preservation of the old file when failure occurs before replace;
- visibility of the complete new file when failure occurs after replace;
- HTTPX `MockTransport` response control;
- a successful loopback request through a standard-library
  `ThreadingHTTPServer`.

### 3.2 Tool decisions

HTTPX `MockTransport` is the unit-test transport for successful responses,
timeouts, TLS-like failures, malformed JSON, response-size bounds, rate limits,
conflicts, and sanitized diagnostics. A local standard-library HTTP server
tests real sockets, headers, redirects, streaming, and timeout integration. No
external network is used by deterministic tests.

`time-machine` is not a standard dependency because V2 owns its clock seam. It
is allowed as a one-off diagnostic if an unavoidable third-party API reads
global time and cannot accept the injected clock.

`pyfakefs` is not used to prove atomic replacement, locking, sync, Pillow
encoding, permissions, disk-full behavior, or crash recovery. Its own
documentation notes limitations around C-library filesystem access and
multithreading. Real temporary files plus injected failpoints exercise the
behavior CiviScribe actually relies on.

`pytest-httpserver` is not required. Its useful integration role is covered by
the standard-library loopback server without adding Werkzeug. A future test may
adopt it only if maintaining a specific protocol scenario becomes materially
simpler.

Reference:

- <https://www.python-httpx.org/advanced/transports/>
- <https://pypi.org/project/time-machine/>
- <https://pytest-pyfakefs.readthedocs.io/en/stable/intro.html>

### 3.3 Required fault matrix

The V2 fault suite covers:

- invalid, unwritable, traversal, absolute, and disappearing output paths;
- short writes, flush failure, sync failure, replace failure, and disk full;
- process termination at every named transaction boundary;
- lock timeout, abandoned process, corrupt old cache, and concurrent writers;
- image encode failure before commit and metadata/sidecar/cache failure after
  the pixel artifact is committed;
- timeout, DNS, TLS, redirect, proxy, status, malformed JSON, oversized body,
  and conflicting Civitai identity responses;
- frozen, offset, daylight-saving, and monotonic-clock edge cases;
- privacy sanitization of every exception and status path;
- pixels-first survival whenever a valid pixel destination can be committed.

## 4. Golden Fixture Management

V2 uses plain immutable fixtures and an explicit JSON manifest. Snapshot
frameworks are unnecessary because the important properties are reviewability,
cross-tool readability, deliberate updates, and byte provenance.

The manifest records, at minimum:

- fixture schema version and stable fixture ID;
- relative path, media type, byte size, and SHA-256;
- source class such as synthetic, project-authored, or sanitized external
  regression;
- consent or license note;
- expected semantic assertions;
- whether byte equality is contractual;
- update reason and the test or bug that justified the fixture.

Tests verify manifest hashes before consuming fixtures. Most metadata checks
compare normalized semantic structures. Byte-for-byte equality is reserved for
deterministic carrier contracts such as exact PNG chunk layout, not for lossy
encoder output that may vary across valid library builds.

Fixture updates require an explicit command naming the fixture and update
reason. Tests and CI never have an auto-accept mode. Generated reports, caches,
large corpora, and downloaded media are not golden fixtures and never enter
release artifacts.

Syrupy and ApprovalTests were both functional in the dependency audit, but
neither improves this policy enough to justify another update mechanism.
ApprovalTests also brings a considerably broader helper dependency graph.

References:

- <https://syrupy-project.github.io/syrupy/>
- <https://github.com/approvals/ApprovalTests.Python>

## 5. Privacy-Safe Logging

V2 uses standard-library `logging`.

Library rules:

- use one package logger rooted at `civiscribe`;
- install only a `NullHandler` in library code;
- never configure the application's handlers, level, destination, or format;
- attach one mandatory recursive privacy filter before any record can reach a
  handler owned by CiviScribe;
- use stable event codes and bounded structured fields;
- use `LoggerAdapter` only where request or save-operation context is useful;
- never log prompts, workflow JSON, image bytes, tokens, authorization
  headers, absolute paths, sidecar bodies, cache bodies, or complete API
  responses;
- reduce paths to approved relative identifiers or basenames before creating
  the log record;
- report exception category and a sanitized reason instead of raw
  `exc_info=True` for path, TLS, network, parser, and cache failures;
- keep metadata warnings and log diagnostics as separate projections of the
  same sanitized diagnostic object.

The sanitizer recursively handles mappings, sequences, exception summaries,
URLs, headers, and free text. It applies length and nesting limits and redacts
token-like values before formatting. Tests pass hostile values through every
public logging helper and assert that both formatted output and captured
`LogRecord` fields are clean.

A local prototype verified removal of an absolute private path and a Bearer
secret from one record.

Structlog's processor model is capable, but V2 does not need an additional
logging abstraction for its small diagnostic surface. Loguru is not selected:
its global sink model is a poor library boundary, and its documented diagnostic
mode can expose variable values. Standard logging integrates directly with
ComfyUI and gives the package owner explicit control over sanitization.

References:

- <https://docs.python.org/3/howto/logging.html>
- <https://docs.python.org/3/howto/logging-cookbook.html>
- <https://www.structlog.org/en/stable/processors.html>
- <https://loguru.readthedocs.io/en/stable/api/logger.html>

## 6. Localization Quality Assurance

CiviScribe uses current ComfyUI frontend localization rather than shipping a
second runtime i18n framework. English is the canonical catalog.

### 6.1 Static validator

`tools/validate_locales.py` will:

1. parse JSON with duplicate-key rejection;
2. validate the catalog schema and locale identifier;
3. compare every recursive leaf path with English;
4. require matching leaf types;
5. reject blank translated values;
6. require exact placeholder parity for the project's declared placeholder
   syntax;
7. reject accidental control characters and warn on unexpected bidirectional
   overrides;
8. validate aliases and fallback locale behavior;
9. report expansion ratios and unusually short translations;
10. produce deterministic human and JSON summaries.

The prototype validated the current 12-locale catalog with 104 leaf fields per
locale. Its largest observed Latin/Cyrillic expansion ratio was about 1.92.
That measurement informs UI stress widths but is not a translation-quality
guarantee.

### 6.2 Pseudo-locales and frontend tests

Two generated test-only pseudo-locales are required:

- `en-XA`, which expands and accents visible text while preserving
  placeholders;
- `ar-XB`, which exercises right-to-left layout without inserting unsafe bidi
  controls into persisted data.

They are generated during tests and are not shipped as user translations.

TypeScript tests cover locale normalization, fallback, missing keys, widget
labels, tooltips, option labels, and serialization independence from visible
text. Playwright plus Axe runs the node in every shipped locale and both
pseudo-locales at representative desktop and narrow node widths. It checks:

- no clipped or overlapping labels and controls;
- progressive-disclosure behavior;
- keyboard navigation and visible focus;
- tooltip and accessible-name parity;
- screen-reader labels for icon controls;
- correct directionality;
- preview resizing without snap-back;
- widget values remaining stable while the locale changes.

Structural tooling cannot certify translation meaning. Every locale still
requires a human review before being marked complete. Machine translation may
be used as a draft only and is identified as such outside the runtime catalog.

References:

- <https://github.com/Comfy-Org/ComfyUI_frontend>
- <https://docs.comfy.org/interface/overview>

## 7. Hosted CI and Release Automation

### 7.1 Platform decision

GitHub Actions is the selected hosted CI and release platform. It matches the
expected source host, Comfy Registry publication path, security tooling, and
artifact-attestation support.

Nox remains the provider-independent command authority. Workflow YAML performs
checkout, tool bootstrap, cache setup, artifact transfer, permissions, and job
composition; it invokes named Nox sessions instead of reimplementing lint,
test, build, conformance, or package-audit commands.

The baseline implementation lives in `.github/workflows/validation.yml` and
invokes the same Python, frontend, and build sessions used locally. The broader
matrix below remains the target for public release automation.

`uv` installs from the locked development environment. Actions and reusable
workflows are pinned to full commit SHAs. Permissions default to read-only and
are elevated only in the exact attestation or publication job that needs them.

### 7.2 Job profiles

Pull requests run:

- repository hygiene and generated-file checks;
- Python formatting, lint, typing, unit, property, fault, and package tests;
- TypeScript formatting, lint, typecheck, and native tests;
- locale parity and documentation checks;
- deterministic mocked-network tests with external sockets disabled;
- Linux and Windows import/build smoke tests;
- a current ComfyUI V3 contract smoke against a pinned known-good revision.

Scheduled/deep jobs add:

- macOS coverage;
- latest-ComfyUI canary testing, reported separately from the pinned gate;
- independent image conformance tools;
- Playwright and Axe live frontend UAT;
- mutation, fuzz, native-memory, CPU-profile, and benchmark artifacts;
- dependency, license, secret, SBOM, and link audits.

Release-candidate jobs run the complete supported OS matrix and test the exact
built wheel and private-test ZIP. Performance observations remain advisory
unless they come from the controlled benchmark runner.

No untrusted pull request runs on a privileged self-hosted machine or receives
publication secrets. A self-hosted performance runner, if ever added, accepts
only protected-branch or manually approved commits.

### 7.3 Release workflow

An annotated semantic-version tag or manual release dispatch starts a clean
release:

1. validate that version declarations and changelog agree;
2. run the complete release Nox profile;
3. build the wheel and custom-node ZIP once in an isolated job;
4. audit package allowlists, privacy, licenses, SBOM, and reproducibility;
5. install and test those exact artifacts on the supported matrix;
6. generate SHA-256 checksums and artifact attestations;
7. require approval in a protected release environment;
8. publish the unchanged artifacts to a GitHub Release;
9. publish the validated custom-node artifact to the Comfy Registry in a
   separate least-privilege job.

No publishing job rebuilds the package. PyPI is not a release target unless
CiviScribe later defines a deliberate standalone Python distribution.
Published tags and artifacts are immutable. A bad release is deprecated or
yanked where supported and replaced by a new version; it is never overwritten.

References:

- <https://nox.thea.codes/en/stable/usage.html>
- <https://docs.astral.sh/uv/guides/integration/github/>
- <https://docs.github.com/en/actions/reference/security/secure-use>
- <https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations>
- <https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments>
- <https://docs.comfy.org/registry/publishing>

## 8. Dependency and Packaging Consequences

The V2 runtime adds HTTPX because it is the accepted Civitai HTTP client. The
profilers, pytest plugins, browser tools, locale validators, conformance tools,
Nox, uv, Hatchling, and release utilities are development-only.

No decision in this document adds:

- a runtime profiler or snapshot framework;
- a fake filesystem;
- a logging framework;
- a second localization runtime;
- a hosted-CI agent to the custom-node package;
- generated benchmark data, profiles, pseudo-locales, or reports to release
  artifacts.

The package allowlist, wheel inspection, ZIP audit, SBOM, and dependency-license
checks enforce this boundary.
