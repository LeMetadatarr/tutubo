"""Thin innertube API client — search endpoint only.

Wraps the unauthenticated `/youtubei/v1/search` endpoint. Set
``TUTUBO_RECORD_DIR`` to capture raw responses as JSON fixtures.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from typing import Optional
import requests
from urllib import error as urllib_error, parse, request as urllib_request

from tutubo import backoff

logger = logging.getLogger(__name__)

_RECORD_DIR = os.environ.get("TUTUBO_RECORD_DIR")


def _save_fixture(slug: str, result: dict) -> None:
    """Write a raw API response to TUTUBO_RECORD_DIR as a JSON fixture."""
    out = pathlib.Path(_RECORD_DIR)
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", slug)[:80]
    path = out / f"{safe}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    logger.info("fixture saved: %s", path)


_BASE_URL = "https://www.youtube.com/youtubei/v1"
_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
_CONTEXT = {
    "client": {
        "clientName": "WEB",
        "clientVersion": "2.20200720.00.02",
    }
}
_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}


_HTTP_ERRORS: tuple = (requests.HTTPError,)
_REQUEST_ERRORS: tuple = (requests.RequestException,)
try:  # curl_cffi sessions raise their own exception hierarchy
    from curl_cffi.requests import exceptions as _cffi_exc

    _HTTP_ERRORS += (_cffi_exc.HTTPError,)
    _REQUEST_ERRORS += (_cffi_exc.RequestException,)
except ImportError:
    pass


def _post(endpoint: str, params: dict, body: dict, session: Optional[object] = None) -> dict:
    """POST to a YouTube innertube endpoint and return the parsed JSON response.

    Without ``session`` this uses stdlib ``urllib.request`` directly, so
    ``TUTUBO_TRANSPORT`` has no effect on the call. With a ``requests``-style
    ``session`` the request goes through it (e.g. one pinned to an IP family).
    """
    backoff.check("search")
    url = f"{_BASE_URL}/{endpoint}?{parse.urlencode(params)}"
    data = json.dumps(body).encode()
    if session is not None:
        try:
            resp = session.post(url, data=data, headers=_HEADERS, timeout=30)
            resp.raise_for_status()
            result = resp.json()
        except _HTTP_ERRORS as e:
            code = getattr(getattr(e, "response", None), "status_code", None) or "error"
            backoff.failed("search", f"HTTP {code}")
            raise RuntimeError(f"YouTube API returned HTTP {code} for {endpoint}") from e
        except _REQUEST_ERRORS as e:
            raise RuntimeError(f"Network error calling YouTube API: {e}") from e
    else:
        req = urllib_request.Request(url, data=data, headers=_HEADERS, method="POST")
        try:
            with urllib_request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
        except urllib_error.HTTPError as e:
            backoff.failed("search", f"HTTP {e.code}")
            raise RuntimeError(f"YouTube API returned HTTP {e.code} for {endpoint}") from e
        except urllib_error.URLError as e:
            raise RuntimeError(f"Network error calling YouTube API: {e.reason}") from e
    backoff.after_success("search")
    if _RECORD_DIR:
        query = body.get("query") or params.get("query") or body.get("continuation", "continuation")
        safe = re.sub(r"[^\w]", "_", query.lower())[:60]
        _save_fixture(f"{endpoint}_{safe}", result)
    return result


def search(query: str, continuation: Optional[str] = None,
           session: Optional[object] = None) -> dict:
    """Call the innertube search endpoint and return the raw JSON."""
    params = {"key": _API_KEY, "contentCheckOk": True, "racyCheckOk": True}
    body: dict = {"context": _CONTEXT}
    if continuation:
        body["continuation"] = continuation
    else:
        body["query"] = query
        params["query"] = query
    if session is not None:
        return _post("search", params, body, session=session)
    return _post("search", params, body)
