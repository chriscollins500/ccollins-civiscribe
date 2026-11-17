from __future__ import annotations

import json
import os
import ssl
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from tests.path_support import directory_link
from tools import audit_comfyui_node_coverage as audit

EXPECTED_TWO = 2
EXPECTED_THREE = 3
EXPECTED_FIVE = 5


@pytest.fixture
def object_info_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    monkeypatch.setattr(audit, "create_tls_contexts", lambda: (("test_system", context),))


@pytest.mark.usefixtures("object_info_tls")
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8188/object_info",
        "http://192.0.2.10:8000/comfy/object_info/",
        "https://comfy.example.invalid/prefix/object_info",
    ],
)
def test_object_info_fetch_preserves_selected_origins_and_proxy_prefixes(url: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == url.rstrip("/")
        assert request.method == "GET"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(200, json={"SaveImage": {"input": {}}})

    assert audit._fetch_json(url, 1.0, transport=httpx.MockTransport(handler)) == {
        "SaveImage": {"input": {}}
    }


@pytest.mark.parametrize(
    "url",
    [
        "file:///object_info",
        "http://127.0.0.1:8188/queue",
        "http://operator:DO_NOT_RECORD@127.0.0.1:8188/object_info",
        "http://127.0.0.1:8188/object_info?token=DO_NOT_RECORD",
        "http://127.0.0.1:8188/object_info#DO_NOT_RECORD",
    ],
)
def test_object_info_fetch_rejects_other_routes_and_secret_bearing_urls(url: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("Rejected schema URL must not reach the transport")

    with pytest.raises(ValueError, match="object_info_url_rejected"):
        audit._fetch_json(url, 1.0, transport=httpx.MockTransport(handler))


@pytest.mark.usefixtures("object_info_tls")
def test_object_info_fetch_bounds_streaming_and_does_not_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "MAX_REGISTRY_RESPONSE_BYTES", 32)

    class OversizedResponse(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"x" * 33
            pytest.fail("Oversized response must be closed before consuming more data")

    with pytest.raises(ValueError, match="object_info_response_too_large"):
        audit._fetch_json(
            "http://127.0.0.1:8188/object_info",
            1.0,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, stream=OversizedResponse())
            ),
        )

    requests = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://example.invalid/private"})

    with pytest.raises(httpx.HTTPStatusError):
        audit._fetch_json(
            "http://127.0.0.1:8188/object_info", 1.0, transport=httpx.MockTransport(redirect)
        )
    assert len(requests) == 1


def test_workflow_audit_excludes_windows_junction_directories_and_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "selected"
    junction = root / "junction"
    _write_json(junction / "outside.json", {"1": {"class_type": "DO_NOT_RECORD"}})
    _write_json(root / "safe.json", {"1": {"class_type": "KSampler", "inputs": {}}})
    monkeypatch.setattr(os.path, "isjunction", lambda path: path == junction, raising=False)

    report = audit.analyze_workflow_roots([root, junction])
    roots = _roots(report)
    assert roots[0]["filesDiscovered"] == 1
    assert roots[0]["issueCounts"] == {"workflow_directory_symlink_skipped": 1}
    assert roots[1]["filesDiscovered"] == 0
    assert roots[1]["issueCounts"] == {"workflow_root_symlink_rejected": 1}
    assert "DO_NOT_RECORD" not in json.dumps(report)


def test_workflow_audit_rejects_real_link_roots_and_skips_linked_directories(
    tmp_path: Path,
) -> None:
    root = tmp_path / "selected"
    outside = tmp_path / "outside"
    _write_json(root / "safe.json", {"1": {"class_type": "KSampler", "inputs": {}}})
    _write_json(outside / "private.json", {"1": {"class_type": "DO_NOT_RECORD"}})
    directory_link(outside, root / "outside-link")
    directory_link(root, tmp_path / "root-link")
    report = audit.analyze_workflow_roots([root, tmp_path / "root-link"])
    roots = _roots(report)
    assert roots[0]["filesDiscovered"] == 1
    assert roots[0]["issueCounts"] == {"workflow_directory_symlink_skipped": 1}
    assert roots[1]["filesDiscovered"] == 0
    assert roots[1]["issueCounts"] == {"workflow_root_symlink_rejected": 1}
    assert "DO_NOT_RECORD" not in json.dumps(report)


