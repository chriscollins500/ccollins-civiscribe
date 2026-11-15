# Metadata and sidecars

CiviScribe builds one generation record and uses it for the metadata written
to the image, optional JSON sidecar, filename values, and display facts. This
keeps the saved information tied to the image that actually reached disk.

## Where the metadata lives

| Carrier | PNG | JPEG | WebP |
| --- | --- | --- | --- |
| A1111-style generation text | PNG `parameters` text and EXIF UserComment | EXIF UserComment | EXIF UserComment |
| ComfyUI API prompt and UI workflow | UTF-8 PNG payloads when enabled and available | Use a sidecar for graph payloads | Use a sidecar for graph payloads |
| Structured Civitai manifest | Rich PNG payload when enabled | Compatible information in generation text | Compatible information in generation text |
| Complete structured sidecar | Optional | Optional | Optional |

The A1111 text describes known prompts, settings, hashes, and safe resource
identities. Civitai applies its own parser and catalog rules when you upload.

## Write a sidecar

Enable **Write sidecar JSON**, then save an image. A save such as
`portrait_00001_.png` gets a companion named `portrait_00001_.json` in the same
folder. A counter-based `portrait_0001.webp` gets `portrait_0001.json`.

Sidecars use deterministic strict UTF-8 JSON. They are written only after the
image commits. A sidecar problem cannot remove or retry that completed image.
When different image formats use the same stem, their companion JSON names can
collide. Use distinct prefixes or folders when each format needs its own sidecar.

## Reading the JSON

| Field | What to look for |
| --- | --- |
| `schemaName`, `schemaVersion` | Sidecar document type and format version |
| `artifact` | Actual filename, subfolder, format, size, dimensions, encoded precision, and metadata status |
| `generationRecord.generator` | CiviScribe version and available ComfyUI version |
| `generationRecord.prompts` | Positive/negative text and its source information |
| `generationRecord.settings` | Known sampler, seed, steps, guidance, denoise, and related settings |
| `generationRecord.resources` | Active resources, strengths, hashes, identities, and resolution details |
| `generationRecord.diagnostics` | Sanitized metadata warnings and errors |
| `payloads` | Included ComfyUI prompt/workflow graph copies |
| `projections` | A1111 text and optional Civitai manifest |
| `save` | Save warnings, redactions, and sidecar status |

The sidecar schema version has its own lifecycle. A CiviScribe 2.0.10 save can
correctly use sidecar schema `2.0.0`.

## Workflow and manifest switches

**Embed ComfyUI workflow** controls both API-prompt and UI-workflow payloads
in the image and sidecar. Turning it off omits those graphs. It still allows
generation text and the structured generation record.

**Embed Civitai manifest** controls the additional structured manifest. The
generation record remains the basis for the other metadata projections.

## Save fallbacks

CiviScribe tries rich metadata, reduced metadata, and a pixels-only result
when optional metadata fails. If the requested output cannot be committed,
a safe-root PNG fallback can preserve writable pixels.

Inspect the actual preview, `artifact`, `metadataStatus`, and `save.warnings`
to see the outcome. A successfully written image can contain incomplete
generation facts if the workflow could not resolve them.
[Privacy and saving safety](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Privacy-and-saving-safety)
