# GitHub repository maintenance

The public repository, wiki, issue forms, contributor pages, and automated
checks are maintained together. This guide records the GitHub configuration
reviewed on November 28, 2026. Historical security and dependency snapshots
retain their own dates.

## Public entry points

The repository About description explains CiviScribe's purpose. Its website
link opens the [website](https://chriscollins500.github.io/ccollins-civiscribe/).
The [project hub](wiki/Project-hub.md) connects the website, wiki, repository,
downloads, Registry, roadmap, Discussions, Issues, and contribution routes.
Topics cover ComfyUI, Civitai, image generation, metadata,
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
Under consideration for uncommitted ideas, and Done for released software or
deployed documentation with evidence links. Deferred output-location controls and possible adapters
for other applications remain under consideration; they do not change the
current product or filesystem boundaries.

Draft project items capture ideas and release summaries without opening
artificial bug reports. Link or convert an item to an issue when there is a
specific implementation task. Review the public board and roadmap guide when
priorities or release status change.

The board's introduction is maintained in `docs/project_board.md`. Publish a
reviewed update through GitHub's Projects API and read it back. Project access
uses the account's approved CLI `project` scope; deployment jobs do not receive
that account token. Release dates use America/New_York, matching the changelog.

## Issues and pull requests

The bug form asks for versions, steps, expected/actual behavior, and optional
diagnostic context. The improvement form asks about the task and proposed
behavior. Both apply `needs-triage` with the appropriate issue-type label.
The documentation form accepts broken links, unclear examples, and website
accessibility issues. Blank issues remain available for reports that do not fit
a form. Discussion forms for Q&A, Ideas, and Show and tell point to the same
guides, roadmap, private reporting route, and community expectations.

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

## Merge verification rollout

Before the November 28, 2026 rollout, the GitHub rules for `main` protected
against deletion and force pushes. Open PRs had successful validation and
dependency reviews, and two of the three lacked a website result. Consult the
[effective rules for `main`](https://github.com/chriscollins500/ccollins-civiscribe/rules)
for the current enforcement state.

The [versioned merge ruleset](../.github/rulesets/main-merge-checks.json) is an
import template that starts disabled. It maps the checks to the verified GitHub Actions
app, requires a PR and resolved review conversations, and requires checks on an
up-to-date branch. CodeQL is a separate native rule for errors and security
findings of medium severity or higher. GitHub documents exceptions for
Dependabot PRs under default CodeQL setup. Validation and dependency review run
for those PRs. The proposal preserves the existing `main` and release-tag
rulesets, supports the current merge methods, and allows the sole maintainer to
merge after checks and conversation resolution.

| PR check | What it verifies |
| --- | --- |
| `CiviScribe validation` | Locked Python, frontend, and package gates. Dependency proposals also run release interruption, benchmark, and supply-chain checks. |
| `review` | Introduced dependencies, with moderate-or-higher known vulnerabilities failing the check. |
| `Website build and browser checks` | Reviewed docs, exact local build, educational examples, browser journeys, and accessibility. |
| CodeQL results | The native scanning rule evaluates GitHub's CodeQL results using the repository's extended queries. |

Every PR gets a website job. A path-filtered workflow may never report a
required status when its filter excludes a PR. A separate path classifier
would add a second site input inventory to maintain. Validation and the
browser job use standard public runners, ephemeral dependency storage and no
artifact uploads for PRs. Validation also runs after changes to `main` and
can be run manually on a topic branch. This removes the duplicate validation
triggered by pushing to a branch that already has a PR.

Review source and workflow changes in the PR, including changes to checks and
this policy. An Actions app binding establishes which app reports a result.
Maintainer review and `CODEOWNERS` cover changes to the workflow itself. Use
the [project board guide](project_board.md) to connect accepted work with its
issue, PR, and eventual release or deployed documentation.

When rolling out a rule change, verify the three names and their reporting app
on fresh hosted PR checks. Import disabled, confirm the saved scope, then
activate in GitHub and read back the effective rules. Exercise a passing PR and
a PR with a controlled failing check before relying on enforcement. Require
a successful post-merge Pages publication and byte audit for website changes.
Follow the existing protected release workflow for software releases. If
enforcement blocks valid work, disable only the changed ruleset and keep the
history and tag rules active while resolving the issue.

## Free GitHub capability coverage

Use public repository capabilities and standard GitHub-hosted runners. Keep
paid plans, larger runners, and private compute outside the project's zero-cost
scope. Verify a stop at $0 in the applicable billing scope before enabling any
metered feature. The API did not return the account plan, required a broader
account scope for usage, and denied the repository cache-limit read. A personal
budget or spending stop was therefore unverified. On November 28 the repository
had 2,072 bytes of active Actions caches and 34,219,150 bytes in its 89 active
artifacts. These sizes describe current storage only. Existing artifact and
cache retention still merit review against GitHub's storage allowances.

| Surface | Current use and next decision |
| --- | --- |
| README, homepage, discovery, community health | The public site is the repository homepage. Eleven topics aid discovery, and GitHub reports 100% community health. The [project hub](wiki/Project-hub.md) links the release, Registry, support, roadmap, and contribution paths. |
| Issues, forms, labels, milestones | Bug, feature, and documentation forms use the triage and area labels. GitHub reported zero open issues and zero milestones. Use milestones when work has an accepted release scope and the linked issues exist. |
| Projects and roadmap | Public Project 2 is enabled and has 13 items. Use the [roadmap guide](project_board.md) for which work belongs on the board and what counts as Done. Review native automation when there is recurring intake from real issues. Its effective configuration was not verified. |
| Discussions and Wiki | Both are enabled. Discussion forms direct people to community and support routes. Publication synchronizes reviewed wiki sources and checks a fresh readback. |
| PRs, reviews, rulesets | `CODEOWNERS` and the PR template support maintainer review. History and tag protection are active. The maintained merge policy and current enforcement are linked above. Consider opt-in auto-merge only after the required checks are enforced. GitHub merge queues require organization ownership on public repositories. |
| Actions and Pages | Repository settings require SHA-pinned actions and default to read-only tokens. Workflows use standard hosted runners. Pages uses HTTPS and a `main`-only environment. The workflow signs the tested archive and checks every published byte. |
| Deployment and immutable releases | The `release` environment restricts deployment to `main` and has one required reviewer. GitHub reports v2.0.12 immutable. All eight saved assets matched GitHub's digests and passed attestation verification against source commit `6cdf4715f91e97c62254b6688408e07f7f4c33e2`. Use the release guide for downloaded bytes and the matching source revision for bundle comparisons. |
| Dependency graph, reviews, Dependabot | GitHub exposes an SPDX SBOM and dependency review. Dependabot security updates are enabled and unpaused. Use the existing locked compatibility and supply-chain profiles for update proposals. |
| CodeQL and secret protection | Extended default CodeQL uses local and remote input sources. Secret scanning, push protection, and private vulnerability reporting are enabled. No open CodeQL, Dependabot, or secret-scanning alerts were returned. Generic patterns warrant a separate false-positive review, and validity checks can send a detected credential to its issuer. Both options are currently disabled. |
| Insights | Maintainer traffic metrics were readable. Use traffic, contribution, dependency, and Actions evidence to assess adoption and reliability without adding site tracking. |
| Public Packages, GHCR, dev containers | GitHub public packages are free. CiviScribe's install path is the ComfyUI Registry, with signed wheel and ZIP assets in Releases. An OCI image would add a distribution to support, while a dev container would duplicate the locked setup and could not stand in for native ComfyUI Desktop validation. Revisit with a concrete container workflow. |
| Codespaces and Copilot code review | These are metered products. The locked local toolchain, existing CI, and maintainer review cover their current CiviScribe use cases. |

GitHub sources checked November 28, 2026.

- [Free plan](https://docs.github.com/en/get-started/learning-about-github/githubs-plans) and [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [Ruleset API schema](https://docs.github.com/en/rest/repos/rules) and [code scanning merge protection](https://docs.github.com/en/code-security/concepts/code-scanning/merge-protection)
- [Troubleshooting required status checks](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks) and [merge queue availability](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request-with-a-merge-queue)
- [Public security features](https://docs.github.com/en/code-security/getting-started/github-security-features) and [validity checks](https://docs.github.com/en/code-security/concepts/secret-security/validity-checks)
- [Artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations), [Packages billing](https://docs.github.com/en/billing/concepts/product-billing/github-packages), and [spending controls](https://docs.github.com/en/billing/how-tos/set-up-budgets)

## Security and dependency checks

- Private vulnerability reporting, Dependabot security updates, secret
  scanning, and secret push protection are enabled.
- Default CodeQL setup uses the extended query suite for Actions, Python,
  and JavaScript/TypeScript, with local and remote input sources.
- Actions' default token permissions are read-only. Workflows declare the
  additional permissions their individual jobs require.
- Repository settings require workflow actions to use full commit SHAs. The
  offline public-project check enforces the same rule in source before changes
  reach GitHub.
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
python -m tools.validate_public_project
```

The offline check validates relative repository links, links to versioned wiki
pages and anchors, documented schema input names, and JSON examples. Nox's
Python session includes it. The runnable save example is also exercised by
the isolated ComfyUI browser tests.

Wiki Markdown lives in `docs/wiki`. The Website workflow tests the generated
site, then publishes those reviewed pages to the existing wiki with a job-scoped
`GITHUB_TOKEN`. Only that job receives `contents: write`; pull requests cannot
publish. It preserves attachments, rejects unmanaged extra Markdown, uses a
fast-forward push, and verifies the published pages from a fresh clone.
The signed Pages deployment depends on that wiki readback.

The website renders the five standard project pages directly from root Markdown.
Changing the roadmap, support, security, contributor, or community source triggers
the same website checks. The offline integration validator checks navigation,
package-version identity, guide inventories, and complete action commit pins.
The scheduled **Public documentation audit** compares live website bytes and
wiki pages with their reviewed source and checks public repository entry points.
It reports drift through a failed check; it does not alter content or create
issues or messages.

The November 24 website scan at
[`9a8a1ad`](https://github.com/chriscollins500/ccollins-civiscribe/commit/9a8a1adf78563f621ab808a5459954d9faf51385)
reports zero findings for all configured languages. The website build and audit
tools use the existing containment helper; the seventeen initial website path
findings cleared through source fixes. No alerts were dismissed and the stock
extended suite and local-input analysis remained enabled.

## Settings references

The following primary references were checked on November 14, 2026.

- [GitHub repository rules](https://docs.github.com/en/rest/repos/rules)
- [CodeQL default setup](https://docs.github.com/en/rest/code-scanning/code-scanning#update-a-code-scanning-default-setup-configuration)
- [Dependabot ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories)
- [Dependency review action](https://github.com/actions/dependency-review-action)
- [Actions permissions](https://docs.github.com/en/rest/actions/permissions)
- [Immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
- [GitHub CLI release creation](https://cli.github.com/manual/gh_release_create)

Additional primary references checked November 24, 2026:

- [Wiki Git publishing](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages)
- [GitHub's wiki-token guidance](https://github.com/orgs/community/discussions/25929)
- [Actions security and token permissions](https://docs.github.com/en/actions/reference/security/secure-use)
