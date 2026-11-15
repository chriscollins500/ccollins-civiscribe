# Quick start

Use an image-generation workflow that already runs successfully in ComfyUI.

1. Search the node menu for **CiviScribe - Save Image for Civitai**.
2. Connect your final image output to its **Images** input.
3. Keep **Output format** set to PNG for your first save.
4. Enter `MyImages` in **Filename / subfolder pattern**.
5. Leave **Embed ComfyUI workflow** and **Embed Civitai manifest** enabled.
6. Press **Run**.

For a workflow ending in VAE Decode, the connection looks like this.

```text
Sampler -> VAE Decode -> CiviScribe Images
```

The first available filename will look like `MyImages_00001_.png` in ComfyUI's
configured output directory. Existing matching files advance the number.
The preview on the node refers to the image that actually reached disk.

## Share the result

Upload the saved image file to Civitai. Use the original saved file so its
metadata accompanies it. Taking a screenshot or exporting a new copy through
another editor can remove that metadata.

Review the settings and resources shown by Civitai before posting. Recognition
depends on Civitai's parser and catalog as well as the information available
in your workflow.

## Organize the next save

Try this filename pattern for a dated folder and a model name.

```text
%date:yyyy-MM-dd%/%model_noext%_%counter:4%
```

For a model named `DreamModel.v2.safetensors` on November 14, 2026, the first
available PNG could be `2026-11-14/DreamModel.v2_0001.png`.

More recipes cover seeds, image size, custom node widgets, and counter placement.
[Filenames and folders](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Filenames-and-folders)

## If a prompt or model is missing

Enable **Write sidecar JSON** for a diagnostic save. The companion JSON records
which information was known and why something remained unresolved. Runtime
prompt generators can supply their final text through the two optional prompt
override inputs.
[Prompts and overrides](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Prompts-and-overrides)
