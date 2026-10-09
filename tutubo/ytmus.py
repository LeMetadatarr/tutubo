"""YouTube Music wrappers — ``MusicTrack``, ``MusicAlbum``, ``MusicArtist`` …

Thin typed views over ``ytmusicapi`` search/get_* responses.  A single
``YTMusic`` client is cached at module level via :func:`_get_ytmus`.
"""
from __future__ import annotations

import json
import time
from typing import List, Optional

from ytmusicapi import YTMusic

from tutubo.models import YoutubePreview, Video

_YTMUS: Optional[YTMusic] = None


def _get_ytmus(max_retries: int = 5) -> Optional[YTMusic]:
    """Return the cached YTMusic singleton, creating it on first call.

    Retries on transient connection errors (rate-limiting, DNS hiccups).
    Returns None if all retries fail — callers must guard against this.
    """
    global _YTMUS
    if _YTMUS:
        return _YTMUS
    for i in range(max_retries):
        try:
            _YTMUS = YTMusic()
            break
        except Exception:
            time.sleep(0.5 * (i + 1))
    return _YTMUS


class YTMusicResult(YoutubePreview):
    """Common base for all YT-Music-domain result wrappers."""

    @property
    def title(self) -> Optional[str]:
        return self._raw_data.get("title")

    @property
    def thumbnail_url(self) -> Optional[str]:
        img = self._raw_data.get("image")
        if not img and self._raw_data.get("thumbnails"):
            img = self._raw_data["thumbnails"][-1]["url"]
        return img

    @property
    def artist(self) -> Optional[str]:
        artist = self._raw_data.get("artist")
        if not artist and self._raw_data.get("artists"):
            artist = ", ".join(a["name"] for a in self._raw_data['artists'])
        return artist

    @property
    def description(self) -> Optional[str]:
        return self._raw_data.get("description")

    @property
    def as_dict(self) -> dict:
        return self._raw_data

    def __str__(self) -> str:
        return json.dumps(self.as_dict, sort_keys=True)


# ---------------------------------------------------------------------------
# Track / Video
# ---------------------------------------------------------------------------

class MusicTrack(YTMusicResult):
    """A song from YouTube Music search or an album track listing."""

    @property
    def watch_url(self) -> str:
        vid = self._raw_data.get("videoId", "")
        return f"https://music.youtube.com/watch?v={vid}" if vid else ""

    @property
    def video_id(self) -> str:
        return self._raw_data.get("videoId", "")

    @property
    def artist_browse_id(self) -> str:
        """Canonical artist ``browseId`` (typically ``UCxxx…``).

        Empty string when the result didn't carry one — common for video-
        type results where the uploader is just a channel, not a music
        artist entity.
        """
        artists = self._raw_data.get("artists")
        if isinstance(artists, list) and artists:
            a = artists[0] or {}
            if isinstance(a, dict):
                return a.get("id") or a.get("browseId") or ""
        return ""

    @property
    def album_browse_id(self) -> str:
        """Canonical album ``browseId`` (``MPREb_xxx``), empty if missing."""
        raw = self._raw_data.get("album")
        if isinstance(raw, dict):
            return raw.get("id") or raw.get("browseId") or ""
        return ""

    @property
    def length(self) -> Optional[int]:
        """Duration in seconds, or None if unknown."""
        secs = self._raw_data.get("duration_seconds")
        if secs is not None:
            return int(secs)
        dur = self._raw_data.get("duration")
        if isinstance(dur, str):
            parts = dur.split(":")
            if len(parts) == 2:
                m, s = parts
                return 60 * int(m) + int(s)
            elif len(parts) == 3:
                h, m, s = parts
                return 3600 * int(h) + 60 * int(m) + int(s)
        return None

    @property
    def album(self) -> str:
        """Album name, or empty string."""
        raw = self._raw_data.get("album")
        if isinstance(raw, dict):
            return raw.get("name") or ""
        return raw or ""

    @property
    def year(self) -> Optional[int]:
        """Release year as int, or None."""
        y = self._raw_data.get("year")
        return int(y) if y else None

    @property
    def is_explicit(self) -> bool:
        """True if YT Music flags this track as explicit."""
        return bool(self._raw_data.get("isExplicit"))

    @property
    def views(self) -> str:
        """View count label, e.g. '682M views'. Empty string if unavailable."""
        return self._raw_data.get("views") or ""

    @property
    def track_number(self) -> Optional[int]:
        """Track number within album, or None."""
        return self._raw_data.get("trackNumber") or self._raw_data.get("index")

    @property
    def video_type(self) -> str:
        """YouTube Music video type, e.g. 'MUSIC_VIDEO_TYPE_ATV' (audio-only),
        'MUSIC_VIDEO_TYPE_OMV' (official music video), 'MUSIC_VIDEO_TYPE_UGC'."""
        return self._raw_data.get("videoType", "")

    @property
    def is_audio_only(self) -> bool:
        """True for 'Official Audio' auto-generated tracks (no music video)."""
        return "ATV" in self.video_type or "OFFICIAL_SOURCE_MUSIC" in self.video_type

    @property
    def is_music_video(self) -> bool:
        """True for official music video uploads."""
        return "OMV" in self.video_type or "UGC" in self.video_type

    @property
    def category(self) -> str:
        """Result category, e.g. 'Songs', 'Videos'."""
        return self._raw_data.get("category", "")

    @property
    def as_dict(self) -> dict:
        return {
            "videoId": self.video_id,
            "artistBrowseId": self.artist_browse_id,
            "albumBrowseId": self.album_browse_id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "image": self.thumbnail_url,
            "url": self.watch_url,
            "duration": self.length,
            "views": self.views,
            "explicit": self.is_explicit,
            "audio_only": self.is_audio_only,
            "music_video": self.is_music_video,
            "video_type": self.video_type,
        }


