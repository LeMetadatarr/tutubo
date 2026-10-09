"""Lightweight preview wrappers around YouTube search-result renderer dicts.

A ``*Preview`` exposes typed accessors over a raw ``...Renderer`` JSON object
returned by the innertube search endpoint.  Calling :meth:`get` on a preview
upgrades it to a full ``Channel`` / ``Playlist`` / ``Video`` (which performs
additional network requests).
"""
from __future__ import annotations

from typing import List

from tutubo.channel import Video, Channel, Playlist
from tutubo.classification import Category, classify_category
from mediavocab.text import classify_video, extract_tags


class YoutubePreview:
    """Base class — stores the raw renderer dict that subclasses interpret."""

    def __init__(self, renderer_data: dict) -> None:
        self._raw_data: dict = renderer_data


# ---------------------------------------------------------------------------
# Playlist / Mix
# ---------------------------------------------------------------------------

class PlaylistPreview(YoutubePreview):
    """Preview of a regular YouTube playlist returned in search results."""

    def get(self) -> Playlist:
        """Return a full ``Playlist`` object (fetches the playlist page)."""
        return Playlist(self.playlist_url)

    @property
    def title(self) -> str:
        return self._raw_data["title"]['simpleText']

    @property
    def playlist_id(self) -> str:
        return self._raw_data["playlistId"]

    @property
    def playlist_url(self) -> str:
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"

    @property
    def video_count(self) -> int:
        return self._raw_data.get('videoCount', 0)

    @property
    def featured_videos(self) -> List[dict]:
        """Up to a few sample videos shown alongside the playlist card."""
        videos = []
        for v in self._raw_data.get('videos', []):
            v = v['childVideoRenderer']
            videos.append({
                "videoId": v['videoId'],
                "url": f"https://youtube.com/watch?v={v['videoId']}",
                "image": f"https://img.youtube.com/vi/{v['videoId']}/default.jpg",
                "title": v["title"]["simpleText"]
            })
        return videos

    @property
    def thumbnail_url(self) -> str:
        return self.thumbnails[-1]["url"]

    @property
    def thumbnails(self) -> List[dict]:
        return [t['thumbnails'][0] for t in self._raw_data['thumbnails']]

    def __str__(self) -> str:
        return self.title

    @property
    def as_dict(self) -> dict:
        return {'playlistId': self.playlist_id,
                'title': self.title,
                'url': self.playlist_url,
                "image": self.thumbnail_url,
                'featured_videos': self.featured_videos}


class YoutubeMixPreview(PlaylistPreview):
    """Preview of an auto-generated YouTube Mix (radioRenderer)."""

    @property
    def thumbnail_url(self) -> str:
        return self.thumbnails[-1]["url"]

    @property
    def thumbnails(self) -> List[dict]:
        return self._raw_data['thumbnail']['thumbnails']

    @property
    def as_dict(self) -> dict:
        return {'playlistId': self.playlist_id,
                'title': self.title,
                'url': self.playlist_url,
                "image": self.thumbnail_url,
                'featured_videos': self.featured_videos}


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class ChannelPreview(YoutubePreview):
    """Preview of a YouTube channel returned in search results."""

    def get(self) -> Channel:
        """Return a full ``Channel`` object (fetches the channel page)."""
        return Channel(self.channel_url)

    @property
    def title(self) -> str:
        return self._raw_data["title"]['simpleText']

    @property
    def description(self) -> str:
        return "".join(r["text"] for r in
                       self._raw_data.get('descriptionSnippet', {}).get('runs', []))

    @property
    def channel_id(self) -> str:
        return self._raw_data["channelId"]

    @property
    def channel_url(self) -> str:
        return f"https://www.youtube.com/channel/{self.channel_id}"

    @property
    def is_verified(self) -> bool:
        for b in self._raw_data.get('ownerBadges', []):
            style = b.get('metadataBadgeRenderer', {}).get('style', '')
            if 'VERIFIED' in style:
                return True
        return False

    @property
    def subscriber_count(self) -> str:
        """Subscriber count label, e.g. '1.28M subscribers'."""
        vct = self._raw_data.get('videoCountText', {})
        return vct.get('simpleText', '') or (vct.get('runs') or [{}])[0].get('text', '')

    @property
    def video_count(self) -> int:
        text = self.subscriber_count
        return int(''.join(c for c in text if c.isdigit()) or 0)

    @property
    def thumbnail_url(self) -> str:
        return self.thumbnails[-1]["url"]

    @property
    def thumbnails(self) -> List[dict]:
        return self._raw_data['thumbnail']['thumbnails']

    def __str__(self) -> str:
        return self.title

    @property
    def as_dict(self) -> dict:
        return {'channelId': self.channel_id,
                'title': self.title,
                'image': self.thumbnail_url,
                'url': self.channel_url,
                'description': self.description,
                'verified': self.is_verified}


