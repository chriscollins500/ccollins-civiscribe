# Civitai Parser Validation

## Purpose

Civitai's upload parser is a remote, changing behavior. Local metadata presence
does not prove that Civitai recognized a field, and a Civitai screenshot does
not prove which metadata carrier supplied it. This procedure provides a
controlled, manual check without adding upload automation to CiviScribe.

## Boundaries

- Uploads remain manual.
- The comparison tool performs no network request and modifies no files.
- It prints no prompts, filenames, paths, hashes, identifiers, tokens, or raw
  API values.
- A sidecar remains local and should not be uploaded unless the tester
  intentionally chooses to share it.
- Civitai parser results are observations, not permanent guarantees.

## Procedure

1. Save a test image with sidecar output enabled.
2. Inspect the image and validate the sidecar locally.
3. Upload the image manually to Civitai.
4. Record the Civitai image ID.
5. Manually capture the public Civitai image API response as JSON. Do not put
   credentials or authorization headers in the file.
6. Run:

```powershell
python tools/compare_civitai_parser_result.py `
  path\to\image.sidecar.json `
  path\to\civitai-image-response.json `
  --image-id 123456
```

The API capture may be a direct image object, a list, or an object containing
an `items` list. When several images are present, `--image-id` is required to
select one unambiguously.

## Report Semantics

Field statuses:

- `match`: Civitai returned the same typed value.
- `missing`: CiviScribe expected a value but Civitai did not return it.
- `different`: both sides returned a value but they differ.
- `not_expected`: the local projection had no value to test.

Resource statuses compare model-version ID sets:

- `match`: exact set match.
- `match_with_additional`: all expected resources were present plus others.
- `partial`: some expected resources were present.
- `missing`: no expected resource was observed.
- `different`: observed resources did not overlap.
- `not_expected`: CiviScribe emitted no parser-facing resources.

Counts reveal set size without disclosing IDs. Repeated tests should use small,
controlled variants when determining whether a result came from A1111
parameters, ComfyUI workflow metadata, or the structured Civitai manifest.

## Interpretation

Treat a field as reliably recognized only when controlled variants differ in
the expected way. Do not infer parser source from the Civitai UI alone.
Resource recognition can also come from Civitai's own hash processing, so an
observed resource is not proof that an explicit `Civitai resources` entry was
consumed.
