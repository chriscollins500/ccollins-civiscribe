const configuredWidgets = new WeakSet();
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
function graphNodes(graph) {
    return graph.nodes ?? graph._nodes ?? [];
}
function collectNodes(graph, visited = new WeakSet()) {
    if (visited.has(graph)) {
        return [];
    }
    visited.add(graph);
    const collected = [];
    for (const node of graphNodes(graph)) {
        if (node.subgraph !== undefined) {
            collected.push(...collectNodes(node.subgraph, visited));
        }
        collected.push(node);
    }
    return collected;
}
function formatDate(format, now) {
    return format.replace(DATE_PART, (part) => {
        if (part === "yy") {
            return String(now.getFullYear()).slice(-2);
        }
        if (part === "yyyy") {
            return String(now.getFullYear());
        }
        const values = {
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
function replacementNode(nodes, name) {
    return (nodes.find((node) => node.properties?.["Node name for S&R"] === name) ??
        nodes.find((node) => node.title === name));
}
function primitiveText(value) {
    if (value === undefined || value === null) {
        return "";
    }
    if (typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "bigint" ||
        typeof value === "boolean") {
        return String(value);
    }
    return "";
}
function sanitizeReplacement(value) {
    return Array.from(primitiveText(value), (character) => {
        const codePoint = character.codePointAt(0) ?? 0;
        return UNSAFE_REPLACEMENT_CHARACTERS.has(character) ||
            codePoint <= 0x1f ||
            codePoint === 0x7f
            ? "_"
            : character;
    }).join("");
}
export function applyComfyFilenameReplacements(graph, value, now = new Date()) {
    const nodes = collectNodes(graph);
    return value.replace(/%([^%]+)%/g, (match, token) => {
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
        const widget = node?.widgets?.find((candidate) => candidate.name === widgetName);
        if (widget === undefined) {
            return match;
        }
        return sanitizeReplacement(widget.value);
    });
}
export function installFilenameSerialization(node, replaceFilename) {
    const widget = node.widgets?.find((candidate) => candidate.name === "filename_prefix");
    if (widget === undefined || configuredWidgets.has(widget)) {
        return false;
    }
    const original = widget.serializeValue;
    widget.serializeValue = function (...args) {
        const rawValue = original === undefined ? widget.value : original.apply(this, args);
        if (rawValue === undefined || rawValue === null) {
            return replaceFilename("");
        }
        if (typeof rawValue === "string" ||
            typeof rawValue === "number" ||
            typeof rawValue === "bigint" ||
            typeof rawValue === "boolean") {
            return replaceFilename(String(rawValue));
        }
        return rawValue;
    };
    configuredWidgets.add(widget);
    return true;
}
