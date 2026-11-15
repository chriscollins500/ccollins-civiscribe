# Manual resource identities

Use an explicit identity when you have verified the Civitai model version
your active resource represents. This is useful for catalog ambiguity,
mirrors, or model variants whose automated lookup remains incomplete.

## Pin the primary model

In **Preferred primary AIR or Civitai URL**, enter one of these forms, replacing
the illustrative numbers with the real model and version you verified.

```text
https://civitai.com/models/12345?modelVersionId=67890
67890
urn:air:sdxl:checkpoint:civitai:12345@67890
```

A model URL with a `modelVersionId` identifies a version. A bare model URL
can remain partial because one model can have many versions. A bare number
means a model-version ID. It does not mean a model ID.

Copy the exact AIR from a trusted source when available, preserving any file
and format qualifier. Enabling lookup can complete compatible version details.

## Map several resources

1. Enable **Write sidecar JSON** for a diagnostic save.
2. Find the active resource under `generationRecord.resources`.
3. Note its `key`, `nodeId`, `filename`, `selectedValue`, and known hashes.
4. Enable **Enable manual resource identities**.
5. Add a JSON list in **Manual resource identities JSON**.

This example illustrates the JSON shape. Its filename and IDs are fictional.
Replace them with the exact active resource and trusted identity before use.

```json
[
  {
    "match": {
      "nodeId": "12",
      "filename": "MyVerifiedStyle.safetensors"
    },
    "air": "urn:air:sdxl:lora:civitai:12345@67890"
  }
]
```

Every selector supplied in `match` must match the active resource. A mapping
can select by `resourceKey`, `nodeId`, `selectedValue`, `filename`, or `hashes`.
Use the resource key from your own sidecar to distinguish repeated loaders.
`selectedValue` is a safe relative model selection. Absolute paths are rejected.

An identity can alternatively provide numeric `modelId` and `modelVersionId`
with `type`, plus available `fileId`, `format`, `baseModel`, `modelName`, and
`modelVersionName`. An AIR often supplies a more complete structured identity.
IDs without the required supporting details can remain partial.

## Precedence and conflicts

Matching manual identities take precedence over the preferred primary value.
Lower-priority workflow, cache, and API evidence can complete compatible fields.
Conflicting evidence remains visible. Multiple equally specific manual
mappings that identify different targets produce `manual_identity_conflict`.

Invalid JSON or an unmatched mapping produces diagnostics while the image
continues saving. Manual mappings apply to resources the scanner found on the
active branch. Review the resulting sidecar before sharing credits.
[Models and resource identities](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Models-and-resource-identities)
