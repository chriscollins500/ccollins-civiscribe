# Privacy and saving safety

CiviScribe saves locally and starts with Civitai lookup disabled. You decide
which saved files to upload and where to share them.

## What leaves the computer

Enabling lookup permits verified HTTPS requests containing model hashes or
explicit Civitai model-version IDs. CiviScribe keeps images, prompt text,
workflows, model contents, sidecars, and local paths out of those requests.
Ordinary saving works without network access or an API key.

## What an image can reveal

The purpose of generation metadata is to preserve how an image was made.
Saved images and sidecars can contain prompt text, model names, settings, and
workflow structure. Sharing the file shares the metadata it carries.

Workflow and metadata sanitizers remove recognized private paths and
secret-like values. Review files before publishing personal or sensitive
content, especially workflows using custom nodes with arbitrary fields.

Turn off **Embed ComfyUI workflow** when you want both graph payloads omitted
from the image and sidecar. The node still writes available generation text
and resource information. Check the resulting file when privacy matters.

## Where files can be saved

Output remains beneath ComfyUI's configured output root. Relative subfolders
are supported. Absolute drive paths, network paths, traversal, device names,
and symlink escapes are rejected by the save-path checks.

Choose ComfyUI's output root through its normal configuration when you need
a different destination disk. CiviScribe's pattern then organizes files
within that root.

## Protecting existing images

Number allocation and publication protect existing numbered outputs,
including concurrent saves that choose the same initial name. Images commit
before optional sidecars. Previews and sidecar artifact facts describe the
committed file, including any fallback.

Writable pixels take priority when metadata, scanner, lookup, cache, EXIF,
sidecar, or verification steps fail. The fallback chain still depends on a
writable destination and valid incoming image data.

## Reporting a security issue

Contact the repository owner privately for a suspected security vulnerability.
For ordinary bug reports, share a redacted workflow or diagnostic excerpt
that you have reviewed. Keep credentials and private generation content out
of public reports.
[Security policy](https://github.com/chriscollins500/ccollins-civiscribe/blob/main/SECURITY.md)