# ---------------------------------------------------------------------------
# Video / Related Video
# ---------------------------------------------------------------------------

def _parse_badge_labels(raw_data: dict) -> List[str]:
    """Return list of badge label strings from videoRenderer badges."""
    labels = []
    for b in raw_data.get('badges', []):
        label = b.get('metadataBadgeRenderer', {}).get('label')
        if label:
            labels.append(label)
    for overlay in raw_data.get('thumbnailOverlays', []):
        badge = overlay.get('thumbnailOverlayTimeStatusRenderer', {})
        style = badge.get('style', '')
        if style in ('LIVE', 'UPCOMING', 'PREMIERE'):
            labels.append(style.capitalize())
    return labels


class VideoPreview(YoutubePreview):
    """Preview of a video search result (videoRenderer)."""

    def get(self) -> Video:
        """Return a full ``Video`` object."""
        return Video(self.video_id)

    @property
    def title(self) -> str:
        return "".join(r["text"] for r in self._raw_data['title']['runs'])

    @property
    def author(self) -> str:
        return "".join(r["text"] for r in self._raw_data['ownerText']['runs'])

    @property
    def channel_url(self) -> str:
        try:
            path = self._raw_data['ownerText']['runs'][0][
                'navigationEndpoint']['commandMetadata'][
                'webCommandMetadata']['url']
            return f'https://www.youtube.com{path}'
        except (KeyError, IndexError):
            return ""

    @property
    def channel_id(self) -> str:
        """Canonical channel id (``UCxxx…``) of the uploader, or '' if missing.

        Pulled from the renderer's ``browseId`` rather than parsed from
        ``channel_url`` — the renderer always carries the canonical id
        regardless of whether the channel publishes a custom ``/@handle``
        or ``/c/name`` URL.
        """
        try:
            return self._raw_data['ownerText']['runs'][0][
                'navigationEndpoint']['browseEndpoint']['browseId']
        except (KeyError, IndexError, TypeError):
            return ""

    @property
    def channel_thumbnail_url(self) -> str:
        """Channel avatar URL, available directly from search results."""
        thumbs = (self._raw_data
                      .get('channelThumbnailSupportedRenderers', {})
                      .get('channelThumbnailWithLinkRenderer', {})
                      .get('thumbnail', {})
                      .get('thumbnails', []))
        return thumbs[-1]['url'] if thumbs else ""

    @property
    def video_id(self) -> str:
        return self._raw_data['videoId']

    @property
    def watch_url(self) -> str:
        return f'https://www.youtube.com/watch?v={self.video_id}'

    @property
    def published_time(self) -> str:
        """Relative publish time, e.g. '2 years ago'. Empty for live streams."""
        return self._raw_data.get('publishedTimeText', {}).get('simpleText', '')

    @property
    def view_count(self) -> int:
        """Exact view count as integer. 0 for live/scheduled videos."""
        vct = self._raw_data.get('viewCountText', {})
        if 'runs' in vct:
            text = vct['runs'][0]['text']
        else:
            text = vct.get('simpleText', '0')
        stripped = text.split()[0].replace(',', '')
        return int(stripped) if stripped.isdigit() else 0

    @property
    def short_view_count(self) -> str:
        """Short view count label, e.g. '272M views'."""
        return self._raw_data.get('shortViewCountText', {}).get('simpleText', '')

    @property
    def length(self) -> int:
        """Duration in seconds. 0 for live streams."""
        if 'lengthText' in self._raw_data:
            pts = self._raw_data['lengthText']['simpleText'].split(":")
            h, m, s = 0, 0, 0
            if len(pts) == 3:
                h, m, s = pts
            elif len(pts) == 2:
                m, s = pts
            elif len(pts) == 1:
                s = pts[0]
            return int(s) + 60 * int(m) + 3600 * int(h)
        return 0

    @property
    def is_live(self) -> bool:
        return any(b.upper() == 'LIVE' for b in self.badges)

    @property
    def is_upcoming(self) -> bool:
        return 'Upcoming' in self.badges or 'Premiere' in self.badges

    @property
    def has_captions(self) -> bool:
        """True if the video has closed captions (CC badge present)."""
        return 'CC' in self.badges

    @property
    def badges(self) -> List[str]:
        """List of badge label strings, e.g. ['CC', '4K'] or ['Live']."""
        return _parse_badge_labels(self._raw_data)

    @property
    def is_verified_channel(self) -> bool:
        for b in self._raw_data.get('ownerBadges', []):
            style = b.get('metadataBadgeRenderer', {}).get('style', '')
            if 'VERIFIED' in style:
                return True
        return False

    @property
    def is_official_artist_channel(self) -> bool:
        """True when the video is from a YouTube Official Artist Channel."""
        for b in self._raw_data.get('ownerBadges', []):
            style = b.get('metadataBadgeRenderer', {}).get('style', '')
            if style == 'BADGE_STYLE_TYPE_VERIFIED_ARTIST':
                return True
        return False

    @property
    def description_snippet(self) -> str:
        """Short description snippet returned by search. Empty string if absent."""
        snips = self._raw_data.get('detailedMetadataSnippets', [])
        if not snips:
            return ""
        return "".join(r['text'] for r in snips[0].get('snippetText', {}).get('runs', []))

    @property
    def thumbnail_url(self) -> str:
        return f"https://img.youtube.com/vi/{self.video_id}/default.jpg"

    @property
    def classification(self):
        """The full mediavocab ``ClassificationResult`` (media_type,
        content_form, programme_format, content_genres) for this video.

        Channel-tag boosting (MOVIE/DOCUMENTARY/ANIME/etc. via channel keyword tags) is NOT
        applied here because search results don't include channel tags — those require fetching
        the channel page separately.  For channel-tag-boosted classification, iterate via
        ``Channel.videos`` (a ``channel.Video`` object) and call ``classify_video(..., channel_tags=v.channel_tags)``.
        """
        return classify_video(
            title=self.title or "",
            description=self.description_snippet,
            length=self.length,
            is_live=self.is_live,
            is_upcoming=self.is_upcoming,
            is_official_artist=self.is_official_artist_channel,
        )

    @property
    def content_type(self) -> Category:
        """Single tutubo search facet (:class:`Category`) for this video,
        collapsed from :attr:`classification` plus the live/upcoming flags."""
        return classify_category(
            self.classification,
            is_live=self.is_live,
            is_upcoming=self.is_upcoming,
            title=self.title or "",
        )

    @property
    def tags(self) -> List[str]:
        """Freeform labels extracted from title and description (genre, era, format sub-type, etc.)."""
        return extract_tags(self.title or "", self.description_snippet)

    @property
    def keywords(self) -> List[str]:
        """Always empty for previews — full Video objects expose channel-level keywords."""
        return []

    def to_work(self) -> object:
        """Return a ``mediavocab.Work`` for this video preview."""
        from tutubo.mediavocab_bridge import video_to_work
        return video_to_work(
            title=self.title,
            video_id=self.video_id,
            classification=self.classification,
            length=self.length,
            is_live=self.is_live,
            is_upcoming=self.is_upcoming,
            author=self.author,
            channel_id=self.channel_id,
            tags=self.tags,
        )

    def to_release(self) -> object:
        """Return a ``mediavocab.Release`` for this video preview."""
        from tutubo.mediavocab_bridge import video_to_release, _resolution_from_badges
        from mediavocab.text import parse_title
        parsed = parse_title(self.title or "")
        work = self.to_work()
        return video_to_release(
            work=work,
            video_id=self.video_id,
            watch_url=self.watch_url,
            thumbnail_url=self.thumbnail_url,
            is_live=self.is_live,
            is_upcoming=self.is_upcoming,
            has_captions=self.has_captions,
            regions_available=None,
            container=parsed.source_format or "",
            resolution=_resolution_from_badges(self.badges),
        )


    def __str__(self) -> str:
        return self.title

    @property
    def as_dict(self) -> dict:
        return {
            'videoId': self.video_id,
            'channelId': self.channel_id,
            'title': self.title,
            'author': self.author,
            'channel_url': self.channel_url,
            'channel_thumbnail': self.channel_thumbnail_url,
            'url': self.watch_url,
            'image': self.thumbnail_url,
            'length': self.length,
            'published': self.published_time,
            'views': self.view_count,
            'short_views': self.short_view_count,
            'badges': self.badges,
            'has_captions': self.has_captions,
            'is_live': self.is_live,
            'is_upcoming': self.is_upcoming,
            'is_official_artist': self.is_official_artist_channel,
            'is_verified': self.is_verified_channel,
            'description': self.description_snippet,
            'content_type': self.content_type,
            'tags': self.tags,
        }


class RelatedVideoPreview(VideoPreview):
    """A video shown as part of a related-videos shelf in search results."""

    @property
    def as_dict(self) -> dict:
        return super().as_dict


# ---------------------------------------------------------------------------
# Related search suggestion
# ---------------------------------------------------------------------------

class RelatedSearch(YoutubePreview):
    """A 'people also searched for' query suggestion card."""

    def get(self, preview: bool = True) -> "object":
        """Return a ``YoutubeSearch`` instance for this suggested query."""
        from tutubo.search import YoutubeSearch
        return YoutubeSearch(self.query, preview=preview)

    @property
    def query(self) -> str:
        return "".join(r["text"] for r in self._raw_data['query']['runs'])

    @property
    def thumbnail_url(self) -> str:
        return self.thumbnails[-1]["url"]

    @property
    def thumbnails(self) -> List[dict]:
        return self._raw_data['thumbnail']['thumbnails']

    def __str__(self) -> str:
        return self.query

    @property
    def as_dict(self) -> dict:
        return {'query': self.query, 'image': self.thumbnail_url}
