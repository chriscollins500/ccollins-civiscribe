"""Normalize untrusted filename templates below a trusted output root."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..domain import UnsafePathError

MAX_TEMPLATE_LENGTH = 512
MAX_COMPONENT_LENGTH = 120
_DATE_TOKEN = re.compile(r"%(?:date:|date_)([^%]+)%")
_DATE_FORMAT_PART = re.compile(r"dd?|DD?|MM?|hh?|HH?|mm?|ss?|yyy?y?|YYY?Y?")
_UNKNOWN_TOKEN = re.compile(r"%[^%]+%")
_INVALID_FILENAME = re.compile(r'[<>"|?*\x00-\x1f]')
_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]+$", re.IGNORECASE)
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class OutputPlan:
    """A verified output directory and safe filename stem."""

    root: Path
    directory: Path
    subfolder: str
    stem: str

    def next_counter(self, extension: str) -> int:
        """Return a useful starting counter; publication still handles races."""

        if _SAFE_EXTENSION.fullmatch(extension) is None:
            raise UnsafePathError("output_extension_invalid")
        counter_file = re.compile(
            rf"_(\d{{5,}})_{re.escape(extension)}$",
            re.IGNORECASE,
        )
        highest = 0
        prefix = f"{self.stem}_"
        try:
            entries = self.directory.iterdir()
            for entry in entries:
                if not entry.is_file() or not entry.name.startswith(prefix):
                    continue
                match = counter_file.search(entry.name)
                if match is not None:
                    highest = max(highest, int(match.group(1)))
        except FileNotFoundError:
            return 1
        return highest + 1


@dataclass(frozen=True, slots=True)
class TemplateValues:
    width: int
    height: int
    batch_index: int
    now: datetime
    model: str | None = None
    seed: int | None = None
    sampler: str | None = None


def _expand_tokens(
    value: str,
    values: TemplateValues,
) -> str:
    def replace_date(match: re.Match[str]) -> str:
        return _format_date(match.group(1), values.now)

    expanded = _DATE_TOKEN.sub(replace_date, value)
    scalar_tokens = {
        "%width%": values.width,
        "%height%": values.height,
        "%batch_num%": values.batch_index,
        "%year%": values.now.year,
        "%month%": values.now.month,
        "%day%": values.now.day,
        "%hour%": values.now.hour,
        "%minute%": values.now.minute,
        "%second%": values.now.second,
    }
    for token, replacement in scalar_tokens.items():
        expanded = expanded.replace(token, str(replacement))
    expanded = expanded.replace(
        "%model%",
        _sanitize_token_value(values.model, fallback="model"),
    )
    expanded = expanded.replace(
        "%seed%",
        _sanitize_token_value(values.seed, fallback="seed"),
    )
    expanded = expanded.replace(
        "%sampler%",
        _sanitize_token_value(values.sampler, fallback="sampler"),
    )
    if _UNKNOWN_TOKEN.search(expanded) is not None:
        raise UnsafePathError("filename_token_unknown")
    return expanded


def _format_date(format_text: str, now: datetime) -> str:
    def replace_part(match: re.Match[str]) -> str:
        part = match.group(0)
        if part == "yy":
            return str(now.year)[-2:]
        if part in {"yyyy", "YYYY"}:
            return str(now.year)
        if part[0] in {"d", "D"}:
            value = now.day
        elif part[0] == "M":
            value = now.month
        elif part[0] in {"h", "H"}:
            value = now.hour
        elif part[0] == "m":
            value = now.minute
        else:
            value = now.second
        return str(value).zfill(len(part))

    return _DATE_FORMAT_PART.sub(replace_part, format_text)


def _sanitize_token_value(value: object | None, *, fallback: str) -> str:
    raw = str(value).strip() if value is not None else ""
    normalized = raw.replace("\\", "_").replace("/", "_").replace(":", "_").replace("%", "_")
    return _sanitize_component(normalized or fallback)


def _sanitize_component(value: str) -> str:
    sanitized = _INVALID_FILENAME.sub("_", value).rstrip(" .")
    if not sanitized:
        raise UnsafePathError("filename_component_empty")
    if ":" in sanitized:
        raise UnsafePathError("filename_colon_rejected")
    if sanitized.partition(".")[0].upper() in _RESERVED_WINDOWS_NAMES:
        raise UnsafePathError("filename_device_name_rejected")
    return sanitized[:MAX_COMPONENT_LENGTH]


def _relative_components(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFC", value).replace("\\", "/")
    windows_path = PureWindowsPath(normalized)
    if (
        windows_path.drive
        or windows_path.root
        or PurePosixPath(normalized).is_absolute()
        or normalized.startswith("//")
    ):
        raise UnsafePathError("filename_absolute_path_rejected")

    raw_components = normalized.split("/")
    if any(component in {"", ".", ".."} for component in raw_components):
        raise UnsafePathError("filename_traversal_rejected")
    return tuple(_sanitize_component(component) for component in raw_components)


def _prepare_directory(root: Path, subfolders: tuple[str, ...]) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    resolved_root = root.resolve(strict=True)
    current = resolved_root
    for component in subfolders:
        current = current / component
        current.mkdir(exist_ok=True)
        if current.is_symlink():
            raise UnsafePathError("output_symlink_rejected")
        resolved_current = current.resolve(strict=True)
        if not resolved_current.is_relative_to(resolved_root):
            raise UnsafePathError("output_escape_rejected")
        current = resolved_current
    return resolved_root, current


def resolve_output_plan(
    output_root: Path,
    filename_prefix: str,
    *,
    values: TemplateValues,
) -> OutputPlan:
    """Resolve a safe output location, creating only explicit subfolders."""

    if not isinstance(filename_prefix, str):
        raise UnsafePathError("filename_template_not_string")
    if not filename_prefix or len(filename_prefix) > MAX_TEMPLATE_LENGTH:
        raise UnsafePathError("filename_template_length_invalid")

    expanded = _expand_tokens(filename_prefix, values)
    components = _relative_components(expanded)
    resolved_root, directory = _prepare_directory(output_root, components[:-1])
    subfolder = PurePosixPath(*components[:-1]).as_posix() if components[:-1] else ""
    return OutputPlan(
        root=resolved_root,
        directory=directory,
        subfolder=subfolder,
        stem=components[-1],
    )
