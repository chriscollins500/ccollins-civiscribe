import assert from "node:assert/strict";
import test from "node:test";

import {
  applyProgressiveVisibility,
  deriveWidgetVisibility,
  installProgressiveVisibility,
  PROGRESSIVE_WIDGET_NAMES,
  visibilityState,
} from "../../web/runtime/visibility.js";

function widget(name, value) {
  return { name, value, options: {} };
}

function nodeWithWidgets() {
  const dirtyCalls = [];
  const sizeCalls = [];
  const widgets = [
    widget("filename_prefix", "ComfyUI"),
    widget("output_format", "png"),
    widget("jpeg_quality", 100),
    widget("jpeg_alpha_background", "#FFFFFF"),
    widget("webp_lossless", true),
    widget("webp_quality", 100),
    widget("write_sidecar_json", false),
    widget("include_workflow", true),
    widget("include_civitai_manifest", true),
    widget("enable_civitai_lookup", false),
    widget("preferred_primary_model_air", ""),
    widget("hashing_mode", "cached_or_fast"),
    widget("lookup_timeout_seconds", 4),
    widget("lookup_cache_results", true),
    widget("advanced_manual_identities_enabled", false),
    widget("manual_resource_identities_json", "[]"),
  ];
  return {
    node: {
      widgets,
      setDirtyCanvas(...args) {
        dirtyCalls.push(args);
      },
      setSize(...args) {
        sizeCalls.push(args);
      },
    },
    widgets,
    dirtyCalls,
    sizeCalls,
  };
}

function byName(widgets, name) {
  return widgets.find((item) => item.name === name);
}

test("visibility policy is deterministic for every image format", () => {
  assert.deepEqual(
    deriveWidgetVisibility({
      outputFormat: "png",
      lookupEnabled: false,
      manualIdentitiesEnabled: false,
    }),
    {
      jpeg_quality: false,
      jpeg_alpha_background: false,
      webp_lossless: false,
      webp_quality: false,
      lookup_timeout_seconds: false,
      lookup_cache_results: false,
      manual_resource_identities_json: false,
    },
  );
  assert.equal(
    deriveWidgetVisibility({
      outputFormat: "jpeg",
      lookupEnabled: true,
      manualIdentitiesEnabled: true,
    }).jpeg_quality,
    true,
  );
  assert.equal(
    deriveWidgetVisibility({
      outputFormat: "webp",
      lookupEnabled: false,
      manualIdentitiesEnabled: false,
    }).webp_lossless,
    true,
  );
});

test("visibility updates both renderers without changing values, order, or size", () => {
  const { node, widgets, dirtyCalls, sizeCalls } = nodeWithWidgets();
  const originalOrder = widgets.map((item) => item.name);
  const originalValues = widgets.map((item) => item.value);

  assert.equal(applyProgressiveVisibility(node), true);
  for (const name of PROGRESSIVE_WIDGET_NAMES) {
    const item = byName(widgets, name);
    assert.equal(item.hidden, true);
    assert.equal(item.options.hidden, true);
  }
  assert.deepEqual(
    widgets.map((item) => item.name),
    originalOrder,
  );
  assert.deepEqual(
    widgets.map((item) => item.value),
    originalValues,
  );
  assert.deepEqual(sizeCalls, []);
  assert.deepEqual(dirtyCalls, [[true, true]]);
  assert.equal(applyProgressiveVisibility(node), false);
  assert.equal(dirtyCalls.length, 1);
});

test("format, lookup, and manual controls reveal only their dependents", () => {
  const { node, widgets } = nodeWithWidgets();
  installProgressiveVisibility(node);
  byName(widgets, "output_format").value = "jpeg";
  byName(widgets, "output_format").callback();
  byName(widgets, "enable_civitai_lookup").value = true;
  byName(widgets, "enable_civitai_lookup").callback();
  byName(widgets, "advanced_manual_identities_enabled").value = true;
  byName(widgets, "advanced_manual_identities_enabled").callback();

  assert.equal(byName(widgets, "jpeg_quality").hidden, false);
  assert.equal(byName(widgets, "jpeg_alpha_background").hidden, false);
  assert.equal(byName(widgets, "webp_lossless").hidden, true);
  assert.equal(byName(widgets, "lookup_timeout_seconds").hidden, false);
  assert.equal(byName(widgets, "lookup_cache_results").hidden, false);
  assert.equal(
    byName(widgets, "manual_resource_identities_json").hidden,
    false,
  );
});

test("callback chaining is installed once and preserves callback results", () => {
  const { node, widgets } = nodeWithWidgets();
  let calls = 0;
  const format = byName(widgets, "output_format");
  format.callback = () => {
    calls += 1;
    return "original-result";
  };
  assert.equal(installProgressiveVisibility(node), true);
  assert.equal(installProgressiveVisibility(node), true);
  format.value = "webp";
  assert.equal(format.callback("ignored"), "original-result");
  assert.equal(calls, 1);
  assert.equal(byName(widgets, "webp_quality").hidden, false);
});

test("visibility helpers fail open for incomplete nodes", () => {
  assert.deepEqual(visibilityState({ widgets: [] }), {
    outputFormat: "png",
    lookupEnabled: false,
    manualIdentitiesEnabled: false,
  });
  assert.equal(installProgressiveVisibility({ widgets: [] }), false);
  assert.equal(applyProgressiveVisibility({ widgets: [] }), false);
});

test("graph dirtiness is used when the node method is unavailable", () => {
  const { node, dirtyCalls } = nodeWithWidgets();
  delete node.setDirtyCanvas;
  node.graph = {
    setDirtyCanvas(...args) {
      dirtyCalls.push(args);
    },
  };
  assert.equal(applyProgressiveVisibility(node), true);
  assert.deepEqual(dirtyCalls, [[true, true]]);
});
