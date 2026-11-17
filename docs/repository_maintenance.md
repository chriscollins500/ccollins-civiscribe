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

## Public roadmap

The [CiviScribe public roadmap](https://github.com/users/chriscollins500/projects/2)
was added on November 15, 2026 and is linked to this repository's Projects tab.
The [roadmap guide](../ROADMAP.md)
explains the priorities, status meanings, recent releases, and feedback routes.

The Roadmap board groups work by status. All items provides a table, and the
release timeline uses actual publication dates for completed versions.
Future ideas remain undated until a maintainer approves a delivery plan.

Use Planned for accepted maintenance priorities, In progress for started work,
Under consideration for uncommitted ideas, and Done for released work with
release-note evidence. Deferred output-location controls and possible adapters
for other applications remain under consideration; they do not change the
current product or filesystem boundaries.

Draft project items capture ideas and release summaries without opening
artificial bug reports. Link or convert an item to an issue when there is a
specific implementation task. Review the public board and roadmap guide when
priorities or release status change.

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
- Dependency pull requests also run the release-interruption tests,
  benchmarks, and supply-chain audits. This covers compatibility that the
  normal unit and frontend tests cannot establish alone.
- Dependabot proposes uv, npm, and GitHub Actions updates weekly on Mondays
  at 09:00 America/New_York. Compatible minor and patch proposals are grouped
  by ecosystem. Major updates receive separate review.

The previous pytest and TypeScript exclusions are removed after validating
pytest 9.2 with pytest-benchmark 5.3.1 and TypeScript 7 with Oxlint. Frontend
contract tests verify compiler/backend pairing and the retained lint checks.
Review the [frontend migration evidence](frontend_lint_migration.md) and
upstream compatibility bounds before merging dependency changes. The locked
project gates determine whether an update works with CiviScribe.
[Contributor guide](../CONTRIBUTING.md)

## CodeQL triage

The first extended scan with local-input analysis reported ten findings in
development tools. Their source and sinks were reviewed against the tool's
actual execution boundary. These tools run as explicit operator-invoked
commands. The save node does not expose their arguments through a service.

The follow-up hardening adds source checks at the file and request boundaries.
It preserves the tools' use as operator-invoked commands.

| Original findings | Source hardening |
| --- | --- |
| #10, Civitai auditor request | Canonical requests are constructed only for the public enums, model-version, and hash routes on HTTPS `civitai.com`. Credentials, nonstandard ports, query strings, fragments, invalid selectors, and unrelated routes are rejected. |
| #2, Registry coverage request | The URL is revalidated at the request boundary, and the request uses the fixed official endpoint. Responses are streamed within a 32 MiB decoded-byte limit. |
| #1, ComfyUI schema request | The operator still selects the ComfyUI origin, including localhost or a LAN host. The request targets `object_info`, preserves reverse-proxy prefixes, rejects credentials, queries, and fragments, disables redirects, and streams within 32 MiB using system TLS trust. |
| #3–#5, Workflow corpus paths | Selected roots and discovered files are resolved before use and checked for containment. Directory symlinks and Windows junctions are excluded, including when selected as roots. |
| #9, Sidecar validator paths | The selected sidecar and schema are resolved before reading. A link that leaves its selected parent directory is rejected with a sanitized error. |
| #6–#8, Package staging paths | The selected new destination and each verified archive member are resolved and checked for containment. Files are created exclusively, so an existing file cannot be overwritten. |

The November 14, 2026 scan of commit
[`280b2e3`](https://github.com/chriscollins500/ccollins-civiscribe/commit/280b2e30f72e607c79b774ae9ed4e70712b5a9b6)
cleared the three request-related warnings. It still reports ten path findings,
including the defensive `resolve()` and link checks themselves. The scan job
completed successfully; that result does not mean there are zero findings.

The November 16, 2026 follow-up expresses the path boundary through standard
normalization and component-aware checks before filesystem probes. It retains
the final resolved-path containment check and inspects links without following
their final component. Operator-selected folders outside this repository remain
supported. The unchanged stock Python extended suite reports zero repository
findings locally, while detecting all seven deliberately unsafe control cases.
The extended suite and local-input analysis remain enabled, with no dismissals,
custom sanitizer models, or source exclusions. See the
[path validation evidence and reproduction steps](codeql_path_validation.md).

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
