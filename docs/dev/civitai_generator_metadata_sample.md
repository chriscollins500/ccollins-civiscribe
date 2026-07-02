# Civitai Generator Metadata Sample Notes

Samples inspected from `civitai samples.zip` showed two common Civitai generator metadata patterns:

- JPEG files use APP1 EXIF.
- PNG files use PNG `eXIf`.
- Generation text is stored in EXIF `UserComment` under the EXIF sub-IFD.
- `UserComment` begins with the EXIF `UNICODE` prefix and is encoded as UTF-16BE.
- Prompt/settings exports commonly include `Civitai resources: [...]` and `Civitai metadata: {...}` fields after the normal prompt/settings text.
- Some Civitai PNG exports store workflow JSON in `UserComment` rather than prompt/settings text.

The node follows the prompt/settings style for its own exports because it is closest to the existing A1111-compatible `parameters` block and keeps the resource JSON parser-friendly.

Safety decisions:

- Do not copy sample payloads into fixtures.
- Do not write fake camera, lens, GPS, artist, copyright, or provenance tags.
- Do not infer resource identities from filenames or hashes alone.
- Do not include unresolved resources in EXIF `Civitai resources`.
- Keep network lookup behavior unchanged and disabled by default.

Use `tools/analyze_civitai_generator_metadata.py` to regenerate local summaries from sample images or zips without mutating files or making network calls.