class MusicVideo(MusicTrack):
    """A music video from YouTube (not YouTube Music — uses regular watch URLs)."""

    @property
    def watch_url(self) -> str:
        vid = self._raw_data.get("videoId", "")
        return f"https://www.youtube.com/watch?v={vid}" if vid else ""

    def get(self) -> Video:
        """Return the corresponding ``tutubo.channel.Video`` object."""
        return Video(self.video_id)


# ---------------------------------------------------------------------------
# Album / Playlist / Artist
# ---------------------------------------------------------------------------

class MusicPlaylist(YTMusicResult):
    """A YouTube Music playlist or album."""

    @property
    def playlist_id(self) -> str:
        return self._raw_data.get("audioPlaylistId") or self._raw_data.get("playlistId", "")

    @property
    def browse_id(self) -> str:
        """Canonical entity ``browseId`` for this playlist/album.

        For albums this is an ``MPREb_xxx`` release-group entity id; for
        regular playlists it's the playlist id itself.
        """
        return self._raw_data.get("browseId") or ""

    @property
    def artist_browse_id(self) -> str:
        """Primary artist's canonical ``browseId``, empty if absent."""
        artists = self._raw_data.get("artists")
        if isinstance(artists, list) and artists:
            a = artists[0] or {}
            if isinstance(a, dict):
                return a.get("id") or a.get("browseId") or ""
        return ""

    @property
    def playlist_url(self) -> str:
        pid = self.playlist_id
        return f"https://music.youtube.com/playlist?list={pid}" if pid else ""

    @property
    def year(self) -> Optional[int]:
        y = self._raw_data.get("year")
        return int(y) if y else None

    @property
    def track_count(self) -> int:
        return self._raw_data.get("trackCount", 0) or len(self.tracks)

    @property
    def duration_seconds(self) -> int:
        return self._raw_data.get("duration_seconds", 0) or 0

    @property
    def is_explicit(self) -> bool:
        return bool(self._raw_data.get("isExplicit"))

    @property
    def tracks(self) -> List["MusicTrack"]:
        """Tracks in this playlist/album, or [] if none have been fetched."""
        if "tracks" in self._raw_data:
            return [MusicTrack(t) for t in self._raw_data["tracks"] if t.get("videoId")]
        elif "songs" in self._raw_data:
            return [MusicTrack(t) for t in self._raw_data["songs"].get("results", []) if t.get("videoId")]
        return []

    @property
    def as_dict(self) -> dict:
        return {
            "browseId": self.browse_id,
            "playlistId": self.playlist_id,
            "artistBrowseId": self.artist_browse_id,
            "title": self.title,
            "artist": self.artist,
            "year": self.year,
            "image": self.thumbnail_url,
            "url": self.playlist_url,
            "track_count": self.track_count,
            "explicit": self.is_explicit,
            "playlist": [t.as_dict for t in self.tracks],
        }


