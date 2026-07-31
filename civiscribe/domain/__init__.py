"""Pure domain types for CiviScribe."""

from .errors import (
    CiviScribeError,
    InvalidImageError,
    SerializationError,
    UnsafePathError,
    WriteError,
)
from .generation import (
    GenerationSettings,
    IssueSeverity,
    PromptField,
    PromptRecord,
    ResourceKind,
    ResourceRecord,
    ResourceRole,
    ResourceStrengths,
    ScanIssue,
    WorkflowKind,
    WorkflowScan,
)
from .identity import (
    HashRecord,
    HashStatus,
    IdentitySource,
    LookupStatus,
    ResourceIdentity,
    ResourceStatus,
)
from .image import ImageFrame
from .record import (
    GENERATOR_NAME,
    Diagnostics,
    GenerationRecord,
    GeneratorRecord,
    ImageFormat,
    ImageRecord,
    generation_record_from_scan,
)

__all__ = [
    "GENERATOR_NAME",
    "CiviScribeError",
    "Diagnostics",
    "GenerationRecord",
    "GenerationSettings",
    "GeneratorRecord",
    "HashRecord",
    "HashStatus",
    "IdentitySource",
    "ImageFormat",
    "ImageFrame",
    "ImageRecord",
    "InvalidImageError",
    "IssueSeverity",
    "LookupStatus",
    "PromptField",
    "PromptRecord",
    "ResourceIdentity",
    "ResourceKind",
    "ResourceRecord",
    "ResourceRole",
    "ResourceStatus",
    "ResourceStrengths",
    "ScanIssue",
    "SerializationError",
    "UnsafePathError",
    "WorkflowKind",
    "WorkflowScan",
    "WriteError",
    "generation_record_from_scan",
]
