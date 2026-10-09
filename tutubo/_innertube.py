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
from urllib import error as urllib_error, parse, request as urllib_request

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


def _post(endpoint: str, params: dict, body: dict) -> dict:
    """POST to a YouTube innertube endpoint and return the parsed JSON response.

    NOTE: this path uses stdlib ``urllib.request`` directly and therefore
    bypasses :func:`tutubo.transport.default_session` — sessions injected
    elsewhere (e.g. into ``Channel`` / ``Playlist``) do not apply here, and
    the ``TUTUBO_TRANSPORT=curl_cffi`` env var has no effect on this call.
    """
    url = f"{_BASE_URL}/{endpoint}?{parse.urlencode(params)}"
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, headers=_HEADERS, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib_error.HTTPError as e:
        raise RuntimeError(f"YouTube API returned HTTP {e.code} for {endpoint}") from e
    except urllib_error.URLError as e:
        raise RuntimeError(f"Network error calling YouTube API: {e.reason}") from e
    if _RECORD_DIR:
        query = body.get("query") or params.get("query") or body.get("continuation", "continuation")
        safe = re.sub(r"[^\w]", "_", query.lower())[:60]
        _save_fixture(f"{endpoint}_{safe}", result)
    return result


def search(query: str, continuation: Optional[str] = None) -> dict:
    """Call the innertube search endpoint and return the raw JSON."""
    params = {"key": _API_KEY, "contentCheckOk": True, "racyCheckOk": True}
    body: dict = {"context": _CONTEXT}
    if continuation:
        body["continuation"] = continuation
    else:
        body["query"] = query
        params["query"] = query
    return _post("search", params, body)
