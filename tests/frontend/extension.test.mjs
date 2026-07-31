import assert from "node:assert/strict";
import test from "node:test";

import {
  createCiviScribeExtension,
  EXTENSION_NAME,
  isCiviScribeNode,
} from "../../web/dist/extension.js";
import { NODE_ID } from "../../web/dist/identity.js";
import { NATIVE_IMAGE_PREVIEW_WIDGET } from "../../web/dist/preview.js";

function targetNode() {
  const sizeCalls = [];
  const node = {
    comfyClass: NODE_ID,
    size: [300, 200],
    widgets: [
      { name: "filename_prefix", value: "%Sampler.steps%", options: {} },
      { name: "output_format", value: "png", options: {} },
      { name: "enable_civitai_lookup", value: false, options: {} },
      { name: "advanced_manual_identities_enabled", value: false, options: {} },
      { name: "jpeg_quality", value: 100, options: {} },
    ],
    computeSize() {
      return [350, 500];
    },
    setSize(value) {
      sizeCalls.push(value);
    },
    addCustomWidget(widget) {
      return widget;
    },
  };
  return { node, sizeCalls };
}

test("extension identity is stable and only targets CiviScribe", () => {
  assert.equal(EXTENSION_NAME, "ccollins-civiscribe.ui");
  assert.equal(isCiviScribeNode({ comfyClass: NODE_ID }), true);
  assert.equal(isCiviScribeNode({ type: NODE_ID }), true);
  assert.equal(isCiviScribeNode({ comfyClass: "OtherNode" }), false);
});

test("new nodes receive visibility and one-time preview policies", () => {
  const extension = createCiviScribeExtension((value) =>
    value.replace("%Sampler.steps%", "20"),
  );
  const { node, sizeCalls } = targetNode();
  extension.nodeCreated(node);
  assert.equal(node.widgets[0].serializeValue(), "20");
  assert.equal(node.widgets[4].hidden, true);
  node.addCustomWidget({ name: NATIVE_IMAGE_PREVIEW_WIDGET });
  assert.deepEqual(sizeCalls, [[420, 720]]);
});

test("loaded nodes preserve serialized dimensions", () => {
  const extension = createCiviScribeExtension();
  const { node, sizeCalls } = targetNode();
  extension.nodeCreated(node);
  extension.loadedGraphNode(node);
  node.addCustomWidget({ name: NATIVE_IMAGE_PREVIEW_WIDGET });
  assert.deepEqual(sizeCalls, []);
});

test("other node types remain untouched", () => {
  const extension = createCiviScribeExtension();
  const node = { comfyClass: "OtherNode", widgets: [] };
  extension.nodeCreated(node);
  extension.loadedGraphNode(node);
  assert.deepEqual(node, { comfyClass: "OtherNode", widgets: [] });
});
