"""Run the standard pip-audit CLI with application-native certificate trust."""

from __future__ import annotations

import runpy
import sys


def main() -> None:
    if sys.platform in {"win32", "darwin"}:
        import truststore  # noqa: PLC0415

        truststore.inject_into_ssl()
    runpy.run_module("pip_audit", run_name="__main__")


if __name__ == "__main__":
    main()
