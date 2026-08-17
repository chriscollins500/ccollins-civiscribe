import { NODE_ID, PACKAGE_NAME } from "./identity.js";
import { installFilenameSerialization, } from "./filename.js";
import { installPreviewPolicy, markNodeLoaded } from "./preview.js";
import { installProgressiveVisibility } from "./visibility.js";
export const EXTENSION_NAME = `${PACKAGE_NAME}.ui`;
export function isCiviScribeNode(node) {
    return (node.comfyClass ?? node.type) === NODE_ID;
}
function configureNode(node, replaceFilename) {
    installFilenameSerialization(node, replaceFilename);
    installPreviewPolicy(node);
    installProgressiveVisibility(node);
}
export function createCiviScribeExtension(replaceFilename = (value) => value) {
    return {
        name: EXTENSION_NAME,
        nodeCreated(node) {
            if (isCiviScribeNode(node)) {
                configureNode(node, replaceFilename);
            }
        },
        loadedGraphNode(node) {
            if (isCiviScribeNode(node)) {
                markNodeLoaded(node);
                configureNode(node, replaceFilename);
            }
        },
    };
}
