# Security Policy

## Supported version

Security fixes apply to the current CiviScribe 2.x release line.

## Reporting

Report suspected vulnerabilities privately to the repository owner before
opening a public issue. Do not include API tokens, private model paths, prompts,
workflows, generated images, or other sensitive data in a report.

## Security boundaries

- Civitai lookup is disabled by default.
- Lookup sends only model hashes or an explicit model version ID over verified
  HTTPS.
- The node does not upload images, prompts, workflows, or sidecars.
- Model files are read only after scanner-selected values resolve beneath
  ComfyUI-approved model roots.
- Output paths remain beneath ComfyUI's configured output directory.
- Metadata, cache, lookup, and sidecar failures cannot prevent writable pixels
  from being saved.
- Persistent caches reject absolute paths and secret-bearing values.
- Release archives are built from an allowlist and scanned for private paths,
  secrets, caches, and development-only content.
