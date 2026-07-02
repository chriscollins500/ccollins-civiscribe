# Security And Privacy Audit

Version audited: 0.9.17

## Summary

The package follows a local-first, pixels-first design. Metadata, lookup, hashing, sidecars, and diagnostics are best effort. The main image save path should continue unless image writing itself fails.

## Network Boundary

Allowed network behavior:

- Optional Civitai identity lookup when `enable_civitai_lookup` is true.
- Requests send only model hash values or modelVersionId values needed for identity resolution.
- API base URL must be HTTPS.
- SSL verification remains enabled.

Disallowed behavior:

- No image upload.
- No model download or install.
- No prompt/workflow/sidecar/local path data sent to Civitai.
- No token support in the node.
- No frontend JavaScript network calls.

## TLS / SSL

The lookup client uses Python `urllib` with verified SSL contexts. It can use certifi's CA bundle and can fall back to the verified system default trust store. It does not set `verify=False`, `CERT_NONE`, or `check_hostname=False`.

Lookup failures such as timeout, DNS, SSL, HTTP status, malformed JSON, missing identity fields, and type mismatch are warnings only. They do not block pixel saving.

## Input And Metadata Safety

The package treats prompts, workflows, sidecars, API responses, and user JSON as data only:

- No `eval`.
- No `exec`.
- No pickle.
- No YAML.
- JSON uses `json.loads` / `JSON.parse`.
- API responses and manual JSON are sanitized before metadata output.

Redaction removes or masks:

- Windows absolute paths.
- UNC paths.
- POSIX absolute paths.
- token-like assignments.
- sensitive keys.
- null bytes and control characters.

## File Safety

Image writes are confined to ComfyUI's configured output directory through path normalization and traversal checks. Sidecar paths are derived from already-safe image paths and must remain inside the output directory.

Hashing reads only resources resolved under approved model roots. Absolute model paths outside known roots are rejected with warnings.

## Cache Safety

Persistent hash cache entries store:

- safe model root category.
- Comfy-relative selected value.
- file size.
- modified time.
- hash values.

They do not store prompts, workflows, images, sidecars, tokens, or absolute private paths.

Identity cache import/export uses a readable JSON format and rejects or redacts unsafe fields. Pinned/locked identity behavior is preserved.

## Sidecar Safety

Sidecars are optional diagnostics:

- UTF-8 RFC8259 JSON.
- JSON Schema Draft 2020-12 validation is available through a tool.
- Sidecar failure never blocks image saving.
- Sidecars contain privacy flags and sanitized warnings/errors.
- `createdAt` is sidecar-only and documented.

## EXIF Safety

PNG output always includes a Civitai-style EXIF `UserComment` layer unless EXIF writing fails and pixels-first fallback drops it. The EXIF writer:

- writes only `UserComment`;
- uses the EXIF `UNICODE` prefix with UTF-16BE text;
- does not write camera, lens, GPS, artist, copyright, serial-number, or fake provenance tags;
- uses the same sanitized prompt/settings/resource objects as the existing metadata path;
- does not perform network calls, file reads, or identity guessing.

`civitai_exif_minimal` removes PNG text/iTXt chunks only when explicitly enabled by the user. It does not change lookup, hashing, cache, or redaction behavior.

## Frontend Safety

The frontend extension:

- Uses `app.registerExtension`.
- Has no network calls.
- Does not generate metadata.
- Does not parse JSON for authority; backend parsing remains authoritative.
- Fails closed if widgets are missing or ComfyUI frontend APIs shift.

## Known Residual Risks

- Civitai upload parsing is external behavior and can change. Use the recognition harness before changing production metadata emission.
- Python TLS trust can be affected by local antivirus/proxy interception. Use `tools/diagnose_civitai_lookup_ssl.py`.
- Broad exception handlers in `nodes.py` are intentional pixels-first guards. They should remain scoped to metadata/diagnostic subsystems and continue to record sanitized warnings.
