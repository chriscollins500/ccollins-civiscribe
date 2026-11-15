# Prompts and overrides

CiviScribe normally finds prompt text by following the active image-generation
branch. Literal prompt widgets and supported deterministic prompt operations
can be read automatically.

LLMs, runtime wildcards, API prompt enhancers, and some custom nodes produce
their text while executing. The queued graph may contain a connection without
the final text. Connect that final text to the appropriate override input.

## Connect the exact text sent to the encoder

```text
Original prompt
  -> LLM or wildcard processor
  -> switches, LoRA trigger append, final edits
  -> final STRING -----------------> active text encoder
          |
          +------------------------> CiviScribe positive override
```

1. Find the final `STRING` that feeds the active text encoder.
2. Branch that same output to **Final positive prompt override**.
3. If the negative prompt is generated dynamically, branch its final string
   to **Final negative prompt override**.
4. Save with **Write sidecar JSON** enabled and check the prompt text.

Overrides supply metadata text. Generation still uses the conditioning
connections in your workflow.

## Krea 2 and enhancer switches

When a workflow chooses between the original prompt and an enhanced prompt,
take the output after that choice and after any appended trigger words. This
records the text actually selected when enhancement is turned on or off.

In a subgraph, expose the final string as an output, such as `Final Prompt`.
Connect that output to CiviScribe in the outer graph.

The same wiring principle applies to Ernie-style enhancers and other runtime
text generators. Exact node names depend on your template.
[Detailed final prompt guide](https://github.com/chriscollins500/ccollins-civiscribe/blob/main/docs/final_prompt_overrides.md)

## Different prompts in multiple stages

One override represents one canonical prompt for the saved image. If two
active encoders or sampling stages use distinct prompts, connect the final
canonical string only when your workflow defines one clearly. Otherwise keep
the ambiguity visible in the diagnostic record.

## Missing prompt diagnostic

`runtime_prompt_unavailable_connect_final_prompt_override` means the scanner
recognized a runtime text producer but could not obtain its final output.
A valid matching override clears that prompt warning.

An unknown prompt can coexist with a successful image save and other known
generation settings.
[Troubleshooting](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Troubleshooting)
