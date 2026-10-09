"""Search facades for YouTube and YouTube Music.

``YoutubeSearch`` wraps the public youtube.com search endpoint and yields
typed previews / full objects.  ``YoutubeMusicSearch`` wraps the YT Music API
(via ``ytmusicapi``) and yields music-domain entities.
"""
from __future__ import annotations

import enum
from typing import Iterator, Optional

from tutubo._innertube import search as _innertube_search
from tutubo.channel import Channel, Video, Playlist
from tutubo.models import (
    VideoPreview, RelatedVideoPreview, ChannelPreview,
    PlaylistPreview, YoutubeMixPreview, RelatedSearch,
)
from tutubo.ytmus import (
    MusicTrack, MusicVideo, MusicAlbum, MusicPlaylist, MusicArtist,
    search_yt_music as search_yt_music,  # re-exported via tutubo package
)


class SearchType(enum.IntEnum):
    """Filter applied while iterating raw search-result sections."""

    YOUTUBE = enum.auto()
    VIDEOS = enum.auto()
    RELATED_VIDEOS = enum.auto()
    CHANNELS = enum.auto()
    PLAYLISTS = enum.auto()
    YOUTUBE_MIX = enum.auto()
    RELATED_QUERIES = enum.auto()
    ALL = enum.auto()


