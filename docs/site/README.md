# CiviScribe on GitHub Pages

This is the source for <https://chriscollins500.github.io/ccollins-civiscribe/>.
The site is a static, accessible introduction and companion to the node. It
does not execute workflows, contact a ComfyUI server, upload images, or resolve
real Civitai identities. Playground data is deliberately synthetic.

The builder renders the reviewed Markdown in `docs/wiki` and selected technical
documents. Those files remain the guide authority. The release history comes
from `CHANGELOG.md`; the displayed version comes from `civiscribe/version.py`.
Update the underlying documents rather than creating a second copy of a guide.

## Build and preview

Use the project's locked Python environment. The CI documentation requirements
pin the same renderer wheel versions and SHA-256 values recorded in `uv.lock`.
No frontend framework or new node runtime dependency is added.

```powershell
.\.venv\Scripts\python.exe -m tools.build_site
.\.venv\Scripts\python.exe -m tools.validate_site
.\.venv\Scripts\python.exe -m http.server 8792 --bind 127.0.0.1 --directory .tmp/site-preview
```

Open <http://127.0.0.1:8792/ccollins-civiscribe/>. Preserve the project URL prefix
in preview so links are tested as they will be served by GitHub Pages.

```powershell
node --test tests/site/lab.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/site/test_site_build.py
node node_modules/@playwright/test/cli.js test --config tests/site/playwright.config.mjs
```

The browser gate uses the already-installed Edge channel locally and Chromium
in CI. It exercises desktop and mobile layouts, both themes, keyboard search,
safe naming examples, format decisions, branch selection, clipboard handling,
the native report example, and no-JavaScript guide access. Axe checks cover
WCAG A/AA criteria through 2.2; automated scans do not replace human review.
The output audit checks links, anchors, private-file boundaries, CSP, and exact
file digests. Lab tests guard the documented naming recipes and unsafe paths.

## Publish

The Pages workflow builds from source, validates the exact output, runs the
browser suite, and uploads only the generated public site. Deployment is limited
to `main`. It attests the Pages artifact before deploying it; it does not build
or publish a new ComfyUI node release. Existing release signing stays separate.

After browser validation, a separate job uses a short-lived `GITHUB_TOKEN`
with `contents: write` to synchronize `docs/wiki` to the existing wiki. It
uses no personal token and stores no credential in the Git remote. A fresh
clone verifies the published Markdown. Website deployment depends on that
readback. Pull requests run validation without publishing to either surface.
The wiki publisher never removes attachments or unknown pages.

`ROADMAP.md`, `SUPPORT.md`, `SECURITY.md`, `CONTRIBUTING.md`, and
`CODE_OF_CONDUCT.md` are rendered directly as website project pages. The
shared project hub routes visitors to the appropriate GitHub or Registry space.
`python -m tools.validate_public_project` checks cross-surface navigation,
package versions, guide coverage, and workflow pins. A scheduled read-only
documentation audit detects published site or wiki drift.

## Verify a deployment

Select a successful Website run on `main` in the repository's Actions tab.
Use its run ID and full source commit from GitHub, then download the exact
artifact into an empty folder:

```powershell
$runId = "RUN_ID_FROM_GITHUB"
$sourceCommit = "FULL_SOURCE_COMMIT_FROM_GITHUB"
gh run download $runId --repo chriscollins500/ccollins-civiscribe --name github-pages
gh attestation verify artifact.tar --repo chriscollins500/ccollins-civiscribe --signer-workflow chriscollins500/ccollins-civiscribe/.github/workflows/pages.yml --source-ref refs/heads/main --source-digest $sourceCommit --deny-self-hosted-runners
```

The signature binds those archive bytes to the workflow and commit. The
archive's `site-manifest.json` records SHA-256 values for every other public
file. The read-only drift audit compares the live manifest and all public
files with a fresh source build. Website provenance is separate from node
release provenance; a website update does not create a software release.

All browser scripts, styles, and images are served from the same origin. There
are no analytics, advertising scripts, external fonts, or runtime CDNs. Theme
preferences use optional browser-local storage. GitHub Pages provides hosting
and applies its own privacy policy and access logging.

Primary deployment references checked 2026-11-24:

- [Custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Configure Pages v6.0.0](https://github.com/actions/configure-pages/releases/tag/v6.0.0)
- [Upload Pages artifact v5.0.0](https://github.com/actions/upload-pages-artifact/releases/tag/v5.0.0)
- [Deploy Pages v5.0.1](https://github.com/actions/deploy-pages/releases/tag/v5.0.1)

The workflow pins exact commits, not moving major-version tags.

On Ubuntu 24.04, the browser job installs an AppArmor profile for the exact
Playwright Chromium executable. It allows that binary to create its sandbox
without changing the runner's global user-namespace restriction. Chromium
sandboxing remains enabled. See the [Chromium sandbox guidance](https://chromium.googlesource.com/chromium/src/+/main/docs/security/apparmor-userns-restrictions.md),
checked 2026-11-24. This setup affects only the disposable hosted runner.
