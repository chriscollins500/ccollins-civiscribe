# API and MCP

Source builds on `main` after the published 2.0.10 release add API discovery,
metadata preflight, and machine-readable save reports. Update the node source
and restart ComfyUI to load them. Existing 2.0.10 downloads do not include this
new integration yet.

## Automate the same node

An application or AI agent can use every CiviScribe setting through ComfyUI's
normal workflow system. The same save node handles manual and automated runs.
It keeps the same image quality, metadata rules, safe filenames, and optional
Civitai lookup.

| What you need | Use |
| --- | --- |
| Learn what the installed node supports | `/civiscribe/v1/capabilities` |
| Read its settings and defaults | `/object_info/CCollins_CiviScribe_SaveImage` |
| Check which branches supply metadata | `/civiscribe/v1/preflight` |
| Run a workflow | ComfyUI's `/prompt` |
| Read completion and save reports | ComfyUI's `/history/{prompt_id}` |
| Download a saved image | ComfyUI's `/view` |
| Connect an AI agent | The official local Comfy MCP |

Use these paths with your own ComfyUI server address. Preflight is a read-only
metadata check: it does not generate, save, read model files, or contact
Civitai. Runtime-generated values can still be unknown before execution.

## Ask an agent to use CiviScribe

Connect the official local Comfy MCP to your ComfyUI. CiviScribe appears in its
node catalog automatically. A request can be as simple as:

> Inspect my CiviScribe node, validate my workflow, run it, and tell me which
> images and sidecars were saved and whether there were any metadata warnings.

The agent uses the standard node, workflow, job, and output tools. Save reports
arrive as JSON text with the finished job. They describe the actual committed
file, including a fallback result. Ordinary image previews and downloads work
as before.

CiviScribe does not add another MCP server, listening port, account, or API key.
Prompts and raw workflows are not included in the new reports. Sidecars still
need to be enabled explicitly. The official MCP's workflow tools do not expose
arbitrary custom HTTP endpoints; applications call preflight directly when
they need it.

For exact requests, a complete Python example, MCP setup, limits, schemas, and
testing, see the [API and MCP reference](https://github.com/chriscollins500/ccollins-civiscribe/blob/main/docs/api_and_mcp.md).
