import { app } from "../../scripts/app.js";

const EXTENSION_NAME = "comfyui-civitai-save-node.advanced-json-ui";
const NODE_NAME = "SaveImageWithCivitaiMetadata";
const ADVANCED_TOGGLE = "advanced_manual_identities_enabled";
const MANUAL_JSON = "manual_resource_identities_json";
const EDITOR_BUTTON = "__civitaiSaveEditResourceJson";
const EDITOR_BUTTON_LABEL = "Advanced resource JSON";
const DEFAULT_NODE_WIDTH = 600;
const DEBUG = false;
const ORIGINALS_KEY = "__civitaiSaveOriginals";
const TOGGLE_ATTACHED_KEY = "__civitaiSaveToggleAttached";
const EDITOR_ATTACHED_KEY = "__civitaiSaveEditorAttached";
const DEFAULT_WIDTH_KEY = "__civitaiSaveDefaultWidthApplied";
const DOM_STYLE_CACHE = new WeakMap();

function findWidget(node, name) {
  return node?.widgets?.find((widget) => widget?.name === name) || null;
}

function findEditorButton(node) {
  return node?.widgets?.find((widget) => widget?.[EDITOR_ATTACHED_KEY]) || findWidget(node, EDITOR_BUTTON);
}

function debugLog(...args) {
  if (DEBUG) {
    console.debug("[civitai-save-node]", ...args);
  }
}

function storeWidgetOriginals(widget) {
  if (!widget || widget[ORIGINALS_KEY]) {
    return;
  }
  widget[ORIGINALS_KEY] = {
    computeSize: widget.computeSize,
    draw: widget.draw,
  };
}

function restoreWidgetFunction(widget, name) {
  const originals = widget?.[ORIGINALS_KEY];
  if (!widget || !originals) {
    return;
  }
  if (typeof originals[name] === "function") {
    widget[name] = originals[name];
  } else {
    delete widget[name];
  }
}

function isDomElement(value) {
  return typeof HTMLElement !== "undefined" && value instanceof HTMLElement;
}

function collectWidgetDomElements(widget) {
  const elements = [];
  const props = ["element", "inputEl", "input", "textarea", "container", "el", "domElement"];
  for (const prop of props) {
    const value = widget?.[prop];
    if (isDomElement(value)) {
      elements.push(value);
      if (isDomElement(value.parentElement)) {
        elements.push(value.parentElement);
      }
    }
  }
  return [...new Set(elements)];
}

function setDomVisible(widget, visible) {
  for (const element of collectWidgetDomElements(widget)) {
    if (!DOM_STYLE_CACHE.has(element)) {
      DOM_STYLE_CACHE.set(element, {
        display: element.style.display,
        visibility: element.style.visibility,
        pointerEvents: element.style.pointerEvents,
      });
    }
    const original = DOM_STYLE_CACHE.get(element) || {};
    if (visible) {
      element.style.display = original.display || "";
      element.style.visibility = original.visibility || "";
      element.style.pointerEvents = original.pointerEvents || "";
    } else {
      element.style.display = "none";
      element.style.visibility = "hidden";
      element.style.pointerEvents = "none";
    }
  }
}

function setWidgetCollapsed(widget, collapsed) {
  if (!widget) {
    return;
  }
  storeWidgetOriginals(widget);

  widget.hidden = collapsed;
  setDomVisible(widget, !collapsed);

  if (!collapsed) {
    restoreWidgetFunction(widget, "computeSize");
    restoreWidgetFunction(widget, "draw");
  } else {
    widget.computeSize = () => [0, 0];
    widget.draw = () => {};
  }
}

function invalidateWidgetLayout(widget) {
  try {
    if (widget) {
      widget.last_y = undefined;
      widget.y = undefined;
    }
  } catch (_) {
    // Cosmetic cache clearing only.
  }
}

function applyDefaultNodeWidth(node) {
  try {
    if (!node || node[DEFAULT_WIDTH_KEY]) {
      return;
    }
    node[DEFAULT_WIDTH_KEY] = true;
    if (typeof node.setSize !== "function") {
      return;
    }
    const width = Math.max(Number(node.size?.[0] || 0), DEFAULT_NODE_WIDTH);
    const height = Number(node.size?.[1] || 0) || Number(node.computeSize?.()?.[1] || 0) || 320;
    node.setSize([width, height]);
  } catch (_) {
    // Default sizing is cosmetic only.
  }
}

