# Final Prompt Overrides

CiviScribe normally reads prompt text from the active ComfyUI graph. Literal
prompts and deterministic string operations need no extra setup.

Some nodes create text only while the workflow is executing. Examples include
LLM prompt enhancement, API-backed rewriting, runtime wildcards, and custom
prompt processors. The queued graph records the connection to that node, but
not necessarily the text it will generate.

## The Reliable Rule

Connect the final `STRING` that actually feeds the active text encoder to
CiviScribe's **Final positive prompt override** or **Final negative prompt
override**.

```text
Original prompt
  -> runtime enhancement
  -> switches and optional edits
  -> final prompt STRING
       -> active text encoder
       -> CiviScribe final prompt override
```

The override changes saved metadata only. It does not alter conditioning or
the generated image.

## Krea 2

The current official local Krea 2 templates use this sequence:

```text
User prompt
  -> TextGenerate
  -> Prompt enhancement switch
  -> Optional LoRA trigger append
  -> Final switch
  -> CLIPTextEncode
```

Use the output of the final switch after the optional LoRA trigger. Connecting
`TextGenerate` directly would lose the original-prompt branch when enhancement
is off and would miss any trigger or edit applied afterward.

The official Krea workflow keeps this chain inside its Text to Image subgraph.
Add a `STRING` subgraph output named `Final Prompt`, connect the final switch to
it, then connect `Final Prompt` to CiviScribe's final positive prompt override
in the outer graph.

## Ernie And Similar Enhancers

Current Ernie templates select between the original prompt and `TextGenerate`
before the active text encoder. Fork the selected switch output to CiviScribe.

Use the same rule for LTX prompt enhancers, Gemini or local-LLM nodes, Qwen
prompt extenders, and wildcard processors: connect the last selected and
postprocessed string, not the earliest generated string.

## What CiviScribe Can Detect Automatically

CiviScribe can safely resolve:

- literal prompt widgets;
- deterministic switches with a known selected branch;
- supported concatenation and replacement nodes; and
- expanded values that a node persists into the queued workflow.

CiviScribe does not execute metadata or replay an LLM. When the selected prompt
depends on a verified runtime text producer and no final value is available, it
leaves the prompt unknown and records this sanitized diagnostic:

```text
runtime_prompt_unavailable_connect_final_prompt_override
```

Connecting a valid matching override clears that prompt diagnostic from the
saved record.

## Multiple Active Prompts

One override represents one canonical final prompt. If a workflow deliberately
uses different active prompt strings for multiple stages or encoders, do not
combine them just to fill one field. Use the string that describes the final
saved generation only when the workflow has a clear canonical prompt; otherwise
leave the value unresolved.

## References

Reviewed 2026-08-19:

- [ComfyUI hidden inputs](https://docs.comfy.org/custom-nodes/backend/more_on_inputs)
- [ComfyUI V3 migration and hidden values](https://docs.comfy.org/custom-nodes/v3_migration)
- [ComfyUI subgraphs](https://docs.comfy.org/interface/features/subgraph)
- [ComfyUI workflow templates](https://github.com/Comfy-Org/workflow_templates)
- [Core TextGenerate implementation](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_textgen.py)
