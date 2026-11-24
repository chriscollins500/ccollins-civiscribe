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

## Native API integration

CiviScribe's discovery, OpenAPI, and metadata-preflight routes run on the
existing ComfyUI server and inherit its access controls and middleware. They
add no listener or authentication service. Preflight accepts bounded strict
JSON and performs no execution, model-file reads, directory creation, cache
writes, or Civitai lookup. It does not echo prompts or raw workflow payloads.

Save reports use standard ComfyUI history text outputs and the official MCP's
job text projection. They contain committed output descriptors and status
codes. They add no persistent catalog. Operators remain responsible for
controlling access to the host ComfyUI's workflow, history, and output routes.
See the [API contract](docs/api_and_mcp.md) for exact limits and boundaries.

## Verify a release download

CiviScribe publishes signed build provenance for the GitHub release assets,
including the ZIP sent to the ComfyUI Registry. To check the 2.0.12 Registry
ZIP, run this in its download folder with GitHub CLI. Resolve the release tag's
commit independently of the downloaded artifact:

```powershell
$releaseCommit = gh api repos/chriscollins500/ccollins-civiscribe/commits/v2.0.12 --jq .sha
gh attestation verify ccollins-civiscribe-2.0.12-registry.zip --repo chriscollins500/ccollins-civiscribe --signer-workflow chriscollins500/ccollins-civiscribe/.github/workflows/publish.yml --source-ref refs/heads/main --source-digest $releaseCommit --deny-self-hosted-runners
```

For other releases, use the asset filename and the full commit for the
expected release tag. A successful check ties those bytes to this repository,
commit, and publication workflow on a GitHub-hosted runner. See the
[GitHub CLI verification reference](https://cli.github.com/manual/gh_attestation_verify).

## Website and documentation

The [website](https://chriscollins500.github.io/ccollins-civiscribe/) and wiki
render reviewed documentation from this repository. The website is static;
its educational demos do not contact ComfyUI or Civitai. It uses no analytics,
external scripts, fonts, or runtime CDNs. Optional theme preferences stay in
browser-local storage. GitHub provides hosting and applies its own access
logging and privacy policy.

The Website workflow tests the generated pages, synchronizes the wiki, and
attests the exact Pages artifact before deployment. Its provenance is separate
from node-release attestations and uses `.github/workflows/pages.yml`.
The artifact's source commit identifies the documentation build; it is not
necessarily a software release tag. See the
[website verification instructions](docs/site/README.md#verify-a-deployment).

Use [private reporting](https://github.com/chriscollins500/ccollins-civiscribe/security/advisories/new)
for vulnerabilities. Ordinary documentation corrections belong in the
[documentation form](https://github.com/chriscollins500/ccollins-civiscribe/issues/new?template=documentation.yml).
