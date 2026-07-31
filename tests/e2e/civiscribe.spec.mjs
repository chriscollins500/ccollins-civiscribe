import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const NODE_ID = "CCollins_CiviScribe_SaveImage";
const LOCALES = [
  "ar",
  "en",
  "es",
  "fa",
  "fr",
  "ja",
  "ko",
  "pt-BR",
  "ru",
  "tr",
  "zh",
  "zh-TW",
];
const WIDGET_NAMES = [
  "filename_prefix",
  "output_format",
  "jpeg_quality",
  "jpeg_alpha_background",
  "webp_lossless",
  "webp_quality",
  "write_sidecar_json",
  "include_workflow",
  "include_civitai_manifest",
  "enable_civitai_lookup",
  "preferred_primary_model_air",
  "hashing_mode",
  "lookup_timeout_seconds",
  "lookup_cache_results",
  "advanced_manual_identities_enabled",
  "manual_resource_identities_json",
];

async function openComfy(page) {
  await page.goto("/", { waitUntil: "networkidle" });
  await expect
    .poll(() =>
      page.evaluate(
        (nodeId) =>
          Boolean(globalThis.LiteGraph?.registered_node_types?.[nodeId]),
        NODE_ID,
      ),
    )
    .toBe(true);
}

async function setLocale(page, locale) {
  await page.evaluate(
    async (value) =>
      globalThis.app.extensionManager.setting.set("Comfy.Locale", value),
    locale,
  );
  await page.reload({ waitUntil: "networkidle" });
  await expect
    .poll(() =>
      page.evaluate(
        (value) =>
          globalThis.app.extensionManager.setting.get("Comfy.Locale") === value,
        locale,
      ),
    )
    .toBe(true);
}

test.afterEach(async ({ page }) => {
  if (!page.isClosed()) {
    await page.evaluate(async () => {
      await globalThis.app?.extensionManager?.setting?.set(
        "Comfy.Locale",
        "en",
      );
    });
  }
});

test("live V3 object info preserves the public contract", async ({
  request,
}) => {
  const response = await request.get(`/object_info/${NODE_ID}`);
  expect(response.ok()).toBe(true);
  const payload = await response.json();
  const info = payload[NODE_ID];
  expect(info.display_name).toBe("CiviScribe - Save Image for Civitai");
  expect(info.output_node).toBe(true);
  expect(info.output).toEqual([]);
  expect(Object.keys(info.input.required)).toContain("images");
  expect(Object.keys(info.input.optional)).toEqual([
    "positive_prompt_override",
    "negative_prompt_override",
  ]);
  expect(info.input.required.output_format[1].options).toEqual([
    "png",
    "jpeg",
    "webp",
  ]);
  expect(info.input.required.enable_civitai_lookup[1].default).toBe(false);
  expect(info.input.required.hashing_mode[1].default).toBe("cached_or_fast");
});

test("progressive disclosure preserves values, order, and node dimensions", async ({
  page,
}) => {
  await openComfy(page);
  const result = await page.evaluate(
    ({ nodeId, expectedNames }) => {
      const graph = globalThis.app.graph;
      graph.clear();
      const node = globalThis.LiteGraph.createNode(nodeId);
      graph.add(node);
      node.setSize([640, 760]);
      const beforeValues = node.widgets.map((widget) => widget.value);
      const beforeNames = node.widgets.map((widget) => widget.name);

      const byName = (name) =>
        node.widgets.find((widget) => widget.name === name);
      byName("output_format").value = "jpeg";
      byName("output_format").callback?.();
      byName("enable_civitai_lookup").value = true;
      byName("enable_civitai_lookup").callback?.();
      byName("advanced_manual_identities_enabled").value = true;
      byName("advanced_manual_identities_enabled").callback?.();

      const visibility = Object.fromEntries(
        node.widgets.map((widget) => [widget.name, widget.hidden !== true]),
      );
      const serialized = node.serialize();
      return {
        beforeNames,
        afterNames: node.widgets.map((widget) => widget.name),
        beforeValues,
        afterValues: node.widgets.map((widget) => widget.value),
        size: Array.from(node.size),
        serializedSize: serialized.size,
        visibility,
        expectedNames,
      };
    },
    { nodeId: NODE_ID, expectedNames: WIDGET_NAMES },
  );

  expect(result.beforeNames).toEqual(WIDGET_NAMES);
  expect(result.afterNames).toEqual(WIDGET_NAMES);
  expect(result.beforeNames).toEqual(result.expectedNames);
  expect(result.afterValues.filter((_, index) => index > 1)).toEqual(
    result.beforeValues
      .filter((_, index) => index > 1)
      .map((value, index) => {
        const name = WIDGET_NAMES[index + 2];
        if (name === "enable_civitai_lookup") return true;
        if (name === "advanced_manual_identities_enabled") return true;
        return value;
      }),
  );
  expect(result.size).toEqual([640, 760]);
  expect(result.serializedSize).toEqual([640, 760]);
  expect(result.visibility.jpeg_quality).toBe(true);
  expect(result.visibility.jpeg_alpha_background).toBe(true);
  expect(result.visibility.webp_quality).toBe(false);
  expect(result.visibility.lookup_timeout_seconds).toBe(true);
  expect(result.visibility.lookup_cache_results).toBe(true);
  expect(result.visibility.manual_resource_identities_json).toBe(true);
});