def test_workflow_audit_preserves_parent_scope_for_dotdot_root(tmp_path: Path) -> None:
    root = tmp_path / "selected"
    _write_json(root / "safe.json", {"1": {"class_type": "KSampler", "inputs": {}}})
    (root / "nested").mkdir()
    report = audit.analyze_workflow_roots([root / "nested" / ".."])
    assert _roots(report)[0]["filesDiscovered"] == 0
    assert _roots(report)[0]["issueCounts"] == {"workflow_root_escape_rejected": 1}


def test_workflow_audit_inspects_the_real_final_component_after_link_and_dotdot(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "target-parent"
    nested = parent / "nested"
    nested.mkdir(parents=True)
    _write_json(parent / "safe/workflow.json", {"1": {"class_type": "KSampler", "inputs": {}}})
    directory_link(nested, tmp_path / "alias")
    directory_link(parent / "safe", parent / "root-link")
    # Windows collapses '..' before following intermediate junctions; POSIX
    # resolves it against the linked directory. Both final links must be rejected.
    _write_json(tmp_path / "safe/workflow.json", {"1": {"class_type": "KSampler", "inputs": {}}})
    directory_link(tmp_path / "safe", tmp_path / "root-link")
    prefix = tmp_path / "alias" / ".."
    report = audit.analyze_workflow_roots([prefix / "root-link", prefix / "safe"])
    roots = _roots(report)
    assert roots[0]["filesDiscovered"] == 0
    assert roots[0]["issueCounts"] == {"workflow_root_symlink_rejected": 1}
    assert roots[1]["filesDiscovered"] == 1


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )


def _all_records(section: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *section["actionableMetadataNodes"],
        *section["broadHeuristicCandidates"],
        *section["otherNodes"],
    ]


def _record(section: dict[str, Any], class_name: str) -> dict[str, Any]:
    return next(item for item in _all_records(section) if item["className"] == class_name)


def _roots(section: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], section["roots"])


def test_object_info_separates_actionable_broad_and_other_without_values() -> None:
    report = audit.analyze_object_info(
        {
            "CheckpointLoaderSimple": {
                "input": {
                    "required": {
                        "ckpt_name": (
                            ["DO_NOT_RECORD_MODEL_A", "DO_NOT_RECORD_MODEL_B"],
                            {},
                        )
                    }
                },
                "output": ["MODEL", "CLIP", "VAE"],
                "python_module": "DO_NOT_RECORD_MODULE",
                "category": "DO_NOT_RECORD_CATEGORY",
            },
            "TypedLatentTransform": {
                "input": {"required": {}},
                "output": ["LATENT"],
            },
            "TypedModelPatcher": {
                "input": {"required": {"model": ("MODEL", {})}},
                "output": ["MODEL"],
            },
            "CLIPSetLastLayer": {
                "input": {
                    "required": {
                        "clip": ("CLIP", {}),
                        "stop_at_clip_layer": ("INT", {}),
                    }
                },
                "output": ["CLIP"],
            },
            "SaveImage": {
                "input": {"required": {"images": ("IMAGE", {})}},
                "output": [],
            },
            "NumberMath": {
                "input": {"required": {"amount": ("FLOAT", {"default": 7.5})}},
                "output": ["FLOAT"],
            },
            "unsafe/class": {
                "input": {"required": {"prompt": ("STRING", {})}},
                "output": ["STRING"],
            },
        }
    )

    checkpoint = _record(report, "CheckpointLoaderSimple")
    assert checkpoint["classification"] == "actionable_metadata"
    assert checkpoint["scannerRecognized"] is True
    assert checkpoint["inputShapes"] == [
        {
            "count": 1,
            "inputs": [{"name": "ckpt_name", "type": "COMBO"}],
        }
    ]
    assert _record(report, "TypedLatentTransform")["classification"] == "broad_heuristic"
    assert _record(report, "TypedModelPatcher")["classification"] == "broad_heuristic"
    clip_skip = _record(report, "CLIPSetLastLayer")
    assert clip_skip["classification"] == "broad_heuristic"
    assert clip_skip["scannerRecognized"] is True
    assert _record(report, "SaveImage")["classification"] == "broad_heuristic"
    assert _record(report, "NumberMath")["classification"] == "other_observed"
    assert report["invalidClassNameCount"] == 1

    serialized = json.dumps(report)
    assert "DO_NOT_RECORD_MODEL" not in serialized
    assert "DO_NOT_RECORD_MODULE" not in serialized
    assert "DO_NOT_RECORD_CATEGORY" not in serialized
    assert "unsafe/class" not in serialized


