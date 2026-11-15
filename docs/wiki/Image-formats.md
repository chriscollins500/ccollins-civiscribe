# Image formats

Choose the format according to how you will use the image. PNG is the easiest
starting point when you want the richest ComfyUI metadata.

| Format | Default encoding | Transparency | Generation metadata | ComfyUI graph payloads in the image |
| --- | --- | --- | --- | --- |
| PNG | Lossless | Preserved | A1111 text, Civitai manifest, EXIF | Available when workflow embedding is enabled |
| JPEG | Quality 100, optimized, 4:4:4 chroma | Flattened over the chosen background | EXIF UserComment | Use PNG for reloadable graphs |
| WebP | Lossless, effort 100 | Preserved, including transparent RGB | EXIF UserComment | Use PNG for reloadable graphs |

## PNG for archiving and workflow reloading

Choose PNG and leave **Embed ComfyUI workflow** enabled. When ComfyUI supplies
both graphs, the file stores the API prompt and the editable UI workflow.
Open or drop the PNG into a compatible ComfyUI workflow interface to reload it.

Reloading requires the models and custom nodes used by that workflow to be
available in the receiving installation.

## JPEG for broad image sharing

JPEG quality defaults to 100, with full chroma resolution. It remains a lossy
format, so decoded pixels can differ from PNG.

JPEG cannot store transparency. For an image with transparent areas, choose
the intended **JPEG alpha background**. For example, `#FFFFFF` composites it
against white and `#202020` uses dark gray.

## WebP for compact lossless output

Keep **Lossless WebP** enabled to preserve the encoded 8-bit samples, including
alpha and RGB values beneath transparent pixels. The effort control affects
compression work in lossless mode. Disabling lossless selects lossy encoding,
where the quality control affects fidelity.

File size depends on image content. Compare your own outputs when size matters.

## Image precision

CiviScribe's current Pillow image writers encode 8-bit samples. Incoming
floating-point tensors pass through the writer's conversion boundary.
Lossless preservation refers to those 8-bit samples. A sidecar records the
incoming tensor dtype, encoded precision, and any precision conversion.

## Batch behavior and previews

Each image in a batch gets its own filename, metadata, and optional sidecar.
The native preview references each committed file. Resizing the node preserves
your chosen size during later preview updates.

For metadata carriers and fallback behavior, see the companion guide.
[Metadata and sidecars](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Metadata-and-sidecars)
