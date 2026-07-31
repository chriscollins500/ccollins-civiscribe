import type { ComfyGraph, ComfyNode, ComfyWidget } from "./types.js";

export type FilenameReplacement = (value: string) => string;

const configuredWidgets = new WeakSet<ComfyWidget>();
const DATE_PART = /dd?|MM?|hh?|mm?|ss?|yyy?y?/g;
const UNSAFE_REPLACEMENT_CHARACTERS = new Set([
  "/",
  "?",
  "<",
  ">",
  "\\",
  ":",
  "*",
  "|",
  '"',
]);

function graphNodes(graph: ComfyGraph): ComfyNode[] {
  return graph.nodes ?? graph._nodes ?? [];
}

function collectNodes(
  graph: ComfyGraph,
  visited: WeakSet<object> = new WeakSet(),
): ComfyNode[] {
  if (visited.has(graph)) {
    return [];
  }
  visited.add(graph);

  const collected: ComfyNode[] = [];
  for (const node of graphNodes(graph)) {
    if (node.subgraph !== undefined) {
      collected.push(...collectNodes(node.subgraph, visited));
    }
    collected.push(node);
  }
  return collected;
}

function formatDate(format: string, now: Date): string {
  return format.replace(DATE_PART, (part) => {
    if (part === "yy") {
      return String(now.getFullYear()).slice(-2);
    }
    if (part === "yyyy") {
      return String(now.getFullYear());
    }

    const values: Record<string, number> = {
      d: now.getDate(),
      M: now.getMonth() + 1,
      h: now.getHours(),
      m: now.getMinutes(),
      s: now.getSeconds(),
    };
    const numeric = values[part[0] ?? ""];
    return numeric === undefined
      ? part
      : String(numeric).padStart(part.length, "0");
  });
}

function replacementNode(
  nodes: ComfyNode[],
  name: string,
): ComfyNode | undefined {
  return (
    nodes.find((node) => node.properties?.["Node name for S&R"] === name) ??
    nodes.find((node) => node.title === name)
  );
}

function primitiveText(value: unknown): string {
  if (value === undefined || value === null) {
    return "";
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "bigint" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  return "";
}

function sanitizeReplacement(value: unknown): string {
  return Array.from(primitiveText(value), (character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return UNSAFE_REPLACEMENT_CHARACTERS.has(character) ||
      codePoint <= 0x1f ||
      codePoint === 0x7f
      ? "_"
      : character;
  }).join("");
}

export function applyComfyFilenameReplacements(
  graph: ComfyGraph,
  value: string,
  now: Date = new Date(),
): string {
  const nodes = collectNodes(graph);
  return value.replace(/%([^%]+)%/g, (match, token: string) => {
    const segments = token.split(".");
    if (segments.length !== 2) {
      return token.startsWith("date:")
        ? formatDate(token.slice(5), now)
        : match;
    }

    const [nodeName, widgetName] = segments;
    if (nodeName === undefined || widgetName === undefined) {
      return match;
    }
    const node = replacementNode(nodes, nodeName);
    const widget = node?.widgets?.find(
      (candidate) => candidate.name === widgetName,
    );
    if (widget === undefined) {
      return match;
    }
    return sanitizeReplacement(widget.value);
  });
}

export function installFilenameSerialization(
  node: ComfyNode,
  replaceFilename: FilenameReplacement,
): boolean {
  const widget = node.widgets?.find(
    (candidate) => candidate.name === "filename_prefix",
  );
  if (widget === undefined || configuredWidgets.has(widget)) {
    return false;
  }

  const original = widget.serializeValue;
  widget.serializeValue = function (...args: unknown[]): unknown {
    const rawValue =
      original === undefined ? widget.value : original.apply(this, args);
    if (rawValue === undefined || rawValue === null) {
      return replaceFilename("");
    }
    if (
      typeof rawValue === "string" ||
      typeof rawValue === "number" ||
      typeof rawValue === "bigint" ||
      typeof rawValue === "boolean"
    ) {
      return replaceFilename(String(rawValue));
    }
    return rawValue;
  };
  configuredWidgets.add(widget);
  return true;
}
