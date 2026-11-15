# Frontend lint and compiler migration

The November 14, 2026 migration replaces ESLint and typescript-eslint with
type-aware Oxlint and TypeScript 7. Prettier, the frontend behavior tests, the
strict compiler options, and the Python validation profile remain in use.

## Compared versions

| Tool | Baseline | Candidate |
| --- | --- | --- |
| ESLint | 10.15.0 | Replaced by Oxlint 1.93.0 |
| typescript-eslint | 8.72.2 | Replaced by oxlint-tsgolint 7.0.2007 |
| TypeScript | 6.0.3 | 7.0.2 |
| Prettier | 3.10.1 | 3.10.1 |

The baseline is commit `0915e46538e30798ae7bd694545a0990eaae70f4`.
Candidate packages were first installed in an isolated, version-pinned test
environment so the original compiler and ESLint implementation could serve
as independent references. No installed third-party files were patched.

## Preserved checks

The resolved baseline enabled 119 checks for TypeScript and 91 for JavaScript,
with 137 distinct rule names across the two scopes. Forty-two require type
information. All 14 existing source and test files were compared individually.

The initial migration helper omits three rules unless nursery rules are
included. The final configuration explicitly preserves `no-undef`,
`no-useless-assignment`, and `typescript/no-unnecessary-condition`.

[The frozen contract](../tests/fixtures/frontend-lint/contract.json) retains
the original severities, resolved options, compiler settings, and one original
synthetic negative example for each rule. Both baseline ESLint and the
candidate rejected every negative example. The source and examples contain
no private workflows, prompts, model paths, or generated images.

The configuration translates four TypeScript extension rules to their native
Oxlint equivalents: array constructors, unused expressions, unused variables,
and useless constructors. Duplicate arguments and legacy octal literals are
rejected by the module parser. Strict-mode parser errors also reject deletes
of local variables, `with` statements, and invalid decimal escapes.

Oxlint does not accept the `preserve-caught-error.errorClassNames` option.
The baseline value is an empty list, so the configuration omits that empty
list while preserving `requireCatchParameter: false`. A future nonempty list
requires a fresh compatibility review.

## Ongoing regression gate

`npm run check` includes [the frontend contract tests](../tests/frontend/lint-contract.test.mjs):

- compare configured rule severities and options with the frozen baseline;
- reject all 137 synthetic violations with their expected rule or parser
  diagnostic and accept representative clean code;
- retain the original compiler settings and verify that the compiler and
  type-aware backend target the same TypeScript release; and
- reject twelve compiler strictness violations and verify `noEmitOnError`.

These are focused regression examples, rather than an exhaustive proof of
identical diagnostics for every possible JavaScript or TypeScript program.
Changes to the frozen contract need the same review as changes to the checks.

## Output and package validation

TypeScript 7 emitted byte-identical copies of all seven runtime JavaScript
files when compared with TypeScript 6.0.3. No frontend behavior adjustment or
weakened compiler flag was needed.

The full candidate gate is:

```powershell
.\.venv\Scripts\python.exe -m nox -s release
```

It runs Python, frontend, build, release interruption, benchmark, and
supply-chain sessions. The build audits the wheel, source distribution, and
private node ZIP. Browser tests against a working ComfyUI instance are a
separate opt-in operation.

The local November 14 gate passed with 1,492 standard Python tests, ten release
interruption tests, two performance tests, and 31 frontend tests. Python
statement and branch coverage were both 100 percent. The frontend tests include
the 137-rule negative corpus and twelve compiler strictness cases. The wheel
inspection, built-wheel import smoke, private-ZIP audit, npm audit, and runtime
Python dependency audit passed.

The subsequent dependency refresh upgraded 22 Python packages, including
pytest 9.2.0 with pytest-benchmark 5.3.1. The same checks passed after that
refresh. The publishing pin is Comfy CLI 1.26.0, checked against its real
Registry configuration and method signature without calling publication.
All pinned GitHub Actions already matched their latest official releases.
CI uses the Node 24.22.3 security release.

At that refresh, check-wheel-contents 0.6.3 still required wheel-filename 1.x,
so the lock retained 1.4.2. The November 15 [wheel-checker migration](wheel_checker_migration.md)
resolved that constraint using a tested upstream source pin and wheel-filename
2.1.0. Both packages remain development-only dependencies.

## Primary references

Checked November 14, 2026:

- [Oxlint migration guide](https://oxc.rs/docs/guide/usage/linter/migrate-from-eslint.html)
- [Oxlint type-aware rules and TypeScript requirements](https://oxc.rs/docs/guide/usage/linter/type-aware.html)
- [Native backend versioning and rule coverage](https://github.com/oxc-project/tsgolint#versioning)
- [Baseline typescript-eslint dependency requirements](https://typescript-eslint.io/users/dependency-versions/)
