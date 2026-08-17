"""Construct identity adapters from current ComfyUI-owned locations."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

from ..identity.civitai_client import (
    PROCESS_RATE_LIMIT_GATE,
    CivitaiClient,
    CivitaiLookupConfig,
)
from ..identity.hashing import HashCache
from ..identity.local_cache import IdentityCache
from ..identity.resolver import IdentityServices
from .model_files import ModelRootLocator, _folder_paths_roots

_FOLDER_PATHS_MODULE: ModuleType | None
try:
    import folder_paths
except ImportError:
    _FOLDER_PATHS_MODULE = None
else:
    _FOLDER_PATHS_MODULE = folder_paths

CACHE_DIRECTORY_NAME = "ccollins-civiscribe"


def _cache_root(folder_paths_module: object, output_root: Path) -> Path:
    getter = getattr(folder_paths_module, "get_user_directory", None)
    if callable(getter):
        try:
            value = getter()
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return Path(value) / CACHE_DIRECTORY_NAME
    return output_root / f".{CACHE_DIRECTORY_NAME}"


def identity_services_from_comfy(
    *,
    output_root: Path,
    enable_lookup: bool = False,
    lookup_timeout_seconds: float = 4.0,
) -> IdentityServices:
    """Build best-effort adapters; construction never performs network I/O."""

    folder_paths_module = _FOLDER_PATHS_MODULE
    if folder_paths_module is None:
        return IdentityServices(
            civitai=CivitaiClient(
                CivitaiLookupConfig(
                    enabled=enable_lookup,
                    timeout_seconds=lookup_timeout_seconds,
                ),
                rate_limit_gate=PROCESS_RATE_LIMIT_GATE,
            )
        )
    root = _cache_root(folder_paths_module, output_root)
    return IdentityServices(
        locator=ModelRootLocator(_folder_paths_roots(folder_paths_module)),
        hash_cache=HashCache(root / "hash-cache.json"),
        identity_cache=IdentityCache(root / "identity-cache.json"),
        civitai=CivitaiClient(
            CivitaiLookupConfig(
                enabled=enable_lookup,
                timeout_seconds=lookup_timeout_seconds,
            ),
            rate_limit_gate=PROCESS_RATE_LIMIT_GATE,
        ),
    )


__all__ = ["CACHE_DIRECTORY_NAME", "identity_services_from_comfy"]
