from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from save_node.civitai.identity_cache import (
    IdentityCache,
    default_identity_cache_path,
    load_identity_cache,
    write_identity_cache,
)
from save_node.civitai.resource_cache_io import import_resource_cache


def main() -> int:
    parser = argparse.ArgumentParser(description="Import readable JSON into the Civitai identity cache.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=default_identity_cache_path())
    args = parser.parse_args()

    try:
        raw = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"errors": [{"code": "resource_cache_import_unreadable"}]}))
        return 1

    existing = load_identity_cache(args.output, allowed_roots=(args.output.parent,))
    result = import_resource_cache(raw, existing_cache=existing.cache if not existing.errors else IdentityCache.empty())
    write_warnings = write_identity_cache(result.cache, args.output, allowed_roots=(args.output.parent,))
    summary = {
        "imported": result.imported_count,
        "skipped": result.skipped_count,
        "warnings": [issue.to_json() for issue in (*existing.warnings, *result.warnings, *write_warnings)],
        "errors": [issue.to_json() for issue in (*existing.errors, *result.errors)],
    }
    print(json.dumps(summary, separators=(",", ":")))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
