# CCollins' CiviScribe V2 Documentation Tooling

Status: accepted for V2 implementation.

This audit selects documentation tools by correctness, accessibility, privacy,
maintenance cost, and fit with CiviScribe. It does not add documentation tools
to the end-user runtime or installable custom-node package.

## 1. Documentation Contract

CiviScribe has two documentation surfaces:

1. ComfyUI-native Markdown help is the primary in-application user surface.
2. Repository Markdown is the source of design, contributor, security, and
   release documentation.

A separately generated documentation website is optional. It must not become a
prerequisite for using the node, and generated site files must not enter the
custom-node ZIP or wheel.

The source format remains portable CommonMark-compatible Markdown with small,
explicit extensions for tables, fenced code, and Mermaid diagrams. Tool-specific
syntax is permitted only when it has a useful plain-Markdown fallback.

Documentation tooling must:

- run only in development and CI environments;
- keep links and assets local by default;
- make no analytics, tracking, font, or CDN requests;
- preserve readable source diffs;
- treat examples and diagrams as testable artifacts;
- validate keyboard, screen-reader, contrast, and responsive behavior;
- support the current ComfyUI localization model;
- avoid executing arbitrary shell examples or untrusted documentation;
- never place private paths, credentials, tokens, or generated user data in
  published output.

The current ComfyUI help-page and localization references are:

- <https://docs.comfy.org/custom-nodes/help_page>
- <https://docs.comfy.org/custom-nodes/i18n>

## 2. Repository Observations

At audit time, the repository contained 131 Markdown files outside virtual
environments and dependency directories. Eighty were under the prototype
`docs/dev` archive, five were V2 design-authority files, and five were current
ComfyUI node-help files.

This means one global enforcement level would be counterproductive. V2 and
current user documentation receive strict structural checks. Historical
prototype documents remain searchable evidence and receive only privacy,
broken-link, and gross-syntax checks unless they are promoted into current
documentation.

Current node help is English Markdown plus ComfyUI locale definitions. V2 keeps
native localized node help close to ComfyUI instead of making an external site
the source required by the application.

## 3. Static-Site Generator Bake-Off

The same five V2 Markdown pages were built in isolated environments with:

- MkDocs core;
- MkDocs Material;
- Zensical;
- Sphinx with MyST, Furo, and `sphinxcontrib-mermaid`.

All builds used explicit navigation and strict warning handling. External fonts
and optional syntax-highlighting CDNs were disabled where supported. The
architecture document supplied two real Mermaid diagrams as the extension
stress case.

Versions tested:

| Candidate | Version |
| --- | --- |
| MkDocs | 1.6.1 |
| MkDocs Material | 9.7.7 |
| Zensical | 0.0.51 |
| Sphinx | 9.1.0 |
| MyST Parser | 5.1.0 |
| Furo | 2025.12.19 |
| sphinxcontrib-mermaid | 2.0.3 |

Warm local build and output observations are comparative measurements, not
product performance guarantees:

| Candidate | Build | Environment packages | Output files | Output size |
| --- | ---: | ---: | ---: | ---: |
| MkDocs core | 0.17 s | 17 | 33 | 2,274,375 bytes |
| MkDocs Material | 0.46 s | 29 | 52 | 2,790,669 bytes |
| Zensical | 0.33 s | 11 | 17 | 796,320 bytes |
| Sphinx/MyST/Furo | 1.90 s | 35 | 44 | 1,185,361 bytes |

The generated architecture pages were loaded in Playwright at desktop and
mobile widths with all non-local requests blocked, then scanned with Axe:

| Candidate | Serious or critical Axe findings | Other observed problems |
| --- | ---: | --- |
| MkDocs core | 1 rule, 20 contrast nodes | No Mermaid rendering; page-script errors |
| MkDocs Material | 2 rules | Mermaid requested from `unpkg.com` |
| Zensical | 3 rules, including 2 critical | Mermaid requested from `unpkg.com` |
| Sphinx/MyST/Furo | 0 | 2 moderate landmark findings; Mermaid requested from jsDelivr |

None of the generated sites had desktop or mobile horizontal overflow in the
tested viewports.

### Decision

Do not add a static-site generator merely because one is available. Native
ComfyUI help and repository Markdown meet the V2 product need today.

