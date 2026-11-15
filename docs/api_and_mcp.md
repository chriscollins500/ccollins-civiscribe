# Native API and Comfy MCP integration

This integration is available in source builds on `main` after the published
2.0.10 release. Updating the source and restarting ComfyUI loads it. The
published 2.0.10 package does not acquire new endpoints automatically.

CiviScribe uses ComfyUI's server, native V3 node schema, queue, history,
WebSocket events, and image downloads. The official local Comfy MCP discovers
and runs the same node. There is one execution path and one public node:
`CCollins_CiviScribe_SaveImage`.

## HTTP endpoints

Use the address of your own ComfyUI server. A common source-install address is
`http://127.0.0.1:8188`; Desktop may use another port. The routes also work
through ComfyUI's `/api` prefix.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/civiscribe/v1/capabilities` | Installed version, formats, limits, and integration paths |
| GET | `/civiscribe/v1/openapi.json` | OpenAPI 3.1 contract, including request, response, and save-result schemas |
| POST | `/civiscribe/v1/preflight` | Static metadata analysis of the selected active save branches |
| GET | `/object_info/CCollins_CiviScribe_SaveImage` | ComfyUI's authoritative input names, types, defaults, and output schema |
| POST | `/prompt` | ComfyUI validates and queues the workflow |
| GET | `/history/{prompt_id}` | Execution status, saved-image descriptors, and CiviScribe reports |
| GET | `/view` | Fetch a committed image using its returned descriptor |
| WS | `/ws` | ComfyUI's execution events for the submitting client |

CiviScribe's three endpoints do not enqueue, execute, create directories,
read model files, write caches, or contact Civitai. They inherit the existing
ComfyUI server's network binding, middleware, and access controls. CiviScribe
adds no listening port, credentials, authentication bypass, or background
service. Access to the host ComfyUI must be controlled by its operator.

The OpenAPI document describes the CiviScribe endpoints. ComfyUI remains the
authority for its own execution routes and node schema.

## Preflight an API workflow

Send an API-format graph under `prompt`. Omit `save_node_id` to analyze every
active CiviScribe save node, or supply it to select one branch.

```json
{
  "prompt": {
    "1": {
      "class_type": "EmptyImage",
      "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 0}
    },
    "2": {
      "class_type": "CCollins_CiviScribe_SaveImage",
      "inputs": {"images": ["1", 0], "output_format": "png"}
    }
  },
  "save_node_id": "2"
}
```

The response has schema `ccollins-civiscribe.preflight`, schema version
`1.0.0`, `phase: "static"`, and `committed: false`. Each entry in `nodes`
contains the selected save-node ID, active upstream IDs, generation-stage ID,
known settings, detected resources, and sanitized issues. Prompt text and raw
workflow payloads are not echoed.

This analysis uses the existing bounded active-branch scanner. It does not
execute nodes, resolve runtime-generated strings, hash models, enrich identities
from caches or Civitai, validate filename destinations, or certify the graph
as executable. Sampling dimensions can differ from the final saved image after
scaling or other processing. Unknown data stays unknown. Use ComfyUI's native
validation and final save report for execution and committed-image facts.

Requests must be strict UTF-8 JSON with unique keys and finite numbers. Limits
are 1 MiB, 32 levels of JSON nesting, 4,096 graph nodes, and 32 selected save
nodes. Inactive and bypassed saves are excluded. Invalid requests return a
fixed `error.code` with HTTP 400, 404, 413, or 415; unexpected preflight failures
return 500 without supplied payloads or server exception details. Responses
use `Cache-Control: no-store`.

## Run and collect results with Python

The [model-free demo](examples/save-demo-api.json) saves separate PNG and WebP
branches and works without a checkpoint. Run this example from the repository
root against a ComfyUI where the updated node is installed. Submitting it
creates images in that server's configured output directory.

```python
import json
import time
from pathlib import Path

import httpx

workflow = json.loads(Path("docs/examples/save-demo-api.json").read_text("utf-8"))
with httpx.Client(base_url="http://127.0.0.1:8188", timeout=10, trust_env=False) as client:
    preflight = client.post("/civiscribe/v1/preflight", json=workflow)
    preflight.raise_for_status()

    queued = client.post("/prompt", json=workflow)
    queued.raise_for_status()
    prompt_id = queued.json()["prompt_id"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = client.get(f"/history/{prompt_id}")
        response.raise_for_status()
        history = response.json().get(prompt_id)
        if history and history["status"]["completed"]:
            if history["status"]["status_str"] != "success":
                raise RuntimeError("ComfyUI execution failed")
            break
        time.sleep(0.25)
    else:
        raise TimeoutError("Check the existing prompt_id before resubmitting")

    for node_id, output in history["outputs"].items():
        for text in output.get("text", []):
            report = json.loads(text)
            if report.get("schema") == "ccollins-civiscribe.save-result":
                print(node_id, report["images"], report["warnings"])
        for image in output.get("images", []):
            saved = client.get("/view", params=image)
            saved.raise_for_status()
            # saved.content is the exact committed image, including its metadata.
```

