import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_PREVIEW_EXTRA_HEIGHT,
  DEFAULT_PREVIEW_WIDTH,
  defaultPreviewSize,
  installPreviewPolicy,
  markNodeLoaded,
  NATIVE_IMAGE_PREVIEW_WIDGET,
  shouldExpandDefaultPreview,
} from "../../web/runtime/preview.js";

function previewNode(size = [300, 200], minimum = [350, 500]) {
  const sizeCalls = [];
  const widgets = [];
  const node = {
    size: [...size],
    computeSize() {
      return [...minimum];
    },
    setSize(next) {
      this.size = [...next];
      sizeCalls.push([...next]);
    },
    addCustomWidget(widget) {
      widgets.push(widget);
      return widget;
    },
  };
  return { node, sizeCalls, widgets };
}

test("default preview sizing adds one native preview-height allowance", () => {
  assert.deepEqual(defaultPreviewSize([350, 500], [300, 200]), [
    DEFAULT_PREVIEW_WIDTH,
    500 + DEFAULT_PREVIEW_EXTRA_HEIGHT,
  ]);
  assert.equal(
    shouldExpandDefaultPreview([300, 200], [300, 200], false, false),
    true,
  );
  assert.equal(
    shouldExpandDefaultPreview([300, 200], [301, 200], false, false),
    false,
  );
  assert.equal(
    shouldExpandDefaultPreview([300, 200], [300, 200], true, false),
    false,
  );
  assert.equal(
    shouldExpandDefaultPreview([300, 200], [300, 200], false, true),
    false,
  );
});

test("a new untouched node expands once when the native preview arrives", () => {
  const { node, sizeCalls, widgets } = previewNode();
  assert.equal(installPreviewPolicy(node), true);
  const preview = { name: NATIVE_IMAGE_PREVIEW_WIDGET };
  assert.equal(node.addCustomWidget(preview), preview);
  assert.deepEqual(widgets, [preview]);
  assert.deepEqual(sizeCalls, [[DEFAULT_PREVIEW_WIDTH, 720]]);

  node.addCustomWidget({ name: NATIVE_IMAGE_PREVIEW_WIDGET });
  node.addCustomWidget({ name: "other-widget" });
  assert.equal(sizeCalls.length, 1);
});

test("manual resizing before output is preserved exactly", () => {
  const { node, sizeCalls } = previewNode();
  installPreviewPolicy(node);
  node.size = [640, 840];
  node.addCustomWidget({ name: NATIVE_IMAGE_PREVIEW_WIDGET });
  assert.deepEqual(sizeCalls, []);
  assert.deepEqual(node.size, [640, 840]);
});

test("loaded workflow nodes never receive automatic preview sizing", () => {
  const { node, sizeCalls } = previewNode();
  installPreviewPolicy(node);
  markNodeLoaded(node);
  node.addCustomWidget({ name: NATIVE_IMAGE_PREVIEW_WIDGET });
  assert.deepEqual(sizeCalls, []);
});

test("nodes without a preview never change size", () => {
  const { node, sizeCalls } = previewNode();
  installPreviewPolicy(node);
  node.addCustomWidget({ name: "text-widget" });
  assert.deepEqual(sizeCalls, []);
});

test("preview installation is idempotent and handles missing APIs", () => {
  const { node, sizeCalls } = previewNode();
  assert.equal(installPreviewPolicy(node), true);
  assert.equal(installPreviewPolicy(node), true);
  node.addCustomWidget({ name: NATIVE_IMAGE_PREVIEW_WIDGET });
  assert.equal(sizeCalls.length, 1);
  assert.equal(installPreviewPolicy({ size: [300, 200] }), false);
});

test("invalid runtime sizes fail safely without repeated resizing", () => {
  const { node, sizeCalls } = previewNode([Number.NaN, 20], [Number.NaN, 10]);
  installPreviewPolicy(node);
  node.addCustomWidget({ name: NATIVE_IMAGE_PREVIEW_WIDGET });
  assert.deepEqual(sizeCalls, [
    [DEFAULT_PREVIEW_WIDTH, DEFAULT_PREVIEW_EXTRA_HEIGHT],
  ]);
});