def test_object_info_recognizes_sampler_contract_without_class_name_markers() -> None:
    report = audit.analyze_object_info(
        {
            "OpaqueExecutionNode": {
                "input": {
                    "required": {
                        "model": ("MODEL", {}),
                        "steps": ("INT", {}),
                        "sampler_name": (["euler"], {}),
                        "scheduler": (["normal"], {}),
                        "seed": ("INT", {}),
                    }
                },
                "output": ["LATENT"],
            }
        }
    )

    record = _record(report, "OpaqueExecutionNode")
    assert record["classification"] == "actionable_metadata"
    assert record["scannerRecognized"] is False


@pytest.mark.parametrize(
    ("class_name", "required", "output"),
    [
        ("OpaqueFileProvider", {"model_name": ("STRING", {})}, ["MODEL"]),
        (
            "OpaquePromptProvider",
            {"text": ("STRING", {}), "clip": ("CLIP", {})},
            ["CONDITIONING"],
        ),
        (
            "OpaqueLatentProvider",
            {"width": ("INT", {}), "height": ("INT", {})},
            ["LATENT"],
        ),
    ],
)
def test_object_info_recognizes_structural_metadata_contracts(
    class_name: str,
    required: dict[str, object],
    output: list[str],
) -> None:
    report = audit.analyze_object_info(
        {
            class_name: {
                "input": {"required": required},
                "output": output,
            }
        }
    )

    record = _record(report, class_name)
    assert record["classification"] == "actionable_metadata"
    assert record["scannerRecognized"] is False


def test_object_info_recognizes_direct_image_generation_contract() -> None:
    report = audit.analyze_object_info(
        {
            "OpaqueRemoteRenderer": {
                "input": {
                    "required": {
                        "prompt": ("STRING", {}),
                        "seed": ("INT", {}),
                        "model": (["remote-model"], {}),
                    }
                },
                "output": ["IMAGE"],
            }
        }
    )

    record = _record(report, "OpaqueRemoteRenderer")
    assert record["classification"] == "actionable_metadata"
    assert record["scannerRecognized"] is False


def test_known_partner_direct_image_generator_is_scanner_recognized() -> None:
    report = audit.analyze_object_info(
        {
            "Flux2ProImageNode": {
                "input": {
                    "required": {
                        "prompt": ("STRING", {}),
                        "seed": ("INT", {}),
                        "model": (["remote-model"], {}),
                    }
                },
                "output": ["IMAGE"],
            }
        }
    )

    record = _record(report, "Flux2ProImageNode")
    assert record["classification"] == "actionable_metadata"
    assert record["scannerRecognized"] is True


@pytest.mark.parametrize(
    ("class_name", "required", "output"),
    [
        ("PulidFluxEvaClipLoader", {}, ["EVA_CLIP"]),
        ("PuLIDEVACLIPLoader", {}, ["EVA_CLIP"]),
        (
            "A1r Conditional CheckpointLoader",
            {
                "ckpt_name_a": (["a.safetensors"], {}),
                "ckpt_name_b": (["b.safetensors"], {}),
                "enable_second": ("BOOLEAN", {}),
            },
            ["MODEL", "CLIP", "VAE", "MODEL", "CLIP", "VAE", "INT"],
        ),
        ("WarpedDualCLIPLoader", {}, ["CLIP"]),
        ("WarpedDualClipLoaderGGUF", {}, ["CLIP"]),
        ("WarpedVAELoader", {}, ["VAE"]),
    ],
)
def test_source_reviewed_registry_and_ui_aliases_are_recognized(
    class_name: str,
    required: dict[str, object],
    output: list[str],
) -> None:
    report = audit.analyze_object_info(
        {
            class_name: {
                "input": {"required": required},
                "output": output,
            }
        }
    )

    assert _record(report, class_name)["scannerRecognized"] is True


