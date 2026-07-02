"""Diagnose verified HTTPS access to Civitai lookup endpoints.

Run this with the same Python executable/environment that launches ComfyUI.
The script sends only public hash/modelVersionId lookup requests.
"""

from __future__ import annotations

import json
import ssl
import sys
import time
from dataclasses import dataclass
from urllib import parse, request

ENDPOINTS = (
    ("by_hash", "https://civitai.com/api/v1/model-versions/by-hash/09d005300d"),
    ("by_model_version", "https://civitai.com/api/v1/model-versions/2734704"),
)
TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class CertifiInfo:
    installed: bool
    path: str | None = None
    error: str | None = None


def main() -> int:
    certifi_info = _certifi_info()
    print(f"python_executable: {sys.executable}")
    print(f"python_version: {sys.version.split()[0]}")
    print(f"openssl_version: {ssl.OPENSSL_VERSION}")
    print(f"certifi_installed: {'yes' if certifi_info.installed else 'no'}")
    if certifi_info.path:
        print(f"certifi_path: {certifi_info.path}")
    if certifi_info.error:
        print(f"certifi_error: {_safe_text(certifi_info.error)}")

    contexts = [("urllib_default", ssl.create_default_context())]
    if certifi_info.installed and certifi_info.path:
        contexts.append(("urllib_certifi", ssl.create_default_context(cafile=certifi_info.path)))

    for endpoint_kind, url in ENDPOINTS:
        for method, context in contexts:
            _run_check(endpoint_kind=endpoint_kind, url=url, method=method, context=context)
    return 0


def _run_check(*, endpoint_kind: str, url: str, method: str, context: ssl.SSLContext) -> None:
    path = _url_path_only(url)
    start = time.perf_counter()
    status = "none"
    success = "no"
    exception_class = ""
    exception_message = ""
    try:
        req = request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ComfyUI-Civitai-Save-Node/diagnostic",
            },
            method="GET",
        )
        with request.urlopen(req, timeout=TIMEOUT_SECONDS, context=context) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            status = str(int(response.status))
            success = "yes" if 200 <= int(response.status) < 300 and _looks_like_json(body) else "no"
    except Exception as exc:  # noqa: BLE001 - diagnostics should report any safe exception.
        exception_class = exc.__class__.__name__
        exception_message = _safe_text(str(exc))
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    print(
        json.dumps(
            {
                "endpointKind": endpoint_kind,
                "endpointPath": path,
                "clientMethod": method,
                "httpStatus": status,
                "success": success,
                "exceptionClass": exception_class,
                "exceptionMessage": exception_message,
                "elapsedMs": elapsed_ms,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _certifi_info() -> CertifiInfo:
    try:
        import certifi  # type: ignore

        path = certifi.where()
        return CertifiInfo(installed=bool(path), path=path or None)
    except Exception as exc:  # noqa: BLE001 - optional dependency probe.
        return CertifiInfo(installed=False, error=str(exc))


def _looks_like_json(body: bytes) -> bool:
    try:
        json.loads(body.decode("utf-8"))
        return True
    except Exception:
        return False


def _url_path_only(url: str) -> str:
    parsed = parse.urlparse(url)
    return parsed.path


def _safe_text(value: str) -> str:
    text = value.replace("\x00", "").replace("\r", " ").replace("\n", " ")
    for marker in ("token=", "api_key=", "apikey=", "authorization:"):
        lowered = text.lower()
        index = lowered.find(marker)
        if index >= 0:
            text = text[: index + len(marker)] + "<redacted>"
    return text[:240]


if __name__ == "__main__":
    raise SystemExit(main())