def get_album(browse_id: str, playlist_id: str = "") -> dict:
    """Fetch album data, preferring get_playlist when a playlistId is available."""
    ytm = _get_ytmus()
    if playlist_id:
        try:
            data = ytm.get_playlist(playlist_id)
            data.setdefault("browseId", browse_id)
            data.setdefault("playlistId", playlist_id)
            return data
        except Exception:
            pass
    data = ytm.get_album(browse_id)
    data.setdefault("browseId", browse_id)
    return data


class MusicAlbum(MusicPlaylist):
    """A YouTube Music album."""

    @property
    def name(self) -> Optional[str]:
        return self.title

    @property
    def label(self) -> str:
        """Record label, or empty string."""
        return self._raw_data.get("label", "")

    @property
    def as_dict(self) -> dict:
        d = super().as_dict
        d["label"] = self.label
        return d


class MusicArtist(YTMusicResult):
    """A YouTube Music artist."""

    @property
    def name(self) -> str:
        # raw search results nest the name under artists[0]["name"]
        artists = self._raw_data.get("artists")
        if artists and isinstance(artists, list) and artists[0].get("name"):
            return artists[0]["name"]
        return self._raw_data.get("artist") or self._raw_data.get("title") or ""

    @property
    def title(self) -> str:
        return self.name

    @property
    def browse_id(self) -> str:
        """Canonical artist ``browseId`` (``UCxxx…``).

        For YT Music artists this is the same value as the artist's
        YouTube channel id, but it identifies the artist *entity* in YT
        Music's catalog — distinct from a regular YouTube channel that
        merely happens to upload music.
        """
        return (self._raw_data.get("browseId")
                or self._raw_data.get("channelId")
                or "")

    @property
    def channel_id(self) -> str:
        """Alias for :attr:`browse_id` — YT Music artist browseIds are
        ``UCxxx`` channel ids."""
        return self.browse_id

    @property
    def channel_url(self) -> str:
        bid = self.browse_id
        return f"https://music.youtube.com/channel/{bid}" if bid else ""

    @property
    def subscribers(self) -> str:
        """Subscriber count label, e.g. '1.2M subscribers'."""
        return self._raw_data.get("subscribers") or self._raw_data.get("views", "")

    @property
    def description(self) -> str:
        return self._raw_data.get("description") or ""

    @property
    def tracks(self) -> List["MusicTrack"]:
        """Top tracks for this artist."""
        songs = self._raw_data.get("songs", {})
        results = songs.get("results", []) if isinstance(songs, dict) else []
        return [MusicTrack(t) for t in results if t.get("videoId")]

    @property
    def as_dict(self) -> dict:
        return {
            "browseId": self.browse_id,
            "channelId": self.channel_id,
            "artist": self.name,
            "image": self.thumbnail_url,
            "url": self.channel_url,
            "subscribers": self.subscribers,
            "description": self.description,
            "playlist": [t.as_dict for t in self.tracks],
        }


def search_yt_music(query: str, as_dict: bool = True, n_retries: int = 3):
    """Convenience generator: search YT Music and yield wrappers (or dicts)."""
    ytmusic = _get_ytmus(n_retries)
    for r in ytmusic.search(query):
        if r["resultType"] == "video":
            obj = MusicVideo(r)
        elif r["resultType"] == "song":
            obj = MusicTrack(r)
        elif r["resultType"] == "album":
            try:
                a = ytmusic.get_album(r["browseId"])
                r.update(a)
            except Exception:
                continue
            obj = MusicAlbum(r)
        elif r["resultType"] == "playlist":
            try:
                a = ytmusic.get_playlist(r.get("browseId", ""))
                r.update(a)
            except Exception:
                continue
            obj = MusicPlaylist(r)
        elif r["resultType"] == "artist":
            try:
                a = ytmusic.get_artist(r["browseId"])
                r.update(a)
            except Exception:
                continue
            obj = MusicArtist(r)
        else:
            continue
        yield obj.as_dict if as_dict else obj
