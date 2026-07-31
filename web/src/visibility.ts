import type { ComfyNode, ComfyWidget } from "./types.js";

const FORMAT_WIDGETS = {
  jpeg: ["jpeg_quality", "jpeg_alpha_background"],
  webp: ["webp_lossless", "webp_quality"],
} as const;

const LOOKUP_WIDGETS = [
  "lookup_timeout_seconds",
  "lookup_cache_results",
] as const;
const MANUAL_WIDGET = "manual_resource_identities_json";
const CONTROLLING_WIDGETS = [
  "output_format",
  "enable_civitai_lookup",
  "advanced_manual_identities_enabled",
] as const;

export interface VisibilityState {
  outputFormat: string;
  lookupEnabled: boolean;
  manualIdentitiesEnabled: boolean;
}

export type WidgetVisibility = Readonly<Record<string, boolean>>;

function widgetByName(node: ComfyNode, name: string): ComfyWidget | undefined {
  return node.widgets?.find((widget) => widget.name === name);
}

function textValue(widget: ComfyWidget | undefined, fallback: string): string {
  return typeof widget?.value === "string"
    ? widget.value.toLowerCase()
    : fallback;
}

function booleanValue(widget: ComfyWidget | undefined): boolean {
  return widget?.value === true;
}

export function visibilityState(node: ComfyNode): VisibilityState {
  return {
    outputFormat: textValue(widgetByName(node, "output_format"), "png"),
    lookupEnabled: booleanValue(widgetByName(node, "enable_civitai_lookup")),
    manualIdentitiesEnabled: booleanValue(
      widgetByName(node, "advanced_manual_identities_enabled"),
    ),
  };
}

export function deriveWidgetVisibility(
  state: VisibilityState,
): WidgetVisibility {
  return {
    jpeg_quality: state.outputFormat === "jpeg",
    jpeg_alpha_background: state.outputFormat === "jpeg",
    webp_lossless: state.outputFormat === "webp",
    webp_quality: state.outputFormat === "webp",
    lookup_timeout_seconds: state.lookupEnabled,
    lookup_cache_results: state.lookupEnabled,
    manual_resource_identities_json: state.manualIdentitiesEnabled,
  };
}

function setWidgetVisible(widget: ComfyWidget, visible: boolean): boolean {
  const hidden = !visible;
  widget.options ??= {};
  const changed = widget.hidden !== hidden || widget.options.hidden !== hidden;
  widget.hidden = hidden;
  widget.options.hidden = hidden;
  return changed;
}

function markCanvasDirty(node: ComfyNode): void {
  if (node.setDirtyCanvas !== undefined) {
    node.setDirtyCanvas(true, true);
    return;
  }
  node.graph?.setDirtyCanvas?.(true, true);
}

export function applyProgressiveVisibility(node: ComfyNode): boolean {
  const policy = deriveWidgetVisibility(visibilityState(node));
  let changed = false;
  for (const [name, visible] of Object.entries(policy)) {
    const widget = widgetByName(node, name);
    if (widget !== undefined) {
      changed = setWidgetVisible(widget, visible) || changed;
    }
  }
  if (changed) {
    markCanvasDirty(node);
  }
  return changed;
}

const configuredNodes = new WeakSet<ComfyNode>();

function wrapControlCallback(node: ComfyNode, widget: ComfyWidget): void {
  const original = widget.callback;
  widget.callback = function (this: unknown, ...args: unknown[]): unknown {
    const result = original?.apply(this, args);
    applyProgressiveVisibility(node);
    return result;
  };
}

export function installProgressiveVisibility(node: ComfyNode): boolean {
  if (configuredNodes.has(node)) {
    applyProgressiveVisibility(node);
    return true;
  }
  const controls = CONTROLLING_WIDGETS.map((name) =>
    widgetByName(node, name),
  ).filter((widget): widget is ComfyWidget => widget !== undefined);
  if (controls.length === 0) {
    return false;
  }
  for (const widget of controls) {
    wrapControlCallback(node, widget);
  }
  configuredNodes.add(node);
  applyProgressiveVisibility(node);
  return true;
}

export const PROGRESSIVE_WIDGET_NAMES = Object.freeze([
  ...FORMAT_WIDGETS.jpeg,
  ...FORMAT_WIDGETS.webp,
  ...LOOKUP_WIDGETS,
  MANUAL_WIDGET,
]);
