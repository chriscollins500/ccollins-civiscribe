# CiviScribe

CiviScribe saves your ComfyUI images with the prompts, settings, and model
resources used to make them. Choose PNG, JPEG, or WebP, save the image, and
upload it to Civitai when you are ready.

This guide covers CiviScribe **2.0.10**. Start with the quick start, then use
the task guides when you need more control.

## Start here

| I want to… | Open this guide |
| --- | --- |
| Install or update CiviScribe | [Installation and updates](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Installation-and-updates) |
| Save my first image | [Quick start](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Quick-start) |
| Understand a control on the node | [Settings reference](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Settings-reference) |
| Pick PNG, JPEG, or WebP | [Image formats](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Image-formats) |
| Organize filenames and folders | [Filenames and folders](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Filenames-and-folders) |
| Move the counter or change its digits | [Counter examples](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Counter-examples) |
| Capture an LLM or wildcard prompt | [Prompts and overrides](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Prompts-and-overrides) |
| Understand missing model credits | [Models and resource identities](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Models-and-resource-identities) |
| Enable lookup or choose a hashing mode | [Civitai lookup and hashing](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Civitai-lookup-and-hashing) |
| Assign verified model identities myself | [Manual resource identities](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Manual-resource-identities) |
| Connect multiple branches or save formats | [Workflow examples](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Workflow-examples) |
| Automate saves or connect an AI agent | [API and MCP](https://github.com/chriscollins500/ccollins-civiscribe/wiki/API-and-MCP) |
| Inspect metadata or a JSON sidecar | [Metadata and sidecars](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Metadata-and-sidecars) |
| Understand what gets shared | [Privacy and saving safety](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Privacy-and-saving-safety) |
| Fix a problem | [Troubleshooting](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Troubleshooting) |
| Check a release download | [Verify a release](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Verify-a-release) |
| Test or contribute to the project | [Development and feedback](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Development-and-feedback) |

## What it records

CiviScribe follows the active connections leading to each save node. When
the workflow supplies enough information, it records positive and negative
prompts, seed, steps, sampler, scheduler, guidance, denoise, final image size,
the primary model, LoRAs and their strengths, and supporting model resources.

Resource identities can include hashes, AIR identifiers, and Civitai model
and version IDs. PNG can also carry the ComfyUI workflow for later reloading.
Optional JSON sidecars explain the saved image and any unresolved details.

For a first save, connect your final `IMAGE`, keep PNG and the default metadata
settings, and press **Run**. Civitai lookup starts disabled, so ordinary saving
works offline.

## What changed in 2.0.10

Model matching now checks the hash algorithm, full digest conflicts, exact
file, and requested version together. Large workflows avoid unnecessary
searches for ordinary filename patterns. Date tokens work consistently in
the browser and backend. Releases verify signed artifacts before publication.
This wiki adds practical guides for the complete node.

Full version history is in the changelog.
[Changelog](https://github.com/chriscollins500/ccollins-civiscribe/blob/main/CHANGELOG.md)
