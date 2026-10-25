"""Internal utilities — URL parsing, HTML extraction, lazy list."""
from __future__ import annotations

import ast
import json
import logging
import re
import urllib.parse
from typing import Any, Iterator, List, Optional
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
    if not html or html[0] not in ('{', '['):
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


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------

_CLOCK_RE = re.compile(r"^\s*(?:(\d{1,3})[:.])?(\d{1,3})[:.](\d{2})\s*$")
_BARE_RE = re.compile(r"^\s*(\d{1,7})\s*$")
MAX_DURATION_SECONDS = 1_000_000


def _bounded(seconds: int) -> Optional[int]:
    return seconds if 0 <= seconds < MAX_DURATION_SECONDS else None


def parse_duration(text: Any, allow_bare: bool = False) -> Optional[int]:
    """Convert a clock label (``"H:MM:SS"`` or ``"M:SS"``) to seconds.

    Some locales print ``"13.28"``; ``.`` is accepted as the separator. Minutes
    and seconds below an hours or minutes field must be under 60. Bare seconds
    (``"30"``) are accepted only with ``allow_bare``. Returns ``None`` for
    anything else, e.g. ``"LIVE"``, ``"UPCOMING"``, an empty value, or a value of
    ``MAX_DURATION_SECONDS`` or more.
    """
    if not isinstance(text, str):
        return None
    m = _CLOCK_RE.match(text)
    if m:
        h, mi, sec = m.groups()
        if int(sec) > 59 or (h is not None and int(mi) > 59):
            return None
        return _bounded(int(h or 0) * 3600 + int(mi) * 60 + int(sec))
    if allow_bare:
        m = _BARE_RE.match(text)
        if m:
            return _bounded(int(m.group(1)))
    return None


def _text_of(node: Any) -> Optional[str]:
    if isinstance(node, dict):
        return node.get("simpleText")
    return None


def duration_from_item(item: dict) -> Optional[int]:
    """Duration in seconds of a listing item, or ``None`` when it has none.

    Accepts a ``richItemRenderer`` wrapper or the bare renderer, and reads
    ``playlistVideoRenderer.lengthSeconds``, ``videoRenderer.lengthText`` (or its
    time-status overlay) and the badge on a ``lockupViewModel`` thumbnail.
    """
    content = item.get("richItemRenderer", {}).get("content", item)

    prv = content.get("playlistVideoRenderer")
    if prv:
        try:
            return _bounded(int(prv["lengthSeconds"]))
        except (KeyError, TypeError, ValueError):
            return parse_duration(_text_of(prv.get("lengthText")))

    vr = content.get("videoRenderer")
    if vr:
        seconds = parse_duration(_text_of(vr.get("lengthText")))
        if seconds is not None:
            return seconds
        for overlay in vr.get("thumbnailOverlays", []):
            status = overlay.get("thumbnailOverlayTimeStatusRenderer")
            if status:
                return parse_duration(_text_of(status.get("text")))
        return None

    lvm = content.get("lockupViewModel")
    if lvm:
        overlays = (lvm.get("contentImage", {}).get("thumbnailViewModel", {})
                    .get("overlays", []))
        for overlay in overlays:
            bottom = overlay.get("thumbnailBottomOverlayViewModel")
            for badge in (bottom or {}).get("badges", []):
                seconds = parse_duration(
                    badge.get("thumbnailBadgeViewModel", {}).get("text"))
                if seconds is not None:
                    return seconds
    return None


def player_response(html: str) -> dict:
    """Extract ``ytInitialPlayerResponse`` from a YouTube watch page."""
    for m in re.finditer(r"ytInitialPlayerResponse\s*=\s*", html):
        try:
            obj = _parse_object(html, m.end())
        except _HTMLParseError:
            continue
        if isinstance(obj, dict):
            return obj
    raise _HTMLParseError("ytInitialPlayerResponse not found in page HTML")
