"""Local and optional remote resource identity resolution."""

from .air import AirParseResult, parse_air
from .resolver import (
    HASHED_BUT_NO_CIVITAI_IDENTITY,
    IdentityResolutionOptions,
    IdentityResolutionResult,
    IdentityServices,
    resolve_resource_identities,
    resolve_scan_identities,
)
from .types import (
    HashingMode,
    HashStatus,
    LocatedResourceFile,
    LookupStatus,
    ResourceFileLocator,
)

__all__ = [
    "HASHED_BUT_NO_CIVITAI_IDENTITY",
    "AirParseResult",
    "HashStatus",
    "HashingMode",
    "IdentityResolutionOptions",
    "IdentityResolutionResult",
    "IdentityServices",
    "LocatedResourceFile",
    "LookupStatus",
    "ResourceFileLocator",
    "parse_air",
    "resolve_resource_identities",
    "resolve_scan_identities",
]
