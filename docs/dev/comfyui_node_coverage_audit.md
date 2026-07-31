# ComfyUI Node Coverage Audit

## Purpose

`tools/audit_comfyui_node_coverage.py` is a development-only discovery tool for
finding node classes that may affect generation metadata. It compares three
different kinds of evidence:

1. Live schemas from ComfyUI `/object_info`.
2. Class names from a local ComfyUI-Manager extension map.
3. Versioned class schemas from the public Comfy Registry.
4. Class and input shapes observed in local workflow JSON corpora.

The report is a triage aid. It is not a support table, a correctness score, or
proof that a node is active in a saved image's execution graph.

## Privacy Contract

The report contains only:

- validated ASCII node class names;
- aggregate counts;
- input names and structural types;
- scanner-recognition booleans and conservative candidate classifications;
- generic labels such as `workflow-root-001`.

It does not contain:

- prompts or negative prompts;
- model, LoRA, VAE, text-encoder, or ControlNet selections;
- widget values;
- workflow filenames;
- workflow or subgraph IDs;
- node positions, titles, properties, model download records, or URLs;
- package source URLs;
- filesystem paths.

UI workflow `widgets_values` and node `properties` are never inspected.
API-prompt input values are reduced immediately to structural types such as
`STRING`, `INTEGER`, `LINK`, `ARRAY`, or `OBJECT`.

Class names, input names, and custom type names that are non-ASCII, path-like,
overlong, or outside the conservative allowlist are omitted and counted by a
generic issue code. The report never echoes a rejected value.

## Evidence Hierarchy

### Live `/object_info`

This is the best source for the schemas currently installed in a running
ComfyUI instance. ComfyUI documents `INPUT_TYPES` as the node's required,
optional, and hidden input schema, and those definitions feed runtime node
information. The live audit records only input names and types; combo choices
and defaults are discarded.

Official references:

- [Custom node properties and INPUT_TYPES](https://docs.comfy.org/custom-nodes/backend/server_overview)
- [ComfyUI data types](https://docs.comfy.org/custom-nodes/backend/datatypes)

### Workflow corpus

A workflow corpus answers a different question: which classes and input shapes
actually appear in saved API prompts, UI workflows, and subgraph definitions?

The reader supports:

- direct ComfyUI API prompt mappings;
- wrappers containing `prompt`, `workflow`, `output`, `graph`, or `graphs`;
- UI workflow JSON with a top-level `nodes` array;
- UI subgraphs under `definitions.subgraphs`;
- direct `subgraphs` collections;
- API-prompt-shaped subgraphs.

ComfyUI's current workflow specification defines UI nodes with class `type` and
input entries containing `name` and `type`. It stores widget values separately.
Current subgraph blueprints use the workflow JSON format, and nested subgraphs
are represented in workflow definitions.

Official references:

- [ComfyUI Workflow JSON specification](https://docs.comfy.org/specs/workflow_json)
- [Subgraph blueprints](https://docs.comfy.org/custom-nodes/subgraph_blueprints)
- [ComfyUI frontend objects and prompt/workflow structures](https://docs.comfy.org/custom-nodes/js/javascript_objects_and_hijacking)

UI workflows often omit unconverted widget inputs from the `inputs` array.
Therefore a UI corpus alone cannot provide a complete backend input schema.
Use it alongside live `/object_info`. API prompts expose executed input keys,
but the audit still records only their structural types.

Subgraph definitions are counted once as definitions. The audit does not
multiply their internal nodes by the number of subgraph references. Runtime API
prompts remain the stronger source for the graph ComfyUI actually executes.

### Manager map and public Registry

The Comfy Registry is a package catalog that powers ComfyUI-Manager. Registry
package counts are not class counts, and package presence does not prove that a
particular version is installed or that its extraction metadata is complete.
A local Manager extension map can expose many class names, but it is a cache
snapshot and can be stale, incomplete, or contain historical aliases.

The audit discards every Manager source identifier and records only class-name
occurrence counts.

Official references:

- [Comfy Registry overview](https://docs.comfy.org/registry/overview)
- [Registry list-nodes API](https://docs.comfy.org/api-reference/registry/retrieves-a-list-of-nodes)
- [ComfyUI-Manager missing-node mapping discussion](https://github.com/Comfy-Org/ComfyUI-Manager/discussions/1502)

## Candidate Classifications

Every safe class observation is placed in exactly one tier.

### `actionable_metadata`

The class is already recognized by CiviScribe's scanner, has a strong
loader/sampler/prompt/latent/save class signature, or exposes metadata-relevant
input names. These are the first classes to review.

This tier means "worth a scanner review." It does not mean the scanner extracts
every setting or resource from that node.

### `broad_heuristic`

The class name or live output types suggest possible relevance, but there is
not enough structural evidence to call it actionable. Examples include model
patches, conditioning transforms, sigma utilities, and auxiliary typed
producers.

These candidates are deliberately kept separate so broad output-type matches
do not inflate a scanner coverage percentage.

### `other_observed`

The class was seen, but the bounded structural audit found no metadata signal.
It remains in workflow and live reports so novel naming conventions can still
be reviewed without being mislabeled as a gap.

## Dated Observations

These measurements were taken on 2026-07-19. They are environment snapshots,
not release guarantees.

### Live Desktop instance

- 2,975 total live node classes from `/object_info`.
- 2,955 class names passed the strict privacy allowlist.
- 521 actionable metadata candidates.
- 521 actionable candidates recognized by the current scanner.
- 0 actionable residuals.
- 716 broad heuristic candidates, 439 already recognized.
- 1,718 other observed classes.

The 521/521 figure means every live class that the bounded structural rules
flagged as actionable has been reviewed into a scanner rule or a source-backed
known-node classification. It does not mean every installed node emits
metadata, and it remains separate from graph reachability, branch selection,
and field-level extraction.

### Local Manager cache

- 3,341 package/source entries in the inspected extension map.
- 25,041 safe unique class-name observations.
- 847 actionable metadata candidates, 678 recognized.
- 3,523 broad heuristic candidates, 1,940 recognized.
- 20,671 other observed classes.

The extension map is intentionally not treated as authoritative runtime data.
It contains historical aliases and classes from packages that are not installed.

### Public Registry

The bounded official Registry crawl completed 67 pages on 2026-07-19:

- 334,035 versioned records observed;
- 25,811 safe unique class names;
- 2,977 actionable metadata candidates, 1,719 recognized;
- 3,675 broad heuristic candidates, 1,585 recognized;
- 19,159 other observed classes;
- 295,619 duplicate versioned records;
- 4,721 deprecated records;
- 3,406 experimental records;
- 35,149 records without usable class-schema data.

Versioned records are not current unique packages or support claims. Historical
versions account for substantial duplication, and Registry presence does not
prove that a class participates in an executed image lineage.

### Sanitized workflow corpus

Four generic roots were inspected in the final broad corpus snapshot:

- 1,342 JSON files discovered and 1,340 parsed;
- 200,792 node occurrences;
- 2,161 unique classes;
- 213 actionable metadata classes;
- 213 actionable classes recognized;
- 0 actionable residuals;
- 232 broad heuristic classes, 184 recognized.

The roots are intentionally generic. The report cannot be used to recover
their source directories or workflow filenames.

## Source-Backed Rule Pass

The review did not turn class-name guesses directly into scanner behavior.
Every addition below was checked against a live input schema, installed source,
or upstream source and then covered by active-graph tests:

- current GGUF VAE and Apt `load_GGUF` selectors;
- Step1XEdit integrated normal and TeaCache generators;
- Searge SDXL prompt channels and output semantics;
- AnimateDiff scheduled prompt combiners;
- Wan MultiGPU loaders, prompt encoders, settings chains, empty embeds, decode,
  tiny-VAE, and diffusion-forcing sampler paths;
- Impact Pack regional and two-sampler pipe lineages;
- RES4LYF optional text-encoder slots and provider samplers;
- Nunchaku Qwen/ZImage/Flux model loaders, text encoders, LoRA stacks, and PuLID;
- antrobots `sample`, `refine`, and `refine_pipe`, guarded by their complete
  backend input contracts rather than their generic class names;
- Sage selector, prompt, sampler-info, LoRA-stack, and runtime branch nodes;
- Jake sampler/scheduler providers and the source-defined multi-embedding picker;
- Apt IPAdapter, SDVN style-model, and AnimateDiff motion-module resources;
- Eclipse context scalar outputs, excluding every path-bearing output;
- the IG2MV direct image generator and its prompt, seed, step, CFG, and size
  inputs;
- Hunyuan3D diffusion-model and VAE loader selections.

The antrobots refiner handling is branch-aware: it records both active model
resources, selects the actual base/refiner model and VAE implied by
`refine_step`, preserves ambiguous dual prompts honestly, and uses the runtime
`use_image` value for txt2img/img2img classification.

## Final Unknown Review

After the source-backed pass, no actionable residual remains in either the live
Desktop schema or the expanded workflow corpus.

The last corpus residuals were resolved by inspecting their current upstream
implementations. Several names were intentionally classified as non-generation
helpers:

- `BNK_GetSigma` computes a sigma scalar for noise injection;
- `VideoMaMaSampler` produces masks for video processing;
- `LLMSampler` and `LLavaSamplerAdvanced` generate text, not diffusion pixels;
- GroundingDINO and Segment Anything loaders provide auxiliary detection and
  segmentation models.

They are recognized so they do not produce false unknown-class warnings, but
they do not emit checkpoints, VAEs, or other Civitai generation resources.

The remaining public-Registry actionable queue is not considered a product
defect list. None of those residuals intersects the live actionable residual
set, and none appears as an actionable residual in the workflow corpus. Future
support should still require a current executable schema, an active workflow
lineage, and source evidence for the exact field semantics.

## Reviewed Intentional Exclusions

The final live shortlist was checked again. The following families remain
unreported by design unless a future product policy introduces a truthful
resource role:

- BLIP, CLIPSeg, MiDaS, SAM, detector, segmenter, and other analysis assets;
- CLIP Vision and style models that are not text encoders;
- Hypernetwork and dynamic model-patch formats without a supported domain role;
- Whisper, Wav2Vec, audio VAE/vocoder, frame-interpolation, and video-only
  assets in this image-only product;
- checkpoint/model/VAE saver nodes and path-selector helpers that do not load
  the executed model;
- model patchers, merges, attention modifiers, sigma transforms, schedulers,
  and sampler providers that do not themselves execute generation;
- arbitrary download-capable loaders whose selected value is a URL or remote
  identifier rather than a Comfy-relative file under an approved model root.

These are not unresolved scanner bugs. Mislabeling them as checkpoints, LoRAs,
VAEs, or text encoders would make Civitai metadata less accurate.

## Hard Limits

Every workflow root is processed with fixed defensive limits:

| Limit | Default |
| --- | ---: |
| File size | 16 MiB |
| JSON files per root | 5,000 |
| Directory depth | 12 |
| JSON nesting depth | 64 |
| JSON container items | 1,000,000 |
| Workflow/subgraph document depth | 8 |
| Documents per file | 512 |
| Nodes per file | 50,000 |
| Inputs per node | 256 |
| Input shapes retained per class | 64 |

Directory and file symlinks are skipped. A file that fails parsing or any hard
limit contributes no partial class observations. Failures are represented by
generic issue-code counts.

## Usage

Live instance plus two workflow corpora:

```powershell
python tools/audit_comfyui_node_coverage.py `
  --object-info-url http://127.0.0.1:8000/object_info `
  --workflow-root .\tests\fixtures\workflows `
  --workflow-root .\another-sanitized-corpus `
  --output .\.tmp\comfyui-node-coverage.json
```

Offline live-schema fixture plus a Manager map:

```powershell
python tools/audit_comfyui_node_coverage.py `
  --object-info-file .\.tmp\object-info.json `
  --extension-node-map .\.tmp\extension-node-map.json `
  --output .\.tmp\comfyui-node-coverage.json
```

`--workflow-root` is repeatable and accepts either one JSON file or one
directory. At least one source is required.

## Conservative Exclusions

The audit does not:

- execute or import third-party custom-node code;
- infer graph activity from a UI workflow;
- resolve switches or determine which subgraph instance executed;
- inspect widget values to recover prompts or model names;
- treat output type `MODEL`, `VAE`, `CLIP`, or `CONDITIONING` as proof that a
  node loads a resource;
- classify auxiliary CLIP Vision, style-model, detector, segmenter, or similar
  assets as Civitai resources without a defined product policy;
- infer resource identity, AIR, Civitai IDs, or hashes;
- fetch repositories or install packages;
- claim Registry presence as scanner support.

This is intentional. Coverage additions require a real node schema, a workflow
showing its role, and a conservative scanner rule with active-graph tests.

## Review Workflow

1. Start with unrecognized `actionableMetadataNodes` from live `/object_info`.
2. Cross-check whether those classes occur in `workflowCorpus`.
3. Prefer classes observed in active API prompts over UI-only class names.
4. Inspect the node's official source or `/object_info` schema outside this
   report.
5. Add scanner behavior only when the resource/setting semantics are clear.
6. Keep unknown and auxiliary assets honest rather than guessing a Civitai
   role.

Manual identity mappings can resolve an already detected resource identity.
They cannot make an undetected loader active, repair graph reachability, or
turn a heuristic candidate into a scanner rule.