class YoutubeSearch:
    """Search YouTube and iterate typed results.

    Typical usage pattern — factory + typed iterator::

        for v in YoutubeSearch.for_movies("blade runner").iterate_movies(max_res=5):
            print(v.title, v.length)

        for v in YoutubeSearch.for_tutorials("python asyncio").iterate_tutorials():
            print(v.title)

    Plain search with post-classification::

        for v in YoutubeSearch("lo-fi beats").iterate_by_content_type(ContentType.MUSIC_AUDIO):
            print(v.title)
    """

    # ------------------------------------------------------------------
    # Factory classmethods — enrich the query for better signal/noise
    # ------------------------------------------------------------------

    @classmethod
    def for_movies(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} full movie")

    @classmethod
    def for_short_films(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} short film")

    @classmethod
    def for_trailers(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} official trailer")

    @classmethod
    def for_documentaries(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} documentary")

    @classmethod
    def for_behind_the_scenes(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} behind the scenes")

    @classmethod
    def for_anime(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} anime")

    @classmethod
    def for_tv_episodes(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} full episode")

    @classmethod
    def for_audiobooks(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} full audiobook")

    @classmethod
    def for_audio_dramas(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} audio drama")

    @classmethod
    def for_podcasts(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} podcast")

    @classmethod
    def for_stand_up(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} stand up comedy special")

    @classmethod
    def for_interviews(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} interview")

    @classmethod
    def for_lectures(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} lecture")

    @classmethod
    def for_concerts(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} full concert")

    @classmethod
    def for_news(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} news")

    @classmethod
    def for_live_news(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} live news")

    @classmethod
    def for_sport(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} full match")

    @classmethod
    def for_gaming(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} gameplay")

    @classmethod
    def for_tutorials(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} tutorial")

    @classmethod
    def for_reactions(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} reaction")

    @classmethod
    def for_compilations(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} compilation")

    @classmethod
    def for_kids(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} for kids")

    @classmethod
    def for_music_videos(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} official music video")

    @classmethod
    def for_music_audio(cls, query: str) -> "YoutubeSearch":
        return cls(f"{query} official audio")

    # keep old name as alias
    for_music = for_music_videos

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def __init__(self, query: str, preview: bool = True, thumbnail_url: str = "") -> None:
        self.query: str = query
        self.preview: bool = preview
        self.thumbnail_url: str = thumbnail_url
        self._initial_results: Optional[dict] = None

    def fetch_query(self, continuation: Optional[str] = None) -> dict:
        """Run the search (or fetch the next page) and return the raw response."""
        result = _innertube_search(self.query, continuation)
        if not self._initial_results:
            self._initial_results = result
        return result

    @property
    def as_dict(self) -> dict:
        return {'query': self.query, 'image': self.thumbnail_url}

    # ------------------------------------------------------------------
    # Low-level iteration
    # ------------------------------------------------------------------

    def iterate_youtube(self, max_res: int = -1, search_type: SearchType = SearchType.YOUTUBE) -> Iterator:
        """Yield up to ``max_res`` raw results matching ``search_type``.

        When ``preview`` is False each item is upgraded to a full object via
        :meth:`get`, which costs an extra HTTP request per item.
        """
        idx = 0
        for r in self._iterate_and_parse(search_type=search_type):
            idx += 1
            if 0 < max_res < idx:
                break
            if not self.preview:
                r = r.get()
            yield r

    def _iterate_and_parse(self, continuation: Optional[str] = None,
                           search_type: SearchType = SearchType.ALL) -> Iterator:
        raw_results = self.fetch_query(continuation)

        try:
            sections = (
                raw_results['contents']['twoColumnSearchResultsRenderer']
                ['primaryContents']['sectionListRenderer']['contents']
            )
        except KeyError:
            try:
                sections = raw_results['onResponseReceivedCommands'][0][
                    'appendContinuationItemsAction']['continuationItems']
            except (KeyError, IndexError):
                return

        item_renderer = None
        continuation_renderer = None
        for s in sections:
            if 'itemSectionRenderer' in s:
                item_renderer = s['itemSectionRenderer']
            if 'continuationItemRenderer' in s:
                continuation_renderer = s['continuationItemRenderer']

        next_continuation = None
        if continuation_renderer:
            next_continuation = continuation_renderer['continuationEndpoint'][
                'continuationCommand']['token']

        if item_renderer:
            raw_video_list = item_renderer['contents']
            for video_details in raw_video_list:
                if video_details.get('searchPyvRenderer', {}).get('ads'):
                    continue

                elif 'shelfRenderer' in video_details and \
                        search_type in (SearchType.ALL, SearchType.YOUTUBE, SearchType.RELATED_VIDEOS):
                    content = video_details['shelfRenderer']['content'].get("verticalListRenderer")
                    if content:
                        for v in content['items']:
                            yield RelatedVideoPreview(v['videoRenderer'])
                    continue

                elif 'radioRenderer' in video_details and \
                        search_type in (SearchType.ALL, SearchType.YOUTUBE, SearchType.YOUTUBE_MIX):
                    yield YoutubeMixPreview(video_details['radioRenderer'])
                    continue

                elif 'playlistRenderer' in video_details and \
                        search_type in (SearchType.ALL, SearchType.YOUTUBE, SearchType.PLAYLISTS):
                    yield PlaylistPreview(video_details['playlistRenderer'])
                    continue

                elif 'channelRenderer' in video_details and \
                        search_type in (SearchType.ALL, SearchType.YOUTUBE, SearchType.CHANNELS):
                    yield ChannelPreview(video_details['channelRenderer'])
                    continue

                elif 'horizontalCardListRenderer' in video_details and \
                        search_type in (SearchType.RELATED_QUERIES, SearchType.YOUTUBE, SearchType.ALL):
                    for v in video_details['horizontalCardListRenderer']['cards']:
                        yield RelatedSearch(v['searchRefinementCardRenderer'])
                    continue

                elif 'didYouMeanRenderer' in video_details:
                    continue

                elif 'backgroundPromoRenderer' in video_details:
                    continue

                elif 'messageRenderer' in video_details:
                    return

                elif 'videoRenderer' in video_details and \
                        search_type in (SearchType.ALL, SearchType.YOUTUBE, SearchType.VIDEOS):
                    yield VideoPreview(video_details['videoRenderer'])

        if next_continuation:
            yield from self._iterate_and_parse(next_continuation, search_type)

    # ------------------------------------------------------------------
    # Typed result iterators
    # ------------------------------------------------------------------

    def iterate_videos(self, max_res: int = -1) -> Iterator:
        """Yield ``VideoPreview`` (or ``Video`` if ``preview=False``) results."""
        for v in self.iterate_youtube(max_res):
            if isinstance(v, (Video, VideoPreview)):
                yield v

    def iterate_related_videos(self, max_res: int = -1) -> Iterator:
        """Yield videos surfaced inside related-video shelves."""
        for v in self.iterate_youtube(max_res):
            if isinstance(v, RelatedVideoPreview):
                yield v

    def iterate_channels(self, max_res: int = -1) -> Iterator:
        """Yield channel results."""
        for v in self.iterate_youtube(max_res):
            if isinstance(v, (Channel, ChannelPreview)):
                yield v

    def iterate_playlists(self, max_res: int = -1) -> Iterator:
        """Yield playlist results."""
        for v in self.iterate_youtube(max_res):
            if isinstance(v, (PlaylistPreview, Playlist)):
                yield v

    def iterate_mixes(self, max_res: int = -1) -> Iterator:
        """Yield YouTube Mix (radio) results."""
        for v in self.iterate_youtube(max_res):
            if isinstance(v, YoutubeMixPreview):
                yield v

    def iterate_queries(self, max_res: int = -1) -> Iterator:
        """Yield related search-query suggestions."""
        for v in self.iterate_youtube(max_res):
            if isinstance(v, RelatedSearch):
                yield v

    # ------------------------------------------------------------------
    # Content-type filtered iterators
    # ------------------------------------------------------------------

    def iterate_by_content_type(self, content_type: "object", max_res: int = -1) -> Iterator:
        """Yield VideoPreview objects whose classified content_type matches."""
        n = 0
        for v in self.iterate_videos():
            if v.content_type == content_type:
                yield v
                n += 1
                if 0 < max_res <= n:
                    break

    def _iter_ct(self, ct_name: str, max_res: int) -> Iterator:
        from tutubo.classification import Category
        return self.iterate_by_content_type(Category[ct_name], max_res=max_res)

    def iterate_movies(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("MOVIE", max_res)

    def iterate_short_films(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("SHORT_FILM", max_res)

    def iterate_trailers(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("TRAILER", max_res)

    def iterate_documentaries(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("DOCUMENTARY", max_res)

    def iterate_behind_the_scenes(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("BEHIND_THE_SCENES", max_res)

    def iterate_anime(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("ANIME", max_res)

    def iterate_tv_episodes(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("TV_EPISODE", max_res)

    def iterate_audiobooks(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("AUDIOBOOK", max_res)

    def iterate_audio_dramas(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("AUDIOBOOK", max_res)

    def iterate_podcasts(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("PODCAST", max_res)

    def iterate_stand_up(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("STAND_UP", max_res)

    def iterate_interviews(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("INTERVIEW", max_res)

    def iterate_lectures(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("LECTURE", max_res)

    def iterate_concerts(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("CONCERT", max_res)

    def iterate_news(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("NEWS", max_res)

    def iterate_live_news(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("LIVE_NEWS", max_res)

    def iterate_live_radio(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("LIVE_RADIO", max_res)

    def iterate_iptv(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("IPTV", max_res)

    def iterate_sport(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("SPORT", max_res)

    def iterate_gaming(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("GAMING", max_res)

    def iterate_tutorials(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("TUTORIAL", max_res)

    def iterate_reactions(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("REACTION", max_res)

    def iterate_compilations(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("COMPILATION", max_res)

    def iterate_kids(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("KIDS", max_res)

    def iterate_music_videos(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("MUSIC_VIDEO", max_res)

    def iterate_music_audio(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("MUSIC_AUDIO", max_res)

    def iterate_social_clips(self, max_res: int = -1) -> Iterator:
        return self._iter_ct("SOCIAL_CLIP", max_res)

class YoutubeMusicSearch:
    """Search the YouTube Music catalogue (music.youtube.com).

    Returns structured music entities — ``MusicTrack``, ``MusicAlbum``,
    ``MusicArtist``, ``MusicPlaylist``, ``MusicVideo`` — sourced from the
    YouTube Music API via ``ytmusicapi``.

    This is a **completely separate surface** from ``YoutubeSearch``:

    * ``YoutubeSearch`` — searches youtube.com; yields ``VideoPreview``,
      ``ChannelPreview``, ``PlaylistPreview`` etc.  Results are classified by
      ``ContentType`` and tagged by ``extract_tags``.
    * ``YoutubeMusicSearch`` — searches music.youtube.com; yields music-domain
      objects (``MusicTrack``, ``MusicAlbum``, ``MusicArtist`` …) with
      structured metadata (ISRC, album art, artist browse IDs).  ``ContentType``
      does not apply to these results.

    Typical usage::

        from tutubo import YoutubeMusicSearch

        for track in YoutubeMusicSearch("Black Sabbath").iterate_tracks(max_res=5):
            print(track.title, track.artist, track.duration)

        for album in YoutubeMusicSearch("Paranoid").iterate_albums(max_res=3):
            print(album.title, album.year)
    """

    def __init__(self, query: str) -> None:
        self.query: str = query

    def _ytmusic(self):
        """Return the cached ``YTMusic`` client, or ``None`` if it failed to init."""
        from tutubo.ytmus import _get_ytmus
        return _get_ytmus()

    def _raw_search(self, filter_type: Optional[str] = None) -> list:
        """Call ``YTMusic.search`` with the given filter, returning [] on failure."""
        ym = self._ytmusic()
        if ym is None:
            return []
        kwargs = {"filter": filter_type} if filter_type else {}
        return ym.search(self.query, **kwargs)

    # ------------------------------------------------------------------
    # Typed iterators — each hits the API with the appropriate filter
    # ------------------------------------------------------------------

    def iterate_tracks(self, max_res: int = -1) -> Iterator:
        """Yield song results as ``MusicTrack`` (type=song) or ``MusicVideo`` (type=video)."""
        n = 0
        for r in self._raw_search("songs"):
            rt = r.get("resultType")
            if rt == "song":
                yield MusicTrack(r)
            elif rt == "video":
                yield MusicVideo(r)
            else:
                continue
            n += 1
            if 0 < max_res <= n:
                break

    def iterate_videos(self, max_res: int = -1) -> Iterator:
        """Yield ``MusicVideo`` results (music videos on the Music catalogue)."""
        n = 0
        for r in self._raw_search("videos"):
            if r.get("resultType") != "video":
                continue
            yield MusicVideo(r)
            n += 1
            if 0 < max_res <= n:
                break

    def iterate_albums(self, max_res: int = -1) -> Iterator:
        """Yield ``MusicAlbum`` results, enriched with full track listing."""
        ym = self._ytmusic()
        n = 0
        for r in self._raw_search("albums"):
            if r.get("resultType") != "album":
                continue
            try:
                r.update(ym.get_album(r["browseId"]))
            except Exception:
                pass
            yield MusicAlbum(r)
            n += 1
            if 0 < max_res <= n:
                break

    def iterate_artists(self, max_res: int = -1) -> Iterator:
        """Yield ``MusicArtist`` results, enriched with top tracks and albums."""
        ym = self._ytmusic()
        n = 0
        for r in self._raw_search("artists"):
            if r.get("resultType") != "artist":
                continue
            try:
                r.update(ym.get_artist(r["browseId"]))
            except Exception:
                pass
            yield MusicArtist(r)
            n += 1
            if 0 < max_res <= n:
                break

    def iterate_playlists(self, max_res: int = -1) -> Iterator:
        """Yield ``MusicPlaylist`` results (community playlists on YT Music)."""
        ym = self._ytmusic()
        n = 0
        for r in self._raw_search("playlists"):
            if r.get("resultType") != "playlist":
                continue
            try:
                r.update(ym.get_playlist(r["browseId"]))
            except Exception:
                pass
            yield MusicPlaylist(r)
            n += 1
            if 0 < max_res <= n:
                break

    def iterate_all(self, max_res: int = -1) -> Iterator:
        """Yield all result types in API order (mixed tracks, albums, artists, playlists)."""
        ym = self._ytmusic()
        n = 0
        for r in self._raw_search():
            rt = r.get("resultType")
            if rt in ("song", "video"):
                obj = MusicTrack(r) if rt == "song" else MusicVideo(r)
            elif rt == "album":
                try:
                    r.update(ym.get_album(r["browseId"]))
                except Exception:
                    pass
                obj = MusicAlbum(r)
            elif rt == "playlist":
                try:
                    r.update(ym.get_playlist(r["browseId"]))
                except Exception:
                    pass
                obj = MusicPlaylist(r)
            elif rt == "artist":
                try:
                    r.update(ym.get_artist(r["browseId"]))
                except Exception:
                    pass
                obj = MusicArtist(r)
            else:
                continue
            yield obj
            n += 1
            if 0 < max_res <= n:
                break


def search_yt(query: str, as_dict: bool = True, parse: bool = False, max_res: int = 50) -> Iterator:
    """Convenience generator: yield ``max_res`` search results for ``query``.

    With ``as_dict=True`` items come out as plain dicts (``.as_dict``).
    With ``parse=True`` previews are upgraded to full objects (extra HTTP per item).
    """
    s = YoutubeSearch(query, preview=not parse)
    for v in s.iterate_youtube(max_res=max_res):
        if as_dict:
            yield v.as_dict
        else:
            yield v