def test_uuid_subgraph_reference_is_expected_ui_wrapper_not_actionable() -> None:
    tier, families, recognized = audit._candidate_tier(
        "f2fdebf6-dfaf-43b6-9eb2-7f70613cfdc1",
        ("ckpt_name", "model"),
        ("MODEL",),
        input_type_pairs=(("ckpt_name", "STRING"), ("model", "MODEL")),
    )

    assert tier == "other_observed"
    assert families == ("ui_subgraph_reference",)
    assert recognized is True


def test_extension_map_records_only_class_and_source_counts() -> None:
    report = audit.analyze_extension_map(
        {
            "DO_NOT_RECORD_SOURCE_A": [["VAELoader", "KSampler"], {}],
            "DO_NOT_RECORD_SOURCE_B": [["VAELoader", "PlainUtility"], {}],
        }
    )

    assert _record(report, "VAELoader")["sourceCount"] == EXPECTED_TWO
    assert _record(report, "KSampler")["classification"] == "actionable_metadata"
    assert _record(report, "PlainUtility")["classification"] == "other_observed"
    assert "DO_NOT_RECORD_SOURCE" not in json.dumps(report)


def test_official_registry_catalog_deduplicates_versions_without_values() -> None:
    report = audit.analyze_registry_comfy_nodes(
        {
            "total": 3,
            "comfy_nodes": [
                {
                    "comfy_node_name": "CheckpointLoaderSimple",
                    "input_types": json.dumps(
                        {
                            "required": {
                                "ckpt_name": [
                                    ["DO_NOT_RECORD_MODEL_A", "DO_NOT_RECORD_MODEL_B"],
                                    {"default": "DO_NOT_RECORD_DEFAULT"},
                                ]
                            }
                        }
                    ),
                    "return_types": json.dumps(["MODEL", "CLIP", "VAE"]),
                    "description": "DO_NOT_RECORD_DESCRIPTION",
                    "deprecated": False,
                    "experimental": False,
                },
                {
                    "comfy_node_name": "CheckpointLoaderSimple",
                    "input_types": json.dumps(
                        {"required": {"ckpt_name": [["DO_NOT_RECORD_MODEL_C"], {}]}}
                    ),
                    "return_types": json.dumps(["MODEL", "CLIP", "VAE"]),
                    "deprecated": True,
                    "experimental": False,
                },
                {
                    "comfy_node_name": "unsafe/class",
                    "input_types": json.dumps({"required": {"prompt": ["STRING", {}]}}),
                    "return_types": json.dumps(["STRING"]),
                    "deprecated": False,
                    "experimental": True,
                },
            ],
        }
    )

    checkpoint = _record(report, "CheckpointLoaderSimple")
    assert report["recordsObserved"] == EXPECTED_THREE
    assert report["safeUniqueClassNames"] == 1
    assert report["duplicateRecordCount"] == 1
    assert report["invalidClassNameCount"] == 1
    assert report["deprecatedRecordCount"] == 1
    assert report["experimentalRecordCount"] == 1
    assert checkpoint["count"] == EXPECTED_TWO
    assert checkpoint["inputShapes"] == [
        {
            "count": EXPECTED_TWO,
            "inputs": [{"name": "ckpt_name", "type": "COMBO"}],
        }
    ]
    serialized = json.dumps(report)
    assert "DO_NOT_RECORD" not in serialized
    assert "unsafe/class" not in serialized


