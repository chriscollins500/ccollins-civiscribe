"""Verified HTTPS trust contexts shared by runtime and standalone tools."""

from __future__ import annotations

import ssl
from typing import Any

_certifi_provider: Any | None
try:
    import certifi
except ImportError:  # pragma: no cover - dependency-minimal platforms
    _certifi_provider = None
else:
    _certifi_provider = certifi

_truststore_provider: Any | None
try:
    import truststore
except ImportError:  # pragma: no cover - dependency availability is platform-specific
    _truststore_provider = None
else:  # pragma: no cover - dependency availability is platform-specific
    _truststore_provider = truststore


def _tls_minimum(context: ssl.SSLContext) -> ssl.SSLContext:
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def create_tls_contexts() -> tuple[tuple[str, ssl.SSLContext], ...]:
    """Return verified trust contexts in system, truststore, certifi order."""

    contexts: list[tuple[str, ssl.SSLContext]] = [
        ("system_default", _tls_minimum(ssl.create_default_context()))
    ]
    try:
        if _truststore_provider is None:
            raise ImportError
        contexts.append(
            ("truststore", _tls_minimum(_truststore_provider.SSLContext(ssl.PROTOCOL_TLS_CLIENT)))
        )
    except (ImportError, AttributeError, ssl.SSLError):
        pass
    try:
        if _certifi_provider is None:
            raise ImportError
        context = ssl.create_default_context(cafile=_certifi_provider.where())
        contexts.append(("certifi", _tls_minimum(context)))
    except (ImportError, AttributeError, OSError, ssl.SSLError):
        pass
    return tuple(contexts)
