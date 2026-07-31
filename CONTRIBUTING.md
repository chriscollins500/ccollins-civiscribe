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
