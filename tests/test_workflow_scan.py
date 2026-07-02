from __future__ import annotations

import json
import unittest

from save_node.civitai.manifest import build_civitai_manifest
from save_node.comfy.workflow_scan import PHASE3_UNRESOLVED_REASON, scan_workflow_graph
from save_node.metadata.a1111 import build_a1111_parameters
from save_node.metadata.schema import HashMetadata
from save_node.metadata.serialize import to_json_text
from save_node.metadata.validate import validate_metadata


def base_prompt() -> dict[str, dict]:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "_meta": {"title": "Base checkpoint"},
            "inputs": {"ckpt_name": "checkpoints/base-model.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "a bright city skyline"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "blurry, low quality"},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 768, "batch_size": 2},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": 123,
                "steps": 30,
                "cfg": 7.5,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 0.8,
            },
        },
    }


def base_extra() -> dict[str, dict]:
    return {
        "workflow": {
            "version": "1.0",
            "nodes": [
                {"id": 1, "type": "CheckpointLoaderSimple", "title": "Base checkpoint"},
                {"id": 5, "type": "KSampler", "title": "Main sampler"},
            ],
        }
    }


class WorkflowScanTests(unittest.TestCase):
    def test_simple_checkpoint_only_workflow(self) -> None:
        result = scan_workflow_graph(
            {
                "1": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "checkpoints/base-model.safetensors"},
                }
            },
            {},
        )

        self.assertEqual(len(result.resources), 1)
        self.assertEqual(result.resources[0].resource.role, "checkpoint")
        self.assertEqual(result.resources[0].resource.type, "checkpoint")
        self.assertEqual(result.resources[0].resource.filename, "base-model.safetensors")
        self.assertFalse(result.resources[0].resolved)
        self.assertEqual(result.unresolved_resources[0].reason, PHASE3_UNRESOLVED_REASON)

    def test_checkpoint_loader_video_file_is_not_labeled_checkpoint(self) -> None:
        result = scan_workflow_graph(
            {
                "1": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "video/ltx-dev-preview.mp4"},
                }
            },
            {},
        )

        resource = result.resources[0].resource
        self.assertEqual(resource.role, "base_model")
        self.assertEqual(resource.type, "video_model")
        self.assertIn("resource_type_uncertain", {warning.code for warning in result.warnings})

    def test_unet_loader_is_base_model_not_checkpoint(self) -> None:
        result = scan_workflow_graph(
            {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux-dev.safetensors"}}},
            {},
        )

        resource = result.resources[0].resource
        self.assertEqual(resource.role, "base_model")
        self.assertEqual(resource.type, "unet")

    def test_gguf_loader_is_diffusion_model_not_checkpoint(self) -> None:
        result = scan_workflow_graph(
            {"1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux-dev-Q8_0.gguf"}}},
            {},
        )

        resource = result.resources[0].resource
        self.assertEqual(resource.role, "base_model")
        self.assertEqual(resource.type, "diffusion_model")

    def test_unet_loader_connected_to_sampler_is_primary_model(self) -> None:
        result = scan_workflow_graph(
            {
                "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux-dev.safetensors"}},
                "2": {"class_type": "KSampler", "inputs": {"model": ["1", 0]}},
            },
            {},
        )

        self.assertEqual(result.generation.model, "flux-dev.safetensors")
        self.assertTrue(result.resources[0].resource.metadata["primaryModel"])

    def test_gguf_loader_connected_to_sampler_is_primary_model(self) -> None:
        result = scan_workflow_graph(
            {
                "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "swiftFast.gguf"}},
                "2": {"class_type": "KSampler", "inputs": {"model": ["1", 0]}},
            },
            {},
        )

        self.assertEqual(result.generation.model, "swiftFast.gguf")
        self.assertTrue(result.resources[0].resource.metadata["primaryModel"])

    def test_model_sampling_aura_flow_preserves_sampler_primary_model(self) -> None:
        result = scan_workflow_graph(
            {
                "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "unused.safetensors"}},
                "2": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "swiftFast.gguf"}},
                "3": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["2", 0], "shift": 3.0}},
                "4": {"class_type": "ClownsharKSampler_Beta", "inputs": {"model": ["3", 0]}},
            },
            {},
        )

        primary = [resource for resource in result.resources if resource.resource.metadata.get("primaryModel")]
        self.assertEqual(result.generation.model, "swiftFast.gguf")
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0].resource.filename, "swiftFast.gguf")
        self.assertNotIn("primary_model_ambiguous", {warning.code for warning in result.warnings})

    def test_duplicate_base_models_without_sampler_primary_warn(self) -> None:
        result = scan_workflow_graph(
            {
                "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "a.safetensors"}},
                "2": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "b.gguf"}},
            },
            {},
        )

        self.assertIsNone(result.generation.model)
        self.assertIn("primary_model_ambiguous", {warning.code for warning in result.warnings})

    def test_save_node_active_graph_excludes_disconnected_loaders(self) -> None:
        result = scan_workflow_graph(
            {
                "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors"}},
                "2": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "swiftFastAndDetailed_neo.gguf"}},
                "3": {
                    "class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["2", 0], "lora_name": "ProjectRealismPhotoLora_v1.safetensors"},
                },
                "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["3", 0]}},
                "5": {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": "Qwen3-4B-BF16.gguf"}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["5", 0], "text": "prompt"}},
                "7": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
                "8": {
                    "class_type": "EmptySD3LatentImage",
                    "inputs": {"width": ["14", 1], "height": ["14", 2], "batch_size": 1},
                },
                "9": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
                "10": {
                    "class_type": "ClownsharKSampler_Beta",
                    "inputs": {
                        "model": ["4", 0],
                        "positive": ["6", 0],
                        "negative": ["7", 0],
                        "latent_image": ["8", 0],
                        "seed": 1,
                        "steps": 12,
                        "sampler_name": "euler",
                    },
                },
                "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["9", 0]}},
                "12": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
                "13": {
                    "class_type": "ImageUpscaleWithModel",
                    "inputs": {"upscale_model": ["12", 0], "image": ["11", 0]},
                },
                "14": {"class_type": "SmartResolutionCalc", "inputs": {}},
                "15": {"class_type": "SaveImageWithCivitaiMetadata", "inputs": {"images": ["11", 0]}},
            },
            {},
        )

        names = [resource.resource.name for resource in result.resources]
        self.assertEqual(
            names,
            [
                "swiftFastAndDetailed_neo.gguf",
                "ProjectRealismPhotoLora_v1.safetensors",
                "Qwen3-4B-BF16.gguf",
                "ae.safetensors",
            ],
        )
        self.assertEqual(result.generation.model, "swiftFastAndDetailed_neo.gguf")
        self.assertNotIn("z_image_turbo_bf16.safetensors", names)
        self.assertNotIn("4x-UltraSharp.pth", names)
        raw_names = [resource.resource.name for resource in result.raw_resources]
        self.assertIn("z_image_turbo_bf16.safetensors", raw_names)
        self.assertIn("4x-UltraSharp.pth", raw_names)

    def test_checkpoint_positive_and_negative_prompts(self) -> None:
        result = scan_workflow_graph(base_prompt(), base_extra())

        self.assertEqual(result.prompt.positive, "a bright city skyline")
        self.assertEqual(result.prompt.negative, "blurry, low quality")
        self.assertEqual(result.generator.version, "1.0")

    def test_checkpoint_with_one_lora(self) -> None:
        prompt = base_prompt()
        prompt["6"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "lora_name": "loras/detail.safetensors",
                "strength_model": 0.8,
                "strength_clip": 0.6,
            },
        }

        result = scan_workflow_graph(prompt, {})
        loras = [resource for resource in result.resources if resource.resource.role == "lora"]

        self.assertEqual(len(loras), 1)
        self.assertEqual(loras[0].resource.filename, "detail.safetensors")
        self.assertEqual(loras[0].resource.strength_model, 0.8)
        self.assertEqual(loras[0].resource.strength_clip, 0.6)

    def test_multiple_loras_keep_different_strengths(self) -> None:
        prompt = base_prompt()
        prompt["6"] = {
            "class_type": "LoraLoader",
            "inputs": {"lora_name": "loras/a.safetensors", "strength_model": 0.4, "strength_clip": 0.5},
        }
        prompt["7"] = {
            "class_type": "LoraLoader",
            "inputs": {"lora_name": "loras/b.safetensors", "strength_model": 0.9, "strength_clip": 0.2},
        }

        result = scan_workflow_graph(prompt, {})
        strengths = {
            resource.resource.filename: (
                resource.resource.strength_model,
                resource.resource.strength_clip,
            )
            for resource in result.resources
            if resource.resource.role == "lora"
        }

        self.assertEqual(strengths["a.safetensors"], (0.4, 0.5))
        self.assertEqual(strengths["b.safetensors"], (0.9, 0.2))

    def test_vae_loader_is_detected(self) -> None:
        prompt = base_prompt()
        prompt["6"] = {"class_type": "VAELoader", "inputs": {"vae_name": "vae/ae.safetensors"}}

        result = scan_workflow_graph(prompt, {})

        self.assertIn("ae.safetensors", [resource.resource.filename for resource in result.resources])
        self.assertEqual(result.generation.vae, "ae.safetensors")

    def test_empty_latent_dimensions_are_detected(self) -> None:
        result = scan_workflow_graph(base_prompt(), {})

        self.assertEqual(result.generation.width, 1024)
        self.assertEqual(result.generation.height, 768)
        self.assertEqual(result.generation.batch_size, 2)

    def test_empty_sd3_latent_with_linked_dimensions_leaves_size_for_image_fallback(self) -> None:
        prompt = base_prompt()
        prompt["4"] = {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": ["20", 0], "height": ["21", 0], "batch_size": 1},
        }

        result = scan_workflow_graph(prompt, {})

        self.assertIsNone(result.generation.width)
        self.assertIsNone(result.generation.height)
        self.assertEqual(result.generation.batch_size, 1)
        self.assertNotIn("unknown_node_class", {warning.code for warning in result.warnings})

    def test_ksampler_settings_are_detected(self) -> None:
        result = scan_workflow_graph(base_prompt(), {})

        self.assertEqual(result.generation.seed, 123)
        self.assertEqual(result.generation.steps, 30)
        self.assertEqual(result.generation.sampler, "euler")
        self.assertEqual(result.generation.scheduler, "normal")
        self.assertEqual(result.generation.cfg_scale, 7.5)
        self.assertEqual(result.generation.denoising_strength, 0.8)

    def test_ksampler_advanced_settings_are_detected(self) -> None:
        prompt = base_prompt()
        prompt["5"]["class_type"] = "KSamplerAdvanced"
        prompt["5"]["inputs"].pop("seed")
        prompt["5"]["inputs"]["noise_seed"] = 456
        prompt["5"]["inputs"]["start_at_step"] = 3
        prompt["5"]["inputs"]["end_at_step"] = 20

        result = scan_workflow_graph(prompt, {})

        self.assertEqual(result.generation.seed, 456)
        self.assertEqual(result.generation.extra["startAtStep"], 3)
        self.assertEqual(result.generation.extra["endAtStep"], 20)

    def test_flux_style_workflow_resources_are_detected(self) -> None:
        prompt = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "unet/flux-q8.gguf"}},
            "2": {
                "class_type": "DualCLIPLoader",
                "inputs": {"clip_name1": "clip/t5xxl.safetensors", "clip_name2": "clip/clip_l.safetensors"},
            },
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/ae.safetensors"}},
            "4": {"class_type": "ModelSamplingFlux", "inputs": {"max_shift": 1.15, "base_shift": 0.5}},
            "5": {"class_type": "FluxGuidance", "inputs": {"guidance": 3.5}},
            "6": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["5", 0]}},
        }

        result = scan_workflow_graph(prompt, {})
        roles = [resource.resource.role for resource in result.resources]
        filenames = [resource.resource.filename for resource in result.resources]

        self.assertIn("base_model", roles)
        self.assertEqual(filenames.count("t5xxl.safetensors"), 1)
        self.assertEqual(filenames.count("clip_l.safetensors"), 1)
        self.assertEqual(result.generation.extra["fluxGuidance"], 3.5)
        self.assertEqual(result.generation.extra["modelSamplingFlux"]["max_shift"], 1.15)

    def test_unknown_custom_node_warns_and_is_ignored(self) -> None:
        prompt = base_prompt()
        prompt["99"] = {"class_type": "MyCustomSecretNode", "inputs": {"anything": "value"}}

        result = scan_workflow_graph(prompt, {})

        self.assertIn("unknown_node_class", {warning.code for warning in result.warnings})

    def test_resource_consistency_between_parameters_and_manifest(self) -> None:
        prompt = base_prompt()
        prompt["6"] = {"class_type": "LoraLoader", "inputs": {"lora_name": "loras/detail.safetensors"}}
        result = scan_workflow_graph(prompt, {})
        validation = validate_metadata(
            filename_prefix="ok",
            prompt_metadata=result.prompt,
            generation=result.generation,
            resources=result.resources,
            unresolved_resources=result.unresolved_resources,
            prompt=prompt,
            extra_pnginfo={},
            include_workflow=False,
            include_civitai_manifest=True,
            additional_warnings=result.warnings,
        )
        manifest = build_civitai_manifest(
            prompt=result.prompt,
            generation=result.generation,
            resources=result.resources,
            unresolved_resources=result.unresolved_resources,
            hashes=HashMetadata(),
            validation=validation,
            include_workflow=True,
            generator=result.generator,
        )
        parameters = build_a1111_parameters(
            prompt=result.prompt,
            generation=result.generation,
            resources=result.resources,
            hashes=HashMetadata(),
        )
        manifest_json = json.loads(to_json_text(manifest))

        self.assertNotIn("Civitai resources:", parameters)
        self.assertNotIn("detail.safetensors", parameters)
        self.assertIn("detail.safetensors", to_json_text(manifest))
        self.assertEqual(len(manifest_json["resources"]), len(result.resources))
        self.assertNotIn(
            "resource_in_parameters_not_manifest",
            {warning.code for warning in validation.warnings},
        )
        self.assertNotIn(
            "resource_in_manifest_not_parameters",
            {warning.code for warning in validation.warnings},
        )

    def test_unicode_prompt_text(self) -> None:
        prompt = base_prompt()
        prompt["2"]["inputs"]["text"] = "雪の街 with neon signs"

        result = scan_workflow_graph(prompt, {})

        self.assertEqual(result.prompt.positive, "雪の街 with neon signs")

    def test_long_prompt_text(self) -> None:
        prompt = base_prompt()
        prompt["2"]["inputs"]["text"] = "glowing architecture, " * 200

        result = scan_workflow_graph(prompt, {})

        self.assertEqual(result.prompt.positive, "glowing architecture, " * 200)

    def test_malformed_workflow_json_warns_without_crashing(self) -> None:
        result = scan_workflow_graph(["not", "a", "mapping"], {"workflow": {"nodes": "bad"}})

        codes = {warning.code for warning in result.warnings}
        self.assertIn("malformed_prompt_graph", codes)
        self.assertIn("malformed_workflow_nodes", codes)
        self.assertEqual(result.resources, ())

    def test_duplicate_resource_names_from_different_nodes_are_kept(self) -> None:
        prompt = base_prompt()
        prompt["6"] = {"class_type": "LoraLoader", "inputs": {"lora_name": "loras/shared.safetensors"}}
        prompt["7"] = {"class_type": "LoraLoader", "inputs": {"lora_name": "other/shared.safetensors"}}

        result = scan_workflow_graph(prompt, {})
        matching = [resource for resource in result.resources if resource.resource.filename == "shared.safetensors"]

        self.assertEqual(len(matching), 2)
        self.assertEqual({resource.resource.node_id for resource in matching}, {"6", "7"})


if __name__ == "__main__":
    unittest.main()
