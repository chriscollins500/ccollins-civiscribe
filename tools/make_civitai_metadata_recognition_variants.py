"""Create controlled PNG metadata variants for manual Civitai recognition tests."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from save_node.io.png_writer import SOFTWARE_TEXT
from save_node.metadata.exif_user_comment import build_exif_bytes, decode_user_comment, encode_user_comment
from save_node.metadata.serialize import to_json_text
from save_node.security.redaction import sanitize_metadata_text


VARIANT_ORDER = (
    "A_full_baseline",
    "B_a1111_hashes_only",
    "C_workflow_and_manifest_only",
    "D_workflow_only",
    "E_civitai_manifest_only",
    "F_no_resource_metadata",
    "G_a1111_model_hash_only",
    "H_explicit_civitai_resources_only",
    "U_exif_usercomment_full_only",
    "V_parameters_plus_exif",
    "W_exif_resources_only",
    "X_exif_civitai_metadata_only",
    "Y_exif_minimal_no_resources",
)
RESOURCE_FIELD_KEYS = {"model", "model hash", "vae", "vae hash", "hashes", "civitai resources"}
HASH_FIELD_KEYS = {"model hash", "vae hash", "hashes"}
MODEL_HASH_FIELD_KEYS = {"model hash", "hashes"}
CIVITAI_RESOURCE_FIELD_KEYS = {"civitai resources"}
SETTINGS_HINT_KEYS = {
    "steps",
    "sampler",
    "schedule type",
    "scheduler",
    "cfg scale",
    "guidance",
    "seed",
    "size",
    "model",
    "model hash",
    "vae",
    "vae hash",
    "hashes",
    "civitai resources",
}


@dataclass(frozen=True)
class VariantRecord:
    variant: str
    filename: str
    metadata_included: tuple[str, ...]
    purpose: str
    notes: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "filename": self.filename,
            "metadataIncluded": list(self.metadata_included),
            "purpose": self.purpose,
            "notes": list(self.notes),
            "manualUploadResult": {
                "promptDetected": None,
                "negativePromptDetected": None,
                "baseModelDisplayed": None,
                "vaeDisplayed": None,
                "lorasDisplayed": None,
                "resourcesPanelEntries": "",
                "otherMetadataPanelEntries": "",
                "workflowNodesButtonPresent": None,
                "apiImageIdOrPostId": "",
                "apiMetaResources": "",
                "apiMetaHashes": "",
                "notes": "",
            },
        }


def make_variants(source_png: Path, output_folder: Path | None = None) -> list[VariantRecord]:
    source = source_png.resolve(strict=True)
    if source.suffix.lower() != ".png":
        raise ValueError("source file must be a PNG")

    destination = output_folder or source.parent / f"{source.stem}_civitai_recognition_variants"
    destination.mkdir(parents=True, exist_ok=True)

    metadata = _read_source_text(source)
    parameters = metadata.get("parameters", "")
    stripped_parameters = strip_resource_metadata_from_parameters(parameters)
    hashes_only = keep_selected_resource_fields(parameters, HASH_FIELD_KEYS, hashes_mode="all")
    model_hash_only = keep_selected_resource_fields(parameters, MODEL_HASH_FIELD_KEYS, hashes_mode="model")
    civitai_resources_only = keep_selected_resource_fields(
        parameters,
        CIVITAI_RESOURCE_FIELD_KEYS,
        hashes_mode="none",
    )
    software = metadata.get("Software") or SOFTWARE_TEXT
    exif_text = _read_source_exif_user_comment(source)
    exif_bytes = _source_or_fallback_exif_bytes(exif_text, parameters)
    exif_resources_only = _exif_field_only(exif_text, parameters, "Civitai resources")
    exif_metadata_only = _exif_field_only(exif_text, parameters, "Civitai metadata")
    exif_minimal_no_resources = strip_resource_metadata_from_parameters(exif_text or parameters)

    records: list[VariantRecord] = []

    baseline_target = destination / _variant_filename(source, "A_full_baseline")
    shutil.copyfile(source, baseline_target)
    records.append(
        VariantRecord(
            variant="A_full_baseline",
            filename=baseline_target.name,
            metadata_included=tuple(_source_metadata_summary(metadata)),
            purpose="Baseline upload: source PNG bytes and metadata copied exactly.",
        )
    )

    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "B_a1111_hashes_only"),
            parameters=hashes_only,
            software=software,
            purpose="Tests whether A1111 Model hash, VAE hash, and Hashes JSON alone drive resource recognition.",
            notes=("Civitai resources field removed for isolation.",),
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "C_workflow_and_manifest_only"),
            parameters=stripped_parameters,
            workflow=metadata.get("workflow"),
            civitai=metadata.get("civitai"),
            software=software,
            purpose="Tests ComfyUI workflow metadata plus the structured civitai manifest without A1111 resource hashes.",
            notes=("A1111 resource-bearing fields stripped.",),
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "D_workflow_only"),
            parameters=stripped_parameters,
            workflow=metadata.get("workflow"),
            software=software,
            purpose="Tests Civitai's ComfyUI workflow parser without the structured civitai manifest.",
            notes=("A1111 resource-bearing fields stripped.",),
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "E_civitai_manifest_only"),
            parameters=stripped_parameters,
            civitai=metadata.get("civitai"),
            software=software,
            purpose="Tests whether Civitai reads the custom structured civitai iTXt manifest.",
            notes=("A1111 resource-bearing fields stripped.",),
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "F_no_resource_metadata"),
            software=software,
            purpose="Negative control with no resource-bearing metadata: only pixels and Software remain.",
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "G_a1111_model_hash_only"),
            parameters=model_hash_only,
            software=software,
            purpose="Tests base model recognition from A1111 Model hash and Hashes model entries only.",
            notes=("VAE hash and VAE Hashes entries removed.",),
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "H_explicit_civitai_resources_only"),
            parameters=civitai_resources_only,
            software=software,
            purpose="Tests explicit A1111 Civitai resources parsing without Hashes, Model hash, or VAE hash.",
            notes=("No AIR/modelVersionId is invented if the source had no Civitai resources field.",),
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "U_exif_usercomment_full_only"),
            exif_bytes=exif_bytes,
            purpose="Tests Civitai-style EXIF UserComment recognition without PNG text/iTXt metadata.",
            notes=("No PNG parameters, prompt, workflow, or civitai chunks are written.",),
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "V_parameters_plus_exif"),
            parameters=parameters,
            exif_bytes=exif_bytes,
            purpose="Tests the combined A1111 parameters plus Civitai-style EXIF UserComment path.",
            notes=("Workflow and structured civitai iTXt chunks removed for isolation.",),
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "W_exif_resources_only"),
            exif_text=exif_resources_only,
            purpose="Tests whether EXIF UserComment Civitai resources alone drive resource recognition.",
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "X_exif_civitai_metadata_only"),
            exif_text=exif_metadata_only,
            purpose="Tests whether EXIF UserComment Civitai metadata JSON alone drives resource recognition.",
        )
    )
    records.append(
        _write_variant(
            source=source,
            target=destination / _variant_filename(source, "Y_exif_minimal_no_resources"),
            exif_text=exif_minimal_no_resources,
            purpose="Negative control for EXIF metadata without explicit resource-bearing fields.",
        )
    )

    _write_manifest(destination, source.name, records)
    return records


def strip_resource_metadata_from_parameters(parameters: str) -> str:
    return _rewrite_parameters(parameters, keep_resource_keys=set(), hashes_mode="none", keep_non_resource=True)


def keep_selected_resource_fields(
    parameters: str,
    keep_resource_keys: set[str],
    *,
    hashes_mode: str,
) -> str:
    return _rewrite_parameters(
        parameters,
        keep_resource_keys=keep_resource_keys,
        hashes_mode=hashes_mode,
        keep_non_resource=False,
    )


def _rewrite_parameters(
    parameters: str,
    *,
    keep_resource_keys: set[str],
    hashes_mode: str,
    keep_non_resource: bool,
) -> str:
    prompt_lines, fields = _split_parameters(parameters)
    output_fields: list[tuple[str, str]] = []
    for key, value in fields:
        normalized = _normalize_key(key)
        if normalized == "hashes":
            filtered_hashes = _filter_hashes(value, hashes_mode)
            if filtered_hashes:
                output_fields.append((key, to_json_text(filtered_hashes)))
            continue
        if normalized in RESOURCE_FIELD_KEYS:
            if normalized in keep_resource_keys:
                output_fields.append((key, value))
            continue
        if keep_non_resource:
            output_fields.append((key, value))

    safe_prompt_lines = [sanitize_metadata_text(line) for line in prompt_lines if line.strip()]
    if not safe_prompt_lines:
        safe_prompt_lines = ["metadata recognition harness"]
    if not any(line.startswith("Negative prompt:") for line in safe_prompt_lines):
        safe_prompt_lines.append("Negative prompt:")
    if output_fields:
        safe_prompt_lines.append(
            ", ".join(f"{sanitize_metadata_text(key)}: {sanitize_metadata_text(value)}" for key, value in output_fields)
        )
    return "\n".join(safe_prompt_lines)


def _split_parameters(parameters: str) -> tuple[list[str], list[tuple[str, str]]]:
    lines = sanitize_metadata_text(parameters or "").splitlines()
    index = _settings_line_index(lines)
    if index is None:
        return lines, []
    return lines[:index], _parse_settings_line(lines[index])


def _settings_line_index(lines: list[str]) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        fields = _parse_settings_line(lines[index])
        if any(_normalize_key(key) in SETTINGS_HINT_KEYS for key, _value in fields):
            return index
    return None


def _parse_settings_line(line: str) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for part in _split_top_level_commas(line):
        key, separator, value = part.partition(":")
        if not separator:
            continue
        fields.append((key.strip(), value.strip()))
    return fields


def _split_top_level_commas(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    for character in value:
        if quote is not None:
            current.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
            current.append(character)
            continue
        if character in "[{(":
            depth += 1
            current.append(character)
            continue
        if character in "]})" and depth > 0:
            depth -= 1
            current.append(character)
            continue
        if character == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(character)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _filter_hashes(value: str, mode: str) -> dict[str, Any]:
    if mode == "none":
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    if mode == "all":
        return parsed
    if mode == "model":
        return {str(key): item for key, item in parsed.items() if _normalize_hash_key(str(key)) == "model"}
    return {}


def _normalize_hash_key(value: str) -> str:
    return value.split(":", 1)[0].strip().lower()


def _normalize_key(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _read_source_text(source: Path) -> dict[str, str]:
    Image, _PngInfo = _pillow()
    with Image.open(source) as image:
        image.load()
        return {str(key): sanitize_metadata_text(str(value)) for key, value in image.text.items()}


def _read_source_exif_user_comment(source: Path) -> str:
    Image, _PngInfo = _pillow()
    try:
        from save_node.metadata.exif_user_comment import EXIF_IFD_TAG, USER_COMMENT_TAG

        with Image.open(source) as image:
            exif = image.getexif()
            try:
                exif_ifd = exif.get_ifd(EXIF_IFD_TAG)
            except Exception:
                exif_ifd = {}
            text, _encoding = decode_user_comment(exif_ifd.get(USER_COMMENT_TAG) or exif.get(USER_COMMENT_TAG))
            return sanitize_metadata_text(text)
    except Exception:
        return ""


def _source_or_fallback_exif_bytes(exif_text: str, parameters: str) -> bytes:
    if exif_text:
        return _exif_bytes_from_text(exif_text)
    try:
        from save_node.metadata.schema import GenerationSettings, PromptMetadata

        prompt = parameters.splitlines()[0] if parameters else "metadata recognition harness"
        return build_exif_bytes(
            prompt=PromptMetadata(positive=prompt),
            generation=GenerationSettings(),
            resources=(),
        )
    except Exception:
        return _exif_bytes_from_text(parameters or "metadata recognition harness")


def _exif_field_only(exif_text: str, parameters: str, field_name: str) -> str:
    source = exif_text or parameters
    fields = _parse_settings_line(source.replace("\n", ", "))
    for key, value in fields:
        if _normalize_key(key) == _normalize_key(field_name):
            return f"{field_name}: {sanitize_metadata_text(value)}"
    return f"{field_name}: []" if field_name == "Civitai resources" else f"{field_name}: {{}}"


def _exif_bytes_from_text(text: str) -> bytes:
    Image, _PngInfo = _pillow()
    exif = Image.Exif()
    from save_node.metadata.exif_user_comment import EXIF_IFD_TAG, USER_COMMENT_TAG

    exif[EXIF_IFD_TAG] = {USER_COMMENT_TAG: encode_user_comment(text)}
    return exif.tobytes()


def _write_variant(
    *,
    source: Path,
    target: Path,
    purpose: str,
    software: str | None = None,
    parameters: str | None = None,
    workflow: str | None = None,
    civitai: str | None = None,
    notes: tuple[str, ...] = (),
    exif_bytes: bytes | None = None,
    exif_text: str | None = None,
) -> VariantRecord:
    Image, PngInfo = _pillow()
    pnginfo = PngInfo()
    included: list[str] = []
    if parameters is not None and parameters != "":
        pnginfo.add_text("parameters", _latin1_text(parameters))
        included.append("parameters:tEXt")
    if software is not None:
        pnginfo.add_text("Software", _latin1_text(software or SOFTWARE_TEXT))
        included.append("Software:tEXt")
    if workflow is not None:
        pnginfo.add_itxt("workflow", sanitize_metadata_text(workflow))
        included.append("workflow:iTXt")
    if civitai is not None:
        pnginfo.add_itxt("civitai", sanitize_metadata_text(civitai))
        included.append("civitai:iTXt")
    if exif_text is not None:
        exif_bytes = _exif_bytes_from_text(exif_text)
    if exif_bytes:
        included.append("eXIf:UserComment")

    with Image.open(source) as image:
        image.load()
        output = image.copy()
        output.info = {}
        output.encoderinfo = {}
        save_kwargs: dict[str, Any] = {"format": "PNG", "compress_level": 4}
        if included and any(item.endswith(":tEXt") or item.endswith(":iTXt") for item in included):
            save_kwargs["pnginfo"] = pnginfo
        if exif_bytes:
            save_kwargs["exif"] = exif_bytes
        output.save(target, **save_kwargs)

    return VariantRecord(
        variant=_variant_name_from_filename(target),
        filename=target.name,
        metadata_included=tuple(included),
        purpose=purpose,
        notes=notes,
    )


def _write_manifest(destination: Path, source_name: str, records: Iterable[VariantRecord]) -> None:
    record_list = list(records)
    payload = {
        "format": "comfyui-civitai-save-node.civitai-recognition-variants",
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sourcePng": Path(source_name).name,
        "variants": [record.to_json() for record in record_list],
    }
    (destination / "recognition_variants_manifest.json").write_text(
        to_json_text(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    with (destination / "recognition_variants_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "variant",
                "filename",
                "metadataIncluded",
                "purpose",
                "promptDetected",
                "negativePromptDetected",
                "baseModelDisplayed",
                "vaeDisplayed",
                "lorasDisplayed",
                "resourcesPanelEntries",
                "otherMetadataPanelEntries",
                "workflowNodesButtonPresent",
                "apiImageIdOrPostId",
                "apiMetaResources",
                "apiMetaHashes",
                "notes",
            ),
        )
        writer.writeheader()
        for record in record_list:
            writer.writerow(
                {
                    "variant": record.variant,
                    "filename": record.filename,
                    "metadataIncluded": "; ".join(record.metadata_included),
                    "purpose": record.purpose,
                    "promptDetected": "",
                    "negativePromptDetected": "",
                    "baseModelDisplayed": "",
                    "vaeDisplayed": "",
                    "lorasDisplayed": "",
                    "resourcesPanelEntries": "",
                    "otherMetadataPanelEntries": "",
                    "workflowNodesButtonPresent": "",
                    "apiImageIdOrPostId": "",
                    "apiMetaResources": "",
                    "apiMetaHashes": "",
                    "notes": " ".join(record.notes),
                }
            )


def _source_metadata_summary(metadata: dict[str, str]) -> list[str]:
    output: list[str] = []
    for key in ("parameters", "Software", "prompt", "workflow", "civitai"):
        if key not in metadata:
            continue
        kind = "tEXt" if key in {"parameters", "Software"} else "iTXt"
        output.append(f"{key}:{kind}")
    return output


def _variant_filename(source: Path, variant: str) -> str:
    return f"{source.stem}__{variant}.png"


def _variant_name_from_filename(path: Path) -> str:
    stem = path.stem
    if "__" in stem:
        return stem.rsplit("__", 1)[1]
    return stem


def _latin1_text(value: str) -> str:
    return sanitize_metadata_text(value).encode("latin-1", errors="replace").decode("latin-1")


def _pillow() -> tuple[Any, Any]:
    try:
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
    except ModuleNotFoundError as exc:
        raise RuntimeError("Pillow is required to create PNG metadata recognition variants") from exc
    return Image, PngInfo


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create controlled PNG copies for manual Civitai metadata recognition testing"
    )
    parser.add_argument("source_png", type=Path, help="PNG generated by Save Image with Civitai Metadata")
    parser.add_argument(
        "--output-folder",
        type=Path,
        default=None,
        help="Folder for generated variants. Defaults to SOURCE_STEM_civitai_recognition_variants next to the source PNG.",
    )
    args = parser.parse_args()

    records = make_variants(args.source_png, args.output_folder)
    output_folder = (
        args.output_folder or args.source_png.parent / f"{args.source_png.stem}_civitai_recognition_variants"
    )
    print(f"wrote {len(records)} variants to {output_folder.name}")
    print("manifest: recognition_variants_manifest.json")
    print("worksheet: recognition_variants_manifest.csv")


if __name__ == "__main__":
    main()