If a standalone public site becomes a real release requirement,
Sphinx/MyST/Furo is the preferred starting point because it had the strongest
accessibility result in this audit, mature strict-build behavior, Markdown
support, and established localization support. It is not approved for
publication unchanged. Before adoption:

1. Vendor pinned Mermaid and other assets locally.
2. Remove every external runtime request.
3. Correct the two moderate landmark findings.
4. Require zero known Axe violations at supported desktop and mobile widths.
5. Keep source Markdown portable and generated output outside package
   artifacts.

MkDocs Material is not selected because the tested build had serious
accessibility findings, a remote diagram dependency, and a current ecosystem
transition warning. Zensical is promising and was the leanest candidate, but
the tested theme's critical accessibility findings make adoption premature.
MkDocs core does not provide enough diagram and accessible-theme behavior
without additional work that recreates a theme project.

References:

- <https://www.sphinx-doc.org/en/master/usage/markdown.html>
- <https://myst-parser.readthedocs.io/>
- <https://pradyunsg.me/furo/>
- <https://www.mkdocs.org/>
- <https://zensical.org/about/roadmap/>

## 4. Markdown Structure

`markdownlint-cli2` 0.23.1 with `markdownlint` 0.41.1 is selected for current
V2, user, security, and contributor Markdown.

The stock rule set reported 136 findings in three V2 files. The findings were
almost entirely three policy mismatches rather than malformed Markdown:

- `MD013` imposed an 80-column limit that conflicts with readable tables and
  does not match the repository's 120-column code policy.
- `MD024` rejected repeated subsection names in different parent sections.
- `MD060` rejected valid compact table delimiters.

With `MD013` disabled, `MD024.siblings_only` enabled, and `MD060` disabled, all
five V2 files passed. All other default rules remain enabled. These exceptions
are narrow and documented rather than a blanket reduction in linting.

Historical prototype documents are excluded from the strict gate until edited
or promoted. New current documents do not inherit that exemption.

Reference: <https://github.com/DavidAnson/markdownlint-cli2>

## 5. Spelling and Prose

### Spelling

`codespell` 2.4.3 is selected as the default typo checker.

On the five V2 documents:

- `codespell` reported zero findings;
- CSpell 10.0.1 reported 173 findings across all five files.

The CSpell findings were overwhelmingly valid product, Python, ComfyUI,
Civitai, image-format, and model terminology. CSpell remains a reasonable
future option for TypeScript identifier checking, but it would require a large
project dictionary before providing useful signal. The lower-noise tool is the
more correct default for current documentation.

Both tools remain advisory for translated text. Locale-specific quality checks
must use an appropriate language dictionary or human review rather than an
English-only gate.

References:

- <https://github.com/codespell-project/codespell>
- <https://cspell.org/>

### Prose

Vale 3.15.1 was tested with its current Google package at warning level. It
reported 222 findings:

- 141 `Vale.Spelling`;
- 64 `Google.Headings`;
- 17 findings across the remaining style rules.

The default package is too noisy to gate this repository. Vale is approved only
as an advisory tool after CiviScribe has:

1. a project vocabulary;
2. rules scoped separately to user, contributor, API, and historical text;
3. a reviewed baseline;
4. a ratchet that prevents new findings without forcing unrelated rewrites.

No generic readability score becomes a release gate. Clear task completion and
technical accuracy matter more than optimizing prose for a synthetic score.

Reference: <https://vale.sh/>

## 6. Link Validation

Lychee 0.24.2 is selected.

The standalone Windows binary checked both external links in the V2 authority
documents successfully in 0.86 seconds. It used the working system trust path
without changing TLS verification.

`markdown-link-check` 3.14.2 also passed the V2 files after Node was explicitly
configured to use the system certificate store. It brings a large Node
dependency tree for a narrower job.

LinkChecker 10.6.0 correctly crawled 49 generated-site URLs but attempted to
create user-level configuration files and failed external TLS validation
through its default Certifi path in the audited environment. It is not
selected.

Policy:

- missing local files, anchors, and generated-site links fail CI;
- external links run with bounded concurrency and timeouts;
- transient external failures are reported separately and do not silently
  redefine a valid local build as invalid;
