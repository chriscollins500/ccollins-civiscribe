export type NodeSize = [number, number];

export interface ComfyWidgetOptions {
  hidden?: boolean;
  [key: string]: unknown;
}

export interface ComfyWidget {
  name: string;
  value?: unknown;
  hidden?: boolean;
  options?: ComfyWidgetOptions;
  callback?: (this: unknown, ...args: unknown[]) => unknown;
  serializeValue?: (this: unknown, ...args: unknown[]) => unknown;
}

export interface ComfyGraph {
  nodes?: ComfyNode[];
  _nodes?: ComfyNode[];
  setDirtyCanvas?(foreground: boolean, background: boolean): void;
}

export interface ComfyNode {
  comfyClass?: string;
  type?: string;
  title?: string;
  properties?: Record<string, unknown>;
  widgets?: ComfyWidget[];
  size?: number[];
  graph?: ComfyGraph;
  subgraph?: ComfyGraph;
  isSubgraphNode?(): boolean;
  computeSize?(): number[];
  setSize?(size: NodeSize): void;
  setDirtyCanvas?(foreground: boolean, background: boolean): void;
  addCustomWidget?(widget: ComfyWidget): ComfyWidget;
}

export interface ComfyExtension {
  name: string;
  nodeCreated?(node: ComfyNode): void;
  loadedGraphNode?(node: ComfyNode): void;
}

export interface ComfyApp {
  graph: ComfyGraph;
  registerExtension(extension: ComfyExtension): void;
}
