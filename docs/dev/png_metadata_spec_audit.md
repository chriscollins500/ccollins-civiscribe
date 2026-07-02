# PNG Metadata Specification Audit

Target references:

- PNG Specification Third Edition, W3C Recommendation 24 June 2025: https://www.w3.org/TR/png/
- PNG extensions and registered public chunks should be treated as compatibility-sensitive additions. This package does not target draft-only Fourth Edition behavior.

## Current Chunks Written

| Keyword / chunk | Chunk type | Default | Purpose |
| --- | --- | --- | --- |
| `parameters` | `tEXt` | yes | A1111/Civitai-compatible generation text. |
| `parameters_utf8` | `iTXt` | only when needed | Full UTF-8 copy of `parameters` when the tEXt chunk needs Latin-1 fallback. |
| `Software` | `tEXt` | yes | Standard PNG keyword identifying concise generator software. |
| `prompt` | `iTXt` | yes | Full ComfyUI API prompt JSON, UTF-8 safe. |
| `workflow` | `iTXt` | when enabled | Full ComfyUI workflow JSON, UTF-8 safe. |
| `civitai` | `iTXt` | when enabled | Structured Civitai-focused manifest JSON. |
| EXIF `UserComment` | `eXIf` | yes | Civitai-style prompt/settings/resources text encoded as EXIF UNICODE UTF-16BE. |

Pillow writes these ancillary chunks before `IDAT` when attached through `PngInfo` and the PNG `exif` save argument. The package does not manually reorder chunks.

When `civitai_exif_minimal` is true, only the PNG `eXIf` chunk is intentionally written. This is an explicit user-selected compatibility mode, not the default.

## Compliance Notes

- Text keywords are normalized to 1-79 Latin-1 bytes, stripped of leading/trailing spaces, and collapsed to avoid consecutive spaces.
- `parameters` remains `tEXt` for broad A1111/Civitai parser compatibility. Because PNG `tEXt` is Latin-1, non-Latin characters are replaced deterministically in that compatibility chunk.
- Full Unicode prompt/workflow/manifest data is preserved in `iTXt`, which is the correct PNG text chunk for UTF-8 metadata.
- `prompt`, `workflow`, `civitai`, and `parameters_utf8` are written as uncompressed `iTXt` by default for simpler parser compatibility.
- The standard `Software` text value is Latin-1 safe and contains no local path, username, prompt, workflow, token, or sidecar data.
- The PNG `eXIf` chunk contains a valid TIFF/Exif payload without JPEG APP1 wrappers.
- EXIF output is limited to `UserComment` in the EXIF sub-IFD. The node does not write fake camera, lens, GPS, artist, copyright, or provenance tags.
- EXIF `UserComment` uses the EXIF `UNICODE` prefix followed by UTF-16BE text, matching Civitai generator sample behavior.

## Compatibility Notes

- Civitai/A1111 compatibility depends on `parameters` staying a classic `tEXt` chunk with the keyword exactly `parameters`.
- ComfyUI reload compatibility depends on the existing `prompt` and `workflow` keys remaining present and UTF-8 safe.
- The `civitai` manifest remains separate from `parameters` so structured resource details do not depend on A1111-style text parsing.
- Civitai generator compatibility is improved by always writing EXIF `UserComment` in normal mode while preserving the existing PNG text/iTXt layers.

## Risks

- `parameters` cannot exactly represent every Unicode prompt because `tEXt` is Latin-1. The node records a warning and preserves full Unicode in `prompt`/`parameters_utf8` iTXt.
- Some downstream tools ignore iTXt. This is why the compatibility tEXt `parameters` chunk is retained.
- Very large metadata is still bounded by package safety limits to avoid pathological saves.

## Deferred Optional Enhancements

- `Creation Time` text keyword: deferred. It can reveal timing information and should be opt-in if added.
- `tIME`: deferred. PNG defines it as last image modification time in UTC, not creation time, so default writing would be privacy- and reproducibility-sensitive.
- XMP via `XML:com.adobe.xmp` iTXt: deferred. If added, it should be opt-in, uncompressed, UTF-8, concise, and avoid full prompts/workflows/local paths/tokens.
- Color chunks (`cICP`, `iCCP`, `sRGB`, `gAMA`, `cHRM`, `mDCV`, `cLLI`): deferred. The node does not currently receive reliable ICC/HDR/color-volume data from image tensors and should not invent color metadata.
- C2PA / Content Credentials: deferred. C2PA is signed provenance, not ordinary PNG text metadata; future support would require signing, certificate/key handling, privacy review, and compatibility testing.
