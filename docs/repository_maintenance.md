# GitHub repository maintenance

The public repository, wiki, issue forms, contributor pages, and automated
checks are maintained together. This guide records the GitHub configuration
reviewed on November 14, 2026.

## Public entry points

The repository About description explains CiviScribe's purpose. Its website
link opens the wiki. Topics cover ComfyUI, Civitai, image generation, metadata,
EXIF, PNG, JPEG, WebP, Python, and TypeScript.

The README uses the existing project banner and links to quick start, user
guide, releases, Registry, and support. The support page routes usage questions,
bug reports, feature ideas, and private vulnerability reports.
[Support guide](../SUPPORT.md)

The social preview uses `assets/branding/civiscribe-social-preview.jpg`,
exported from the banner at quality 98 with 4:4:4 chroma to meet GitHub's
1 MB upload limit. A black matte above and below the full banner produces a
1680×840 image, matching GitHub's 2:1 preview shape without cropping the text.

## Issues and pull requests

The bug form asks for versions, steps, expected/actual behavior, and optional
diagnostic context. The improvement form asks about the task and proposed
behavior. Both apply `needs-triage` with the appropriate issue-type label.
Blank issues remain available for reports that do not fit a form.

Keep the existing GitHub labels. Additional area labels help route metadata,
filenames, image saving, frontend, packaging, and public security-hardening work.
The `dependencies` label identifies update proposals. Use `good first issue`
and `help wanted` when a maintainer has identified suitable work.

`CODEOWNERS` identifies `@chriscollins500` as the repository maintainer. The
pull-request template asks for resulting behavior, validation, and relevant
user-facing details. Release-note categories are available through GitHub's
Generate release notes control. The publication workflow takes its update
text from the matching dated `CHANGELOG.md` section.

## History and release protection

An active branch ruleset protects `main` against deletion and force pushes.
An active tag ruleset protects `v*` release tags against updates and deletion.
Normal commits and new version tags follow the existing development and
publication workflow. The release environment requires maintainer approval
and permits deployment from `main`.

GitHub release immutability is enabled for future releases. The current
GitHub CLI creates a draft when assets are attached, uploads them, and then
publishes. Publication locks the release assets and associated tag. The
workflow's explicit artifact list and provenance verification run before
that publication step.

The publish workflow validates the source, builds the package bundle once,
tests it across operating systems and ComfyUI, signs its eight named release
assets, verifies their provenance, and uploads the same Registry ZIP. The
Registry processes new versions asynchronously. Check the public version
record and catalog pointer when determining availability.
[Release verification](wiki/Verify-a-release.md)

## Security and dependency checks

- Private vulnerability reporting, Dependabot security updates, secret
  scanning, and secret push protection are enabled.
- Default CodeQL setup uses the extended query suite for Actions, Python,
  and JavaScript/TypeScript, with local and remote input sources.
- Actions' default token permissions are read-only. Workflows declare the
  additional permissions their individual jobs require.
- Dependency review checks introduced dependency changes for moderate-or-higher
  known vulnerabilities. It runs on pull requests and supports manual ref
  comparisons through its workflow-dispatch inputs.
- Dependabot proposes uv, npm, and GitHub Actions updates weekly on Mondays
  at 09:00 America/New_York. Compatible minor and patch proposals are grouped
  by ecosystem. Major updates receive separate review.

Review the TypeScript, pytest, and minimatch compatibility notes before
merging dependency changes. The locked project gates determine whether an
update works with CiviScribe.
[Contributor guide](../CONTRIBUTING.md)

## CodeQL triage

The first extended scan with local-input analysis reported ten findings in
development tools. Their source and sinks were reviewed against the tool's
actual execution boundary. These tools run as explicit operator-invoked
commands. The save node does not expose their arguments through a service.

| Findings | Reviewed boundary |
| --- | --- |
| #10, Civitai auditor request | HTTPS is restricted to `civitai.com`, redirects are disabled, and live identity selectors are positive version IDs or validated hex hashes. |
| #2, Registry coverage request | The Registry URL is restricted to HTTPS `api.comfy.org/comfy-nodes`, port 443, with credentials, query strings, and fragments rejected. Redirects are disabled. |
| #1, ComfyUI schema request | `--object-info-url` is an explicit operator-selected audit target. The tool is a local CLI without an inbound request handler or elevated service identity. |
| #3–#5, Workflow corpus paths | The operator supplies the roots. Traversal is bounded, symlinks are excluded, and only structural class/input summaries enter reports. |
| #9, Sidecar validator paths | The operator explicitly selects the sidecar and optional schema for read-only JSON validation. |
| #6–#8, Package staging paths | The operator selects a new destination. Bundle verification and the archive allowlist run before file creation. |

Source-specific review notes accompany the findings. Their GitHub status is
open pending the maintainer's decision on dismissal. New findings need their
own review. The extended suite and local-input analysis are enabled.

## Documentation checks

```powershell
python -m tools.validate_repository_docs
```

The offline check validates relative repository links, links to versioned wiki
pages and anchors, documented schema input names, and JSON examples. Nox's
Python session includes it. The runnable save example is also exercised by
the isolated ComfyUI browser tests.

Wiki Markdown lives in `docs/wiki`. Publish reviewed changes to the separate
wiki Git repository and verify the rendered page. Keep its source and published
content aligned.

## Settings references

The following primary references were checked on November 14, 2026.

- [GitHub repository rules](https://docs.github.com/en/rest/repos/rules)
- [CodeQL default setup](https://docs.github.com/en/rest/code-scanning/code-scanning#update-a-code-scanning-default-setup-configuration)
- [Dependabot ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories)
- [Dependency review action](https://github.com/actions/dependency-review-action)
- [Actions permissions](https://docs.github.com/en/rest/actions/permissions)
- [Immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
- [GitHub CLI release creation](https://cli.github.com/manual/gh_release_create)
