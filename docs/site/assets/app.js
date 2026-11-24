import {
  branches,
  chooseFormat,
  previewFilename,
  searchGuides,
} from "./lab-core.js";

const base = document.body.dataset.base;
document.documentElement.dataset.interactive = "true";
const one = (selector) => document.querySelector(selector);
const all = (selector) => [...document.querySelectorAll(selector)];
let toastTimer;
function announce(message) {
  const toast = one(".toast");
  clearTimeout(toastTimer);
  toast.textContent = message;
  toastTimer = setTimeout(() => {
    toast.textContent = "";
  }, 3200);
}

const themeButton = one(".theme-toggle");
function reflectTheme() {
  const light = document.documentElement.dataset.theme === "light";
  themeButton.setAttribute(
    "aria-label",
    `Switch to ${light ? "dark" : "light"} theme`,
  );
  themeButton.setAttribute("aria-pressed", String(light));
}
reflectTheme();
themeButton.addEventListener("click", () => {
  const next =
    document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("civiscribe-theme", next);
  } catch {
    /* Preferences are optional. */
  }
  reflectTheme();
});

async function copy(value, button) {
  try {
    if (!navigator.clipboard?.writeText)
      throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(value);
    const label = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => {
      button.textContent = label;
    }, 1800);
    announce("Copied to your clipboard.");
  } catch {
    announce(
      "Clipboard access is unavailable. Select the text and copy it manually.",
    );
  }
}
all("[data-copy-input]").forEach((button) =>
  button.addEventListener("click", () =>
    copy(document.getElementById(button.dataset.copyInput).value, button),
  ),
);
all("[data-copy-output]").forEach((button) =>
  button.addEventListener("click", () =>
    copy(
      document.getElementById(button.dataset.copyOutput).textContent,
      button,
    ),
  ),
);
all(".prose pre").forEach((pre) => {
  const wrap = document.createElement("div");
  wrap.className = "code-wrap";
  pre.before(wrap);
  wrap.append(pre);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-code";
  button.textContent = "Copy";
  button.setAttribute("aria-label", "Copy code example");
  button.addEventListener("click", () => copy(pre.textContent, button));
  wrap.append(button);
});

const dialog = one(".search-dialog");
const searchInput = one("#site-search");
const searchStatus = one(".search-status");
const resultsList = one(".search-results");
let indexPromise;
function loadIndex() {
  indexPromise ??= fetch(`${base}/search-index.json`, {
    credentials: "omit",
    signal: AbortSignal.timeout(8000),
  })
    .then((response) => {
      if (!response.ok) throw new Error("Search unavailable");
      return response.json();
    })
    .then((entries) => {
      if (!Array.isArray(entries) || entries.length > 200)
        throw new Error("Invalid search index");
      return entries.filter(
        (entry) =>
          typeof entry.title === "string" &&
          typeof entry.text === "string" &&
          typeof entry.url === "string" &&
          entry.url.startsWith(`${base}/`),
      );
    })
    .catch((error) => {
      indexPromise = undefined;
      throw error;
    });
  return indexPromise;
}
async function runSearch() {
  const query = searchInput.value;
  resultsList.replaceChildren();
  if (!query.trim()) {
    searchStatus.textContent =
      "Try “counter”, “LoRA”, “API”, or a setting name.";
    return;
  }
  searchStatus.textContent = "Searching the guides…";
  try {
    const entries = await loadIndex();
    if (query !== searchInput.value) return;
    const results = searchGuides(entries, query);
    searchStatus.textContent = results.length
      ? `${results.length} ${results.length === 1 ? "guide" : "guides"} found.`
      : "No matches yet. Try fewer words, a setting name, or “troubleshooting”.";
    for (const result of results) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = result.url;
      const title = document.createElement("strong");
      title.textContent = result.title;
      const description = document.createElement("p");
      description.textContent = result.description || result.text.slice(0, 150);
      link.append(title, description);
      item.append(link);
      resultsList.append(item);
    }
  } catch {
    searchStatus.textContent =
      "Search couldn’t load. You can still browse every topic in The field guide.";
  }
}
all(".search-trigger").forEach((button) =>
  button.addEventListener("click", () => {
    dialog.showModal();
    searchInput.focus();
    runSearch();
  }),
);
one("[data-close-search]").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) {
    const box = dialog.getBoundingClientRect();
    if (
      event.clientX < box.left ||
      event.clientX > box.right ||
      event.clientY < box.top ||
      event.clientY > box.bottom
    )
      dialog.close();
  }
});
searchInput.addEventListener("input", runSearch);
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") {
    const first = resultsList.querySelector("a");
    if (first) {
      event.preventDefault();
      first.focus();
    }
  }
});
document.addEventListener(
  "keydown",
  (event) => {
    if (event.key === "Escape" && dialog.open) {
      event.preventDefault();
      dialog.close();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (!dialog.open) dialog.showModal();
      searchInput.focus();
      runSearch();
    }
  },
  { capture: true },
);

