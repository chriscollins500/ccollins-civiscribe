import { NODE_ID, PACKAGE_NAME } from "./identity.js";
import {
  installFilenameSerialization,
  type FilenameReplacement,
} from "./filename.js";
import { installPreviewPolicy, markNodeLoaded } from "./preview.js";
import type { ComfyExtension, ComfyNode } from "./types.js";
import { installProgressiveVisibility } from "./visibility.js";

export const EXTENSION_NAME = `${PACKAGE_NAME}.ui` as const;

export function isCiviScribeNode(node: ComfyNode): boolean {
  return (node.comfyClass ?? node.type) === NODE_ID;
}

function configureNode(
  node: ComfyNode,
  replaceFilename: FilenameReplacement,
): void {
  installFilenameSerialization(node, replaceFilename);
  installPreviewPolicy(node);
  installProgressiveVisibility(node);
}

export function createCiviScribeExtension(
  replaceFilename: FilenameReplacement = (value) => value,
): ComfyExtension {
  return {
    name: EXTENSION_NAME,
    nodeCreated(node: ComfyNode): void {
      if (isCiviScribeNode(node)) {
        configureNode(node, replaceFilename);
      }
    },
    loadedGraphNode(node: ComfyNode): void {
      if (isCiviScribeNode(node)) {
        markNodeLoaded(node);
        configureNode(node, replaceFilename);
      }
    },
  };
}
