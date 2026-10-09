"""Internal utilities — URL parsing, HTML extraction, lazy list."""
from __future__ import annotations

import ast
import json
import logging
import re
import urllib.parse
from typing import Any, Iterator, List
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def video_id(url: str) -> str:
    """Extract the 11-character video ID from a YouTube URL."""
    m = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    if not m:
        raise ValueError(f"Could not extract video_id from: {url}")
    return m.group(1)


def playlist_id(url: str) -> str:
    """Extract the playlist ID from a YouTube playlist URL."""
    parsed = urllib.parse.urlparse(url)
    ids = parse_qs(parsed.query).get('list', [])
    if not ids:
        raise ValueError(f"No playlist ID found in URL: {url}")
    return ids[0]


def channel_name(url: str) -> str:
    """Return the canonical channel URI path (e.g. ``/@LofiGirl`` or ``/c/name``)."""
    pattern = r"(?:https?://)?(?:www\.)?youtube\.com/(?:(user|channel|c)(?:/))?@?([%\d\w_\-]+)"
    m = re.search(pattern, url)
    if not m:
        raise ValueError(f"Could not parse channel URL: {url}")
    style, identifier = m.group(1), m.group(2)
    if "@" in url:
        return f"/@{identifier}"
    return f"/{style or 'c'}/{identifier}"


# ---------------------------------------------------------------------------
# HTML → JSON extraction
# ---------------------------------------------------------------------------

class _HTMLParseError(Exception):
    pass


def _find_object_from_startpoint(html: str, start: int) -> str:
    """Return the JS object/array literal starting at ``start`` in ``html``."""
    html = html[start:]
    if html[0] not in ('{', '['):
        raise _HTMLParseError(f"Invalid start: {html[:20]!r}")
    closers = {'{': '}', '[': ']', '"': '"', '/': '/'}
    stack = [html[0]]
    last = '{'
    curr = None
    i = 1
    while i < len(html) and stack:
        if curr not in (' ', '\n'):
            last = curr
        curr = html[i]
        ctx = stack[-1]
        if curr == closers[ctx]:
            stack.pop()
            i += 1
            continue
        if ctx in ('"', '/'):
            if curr == '\\':
                i += 2
                continue
        else:
            if curr in closers:
                if not (curr == '/' and last not in ('(', ',', '=', ':', '[', '!', '&', '|', '?', '{', '}', ';')):
                    stack.append(curr)
        i += 1
    return html[:i]


def _parse_object(html: str, start: int) -> Any:
    """Parse the JS literal at ``start`` as JSON, falling back to a Python literal."""
    raw = _find_object_from_startpoint(html, start)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError) as exc:
            raise _HTMLParseError("Could not parse object") from exc


def initial_data(html: str) -> dict:
    """Extract ``ytInitialData`` from a YouTube page."""
    for pattern in (r"window\[['\"]ytInitialData['\"]\]\s*=\s*", r"ytInitialData\s*=\s*"):
        m = re.search(pattern, html)
        if m:
            try:
                return _parse_object(html, m.end())
            except _HTMLParseError:
                continue
    raise _HTMLParseError("ytInitialData not found in page HTML")


def get_ytcfg(html: str) -> dict:
    """Extract the ``ytcfg`` object from a YouTube page."""
    result = {}
    for pattern in (r"ytcfg\s=\s", r"ytcfg\.set\("):
        for m in re.finditer(pattern, html):
            try:
                result.update(_parse_object(html, m.end()))
            except _HTMLParseError:
                continue
    if result:
        return result
    raise _HTMLParseError("ytcfg not found in page HTML")


# ---------------------------------------------------------------------------
# Lazy list
# ---------------------------------------------------------------------------

class DeferredGeneratorList:
    """Wraps a generator so elements are fetched only as needed.

    Supports indexing, slicing, iteration and len(). Negative indexing or
    slicing forces full materialisation of the underlying generator.
    """

    def __init__(self, generator: Iterator[Any]) -> None:
        self.gen: Iterator[Any] = generator
        self._elements: List[Any] = []

    def _fetch_up_to(self, index: int) -> None:
        """Pull from the generator until ``_elements`` covers ``index``."""
        while len(self._elements) <= index:
            try:
                self._elements.append(next(self.gen))
            except StopIteration:
                break

    def _fetch_all(self) -> None:
        """Drain the generator into ``_elements``."""
        for item in self.gen:
            self._elements.append(item)
        self.gen = iter([])

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            if key >= 0:
                self._fetch_up_to(key)
            else:
                self._fetch_all()
            return self._elements[key]
        if isinstance(key, slice):
            self._fetch_all()
            return self._elements[key]
        raise TypeError(f"Invalid key type: {type(key)}")

    def __iter__(self) -> Iterator[Any]:
        i = 0
        while True:
            self._fetch_up_to(i)
            if i >= len(self._elements):
                return
            yield self._elements[i]
            i += 1

    def __len__(self) -> int:
        self._fetch_all()
        return len(self._elements)

    def __repr__(self) -> str:
        self._fetch_all()
        return repr(self._elements)

    def __eq__(self, other: object) -> bool:
        return list(self) == other
