# CiviScribe roadmap

[Website and project hub](https://chriscollins500.github.io/ccollins-civiscribe/guides/project-hub/)
· [User guide](https://github.com/chriscollins500/ccollins-civiscribe/wiki)
· [Contribute](CONTRIBUTING.md)

Follow the [public roadmap board](https://github.com/users/chriscollins500/projects/2/views/4)
for current priorities, ideas under consideration, and released improvements.
It is also linked from this repository's **Projects** tab.

CiviScribe remains a focused image-save node for current ComfyUI Desktop,
with accurate generation metadata, high-quality images, and safe saving.

## Current priorities

- Keep up with current ComfyUI Desktop and native V3 changes.
- Keep Civitai metadata and resource identities accurate as its API evolves.
- Improve workflow examples and troubleshooting from real user feedback.
- Maintain release verification, image fidelity, and tested dependencies.

These are ongoing maintenance priorities. Individual fixes and features need
reproducible evidence and a reviewed scope before implementation.

## Ideas under consideration

- **Additional output-location controls:** deferred for a separate design
  review. Current output stays beneath ComfyUI's configured output root;
  absolute drive-letter paths remain unsupported.
- **Support for another image-generation application:** research a separate
  adapter only after checking demand, real exported images, and the host's
  integration options. The current node continues to target ComfyUI.

An idea on the board is not a commitment to build it. Future work has no
promised version or delivery date until it is explicitly scheduled.

## What the statuses mean

| Status | Meaning |
| --- | --- |
| Planned | An accepted maintenance priority or scoped piece of upcoming work. |
| In progress | Work has started. |
| Under consideration | An idea being evaluated; implementation is not committed. |
| Done | Released software or deployed documentation, with links to the result and validation evidence. |

The roadmap board shows priorities without requiring made-up deadlines.
The release timeline uses actual publication dates for shipped versions.
Release dates use America/New_York, matching the dated changelog sections.

## Website and documentation

The [website](https://chriscollins500.github.io/ccollins-civiscribe/) includes
the complete guide and interactive examples. Website and wiki updates can
deploy independently of a node release. Their source lives in this repository;
the publishing workflow validates the guides and synchronizes the wiki before
deploying the signed website artifact.

## Recent releases

| Release | Highlights |
| --- | --- |
| [2.0.12](https://github.com/chriscollins500/ccollins-civiscribe/releases/tag/v2.0.12) | Resolved development-tool path findings while preserving security checks and save-node behavior. |
| [2.0.11](https://github.com/chriscollins500/ccollins-civiscribe/releases/tag/v2.0.11) | Native read-only API and Comfy MCP integration; refreshed development and package checks. |
| [2.0.10](https://github.com/chriscollins500/ccollins-civiscribe/releases/tag/v2.0.10) | More precise resource identities, a complete wiki, and verified release artifacts. |
| [2.0.9](https://github.com/chriscollins500/ccollins-civiscribe/releases/tag/v2.0.9) | Model-name and counter filename tokens; updated Civitai hash-contract checks. |
| [2.0.8](https://github.com/chriscollins500/ccollins-civiscribe/releases/tag/v2.0.8) | Correct metadata detection with multiple save nodes in one workflow. |

The [changelog](CHANGELOG.md) records the full release history. The
[wiki](https://github.com/chriscollins500/ccollins-civiscribe/wiki) documents
what the current release can do.

## Feedback and suggestions

Share ideas or questions in
[GitHub Discussions](https://github.com/chriscollins500/ccollins-civiscribe/discussions).
For a reproducible bug or a specific improvement, use the
[issue forms](https://github.com/chriscollins500/ccollins-civiscribe/issues/new/choose).
See the [support guide](SUPPORT.md) for other ways to get help.