test("native preview does not overwrite a user-resized node", async ({
  page,
}) => {
  await openComfy(page);
  await page.evaluate((nodeId) => {
    const graph = globalThis.app.graph;
    graph.clear();
    const image = globalThis.LiteGraph.createNode("EmptyImage");
    const save = globalThis.LiteGraph.createNode(nodeId);
    image.pos = [100, 220];
    save.pos = [550, 140];
    graph.add(image);
    graph.add(save);
    image.connect(0, save, 0);
    for (const widget of image.widgets ?? []) {
      if (widget.name === "width") widget.value = 256;
      if (widget.name === "height") widget.value = 192;
    }
    for (const widget of save.widgets ?? []) {
      if (widget.name === "filename_prefix") {
        widget.value = `phase11/e2e_${Date.now()}`;
      }
      if (widget.name === "hashing_mode") widget.value = "cached_only";
    }
    save.setSize([700, 820]);
    globalThis.__civiscribeE2eSave = save;
  }, NODE_ID);

  await page.evaluate(async () => globalThis.app.queuePrompt(0, 1));
  await expect
    .poll(() =>
      page.evaluate(() => globalThis.__civiscribeE2eSave?.imgs?.length ?? 0),
    )
    .toBeGreaterThan(0);
  await page.mouse.click(40, 500);
  await page.mouse.click(50, 520);
  await page.mouse.click(60, 540);

  const result = await page.evaluate(() => {
    const node = globalThis.__civiscribeE2eSave;
    const serialized = globalThis.app.graph.serialize();
    return {
      size: Array.from(node.size),
      serializedSize: serialized.nodes.find((item) => item.type === node.type)
        ?.size,
      previewCount: node.widgets.filter(
        (widget) => widget.name === "$$canvas-image-preview",
      ).length,
      imageCount: node.imgs?.length ?? 0,
    };
  });
  expect(result.size).toEqual([700, 820]);
  expect(result.serializedSize).toEqual([700, 820]);
  expect(result.previewCount).toBe(1);
  expect(result.imageCount).toBe(1);
});

test("all shipped locales preserve runtime serialization identity", async ({
  page,
}) => {
  await openComfy(page);
  const observations = [];
  for (const locale of LOCALES) {
    await setLocale(page, locale);
    observations.push(
      await page.evaluate((nodeId) => {
        const node = globalThis.LiteGraph.createNode(nodeId);
        return {
          locale: globalThis.app.extensionManager.setting.get("Comfy.Locale"),
          title: node.title,
          inputNames: node.inputs.map((input) => input.name),
          widgetNames: node.widgets.map((widget) => widget.name),
          widgetLabels: node.widgets.map(
            (widget) => widget.label ?? widget.name,
          ),
        };
      }, NODE_ID),
    );
  }
  for (const item of observations) {
    expect(item.locale).toBeTruthy();
    expect(item.title.trim()).not.toBe("");
    expect(item.inputNames.slice(0, 3)).toEqual([
      "images",
      "positive_prompt_override",
      "negative_prompt_override",
    ]);
    expect(item.widgetNames).toEqual(WIDGET_NAMES);
    expect(item.widgetLabels.every((label) => label.trim() !== "")).toBe(true);
  }
});

test("CiviScribe adds no DOM accessibility violations to ComfyUI", async ({
  page,
}) => {
  await openComfy(page);
  const baseline = await new AxeBuilder({ page }).analyze();
  await page.evaluate((nodeId) => {
    const node = globalThis.LiteGraph.createNode(nodeId);
    globalThis.app.graph.add(node);
  }, NODE_ID);
  const withNode = await new AxeBuilder({ page }).analyze();
  const summary = (result) =>
    Object.fromEntries(
      result.violations.map((violation) => [
        violation.id,
        violation.nodes.length,
      ]),
    );
  expect(summary(withNode)).toEqual(summary(baseline));

  const runButton = page.getByTestId("queue-button");
  await runButton.focus();
  await expect(runButton).toBeFocused();
});
