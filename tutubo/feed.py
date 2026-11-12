"""A channel's upload feed: one request per channel.

YouTube serves the latest uploads of a channel as an Atom feed
(``/feeds/videos.xml?channel_id=...``), about fifteen entries in one small
response. :func:`channel_feed` reads it and :func:`refresh_channel` compares it
with the video ids a caller already knows, so a full channel listing is needed
only when the feed holds an id that is new. The request is a ``feed`` request
of the shared back-off (:mod:`tutubo.backoff`).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional
from xml.etree import ElementTree
from xml.parsers import expat

from tutubo import backoff
from tutubo.fetch import plain_session

FEED_URL = "https://www.youtube.com/feeds/videos.xml"
MAX_BYTES = 2_000_000
ERROR_BYTES = 65536
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
       "m": "http://search.yahoo.com/mrss/"}


class FeedError(RuntimeError):
    """The feed could not be read: bad channel id, failed request, oversized or malformed answer."""


@dataclass(frozen=True)
class FeedEntry:
    video_id: str
    title: str
    channel_id: str
    channel: str
    published: str
    updated: str
    url: str
    thumbnail: str = ""
    description: str = ""
    views: Optional[int] = None


@dataclass(frozen=True)
class FeedUpdate:
    """``new`` holds the entries whose id the caller did not know, newest first. ``needs_listing`` is True when there are any:
    the feed holds only the latest uploads, so what lies between them and the known ones needs a full listing."""
    channel_id: str
    entries: List[FeedEntry]
    new: List[FeedEntry]

    @property
    def needs_listing(self) -> bool:
        return bool(self.new)


def _text(node: Optional[ElementTree.Element]) -> str:
    return (node.text or "").strip() if node is not None else ""


def _entry(node: ElementTree.Element) -> Optional[FeedEntry]:
    video_id = _text(node.find("yt:videoId", _NS))
    if not _VIDEO_ID.fullmatch(video_id):
        return None
    group = node.find("m:group", _NS)
    thumb = group.find("m:thumbnail", _NS) if group is not None else None
    stats = group.find("m:community/m:statistics", _NS) if group is not None else None
    views = stats.get("views") if stats is not None else None
    views = int(views) if views and views.isascii() and views.isdigit() and len(views) < 19 else None
    return FeedEntry(
        video_id=video_id, title=_text(node.find("a:title", _NS)),
        channel_id=_text(node.find("yt:channelId", _NS)), channel=_text(node.find("a:author/a:name", _NS)),
        published=_text(node.find("a:published", _NS)), updated=_text(node.find("a:updated", _NS)),
        url=f"https://www.youtube.com/watch?v={video_id}",
        thumbnail=thumb.get("url", "") if thumb is not None else "",
        description=_text(group.find("m:description", _NS)) if group is not None else "",
        views=views)


def _refuse_dtd(*_):
    raise FeedError("feed declares a DTD")


def parse_feed(body: bytes) -> List[FeedEntry]:
    """The entries of an Atom feed, in feed order. A document with a DOCTYPE or entity declaration, in any encoding, or whose
    root is not an Atom ``feed`` is refused."""
    if len(body) > MAX_BYTES:
        raise FeedError("feed is larger than the limit")
    scan = expat.ParserCreate()
    scan.StartDoctypeDeclHandler = _refuse_dtd
    scan.EntityDeclHandler = _refuse_dtd
    try:
        scan.Parse(body, True)
        root = ElementTree.fromstring(body)
    except (expat.ExpatError, ElementTree.ParseError, ValueError, LookupError) as e:
        raise FeedError(f"feed is not valid XML: {e}") from None
    if root.tag != "{%s}feed" % _NS["a"]:
        raise FeedError("not an Atom feed")
    return [e for e in map(_entry, root.findall("a:entry", _NS)) if e]


class _Failure:
    """A failed answer cut to ``ERROR_BYTES``, so the back-off can read its text without the rest of the body."""

    def __init__(self, response):
        self.status_code = response.status_code
        head = b""
        for chunk in response.iter_content(ERROR_BYTES):
            head = chunk[:ERROR_BYTES]
            break
        self.text = head.decode("utf-8", "replace")

    def raise_for_status(self):
        raise FeedError(f"feed request failed: {self.status_code}")


def channel_feed(channel_id: str, session: Optional[object] = None, family: Optional[str] = "ipv4",
                 timeout: float = 20) -> List[FeedEntry]:
    """The latest uploads of a channel, one request. Raises :class:`tutubo.backoff.BackedOff` while ``feed`` is paused or when
    YouTube asks for a check, :class:`FeedError` for anything else that goes wrong."""
    if not _CHANNEL_ID.fullmatch(channel_id or ""):
        raise FeedError(f"not a channel id: {channel_id!r}")
    backoff.check("feed")
    started = time.time()
    http = session or plain_session(family)
    try:
        response = http.get(FEED_URL, params={"channel_id": channel_id}, timeout=timeout, stream=True)
    except Exception as e:
        if backoff.failed("feed", e):
            raise backoff.paused("feed") from e
        raise FeedError(f"feed request failed: {type(e).__name__}") from None
    try:
        try:
            status = getattr(response, "status_code", 200)
            backoff.after("feed", _Failure(response) if isinstance(status, int) and status >= 400 else response, started)
        except backoff.BackedOff:
            raise
        except Exception:
            if backoff.enabled() and backoff.shared().blocked_until("feed"):
                raise backoff.paused("feed") from None
            raise FeedError(f"feed request failed: {getattr(response, 'status_code', '?')}") from None
        body = b""
        try:
            for chunk in response.iter_content(65536):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FeedError("feed is larger than the limit")
        except FeedError:
            raise
        except Exception as e:
            raise FeedError(f"feed read failed: {type(e).__name__}") from None
    finally:
        close = getattr(response, "close", None)
        if close:
            close()
    return parse_feed(body)


def refresh_channel(channel_id: str, known_ids: Iterable[str], session: Optional[object] = None,
                    family: Optional[str] = "ipv4") -> FeedUpdate:
    """Read the feed once and split off the entries not in ``known_ids``."""
    known = set(known_ids)
    entries = channel_feed(channel_id, session=session, family=family)
    return FeedUpdate(channel_id, entries, [e for e in entries if e.video_id not in known])


def main(argv: Optional[List[str]] = None) -> int:
    """``python -m tutubo.feed CHANNEL_ID...``: one JSON object per new entry on standard output; exit 75 on a pause, 1 on an error."""
    import argparse
    import json
    import sys
    parser = argparse.ArgumentParser(prog="python -m tutubo.feed", allow_abbrev=False)
    parser.add_argument("channels", nargs="+", help="channel ids (UC...)")
    parser.add_argument("--family", default="ipv4", choices=("ipv4", "ipv6", "any"))
    parser.add_argument("--known", action="append", default=[], help="a video id to leave out; repeatable")
    args = parser.parse_args(argv)
    status = 0
    for channel_id in args.channels:
        try:
            update = refresh_channel(channel_id, args.known, family=args.family)
        except backoff.BackedOff as e:
            print(json.dumps({"event": "paused", "kind": e.kind, "until": e.until}))
            return backoff.PAUSED_EXIT
        except FeedError as e:
            print(json.dumps({"event": "error", "channel_id": channel_id, "error": str(e)}))
            status = 1
            continue
        for entry in update.new:
            print(json.dumps({"event": "entry", **entry.__dict__}))
    sys.stdout.flush()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
