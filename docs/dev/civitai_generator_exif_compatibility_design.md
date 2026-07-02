# Civitai Generator EXIF Compatibility Design

## Goal

Add a Civitai-style EXIF compatibility layer without regressing the working PNG text/iTXt behavior.

Default mode keeps:

- `parameters` as PNG `tEXt`
- `Software` as PNG `tEXt`
- `prompt` as PNG `iTXt`
- `workflow` as PNG `iTXt` when enabled
- `civitai` as PNG `iTXt` when enabled

Default mode now adds:

- PNG `eXIf` containing EXIF `UserComment`

## UserComment Format

`UserComment` is encoded as:

```text
UNICODE\0 + UTF-16BE text
```

The text follows this shape:

```text
<positive prompt>
Negative prompt: <negative prompt when known>
Steps: <steps>, Sampler: <sampler>, CFG scale: <cfg or guidance>, Seed: <seed>, Size: <width>x<height>, Created Date: <UTC timestamp>, Civitai resources: <compact JSON>, Civitai metadata: <compact JSON>
```

Unknown values are omitted. Resource identities are included only when they are safely resolved by AIR, preferred/pinned identity, local cache, or validated API response.

## Minimal Mode

`civitai_exif_minimal` defaults to `false`.

When true, the node writes only PNG `eXIf` / EXIF `UserComment` and intentionally omits the PNG text/iTXt chunks. This mode is explicit because it removes ComfyUI reload metadata and the classic A1111 `parameters` chunk from the PNG.

## Pixels First

EXIF construction and EXIF save failures are warnings only. If EXIF fails, the node still saves the image and falls back to the remaining metadata layers when available.

## Non-Goals

- No fake camera/lens/GPS metadata.
- No XMP/C2PA/tIME/color chunk implementation.
- No lookup/default/network behavior changes.
- No identity guessing from filenames or bytes.