def test_official_registry_fetch_is_bounded_paged_and_structural() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params["page"])
        entries = (
            [
                {
                    "comfy_node_name": "KSampler",
                    "input_types": json.dumps(
                        {
                            "required": {
                                "steps": ["INT", {"default": 20}],
                                "sampler_name": [
                                    ["DO_NOT_RECORD_SAMPLER"],
                                    {"default": "DO_NOT_RECORD_DEFAULT"},
                                ],
                            }
                        }
                    ),
                    "return_types": json.dumps(["LATENT"]),
                },
                {
                    "comfy_node_name": "PlainUtility",
                    "input_types": json.dumps({"required": {"value": ["INT", {}]}}),
                    "return_types": json.dumps(["INT"]),
                },
            ]
            if page == 1
            else [
                {
                    "comfy_node_name": "VAELoader",
                    "input_types": json.dumps(
                        {"required": {"vae_name": [["DO_NOT_RECORD_VAE"], {}]}}
                    ),
                    "return_types": json.dumps(["VAE"]),
                }
            ]
        )
        return httpx.Response(
            200,
            json={"comfy_nodes": entries, "total": 3},
            request=request,
        )

    report = audit.fetch_registry_comfy_nodes(
        transport=httpx.MockTransport(handler),
        options=audit.RegistryFetchOptions(
            page_size=2,
            workers=2,
            max_records=3,
        ),
    )

    assert report["complete"] is True
    assert report["pagesRequested"] == EXPECTED_TWO
    assert report["pagesSucceeded"] == EXPECTED_TWO
    assert report["recordsObserved"] == EXPECTED_THREE
    assert report["safeUniqueClassNames"] == EXPECTED_THREE
    assert {int(request.url.params["page"]) for request in requests} == {1, 2}
    assert all(
        request.headers["user-agent"] == "CCollins-CiviScribe-Node-Audit/2.0"
        for request in requests
    )
    assert "DO_NOT_RECORD" not in json.dumps(report)


def test_official_registry_fetch_rejects_nonofficial_url() -> None:
    with pytest.raises(ValueError, match="official_registry_url_rejected"):
        audit.fetch_registry_comfy_nodes(
            "https://example.invalid/comfy-nodes",
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        )


def test_registry_request_revalidates_target_and_uses_a_bounded_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "MAX_REGISTRY_RESPONSE_BYTES", 32)

    class OversizedResponse(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"x" * 33
            pytest.fail("Registry response must not be fully buffered")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(audit.DEFAULT_REGISTRY_COMFY_NODES_URL + "?")
        return httpx.Response(200, stream=OversizedResponse())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="official_registry_url_rejected"):
            audit._registry_page_payload(
                client, "https://example.invalid/comfy-nodes", page=1, page_size=1
            )
        with pytest.raises(ValueError, match="official_registry_response_too_large"):
            audit._registry_page_payload(
                client, "https://api.comfy.org:443/comfy-nodes/", page=1, page_size=1
            )


def test_repeatable_workflow_roots_parse_api_ui_and_nested_subgraphs(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first-corpus"
    second_root = tmp_path / "second-corpus"
    _write_json(
        first_root / "api-input.json",
        {
            "prompt": {
                "1": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "DO_NOT_RECORD_MODEL_VALUE"},
                },
                "2": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "clip": ["1", 1],
                        "text": "DO_NOT_RECORD_POSITIVE_PROMPT",
                    },
                },
            },
            "subgraphs": {
                "DO_NOT_RECORD_SUBGRAPH_KEY": {
                    "10": {
                        "class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": "DO_NOT_RECORD_CONTROLNET"},
                    }
                }
            },
        },
    )
    _write_json(
        second_root / "ui-input.json",
        {
            "version": 1,
            "nodes": [
                {
                    "id": 1,
                    "type": "KSampler",
                    "inputs": [
                        {"name": "model", "type": "MODEL", "link": 1},
                        {"name": "positive", "type": "CONDITIONING", "link": 2},
                    ],
                    "widgets_values": ["DO_NOT_RECORD_SAMPLER_WIDGET"],
                    "properties": {"models": ["DO_NOT_RECORD_PROPERTY_VALUE"]},
                }
            ],
            "definitions": {
                "subgraphs": [
                    {
                        "id": "subgraph-id-not-reported",
                        "nodes": [
                            {
                                "id": 2,
                                "type": "VAELoader",
                                "inputs": [],
                                "widgets_values": ["DO_NOT_RECORD_VAE_WIDGET"],
                            }
                        ],
                    }
                ]
            },
        },
    )

    report = audit.analyze_workflow_roots([first_root, second_root])

    assert [item["rootLabel"] for item in _roots(report)] == [
        "workflow-root-001",
        "workflow-root-002",
    ]
    assert report["rootCount"] == EXPECTED_TWO
    assert report["nodeOccurrences"] == EXPECTED_FIVE
    assert _record(report, "CheckpointLoaderSimple")["inputShapes"] == [
        {
            "count": 1,
            "inputs": [{"name": "ckpt_name", "type": "STRING"}],
        }
    ]
    assert _record(report, "CLIPTextEncode")["inputShapes"] == [
        {
            "count": 1,
            "inputs": [
                {"name": "clip", "type": "LINK"},
                {"name": "text", "type": "STRING"},
            ],
        }
    ]
    assert _record(report, "KSampler")["documentKinds"] == {"ui_workflow": 1}
    assert _record(report, "VAELoader")["documentKinds"] == {"ui_subgraph": 1}
    assert _record(report, "ControlNetLoader")["documentKinds"] == {"api_subgraph": 1}

    serialized = json.dumps(report)
    for forbidden in (
        "DO_NOT_RECORD_MODEL_VALUE",
        "DO_NOT_RECORD_POSITIVE_PROMPT",
        "DO_NOT_RECORD_CONTROLNET",
        "DO_NOT_RECORD_SAMPLER_WIDGET",
        "DO_NOT_RECORD_PROPERTY_VALUE",
        "DO_NOT_RECORD_VAE_WIDGET",
        "api-input.json",
        "ui-input.json",
        str(first_root),
        str(second_root),
        "subgraph-id-not-reported",
        "DO_NOT_RECORD_SUBGRAPH_KEY",
    ):
        assert forbidden not in serialized


