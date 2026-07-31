import assert from "node:assert/strict";
import test from "node:test";

import {
  applyComfyFilenameReplacements,
  installFilenameSerialization,
} from "../../web/dist/filename.js";

test("ComfyUI filename replacements support dates and node widget values", () => {
  const graph = {
    nodes: [
      {
        title: "Sampler",
        widgets: [{ name: "steps", value: 99 }],
      },
      {
        subgraph: {
          nodes: [
            {
              title: "Nested sampler",
              properties: { "Node name for S&R": "Sampler" },
              widgets: [{ name: "steps", value: "20/bad:name" }],
            },
          ],
        },
      },
    ],
  };
  const now = new Date(2026, 6, 18, 14, 5, 6);

  assert.equal(
    applyComfyFilenameReplacements(
      graph,
      "%date:yyyy-MM-dd_hhmmss%_%Sampler.steps%_%width%_%model%",
      now,
    ),
    "2026-07-18_140506_20_bad_name_%width%_%model%",
  );
});

test("ComfyUI filename replacements preserve unknown patterns and survive cycles", () => {
  const graph = { nodes: [] };
  graph.nodes.push({ title: "Cycle", subgraph: graph });

  assert.equal(
    applyComfyFilenameReplacements(
      graph,
      "%Missing.value%_%date:yyy%_%seed%",
      new Date(2026, 0, 2, 3, 4, 5),
    ),
    "%Missing.value%_yyy_%seed%",
  );
});

test("filename serialization applies the injected ComfyUI resolver", () => {
  const widget = {
    name: "filename_prefix",
    value: "%date:yyyy-MM-dd%/%Sampler.steps%_%model%",
  };
  const node = { widgets: [widget] };

  assert.equal(
    installFilenameSerialization(node, (value) =>
      value
        .replace("%date:yyyy-MM-dd%", "2026-07-18")
        .replace("%Sampler.steps%", "20"),
    ),
    true,
  );
  assert.equal(widget.serializeValue(), "2026-07-18/20_%model%");
});

test("filename serialization preserves an existing widget serializer", () => {
  const context = { marker: "existing" };
  const widget = {
    name: "filename_prefix",
    value: "ignored",
    serializeValue(suffix) {
      assert.equal(this, context);
      return `existing_${suffix}`;
    },
  };

  installFilenameSerialization({ widgets: [widget] }, (value) =>
    value.toUpperCase(),
  );
  assert.equal(widget.serializeValue.call(context, "value"), "EXISTING_VALUE");
});

test("filename serialization is idempotent and ignores unrelated nodes", () => {
  const widget = { name: "filename_prefix", value: "name" };
  const node = { widgets: [widget] };
  let replacements = 0;
  const replaceFilename = (value) => {
    replacements += 1;
    return value;
  };

  assert.equal(installFilenameSerialization(node, replaceFilename), true);
  assert.equal(installFilenameSerialization(node, replaceFilename), false);
  assert.equal(widget.serializeValue(), "name");
  assert.equal(replacements, 1);
  assert.equal(
    installFilenameSerialization(
      { widgets: [{ name: "other", value: "name" }] },
      replaceFilename,
    ),
    false,
  );
});
