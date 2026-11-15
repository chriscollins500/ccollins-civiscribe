# Settings reference

These are the controls declared by CiviScribe 2.0.10. Display names may be
translated by ComfyUI. The internal names are included for API workflows.

## Connections

| Connection | Internal name | Meaning |
| --- | --- | --- |
| Images input | `images` | Required ComfyUI `IMAGE`, including batches |
| Final positive prompt override | `positive_prompt_override` | Optional final positive `STRING` used in saved metadata |
| Final negative prompt override | `negative_prompt_override` | Optional final negative `STRING` used in saved metadata |
| Images output | `images` | Original incoming image tensor passed through to another node |

The output socket carries the incoming tensor. The preview shows the committed
file, including its selected encoding and any fallback. Use the saved file
when checking the disk result.

## Everyday controls

| Control | Internal name | Default | How to use it |
| --- | --- | --- | --- |
| Filename / subfolder pattern | `filename_prefix` | `ComfyUI` | Relative path beneath ComfyUI's output root |
| Output format | `output_format` | `png` | `png`, `jpeg`, or `webp` |
| Write sidecar JSON | `write_sidecar_json` | Off | Save a detailed JSON companion after the image succeeds |
| Embed ComfyUI workflow | `include_workflow` | On | Include sanitized API prompt and UI workflow payloads when available |
| Embed Civitai manifest | `include_civitai_manifest` | On | Include the structured Civitai resource manifest in rich metadata and sidecars |
| Enable Civitai lookup | `enable_civitai_lookup` | Off | Allow optional hash or version identification requests |
| Preferred primary AIR or Civitai URL | `preferred_primary_model_air` | Empty | Supply a verified identity for the active primary model |
| Hashing mode | `hashing_mode` | `cached_or_fast` | Choose `cached_only`, `cached_or_fast`, or `full` |

Turning workflow embedding off omits both graph payloads from the image and
sidecar. Prompts, settings, and resource metadata still follow their own
projections. JPEG and WebP carry generation metadata through EXIF. PNG offers
the complete workflow carriers.

## Format controls

| Control | Internal name | Default | Range or accepted value |
| --- | --- | --- | --- |
| JPEG quality | `jpeg_quality` | `100` | Integer 1–100 |
| JPEG alpha background | `jpeg_alpha_background` | `#FFFFFF` | RGB hex color, such as `#202020` |
| Lossless WebP | `webp_lossless` | On | Enable decoded 8-bit sample preservation |
| WebP effort / quality | `webp_quality` | `100` | Integer 0–100, encoding effort in lossless mode or quality in lossy mode |

JPEG controls appear for JPEG. WebP controls appear for WebP. Switching the
format preserves the values you entered.

## Advanced controls

| Control | Internal name | Default | Meaning |
| --- | --- | --- | --- |
| Lookup timeout (seconds) | `lookup_timeout_seconds` | `4.0` | Per-request timeout, 1–30 seconds |
| Cache successful lookup results | `lookup_cache_results` | On | Persist successful API identity results locally |
| Enable manual resource identities | `advanced_manual_identities_enabled` | Off | Apply the advanced JSON mapping |
| Manual resource identities JSON | `manual_resource_identities_json` | `[]` | A JSON list of explicit resource mappings |

Lookup controls appear when lookup is enabled. The JSON field appears when
manual identities are enabled. ComfyUI may also place advanced controls in its
advanced widget view. Hiding a control preserves its value.

The timeout controls individual lookup requests. Several active resources or
identity-completion requests can make total save time longer than that value.
[Civitai lookup and hashing](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Civitai-lookup-and-hashing)
