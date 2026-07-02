from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from save_node import nodes
from save_node.civitai.lookup import CivitaiApiResolutionResult
from save_node.comfy.workflow_scan import WorkflowScanResult
from save_node.hashing.resource_identity import ResourceHashingResult
from save_node.metadata.schema import (
    GenerationSettings,
    GeneratorMetadata,
    HashMetadata,
    ModelResourceMetadata,
    PromptMetadata,
    ResolvedResource,
    ValidationIssue,
    ValidationResult,
)


class PixelsFirstTests(unittest.TestCase):
    def test_image_saves_when_hashing_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(tmp, attach_local_hashes=RuntimeError("hash failed"))
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_image_saves_when_identity_cache_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(tmp, load_identity_cache=RuntimeError("cache failed"))
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_image_saves_when_api_lookup_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(
                tmp,
                enable_civitai_lookup=True,
                resolve_resources_with_civitai_api=TimeoutError(),
            )
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_image_saves_when_sidecar_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(
                tmp,
                write_sidecar_json=True,
                write_sidecar_json_file=OSError("sidecar failed"),
            )
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_image_saves_when_manifest_build_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(tmp, build_civitai_manifest=TypeError("manifest failed"))
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_image_saves_when_png_metadata_build_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(tmp, build_pnginfo=RuntimeError("pnginfo failed"))
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_image_saves_when_exif_metadata_build_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(tmp, build_exif_bytes=RuntimeError("exif failed"))
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_image_saves_when_minimal_exif_metadata_build_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(tmp, civitai_exif_minimal=True, build_exif_bytes=RuntimeError("exif failed"))
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_image_saves_when_filename_template_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(tmp, filename_prefix="../bad")
            image_path = _saved_path(tmp, result)

            self.assertTrue(image_path.exists())
            self.assertEqual(image_path.name, "CivitaiMetadata_00001_.png")

    def test_image_save_retries_without_metadata_when_first_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pil_image = FakePilImage(fail_first_metadata_save=True)
            result = _run_save(tmp, pil_image=pil_image)

            self.assertTrue(_saved_path(tmp, result).exists())
            self.assertEqual(pil_image.save_calls, 2)

    def test_unresolved_resource_does_not_block_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(tmp, scan=_scan_result(resources=(_resource(),)))
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_malformed_preferred_primary_air_does_not_block_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(
                tmp,
                scan=_scan_result(resources=(_resource(),)),
                preferred_primary_model_air="not-air",
            )
            self.assertTrue(_saved_path(tmp, result).exists())

    def test_disabled_advanced_manual_json_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                nodes, "apply_manual_resource_identities", side_effect=AssertionError("stale JSON was parsed")
            ) as patched:
                result = _run_save(
                    tmp,
                    scan=_scan_result(resources=(_resource(),)),
                    advanced_manual_identities_enabled=False,
                    manual_resource_identities_json="{bad json",
                )

            self.assertTrue(_saved_path(tmp, result).exists())
            self.assertEqual(patched.call_count, 0)

    def test_enabled_advanced_manual_json_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                nodes, "apply_manual_resource_identities", wraps=nodes.apply_manual_resource_identities
            ) as patched:
                result = _run_save(
                    tmp,
                    scan=_scan_result(resources=(_resource(),)),
                    advanced_manual_identities_enabled=True,
                    manual_resource_identities_json="[]",
                )

            self.assertTrue(_saved_path(tmp, result).exists())
            self.assertEqual(patched.call_count, 1)

    def test_malformed_enabled_advanced_manual_json_does_not_block_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(
                tmp,
                scan=_scan_result(resources=(_resource(),)),
                advanced_manual_identities_enabled=True,
                manual_resource_identities_json="{bad json",
            )

            self.assertTrue(_saved_path(tmp, result).exists())

    def test_preferred_primary_air_still_works_when_advanced_json_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                nodes, "apply_preferred_primary_model_air", wraps=nodes.apply_preferred_primary_model_air
            ) as patched:
                result = _run_save(
                    tmp,
                    scan=_scan_result(resources=(_resource(),)),
                    preferred_primary_model_air="urn:air:sdxl:checkpoint:civitai:10@20",
                    advanced_manual_identities_enabled=False,
                    manual_resource_identities_json="{bad json",
                )

            self.assertTrue(_saved_path(tmp, result).exists())
            self.assertEqual(patched.call_count, 1)

    def test_lifecycle_failure_does_not_block_image_or_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_save(
                tmp,
                write_sidecar_json=True,
                build_resource_lifecycle=RuntimeError("lifecycle failed"),
            )

            image_path = _saved_path(tmp, result)
            self.assertTrue(image_path.exists())
            self.assertTrue(image_path.with_suffix(".json").exists())

    def test_metadata_status_is_partial_when_resources_unresolved(self) -> None:
        status = nodes._metadata_status([], ValidationResult(), (_resource(),))

        self.assertEqual(status, "partial")

    def test_metadata_status_is_minimal_when_png_metadata_fails(self) -> None:
        status = nodes._metadata_status(
            [ValidationIssue(code="png_metadata_failed", message="failed")],
            ValidationResult(),
            (),
        )

        self.assertEqual(status, "minimal")

    def test_save_returns_image_passthrough_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            images = [FakeTensor()]
            result = _run_save(tmp, images=images)

            self.assertIs(result["result"][0], images)
            self.assertEqual(result["result"][0][0].shape, images[0].shape)
            self.assertTrue(_saved_path(tmp, result).exists())


