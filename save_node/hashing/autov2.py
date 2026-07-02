"""AutoV2 hash helpers.

The AutoV2 value used by common Stable Diffusion tooling is represented as the
first 10 hex characters of the full file SHA256. The full SHA256 is still stored
separately so downstream tooling can use the stronger identity when needed.
"""

from __future__ import annotations

import hashlib

AUTO_V2_LENGTH = 10
AUTO_V1_LENGTH = 8
AUTO_V1_OFFSET = 0x100000
AUTO_V1_SIZE = 64 * 1024
MODEL_HASH_EXTENSIONS = {
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".gguf",
}


def compute_autov2_from_sha256(sha256: str) -> str:
    return sha256[:AUTO_V2_LENGTH]


def compute_autov1_from_chunk(chunk: bytes) -> str:
    return hashlib.sha256(chunk).hexdigest()[:AUTO_V1_LENGTH]


def should_compute_autov2(filename: str) -> bool:
    lowered = filename.lower()
    return any(lowered.endswith(extension) for extension in MODEL_HASH_EXTENSIONS)


__all__ = [
    "AUTO_V1_LENGTH",
    "AUTO_V1_OFFSET",
    "AUTO_V1_SIZE",
    "AUTO_V2_LENGTH",
    "compute_autov1_from_chunk",
    "compute_autov2_from_sha256",
    "should_compute_autov2",
]
