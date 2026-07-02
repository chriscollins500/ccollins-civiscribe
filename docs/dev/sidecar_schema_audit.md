# JSON Sidecar Schema Audit

Target references:

- RFC 8259 JSON: https://www.rfc-editor.org/rfc/rfc8259
- `application/json` media type registration is maintained through the JSON RFC series and IANA media type registry.
- JSON Schema Draft 2020-12: https://json-schema.org/draft/2020-12/json-schema-core.html
- RFC 3339 timestamps: https://www.rfc-editor.org/rfc/rfc3339

## Format

The sidecar is a project-defined diagnostic artifact, not an external AI metadata standard:

```json
{
  "sidecarFormat": "comfyui-civitai-save-node.sidecar",
  "sidecarSchemaVersion": "1.0.0"
}
```

The node version is recorded separately in `generator.version`.

## Why JSON

JSON is widely supported by local tooling, readable enough for debugging, and already used for ComfyUI prompt/workflow metadata and the structured Civitai manifest. The sidecar writer uses strict JSON serialization with:

- UTF-8 output.
- `ensure_ascii = false`.
- no `NaN` or `Infinity`.
- no comments or trailing commas.
- deterministic key ordering.
- 2-space indentation.
- newline at EOF.

## Why JSON Schema 2020-12

Draft 2020-12 is the current stable JSON Schema draft family and is supported by common validators. The schema validates the stable sidecar envelope while allowing resource and lookup diagnostic details to evolve.

The schema file is:

```text
schemas/comfyui-civitai-save-node-sidecar.schema.json
```

## Timestamps

`createdAt` is written only to the optional sidecar, not to PNG metadata. It uses RFC 3339 UTC with a `Z` suffix, for example:

```text
2026-07-01T23:15:00Z
```

This timestamp helps users connect an explicit sidecar to a debugging session. If stricter privacy controls are needed later, timestamp emission should become a sidecar option.

## Top-Level Shape

Current sidecars include:

- `$schema`
- `sidecarFormat`
- `sidecarSchemaVersion`
- `generator`
- `createdAt`
- `image`
- `pngMetadata`
- `a1111`
- `civitai`
- `resources`
- `resourceLifecycle`
- `lookupDiagnostics`
- `settings`
- `warnings`
- `errors`
- `privacy`
- `legacy`

`schema_version: phase-1` is no longer a primary top-level field. It is retained only as `legacy.schema_version` for one-way historical compatibility.

## Privacy Policy

Sidecars must not include:

- absolute Windows, UNC, POSIX home, ComfyUI install, or temp paths.
- API tokens or token-like assignments.
- prompts/workflows/images sent to Civitai.
- full manual identity JSON when advanced identities are disabled.

Sidecars may include:

- the final A1111 `parameters` string, because it is the primary PNG compatibility metadata.
- Comfy-relative model selections and basenames.
- model hashes, because lookup already uses model hashes as model identifiers.
- safe lookup status and failure classes.

## Backward Compatibility

The node does not read sidecars during save. Old sidecars remain historical artifacts and are not migrated in place. New sidecars use the modern envelope and keep only a small `legacy` object for the old phase marker.

The embedded PNG metadata remains the compatibility contract for A1111/Civitai and ComfyUI. Sidecars are diagnostics and must never block image saving.

## Intentionally Not Included

The sidecar is not a second image container and does not duplicate PNG binary payloads. It does not include:

- image pixel hashes by default.
- absolute source paths.
- local model root paths.
- auth headers or tokens.
- network request URLs containing query strings.
- downloaded API payloads unrelated to identity resolution.
- fake camera/lens/GPS EXIF, XMP, C2PA, or other platform metadata.

## Example

```json
{
  "$schema": "https://github.com/comfyui-civitai-save-node/comfyui-civitai-save-node/schemas/comfyui-civitai-save-node-sidecar.schema.json",
  "sidecarFormat": "comfyui-civitai-save-node.sidecar",
  "sidecarSchemaVersion": "1.0.0",
  "generator": {
    "name": "Save Image with Civitai Metadata",
    "package": "comfyui-civitai-save-node",
    "version": "0.9.17"
  },
  "createdAt": "2026-07-01T23:15:00Z",
  "image": {
    "fileName": "image.png",
    "format": "PNG",
    "width": 1024,
    "height": 768,
    "mode": "RGB"
  },
  "pngMetadata": {
    "chunks": [
      {"type": "tEXt", "keyword": "parameters", "encoding": "latin-1", "compressed": false},
      {"type": "tEXt", "keyword": "Software", "encoding": "latin-1", "compressed": false},
      {"type": "iTXt", "keyword": "prompt", "encoding": "utf-8", "compressed": false},
      {"type": "iTXt", "keyword": "workflow", "encoding": "utf-8", "compressed": false},
      {"type": "iTXt", "keyword": "civitai", "encoding": "utf-8", "compressed": false},
      {"type": "eXIf", "keyword": "UserComment", "encoding": "EXIF UNICODE UTF-16BE", "compressed": false}
    ],
    "compatibility": {
      "a1111ParametersChunk": "parameters",
      "parametersChunkType": "tEXt",
      "structuredManifestChunk": "civitai",
      "structuredManifestChunkType": "iTXt",
      "civitaiExifUserComment": "eXIf/UserComment"
    }
  },
  "a1111": {
    "parameters": "positive prompt\nNegative prompt:\nSteps: 8, Sampler: Euler, Size: 1024x768",
    "unicodeFallbackApplied": false,
    "compatibilityTarget": "A1111/Civitai-style parameters parser"
  },
  "civitai": {},
  "resources": {"resolved": [], "unresolved": [], "final": []},
  "resourceLifecycle": {
    "rawResourcesFound": [],
    "activeResources": [],
    "normalizedResources": [],
    "resolvedResources": [],
    "unresolvedResources": [],
    "finalResources": [],
    "metadataStatus": "partial"
  },
  "lookupDiagnostics": {"enabled": false, "client": null, "sslContextSource": null, "entries": []},
  "settings": {"writeSidecarJson": true, "enableCivitaiLookup": false},
  "warnings": [],
  "errors": [],
  "privacy": {
    "absolutePathsIncluded": false,
    "tokensIncluded": false,
    "promptsSentToCivitai": false,
    "workflowSentToCivitai": false,
    "imagesSentToCivitai": false,
    "lookupRequestData": []
  },
  "legacy": {"schema_version": "phase-1", "deprecated": true}
}
```

## Validation

Use:

```text
python tools/validate_sidecar.py path/to/image.json
```

The validator reads only the selected JSON file and local schema. It does not mutate files and does not require network access. If `jsonschema` is not installed, schema validation is skipped after strict JSON and required-field checks.
