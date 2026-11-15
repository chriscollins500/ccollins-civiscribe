# Wheel-checker compatibility migration

The November 15, 2026 migration uses the upstream wheel-filename 2.x support
in check-wheel-contents. The source and parser versions are pinned together.

| Component | Previous | Pinned candidate |
| --- | --- | --- |
| check-wheel-contents | PyPI 0.6.3 | Upstream 0.7.0.dev1 |
| Upstream commit | Released package | `ab1f393c85c30538898fa1f4c73abc13898b0d65` |
| wheel-filename | 1.4.2 | 2.1.0 |

The [source pin](../pyproject.toml) and lockfile use the full commit, never a
moving branch. The installed package's PEP 610 metadata must identify that
repository and commit. No installed third-party files are modified and no
upstream dependency requirements are overridden.

This checker version is unreleased upstream code. The pin is limited to the
development dependency group. Normal CiviScribe installation retains the same
runtime dependencies and does not install the checker or its parser.

## Independent baseline comparison

The reference was the installed check-wheel-contents 0.6.3 with wheel-filename
1.4.2, at CiviScribe commit `2287b7a5444e0be6a737234b4895daa1937c475f`.
The candidate was installed first in a separate cached environment.

Both implementations were run against the same generated wheel corpus:

- fourteen negative cases, one for every rule W001–W010, W101–W102, and
  W201–W202;
- thirteen archive/metadata failures, including missing WHEEL/RECORD files,
  invalid headers, directory mismatches, unsafe RECORD paths, duplicate
  entries, invalid sizes and filenames, and a corrupt ZIP; and
- nine valid layouts, including build tags, platform-root and relocated
  libraries, allowed empty duplicates, stub packages, package-tree matching,
  and intentionally configured top-level names.

All 36 results matched, including process exit status, reported rule IDs, and
failure category. Both implementations also accepted the exact hosted
CiviScribe wheel from the reference commit, identified by its SHA-256.
Comparison of the fourteen rule bodies found no implementation changes.

The ten W001–W010 checks apply with the current default build command. The
four W1/W2 checks need explicit package-tree or top-level arguments; those
options are exercised in the corpus as well.

## Permanent validation

[The frozen baseline](../tests/fixtures/wheel-checker/contract.json) records
the old tool's normalized results without local paths or user data.
[The regression tests](../tests/unit/test_wheel_checker_contract.py) rerun all
36 cases, verify coverage of every rule, and check the installed source and
parser versions. The standard Python gate includes these 38 tests.

The existing build session continues to check the newly built real wheel.
The full local candidate command is:

```powershell
.\.venv\Scripts\python.exe -m nox -s release
```

The hosted release-validation workflow additionally exercises exact built
packages on Linux, Windows, and macOS, independent image readers on Linux,
and a fresh isolated ComfyUI instance with Playwright and Axe.

The November 15 local gate passed 1,530 standard Python tests with 100%
statement and branch coverage, 31 frontend tests, 10 release tests, and two
performance checks. Formatting, linting, strict typing, dependency audits,
wheel inspection, source-distribution construction, and private-ZIP auditing
also passed. An isolated import from the built wheel succeeded.

These representative regressions preserve the existing checks; they are not
an exhaustive proof of equivalence for every malformed wheel.

## Updating the pin

Review the upstream diff and compare the corpus before updating the source
revision or parser. Update the reviewed-source record deliberately and rerun
the full local and hosted candidate gates. When a compatible upstream release
is available on PyPI, the Git source can be retired after the same checks pass.

## Primary references

Checked November 15, 2026:

- [Reviewed upstream diff](https://github.com/jwodder/check-wheel-contents/compare/v0.6.3...ab1f393c85c30538898fa1f4c73abc13898b0d65)
- [Pinned upstream requirements](https://github.com/jwodder/check-wheel-contents/blob/ab1f393c85c30538898fa1f4c73abc13898b0d65/pyproject.toml)
- [uv Git source pinning](https://docs.astral.sh/uv/concepts/projects/dependencies/#git)