def _run_save(
    tmp: str,
    *,
    images: list["FakeTensor"] | None = None,
    filename_prefix: str = "safe",
    write_sidecar_json: bool = False,
    enable_civitai_lookup: bool = False,
    preferred_primary_model_air: str = "",
    advanced_manual_identities_enabled: bool | None = None,
    manual_resource_identities_json: str = "[]",
    civitai_exif_minimal: bool = False,
    pil_image: "FakePilImage | None" = None,
    scan: WorkflowScanResult | None = None,
    attach_local_hashes: object | None = None,
    load_identity_cache: object | None = None,
    resolve_resources_with_civitai_api: object | None = None,
    build_civitai_manifest: object | None = None,
    build_exif_bytes: object | None = None,
    build_pnginfo: object | None = None,
    build_resource_lifecycle: object | None = None,
    write_sidecar_json_file: object | None = None,
) -> dict[str, object]:
    output_dir = Path(tmp) / "output"
    output_dir.mkdir()
    fake_image = pil_image or FakePilImage()
    scan = scan or _scan_result()
    hash_result = ResourceHashingResult(
        resources=scan.resources,
        unresolved_resources=scan.unresolved_resources,
        hashes=HashMetadata(),
        generation=scan.generation,
        warnings=(),
    )
    lookup_result = CivitaiApiResolutionResult(
        resources=scan.resources,
        unresolved_resources=scan.unresolved_resources,
    )

    patches = [
        mock.patch.object(nodes, "_get_comfy_output_directory", return_value=output_dir),
        mock.patch.object(
            nodes,
            "_get_save_image_path",
            side_effect=lambda prefix, out, _w, _h: (str(out), prefix.replace("/", "_"), 1, "", prefix),
        ),
        mock.patch.object(nodes, "_tensor_to_pil_image", return_value=fake_image),
        mock.patch.object(nodes, "scan_workflow_graph", return_value=scan),
        _patch_or_raise(nodes, "attach_local_hashes", attach_local_hashes, hash_result),
        _patch_or_raise(nodes, "load_identity_cache", load_identity_cache, _empty_identity_load()),
        mock.patch.object(nodes, "combine_identity_caches", return_value=_empty_identity_load().cache),
        mock.patch.object(
            nodes,
            "apply_identity_cache",
            return_value=_empty_identity_result(scan.resources, scan.unresolved_resources),
        ),
        _patch_or_raise(nodes, "resolve_resources_with_civitai_api", resolve_resources_with_civitai_api, lookup_result),
        _patch_or_raise(nodes, "build_civitai_manifest", build_civitai_manifest, None),
        _patch_or_raise(nodes, "build_exif_bytes", build_exif_bytes, b"exif"),
        _patch_or_raise(nodes, "build_pnginfo", build_pnginfo, object()),
    ]
    if build_resource_lifecycle is not None:
        patches.append(_patch_or_raise(nodes, "build_resource_lifecycle", build_resource_lifecycle, None))
    if write_sidecar_json_file is not None:
        patches.append(_patch_or_raise(nodes, "write_sidecar_json_file", write_sidecar_json_file, None))

    entered = [patch.__enter__() for patch in patches]
    try:
        image_batch = images or [FakeTensor()]
        return nodes.SaveImageWithCivitaiMetadata().save_images(
            image_batch,
            filename_prefix=filename_prefix,
            write_sidecar_json=write_sidecar_json,
            include_workflow=True,
            include_civitai_manifest=True,
            enable_civitai_lookup=enable_civitai_lookup,
            preferred_primary_model_air=preferred_primary_model_air,
            advanced_manual_identities_enabled=advanced_manual_identities_enabled,
            manual_resource_identities_json=manual_resource_identities_json,
            civitai_exif_minimal=civitai_exif_minimal,
            prompt={"1": {"class_type": "KSampler", "inputs": {}}},
            extra_pnginfo={"workflow": {"nodes": []}},
        )
    finally:
        for patch in reversed(patches):
            patch.__exit__(None, None, None)
        entered.clear()


