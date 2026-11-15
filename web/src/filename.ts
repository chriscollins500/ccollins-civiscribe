import type { ComfyGraph, ComfyNode, ComfyWidget } from "./types.js";

export type FilenameReplacement = (value: string) => string;

const configuredWidgets = new WeakSet<ComfyWidget>();
const DATE_PART = /dd?|DD?|MM?|hh?|HH?|mm?|ss?|yyy?y?|YYY?Y?/g;
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

function indexReplacementNodes(graph: ComfyGraph) {
  const aliases = new Map<string, ComfyNode>();
  const titles = new Map<string, ComfyNode>();
  const visited = new WeakSet<ComfyGraph>();
  const pending: ({ graph: ComfyGraph } | { node: ComfyNode })[] = [{ graph }];
  let item: (typeof pending)[number] | undefined;
  while ((item = pending.pop()) !== undefined) {
    if ("node" in item) {
      const { node } = item;
      const alias = node.properties?.["Node name for S&R"];
      if (typeof alias === "string" && !aliases.has(alias))
        aliases.set(alias, node);
      if (node.title !== undefined && !titles.has(node.title))
        titles.set(node.title, node);
    } else if (!visited.has(item.graph)) {
      visited.add(item.graph);
      // Preserve ComfyUI's child-before-parent order, including shared subgraphs.
      for (const node of [...graphNodes(item.graph)].reverse()) {
        pending.push({ node });
        if (node.subgraph !== undefined) pending.push({ graph: node.subgraph });
      }
    }
  }
  return (name: string) => aliases.get(name) ?? titles.get(name);
}

function formatDate(format: string, now: Date): string {
  return format.replace(DATE_PART, (part) => {
    if (part.toLowerCase() === "yy") {
      return String(now.getFullYear()).slice(-2);
    }
    if (part.toLowerCase() === "yyyy") {
      return String(now.getFullYear());
    }

    const values: Record<string, number> = {
      d: now.getDate(),
      D: now.getDate(),
      M: now.getMonth() + 1,
      h: now.getHours(),
      H: now.getHours(),
      m: now.getMinutes(),
      s: now.getSeconds(),
    };
    const numeric = values[part[0] ?? ""];
    return numeric === undefined
      ? part
      : String(numeric).padStart(part.length, "0");
  });
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
  let findNode: ReturnType<typeof indexReplacementNodes> | undefined;
  return value.replace(/%([^%]+)%/g, (match, token: string) => {
    if (token.startsWith("date:")) return formatDate(token.slice(5), now);
    const segments = token.split(".");
    if (segments.length !== 2) {
      return match;
    }

    const [nodeName, widgetName] = segments;
    if (nodeName === undefined || widgetName === undefined) {
      return match;
    }
    findNode ??= indexReplacementNodes(graph);
    const node = findNode(nodeName);
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
