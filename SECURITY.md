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

## Verify a release download

CiviScribe publishes signed build provenance for the GitHub release assets,
including the ZIP sent to the ComfyUI Registry. To check the 2.0.9 Registry
ZIP, run this in its download folder with GitHub CLI:

```powershell
gh attestation verify ccollins-civiscribe-2.0.9-registry.zip --repo chriscollins500/ccollins-civiscribe --signer-workflow chriscollins500/ccollins-civiscribe/.github/workflows/publish.yml --source-ref refs/heads/main --source-digest 5262524168e7ba16661359778ad0e4ca277a3dac --deny-self-hosted-runners
```

For other releases, use the asset filename and the full commit for the
expected release tag. A successful check ties those bytes to this repository,
commit, and publication workflow on a GitHub-hosted runner. See the
[GitHub CLI verification reference](https://cli.github.com/manual/gh_attestation_verify).
