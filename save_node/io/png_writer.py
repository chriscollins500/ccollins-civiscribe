"""PNG metadata writer helpers."""

from __future__ import annotations

from typing import Any

from ..metadata.serialize import to_json_text
from ..security.redaction import MAX_PNG_TEXT_BYTES, sanitize_metadata_text
from ..version import __version__

SOFTWARE_TEXT = f"ComfyUI; comfyui-civitai-save-node {__version__}"


def build_pnginfo(
    *,
    parameters: str,
    prompt: Any | None,
    extra_pnginfo: dict[str, Any],
    include_workflow: bool,
    civitai_manifest: dict[str, Any] | None,
) -> Any:
    """Build a Pillow PngInfo object with A1111-compatible parameters text."""

    from PIL.PngImagePlugin import PngInfo

    pnginfo = PngInfo()
    _add_parameters_text(pnginfo, parameters)
    _add_latin1_text(pnginfo, "Software", SOFTWARE_TEXT)

    if prompt is not None:
        _add_itxt(pnginfo, "prompt", to_json_text(prompt))

    for key, value in extra_pnginfo.items():
        if key == "workflow" and not include_workflow:
            continue
        _add_itxt(pnginfo, str(key), to_json_text(value))

    if civitai_manifest is not None:
        _add_itxt(pnginfo, "civitai", to_json_text(civitai_manifest))

    return pnginfo


def parameters_text_needs_latin1_fallback(parameters: str) -> bool:
    safe_value = _safe_png_text("parameters", parameters)
    return _latin1_compatible_text(safe_value) != safe_value


def _add_parameters_text(pnginfo: Any, parameters: str) -> None:
    safe_key = _safe_png_key("parameters")
    safe_value = _safe_png_text(safe_key, parameters)
    latin1_value = _latin1_compatible_text(safe_value)
    pnginfo.add_text(safe_key, latin1_value)
    if latin1_value != safe_value:
        _add_itxt(pnginfo, "parameters_utf8", safe_value)


def _add_latin1_text(pnginfo: Any, key: str, value: str) -> None:
    safe_key = _safe_png_key(key)
    safe_value = _latin1_compatible_text(_safe_png_text(safe_key, value))
    pnginfo.add_text(safe_key, safe_value)


def _add_itxt(pnginfo: Any, key: str, value: str) -> None:
    safe_key = _safe_png_key(key)
    safe_value = _safe_png_text(safe_key, value)
    if hasattr(pnginfo, "add_itxt"):
        pnginfo.add_itxt(safe_key, safe_value)
        return
    pnginfo.add_text(safe_key, safe_value)


def _safe_png_key(key: str) -> str:
    safe_key = sanitize_metadata_text(str(key)).replace("\n", " ").replace("\t", " ")
    safe_key = " ".join(safe_key.strip().split())
    safe_key = safe_key.encode("latin-1", errors="replace").decode("latin-1")
    safe_key = "".join(
        character
        for character in safe_key
        if character == " " or 32 <= ord(character) <= 126 or 161 <= ord(character) <= 255
    )
    safe_key = safe_key.encode("latin-1")[:79].decode("latin-1", errors="ignore").strip()
    return safe_key or "metadata"


def _safe_png_text(key: str, value: str) -> str:
    safe_value = sanitize_metadata_text(value)
    if len(safe_value.encode("utf-8")) <= MAX_PNG_TEXT_BYTES:
        return safe_value
    if key == "parameters":
        return "Metadata omitted: parameters exceeded maximum safe PNG metadata size"
    return to_json_text(
        {
            "metadataOmitted": True,
            "metadataKey": key,
            "reason": "metadata_text_too_large",
            "maxUtf8Bytes": MAX_PNG_TEXT_BYTES,
        }
    )


def _latin1_compatible_text(value: str) -> str:
    return value.encode("latin-1", errors="replace").decode("latin-1")


__all__ = [
    "SOFTWARE_TEXT",
    "build_pnginfo",
    "parameters_text_needs_latin1_fallback",
]
