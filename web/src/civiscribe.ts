// @ts-expect-error ComfyUI supplies this runtime module to custom-node extensions.
import { app as runtimeApp } from "../../scripts/app.js";

import { createCiviScribeExtension } from "./extension.js";
import { applyComfyFilenameReplacements } from "./filename.js";
import type { ComfyApp } from "./types.js";

const app = runtimeApp as unknown as ComfyApp;
app.registerExtension(
  createCiviScribeExtension((value) =>
    applyComfyFilenameReplacements(app.graph, value),
  ),
);