function markDirty(node) {
  try {
    node?.setDirtyCanvas?.(true, true);
    node?.graph?.setDirtyCanvas?.(true, true);
    app?.graph?.setDirtyCanvas?.(true, true);
    app?.canvas?.setDirty?.(true, true);
    app?.canvas?.setDirtyCanvas?.(true, true);
  } catch (_) {
    // UI polish must never break the graph.
  }
}

function fitNode(node) {
  try {
    if (typeof node?.computeSize === "function" && typeof node?.setSize === "function") {
      const size = node.computeSize();
      if (Array.isArray(size) && size.length >= 2) {
        const currentWidth = Number(node.size?.[0] || 0);
        node.setSize([Math.max(currentWidth, Number(size[0] || 0)), Number(size[1] || node.size?.[1] || 0)]);
      }
    }
    markDirty(node);
  } catch (_) {
    markDirty(node);
  }
}

function normalizeEditorValue(value) {
  const text = String(value ?? "").trim();
  return text || "[]";
}

function jsonStatus(value) {
  const text = normalizeEditorValue(value);
  if (text === "[]") {
    return "Empty";
  }
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      return parsed.length === 1 ? "1 entry" : `${parsed.length} entries`;
    }
    return "Valid JSON";
  } catch (_) {
    return "Invalid";
  }
}

function updateEditorButton(button, manualJson) {
  if (!button) {
    return;
  }
  button.name = EDITOR_BUTTON_LABEL;
  button.value = `Edit JSON (${jsonStatus(manualJson?.value)})`;
  button.label = button.value;
  button.serialize = false;
  button.options = { ...(button.options || {}), serialize: false };
}

function applyEditorValue(node, manualJson, value) {
  const nextValue = normalizeEditorValue(value);
  const previousValue = manualJson.value;
  manualJson.value = nextValue;
  try {
    manualJson.callback?.(nextValue, app?.canvas, app?.graph);
  } catch (_) {
    // Backend parsing remains authoritative; UI callbacks are best-effort.
  }
  try {
    node?.onWidgetChanged?.(manualJson.name, nextValue, previousValue, manualJson);
  } catch (_) {
    // Some ComfyUI builds do not expose this hook.
  }
  updateEditorButton(findEditorButton(node), manualJson);
  markDirty(node);
}

function setModalStatus(statusEl, textarea) {
  if (!statusEl || !textarea) {
    return;
  }
  const text = normalizeEditorValue(textarea.value);
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      statusEl.textContent = parsed.length === 0 ? "Valid JSON array: empty" : `Valid JSON array: ${parsed.length} entries`;
    } else {
      statusEl.textContent = "Valid JSON, but not an array";
    }
    statusEl.style.color = "#78d99f";
  } catch (_) {
    statusEl.textContent = "Invalid JSON. You can still apply it; backend safety will warn and keep saving pixels.";
    statusEl.style.color = "#ffbf66";
  }
}

function closeModal(overlay) {
  try {
    overlay?.remove();
  } catch (_) {
    // Closing the editor must never affect the graph.
  }
}

