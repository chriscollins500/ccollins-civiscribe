import { Buffer } from "node:buffer";
import { readFile } from "node:fs/promises";
import { URL } from "node:url";

import { expect, test } from "@playwright/test";

const API = "/civiscribe/v1";
const NODE_ID = "CCollins_CiviScribe_SaveImage";

test("native API discovery and preflight preserve the host queue", async ({
  request,
}) => {
  for (const prefix of ["", "/api"]) {
    const response = await request.get(`${prefix}${API}/capabilities`);
    expect(response.ok()).toBe(true);
    expect(response.headers()["cache-control"]).toBe("no-store");
    const capabilities = await response.json();
    expect(capabilities.nodeId).toBe(NODE_ID);
    expect(capabilities.preflight).toMatchObject({
      readOnly: true,
      networkRequests: false,
      modelFileReads: false,
    });
    const contract = await request.get(`${prefix}${API}/openapi.json`);
    expect(contract.ok()).toBe(true);
    expect((await contract.json()).openapi).toBe("3.1.0");
  }
  const example = JSON.parse(
    await readFile(
      new URL("../../docs/examples/save-demo-api.json", import.meta.url),
      "utf8",
    ),
  );
  const before = await (await request.get("/queue")).json();
  const response = await request.post(`/api${API}/preflight`, {
    data: example,
  });
  expect(response.ok()).toBe(true);
  const result = await response.json();
  expect(result.committed).toBe(false);
  expect(result.phase).toBe("static");
  expect(result.nodes.map((node) => node.saveNodeId)).toEqual(["2", "3"]);
  expect(await (await request.get("/queue")).json()).toEqual(before);
});

test("native preflight bounds and sanitizes malformed requests", async ({
  request,
}) => {
  for (const [data, code, status] of [
    ["{", "invalid_json", 400],
    ['{"prompt":{},"prompt":{}}', "duplicate_json_key", 400],
    ['{"prompt":{"x":NaN}}', "invalid_json_constant", 400],
    [" ".repeat(1024 * 1024 + 1), "request_too_large", 413],
  ]) {
    const result = await request.post(`${API}/preflight`, {
      data: Buffer.from(data),
      headers: { "content-type": "application/json" },
    });
    expect(result.status()).toBe(status);
    expect(await result.json()).toEqual({ error: { code } });
  }
});

test("save reports describe the safe-root fallback actually committed", async ({
  request,
}) => {
  const example = JSON.parse(
    await readFile(
      new URL("../../docs/examples/save-demo-api.json", import.meta.url),
      "utf8",
    ),
  );
  delete example.prompt["3"];
  example.prompt["2"].inputs.filename_prefix = "../escape";
  example.prompt["2"].inputs.output_format = "jpeg";
  const response = await request.post("/prompt", { data: example });
  expect(response.ok()).toBe(true);
  const { prompt_id: promptId } = await response.json();
  let history;
  await expect
    .poll(async () => {
      history = (await (await request.get(`/history/${promptId}`)).json())[
        promptId
      ];
      return history?.status?.completed;
    })
    .toBe(true);
  expect(history.status.status_str).toBe("success");
  const output = history.outputs["2"];
  const report = JSON.parse(output.text[0]);
  expect(report.images[0]).toMatchObject({
    filename: output.images[0].filename,
    subfolder: output.images[0].subfolder,
    type: output.images[0].type,
    format: "jpeg",
    width: 64,
    height: 64,
    sidecarStatus: "written",
  });
  expect(report.images[0].filename).toMatch(/^ComfyUI_\d+_\.jpg$/);
  expect(report.images[0].subfolder).toBe("");
  expect(report.warnings.length).toBeGreaterThan(0);
  expect((await request.get("/view", { params: output.images[0] })).ok()).toBe(
    true,
  );
});
