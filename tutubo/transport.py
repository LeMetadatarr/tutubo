"""Pluggable HTTP transport layer.

Provides a single :func:`default_session` factory. When
``TUTUBO_TRANSPORT=curl_cffi`` and ``curl_cffi`` is importable it returns a
``curl_cffi.requests.Session`` impersonating Chrome. Otherwise it returns an
``unblock_requests.CloudflareSession`` when that package is importable, and a
plain ``requests.Session`` as a final fallback. All variants are drop-in
``requests.Session`` instances (install extras via ``pip install
tutubo[stealth]``).

The curl_cffi transport mimics real-browser TLS/HTTP fingerprints and
``CloudflareSession`` adds anti-bot routing with a Wayback fallback, both of
which help evade bot detection on YouTube channel HTML pages.

Note: ``tutubo._innertube._post`` uses stdlib ``urllib.request`` and is
intentionally outside this abstraction — sessions injected here do not
apply to that path.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_TRANSPORT_ENV = "TUTUBO_TRANSPORT"


def _curl_cffi_session() -> Any:
    """Return a new ``curl_cffi.requests.Session`` impersonating Chrome."""
    from curl_cffi import requests as cffi_requests  # type: ignore
    # ``impersonate`` picks a realistic TLS/JA3 fingerprint.
    return cffi_requests.Session(impersonate="chrome")


def default_session() -> Any:
    """Return a fresh HTTP session honoring ``TUTUBO_TRANSPORT``.

    - If ``TUTUBO_TRANSPORT=curl_cffi`` and ``curl_cffi`` is importable,
      returns a curl_cffi session impersonating Chrome.
    - Otherwise returns a stdlib ``requests.Session``.
    """
    transport = os.environ.get(_TRANSPORT_ENV, "").strip().lower()
    if transport == "curl_cffi":
        try:
            return _curl_cffi_session()
        except ImportError:
            logger.warning(
                "TUTUBO_TRANSPORT=curl_cffi but curl_cffi is not installed; "
                "falling back to requests. Install with `pip install tutubo[stealth]`."
            )
    try:
        from unblock_requests import CloudflareSession

        return CloudflareSession(env_prefix="TUTUBO", wayback_fallback=True)
    except Exception:
        import requests

        return requests.Session()