The save result is strict JSON in native `outputs[node_id].text[]` alongside
the unchanged `images[]` preview descriptors. Its schema is
`ccollins-civiscribe.save-result`, version `1.0.0`.

Each image reports its actual filename, relative subfolder, format, width,
height, metadata status, sidecar status, and optional sidecar filename.
Warnings contain stable codes and optional batch indices. Reports contain no
prompt, workflow, model paths, or new filesystem catalog. They project the
existing committed `SaveOutcome`; generation metadata still comes from the
single `GenerationRecord` used by the writers and sidecars.

Read the report's actual output facts after a fallback. A requested filename,
format, or sidecar setting is not proof of what was committed. If report
projection fails, the saved image and native preview remain available.
Reports follow ComfyUI's ordinary in-memory history retention. They are not
a persistent receipt database. Sidecars remain opt-in and retain their existing
schema and inclusion rules.

Do not automatically repeat a timed-out POST: first check the prompt ID and
history so a retry does not create duplicate outputs.

## Use the official local Comfy MCP

Connect [Comfy-Org/comfy-mcp](https://docs.comfy.org/agent-tools/mcp) to the
same ComfyUI that contains CiviScribe. No separate CiviScribe MCP server or
registration is needed. All node settings remain discoverable and callable
through the official tools.

When the default address differs from your server, the MCP connection's
environment can select it explicitly:

```json
{
  "mcpServers": {
    "comfy": {
      "command": "comfy-mcp",
      "env": {
        "COMFY_LOCAL_URL": "http://127.0.0.1:8188",
        "COMFYUI_URL": "http://127.0.0.1:8188"
      }
    }
  }
}
```

Replace the port with the actual local server port. This example configures
an already-installed official MCP. Follow its installation instructions for
your client rather than installing a second copy for CiviScribe.

The agent's sequence is:

1. `server_info` confirms the intended server and workspace.
2. `nodes` with `action: "get"` and `name: "CCollins_CiviScribe_SaveImage"`
   reads the complete native widget contract.
3. `validate_workflow` checks a local workflow file against the live catalog.
4. `run_workflow` with `wait: false` queues that file and returns `prompt_id`.
5. `job` with `action: "status"` reads status. On completion,
   `text_outputs[save_node_id][]` contains the JSON save reports.
6. `fetch_outputs` returns or downloads the standard image outputs. Use
   `url_only: true` when URLs are sufficient.

Use an API-format workflow export for `workflow_path`. The HTTP demo above
contains a `prompt` wrapper for POST requests; when using that demo with the
CLI/MCP, save its `prompt` member as the workflow file.

The official MCP does not expose arbitrary custom HTTP routes. Its existing
workflow validation and execution tools cover CiviScribe; applications that
want metadata preflight call the documented HTTP endpoint directly. There is
no claim that the MCP adds a tool for every custom route.

## Design and verification

The host-independent functions live in `civiscribe.api`. Native route
registration uses the current V3 `ComfyExtension.on_load` hook and ComfyUI's
existing route table. The OpenAPI contract is packaged in the wheel and
custom-node ZIP, using package-relative resources for both import layouts.
The native SavedImages projection adds standard text outputs while preserving
previews, pass-through images, and the save node's existing input contract.

Focused tests cover five branches, bounded parsing, schema conformance,
sanitized errors, streamed body limits, native registration, and report failure.
The exact-artifact browser gate also checks HTTP routes, history reports,
safe-root fallback, and the real official MCP over stdio: discovery,
validation, three-format execution, job reports, and output URLs.

To run that isolated gate, provide a clean ComfyUI checkout, its Python, and
an existing Python environment containing the official MCP and CLI:

```powershell
python -m tools.test_comfy_artifact --comfy PATH_TO_CLEAN_COMFYUI --python COMFYUI_PYTHON --mcp-python COMFY_MCP_PYTHON --commit SOURCE_COMMIT
```

For a locally prepared uncommitted bundle, add `--working-tree`. The harness
uses only its own loopback server, synthetic workflows, and temporary outputs.
It stops its own processes when testing finishes. Hosted validation pins
`comfy-mcp==0.10.0` and `comfy-cli==1.26.0` as test tooling; neither becomes a
CiviScribe runtime dependency.

On November 15, 2026, the local Windows exact-ZIP gate passed all 11 browser,
HTTP, accessibility, and real MCP tests with ComfyUI 0.44.2, frontend 1.57.6,
Comfy MCP 0.10.0, and Comfy CLI 1.23.0. The same gate is required in hosted
validation with the pinned CLI 1.26.0. A test-server pass does not install or
restart a working Desktop session.

Primary references checked November 15, 2026:
[ComfyUI routes](https://docs.comfy.org/development/comfyui-server/comms_routes),
[official local MCP](https://docs.comfy.org/agent-tools/mcp),
[Comfy MCP source](https://github.com/Comfy-Org/comfy-mcp), and
[MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle).
