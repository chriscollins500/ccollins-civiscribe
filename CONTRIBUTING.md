# Contributing

CiviScribe targets the current ComfyUI Desktop release and Python 3.12.

## Development

Create or update the locked environment with `uv sync`, install frontend
dependencies with `npm ci`, and run the standard checks with:

```powershell
python -m nox -s python frontend build
```

The Python session runs formatting, linting, strict typing, locale and golden
fixture validation, sidecar validation, and the test suite with 100 percent
line and branch coverage. The frontend session runs formatting, linting,
TypeScript checks, and Node tests. The build session creates and audits the
wheel, source distribution, and ComfyUI private-test ZIP.

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
candidate checks, attests the existing files, then publishes unchanged artifacts
to GitHub and the Registry. The Registry adapter uses the pinned official CLI's
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
