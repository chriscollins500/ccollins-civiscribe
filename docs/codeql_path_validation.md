# Development-tool path validation

The November 16, 2026 refactor addresses CodeQL alerts #11–20 in the workflow
coverage auditor, sidecar validator, and release staging tools. These commands
accept locations selected by the local operator, including folders outside the
repository. The save-node runtime does not import these tools.

## Boundary and implementation

`tools/audit_paths.py` separates normalization, containment, and filesystem use:

1. Normalize paths with the standard library's `realpath`, or `abspath` when
   inspecting the link itself.
2. Require the component-aware common path to equal the selected root. This
   rejects traversal, sibling names that share a prefix, and different drives
   or UNC shares. Preserve Windows case-insensitive comparisons and spelling.
3. Check the separator-terminated prefix before subsequent filesystem access.
   The selected root itself is also allowed. This form is understood by the
   stock CodeQL path-injection rule.
4. Retain `Path.resolve()` and the final component containment check. Link loops
   retain their sanitized diagnostic; resolution cannot silently move the
   returned path outside the selected scope.

Workflow root inspection resolves the parent before checking the final
component as a link or junction. It must inspect the actual selected path,
including when intermediate links and `..` occur together. It still rejects
linked roots and skips linked directories and files. Windows junctions and
POSIX symlinks have separate real filesystem regressions.

No-overwrite staging, bounded parsing, sidecar privacy checks, network request
checks, and runtime output-root restrictions are retained. This refactor does
not make concurrent filesystem replacement atomic; existing protections and
their limits still apply.

## Analyzer evidence

The isolated baseline was taken from source commit
`12b985d81ab7170bf023939b76fec7418ee13b4c`. It reproduced exactly the ten
`py/path-injection` findings reported by GitHub.

The candidate was checked with GitHub's matching CodeQL CLI **2.27.4**,
`codeql/python-queries` **1.9.0**, and `codeql/python-all` **7.2.9**. The complete
stock Python `security-extended` suite ran with remote and local sources enabled.
It reported **zero repository findings**.

The same scan included an isolated copy of
`tests/security/path_injection_controls.py.txt`. All **seven unsafe operations**
were reported: raw reading, link inspection, directory creation, exclusive
writing, normalization without containment, an unchecked child added after
validation, and a helper with missing containment. All **four validated
operations** remained unreported. The fixture is never executed. Its `.txt`
suffix keeps intentionally vulnerable examples out of ordinary production
analysis; it does not exclude any application or tool source.

No CodeQL queries, threat models, workflow settings, or source paths were
disabled or excluded. No custom sanitizer model or alert dismissal is used.
A successful scan job alone is insufficient: check the analysis results for
the exact source commit and confirm alerts #11–20 become `fixed`.

## Reproducing the analyzer controls

Use an official CodeQL bundle matching the versions above. Set `$codeql` to its
executable. The temporary directory below must be new for each run. These
commands create an isolated source snapshot without executing the fixture:

```powershell
$work = Join-Path (Get-Location) '.tmp/codeql-path-check'
$source = Join-Path $work 'source'
New-Item -ItemType Directory -Path "$source/tools" -Force | Out-Null
Copy-Item tools/audit_paths.py, tools/__init__.py "$source/tools"
Copy-Item tests/security/path_injection_controls.py.txt "$source/controls.py"
& $codeql database create "$work/database" --language=python --source-root=$source --build-mode=none
& $codeql database analyze "$work/database" 'codeql/python-queries@1.9.0:Security/CWE-022/PathInjection.ql' --threat-model=local --format=sarif-latest --output="$work/results.sarif"
```

The reported path-injection locations must exactly match the seven lines
marked `UNSAFE`, with no findings on the four `SAFE` lines or the helper.
For the full repository check, extract tracked Python files into a separate
source snapshot and analyze
`codeql/python-queries@1.9.0:codeql-suites/python-security-extended.qls` with
`--threat-model=local`. Default remote sources remain enabled.

## Behavior and project gates

The focused regressions cover external and relative locations, Unicode names,
filesystem roots, traversal and prefix lookalikes, Windows drive and UNC
boundaries, real junctions and symlinks, broken links, escaping aliases,
sanitized loop errors, and exclusive staging. A separate Windows differential
check compared the original and refactored helper across **400 filesystem
cases** with **zero differences**.

Run the normal project gate:

```powershell
.\.venv\Scripts\python.exe -m nox -s python frontend build
```

Windows runs real junction regressions without requiring symbolic-link
privileges. Three file-symlink/loop cases run on POSIX CI instead. The
Windows-only drive/UNC case is skipped on POSIX. The normal gate still enforces
100 percent runtime statement and branch coverage, frontend checks, wheel
inspection, and private ZIP construction/audit. Building test artifacts does
not publish a release or install/restart ComfyUI.

The Windows validation used PowerShell 7.6.9 and project Python 3.12.16.
The final Python gate passed **1,579 tests**, with three platform skips and
12 tests outside the standard gate deselected, at **100 percent statement
and branch coverage**. All **31 frontend tests** passed. Wheel inspection
and the **100-member private ZIP audit** passed. After the final link-inspection
refinement, the Python gate and the full CodeQL Python suite were rerun.

## Primary references

Checked November 16, 2026:

- [CodeQL path-injection rule](https://codeql.github.com/codeql-query-help/python/py-path-injection/)
- [Pinned normalization and prefix models](https://github.com/github/codeql/blob/codeql-cli/v2.27.4/python/ql/lib/semmle/python/frameworks/Stdlib.qll)
- [Pinned path-injection configuration](https://github.com/github/codeql/blob/codeql-cli/v2.27.4/python/ql/lib/semmle/python/security/dataflow/PathInjectionQuery.qll)
- [Official CodeQL bundle](https://github.com/github/codeql-action/releases/tag/codeql-bundle-v2.27.4)
