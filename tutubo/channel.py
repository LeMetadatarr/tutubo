"""Standalone YouTube Channel/Playlist/Video classes — no pytube dependency.

Fetches and parses youtube.com pages directly via the public ``ytInitialData``
JSON blob and the innertube ``/browse`` continuation endpoint.  All page
requests share a consent cookie (``SOCS``) so EU/GDPR redirects don't kick in.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, List, Optional, Tuple

from tutubo._utils import channel_name, initial_data, get_ytcfg, DeferredGeneratorList
from tutubo.transport import default_session

logger = logging.getLogger(__name__)


def _continuation_token(item: dict) -> Optional[str]:
    """Return the browse continuation token held by *item*, or ``None``.

    YouTube serves the token either as a ``continuationItemRenderer`` or, in the
    newer view-model layout, as a ``continuationItemViewModel``.
    """
    renderer = item.get("continuationItemRenderer")
    if renderer:
        return (renderer.get("continuationEndpoint", {})
                        .get("continuationCommand", {})
                        .get("token"))
    view_model = item.get("continuationItemViewModel")
    if view_model:
        return (view_model.get("continuationCommand", {})
                          .get("innertubeCommand", {})
                          .get("continuationCommand", {})
                          .get("token"))
    return None

_BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse"
_BROWSE_CONTEXT = {
    "client": {"clientName": "WEB", "clientVersion": "2.20200720.00.02"}
}
# Standard headers and consent cookie for all YouTube page requests.
# SOCS is a proto-encoded persistent consent acceptance token required in EU/similar regions.
_YT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}
_YT_COOKIES = {
    "CONSENT": "YES+cb",
    "SOCS": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg",
}


class Video:
    """Lightweight YouTube video object populated from channel-page data."""

    def __init__(self, video_id: str, title: Optional[str] = None,
                 thumbnail_url: Optional[str] = None, is_live: bool = False,
                 keywords: Optional[List[str]] = None, view_count: str = "",
                 published_time: str = "", channel_tags: Optional[List[str]] = None,
                 description: str = "") -> None:
        self.video_id: str = video_id
        self.watch_url: str = f"https://www.youtube.com/watch?v={video_id}"
        self._title: Optional[str] = title
        self._thumbnail_url: Optional[str] = thumbnail_url
        self._is_live: bool = is_live
        self.keywords: List[str] = keywords or []
        self.view_count: str = view_count        # e.g. "31K views"
        self.published_time: str = published_time  # e.g. "5 hours ago"
        self.channel_tags: List[str] = channel_tags or []
        self.description: str = description

    @property
    def title(self) -> Optional[str]:
        return self._title

    @property
    def thumbnail_url(self) -> str:
        if self._thumbnail_url:
            return self._thumbnail_url
        return f"https://img.youtube.com/vi/{self.video_id}/maxresdefault.jpg"

    @property
    def is_live(self) -> bool:
        return self._is_live

    @property
    def classification(self):
        """Full mediavocab ``ClassificationResult`` inferred from title,
        description and channel tags."""
        from mediavocab.text import classify_video
        return classify_video(
            title=self._title or "",
            description=self.description,
            is_live=self._is_live,
            channel_tags=self.channel_tags,
        )

    @property
    def content_type(self) -> "object":
        """Single tutubo search facet (:class:`~tutubo.classification.Category`),
        collapsed from :attr:`classification`."""
        from tutubo.classification import classify_category
        return classify_category(
            self.classification,
            is_live=self._is_live,
            title=self._title or "",
            tags=self.channel_tags,
        )

    @property
    def tags(self) -> List[str]:
        """Freeform labels from title and description (genre, era, format sub-type, etc.)."""
        from mediavocab.text import extract_tags
        return extract_tags(self._title or "", self.description)

    @property
    def as_dict(self) -> dict:
        return {
            "videoId": self.video_id,
            "url": self.watch_url,
            "title": self.title,
            "image": self.thumbnail_url,
            "is_live": self.is_live,
            "views": self.view_count,
            "published": self.published_time,
            "description": self.description,
            "content_type": self.content_type,
            "tags": self.tags,
        }

    def __repr__(self) -> str:
        return f"<Video {self.video_id!r} title={self.title!r}>"


class Playlist:
    """A YouTube playlist — fetches video URLs from the playlist page."""

    def __init__(self, url: str, session: Optional[object] = None) -> None:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        ids = parse_qs(parsed.query).get("list", [])
        if not ids:
            raise ValueError(f"No playlist ID found in URL: {url}")
        self._playlist_id = ids[0]
        self._html: Optional[str] = None
        self._initial_data: Optional[dict] = None
        self._ytcfg: Optional[dict] = None
        self._title: Optional[str] = None
        self._session = session if session is not None else default_session()

    @property
    def playlist_id(self) -> str:
        return self._playlist_id

    @property
    def playlist_url(self) -> str:
        return f"https://www.youtube.com/playlist?list={self._playlist_id}"

    @property
    def html(self) -> str:
        """Cached HTML of the playlist page (fetched on first access)."""
        if not self._html:
            resp = self._session.get(
                self.playlist_url,
                headers={**_YT_HEADERS, "Accept-Language": "en-US,en;q=0.9"},
                cookies=_YT_COOKIES,
                timeout=30,
            )
            resp.raise_for_status()
            self._html = resp.text
        return self._html

    @property
    def data(self) -> dict:
        """Parsed ``ytInitialData`` blob from the playlist page."""
        if not self._initial_data:
            self._initial_data = initial_data(self.html)
        return self._initial_data

    @property
    def yt_api_key(self) -> str:
        if not self._ytcfg:
            self._ytcfg = get_ytcfg(self.html)
        return self._ytcfg.get("INNERTUBE_API_KEY", "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8")

    @property
    def title(self) -> Optional[str]:
        if not self._title:
            try:
                self._title = self.data["metadata"]["playlistMetadataRenderer"]["title"]
            except (KeyError, TypeError):
                pass
        return self._title

    @staticmethod
    def _extract_video_ids(raw: str) -> Tuple[List[str], Optional[str]]:
        """Parse a playlist response and return (video_ids, continuation_token)."""
        data = json.loads(raw) if isinstance(raw, str) else raw
        continuation = None
        items = None
        try:
            sections = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0][
                "tabRenderer"]["content"]["sectionListRenderer"]["contents"]
        except (KeyError, IndexError, TypeError):
            sections = None
        for section in sections or []:
            continuation = continuation or _continuation_token(section)
            if items is not None:
                continue
            try:
                contents = section["itemSectionRenderer"]["contents"]
            except (KeyError, TypeError):
                continue
            if contents and "playlistVideoListRenderer" in contents[0]:
                items = contents[0]["playlistVideoListRenderer"]["contents"]
            elif any("lockupViewModel" in c for c in contents):
                items = contents
        if items is None:
            try:
                items = data["onResponseReceivedActions"][0][
                    "appendContinuationItemsAction"]["continuationItems"]
            except (KeyError, IndexError, TypeError):
                return [], None

        if items:
            token = _continuation_token(items[-1])
            if token:
                continuation = token
                items = items[:-1]

        ids = []
        seen = set()
        for item in items:
            vid_id = (item.get("playlistVideoRenderer", {}).get("videoId")
                      or item.get("lockupViewModel", {}).get("contentId"))
            if vid_id and vid_id not in seen:
                ids.append(vid_id)
                seen.add(vid_id)
        return ids, continuation

    def _continuation_post(self, token: str) -> str:
        """POST a continuation token to the browse endpoint and return raw JSON text."""
        url = f"{_BROWSE_URL}?key={self.yt_api_key}"
        resp = self._session.post(url, json={
            "continuation": token,
            "context": _BROWSE_CONTEXT,
        }, timeout=30)
        resp.raise_for_status()
        return resp.text

    def _video_id_generator(self) -> Iterable[str]:
        ids, continuation = self._extract_video_ids(json.dumps(self.data))
        yield from ids
        while continuation:
            raw = self._continuation_post(continuation)
            ids, continuation = self._extract_video_ids(raw)
            yield from ids

    @property
    def video_urls(self) -> List[str]:
        return [f"https://www.youtube.com/watch?v={vid}" for vid in self._video_id_generator()]

    @property
    def videos(self) -> Iterable[Video]:
        for vid_id in self._video_id_generator():
            yield Video(vid_id)

    def __repr__(self) -> str:
        return f"<Playlist {self._playlist_id!r} title={self.title!r}>"


class PodcastPreview:
    """A podcast show card from a channel's Podcasts tab."""

    def __init__(self, title: str, playlist_id: str, episode_count: str = "",
                 last_updated: str = "", thumbnail_url: str = "") -> None:
        self.title: str = title
        self.playlist_id: str = playlist_id
        self.episode_count: str = episode_count
        self.last_updated: str = last_updated
        self.thumbnail_url: str = thumbnail_url

    @property
    def playlist_url(self) -> str:
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"

    def get(self) -> "Playlist":
        """Return a full ``Playlist`` for this podcast's episode list."""
        return Playlist(self.playlist_url)

    @property
    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "playlistId": self.playlist_id,
            "url": self.playlist_url,
            "episodeCount": self.episode_count,
            "lastUpdated": self.last_updated,
            "image": self.thumbnail_url,
        }

    def __repr__(self) -> str:
        return f"<PodcastPreview {self.title!r} episodes={self.episode_count!r}>"


