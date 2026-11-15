from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import cast

import pytest

from civiscribe.adapters import http_api
from civiscribe.api import API_PREFIX, MAX_REQUEST_BYTES

# Windows creates a loopback socket pair for asyncio; no external hosts are allowed.
pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])
NODE_ID = "CCollins_CiviScribe_SaveImage"
ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Body:
    chunks: tuple[bytes, ...] = ()
    consumed: int = 0

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk


@dataclass
class Request:
    content_type: str = "application/json"
    content_length: int | None = None
    content: Body = field(default_factory=Body)


@dataclass
class Response:
    text: str
    status: int
    content_type: str
    headers: Mapping[str, str]


class Routes:
    def __init__(self) -> None:
        self.handlers: dict[tuple[str, str], http_api.Handler] = {}

    def _register(self, method: str, path: str) -> Callable[[http_api.Handler], http_api.Handler]:
        def decorate(handler: http_api.Handler) -> http_api.Handler:
            assert (method, path) not in self.handlers
            self.handlers[method, path] = handler
            return handler

        return decorate

    def get(self, path: str) -> Callable[[http_api.Handler], http_api.Handler]:
        return self._register("GET", path)

    def post(self, path: str) -> Callable[[http_api.Handler], http_api.Handler]:
        return self._register("POST", path)


def call(method: str, path: str, request: Request) -> Response:
    routes = Routes()
    http_api.register_routes(routes, Response, node_id=NODE_ID)
    assert set(routes.handlers) == {
        ("GET", f"{API_PREFIX}/capabilities"),
        ("GET", f"{API_PREFIX}/openapi.json"),
        ("POST", f"{API_PREFIX}/preflight"),
    }

    async def invoke() -> object:
        return await routes.handlers[method, f"{API_PREFIX}/{path}"](request)

    return cast(Response, asyncio.run(invoke()))


@pytest.mark.parametrize("path", ["capabilities", "openapi.json"])
def test_get_routes_are_read_only_json_with_no_store_headers(path: str) -> None:
    result = call("GET", path, Request())
    assert result.status == HTTPStatus.OK
    assert result.content_type == "application/json"
    assert result.headers == {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    assert isinstance(json.loads(result.text), dict)


def test_preflight_accepts_streamed_bodies_without_content_length() -> None:
    payload = (ROOT / "docs/examples/save-demo-api.json").read_bytes()
    result = call("POST", "preflight", Request(content=Body((payload[:20], payload[20:]))))
    assert result.status == HTTPStatus.OK
    assert json.loads(result.text)["committed"] is False


@pytest.mark.parametrize(
    "body_request,code,status",
    [
        (Request(content_type="text/plain"), "application_json_required", 415),
        (Request(content_length=MAX_REQUEST_BYTES + 1), "request_too_large", 413),
        (
            Request(content=Body((b" " * MAX_REQUEST_BYTES, b"x", b"never read"))),
            "request_too_large",
            413,
        ),
        (Request(content=Body((b"{",))), "invalid_json", 400),
        (Request(content=Body((b"{}",))), "prompt_object_required", 400),
    ],
)
def test_route_rejects_unsafe_bodies_without_echoing_them(
    body_request: Request, code: str, status: int
) -> None:
    result = call("POST", "preflight", body_request)
    assert result.status == status
    assert json.loads(result.text) == {"error": {"code": code}}
    assert b"never read" not in body_request.content.chunks[: body_request.content.consumed]


def test_internal_preflight_failures_have_sanitized_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_payload: object, *, node_id: str) -> dict[str, object]:
        raise RuntimeError("private server detail")

    monkeypatch.setattr(http_api, "preflight", fail)
    result = call("POST", "preflight", Request(content=Body((b"{}",))))
    assert result.status == HTTPStatus.INTERNAL_SERVER_ERROR
    assert json.loads(result.text) == {"error": {"code": "preflight_unavailable"}}
    assert "private server detail" not in result.text
