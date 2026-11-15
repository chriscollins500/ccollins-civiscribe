# Verify a release

CiviScribe releases include SHA-256 checksums and GitHub/Sigstore build
attestations. Verification ties downloaded bytes to the expected repository,
source commit, and publication workflow.

## For everyday installation

Use the official CiviScribe node-pack card in ComfyUI Manager or the project's
GitHub repository. Keep the installed version available when reporting a bug.
[Installation and updates](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Installation-and-updates)

## Verify a downloaded ZIP

With GitHub CLI installed and authenticated, open a terminal in a download
folder and run these PowerShell commands for 2.0.10.

```powershell
gh release download v2.0.10 --repo chriscollins500/ccollins-civiscribe --pattern ccollins-civiscribe-2.0.10-registry.zip
$releaseCommit = gh api repos/chriscollins500/ccollins-civiscribe/commits/v2.0.10 --jq .sha
gh attestation verify ccollins-civiscribe-2.0.10-registry.zip --repo chriscollins500/ccollins-civiscribe --signer-workflow chriscollins500/ccollins-civiscribe/.github/workflows/publish.yml --source-ref refs/heads/main --source-digest $releaseCommit --deny-self-hosted-runners
```

A successful result verifies the signature, exact digest, source commit, and
signer constraints. The same verification works for the other attested release
assets when you use their exact filenames.

The Registry ZIP is flat for the Registry installation process. The
`ccollins-civiscribe-2.0.10-private-test.zip` has one `ccollins-civiscribe/`
root for package testing. The wheel and source archive serve Python tooling.
Manager users can follow the ordinary installation guide.

## Check a checksum

Download `release-manifest.json` from the same release. Its artifact entries
contain each filename, byte size, and SHA-256 digest. Compute the local ZIP's
digest and compare it with its matching entry.

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath ccollins-civiscribe-2.0.10-registry.zip
```

Verify the manifest's attestation too when you rely on it as signed evidence.
A checksum comparison detects different bytes. Provenance adds the expected
source and workflow identity.

## How publication uses verification

The release workflow builds and tests a commit-bound bundle once. It signs
the seven named assets and their manifest, verifies all eight before creating
the GitHub release, and verifies the Registry ZIP again before upload.
The published Registry listing is checked after upload.

Attestations establish origin and integrity. Code review and functional tests
provide separate evidence about behavior. These attestations apply to the
distributed software artifacts. Generated images carry generation metadata.
[GitHub attestation documentation](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
· [CLI verification reference](https://cli.github.com/manual/gh_attestation_verify)
