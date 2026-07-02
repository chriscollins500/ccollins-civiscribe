"""Inspect PNG chunk order and common metadata chunks without mutating the file."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from save_node.metadata.exif_user_comment import EXIF_IFD_TAG, USER_COMMENT_TAG, decode_user_comment


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TEXT_CHUNKS = {b"tEXt", b"zTXt", b"iTXt"}
KNOWN_METADATA = {
    "parameters",
    "prompt",
    "workflow",
    "civitai",
    "Software",
    "XML:com.adobe.xmp",
}
KNOWN_CHUNKS = {b"eXIf", b"tIME", b"pHYs", b"cICP", b"iCCP", b"sRGB", b"gAMA", b"cHRM", b"mDCV", b"cLLI"}


@dataclass(frozen=True)
class PngChunk:
    index: int
    kind: bytes
    data: bytes
    crc_expected: int
    crc_actual: int
    after_idat: bool

    @property
    def crc_ok(self) -> bool:
        return self.crc_expected == self.crc_actual


def iter_png_chunks(path: Path) -> list[PngChunk]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")

    chunks: list[PngChunk] = []
    offset = len(PNG_SIGNATURE)
    seen_idat = False
    index = 0
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("truncated PNG chunk header")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            raise ValueError(f"truncated PNG chunk {kind.decode('latin-1', errors='replace')}")
        chunk_data = data[start:end]
        crc_expected = struct.unpack(">I", data[end : end + 4])[0]
        crc_actual = zlib.crc32(kind + chunk_data) & 0xFFFFFFFF
        chunks.append(
            PngChunk(
                index=index,
                kind=kind,
                data=chunk_data,
                crc_expected=crc_expected,
                crc_actual=crc_actual,
                after_idat=seen_idat,
            )
        )
        index += 1
        offset = end + 4
        if kind == b"IDAT":
            seen_idat = True
        if kind == b"IEND":
            break
    return chunks


def describe_text_chunk(chunk: PngChunk) -> tuple[str | None, str]:
    if chunk.kind == b"tEXt":
        keyword, _sep, _text = chunk.data.partition(b"\x00")
        return _decode_keyword(keyword), "Latin-1 tEXt"
    if chunk.kind == b"zTXt":
        keyword, _sep, rest = chunk.data.partition(b"\x00")
        method = rest[:1].hex() if rest else "missing"
        return _decode_keyword(keyword), f"compressed Latin-1 zTXt method={method}"
    if chunk.kind == b"iTXt":
        keyword, _sep, rest = chunk.data.partition(b"\x00")
        compressed = "unknown"
        if len(rest) >= 2:
            compressed = "yes" if rest[0] else "no"
        return _decode_keyword(keyword), f"UTF-8 iTXt compressed={compressed}"
    return None, ""


def inspect_png(path: Path) -> str:
    chunks = iter_png_chunks(path)
    lines = [f"file: {path.name}", "chunks:"]
    metadata_seen: dict[str, str] = {}
    exif_user_comment: tuple[str, str] | None = None

    for chunk in chunks:
        kind = chunk.kind.decode("latin-1", errors="replace")
        position = "after IDAT" if chunk.after_idat else "before IDAT"
        crc = "ok" if chunk.crc_ok else f"bad expected={chunk.crc_expected:08x} actual={chunk.crc_actual:08x}"
        detail = ""
        keyword, text_kind = describe_text_chunk(chunk)
        if keyword is not None:
            detail = f" keyword={keyword!r} text={text_kind}"
            if keyword in KNOWN_METADATA:
                metadata_seen[keyword] = f"{kind} ({text_kind})"
        elif chunk.kind in KNOWN_CHUNKS:
            metadata_seen[kind] = kind
            if chunk.kind == b"eXIf":
                exif_user_comment = _decode_exif_user_comment(path)
        lines.append(f"  {chunk.index:02d} {kind} length={len(chunk.data)} {position} crc={crc}{detail}")

    lines.append("metadata summary:")
    for name in ("parameters", "prompt", "workflow", "civitai", "Software", "XML:com.adobe.xmp"):
        lines.append(f"  {name}: {metadata_seen.get(name, 'absent')}")
    for name in ("eXIf", "tIME", "pHYs", "cICP", "iCCP", "sRGB", "gAMA", "cHRM", "mDCV", "cLLI"):
        lines.append(f"  {name}: {'present' if name in metadata_seen else 'absent'}")
    if exif_user_comment is not None:
        text, encoding = exif_user_comment
        lines.append("exif UserComment:")
        lines.append(f"  encoding: {encoding}")
        lines.append(f"  decodedLength: {len(text)}")
        preview = text[:800].replace("\n", "\\n")
        lines.append(f"  preview: {preview}")
        parsed = parse_user_comment_fields(text)
        for key in ("Steps", "Sampler", "CFG scale", "Seed", "Size", "Created Date"):
            if key in parsed:
                lines.append(f"  {key}: {parsed[key]}")
        for key in ("Civitai resources", "Civitai metadata"):
            value = parsed.get(key)
            if value is None:
                lines.append(f"  {key}: absent")
                continue
            try:
                parsed_value = json.loads(value)
                count = len(parsed_value) if isinstance(parsed_value, list) else len(parsed_value.keys())
                lines.append(f"  {key}: valid JSON ({type(parsed_value).__name__}, {count})")
            except json.JSONDecodeError:
                lines.append(f"  {key}: invalid JSON")
    return "\n".join(lines)


def parse_user_comment_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key in ("Civitai resources", "Civitai metadata"):
        pattern = re.compile(rf"(?:^|, )({re.escape(key)}):\s*(.+?)(?=, Civitai metadata:|$)", re.DOTALL)
        match = pattern.search(text)
        if match:
            fields[key] = match.group(2).strip()
    for key in ("Steps", "Sampler", "CFG scale", "Seed", "Size", "Created Date"):
        match = re.search(rf"(?:^|, |\n)({re.escape(key)}):\s*([^,\n]+)", text)
        if match:
            fields[key] = match.group(2).strip()
    return fields


def _decode_exif_user_comment(path: Path) -> tuple[str, str]:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return "", "Pillow unavailable"

    with Image.open(path) as image:
        exif = image.getexif()
        try:
            exif_ifd = exif.get_ifd(EXIF_IFD_TAG)
        except Exception:
            exif_ifd = {}
        value = exif_ifd.get(USER_COMMENT_TAG)
        if value is None:
            value = exif.get(USER_COMMENT_TAG)
        return decode_user_comment(value)


def _decode_keyword(raw: bytes) -> str:
    return raw.decode("latin-1", errors="replace")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Inspect PNG chunk sequence and metadata chunks")
    parser.add_argument("png", type=Path, help="Path to a PNG file")
    args = parser.parse_args()
    print(inspect_png(args.png))


if __name__ == "__main__":
    main()
