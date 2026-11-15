# Troubleshooting

Start with the saved file and a diagnostic sidecar. Enable **Write sidecar
JSON**, save once, and inspect `generationRecord.diagnostics`, the affected
resource's status, and `save.warnings`. These fields help explain what happened
without needing to guess from the filename.

| Symptom | Check | Next step |
| --- | --- | --- |
| Node missing from the menu | ComfyUI startup log and installed Python environment | Install dependencies into that instance, restart, and refresh the browser |
| New setting missing after updating | Installed version and browser cache | Restart ComfyUI and reload its tab after confirming the package updated |
| `save_node_ambiguous` with several saves | Installed CiviScribe version | Update to 2.0.8 or newer and restart so each executing save supplies its ID |
| Prompt empty after an LLM or wildcard | Runtime prompt diagnostic | Connect the last selected prompt string to the matching override |
| Civitai resource missing | `status`, `identityScope`, `parserFacing`, `parserExclusionReason` | Review the active branch, available hashes, lookup, and verified explicit identity |
| `conflict` after updating to 2.0.10 | Full digest, algorithm, file, or version disagreement | Verify the exact downloaded file and intended catalog version |
| Old or unrelated model appears | The image input and active branch wiring | Save from the intended output and inspect resource lineage in the sidecar |
| Save becomes slow | Full hashing, model size, number of resources, lookup waits | Try `cached_or_fast` and disable lookup to isolate the source of delay |
| HTTP 429 or a lookup failure | `lookupDiagnostics` and server availability | Continue local saves and let the bounded process cooldown expire |
| Filename differs from the pattern | Unknown tokens or invalid path diagnostic | Use a relative pattern and supported tokens, then inspect the actual saved path |
| Counter appears to reset | Folder, format, and expanded prefix changed | Compare matching filenames in that exact destination |
| Sidecar missing but image exists | `save.warnings`, existing companion name, permissions | Use a unique prefix/folder and verify the destination is writable |
| JPEG transparency changed | JPEG background setting | Choose the intended background or save PNG/lossless WebP |
| Workflow will not reload from JPEG/WebP | Format and workflow carriers | Use an original PNG with workflow embedding enabled |

## Unknown model identity

A filename or model family cannot prove a Civitai listing. A locally converted
or quantized file can have a different hash from its source download. Verify
the intended version and file before entering a preferred AIR or manual map.
Keep file qualifiers in an AIR when they are known.

The three hashing modes consult cached hashes first. Selecting `full` allows
whole-file hashing when no usable cache entry is available. Check `hashStatus`
and the actual `hashes` fields to see what evidence was used.

## Image saved through a fallback

An unsafe name, encoding problem, or metadata failure can lead to reduced
metadata or a safe PNG destination. The node preview points to that result.
Read `artifact` and `save.warnings` in its sidecar, when available.

If all destinations are unwritable or the incoming data cannot form an image,
fix the underlying output permissions, disk capacity, or upstream image data.

## Report a reproducible bug

Include the CiviScribe version, ComfyUI version, image format, relevant node
class names, expected result, actual result, and sanitized diagnostic codes.
Attach a minimal redacted workflow or synthetic example when possible.

GitHub Discussions is suitable for usage questions and feature ideas. Issues
are suitable for reproducible defects.
[Discussions](https://github.com/chriscollins500/ccollins-civiscribe/discussions)
· [Issues](https://github.com/chriscollins500/ccollins-civiscribe/issues)
