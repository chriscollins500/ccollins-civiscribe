# Counter examples

Use one `%counter%` token to choose where the sequence number appears in the
filename. `%counter%` uses five digits. `%counter:4%` uses at least four.

These recipes assume the destination has no matching files.

| Pattern | First PNG | Next PNG |
| --- | --- | --- |
| `portrait` | `portrait_00001_.png` | `portrait_00002_.png` |
| `%counter%_portrait` | `00001_portrait.png` | `00002_portrait.png` |
| `portrait_%counter:2%_final` | `portrait_01_final.png` | `portrait_02_final.png` |
| `portrait_%counter:4%` | `portrait_0001.png` | `portrait_0002.png` |
| `%date:yyyy-MM-dd%/portrait_%counter:3%` | `2026-11-14/portrait_001.png` | `2026-11-14/portrait_002.png` |

The final row assumes a November 14, 2026 save date.

## How numbering continues

CiviScribe examines matching files in the destination folder for the selected
format and starts after the highest matching number. Different folders,
formats, or expanded filename prefixes can have independent sequences.

The width is a minimum. `%counter:2%` produces `99`, then `100`. Changing padding
does not reset matching numbering. If `portrait_0099.png` exists, the pattern
`portrait_%counter:2%` continues with `portrait_100.png`.

Existing numbered images remain protected when simultaneous saves compete for
the same name. A save allocates another available name when a collision occurs.

## Rules for using the token

- Use one token in the filename component.
- Choose a width from 1 through 9.
- Put date or model tokens in folders when useful.
- Keep the counter in the filename, as in `portraits/%counter:4%_final`.

Patterns such as `%counter:0%`, `%counter:10%`, or two counter tokens are invalid.
Counter tokens in subfolder names are also invalid. Check the actual saved path
and sidecar diagnostic if a pattern falls back to a safe name.

## Seeds and counters

The seed describes generation randomness. The counter allocates a filename.
For example, `%seed%_%counter:4%` might produce `123_0001.png` for one save.
Repeated saves with seed `123` can create additional numbered files.

For all other tokens, see the filename guide.
[Filenames and folders](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Filenames-and-folders)
