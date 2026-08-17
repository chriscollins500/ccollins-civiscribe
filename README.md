<div align="center">

# CCollins' CiviScribe

### Your image should remember how it was made.

**CiviScribe is a friendly Save Image node for ComfyUI that gives Civitai the
prompt, settings, resources, hashes, and workflow information it needs to
understand your image.**

[![Validation](https://img.shields.io/github/actions/workflow/status/chriscollins500/ccollins-civiscribe/validation.yml?branch=main&style=for-the-badge&label=Validation)](https://github.com/chriscollins500/ccollins-civiscribe/actions/workflows/validation.yml)
[![ComfyUI](https://img.shields.io/badge/ComfyUI-Current_V3-18A058?style=for-the-badge)](https://www.comfy.org/)
[![Formats](https://img.shields.io/badge/Images-PNG_%7C_JPEG_%7C_WebP-4C7DFF?style=for-the-badge)](#image-formats)
[![License](https://img.shields.io/badge/License-MIT-7D5FFF?style=for-the-badge)](LICENSE)

**Save once. Share with context. No metadata expertise required.**

</div>

---

## What is CiviScribe?

[ComfyUI](https://www.comfy.org/) is a visual, node-based app for creating AI
images. CiviScribe is the final node in that workflow: connect your finished
image, press **Run**, and it saves an upload-ready PNG, JPEG, or WebP.

Along with the image, CiviScribe records the useful details that normally get
lost between ComfyUI and Civitai:

- your positive and negative prompts;
- seed, steps, sampler, scheduler, guidance or CFG, denoise, and image size;
- the model, LoRAs and strengths, VAE, text encoders, ControlNet, IPAdapter,
  and upscalers that actually contributed to the saved image;
- hashes, AIR identifiers, and Civitai model/version IDs when they are known;
- the ComfyUI prompt and reloadable workflow for PNG files; and
- a human-readable A1111-style parameters block used by common image tools.

You do not need to understand any of those formats. CiviScribe scans the active
workflow, writes the compatible metadata, and keeps unresolved information
honest instead of guessing.

> **You make the image. CiviScribe handles the paperwork.**

## Why use it?

| What you want                                 | What CiviScribe does                                                                     |
| --------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Civitai to recognize your generation settings | Writes a parser-friendly A1111 parameters block                                          |
| The correct model and LoRAs                   | Follows the active path to the saved image instead of listing every loader on the canvas |
| A workflow you can reopen later               | Embeds the ComfyUI prompt and workflow in PNG when enabled                               |
| Strong resource identification                | Uses safe hashes, AIR data, local identity records, and optional Civitai lookup          |
| No invented model IDs                         | Leaves uncertain resources unresolved and explains why                                   |
| Your image even when metadata fails           | Saves the pixels first, then adds as much metadata as it safely can                      |
| Local-first operation                         | Saves locally; optional lookup sends only a hash or explicit model-version ID            |

```mermaid
flowchart LR
    A["Your ComfyUI workflow"] --> B["Final IMAGE"]
    B --> C["CiviScribe"]
    C --> D["PNG, JPEG, or WebP"]
    D --> E["Civitai-ready metadata"]
```

## Install

### ComfyUI Manager

Open **ComfyUI Manager**, search for **CiviScribe**, open the node-pack card,
and select **Install**. Restart ComfyUI when installation finishes.

You can also use the manual method below when you prefer to install directly
from the source repository.

### Manual installation

Open a terminal in your ComfyUI `custom_nodes` folder and run:

```powershell
git clone https://github.com/chriscollins500/ccollins-civiscribe.git
cd ccollins-civiscribe
python -m pip install .
```

Use the same Python environment that launches ComfyUI, then restart ComfyUI.
The official [ComfyUI custom-node installation guide](https://docs.comfy.org/installation/install_custom_node)
includes environment-specific instructions for Desktop, portable, and manual
installations.

### Requirements

- the current ComfyUI Desktop release and native ComfyUI V3 API;
- Python 3.12 or newer; and
- no Civitai account, token, or API key for ordinary saving.

## Use It In One Minute

1. Add **CCollins / CiviScribe / CiviScribe - Save Image for Civitai** to your
   workflow.
2. Connect the workflow's final `IMAGE` output to CiviScribe's `images` input.
3. Leave the defaults alone for the easiest, most compatible setup.
4. Choose PNG, JPEG, or WebP and set a filename pattern if desired.
5. Queue the workflow.
6. Upload the saved image to Civitai.

For most people, that is the entire setup.

### Recommended everyday settings

| Setting                | Recommended value | Why                                                          |
| ---------------------- | ----------------- | ------------------------------------------------------------ |
| Output format          | `PNG`             | Lossless pixels and the richest ComfyUI metadata support     |
| Embed ComfyUI workflow | On                | Embeds both sanitized ComfyUI graph payloads for reloading    |
| Embed Civitai manifest | On                | Keeps a structured record of resources and identities        |
| Enable Civitai lookup  | Off               | Normal saves stay completely local                           |
| Hashing mode           | `cached_or_fast`  | Reuses cached results without forcing large full-file hashes |
| Write sidecar JSON     | Off               | Enable only when you want a detailed audit/debug record      |

## What Civitai Can Receive

CiviScribe gives Civitai the strongest truthful information available for the
active generation path:

- positive and negative prompts;
- txt2img or img2img classification when the graph proves it;
- steps, sampler, scheduler, seed, size, CFG, Flux guidance, and denoise;
- primary checkpoint, diffusion model, UNET, or GGUF model;
- LoRAs with model and CLIP strengths, including active ND Super bundles;
- VAE, text encoder, embedding, ControlNet, IPAdapter, and upscaler resources;
- Civitai resources with AIR and model/version IDs when safely resolved; and
- AutoV1, AutoV2, AutoV3, and SHA-256 hashes when available.

Civitai controls its own parser and resource catalog, so not every resource is
guaranteed to appear on every upload. CiviScribe records unresolved active
resources in its structured metadata rather than attaching the wrong listing.

## Image Formats

| Format   | Default behavior                                           | Best for                                                        |
| -------- | ---------------------------------------------------------- | --------------------------------------------------------------- |
| **PNG**  | Lossless; A1111, ComfyUI, Civitai, and EXIF metadata       | Maximum compatibility and reloadable workflows                  |
| **JPEG** | Quality 100, optimized coding, 4:4:4 chroma; EXIF metadata | Smaller, widely shareable files when transparency is not needed |
| **WebP** | Lossless by default; preserves alpha and EXIF metadata     | Compact lossless images and transparency                        |

JPEG is inherently lossy. CiviScribe uses high-fidelity defaults, but PNG or
lossless WebP is the better choice when decoded-pixel preservation matters.

## Friendly Filenames And Folders

CiviScribe supports ComfyUI filename tokens plus simple aliases for common
generation values.

```text
%date:yyyy-MM-dd%/%date:hhmmss%_%model%
```

That pattern creates a dated subfolder and names the image with its save time
and active model. You can also use `%seed%`, `%sampler%`, `%width%`, `%height%`,
`%batch_num%`, and current ComfyUI `%Node name.widget_name%` replacements.

All expanded paths are checked before writing. Absolute paths, traversal,
unsafe Windows names, unresolved tokens, and escapes outside ComfyUI's output
folder are rejected.

## When Automatic Detection Needs Help

Most workflows need no extra configuration. The optional controls are there
for unusual or highly customized graphs:

- **Positive/negative prompt override** supplies metadata text when a custom
  prompt node cannot be understood automatically. It does not change the image.
- **Enable Civitai lookup** asks Civitai to identify unknown resources using
  hashes. Only a hash or explicit model-version ID is sent.
- **Preferred primary AIR or Civitai URL** pins the active primary model to the
  intended Civitai listing when mirrors or quantized files are ambiguous.
- **Manual resource identities** lets advanced users pin several resources.
- **Sidecar JSON** writes a detailed, machine-readable audit beside the image.

The interface reveals these controls only when they are relevant, so normal
use stays compact.

## Privacy And Safety

CiviScribe is local-first by design.

- Civitai lookup is **off by default**.
- It never uploads images, prompts, workflows, sidecars, or model files.
- Optional lookup sends only an exact hash or explicit model-version ID over
  verified HTTPS.
- It does not store API tokens because it does not need them.
- Model files are read only after an active resource resolves beneath a
  ComfyUI-approved model folder.
- Output stays inside ComfyUI's configured output directory.
- Paths and secret-like values are removed from metadata and diagnostics.
- Metadata, lookup, cache, EXIF, and sidecar failures never discard writable
  image pixels.

See the [security policy](SECURITY.md) for the complete trust boundary.

## Frequently Asked Questions

### Do I need a Civitai API key?

No. Saving works locally without an account, key, or network connection.

### Does CiviScribe upload my image?

No. It only saves files to ComfyUI's configured output folder. You decide what
to upload and where.

### Why is a resource unresolved?

CiviScribe could not prove its identity from the workflow, cache, available
hashes, or optional API response. It will not guess from a filename. Enable
lookup, run full hashing when appropriate, or provide a preferred AIR for a
known resource.

### Can I reload the workflow from an image?

When **Embed ComfyUI workflow** is enabled, PNG files include both the
sanitized ComfyUI API prompt graph and UI workflow graph used by compatible
ComfyUI tools. Turning it off omits both graph payloads from the image and
sidecar. JPEG and WebP carry A1111/Civitai metadata in EXIF, but are not
presented as full ComfyUI workflow containers.

### What happens if metadata writing fails?

CiviScribe tries rich metadata, reduced compatible metadata, and finally a
pixels-only save. A valid writable image takes priority over optional metadata.

### Does it support video or audio?

No. CiviScribe is deliberately focused on Civitai-compatible still images:
PNG, JPEG, and WebP.

<details>
<summary><strong>Technical metadata layout</strong></summary>

### PNG

- `parameters` and `Software` use classic PNG `tEXt` chunks.
- Optional `prompt`, `workflow`, and `civitai` values use UTF-8 `iTXt`. The
  workflow setting controls both ComfyUI graph payloads.
- EXIF UserComment provides an additional A1111/Civitai-compatible carrier.
- Unicode parameters retain a parser-safe text form and a full UTF-8 form.

### JPEG and WebP

- Both use the same immutable generation record and A1111/Civitai projection
  as PNG.
- Compatible generation text is stored in EXIF UserComment.
- Only truthful software and final-dimension fields are authored.

Every output is derived from one immutable generation record so the A1111
parameters, Civitai manifest, EXIF, filename, sidecar, and preview do not keep
competing versions of the same fact.

</details>

<details>
<summary><strong>Development and verification</strong></summary>

CiviScribe uses a locked Python and TypeScript toolchain. The complete local
gate is:

```powershell
.\.venv\Scripts\python.exe -m nox -s python frontend build
```

It runs formatting, linting, strict typing, locale and golden-fixture
validation, schema checks, Python tests with 100 percent statement and branch
coverage, frontend tests, dependency auditing, wheel/source builds, and the
private release-package audit.

Architecture and implementation documents are available in [`docs/`](docs/).
Contributor guidance is in [CONTRIBUTING.md](CONTRIBUTING.md).

</details>

## Support The Project

Found a workflow CiviScribe does not understand? Open a
[GitHub issue](https://github.com/chriscollins500/ccollins-civiscribe/issues)
with the node class names and a safely redacted workflow or sidecar. Never post
private prompts, local paths, tokens, or images you do not want to share.

CiviScribe is available under the [MIT License](LICENSE).

<div align="center">

**CCollins' CiviScribe**

_Better metadata. Honest resources. Your pixels come first._

</div>