if (one("#filename-pattern")) {
  function refreshFilename() {
    const result = previewFilename(one("#filename-pattern").value, {
      model: one("#filename-model").value,
      seed: one("#filename-seed").value,
      counter: one("#filename-counter").value,
      format: one("#filename-format").value,
    });
    one("#filename-output").textContent = result.ok
      ? result.path
      : "Pattern needs a little attention.";
    one("#filename-error").textContent = result.error;
    one("#filename-pattern").setAttribute("aria-invalid", String(!result.ok));
  }
  all("#filenames input, #filenames select").forEach((input) =>
    input.addEventListener("input", refreshFilename),
  );
  all("[data-pattern]").forEach((button) =>
    button.addEventListener("click", () => {
      one("#filename-pattern").value = button.dataset.pattern;
      refreshFilename();
    }),
  );
  refreshFilename();

  function selectBranch(key) {
    const branch = branches[key];
    if (!branch) return;
    all("[data-branch]").forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.branch === key),
      ),
    );
    all("[data-branch-row]").forEach((row) =>
      row.classList.toggle("is-active", row.dataset.branchRow === key),
    );
    one("#branch-name").textContent = branch.name;
    one("#branch-prompt").textContent = branch.prompt;
    const facts = one("#branch-facts");
    facts.replaceChildren();
    for (const [label, value] of [
      ["Model", branch.model],
      ["Seed", branch.seed],
      ["Steps", branch.steps],
      ["Active resources", branch.resource],
      ["Identity", branch.identity],
    ]) {
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = value;
      facts.append(term, description);
    }
  }
  all("[data-branch]").forEach((button) =>
    button.addEventListener("click", () => selectBranch(button.dataset.branch)),
  );
  selectBranch("portrait");

  function refreshFormat() {
    const result = chooseFormat({
      workflow: one("#format-workflow").checked,
      alpha: one("#format-alpha").checked,
      lossless: one("#format-lossless").checked,
      compact: one("#format-compact").checked,
    });
    one("#format-choice").textContent = result.format;
    one("#format-reason").textContent = result.reason;
  }
  all("#formats input").forEach((input) =>
    input.addEventListener("change", refreshFormat),
  );
  refreshFormat();

  const metadata = {
    parameters: {
      text: "A softly lit portrait in a sunlit studio.\nNegative prompt: blurry, low detail\nSteps: 28, Sampler: Euler, CFG scale: 7, Seed: 123, Size: 1024x768, Model: PortraitModel",
      explanation:
        "A1111-style text helps compatible image tools read common generation facts. This example contains no Civitai identity claim.",
    },
    record: {
      text: JSON.stringify(
        {
          example:
            "Concept only — not a complete GenerationRecord or sidecar schema",
          positive_prompt: "A softly lit portrait in a sunlit studio.",
          negative_prompt: "blurry, low detail",
          settings: {
            seed: 123,
            steps: 28,
            sampler: "euler",
            width: 1024,
            height: 768,
          },
          resources: [
            { filename: "PortraitModel.safetensors", identity: "unresolved" },
          ],
        },
        null,
        2,
      ),
      explanation:
        "One immutable generation record is the source of truth. This simplified teaching example is not a valid full sidecar; use the guide for the actual schema.",
    },
    report: {
      text: "Loading the documented save-report example…",
      explanation:
        "Native save reports describe committed outputs and status codes. They do not contain your prompts or raw workflow. The example is synthetic.",
    },
  };
  async function refreshMetadata() {
    const key = one("#metadata-view").value;
    const view = metadata[key];
    if (!view) return;
    one("#metadata-code").textContent = view.text;
    one("#metadata-explanation").textContent = view.explanation;
    if (key === "report") {
      try {
        const response = await fetch(`${base}/examples/save-report.json`, {
          credentials: "omit",
          signal: AbortSignal.timeout(8000),
        });
        if (!response.ok) throw new Error("Example unavailable");
        const example = await response.json();
        if (one("#metadata-view").value === "report")
          one("#metadata-code").textContent = JSON.stringify(example, null, 2);
      } catch {
        if (one("#metadata-view").value === "report")
          one("#metadata-code").textContent =
            "The example could not load. Open the API & MCP guide for the report contract.";
      }
    }
  }
  one("#metadata-view").addEventListener("change", refreshMetadata);
  refreshMetadata();
}
