"""Thin routes on ComfyUI's existing HTTP server; no listener or job store."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Protocol

from ..api import (
    API_PREFIX,
    MAX_REQUEST_BYTES,
    ApiError,
    capabilities,
    openapi_document,
    parse_request,
    preflight,
)
from ..serialization import dumps_json


class RequestBody(Protocol):
    def iter_chunked(self, size: int) -> AsyncIterator[bytes]: ...


class ApiRequest(Protocol):
    @property
    def content_type(self) -> str: ...
    @property
    def content_length(self) -> int | None: ...
    @property
    def content(self) -> RequestBody: ...


type Handler = Callable[[ApiRequest], Awaitable[object]]


class Routes(Protocol):
    def get(self, path: str) -> Callable[[Handler], Handler]: ...
    def post(self, path: str) -> Callable[[Handler], Handler]: ...


class ResponseFactory(Protocol):
    def __call__(
        self, *, text: str, status: int, content_type: str, headers: Mapping[str, str]
    ) -> object: ...


def register_routes(routes: Routes, response: ResponseFactory, *, node_id: str) -> None:
    """Register once from the native V3 extension's on_load lifecycle hook."""

    def respond(payload: object, status: int = 200) -> object:
        return response(
            text=dumps_json(payload),
            status=status,
            content_type="application/json",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @routes.get(f"{API_PREFIX}/capabilities")
    async def get_capabilities(_request: ApiRequest) -> object:
        return respond(capabilities(node_id))

    @routes.get(f"{API_PREFIX}/openapi.json")
    async def get_openapi(_request: ApiRequest) -> object:
        return respond(openapi_document())

    @routes.post(f"{API_PREFIX}/preflight")
    async def post_preflight(request: ApiRequest) -> object:
        try:
            if request.content_type != "application/json":
                raise ApiError("application_json_required", 415)
            if request.content_length is not None and request.content_length > MAX_REQUEST_BYTES:
                raise ApiError("request_too_large", 413)
            body = bytearray()
            async for chunk in request.content.iter_chunked(64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_REQUEST_BYTES:
                    raise ApiError("request_too_large", 413)
            payload = parse_request(bytes(body))
            result = await asyncio.to_thread(preflight, payload, node_id=node_id)
            return respond(result)
        except ApiError as exc:
            return respond({"error": {"code": exc.code}}, exc.status)
        except Exception:
            # Failed preflight cannot disclose payloads, paths, or server exception text.
            return respond({"error": {"code": "preflight_unavailable"}}, 500)
