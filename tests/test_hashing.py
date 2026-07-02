from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import unittest
import zlib
from unittest import mock
from pathlib import Path, PurePosixPath, PureWindowsPath

from save_node.civitai.manifest import build_civitai_manifest
from save_node.hashing.autov2 import AUTO_V1_OFFSET, AUTO_V1_SIZE, compute_autov1_from_chunk, compute_autov2_from_sha256
from save_node.hashing.hashes import HashCache, compute_file_hashes
from save_node.hashing.resolver import ModelRootResolver
from save_node.hashing.resource_identity import (
    HASHED_BUT_NO_CIVITAI_IDENTITY,
    attach_local_hashes,
)
from save_node.io.sidecar import build_sidecar_payload
from save_node.metadata.a1111 import build_a1111_parameters
from save_node.metadata.schema import (
    GenerationSettings,
    MetadataOptions,
    ModelResourceMetadata,
    PromptMetadata,
    ResolvedResource,
)
from save_node.metadata.serialize import to_json_text
from save_node.metadata.validate import validate_metadata


def write_model(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def write_safetensors_header(path: Path, metadata: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = json.dumps({"__metadata__": metadata}, separators=(",", ":")).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header)) + header)
    return path


def basename(value: str) -> str:
    windows_name = PureWindowsPath(value).name
    posix_name = PurePosixPath(windows_name).name
    return posix_name or windows_name


