# Models and resource identities

CiviScribe starts at each save node's image input and follows the selected
upstream path. This lets separate generation branches keep their own metadata.

## What it can detect

The scanner recognizes supported loaders and generation structures for primary
checkpoints, diffusion/UNET/GGUF models, LoRAs, VAEs, text and vision encoders,
embeddings, ControlNet, IPAdapter, style resources, model patches, and upscalers.
It records applicable model and CLIP strengths. Supported bundle loaders include
active ND Super and rgthree Power LoRA entries.

Detection depends on a node's class, inputs, and active connections. A newly
invented custom loader may need scanner support. Merely having a model file
or loader visible on the canvas does not establish that it contributed.

## Active branches

```text
Model A -> generation A -> image A -> CiviScribe A
Model B -> generation B -> image B -> CiviScribe B
```

Each save starts with its own executing node ID. Disconnected loaders and
resources on known inactive, muted, or bypassed branches are excluded. When
a dynamic selection cannot be proven, the uncertainty stays diagnostic.

## Detection and identification

A resource can be detected by its filename and role while its Civitai identity
is unresolved. CiviScribe uses explicit identities, workflow evidence, hashes,
local caches, and optional lookup to establish which listing and version it is.

An AIR is a structured resource identifier. It can identify a model version
and, when present, a particular file and format. File qualifiers matter when
a version offers several precision or quantization variants.

In 2.0.10, a matching short hash cannot override a conflicting known full
digest. The returned hash algorithm, file identity, and requested version
must agree with the available evidence.

## Resource states in a sidecar

| State | Meaning |
| --- | --- |
| `resolved` | Enough compatible identity evidence is present |
| `partial` | Some identity details are known, with completion still needed |
| `unresolved` | An active resource was found, but its identity remains unknown |
| `conflict` | Available evidence disagrees or matches multiple incompatible targets |

Structured metadata retains unresolved active resources. Compatibility output
includes only identities that meet its emission rules. Even a resolved record
can have file-scope or role constraints that affect parser-facing output.

Check `parserFacing`, `parserExclusionReason`, `identityScope`, and
`unresolvedReason` in the sidecar when investigating a missing credit.
[Metadata and sidecars](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Metadata-and-sidecars)

## Help with an unknown resource

Try optional lookup, review the hashing mode, or supply a verified preferred
primary identity. Manual mappings support several active resources. A filename
alone cannot prove a Civitai model or version.
[Civitai lookup and hashing](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Civitai-lookup-and-hashing)
