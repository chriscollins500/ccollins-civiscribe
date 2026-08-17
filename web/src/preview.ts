import type { ComfyNode, ComfyWidget, NodeSize } from "./types.js";

export const NATIVE_IMAGE_PREVIEW_WIDGET = "$$canvas-image-preview";
export const DEFAULT_PREVIEW_WIDTH = 420;
export const DEFAULT_PREVIEW_EXTRA_HEIGHT = 220;

interface PreviewState {
  initialSize: NodeSize;
  loaded: boolean;
  previewHandled: boolean;
  wrapped: boolean;
}

const previewStates = new WeakMap<ComfyNode, PreviewState>();

function finiteSize(value: number[] | undefined): NodeSize | undefined {
  if (
    value === undefined ||
    value.length < 2 ||
    !Number.isFinite(value[0]) ||
    !Number.isFinite(value[1])
  ) {
    return undefined;
  }
  return [Math.max(0, value[0] ?? 0), Math.max(0, value[1] ?? 0)];
}

function currentSize(node: ComfyNode): NodeSize {
  return finiteSize(node.size) ?? [0, 0];
}

function sameSize(left: NodeSize, right: NodeSize): boolean {
  return left[0] === right[0] && left[1] === right[1];
}

export function defaultPreviewSize(
  minimum: NodeSize,
  current: NodeSize,
): NodeSize {
  return [
    Math.max(current[0], minimum[0], DEFAULT_PREVIEW_WIDTH),
    Math.max(current[1], minimum[1] + DEFAULT_PREVIEW_EXTRA_HEIGHT),
  ];
}

export function shouldExpandDefaultPreview(
  initial: NodeSize,
  current: NodeSize,
  loaded: boolean,
  previewHandled: boolean,
): boolean {
  return !loaded && !previewHandled && sameSize(initial, current);
}

function handlePreviewWidget(
  node: ComfyNode,
  widget: ComfyWidget,
  state: PreviewState,
): void {
  if (widget.name !== NATIVE_IMAGE_PREVIEW_WIDGET || state.previewHandled) {
    return;
  }
  const current = currentSize(node);
  const shouldExpand = shouldExpandDefaultPreview(
    state.initialSize,
    current,
    state.loaded,
    state.previewHandled,
  );
  state.previewHandled = true;
  if (!shouldExpand || node.setSize === undefined) {
    return;
  }
  const minimum = finiteSize(node.computeSize?.()) ?? current;
  node.setSize(defaultPreviewSize(minimum, current));
}

function stateFor(node: ComfyNode): PreviewState {
  const existing = previewStates.get(node);
  if (existing !== undefined) {
    return existing;
  }
  const state: PreviewState = {
    initialSize: currentSize(node),
    loaded: false,
    previewHandled: false,
    wrapped: false,
  };
  previewStates.set(node, state);
  return state;
}

export function installPreviewPolicy(node: ComfyNode): boolean {
  const state = stateFor(node);
  if (state.wrapped) {
    return true;
  }
  if (node.addCustomWidget === undefined) {
    return false;
  }
  // Reflect.apply below restores the original receiver before invocation.
  // eslint-disable-next-line @typescript-eslint/unbound-method
  const original = node.addCustomWidget;
  node.addCustomWidget = function (
    this: ComfyNode,
    widget: ComfyWidget,
  ): ComfyWidget {
    const result = Reflect.apply(original, node, [widget]);
    handlePreviewWidget(node, widget, state);
    return result;
  };
  state.wrapped = true;
  return true;
}

export function markNodeLoaded(node: ComfyNode): void {
  stateFor(node).loaded = true;
}
