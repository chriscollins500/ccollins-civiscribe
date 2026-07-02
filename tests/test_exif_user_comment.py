from __future__ import annotations

from io import BytesIO
import json
import re
import unittest

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - depends on local test interpreter
    Image = None

from save_node.civitai.air import parse_air
from save_node.metadata.exif_user_comment import (
    EXIF_IFD_TAG,
    USER_COMMENT_TAG,
    USER_COMMENT_UNICODE_PREFIX,
    build_exif_bytes,
    build_exif_user_comment_text,
    decode_user_comment,
    encode_user_comment,
)
from save_node.metadata.schema import GenerationSettings, ModelResourceMetadata, PromptMetadata, ResolvedResource
from save_node.version import __version__


class ExifUserCommentTests(unittest.TestCase):
    def setUp(self) -> None:
        if Image is None:
            self.skipTest("Pillow is required for EXIF verification")

    def test_user_comment_uses_unicode_utf16be_prefix(self) -> None:
        encoded = encode_user_comment("snow 雪")

        self.assertTrue(encoded.startswith(USER_COMMENT_UNICODE_PREFIX))
        self.assertEqual(encoded[len(USER_COMMENT_UNICODE_PREFIX) :].decode("utf-16-be"), "snow 雪")

    def test_png_exif_user_comment_decodes_from_exif_sub_ifd(self) -> None:
        exif = build_exif_bytes(
            prompt=PromptMetadata(positive="a prompt", negative="low quality"),
            generation=GenerationSettings(steps=12, sampler="Euler", cfg_scale=7, seed=123, width=64, height=32),
            resources=(_resolved_lora(),),
        )
        output = BytesIO()
        Image.new("RGB", (64, 32)).save(output, format="PNG", exif=exif)

        with Image.open(BytesIO(output.getvalue())) as image:
            root_exif = image.getexif()
            exif_ifd = root_exif.get_ifd(EXIF_IFD_TAG)
            text, encoding = decode_user_comment(exif_ifd.get(USER_COMMENT_TAG))

        self.assertEqual(encoding, "UNICODE UTF-16BE")
        self.assertIn("a prompt", text)
        self.assertIn("Negative prompt: low quality", text)
        self.assertIn("Steps: 12", text)
        self.assertIn("Sampler: Euler", text)
        self.assertIn("CFG scale: 7", text)
        self.assertIn("Seed: 123", text)
        self.assertIn("Size: 64x32", text)
        self.assertNotIn("GPS", text)
        self.assertNotIn("Lens", text)

    def test_civitai_resources_json_is_compact_and_parseable(self) -> None:
        text = build_exif_user_comment_text(
            prompt=PromptMetadata(positive="portrait"),
            generation=GenerationSettings(steps=8, sampler="Euler", seed=9, width=16, height=8),
            resources=(_resolved_checkpoint(), _resolved_lora(), _unresolved_vae()),
        )
        resources = _extract_json_after(text, "Civitai resources")
        metadata = _extract_json_after(text, "Civitai metadata")

        self.assertEqual(resources[0]["type"], "checkpoint")
        self.assertEqual(resources[0]["modelId"], 10)
        self.assertEqual(resources[0]["modelVersionId"], 20)
        self.assertEqual(resources[0]["air"], "urn:air:sdxl:checkpoint:civitai:10@20")
        self.assertEqual(resources[1]["type"], "lora")
        self.assertEqual(resources[1]["modelVersionId"], 40)
        self.assertEqual(resources[1]["strength"], 0.75)
        self.assertEqual(len(resources), 2)
        self.assertNotIn("ae.safetensors", json.dumps(resources))
        self.assertEqual(metadata["generator"]["version"], __version__)
        self.assertEqual(metadata["resources"], resources)

    def test_only_model_version_identity_is_allowed_without_fake_air(self) -> None:
        text = build_exif_user_comment_text(
            prompt=PromptMetadata(positive="portrait"),
            generation=GenerationSettings(width=16, height=8),
            resources=(
                ResolvedResource(
                    resource=ModelResourceMetadata(
                        role="checkpoint",
                        type="diffusion_model",
                        civitai_model_id=2432159,
                        civitai_model_version_id=2734704,
                        metadata={"identityIncomplete": True, "primaryModel": True},
                    ),
                    resolved=True,
                ),
            ),
        )
        resources = _extract_json_after(text, "Civitai resources")

        self.assertEqual(resources, [{"modelId": 2432159, "modelVersionId": 2734704, "type": "checkpoint"}])
        self.assertNotIn("urn:air", json.dumps(resources))


def _extract_json_after(text: str, label: str):
    match = re.search(rf"{re.escape(label)}:\s*(.+?)(?=, Civitai metadata:|$)", text, re.DOTALL)
    if match is None:
        raise AssertionError(f"missing {label}")
    return json.loads(match.group(1))


def _resolved_checkpoint() -> ResolvedResource:
    air, warnings = parse_air("urn:air:sdxl:checkpoint:civitai:10@20")
    assert warnings == ()
    assert air is not None
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role="checkpoint",
            type="checkpoint",
            air=air,
            civitai_model_id=10,
            civitai_model_version_id=20,
        ),
        resolved=True,
    )


def _resolved_lora() -> ResolvedResource:
    air, warnings = parse_air("urn:air:sdxl:lora:civitai:30@40")
    assert warnings == ()
    assert air is not None
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role="lora",
            type="lora",
            air=air,
            civitai_model_id=30,
            civitai_model_version_id=40,
            strength=0.75,
            strength_model=0.75,
            strength_clip=0.5,
        ),
        resolved=True,
    )


def _unresolved_vae() -> ResolvedResource:
    return ResolvedResource(
        resource=ModelResourceMetadata(
            role="vae",
            type="vae",
            name="ae.safetensors",
            filename="ae.safetensors",
        ),
        resolved=False,
        unresolved_reason="hashed_but_no_civitai_identity",
    )


if __name__ == "__main__":
    unittest.main()