def resource(
    role: str,
    selected: str,
    *,
    node_id: str = "1",
    resource_type: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ResolvedResource:
    name = basename(selected)
    return ResolvedResource(
        ModelResourceMetadata(
            role=role,
            type=resource_type or role,
            node_id=node_id,
            node_class_type="TestLoader",
            name=name,
            selected_value=selected.replace("\\", "/") if not Path(selected).is_absolute() else name,
            source_value=selected,
            filename=name,
            local_path_basename=name,
            metadata=metadata or {},
        ),
        resolved=False,
        unresolved_reason="phase_3_unresolved",
    )


class HashingTests(unittest.TestCase):
    def test_sha256_hashes_small_model_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = write_model(Path(tmp) / "model.safetensors", b"tiny model")

            result = compute_file_hashes(model)

            self.assertEqual(result.hashes.sha256, hashlib.sha256(b"tiny model").hexdigest())
            self.assertEqual(result.status, "hashed")

    def test_autov2_hash_uses_deterministic_sha256_prefix(self) -> None:
        sha256 = hashlib.sha256(b"auto v2 fixture").hexdigest()

        self.assertEqual(compute_autov2_from_sha256(sha256), sha256[:10])

    def test_autov1_hash_uses_legacy_offset_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chunk = b"x" * AUTO_V1_SIZE
            model = Path(tmp) / "model.safetensors"
            model.write_bytes(b"\0" * AUTO_V1_OFFSET + chunk)

            result = compute_file_hashes(model, hashing_mode="full")

            self.assertEqual(result.hashes.auto_v1, compute_autov1_from_chunk(chunk))

    def test_full_mode_computes_crc32(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = b"crc fixture"
            model = write_model(Path(tmp) / "model.safetensors", data)

            result = compute_file_hashes(model, hashing_mode="full")

            self.assertEqual(result.hashes.crc32, f"{zlib.crc32(data) & 0xFFFFFFFF:08X}")

    def test_full_mode_computes_blake3_when_dependency_is_installed(self) -> None:
        try:
            import blake3 as blake3_module
        except ImportError:
            self.skipTest("blake3 package is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            data = b"blake3 fixture"
            model = write_model(Path(tmp) / "model.safetensors", data)

            result = compute_file_hashes(model, hashing_mode="full")

            self.assertEqual(result.hashes.blake3, blake3_module.blake3(data).hexdigest())

    def test_autov3_reads_safetensors_metadata_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_hash = "abcdef1234567890"
            model = write_safetensors_header(Path(tmp) / "model.safetensors", {"sshs_model_hash": model_hash})

            result = compute_file_hashes(model, hashing_mode="cached_or_fast")

            self.assertEqual(result.hashes.auto_v3, model_hash[:12])

    def test_autov3_absent_when_safetensors_metadata_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = write_safetensors_header(Path(tmp) / "model.safetensors", {"title": "no hash"})

            result = compute_file_hashes(model, hashing_mode="cached_or_fast")

            self.assertIsNone(result.hashes.auto_v3)

    def test_resolves_checkpoint_inside_approved_model_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            model = write_model(root / "sub" / "base.safetensors", b"model")
            resolver = ModelRootResolver({"checkpoints": [root]})

            resolved = resolver.resolve(resource("checkpoint", "sub/base.safetensors").resource)

            self.assertEqual(resolved.path, model.resolve())
            self.assertEqual(resolved.status, "resolved")

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            root.mkdir()
            resolver = ModelRootResolver({"checkpoints": [root]})

            resolved = resolver.resolve(resource("checkpoint", "../outside.safetensors").resource)

            self.assertIsNone(resolved.path)
            self.assertEqual(resolved.warnings[0].code, "resource_path_traversal_rejected")

    def test_rejects_absolute_path_outside_approved_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            outside = write_model(Path(tmp) / "outside.safetensors", b"outside")
            root.mkdir()
            resolver = ModelRootResolver({"checkpoints": [root]})

            resolved = resolver.resolve(resource("checkpoint", str(outside)).resource)

            self.assertIsNone(resolved.path)
            self.assertEqual(resolved.warnings[0].code, "resource_absolute_path_outside_roots")

    def test_rejects_symlink_escape_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            root.mkdir()
            outside = write_model(Path(tmp) / "outside.safetensors", b"outside")
            link = root / "linked.safetensors"
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is not available on this platform")

            resolver = ModelRootResolver({"checkpoints": [root]})
            resolved = resolver.resolve(resource("checkpoint", "linked.safetensors").resource)

            self.assertIsNone(resolved.path)
            self.assertEqual(resolved.warnings[0].code, "resource_path_outside_model_roots")

    def test_missing_file_warns_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = ModelRootResolver({"checkpoints": [Path(tmp) / "checkpoints"]})
            result = attach_local_hashes(
                resources=(resource("checkpoint", "missing.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
            )

            self.assertIn("resource_file_missing", {warning.code for warning in result.warnings})
            self.assertEqual(result.resources[0].resource.hash_status, "missing")

    def test_unreadable_file_warns_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            (root / "notfile.safetensors").mkdir(parents=True)
            resolver = ModelRootResolver({"checkpoints": [root]})
            result = attach_local_hashes(
                resources=(resource("checkpoint", "notfile.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
            )

            self.assertIn("resource_file_unreadable", {warning.code for warning in result.warnings})
            self.assertEqual(result.resources[0].resource.hash_status, "unreadable")

    def test_resource_receives_sha256_and_autov2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            write_model(root / "base.safetensors", b"hash me")
            resolver = ModelRootResolver({"checkpoints": [root]})

            result = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(model="base.safetensors"),
                resolver=resolver,
            )

            hashes = result.resources[0].resource.hashes
            self.assertEqual(hashes.sha256, hashlib.sha256(b"hash me").hexdigest())
            self.assertEqual(hashes.auto_v2, hashes.sha256[:10])
            self.assertEqual(result.generation.model_hash, hashes.auto_v2)

    def test_a1111_hashes_include_model_and_lora_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_root = Path(tmp) / "checkpoints"
            lora_root = Path(tmp) / "loras"
            write_model(checkpoint_root / "base.safetensors", b"base")
            write_model(lora_root / "detail.safetensors", b"lora")
            resolver = ModelRootResolver({"checkpoints": [checkpoint_root], "loras": [lora_root]})
            result = attach_local_hashes(
                resources=(
                    resource("checkpoint", "base.safetensors", node_id="1"),
                    resource("lora", "detail.safetensors", node_id="2"),
                ),
                generation=GenerationSettings(model="base.safetensors"),
                resolver=resolver,
            )

            parameters = build_a1111_parameters(
                prompt=PromptMetadata(positive="test"),
                generation=result.generation,
                resources=result.resources,
                hashes=result.hashes,
            )

            self.assertIn("Model hash:", parameters)
            self.assertIn("Hashes:", parameters)
            self.assertIn("LORA:detail.safetensors", parameters)
            self.assertIn(result.resources[0].resource.hashes.auto_v2 or "", parameters)

    def test_manifest_hashes_match_a1111_hash_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})
            result = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(model="base.safetensors"),
                resolver=resolver,
            )
            validation = validate_metadata(
                filename_prefix="ok",
                prompt_metadata=PromptMetadata(positive="test"),
                generation=result.generation,
                resources=result.resources,
                unresolved_resources=result.unresolved_resources,
                prompt={},
                extra_pnginfo={},
                include_workflow=False,
                include_civitai_manifest=True,
                additional_warnings=result.warnings,
            )
            manifest = build_civitai_manifest(
                prompt=PromptMetadata(positive="test"),
                generation=result.generation,
                resources=result.resources,
                unresolved_resources=result.unresolved_resources,
                hashes=result.hashes,
                validation=validation,
                include_workflow=False,
            )
            parameters = build_a1111_parameters(
                prompt=PromptMetadata(positive="test"),
                generation=result.generation,
                resources=result.resources,
                hashes=result.hashes,
            )
            manifest_json = json.loads(to_json_text(manifest))

            self.assertEqual(manifest_json["hashes"]["Model"], result.hashes.additional["Model"])
            self.assertIn(result.hashes.additional["Model"], parameters)
            self.assertEqual(
                manifest_json["resources"][0]["hashes"]["AutoV2"],
                result.resources[0].resource.hashes.auto_v2,
            )

    def test_hashed_without_civitai_identity_remains_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})
            result = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
            )
            validation = validate_metadata(
                filename_prefix="ok",
                prompt_metadata=PromptMetadata(positive="test"),
                generation=result.generation,
                resources=result.resources,
                unresolved_resources=result.unresolved_resources,
                prompt={},
                extra_pnginfo={},
                include_workflow=False,
                include_civitai_manifest=True,
                additional_warnings=result.warnings,
            )

            self.assertFalse(result.resources[0].resolved)
            self.assertEqual(result.unresolved_resources[0].reason, HASHED_BUT_NO_CIVITAI_IDENTITY)
            self.assertIn(
                "resource_hashed_but_no_civitai_identity",
                {warning.code for warning in validation.warnings},
            )

    def test_hash_cache_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})
            cache = HashCache()

            first = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=cache,
            )
            second = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=cache,
            )

            self.assertEqual(first.resources[0].resource.hashes, second.resources[0].resource.hashes)
            self.assertEqual(cache.hits, 1)
            self.assertEqual(second.resources[0].resource.hash_source, "local_file_cache")

    def test_hash_cache_invalidates_on_size_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            model = write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})
            cache = HashCache()

            first = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=cache,
            )
            model.write_bytes(b"base changed")
            second = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=cache,
            )

            self.assertNotEqual(
                first.resources[0].resource.hashes.sha256,
                second.resources[0].resource.hashes.sha256,
            )
            self.assertEqual(cache.hits, 0)

    def test_persistent_hash_cache_hits_after_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            cache_path = Path(tmp) / "cache" / "hashes.json"
            write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})

            first_cache = HashCache(persistent_path=cache_path)
            first = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=first_cache,
            )
            second_cache = HashCache(persistent_path=cache_path)
            second = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=second_cache,
            )

            self.assertEqual(first.resources[0].resource.hashes, second.resources[0].resource.hashes)
            self.assertEqual(second_cache.hits, 1)
            self.assertEqual(second.resources[0].resource.hash_source, "local_file_cache")

    def test_persistent_hash_cache_invalidates_on_modified_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            cache_path = Path(tmp) / "cache" / "hashes.json"
            model = write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})

            cache = HashCache(persistent_path=cache_path)
            first = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=cache,
            )
            model.write_bytes(b"base changed")
            second = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=cache,
            )

            self.assertNotEqual(
                first.resources[0].resource.hashes.sha256,
                second.resources[0].resource.hashes.sha256,
            )
            self.assertGreaterEqual(cache.misses, 2)

    def test_persistent_hash_cache_recovers_from_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            cache_path = Path(tmp) / "cache" / "hashes.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text("{not json", encoding="utf-8")
            write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})
            cache = HashCache(persistent_path=cache_path)

            result = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=cache,
            )

            self.assertEqual(result.resources[0].resource.hash_status, "hashed")
            self.assertIn("hash_cache_corrupt", {warning.code for warning in result.warnings})

    def test_persistent_hash_cache_contains_no_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            cache_path = Path(tmp) / "cache" / "hashes.json"
            write_model(root / "nested" / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})

            attach_local_hashes(
                resources=(resource("checkpoint", "nested/base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=HashCache(persistent_path=cache_path),
            )
            text = cache_path.read_text(encoding="utf-8")

            self.assertNotIn(str(tmp), text)
            self.assertNotIn(str(root), text)
            self.assertIn("nested/base.safetensors", text)

    def test_hashing_mode_cached_only_skips_uncached_file_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})

            with mock.patch("save_node.hashing.hashes._sha256", side_effect=AssertionError("hash read happened")):
                result = attach_local_hashes(
                    resources=(resource("checkpoint", "base.safetensors"),),
                    generation=GenerationSettings(model="base.safetensors"),
                    resolver=resolver,
                    cache=HashCache(),
                    hashing_mode="cached_only",
                )

            self.assertTrue(result.resources[0].resource.hashes.is_empty)
            self.assertEqual(result.resources[0].resource.hash_status, "hash_skipped_cached_only")
            self.assertIn("resource_hash_skipped_cached_only", {warning.code for warning in result.warnings})

    def test_hashing_mode_cached_or_fast_does_not_full_hash_slow_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})

            with (
                mock.patch("save_node.hashing.hashes.DEFAULT_FAST_HASH_BYTES", 1),
                mock.patch("save_node.hashing.hashes._sha256", side_effect=AssertionError("full hash happened")),
            ):
                result = attach_local_hashes(
                    resources=(resource("checkpoint", "base.safetensors"),),
                    generation=GenerationSettings(model="base.safetensors"),
                    resolver=resolver,
                    cache=HashCache(),
                    hashing_mode="cached_or_fast",
                )

            self.assertEqual(result.resources[0].resource.hash_status, "hashed_fast_partial")
            self.assertIsNone(result.resources[0].resource.hashes.sha256)
            self.assertIsNotNone(result.resources[0].resource.hashes.auto_v1)

    def test_hashing_mode_full_computes_hashes_when_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})

            result = attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(model="base.safetensors"),
                resolver=resolver,
                cache=HashCache(),
                hashing_mode="full",
            )

            self.assertEqual(result.resources[0].resource.hashes.sha256, hashlib.sha256(b"base").hexdigest())
            self.assertEqual(result.resources[0].resource.hashes.auto_v2, hashlib.sha256(b"base").hexdigest()[:10])
            self.assertEqual(result.resources[0].resource.hashes.crc32, f"{zlib.crc32(b'base') & 0xFFFFFFFF:08X}")
            self.assertEqual(result.resources[0].resource.hash_status, "hashed")

    def test_persistent_hash_cache_stores_all_hash_names_without_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            cache_path = Path(tmp) / "cache" / "hashes.json"
            write_safetensors_header(
                root / "base.safetensors",
                {"sshs_model_hash": "abcdef1234567890"},
            )
            resolver = ModelRootResolver({"checkpoints": [root]})

            attach_local_hashes(
                resources=(resource("checkpoint", "base.safetensors"),),
                generation=GenerationSettings(),
                resolver=resolver,
                cache=HashCache(persistent_path=cache_path),
                hashing_mode="full",
            )
            text = cache_path.read_text(encoding="utf-8")
            cache_json = json.loads(text)
            hashes = cache_json["records"][0]["hashes"]

            self.assertIn("AutoV1", hashes)
            self.assertIn("AutoV2", hashes)
            self.assertIn("AutoV3", hashes)
            self.assertIn("CRC32", hashes)
            self.assertIn("SHA256", hashes)
            self.assertNotIn(str(tmp), text)
            self.assertNotIn(str(root), text)

    def test_primary_model_hash_matches_hashes_model_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "diffusion_models"
            write_model(root / "unused.safetensors", b"unused")
            write_model(root / "swift.gguf", b"primary")
            resolver = ModelRootResolver({"diffusion_models": [root]})

            result = attach_local_hashes(
                resources=(
                    resource("base_model", "unused.safetensors", node_id="1", resource_type="unet"),
                    resource(
                        "base_model",
                        "swift.gguf",
                        node_id="2",
                        resource_type="diffusion_model",
                        metadata={"primaryModel": True},
                    ),
                ),
                generation=GenerationSettings(),
                resolver=resolver,
            )

            primary_hash = result.resources[1].resource.hashes.auto_v2
            self.assertEqual(result.generation.model, "swift.gguf")
            self.assertEqual(result.generation.model_hash, primary_hash)
            self.assertEqual(result.hashes.additional["model"], primary_hash)
            self.assertEqual(result.hashes.additional["Model"], primary_hash)

    def test_ambiguous_base_model_hash_is_not_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "diffusion_models"
            write_model(root / "a.safetensors", b"a")
            write_model(root / "b.gguf", b"b")
            resolver = ModelRootResolver({"diffusion_models": [root]})

            result = attach_local_hashes(
                resources=(
                    resource("base_model", "a.safetensors", node_id="1", resource_type="unet"),
                    resource("base_model", "b.gguf", node_id="2", resource_type="diffusion_model"),
                ),
                generation=GenerationSettings(),
                resolver=resolver,
            )

            self.assertIsNone(result.generation.model_hash)
            self.assertNotIn("model", result.hashes.additional)
            self.assertIn("primary_model_hash_ambiguous", {warning.code for warning in result.warnings})

    def test_no_absolute_paths_in_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            model = write_model(root / "base.safetensors", b"base")
            resolver = ModelRootResolver({"checkpoints": [root]})
            result = attach_local_hashes(
                resources=(resource("checkpoint", str(model)),),
                generation=GenerationSettings(model="base.safetensors"),
                resolver=resolver,
            )
            validation = validate_metadata(
                filename_prefix="ok",
                prompt_metadata=PromptMetadata(positive="test"),
                generation=result.generation,
                resources=result.resources,
                unresolved_resources=result.unresolved_resources,
                prompt={},
                extra_pnginfo={},
                include_workflow=False,
                include_civitai_manifest=True,
                additional_warnings=result.warnings,
            )
            manifest = build_civitai_manifest(
                prompt=PromptMetadata(positive="test"),
                generation=result.generation,
                resources=result.resources,
                unresolved_resources=result.unresolved_resources,
                hashes=result.hashes,
                validation=validation,
                include_workflow=False,
            )
            parameters = build_a1111_parameters(
                prompt=PromptMetadata(positive="test"),
                generation=result.generation,
                resources=result.resources,
                hashes=result.hashes,
            )
            sidecar = build_sidecar_payload(
                image={"filename": "image.png", "subfolder": "", "type": "output"},
                options=MetadataOptions(
                    strict_mode=False,
                    include_workflow=False,
                    include_civitai_manifest=True,
                    write_sidecar_json=True,
                ),
                prompt={},
                extra_pnginfo={},
                civitai_manifest=manifest,
                validation=validation,
            )
            combined = "\n".join(
                [
                    parameters,
                    to_json_text(manifest),
                    to_json_text(sidecar),
                    to_json_text(validation),
                ]
            )

            self.assertNotIn(str(tmp), combined)
            self.assertNotIn(str(root), combined)
            self.assertNotIn(str(model), combined)


if __name__ == "__main__":
    unittest.main()
