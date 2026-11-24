/** Small, deterministic teaching models. These never call a generation server. */
const MODEL_EXTENSION = /\.(safetensors|safetensor|ckpt|pt|pth|bin|gguf|sft)$/i;
const RESERVED =
  /^(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³]|conin\$|conout\$)(\.|$)/i;

export function modelBasename(value) {
  return (
    String(value || "model")
      .replaceAll("\\", "/")
      .split("/")
      .at(-1) || "model"
  );
}

export function modelNoExtension(value) {
  return modelBasename(value).replace(MODEL_EXTENSION, "");
}

export function formatExampleDate(pattern) {
  const values = {
    yyyy: "2026",
    YYYY: "2026",
    yy: "26",
    YY: "26",
    M: "11",
    MM: "11",
    d: "14",
    D: "14",
    dd: "14",
    DD: "14",
    h: "15",
    H: "15",
    hh: "15",
    HH: "15",
    m: "4",
    mm: "04",
    s: "5",
    ss: "05",
  };
  return pattern.replace(
    /yyyy|YYYY|yy|YY|MM|M|dd|DD|d|D|hh|HH|h|H|mm|m|ss|s/g,
    (part) => values[part],
  );
}

export function previewFilename(pattern, options = {}) {
  const invalid = (error) => ({ ok: false, path: "", error });
  if (typeof pattern !== "string" || !pattern.trim())
    return invalid("Enter a filename pattern to see a preview.");
  if (pattern.length > 500)
    return invalid("Keep this example pattern within 500 characters.");
  const normalized = pattern.replaceAll("\\", "/");
  if (normalized.startsWith("/") || /^[a-z]:/i.test(normalized))
    return invalid("Use a relative path beneath ComfyUI’s output folder.");
  const counter = Number(options.counter ?? 1);
  if (!Number.isSafeInteger(counter) || counter < 1 || counter > 999999999)
    return invalid("Choose a whole example counter from 1 to 999999999.");
  const format = options.format ?? "png";
  if (!["png", "jpeg", "webp"].includes(format))
    return invalid("Choose PNG, JPEG, or WebP.");
  const aliases = {
    model: modelBasename(options.model),
    model_noext: modelNoExtension(options.model),
    seed: String(options.seed || "seed"),
    sampler: "euler",
    width: "1024",
    height: "768",
    batch_num: "0",
    year: "2026",
    month: "11",
    day: "14",
    hour: "15",
    minute: "4",
    second: "5",
  };
  let counterCount = 0;
  let tokenError = "";
  const pieces = normalized.split("/");
  const expanded = pieces.map((piece, index) =>
    piece.replace(/%([^%]+)%/g, (whole, token) => {
      if (token.startsWith("counter")) {
        counterCount += 1;
        if (!/^counter(?::[1-9])?$/.test(token))
          tokenError =
            "Counter padding must be one digit from 1 to 9, for example %counter:4%.";
        if (index !== pieces.length - 1)
          tokenError = "Place the counter in the filename, not in a subfolder.";
        const width = /^counter:([1-9])$/.exec(token)?.[1] ?? "5";
        return String(counter).padStart(Number(width), "0");
      }
      if (token.startsWith("date:")) return formatExampleDate(token.slice(5));
      if (Object.hasOwn(aliases, token)) return aliases[token];
      tokenError = token.includes(".")
        ? "Widget tokens need ComfyUI to resolve them. This browser demo can’t inspect your nodes."
        : `Unknown example token: ${whole}`;
      return whole;
    }),
  );
  if (counterCount > 1)
    return invalid("Use the counter token once in a filename.");
  if (tokenError) return invalid(tokenError);
  for (const piece of expanded) {
    if (
      !piece ||
      piece === "." ||
      piece === ".." ||
      /[<>:"|?*%/\\]/.test(piece) ||
      [...piece].some((character) => character.charCodeAt(0) < 32) ||
      /[. ]$/.test(piece) ||
      RESERVED.test(piece)
    )
      return invalid(
        "That pattern contains an unsafe or unresolved path component. Try a plain relative folder and filename.",
      );
  }
  const leaf = expanded.pop();
  const suffix = counterCount ? "" : `_${String(counter).padStart(5, "0")}_`;
  const extension = format === "jpeg" ? "jpg" : format;
  return {
    ok: true,
    path: [...expanded, `${leaf}${suffix}.${extension}`].join("/"),
    error: "",
  };
}

export function chooseFormat({
  workflow = false,
  alpha = false,
  lossless = true,
  compact = false,
} = {}) {
  if (workflow)
    return {
      format: "PNG",
      reason:
        "PNG carries the reloadable ComfyUI workflow payloads and preserves pixels losslessly. Keep workflow embedding enabled.",
    };
  if (lossless && compact)
    return {
      format: "WebP",
      reason:
        "Lossless WebP preserves decoded 8-bit samples and transparency. Actual file size depends on the image; it is not a full workflow container.",
    };
  if (alpha)
    return {
      format: compact ? "WebP" : "PNG",
      reason:
        "PNG and lossless WebP preserve transparency. JPEG must flatten it onto a background. Keep WebP’s lossless setting enabled when sample preservation matters.",
    };
  if (compact && !lossless)
    return {
      format: "JPEG",
      reason:
        "JPEG is widely shareable and lossy. CiviScribe defaults to quality 100 and 4:4:4 chroma. A smaller result is image-dependent; choose PNG or lossless WebP for sample preservation.",
    };
  return {
    format: "PNG",
    reason:
      "PNG is a straightforward lossless starting point with rich metadata support. Lossless WebP is another option when you do not need a reloadable workflow.",
  };
}

export const branches = Object.freeze({
  portrait: {
    name: "Portrait branch",
    prompt: "A softly lit portrait in a sunlit studio.",
    model: "PortraitModel.safetensors",
    seed: "123",
    steps: "28",
    resource: "WarmLight.safetensors · strength 0.65",
    identity: "No Civitai identity supplied in this example",
  },
  landscape: {
    name: "Landscape branch",
    prompt: "A quiet mountain lake under a wide, silver sky.",
    model: "LandscapeModel.gguf",
    seed: "456",
    steps: "32",
    resource: "No active LoRA in this example",
    identity: "No Civitai identity supplied in this example",
  },
  experiment: {
    name: "Mystery-resource branch",
    prompt: "An imaginary paper city, folded out of moonlight.",
    model: "CustomModel.safetensors",
    seed: "789",
    steps: "24",
    resource: "MysteryStyle.safetensors · strength 0.8",
    identity: "Unresolved. A filename is not a model-version ID.",
  },
});

export function searchGuides(entries, query) {
  const normalize = (value) =>
    String(value)
      .normalize("NFKD")
      .replace(/\p{Diacritic}/gu, "")
      .toLowerCase();
  const terms = normalize(query)
    .trim()
    .slice(0, 160)
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 8);
  if (!terms.length) return [];
  return entries
    .map((entry) => {
      const title = normalize(entry.title);
      const text = normalize(entry.text);
      const matched = terms.every(
        (term) => title.includes(term) || text.includes(term),
      );
      const score = matched
        ? terms.reduce(
            (total, term) =>
              total +
              (title.includes(term) ? 100 : 0) +
              (title.startsWith(term) ? 40 : 0) +
              (text.includes(term) ? 10 : 0),
            0,
          )
        : 0;
      return { ...entry, score };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || a.title.localeCompare(b.title))
    .slice(0, 10);
}