def test_wrapper_with_prompt_and_workflow_records_both_structures(
    tmp_path: Path,
) -> None:
    workflow_file = tmp_path / "wrapped.json"
    _write_json(
        workflow_file,
        {
            "prompt": {
                "1": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": "DO_NOT_RECORD"},
                }
            },
            "workflow": {
                "nodes": [
                    {
                        "id": 1,
                        "type": "SamplerCustomAdvanced",
                        "inputs": [{"name": "guider", "type": "GUIDER"}],
                    }
                ]
            },
        },
    )

    report = audit.analyze_workflow_roots([workflow_file])

    assert report["nodeOccurrences"] == EXPECTED_TWO
    assert _roots(report)[0]["documentKinds"] == {
        "api_prompt": 1,
        "ui_workflow": 1,
    }
    assert "DO_NOT_RECORD" not in json.dumps(report)


def test_unsafe_workflow_labels_are_omitted_without_echoing_them(
    tmp_path: Path,
) -> None:
    root = tmp_path / "corpus"
    _write_json(
        root / "unsafe.json",
        {
            "1": {
                "class_type": "private/class",
                "inputs": {"private/input": "DO_NOT_RECORD"},
            },
            "2": {
                "class_type": "KSampler",
                "inputs": {
                    "private/input": "DO_NOT_RECORD",
                    "steps": 20,
                },
            },
        },
    )

    report = audit.analyze_workflow_roots([root])
    root_report = _roots(report)[0]

    assert root_report["issueCounts"] == {
        "unsafe_class_name_omitted": 1,
        "unsafe_input_name_omitted": 1,
    }
    assert _record(report, "KSampler")["inputShapes"] == [
        {
            "count": 1,
            "inputs": [{"name": "steps", "type": "INTEGER"}],
        }
    ]
    serialized = json.dumps(report)
    assert "private/class" not in serialized
    assert "private/input" not in serialized
    assert "DO_NOT_RECORD" not in serialized


