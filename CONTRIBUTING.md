# Contributing

CiviScribe targets the current ComfyUI Desktop release and Python 3.12.

## Ways to contribute

Questions and early ideas fit well in
[Discussions](https://github.com/chriscollins500/ccollins-civiscribe/discussions).
The [support guide](SUPPORT.md) links the bug and feature forms. Small fixes,
documentation improvements, and reviewed translations are welcome through
pull requests. Follow the [community guidelines](CODE_OF_CONDUCT.md).

For code changes, describe the trigger and resulting behavior. Include a
focused synthetic regression when it catches a bug or preserves an important
contract. Review fixtures, logs, screenshots, and examples for private content.
The pull-request template provides space to record validation and limitations.

## Development

Create or update the locked environment with `uv sync`, install frontend
dependencies with `npm ci`, and run the standard checks with:

```powershell
python -m nox -s python frontend build
```

The Python session runs formatting, linting, strict typing, locale and golden
fixture validation, sidecar and repository-documentation checks, and the test suite with 100 percent
line and branch coverage. The frontend session runs formatting, linting,
TypeScript checks, and Node tests. The build session creates and audits the
wheel, source distribution, and ComfyUI private-test ZIP.

For documentation work, run the offline documentation check directly.

```powershell
python -m tools.validate_repository_docs
```

It checks local links, wiki destinations, documented node inputs, and JSON
examples. Hosted Validation also runs this check. Dependency review checks
new dependency changes for moderate-or-higher known vulnerabilities. CodeQL
uses the extended suite with local and remote input sources. Dependabot
proposes weekly updates for uv, npm, and pinned GitHub Actions.
Dependency pull requests also run release-interruption tests, benchmarks,
and supply-chain audits. Frontend tests check the native compiler/backend
pairing. The Python lock retains upstream dependency compatibility bounds.

The [repository maintenance guide](docs/repository_maintenance.md) records
labels, history protection, security settings, and the publication process.

### Dependency update baseline

The 2026-10-28 refresh uses Pillow 13, NumPy 2.5.4, truststore 0.10.5, and a
direct certifi security minimum of 2026.10.23. The Python lockfile also includes
uv so Nox prefers the project's tested tool over an older executable on PATH.
CI uses Node 24.22.3. The browser job targets the ComfyUI 0.44.2 Desktop
baseline. The November 14 frontend migration uses TypeScript 7.0.2, Oxlint
1.93.0, and oxlint-tsgolint 7.0.2007. ESLint, typescript-eslint, and the old
parser-specific minimatch override are removed. The release supply-chain
session checks the frontend lock for moderate or higher advisories.
The [migration evidence](docs/frontend_lint_migration.md) documents the frozen
rule contract, negative cases, and unchanged generated JavaScript.

Development compatibility checks are deliberate:

- TypeScript and oxlint-tsgolint must use the same TypeScript release. The
  frontend contract test verifies this pairing and preserves all previously
  enabled lint checks, severities, and options.
- pytest 9.2 is paired with pytest-benchmark 5.3.1, which fixes access to the
  removed private `Node._nodeid` attribute. The old pytest cap is removed.
- The latest check-wheel-contents 0.6.3 requires wheel-filename 1.x. Version
  2.1.0 removes parser and exception names that the checker imports, so the
  lock retains 1.4.2. No upstream requirements are overridden.

The November 14 refresh upgrades all other locked dependencies to their latest
compatible stable releases, including 22 Python packages. The publishing
workflow pins Comfy CLI 1.26.0; its Registry imports, configuration parser, and
publication method signature were checked offline without publishing a version.

Refresh lockfiles with `python -m uv --system-certs lock --upgrade` and
`npm update`, then run the full candidate profile below. Recheck these upstream
constraints when updating either toolchain; do not patch installed third-party files.
Keep `NODE_USE_SYSTEM_CA=1` on Windows.

Additional primary sources checked 2026-11-14:
[pytest-benchmark compatibility fix](https://pytest-benchmark.readthedocs.io/en/latest/changelog.html),
[wheel-filename breaking changes](https://github.com/wheelodex/wheel-filename/blob/master/CHANGELOG.md),
[Comfy CLI 1.26.0](https://github.com/Comfy-Org/comfy-cli/releases/tag/v1.26.0),
[Node 24.22.3 security release](https://nodejs.org/en/blog/release/v24.22.3).

Primary sources checked 2026-10-28:
[Pillow 13 changes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html),
[certifi advisory](https://github.com/advisories/GHSA-6q48-6c7w-9gw2),
[TypeScript ESLint package requirements](https://registry.npmjs.org/typescript-eslint/8.72.1),
[pytest-benchmark 5.3.0](https://pypi.org/project/pytest-benchmark/5.3.0/).

Keep runtime changes local-first, deterministic, path-safe, and pixels-first.
Never add uploads, model installation, token persistence, filename-based
identity guessing, or metadata behavior that can prevent a writable image from
being saved.

## Registry release notes

Every final package version must have one dated `## VERSION - YYYY-MM-DD`
section in `CHANGELOG.md`. The manual Registry publishing workflow extracts
that section and supplies it as the version's Updates text. Publication fails
before contacting the Registry when the matching section is missing, empty, or
duplicated. After publication, the workflow authoritatively synchronizes the
public node description from `pyproject.toml`, verifies that the published
version record exists, and confirms that the catalog points to the newest
active version.

## Release candidate checks

Routine development remains `python -m nox -s python frontend`. The heavier
candidate profile is explicit:

```powershell
python -m nox -s release
```

It adds packaging, real subprocess interruption at cache/image/sidecar publication
boundaries, advisory benchmarks and Python allocation measurements, and an
anonymous dependency audit. `dist/runtime-sbom.json` is the standard CycloneDX
report for the locked runtime dependencies on the build platform;
`dist/development-licenses.json` inventories the development environment too.
Security-audit tools are development-only, not node runtime dependencies.

`release-tests`, `bench`, and `supply-chain` can also be run separately. A killed
writer can leave a private temporary file; tests prove it does not replace an
existing image or prevent the next save. We deliberately do not sweep temporary
files that another process may still own. These are process-crash tests, not
claims about physical disk failure or power-loss durability.

For an explicit strict-runtime pass, run `python -m nox -s strict`. This repeats
the normal Python tests with warnings treated as errors, strict bytes handling,
UTF-8 mode, and three hash seeds/time-zone environments. It is intentionally
outside everyday checks. Time-zone behavior follows the host runtime; setting
`TZ` does not emulate POSIX time-zone switching on Windows.

The manual **Release candidate validation** workflow builds once, binds wheel,
sdist, private-test ZIP, Registry ZIP and supply-chain reports to the source
commit, then tests those artifacts on Windows, Linux and macOS. Linux also requires
ExifTool, PNGCheck, djpeg, webpinfo and dwebp. Another isolated CPU-only job loads
the exact ZIP into the pinned current ComfyUI checkout and runs Playwright/Axe.
Missing readers or a failed browser test block release; they are not silent skips.
Update the ComfyUI revision deliberately when adopting a newer Desktop baseline.

The **Publish to ComfyUI Registry** workflow runs only from `main`, depends on all
candidate checks, signs the manifest and its seven named assets using GitHub
artifact attestations, and verifies all eight before creating the GitHub release.
The source archive is also compared with the audited node files and wheel
package metadata before its checksum enters the manifest.
The Registry job independently verifies the ZIP against the same source commit,
publication workflow, main ref and hosted-runner policy before uploading it.
See [download verification](SECURITY.md#verify-a-release-download).
The Registry adapter uses the pinned official CLI's
request schema but uploads the already-audited ZIP, avoiding the CLI's automatic
repack. Description synchronization and paginated readback still follow upload.
Published versions and assets are never overwritten; use a new version after a
failed or incorrect release. Do not rerun version creation merely to retry a
failed listing check; run the listing verifier separately.

Before the first release with this workflow, configure the GitHub `release`
environment with a required reviewer, restrict it to `main`, and place the
`REGISTRY_ACCESS_TOKEN` secret there. The workflow fails closed if no required
reviewer is configured. Repository settings and credentials are separate from
source changes; local tests cannot prove that hosted approval or attestation ran.

For uncommitted local validation, `tools.release_bundle prepare --working-tree`
and `tools.test_comfy_artifact --working-tree` explicitly mark/accept a local
candidate. Publication rejects these bundles. Normal bundle preparation requires
the requested commit to match HEAD and a clean working tree.

To exercise an existing clean ComfyUI checkout without touching Desktop, use
`python -m tools.test_comfy_artifact --help`. It creates its own temporary base
directory, loads only the staged CiviScribe package, uses CPU and a free loopback
port, and stops only its own process. Never point browser UAT at a working session.

Sources checked 2026-09-12: [Comfy publishing](https://docs.comfy.org/registry/publishing),
[GitHub attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations),
[pip-audit](https://github.com/pypa/pip-audit).