class Channel:
    """YouTube Channel — fetches metadata, videos, shorts, live streams, and playlists."""

    def __init__(self, url: str, language: str = "en-US,en;q=0.9",
                 session: Optional[object] = None) -> None:
        self._channel_uri = channel_name(url)
        self.language = language
        self.channel_url = f"https://www.youtube.com{self._channel_uri}"
        self.videos_url = self.channel_url + "/videos"
        self.shorts_url = self.channel_url + "/shorts"
        self.streams_url = self.channel_url + "/streams"
        self.playlists_url = self.channel_url + "/playlists"
        self.podcasts_url = self.channel_url + "/podcasts"

        self._html_cache: dict = {}
        self._initial_data_cache: dict = {}
        self._ytcfg: Optional[dict] = None
        self._visitor_data: Optional[str] = None
        self._session = session if session is not None else default_session()

    def _get_html(self, url: str) -> str:
        """Fetch ``url`` (memoised per-instance) with consent cookies set."""
        if url not in self._html_cache:
            resp = self._session.get(
                url,
                headers={**_YT_HEADERS, "Accept-Language": self.language},
                cookies=_YT_COOKIES,
                timeout=30,
            )
            resp.raise_for_status()
            self._html_cache[url] = resp.text
        return self._html_cache[url]

    def _get_data(self, url: str) -> dict:
        """Return parsed ``ytInitialData`` for ``url``, fetched and cached on demand."""
        if url not in self._initial_data_cache:
            self._initial_data_cache[url] = initial_data(self._get_html(url))
        return self._initial_data_cache[url]

    @property
    def _metadata_renderer(self) -> dict:
        return self._get_data(self.channel_url).get(
            "metadata", {}
        ).get("channelMetadataRenderer", {})

    @property
    def _page_header(self) -> dict:
        data = self._get_data(self.channel_url)
        return (data.get("header", {})
                    .get("pageHeaderRenderer", {})
                    .get("content", {})
                    .get("pageHeaderViewModel", {}))

    def _header_metadata_texts(self) -> List[str]:
        """Flatten ``pageHeaderViewModel`` metadata rows into a list of strings."""
        rows = (self._page_header
                    .get("metadata", {})
                    .get("contentMetadataViewModel", {})
                    .get("metadataRows", []))
        texts = []
        for row in rows:
            for part in row.get("metadataParts", []):
                t = part.get("text", {}).get("content", "")
                if t:
                    texts.append(t)
        return texts

    @property
    def channel_name(self) -> str:
        return self._metadata_renderer.get("title", "")

    @property
    def channel_id(self) -> str:
        return self._metadata_renderer.get("externalId", "")

    @property
    def vanity_url(self) -> Optional[str]:
        return self._metadata_renderer.get("vanityChannelUrl")

    @property
    def description(self) -> str:
        hdr_desc = (self._page_header
                        .get("description", {})
                        .get("descriptionPreviewViewModel", {})
                        .get("description", {})
                        .get("content", ""))
        return hdr_desc or self._metadata_renderer.get("description", "")

    @property
    def subscribers(self) -> str:
        """Subscriber count label, e.g. '12.3M subscribers'."""
        for t in self._header_metadata_texts():
            if "subscriber" in t.lower():
                return t
        return ""

    @property
    def video_count_label(self) -> str:
        """Video count label, e.g. '2.3K videos'."""
        for t in self._header_metadata_texts():
            if "video" in t.lower():
                return t
        return ""

    @property
    def thumbnail_url(self) -> str:
        thumbs = self._metadata_renderer.get("avatar", {}).get("thumbnails", [])
        return thumbs[0]["url"] if thumbs else ""

    @property
    def keywords(self) -> List[str]:
        """Channel tags / keywords as a list of strings."""
        raw = self._metadata_renderer.get("keywords", "")
        if isinstance(raw, list):
            return raw
        # older response format: space-separated, quoted phrases
        import shlex
        try:
            return shlex.split(raw) if raw else []
        except Exception:
            return raw.split() if raw else []

    @property
    def available_countries(self) -> List[str]:
        """ISO country codes where this channel is available."""
        return self._metadata_renderer.get("availableCountryCodes", [])

    @property
    def rss_url(self) -> str:
        """RSS feed URL for this channel's uploads."""
        return self._metadata_renderer.get("rssUrl", "")

    @property
    def title(self) -> str:
        return self.channel_name

    @property
    def yt_api_key(self) -> str:
        if not self._ytcfg:
            self._ytcfg = get_ytcfg(self._get_html(self.channel_url))
        return self._ytcfg.get("INNERTUBE_API_KEY", "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8")

    def _continuation_post(self, token: str) -> str:
        """POST a browse continuation; ``visitorData`` is required for newer feeds."""
        url = f"{_BROWSE_URL}?key={self.yt_api_key}"
        resp = self._session.post(url, json={
            "continuation": token,
            "context": _BROWSE_CONTEXT,
            **({"visitorData": self._visitor_data} if self._visitor_data else {}),
        }, timeout=30)
        resp.raise_for_status()
        return resp.text

    # ------------------------------------------------------------------
    # Video item parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _video_id_from_item(item: dict) -> Optional[str]:
        """Pull the videoId from any of the renderer shapes YouTube uses for grid items."""
        content = item.get("richItemRenderer", {}).get("content", {})
        if "videoRenderer" in content:
            return content["videoRenderer"].get("videoId")
        if "reelItemRenderer" in content:
            return content["reelItemRenderer"].get("videoId")
        if "lockupViewModel" in content:
            return content["lockupViewModel"].get("contentId")
        return None

    @staticmethod
    def _title_from_item(item: dict) -> Optional[str]:
        """Pull the title from a videoRenderer or lockupViewModel grid item."""
        content = item.get("richItemRenderer", {}).get("content", {})
        runs = content.get("videoRenderer", {}).get("title", {}).get("runs", [])
        if runs:
            return runs[0].get("text")
        lvm = content.get("lockupViewModel", {})
        return (lvm.get("metadata", {})
                   .get("lockupMetadataViewModel", {})
                   .get("title", {})
                   .get("content"))

    @staticmethod
    def _description_from_item(item: dict) -> str:
        """Return description snippet text from a videoRenderer item, or empty string."""
        content = item.get("richItemRenderer", {}).get("content", {})
        runs = (content.get("videoRenderer", {})
                       .get("descriptionSnippet", {})
                       .get("runs", []))
        return " ".join(r.get("text", "") for r in runs).strip()

    @staticmethod
    def _is_live_from_item(item: dict) -> bool:
        """True if the item carries a LIVE badge in either renderer shape."""
        content = item.get("richItemRenderer", {}).get("content", {})
        for badge in content.get("videoRenderer", {}).get("badges", []):
            if "LIVE" in badge.get("metadataBadgeRenderer", {}).get("style", ""):
                return True
        for overlay in (content.get("lockupViewModel", {})
                                .get("contentImage", {})
                                .get("thumbnailViewModel", {})
                                .get("overlays", [])):
            for badge in overlay.get("thumbnailBottomOverlayViewModel", {}).get("badges", []):
                if "LIVE" in badge.get("thumbnailBadgeViewModel", {}).get("badgeStyle", ""):
                    return True
        return False

    @staticmethod
    def _metadata_rows_from_item(item: dict) -> List[str]:
        """Return flat list of metadata text strings from lockupViewModel or videoRenderer."""
        content = item.get("richItemRenderer", {}).get("content", {})
        # lockupViewModel: rows → parts → text.content
        lvm = content.get("lockupViewModel", {})
        if lvm:
            rows = (lvm.get("metadata", {})
                       .get("lockupMetadataViewModel", {})
                       .get("metadata", {})
                       .get("contentMetadataViewModel", {})
                       .get("metadataRows", []))
            texts = []
            for row in rows:
                for part in row.get("metadataParts", []):
                    t = part.get("text", {}).get("content", "")
                    if t:
                        texts.append(t)
            return texts
        # videoRenderer: publishedTimeText + shortViewCountText
        vr = content.get("videoRenderer", {})
        texts = []
        svc = vr.get("shortViewCountText", {}).get("simpleText", "")
        if svc:
            texts.append(svc)
        pt = vr.get("publishedTimeText", {}).get("simpleText", "")
        if pt:
            texts.append(pt)
        return texts

    def _extract_items(self, raw_json: str, tab_suffix: str,
                       channel_tags: Optional[List[str]] = None) -> Tuple[List[Video], Optional[str]]:
        data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json

        # Initial page: find the active tab
        items = None
        try:
            for tab in data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]:
                tr = tab.get("tabRenderer", {})
                url = (tr.get("endpoint", {})
                         .get("commandMetadata", {})
                         .get("webCommandMetadata", {})
                         .get("url", ""))
                if url.split("?")[0].rsplit("/", 1)[-1] == tab_suffix:
                    items = tr["content"]["richGridRenderer"]["contents"]
                    try:
                        self._visitor_data = (
                            data["responseContext"]
                            ["webResponseContextExtensionData"]
                            ["ytConfigData"]["visitorData"]
                        )
                    except (KeyError, TypeError):
                        pass
                    break
        except (KeyError, TypeError):
            pass

        # Continuation response
        if items is None:
            try:
                items = data["onResponseReceivedActions"][0][
                    "appendContinuationItemsAction"]["continuationItems"]
            except (KeyError, IndexError, TypeError):
                return [], None

        if not items:
            return [], None

        continuation = _continuation_token(items[-1])
        if continuation:
            items = items[:-1]

        videos = []
        seen = set()
        for item in items:
            vid_id = self._video_id_from_item(item)
            if not vid_id or vid_id in seen:
                continue
            seen.add(vid_id)
            meta = self._metadata_rows_from_item(item)
            # heuristic: "X views" comes before the date string
            view_count = next((t for t in meta if "view" in t.lower()), "")
            published_time = next((t for t in meta if "view" not in t.lower()), "")
            videos.append(Video(
                video_id=vid_id,
                title=self._title_from_item(item),
                is_live=self._is_live_from_item(item),
                view_count=view_count,
                published_time=published_time,
                channel_tags=channel_tags or [],
                description=self._description_from_item(item),
            ))
        return videos, continuation

    def _video_generator(self, page_url: str) -> Iterable[Video]:
        """Yield ``Video`` objects from a channel tab, paging via continuations."""
        tab_suffix = page_url.rsplit("/", 1)[-1]
        data = self._get_data(page_url)
        tags = self.keywords
        videos, continuation = self._extract_items(data, tab_suffix, channel_tags=tags)
        yield from videos
        while continuation:
            raw = self._continuation_post(continuation)
            videos, continuation = self._extract_items(raw, tab_suffix, channel_tags=tags)
            yield from videos

    # ------------------------------------------------------------------
    # Public video/stream properties
    # ------------------------------------------------------------------

    @property
    def videos(self) -> Iterable[Video]:
        """Yield Video objects for all videos in this channel."""
        return DeferredGeneratorList(self._video_generator(self.videos_url))

    @property
    def shorts(self) -> Iterable[Video]:
        """Yield Video objects for Shorts in this channel."""
        return DeferredGeneratorList(self._video_generator(self.shorts_url))

    @property
    def streams(self) -> Iterable[Video]:
        """Yield Video objects from the channel's /streams tab (past and current livestreams).

        Maps to ``/@handle/streams`` — a paginated browse tab that lists all
        livestream uploads, including recordings of ended streams.
        For the single currently on-air stream use :attr:`live`.
        """
        return DeferredGeneratorList(self._video_generator(self.streams_url))

    @property
    def live(self) -> Optional[Video]:
        """Return the currently on-air live stream, or None if the channel is offline.

        Maps to ``/@handle/live``, which YouTube redirects to the active livestream
        watch page.  If no stream is live YouTube redirects to a regular video or
        the channel home — both cases return ``None``.

        For a paginated list of all livestream uploads use :attr:`streams`.
        """
        url = self.channel_url + "/live"
        try:
            data = self._get_data(url)
        except Exception:
            return None

        ep = (data.get("currentVideoEndpoint", {})
                  .get("watchEndpoint", {}))
        video_id = ep.get("videoId")
        if not video_id:
            return None

        # Confirm this is actually a live stream, not a redirect to a regular video.
        # videoDetails.isLiveContent is set on live and live-replay pages.
        # playerMicroformat.liveBroadcastDetails.isLiveNow is set only while streaming.
        is_live_content = (
            data.get("videoDetails", {}).get("isLiveContent")
            or data.get("microformat", {})
                   .get("playerMicroformatRenderer", {})
                   .get("liveBroadcastDetails", {})
                   .get("isLiveNow")
        )
        if not is_live_content:
            return None

        # Extract title from videoPrimaryInfoRenderer
        title = ""
        try:
            contents = (data["contents"]["twoColumnWatchNextResults"]
                            ["results"]["results"]["contents"])
            for block in contents:
                pvir = block.get("videoPrimaryInfoRenderer", {})
                if pvir:
                    runs = pvir.get("title", {}).get("runs", [])
                    title = "".join(r.get("text", "") for r in runs)
                    break
        except (KeyError, TypeError):
            pass

        channel_tags = self.keywords
        return Video(
            video_id=video_id,
            title=title,
            is_live=True,
            channel_tags=channel_tags,
        )

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_playlist_ids(data: dict) -> Tuple[List[str], Optional[str]]:
        """Return (playlist_ids, continuation_token) from a channel /playlists response."""
        playlists = []
        try:
            tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
            for tab in tabs:
                content = tab.get("tabRenderer", {}).get("content", {})
                if "sectionListRenderer" not in content:
                    continue
                for c in content["sectionListRenderer"]["contents"][0][
                        "itemSectionRenderer"]["contents"]:
                    if "shelfRenderer" in c:
                        playlists = c["shelfRenderer"]["content"][
                            "horizontalListRenderer"]["items"]
                        break
                    elif "gridRenderer" in c:
                        playlists = c["gridRenderer"]["items"]
                        break
                if playlists:
                    break
        except (KeyError, IndexError, TypeError):
            pass

        continuation = _continuation_token(playlists[-1]) if playlists else None
        if continuation:
            playlists = playlists[:-1]

        ids = []
        for p in playlists:
            if "gridPlaylistRenderer" in p:
                ids.append(p["gridPlaylistRenderer"]["playlistId"])
            elif "lockupViewModel" in p:
                ids.append(p["lockupViewModel"]["contentId"])
        return ids, continuation

    def _playlist_generator(self) -> Iterable[Playlist]:
        """Yield ``Playlist`` objects scraped from the channel's /playlists tab."""
        data = self._get_data(self.playlists_url)
        ids, _ = self._extract_playlist_ids(data)
        for pid in ids:
            yield Playlist(f"https://www.youtube.com/playlist?list={pid}",
                           session=self._session)

    @property
    def playlist_urls(self) -> List[str]:
        data = self._get_data(self.playlists_url)
        ids, _ = self._extract_playlist_ids(data)
        return [f"https://www.youtube.com/playlist?list={pid}" for pid in ids]

    @property
    def playlists(self) -> Iterable[Playlist]:
        """Yield Playlist objects for all playlists in this channel."""
        return DeferredGeneratorList(self._playlist_generator())

    # ------------------------------------------------------------------
    # Podcasts
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_podcast_item(lvm: dict) -> Optional["PodcastPreview"]:
        """Build a ``PodcastPreview`` from a lockupViewModel on the Podcasts tab."""
        import re as _re
        meta = lvm.get("metadata", {}).get("lockupMetadataViewModel", {})
        title = meta.get("title", {}).get("content", "")
        rows = (meta.get("metadata", {})
                    .get("contentMetadataViewModel", {})
                    .get("metadataRows", []))
        last_updated = ""
        for row in rows:
            for part in row.get("metadataParts", []):
                t = part.get("text", {}).get("content", "")
                if t and t.lower() != "view full podcast":
                    last_updated = t
        # Episode count is in the thumbnail badge
        episode_count = ""
        primary = (lvm.get("contentImage", {})
                      .get("collectionThumbnailViewModel", {})
                      .get("primaryThumbnail", {})
                      .get("thumbnailViewModel", {}))
        for overlay in primary.get("overlays", []):
            for badge in overlay.get("thumbnailOverlayBadgeViewModel", {}).get("thumbnailBadges", []):
                episode_count = badge.get("thumbnailBadgeViewModel", {}).get("text", "")
        # Thumbnail URL
        sources = primary.get("image", {}).get("sources", [])
        thumbnail_url = sources[0].get("url", "") if sources else ""
        # Playlist ID from onTap command URL
        url_path = (lvm.get("rendererContext", {})
                       .get("commandContext", {})
                       .get("onTap", {})
                       .get("innertubeCommand", {})
                       .get("commandMetadata", {})
                       .get("webCommandMetadata", {})
                       .get("url", ""))
        m = _re.search(r"list=([^&]+)", url_path)
        playlist_id = m.group(1) if m else ""
        if not playlist_id:
            return None
        return PodcastPreview(
            title=title,
            playlist_id=playlist_id,
            episode_count=episode_count,
            last_updated=last_updated,
            thumbnail_url=thumbnail_url,
        )

    def _podcast_generator(self) -> Iterable["PodcastPreview"]:
        data = self._get_data(self.podcasts_url)
        tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
        for tab in tabs:
            tr = tab.get("tabRenderer", {})
            url_path = (tr.get("endpoint", {})
                          .get("commandMetadata", {})
                          .get("webCommandMetadata", {})
                          .get("url", ""))
            if not url_path.endswith("/podcasts"):
                continue
            content = tr.get("content", {})
            items = content.get("richGridRenderer", {}).get("contents", [])
            for item in items:
                lvm = item.get("richItemRenderer", {}).get("content", {}).get("lockupViewModel", {})
                if lvm:
                    pod = self._parse_podcast_item(lvm)
                    if pod:
                        yield pod

    @property
    def podcasts(self) -> Iterable["PodcastPreview"]:
        """Yield PodcastPreview objects for each show on the Podcasts tab."""
        return DeferredGeneratorList(self._podcast_generator())

    @property
    def as_dict(self) -> dict:
        return {
            "channelId": self.channel_id,
            "title": self.title,
            "image": self.thumbnail_url,
            "url": self.channel_url,
            "description": self.description,
            "subscribers": self.subscribers,
            "video_count": self.video_count_label,
            "keywords": self.keywords,
            "rss_url": self.rss_url,
        }

    def __repr__(self) -> str:
        return f"<Channel {self._channel_uri!r}>"