function openJsonEditor(node, manualJson) {
  if (!manualJson || typeof document === "undefined") {
    return;
  }

  const overlay = document.createElement("div");
  overlay.style.position = "fixed";
  overlay.style.inset = "0";
  overlay.style.zIndex = "10000";
  overlay.style.background = "rgba(0, 0, 0, 0.55)";
  overlay.style.display = "flex";
  overlay.style.alignItems = "center";
  overlay.style.justifyContent = "center";
  overlay.style.padding = "24px";

  const panel = document.createElement("div");
  panel.style.width = "min(920px, calc(100vw - 48px))";
  panel.style.height = "min(680px, calc(100vh - 48px))";
  panel.style.minWidth = "420px";
  panel.style.minHeight = "320px";
  panel.style.resize = "both";
  panel.style.overflow = "hidden";
  panel.style.display = "flex";
  panel.style.flexDirection = "column";
  panel.style.gap = "10px";
  panel.style.padding = "16px";
  panel.style.borderRadius = "8px";
  panel.style.border = "1px solid rgba(255,255,255,0.18)";
  panel.style.boxShadow = "0 18px 60px rgba(0,0,0,0.45)";
  panel.style.background = "#202124";
  panel.style.color = "#f4f4f5";

  const title = document.createElement("div");
  title.textContent = "Advanced resource JSON";
  title.style.fontSize = "16px";
  title.style.fontWeight = "600";

  const help = document.createElement("div");
  help.textContent = "Pins resource identities for advanced workflows. Invalid JSON never blocks image saving.";
  help.style.fontSize = "12px";
  help.style.opacity = "0.78";

  const textarea = document.createElement("textarea");
  textarea.value = normalizeEditorValue(manualJson.value);
  textarea.spellcheck = false;
  textarea.style.flex = "1";
  textarea.style.width = "100%";
  textarea.style.minHeight = "180px";
  textarea.style.boxSizing = "border-box";
  textarea.style.resize = "none";
  textarea.style.borderRadius = "6px";
  textarea.style.border = "1px solid rgba(255,255,255,0.18)";
  textarea.style.background = "#111315";
  textarea.style.color = "#f4f4f5";
  textarea.style.padding = "10px";
  textarea.style.fontFamily = "ui-monospace, SFMono-Regular, Consolas, monospace";
  textarea.style.fontSize = "12px";
  textarea.style.lineHeight = "1.4";

  const status = document.createElement("div");
  status.style.fontSize = "12px";
  setModalStatus(status, textarea);
  textarea.addEventListener("input", () => setModalStatus(status, textarea));

  const actions = document.createElement("div");
  actions.style.display = "flex";
  actions.style.justifyContent = "flex-end";
  actions.style.gap = "8px";

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "Cancel";
  cancel.style.padding = "8px 12px";

  const apply = document.createElement("button");
  apply.type = "button";
  apply.textContent = "Apply";
  apply.style.padding = "8px 12px";
  apply.style.fontWeight = "600";

  cancel.addEventListener("click", () => closeModal(overlay));
  apply.addEventListener("click", () => {
    applyEditorValue(node, manualJson, textarea.value);
    closeModal(overlay);
  });
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) {
      closeModal(overlay);
    }
  });
  overlay.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeModal(overlay);
    }
  });

  actions.append(cancel, apply);
  panel.append(title, help, textarea, status, actions);
  overlay.append(panel);
  document.body.append(overlay);
  textarea.focus();
}

function ensureEditorButton(node, manualJson) {
  if (!node || typeof node.addWidget !== "function") {
    return null;
  }
  let button = findEditorButton(node);
  if (!button) {
    button = node.addWidget("button", EDITOR_BUTTON, "Edit JSON", () => openJsonEditor(node, manualJson), {
      serialize: false,
    });
    button[EDITOR_ATTACHED_KEY] = true;
    button.serialize = false;
  }
  updateEditorButton(button, manualJson);
  return button;
}

function refreshAdvancedJsonVisibility(node) {
  try {
    const toggle = findWidget(node, ADVANCED_TOGGLE);
    const manualJson = findWidget(node, MANUAL_JSON);
    if (!toggle || !manualJson) {
      return;
    }
    const visible = Boolean(toggle.value);
    const editorButton = ensureEditorButton(node, manualJson);
    setWidgetCollapsed(manualJson, true);
    setWidgetCollapsed(editorButton, !visible);
    invalidateWidgetLayout(manualJson);
    invalidateWidgetLayout(editorButton);
    fitNode(node);
    debugLog("advanced JSON editor visibility", visible);
  } catch (_) {
    // Defensive by design: backend behavior remains authoritative.
  }
}

function scheduleRefresh(node) {
  refreshAdvancedJsonVisibility(node);
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => refreshAdvancedJsonVisibility(node));
  }
  setTimeout(() => refreshAdvancedJsonVisibility(node), 0);
}

function attachAdvancedJsonToggle(node) {
  try {
    const toggle = findWidget(node, ADVANCED_TOGGLE);
    const manualJson = findWidget(node, MANUAL_JSON);
    if (!toggle || !manualJson) {
      return;
    }
    ensureEditorButton(node, manualJson);
    if (!toggle[TOGGLE_ATTACHED_KEY]) {
      toggle[TOGGLE_ATTACHED_KEY] = true;
      const originalCallback = toggle.callback;
      toggle.callback = function (value, canvas, graph, pos, event) {
        const result = originalCallback?.apply(this, arguments);
        scheduleRefresh(node);
        return result;
      };
    }
    scheduleRefresh(node);
  } catch (_) {
    // The extension should fail closed without affecting node execution.
  }
}

app.registerExtension({
  name: EXTENSION_NAME,
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_NAME) {
      return;
    }
    const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = originalOnNodeCreated?.apply(this, arguments);
      applyDefaultNodeWidth(this);
      attachAdvancedJsonToggle(this);
      return result;
    };
    const originalOnConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const result = originalOnConfigure?.apply(this, arguments);
      attachAdvancedJsonToggle(this);
      return result;
    };
  },
});
