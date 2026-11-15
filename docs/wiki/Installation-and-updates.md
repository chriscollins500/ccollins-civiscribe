# Installation and updates

CiviScribe targets current ComfyUI Desktop and its native V3 node API. The
package requires Python 3.12 or newer. Use the Python environment belonging
to your ComfyUI installation when installing manually.

## Install with ComfyUI Manager

1. Open ComfyUI Manager.
2. Search for **CiviScribe** or **CCollins' CiviScribe**.
3. Open the node-pack card and choose **Install**.
4. Restart ComfyUI after installation finishes.
5. Search the node menu for **CiviScribe - Save Image for Civitai**.

The node appears in **CCollins / CiviScribe**. Its internal class name is
`CCollins_CiviScribe_SaveImage`.

## Install manually

Open a terminal in the `custom_nodes` directory used by your ComfyUI instance.

```powershell
git clone https://github.com/chriscollins500/ccollins-civiscribe.git
cd ccollins-civiscribe
python -m pip install .
```

Here, `python` means ComfyUI's Python interpreter. Desktop, portable, and
manual installations keep it in different locations. Restart ComfyUI when
installation finishes. The official guide explains those environments.
[ComfyUI installation guide](https://docs.comfy.org/installation/install_custom_node)

## Update

For a Manager installation, use the update control on the CiviScribe node-pack
card, then restart ComfyUI.

For a manual Git installation, save any changes you made to the node's source,
then run these commands inside its repository using ComfyUI's Python.

```powershell
git pull --ff-only
python -m pip install --upgrade .
```

Restart ComfyUI and refresh its browser tab. `--ff-only` stops if your local
source has diverged, so you can review those changes before updating.

## Check the installed version

The installed source records its version in `civiscribe/version.py`. A newly
saved sidecar also reports it at `generationRecord.generator.version`.
Check the node pack in Manager to compare it with the current release.
[GitHub releases](https://github.com/chriscollins500/ccollins-civiscribe/releases)

## If the node is missing

Read ComfyUI's startup log for an import error. Confirm that dependencies were
installed into the interpreter that starts that instance. Keep one installed
CiviScribe custom-node root and restart after updating. The troubleshooting
guide covers missing nodes and stale browser code.
[Troubleshooting](https://github.com/chriscollins500/ccollins-civiscribe/wiki/Troubleshooting)
