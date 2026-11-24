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

Use the project's locked Python environment, which includes markdown-it-py
4.3.0 and mdurl 0.1.2. No frontend framework or new runtime dependency is added.

```powershell
.\.venv\Scripts\python.exe -m tools.build_site
.\.venv\Scripts\python.exe -m tools.validate_site
python -m http.server 8792 --bind 127.0.0.1 --directory .tmp/site-preview
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
