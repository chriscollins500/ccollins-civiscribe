# Workflow Fixtures

Only compact, sanitized API-prompt and workflow graphs belong here.

The initial project-authored fixture set covers a basic checkpoint graph,
linked scalar controls, active GGUF/LoRA/VAE/text-encoder lineage with
disconnected resource exclusion, Unicode text, a zeroed negative branch, and
rgthree Power LoRA enabled/disabled entries.

The corpus also covers ND Super LoRA Loader's source-defined JSON bundle,
including enabled, disabled, zero-strength, and split model/CLIP entries.

Switch-selected checkpoints, multiple prompt encoders, img2img
classification, malformed graphs, duplicate resources, and traversal limits
are exercised with compact synthetic graphs in focused unit tests.
