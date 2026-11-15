# Security Policy

## Supported version

Security fixes apply to the current CiviScribe 2.x release line.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/chriscollins500/ccollins-civiscribe/security/advisories/new)
to send suspected vulnerabilities to the repository maintainer. Include the
affected version, minimal reproduction steps, and the expected impact. Review
reports for API tokens, private paths, prompts, workflows, images, and other
sensitive data before attaching them.

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
including the ZIP sent to the ComfyUI Registry. To check the 2.0.10 Registry
ZIP, run this in its download folder with GitHub CLI:

```powershell
gh attestation verify ccollins-civiscribe-2.0.10-registry.zip --repo chriscollins500/ccollins-civiscribe --signer-workflow chriscollins500/ccollins-civiscribe/.github/workflows/publish.yml --source-ref refs/heads/main --source-digest bba5ec8e0c52c5157246ac8d84cceaf1f53bb1fa --deny-self-hosted-runners
```

For other releases, use the asset filename and the full commit for the
expected release tag. A successful check ties those bytes to this repository,
commit, and publication workflow on a GitHub-hosted runner. See the
[GitHub CLI verification reference](https://cli.github.com/manual/gh_attestation_verify).
