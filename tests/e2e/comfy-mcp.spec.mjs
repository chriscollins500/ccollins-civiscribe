import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import process from "node:process";
import { createInterface } from "node:readline";
import { clearTimeout, setTimeout } from "node:timers";
import { setTimeout as delay } from "node:timers/promises";
import { URL } from "node:url";

import { expect, test } from "@playwright/test";

test("official Comfy MCP discovers, validates, runs, and reads CiviScribe reports", async ({
  baseURL,
}, testInfo) => {
  test.setTimeout(180_000);
  const python = process.env.CIVISCRIBE_E2E_MCP_PYTHON;
  expect(
    python,
    "Configure --mcp-python for the isolated MCP test",
  ).toBeTruthy();
  const temporary = testInfo.outputPath("mcp");
  await mkdir(temporary, { recursive: true });
  const child = spawn("comfy-mcp", [], {
    cwd: temporary,
    env: {
      ...process.env,
      COMFY_BIN: join(
        dirname(python),
        process.platform === "win32" ? "comfy.exe" : "comfy",
      ),
      COMFY_LOCAL_URL: baseURL,
      COMFYUI_URL: baseURL,
    },
    windowsHide: true,
    stdio: ["pipe", "pipe", "ignore"],
  });
  const lines = createInterface({ input: child.stdout });
  const pending = new Map();
  let sequence = 0;
  lines.on("line", (line) => {
    const message = JSON.parse(line);
    const entry = pending.get(message.id);
    if (entry) {
      pending.delete(message.id);
      clearTimeout(entry.timer);
      if (message.error) entry.reject(new Error("MCP request failed"));
      else entry.resolve(message.result);
    }
  });
  const failPending = () => {
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(new Error("Official MCP server exited unexpectedly"));
    }
    pending.clear();
  };
  child.on("error", failPending);
  child.on("exit", failPending);
  const notify = (method) =>
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method })}\n`);
  const rpc = (method, params) =>
    new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`MCP ${method} timed out`));
      }, 60_000);
      pending.set(id, { resolve, reject, timer });
      child.stdin.write(
        `${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`,
      );
    });
  const tool = async (name, args) => {
    const result = await rpc("tools/call", { name, arguments: args });
    if (result.isError) {
      const detail = result.content
        .filter((item) => item.type === "text")
        .map((item) => item.text)
        .join("\n")
        .replaceAll(
          /(?:\b[A-Z]:[\\/]|\/(?:Users|home|tmp)\/)[^\n]*/gi,
          "[local path redacted]",
        )
        .slice(0, 1000);
      throw new Error(`Official MCP tool ${name} failed: ${detail}`);
    }
    return (
      result.structuredContent ??
      JSON.parse(
        result.content
          .filter((item) => item.type === "text")
          .map((item) => item.text)
          .join("\n"),
      )
    );
  };
  try {
    const initialized = await rpc("initialize", {
      protocolVersion: "2025-11-25",
      capabilities: {},
      clientInfo: { name: "civiscribe-integration-test", version: "1.0.0" },
    });
    expect(initialized.protocolVersion).toBe("2025-11-25");
    notify("notifications/initialized");
    const catalog = await rpc("tools/list", {});
    expect(catalog.tools.map((item) => item.name)).toEqual(
      expect.arrayContaining(["nodes", "run_workflow", "job", "fetch_outputs"]),
    );
    await tool("server_info", {});
    const schema = await tool("nodes", {
      action: "get",
      name: "CCollins_CiviScribe_SaveImage",
    });
    expect(JSON.stringify(schema)).toContain("CCollins_CiviScribe_SaveImage");
    const example = JSON.parse(
      await readFile(
        new URL("../../docs/examples/save-demo-api.json", import.meta.url),
        "utf8",
      ),
    );
    example.prompt["2"].inputs.filename_prefix = "MCPDemo/png_%counter:4%";
    example.prompt["3"].inputs.filename_prefix = "MCPDemo/webp_%counter:4%";
    example.prompt["4"] = {
      ...example.prompt["2"],
      inputs: { ...example.prompt["2"].inputs },
    };
    example.prompt["4"].inputs.output_format = "jpeg";
    example.prompt["4"].inputs.filename_prefix = "MCPDemo/jpeg_%counter:4%";
    const workflow = join(temporary, "workflow.json");
    // comfy-cli takes a raw API export; /prompt takes the enclosing HTTP payload.
    await writeFile(workflow, JSON.stringify(example.prompt), "utf8");
    const validated = await tool("validate_workflow", {
      workflow_path: workflow,
    });
    expect(validated.valid).toBe(true);
    const submitted = await tool("run_workflow", {
      workflow_path: workflow,
      wait: false,
    });
    expect(submitted.prompt_id).toBeTruthy();
    let status;
    await expect
      .poll(
        async () => {
          status = await tool("job", {
            action: "status",
            prompt_id: submitted.prompt_id,
          });
          return status.status;
        },
        { timeout: 60_000 },
      )
      .toBe("completed");
    for (const [nodeId, format] of [
      ["2", "png"],
      ["3", "webp"],
      ["4", "jpeg"],
    ]) {
      const report = JSON.parse(status.text_outputs[nodeId][0]);
      expect(report.schema).toBe("ccollins-civiscribe.save-result");
      expect(report.images[0]).toMatchObject({
        format,
        subfolder: "MCPDemo",
        width: 64,
        height: 64,
        sidecarStatus: "written",
      });
    }
    const outputs = await tool("fetch_outputs", {
      prompt_id: submitted.prompt_id,
      out_dir: join(temporary, "outputs"),
      url_only: true,
    });
    expect(JSON.stringify(outputs)).toContain("/view?");
  } finally {
    child.stdin.end();
    if (child.exitCode === null) {
      await Promise.race([once(child, "exit"), delay(3000)]);
      if (child.exitCode === null) child.kill();
    }
    lines.close();
  }
});
