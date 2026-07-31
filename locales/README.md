# Locales

English is the canonical CiviScribe locale. The package uses ComfyUI's native
`locales/<language>/nodeDefs.json` convention and currently ships every locale
offered by the supported ComfyUI Desktop frontend:

`ar`, `en`, `es`, `fa`, `fr`, `ja`, `ko`, `pt-BR`, `ru`, `tr`, `zh`, and
`zh-TW`.

Run `python tools/validate_locales.py locales` to reject duplicate JSON keys,
missing locales, recursive key/type drift, blank strings, control characters,
unsafe bidi controls, and placeholder differences. Frontend tests also generate
expanded and right-to-left pseudo-locales without shipping them.

The validator proves structural and safety parity, not linguistic quality.
Translations still require human review before a public release.