def _patch_or_raise(module: object, name: str, value: object | None, default: object):
    if isinstance(value, BaseException):
        return mock.patch.object(module, name, side_effect=value)
    if value is not None:
        return mock.patch.object(module, name, return_value=value)
    return mock.patch.object(module, name, return_value=default)


def _saved_path(tmp: str, result: dict[str, object]) -> Path:
    ui = result["ui"]
    assert isinstance(ui, dict)
    images = ui["images"]
    image = images[0]
    return Path(tmp) / "output" / image["filename"]


def _scan_result(*, resources: tuple[ResolvedResource, ...] = ()) -> WorkflowScanResult:
    return WorkflowScanResult(
        prompt=PromptMetadata(positive="test prompt"),
        generation=GenerationSettings(width=1, height=1, steps=1),
        resources=resources,
        unresolved_resources=(),
        warnings=(),
        generator=GeneratorMetadata(version="test"),
    )


def _resource() -> ResolvedResource:
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role="checkpoint",
            type="checkpoint",
            name="base.safetensors",
            filename="base.safetensors",
            selected_value="base.safetensors",
            local_path_basename="base.safetensors",
        ),
        resolved=False,
        unresolved_reason="missing",
    )


def _empty_identity_load():
    from save_node.civitai.identity_cache import IdentityCacheLoadResult

    return IdentityCacheLoadResult(cache=_empty_identity_cache())


def _empty_identity_cache():
    from save_node.civitai.identity_cache import IdentityCache

    return IdentityCache.empty()


def _empty_identity_result(resources, unresolved_resources):
    from save_node.civitai.identity_resolution import IdentityResolutionResult
    from save_node.metadata.schema import IdentityCacheMetadata

    return IdentityResolutionResult(
        resources=resources,
        unresolved_resources=unresolved_resources,
        identity_cache=IdentityCacheMetadata(),
        warnings=(),
        errors=(),
    )


class FakeTensor:
    shape = (1, 1, 3)


class FakePilImage:
    def __init__(self, *, fail_first_metadata_save: bool = False) -> None:
        self.fail_first_metadata_save = fail_first_metadata_save
        self.save_calls = 0

    def save(self, path: Path, **kwargs: Any) -> None:
        self.save_calls += 1
        if self.fail_first_metadata_save and "pnginfo" in kwargs and self.save_calls == 1:
            raise OSError("metadata write failed")
        Path(path).write_bytes(b"fake image")


if __name__ == "__main__":
    unittest.main()
