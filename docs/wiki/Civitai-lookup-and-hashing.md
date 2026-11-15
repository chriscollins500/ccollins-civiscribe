# Civitai lookup and hashing

Ordinary saving works locally. Turn on **Enable Civitai lookup** when you want
CiviScribe to ask Civitai to identify active resources using available hashes
or an explicit model-version ID.

## What a lookup shares

Requests contain a model hash or explicit version ID over verified HTTPS.
Images, prompts, workflows, sidecars, local paths, and model files stay local.
The node uses anonymous lookup and requires no API key.

Successful identities can be cached for later saves. Disable **Cache successful
lookup results** to stop storing new API identity results. Existing local
identity evidence can still be used.

## Choose a hashing mode

| Mode | Model-file behavior | When it helps |
| --- | --- | --- |
| `cached_only` | Reuses cached hashes and reads no model contents | Keep model-file reads minimal |
| `cached_or_fast` | Reuses hashes or computes the fast partial hash | Everyday default |
| `full` | Allows whole-file hashing when a cached result is unavailable | Obtain stronger file evidence for difficult identities |

All modes consult the local hash cache first. Full hashing can take noticeable
time for a large model and uses local disk reads. Model reads are restricted
to scanner-selected files beneath ComfyUI-approved model roots.

Available hashes can include SHA-256, AutoV1, AutoV2, AutoV3, CRC32, and BLAKE3.
Availability depends on the source. Local full hashing computes SHA-256 and
its compatible AutoV2/AutoV3 prefixes alongside supported local hashes.
The node preserves exact evidence and never substitutes one algorithm for
another merely because the text has the same length.

## Network behavior

**Lookup timeout** defaults to four seconds per request. A workflow can require
more than one request across its active resources. A timeout leaves the
resource unresolved and allows saving to continue.

When Civitai returns HTTP 429, CiviScribe starts a bounded shared cooldown for
that process. Saving proceeds with a diagnostic while lookup is unavailable.
Server errors and unavailable or ambiguous files also leave diagnostic results.

Civitai's documented archived or taken-down versions can omit file information.
An incomplete response cannot establish an exact file identity.
[Current Civitai model-version documentation](https://developer.civitai.com/site/reference/model-versions.md)

## Cache location

When ComfyUI provides its user directory, caches are stored beneath its
`ccollins-civiscribe` subfolder as `hash-cache.json` and `identity-cache.json`.
The fallback is `.ccollins-civiscribe` beneath the output root. Cache documents
are bounded, validated, and kept separate from image metadata.

For a diagnosis, inspect sidecar fields such as `hashStatus`, `lookupStatus`,
and `lookupDiagnostics`. Lookup being enabled does not guarantee a catalog
match for every local conversion or private model.
[Troubleshooting](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Troubleshooting)
