from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from save_node.civitai.identity_cache import default_identity_cache_path, load_identity_cache
from save_node.civitai.resource_cache_io import export_resource_cache
from save_node.metadata.serialize import to_json_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the Civitai identity cache as readable JSON.")
    parser.add_argument("--input", type=Path, default=default_identity_cache_path())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    loaded = load_identity_cache(args.input, allowed_roots=(args.input.parent,))
    payload = export_resource_cache(loaded.cache)
    args.output.write_text(to_json_text(payload, indent=2), encoding="utf-8")
    if loaded.errors:
        print(json.dumps({"errors": [issue.to_json() for issue in loaded.errors]}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