def test_size_depth_and_malformed_limits_skip_files_transactionally(
    tmp_path: Path,
) -> None:
    root = tmp_path / "limited"
    root.mkdir()
    (root / "oversized.json").write_text(
        json.dumps({"padding": "x" * 1_000}),
        encoding="utf-8",
    )
    (root / "malformed.json").write_text("{", encoding="utf-8")
    _write_json(
        root / "deep.json",
        {
            "prompt": {
                "1": {
                    "class_type": "KSampler",
                    "inputs": {"nested": {"a": {"b": {"c": {"d": 1}}}}},
                }
            }
        },
    )
    limits = audit.WorkflowAuditLimits(
        max_file_bytes=500,
        max_json_depth=4,
    )

    report = audit.analyze_workflow_roots([root], limits=limits)
    root_report = _roots(report)[0]

    assert root_report["filesDiscovered"] == EXPECTED_THREE
    assert root_report["filesParsed"] == 0
    assert root_report["filesSkipped"] == EXPECTED_THREE
    assert root_report["issueCounts"] == {
        "json_depth_limit_exceeded": 1,
        "workflow_file_size_limit_exceeded": 1,
        "workflow_json_invalid": 1,
    }
    assert report["nodeOccurrences"] == 0
    assert report["observedNodeClasses"] == 0


def test_node_limit_discards_partial_file_observations(tmp_path: Path) -> None:
    root = tmp_path / "node-limit"
    _write_json(
        root / "many.json",
        {
            "1": {"class_type": "KSampler", "inputs": {"steps": 10}},
            "2": {"class_type": "VAELoader", "inputs": {"vae_name": "DO_NOT_RECORD"}},
        },
    )
    limits = audit.WorkflowAuditLimits(max_nodes_per_file=1)

    report = audit.analyze_workflow_roots([root], limits=limits)

    assert _roots(report)[0]["issueCounts"] == {"workflow_node_limit_exceeded": 1}
    assert report["nodeOccurrences"] == 0
    assert report["observedNodeClasses"] == 0


def test_unsafe_nodes_still_count_toward_strict_node_limit(tmp_path: Path) -> None:
    root = tmp_path / "unsafe-node-limit"
    _write_json(
        root / "many.json",
        {
            "1": {
                "class_type": "unsafe/class",
                "inputs": {"prompt": "DO_NOT_RECORD"},
            },
            "2": {"class_type": "KSampler", "inputs": {"steps": 10}},
        },
    )
    limits = audit.WorkflowAuditLimits(max_nodes_per_file=1)

    report = audit.analyze_workflow_roots([root], limits=limits)

    assert _roots(report)[0]["issueCounts"] == {
        "unsafe_class_name_omitted": 1,
        "workflow_node_limit_exceeded": 1,
    }
    assert report["nodeOccurrences"] == 0
    assert report["observedNodeClasses"] == 0
    assert "DO_NOT_RECORD" not in json.dumps(report)


def test_shape_count_is_bounded_and_reports_truncation(tmp_path: Path) -> None:
    root = tmp_path / "shapes"
    for index, input_name in enumerate(("seed", "steps", "cfg"), start=1):
        _write_json(
            root / f"{index}.json",
            {
                "1": {
                    "class_type": "CustomSampler",
                    "inputs": {input_name: index},
                }
            },
        )
    limits = audit.WorkflowAuditLimits(max_shapes_per_class=2)

    report = audit.analyze_workflow_roots([root], limits=limits)
    sampler = _record(report, "CustomSampler")

    assert sampler["count"] == EXPECTED_THREE
    assert len(sampler["inputShapes"]) == EXPECTED_TWO
    assert sampler["truncatedInputShapeCount"] == 1


def test_parser_accepts_repeatable_workflow_roots() -> None:
    args = audit._parser().parse_args(
        [
            "--workflow-root",
            "first",
            "--workflow-root",
            "second",
        ]
    )

    assert args.workflow_root == [Path("first"), Path("second")]


def test_report_privacy_contract_is_explicit(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    args = audit._parser().parse_args(["--workflow-root", str(root)])

    report = audit._build_report(args)

    assert report["schemaVersion"] == "2.2.0"
    assert report["privacy"] == {
        "classNamesOnly": True,
        "genericWorkflowRootLabels": True,
        "inputValuesRecorded": False,
        "pathsRecorded": False,
        "promptsRecorded": False,
        "workflowFileNamesRecorded": False,
    }
    assert str(root) not in json.dumps(report)


def test_build_report_requires_at_least_one_source() -> None:
    args = audit._parser().parse_args([])

    with pytest.raises(ValueError, match="at_least_one_audit_source_required"):
        audit._build_report(args)
