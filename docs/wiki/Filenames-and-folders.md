# Filenames and folders

**Filename / subfolder pattern** accepts a relative path beneath ComfyUI's
configured output folder. Use `/` between folders and leave the image extension
off the pattern. CiviScribe adds the extension and allocates a free counter.

## Ready-to-use recipes

These examples assume a save on November 14, 2026 at 15:04:05, a model named
`DreamModel.v2.safetensors`, seed `123`, sampler `euler`, and a 1024×768 image.
They show the first available PNG filename.

| Pattern | Example output |
| --- | --- |
| `portrait` | `portrait_00001_.png` |
| `%date:yyyy-MM-dd%/portrait` | `2026-11-14/portrait_00001_.png` |
| `%date:YYYY.MM.DD%/%date:HHmmss%` | `2026.11.14/150405_00001_.png` |
| `%model%` | `DreamModel.v2.safetensors_00001_.png` |
| `%model_noext%/%seed%` | `DreamModel.v2/123_00001_.png` |
| `%width%x%height%_%sampler%` | `1024x768_euler_00001_.png` |
| `%model_noext%_%counter:4%` | `DreamModel.v2_0001.png` |

## Available tokens

| Token | Value |
| --- | --- |
| `%model%` | Active primary model basename, including its extension |
| `%model_noext%` | Same basename with one recognized final model extension removed |
| `%seed%` | Detected generation seed |
| `%sampler%` | Detected sampler name |
| `%width%`, `%height%` | Dimensions of this saved image |
| `%batch_num%` | Zero-based batch index, starting at `0` |
| `%year%`, `%month%`, `%day%` | Numeric local date values |
| `%hour%`, `%minute%`, `%second%` | Numeric local time values |
| `%date:FORMAT%` | Local save date/time with explicit padding |
| `%Node name.widget_name%` | A ComfyUI widget replacement resolved in the browser |
| `%counter%`, `%counter:N%` | Save counter, optionally with 1–9 minimum digits |

Simple date aliases such as `%month%` produce numeric values without a padding
promise. Use `%date:MM%` when you want two digits.

## Date pattern letters

| Pattern | Meaning | Example |
| --- | --- | --- |
| `yyyy` or `YYYY` | Four-digit year | `2026` |
| `yy` or `YY` | Two-digit year | `26` |
| `M`, `MM` | Month | `11`, `11` |
| `d` / `D`, `dd` / `DD` | Day | `14`, `14` |
| `h` / `H`, `hh` / `HH` | Hour, 24-hour clock | `15`, `15` |
| `m`, `mm` | Minute | `4`, `04` |
| `s`, `ss` | Second | `5`, `05` |

Capital `M` means month. Lowercase `m` means minute. A date token uses the local
save time, so queuing around midnight can change its folder.

## Model names without extensions

`%model_noext%` removes one final `.safetensors`, `.safetensor`, `.ckpt`, `.pt`,
`.pth`, `.bin`, `.gguf`, or `.sft`, ignoring capitalization. Other suffixes and
dots remain. `DreamModel.v2.safetensors` becomes `DreamModel.v2`.

When the model, seed, or sampler is unknown, the corresponding aliases use
`model`, `seed`, or `sampler`. These are filename placeholders. The metadata
keeps the value unresolved.

## Referencing another node's widget

If ComfyUI identifies a sampler node as `KSampler`, `%KSampler.seed%` references
its `seed` widget. Use the name or replacement alias recognized by ComfyUI, and
keep it unique in workflows with repeated nodes. References inside nested
graphs are searched as part of filename serialization.

The browser resolves widget references before submission. For a direct API
request, expand them yourself. CiviScribe's model, seed, size, date, and counter
aliases are also handled in the backend.

## Path limits

Keep paths relative to the configured output root. Absolute drive paths,
network paths, `..`, Windows device names, unresolved tokens, and directory
escapes are rejected. Invalid patterns trigger the save fallback and a
diagnostic. Ordinary patterns keep the `_00001_` suffix.
[Counter examples](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Counter-examples)
