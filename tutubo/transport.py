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

An optional address family (``"ipv4"`` or ``"ipv6"``) pins every connection a
session opens to one IP family. It is carried by the session's own adapters,
never by process-wide state, so other HTTP users in the process and other
threads are unaffected. :func:`set_default_family` sets the family used when no
explicit one is given.

Note: ``tutubo._innertube._post`` uses stdlib ``urllib.request`` unless a
session is passed to it; ``YoutubeSearch`` passes one whenever a session or
family is configured.
"""
from __future__ import annotations

import logging
import os
import socket
from typing import Any, Optional, Union

from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

_TRANSPORT_ENV = "TUTUBO_TRANSPORT"


# A socket bound to the wildcard address of one family cannot connect over the
# other, so urllib3 skips every address of the wrong family when resolving.
_SOURCE_ADDRESSES = {"ipv4": ("0.0.0.0", 0), "ipv6": ("::", 0)}

_default_family: Optional[str] = None


def normalize_family(family: Union[str, int, None]) -> Optional[str]:
    """Return ``"ipv4"``, ``"ipv6"`` or ``None`` (any family) for ``family``.

    Accepts ``None`` / ``"any"``, ``"ipv4"`` / ``"ipv6"`` (case-insensitive)
    and ``socket.AF_INET`` / ``socket.AF_INET6``.
    """
    if family is None:
        return None
    if family == socket.AF_INET:
        return "ipv4"
    if family == socket.AF_INET6:
        return "ipv6"
    if isinstance(family, str):
        name = family.strip().lower()
        if name == "any":
            return None
        if name in _SOURCE_ADDRESSES:
            return name
    raise ValueError(
        f"unknown address family {family!r}; use 'ipv4', 'ipv6' or None")


def set_default_family(family: Union[str, int, None]) -> None:
    """Set the family used by sessions created without an explicit ``family``.

    ``None`` restores unrestricted resolution. Applies to sessions created
    after the call.
    """
    global _default_family
    _default_family = normalize_family(family)


def get_default_family() -> Optional[str]:
    """Return the module-level default family (``None`` when unset)."""
    return _default_family


def resolve_family(family: Union[str, int, None] = None) -> Optional[str]:
    """Return ``family`` normalised, or the module default when ``family`` is None.

    ``"any"`` opts out of the module default for one object.
    """
    if family is None:
        return _default_family
    return normalize_family(family)


class FamilyAdapter(HTTPAdapter):
    """``HTTPAdapter`` whose connections use one IP family only."""

    __attrs__ = HTTPAdapter.__attrs__ + ["_source_address"]

    def __init__(self, family: str, *args: Any, **kwargs: Any) -> None:
        self._source_address = _SOURCE_ADDRESSES[family]
        super().__init__(*args, **kwargs)

    def _v6only(self, kwargs: dict) -> None:
        # keep a v4-mapped literal (::ffff:a.b.c.d) from reaching IPv4
        if self._source_address[0] == "::":
            from urllib3.connection import HTTPConnection
            kwargs["socket_options"] = HTTPConnection.default_socket_options + [
                (socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)]

    def init_poolmanager(self, *args: Any, **pool_kwargs: Any) -> None:
        pool_kwargs["source_address"] = self._source_address
        self._v6only(pool_kwargs)
        super().init_poolmanager(*args, **pool_kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        proxy_kwargs["source_address"] = self._source_address
        self._v6only(proxy_kwargs)
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _curl_cffi_session(family: Optional[str] = None) -> Any:
    """Return a new ``curl_cffi.requests.Session`` impersonating Chrome.

    ``family`` restricts name resolution and the local bind address to that
    family for this session only.
    """
    from curl_cffi import requests as cffi_requests  # type: ignore
    # ``impersonate`` picks a realistic TLS/JA3 fingerprint.
    if family is None:
        return cffi_requests.Session(impersonate="chrome")
    from curl_cffi.const import CurlIpResolve, CurlOpt  # type: ignore
    v4 = family == "ipv4"
    # IPRESOLVE restricts name resolution; binding the local address makes the
    # kernel refuse any other-family target however it is written, redirects
    # included. Redirects are limited to http(s).
    return cffi_requests.Session(impersonate="chrome", curl_options={
        CurlOpt.IPRESOLVE: CurlIpResolve.V4 if v4 else CurlIpResolve.V6,
        CurlOpt.INTERFACE: "host!0.0.0.0" if v4 else "host!::",
        CurlOpt.PROTOCOLS_STR: "http,https",
        CurlOpt.REDIR_PROTOCOLS_STR: "http,https",
    })


def make_session(family: Union[str, int, None] = None) -> Any:
    """Return a fresh HTTP session honoring ``TUTUBO_TRANSPORT`` and ``family``.

    - ``family`` ``"ipv4"`` / ``"ipv6"`` restricts every connection of the
      session to that IP family; ``None`` uses :func:`set_default_family`'s
      value (unrestricted unless set); ``"any"`` forces unrestricted.
    - With no family in effect: if ``TUTUBO_TRANSPORT=curl_cffi`` and
      ``curl_cffi`` is importable, returns a curl_cffi session impersonating
      Chrome; otherwise a ``CloudflareSession`` or ``requests.Session``.
    - With a family in effect, curl_cffi sessions are pinned through curl's
      IP resolve option and ``requests`` sessions through :class:`FamilyAdapter`.
      ``CloudflareSession`` keeps its curl_cffi fast path (pinned the same way)
      but loses its Wayback / solver / proxy fallbacks, which would leave the
      pinned family.
    """
    fam = resolve_family(family)
    transport = os.environ.get(_TRANSPORT_ENV, "").strip().lower()
    if transport == "curl_cffi":
        try:
            return _curl_cffi_session(fam)
        except ImportError:
            logger.warning(
                "TUTUBO_TRANSPORT=curl_cffi but curl_cffi is not installed; "
                "falling back to requests. Install with `pip install tutubo[stealth]`."
            )
    try:
        from unblock_requests import CloudflareSession
    except Exception:
        import requests

        session = requests.Session()
    else:
        # A pinned CloudflareSession keeps its curl_cffi fast path (pinned
        # through curl) and turns its Wayback / solver / proxy fallbacks off.
        if fam is None:
            return CloudflareSession(env_prefix="TUTUBO", wayback_fallback=True)
        return CloudflareSession(env_prefix="TUTUBO", ip_family=fam)
    if fam is not None:
        adapter = FamilyAdapter(fam)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    return session


def default_session() -> Any:
    """Return a fresh HTTP session honoring ``TUTUBO_TRANSPORT`` and the default family."""
    return make_session()
