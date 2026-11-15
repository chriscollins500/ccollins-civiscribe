# Workflow examples

These wiring examples start with workflows that already generate successfully
in your installation. Connect the finished `IMAGE` to CiviScribe. Model names,
samplers, and node layouts depend on your chosen workflow.

## Save a standard checkpoint image

```text
Checkpoint -> text encoders -> positive and negative conditioning
           -> sampler model input
           -> VAE Decode VAE input

Empty latent -> sampler -> VAE Decode -> CiviScribe Images
```

Use PNG and `portraits/%model_noext%_%counter:4%` as the filename pattern.
The save records the active checkpoint, prompts, available sampler settings,
and final dimensions. Add a LoRA on the active model/CLIP path to record its
filename, applicable strengths, and available identity evidence too.

## Save five independent branches

```text
Model A -> sampler A -> decode A -> CiviScribe A   branches/A/%counter:4%
Model B -> sampler B -> decode B -> CiviScribe B   branches/B/%counter:4%
Model C -> sampler C -> decode C -> CiviScribe C   branches/C/%counter:4%
Model D -> sampler D -> decode D -> CiviScribe D   branches/D/%counter:4%
Model E -> sampler E -> decode E -> CiviScribe E   branches/E/%counter:4%
```

Each CiviScribe node requests its own executing ID from ComfyUI and follows
its own image branch. A loader elsewhere on the canvas cannot supply credits
solely because it exists there. Give each branch a clear folder or prefix
when you want independent image sequences.

## Save PNG and JPEG from the same result

```text
Final IMAGE -> CiviScribe PNG
           -> CiviScribe JPEG
```

Create two save nodes and connect the same final image to both. Select PNG on
one and JPEG on the other. For example, use `archive/%model_noext%` for PNG and
`sharing/%model_noext%` for JPEG. Choose a JPEG background if the image has alpha.

Each node writes its own file, encoding, metadata, counter, and optional
sidecar. The preview for each node shows its actual saved result.

## Record an image-to-image pass

```text
Load Image -> VAE Encode -> sampler -> VAE Decode -> CiviScribe
```

Connect the final decode to CiviScribe. Known latent provenance and active
sampling evidence can establish img2img classification and denoise. The final
image dimensions describe the committed output, including later scaling.

## Save an upscaled image

```text
Generated IMAGE -> active upscaler -> CiviScribe
```

Connect after the upscaler to save the larger result and its final dimensions.
Supported active upscaler resources can appear in the generation record.
Use another save node before the upscale if you also want the earlier image.

## Preserve an enhanced prompt

```text
Enhancer -> final selected STRING -> text encoder -> generation
                                -> CiviScribe prompt override
Final IMAGE ------------------------------------> CiviScribe Images
```

Branch the last string after switches and trigger edits to the matching
prompt override. For a subgraph, expose that final string as an output.
[Prompts and overrides](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Prompts-and-overrides)

## Test saving through the API without downloading a model

The repository includes a tiny API prompt that creates a synthetic 64×64
image and saves PNG and WebP copies with sidecars. It exercises saving and
counter placement. Because it contains no model or sampler, generation
settings and resource identities appropriately remain unknown.

This is a ComfyUI API request body for `POST /prompt`. API users can submit it
to their own running instance. It is separate from the editable UI workflow
format. The second example contains a standard checkpoint workflow with
`REPLACE_WITH_YOUR_CHECKPOINT.safetensors` for you to replace with an installed
checkpoint's exact selector.
[Synthetic save example](https://github.com/chriscollins500/ccollins-civiscribe/blob/main/docs/examples/save-demo-api.json)
· [Checkpoint example](https://github.com/chriscollins500/ccollins-civiscribe/blob/main/docs/examples/checkpoint-api.json)