- TLS verification is never disabled.

Reference: <https://github.com/lycheeverse/lychee>

## 7. Executable Examples

Sybil 10.1.0 is selected for explicitly executable Python examples.

Its Markdown parser collected a fenced Python example, failed when the expected
digest was intentionally wrong, and passed after the example was corrected.
This proves both collection and failure propagation in the intended source
format.

Only examples explicitly designated as executable are collected. Shell,
PowerShell, network, installation, file-deletion, and user-workflow examples
are never executed merely because they appear in Markdown. JSON examples use
the project's JSON and schema validators. Command examples receive syntax or
argument-level tests in dedicated test code.

Doctest remains suitable for docstrings. Sybil covers narrative Markdown where
doctest is not a natural fit. `pytest-codeblocks` is unnecessary duplication.

Reference: <https://sybil.readthedocs.io/>

## 8. Diagrams

Mermaid remains the selected source format for architecture diagrams because
it is text-reviewable and already used by the V2 architecture.

The current Mermaid browser parser validated both V2 diagrams. Diagram
validation reuses the existing Playwright installation and a pinned local
Mermaid browser bundle. This avoids adding Puppeteer through Mermaid CLI and
avoids remote scripts.

Published diagrams must:

- parse successfully;
- render locally with the network blocked;
- include nearby prose that communicates the same essential information;
- remain legible at desktop and mobile widths;
- avoid conveying meaning by color alone.

Reference: <https://mermaid.js.org/>

## 9. Accessibility and Visual Validation

Reuse the accepted Playwright and Axe stack. Do not add a second browser
automation framework.

Current documentation gates are:

- one page-level `h1`;
- valid landmark structure;
- keyboard-operable navigation and search;
- accessible names on controls and dialogs;
- no serious, critical, or accepted-known Axe violations;
- no desktop or mobile horizontal overflow;
- locally rendered diagrams;
- no blocked or attempted external asset hosts;
- light, dark, forced-colors, 200 percent zoom, and reduced-motion checks when a
  standalone site is introduced.

Screenshots are diagnostic artifacts, not the accessibility assertion.

References:

- <https://playwright.dev/>
- <https://github.com/dequelabs/axe-core-npm/tree/develop/packages/playwright>

## 10. Localization

The primary node-help source follows current ComfyUI localization conventions.
V2 adds a small parity validator rather than a translation framework:

- every supported locale has the required node-help file and node keys;
- required headings and anchors have locale equivalents;
- code, widget names, AIR examples, paths, and JSON keys remain unchanged where
  translation would make them incorrect;
- missing translations fall back to English in the same way as the current
  ComfyUI surface;
- right-to-left locales receive layout and keyboard tests;
- human review remains required for release text.

If a standalone Sphinx site is later adopted, Sphinx gettext catalogs may
support that site. They do not replace ComfyUI-native localized help.

Machine translation is never silently committed as authoritative
documentation.

## 11. Deferred Generators

Do not add `mkdocstrings`, pdoc, or another Python API generator until V2 has an
intentional public Python API. Internal modules are not documentation promises.

When V2 schemas stabilize, generate reference tables from the authoritative
Pydantic or JSON Schema definitions. Do not maintain a second hand-written
field registry. Evaluate a schema renderer only against the real V2 schemas.

Do not introduce Docusaurus, VitePress, a React documentation application, or a
documentation database. Those systems add a frontend product where this
project currently needs validated reference material.

## 12. Accepted Development Profile

The V2 documentation profile is:

- Markdown as source;
- current ComfyUI-native Markdown for node help;
- `markdownlint-cli2` for structure;
- `codespell` for low-noise typo detection;
- Lychee for links;
- Sybil for selected Python examples;
- project JSON/schema validators for data examples;
- pinned local Mermaid plus Playwright for diagram parsing and rendering;
- Playwright plus Axe for accessibility and responsive validation;
- Vale advisory only after a project ruleset and vocabulary exist;
- no static-site generator until a standalone site is required;
- Sphinx/MyST/Furo as the preferred site candidate subject to the acceptance
  work in section 3.

All versions are pinned in the development lockfile when V2 implementation
begins. Generated site files, downloaded validator binaries, test browser data,
and documentation caches are excluded from installable artifacts.
