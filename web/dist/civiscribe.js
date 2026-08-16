// @ts-expect-error ComfyUI supplies this runtime module to custom-node extensions.
import { app as runtimeApp } from "../../scripts/app.js";
import { createCiviScribeExtension } from "./extension.js";
import { applyComfyFilenameReplacements } from "./filename.js";
const app = runtimeApp;
app.registerExtension(createCiviScribeExtension((value) => applyComfyFilenameReplacements(app.graph, value)));
