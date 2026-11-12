"""Targeted unit tests covering previously-untested branches.

Focus areas:
- mediavocab_bridge: every converter (Video/Music/Channel/Podcast → mediavocab)
- ytmus: MusicTrack/Album/Playlist/Artist parsing edge cases
- download: subprocess wrapper success + failure paths (mocked)
- _innertube: HTTP error paths and fixture recording
- _utils: parse failures, DeferredGeneratorList edge cases
- channel: Channel/Playlist/Video small branches
- search: YoutubeMusicSearch error paths

All tests are offline (no network, no yt-dlp binary required).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tutubo import _innertube
from tutubo._utils import (
    DeferredGeneratorList,
    _HTMLParseError,
    _parse_object,
    channel_name,
    get_ytcfg,
    initial_data,
    playlist_id,
    video_id,
)


# ---------------------------------------------------------------------------
# _utils — URL helpers, HTML extraction, DeferredGeneratorList
# ---------------------------------------------------------------------------

class TestUrlHelpers:
    def test_video_id_from_watch_url(self):
        assert video_id("https://youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_video_id_from_short_url(self):
        assert video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_video_id_invalid_raises(self):
        with pytest.raises(ValueError):
            video_id("https://example.com/")

    def test_playlist_id_from_url(self):
        assert playlist_id("https://youtube.com/playlist?list=PLabc123") == "PLabc123"

    def test_playlist_id_missing_raises(self):
        with pytest.raises(ValueError):
            playlist_id("https://youtube.com/watch?v=abc")

    def test_channel_name_handle(self):
        assert channel_name("https://youtube.com/@LofiGirl") == "/@LofiGirl"

    def test_channel_name_user(self):
        assert channel_name("https://youtube.com/user/SomeUser") == "/user/SomeUser"

    def test_channel_name_c(self):
        assert channel_name("https://youtube.com/c/SomeChannel") == "/c/SomeChannel"

    def test_channel_name_channel_id(self):
        # /channel/UCxxx style
        assert channel_name("https://youtube.com/channel/UCabc") == "/channel/UCabc"

    def test_channel_name_invalid_raises(self):
        with pytest.raises(ValueError):
            channel_name("https://example.com/foo bar")


class TestHtmlParse:
    def test_initial_data_extract(self):
        html = 'var ytInitialData = {"foo": "bar"};</script>'
        assert initial_data(html) == {"foo": "bar"}

    def test_initial_data_window_form(self):
        html = 'window["ytInitialData"] = {"a": 1};</script>'
        assert initial_data(html) == {"a": 1}

    def test_initial_data_missing_raises(self):
        with pytest.raises(_HTMLParseError):
            initial_data("<html>nope</html>")

    def test_get_ytcfg_set_form(self):
        html = 'ytcfg.set({"INNERTUBE_API_KEY": "K"});'
        assert get_ytcfg(html)["INNERTUBE_API_KEY"] == "K"

    def test_get_ytcfg_assignment_form(self):
        html = 'ytcfg = {"X": 1};'
        assert get_ytcfg(html)["X"] == 1

    def test_get_ytcfg_missing_raises(self):
        with pytest.raises(_HTMLParseError):
            get_ytcfg("nothing here")

    def test_parse_object_invalid_json_then_literal(self):
        # Python-literal-but-not-JSON: single-quoted strings
        html = "{'a': 1}"
        assert _parse_object(html, 0) == {"a": 1}

    def test_parse_object_invalid_start_raises(self):
        with pytest.raises(_HTMLParseError):
            _parse_object("xnotobject", 0)


class TestDeferredGeneratorList:
    def test_iter_and_indexing(self):
        d = DeferredGeneratorList(iter([1, 2, 3]))
        assert d[0] == 1
        assert list(d) == [1, 2, 3]

    def test_negative_index_forces_full(self):
        d = DeferredGeneratorList(iter([1, 2, 3]))
        assert d[-1] == 3

    def test_slice(self):
        d = DeferredGeneratorList(iter([1, 2, 3, 4]))
        assert d[1:3] == [2, 3]

    def test_len(self):
        d = DeferredGeneratorList(iter([1, 2]))
        assert len(d) == 2

    def test_repr(self):
        d = DeferredGeneratorList(iter([1, 2]))
        assert repr(d) == "[1, 2]"

    def test_eq(self):
        d = DeferredGeneratorList(iter([1, 2]))
        assert d == [1, 2]

    def test_invalid_key_type_raises(self):
        d = DeferredGeneratorList(iter([1, 2]))
        with pytest.raises(TypeError):
            d["foo"]


# ---------------------------------------------------------------------------
# _innertube — POST helpers, error paths, fixture recording
# ---------------------------------------------------------------------------

class TestInnertube:
    def test_search_passes_query(self, monkeypatch):
        called = {}

        def fake_post(endpoint, params, body):
            called["endpoint"] = endpoint
            called["params"] = params
            called["body"] = body
            return {"ok": True}

        monkeypatch.setattr(_innertube, "_post", fake_post)
        result = _innertube.search("hello world")
        assert result == {"ok": True}
        assert called["endpoint"] == "search"
        assert called["body"]["query"] == "hello world"
        assert called["params"]["query"] == "hello world"

    def test_search_with_continuation(self, monkeypatch):
        called = {}

        def fake_post(endpoint, params, body):
            called["body"] = body
            return {}

        monkeypatch.setattr(_innertube, "_post", fake_post)
        _innertube.search("ignored", continuation="TOKEN")
        assert called["body"]["continuation"] == "TOKEN"
        assert "query" not in called["body"]

    def test_post_http_error_raises_runtime(self, monkeypatch):
        from urllib import error as urllib_error

        def fake_urlopen(*a, **kw):
            raise urllib_error.HTTPError(
                "http://x", 500, "boom", hdrs=None, fp=None
            )

        monkeypatch.setattr(_innertube.urllib_request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="HTTP 500"):
            _innertube._post("search", {}, {"query": "q"})

    def test_post_url_error_raises_runtime(self, monkeypatch):
        from urllib import error as urllib_error

        def fake_urlopen(*a, **kw):
            raise urllib_error.URLError("dns boom")

        monkeypatch.setattr(_innertube.urllib_request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="Network error"):
            _innertube._post("search", {}, {"query": "q"})

    def test_post_records_fixture(self, monkeypatch, tmp_path):
        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b'{"ok": 1}'

        monkeypatch.setattr(_innertube.urllib_request, "urlopen",
                            lambda *a, **kw: _FakeResp())
        monkeypatch.setattr(_innertube, "_RECORD_DIR", str(tmp_path))
        result = _innertube._post("search", {}, {"query": "Hello World!"})
        assert result == {"ok": 1}
        files = list(tmp_path.glob("*.json"))
        assert files, "fixture file should be written"

    def test_post_records_fixture_continuation(self, monkeypatch, tmp_path):
        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b"{}"

        monkeypatch.setattr(_innertube.urllib_request, "urlopen",
                            lambda *a, **kw: _FakeResp())
        monkeypatch.setattr(_innertube, "_RECORD_DIR", str(tmp_path))
        _innertube._post("search", {}, {"continuation": "tok"})
        assert list(tmp_path.glob("*.json"))


# ---------------------------------------------------------------------------
# mediavocab_bridge — every converter
# ---------------------------------------------------------------------------

class TestVideoBridge:
    def test_video_to_work_basic(self):
        from mediavocab import MediaType
        from mediavocab.text.classify import ClassificationResult
        from tutubo.mediavocab_bridge import video_to_work
        w = video_to_work(
            title="Cool Movie (2020)",
            video_id="abc123",
            classification=ClassificationResult(media_type=MediaType.MOVIE),
            length=7200,
            is_live=False,
            is_upcoming=False,
            author="Some Channel",
            channel_id="UCxyz",
            tags=["action"],
        )
        assert w.title
        assert w.media_type == MediaType.MOVIE
        assert w.external_ids["youtube"] == "abc123"
        assert w.runtime == 7200
        assert w.credits, "channel credit should be attached"

    def test_video_to_work_upcoming(self):
        from mediavocab import ReleaseStatus
        from mediavocab.text.classify import ClassificationResult
        from tutubo.mediavocab_bridge import video_to_work
        w = video_to_work(
            title="Upcoming",
            video_id="x",
            classification=ClassificationResult(),
            length=0,
            is_live=False,
            is_upcoming=True,
            author="",
            channel_id="",
            tags=[],
        )
        assert w.release_status == ReleaseStatus.ANNOUNCED
        assert w.credits == []

    def test_video_to_work_dedupes_genres(self):
        from mediavocab import MediaType
        from mediavocab.text.classify import ClassificationResult
        from tutubo.mediavocab_bridge import video_to_work
        w = video_to_work(
            title="x",
            video_id="x",
            classification=ClassificationResult(media_type=MediaType.MOVIE,
                                                content_genres=["action"]),
            length=100,
            is_live=False,
            is_upcoming=False,
            author="a",
            channel_id="c",
            tags=["action", "action", "drama"],
        )
        # genre list should not have dupes
        assert len(w.content_genres) == len(set(w.content_genres))

    def test_video_to_work_propagates_form_and_format(self):
        from mediavocab import MediaType, ContentForm, ProgrammeFormat
        from mediavocab.text.classify import ClassificationResult
        from tutubo.mediavocab_bridge import video_to_work
        w = video_to_work(
            title="The Making Of", video_id="v",
            classification=ClassificationResult(
                media_type=MediaType.MOVIE,
                content_form=ContentForm.BEHIND_SCENES,
                programme_format=ProgrammeFormat.DOCUMENTARY,
            ),
            length=600, is_live=False, is_upcoming=False,
            author="", channel_id="", tags=[],
        )
        assert w.content_form == ContentForm.BEHIND_SCENES
        assert w.programme_format == ProgrammeFormat.DOCUMENTARY

    def test_video_to_release_live(self):
        from mediavocab import StreamMode
        from mediavocab.text.classify import ClassificationResult
        from tutubo.mediavocab_bridge import video_to_release, video_to_work
        w = video_to_work("t", "v", ClassificationResult(), 0, True, False, "", "", [])
        r = video_to_release(
            work=w, video_id="v", watch_url="u", thumbnail_url="i",
            is_live=True, is_upcoming=False, has_captions=True,
            regions_available=["US", "GB"],
        )
        assert r.stream_mode == StreamMode.LIVE
        assert r.regions_available == ["US", "GB"]
        assert r.accessibility

    def test_video_to_release_radio_continuous(self):
        from mediavocab import MediaType, StreamMode, ReleaseStatus
        from mediavocab.models.work import Work
        from tutubo.mediavocab_bridge import video_to_release
        w = Work(title="t", media_type=MediaType.RADIO,
                 release_status=ReleaseStatus.RELEASED)
        r = video_to_release(
            work=w, video_id="v", watch_url="u", thumbnail_url="i",
            is_live=False, is_upcoming=False, has_captions=False,
            regions_available=None,
        )
        assert r.stream_mode == StreamMode.CONTINUOUS

    def test_video_to_release_announced_when_upcoming(self):
        from mediavocab import ReleaseStatus
        from mediavocab.text.classify import ClassificationResult
        from tutubo.mediavocab_bridge import video_to_release, video_to_work
        w = video_to_work("t", "v", ClassificationResult(), 0, False, True, "", "", [])
        r = video_to_release(
            work=w, video_id="v", watch_url="u", thumbnail_url="i",
            is_live=False, is_upcoming=True, has_captions=False,
            regions_available=None,
        )
        assert r.release_status == ReleaseStatus.ANNOUNCED

    def test_resolution_from_badges(self):
        from tutubo.mediavocab_bridge import _resolution_from_badges
        assert _resolution_from_badges(["8K"]) == "4320p"
        assert _resolution_from_badges(["4K"]) == "2160p"
        assert _resolution_from_badges(["HD"]) == "1080p"
        assert _resolution_from_badges(["CC"]) == ""
        assert _resolution_from_badges([]) == ""

    def test_stream_mode_tv_continuous(self):
        # Continuity for broadcast media types is decided in video_to_release
        # (TV/RADIO → CONTINUOUS), not a ContentType→StreamMode table.
        from mediavocab import MediaType, StreamMode, ReleaseStatus
        from mediavocab.models.work import Work
        from tutubo.mediavocab_bridge import video_to_release
        w = Work(title="t", media_type=MediaType.TV, release_status=ReleaseStatus.RELEASED)
        r = video_to_release(
            work=w, video_id="v", watch_url="u", thumbnail_url="i",
            is_live=False, is_upcoming=False, has_captions=False, regions_available=None,
        )
        assert r.stream_mode == StreamMode.CONTINUOUS


class TestMusicBridge:
    def _track(self, **overrides):
        from tutubo.ytmus import MusicTrack
        raw = {
            "videoId": "abc",
            "title": "Song",
            "artists": [{"name": "A", "id": "UCa"}],
            "duration": "3:45",
            "year": "2020",
            "isExplicit": True,
            "videoType": "MUSIC_VIDEO_TYPE_OMV",
            "album": {"name": "Alb", "id": "MPRalb"},
            "trackNumber": 4,
        }
        raw.update(overrides)
        return MusicTrack(raw)

    def test_music_track_to_work(self):
        from mediavocab import MediaType
        from tutubo.mediavocab_bridge import music_track_to_work
        track = self._track()
        w = music_track_to_work(track)
        assert w.title == "Song"
        assert w.media_type == MediaType.MUSIC_VIDEO  # OMV → music_video
        assert "explicit" in w.content_genres
        assert w.external_ids.get("youtube") == "abc"
        assert w.external_ids.get("youtube_album_browse") == "MPRalb"
        assert w.credits

    def test_music_track_to_work_audio_only(self):
        from mediavocab import MediaType
        from tutubo.mediavocab_bridge import music_track_to_work
        track = self._track(videoType="MUSIC_VIDEO_TYPE_ATV")
        w = music_track_to_work(track)
        assert w.media_type == MediaType.MUSIC

    def test_music_track_to_release(self):
        from tutubo.mediavocab_bridge import music_track_to_release, music_track_to_work
        track = self._track()
        r = music_track_to_release(track, music_track_to_work(track))
        assert r.platform == "youtube_music"
        assert r.uri.startswith("https://music.youtube.com/")

    def test_music_video_to_release(self):
        from tutubo.mediavocab_bridge import music_video_to_release, music_track_to_work
        track = self._track()
        r = music_video_to_release(track, music_track_to_work(track))
        assert r.platform == "youtube"
        assert r.uri.startswith("https://www.youtube.com/")

    def test_music_video_to_release_no_video_id(self):
        from tutubo.mediavocab_bridge import music_video_to_release, music_track_to_work
        track = self._track(videoId="")
        r = music_video_to_release(track, music_track_to_work(track))
        assert r.uri == ""

    def test_music_playlist_to_work_and_release(self):
        from tutubo.ytmus import MusicPlaylist
        from tutubo.mediavocab_bridge import music_playlist_to_work, music_playlist_to_release
        pl = MusicPlaylist({
            "title": "PL",
            "browseId": "VLpl",
            "playlistId": "pl",
            "artists": [{"name": "A", "id": "UCa"}],
            "year": "2021",
            "duration_seconds": 600,
            "isExplicit": True,
            "tracks": [
                {"videoId": "v1", "title": "t1", "trackNumber": 1},
                {"videoId": "v2", "title": "t2"},
            ],
        })
        w = music_playlist_to_work(pl)
        assert w.title == "PL"
        assert "explicit" in w.content_genres
        assert len(w.tracklist) == 2
        r = music_playlist_to_release(pl, w)
        assert r.platform == "youtube_music"
        assert r.external_ids["youtube_playlist"] == "pl"

    def test_music_playlist_to_work_track_failure_skipped(self):
        """If a track fails to convert, it's skipped silently (covers `except Exception`)."""
        from tutubo.ytmus import MusicPlaylist
        from tutubo.mediavocab_bridge import music_playlist_to_work
        pl = MusicPlaylist({"title": "PL", "tracks": [{"videoId": "v", "title": "t"}]})
        # Force music_track_to_work to fail by patching it
        import tutubo.mediavocab_bridge as br
        orig = br.music_track_to_work
        try:
            br.music_track_to_work = lambda t: (_ for _ in ()).throw(RuntimeError("boom"))
            w = music_playlist_to_work(pl)
            assert w.tracklist == []
        finally:
            br.music_track_to_work = orig

    def test_music_album_to_release_with_label(self):
        from tutubo.ytmus import MusicAlbum
        from tutubo.mediavocab_bridge import music_album_to_release, music_playlist_to_work
        album = MusicAlbum({
            "title": "Alb",
            "browseId": "MPRalb",
            "playlistId": "pl",
            "label": "Some Records",
            "tracks": [],
        })
        r = music_album_to_release(album, music_playlist_to_work(album))
        assert r.label is not None
        assert r.label.name == "Some Records"

    def test_music_album_to_release_no_label(self):
        from tutubo.ytmus import MusicAlbum
        from tutubo.mediavocab_bridge import music_album_to_release, music_playlist_to_work
        album = MusicAlbum({"title": "Alb", "tracks": []})
        r = music_album_to_release(album, music_playlist_to_work(album))
        assert r.label is None


class TestEntityBridge:
    def test_channel_to_entity(self):
        from tutubo.channel import Channel
        from tutubo.mediavocab_bridge import channel_to_entity
        ch = Channel("https://youtube.com/@SomeChannel")
        # Set fake metadata via property override
        ch._initial_data_cache[ch.channel_url] = {
            "metadata": {"channelMetadataRenderer": {
                "title": "Some Channel", "externalId": "UCabc",
                "vanityChannelUrl": "http://youtube.com/@SomeChannel",
                "rssUrl": "http://rss",
                "keywords": ["a", "b"],
                "availableCountryCodes": ["US"],
            }}
        }
        ent = channel_to_entity(ch)
        assert ent.name == "Some Channel"
        assert ent.external_ids["youtube_channel"] == "UCabc"
        assert ent.external_ids["youtube_rss"] == "http://rss"
        assert ent.aliases == ["http://youtube.com/@SomeChannel"]
        assert "keywords" in ent.extra

    def test_channel_to_entity_minimal(self):
        from tutubo.channel import Channel
        from tutubo.mediavocab_bridge import channel_to_entity
        ch = Channel("https://youtube.com/@x")
        ch._initial_data_cache[ch.channel_url] = {"metadata": {"channelMetadataRenderer": {}}}
        ent = channel_to_entity(ch)
        assert ent.name == ""
        assert ent.aliases == []
        assert ent.external_ids == {}

    def test_channel_preview_to_entity(self):
        from tutubo.models import ChannelPreview
        from tutubo.mediavocab_bridge import channel_preview_to_entity
        cp = ChannelPreview({
            "channelId": "UCxxx",
            "title": {"simpleText": "Foo"},
            "ownerBadges": [{"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_VERIFIED"}}],
        })
        ent = channel_preview_to_entity(cp)
        assert ent.name == "Foo"
        assert ent.external_ids["youtube_channel"] == "UCxxx"
        assert ent.extra["verified"] is True

    def test_music_artist_to_entity(self):
        from tutubo.ytmus import MusicArtist
        from tutubo.mediavocab_bridge import music_artist_to_entity
        a = MusicArtist({"artist": "X", "browseId": "UCx", "subscribers": "1M"})
        ent = music_artist_to_entity(a)
        assert ent.name == "X"
        assert ent.external_ids["youtube_channel"] == "UCx"
        assert ent.extra["subscribers"] == "1M"


class TestPodcastBridge:
    def test_podcast_preview_to_work_and_release(self):
        from tutubo.channel import PodcastPreview
        from tutubo.mediavocab_bridge import podcast_preview_to_release, podcast_preview_to_work
        pod = PodcastPreview(
            title="My Pod", playlist_id="PLp",
            episode_count="10", last_updated="last week",
            thumbnail_url="http://t",
        )
        w = podcast_preview_to_work(pod)
        assert w.title == "My Pod"
        assert w.external_ids["youtube_playlist"] == "PLp"
        r = podcast_preview_to_release(pod, w)
        assert r.uri == pod.playlist_url
        assert r.image == "http://t"

    def test_podcast_preview_to_work_no_playlist_id(self):
        from tutubo.channel import PodcastPreview
        from tutubo.mediavocab_bridge import podcast_preview_to_work
        pod = PodcastPreview(title="X", playlist_id="")
        w = podcast_preview_to_work(pod)
        assert w.external_ids == {}


# ---------------------------------------------------------------------------
# ytmus — track parsing edge cases, get_album, search_yt_music
# ---------------------------------------------------------------------------

class TestMusicTrackParsing:
    def _t(self, **kw):
        from tutubo.ytmus import MusicTrack
        return MusicTrack(kw)

    def test_watch_url_empty_when_no_id(self):
        assert self._t().watch_url == ""

    def test_artist_from_artists_list(self):
        t = self._t(artists=[{"name": "A"}, {"name": "B"}])
        assert t.artist == "A, B"

    def test_artist_browse_id_from_id(self):
        t = self._t(artists=[{"name": "A", "id": "UCa"}])
        assert t.artist_browse_id == "UCa"

    def test_artist_browse_id_from_browseId(self):
        t = self._t(artists=[{"name": "A", "browseId": "UCb"}])
        assert t.artist_browse_id == "UCb"

    def test_artist_browse_id_missing(self):
        assert self._t().artist_browse_id == ""
        assert self._t(artists=[None]).artist_browse_id == ""

    def test_album_browse_id_dict(self):
        t = self._t(album={"name": "x", "id": "MPr"})
        assert t.album_browse_id == "MPr"

    def test_album_browse_id_string(self):
        t = self._t(album="Plain Name")
        assert t.album_browse_id == ""
        assert t.album == "Plain Name"

    def test_length_seconds(self):
        assert self._t(duration_seconds=125).length == 125

    def test_length_mm_ss(self):
        assert self._t(duration="3:45").length == 225

    def test_length_hh_mm_ss(self):
        assert self._t(duration="1:02:03").length == 3723

    def test_length_missing_returns_none(self):
        assert self._t().length is None

    def test_year(self):
        assert self._t(year="2020").year == 2020
        assert self._t().year is None

    def test_views_default(self):
        assert self._t().views == ""

    def test_video_type_flags(self):
        assert self._t(videoType="MUSIC_VIDEO_TYPE_ATV").is_audio_only
        assert self._t(videoType="MUSIC_VIDEO_TYPE_OMV").is_music_video
        assert self._t(videoType="MUSIC_VIDEO_TYPE_UGC").is_music_video
        assert not self._t(videoType="").is_audio_only

    def test_track_number(self):
        assert self._t(trackNumber=4).track_number == 4
        assert self._t(index=2).track_number == 2

    def test_thumbnail_url_from_thumbnails(self):
        t = self._t(thumbnails=[{"url": "u1"}, {"url": "u2"}])
        assert t.thumbnail_url == "u2"

    def test_thumbnail_url_from_image_field(self):
        t = self._t(image="img")
        assert t.thumbnail_url == "img"

    def test_str_serialises(self):
        t = self._t(title="X")
        assert "X" in str(t)


class TestMusicVideoMixin:
    def test_watch_url_uses_youtube(self):
        from tutubo.ytmus import MusicVideo
        v = MusicVideo({"videoId": "abc"})
        assert v.watch_url == "https://www.youtube.com/watch?v=abc"

    def test_get_returns_video(self):
        from tutubo.ytmus import MusicVideo
        from tutubo.channel import Video
        v = MusicVideo({"videoId": "abc"})
        assert isinstance(v.get(), Video)


class TestMusicPlaylist:
    def _p(self, **kw):
        from tutubo.ytmus import MusicPlaylist
        return MusicPlaylist(kw)

    def test_ids(self):
        assert self._p(audioPlaylistId="A").playlist_id == "A"
        assert self._p(playlistId="B").playlist_id == "B"
        assert self._p().playlist_id == ""
        assert self._p(browseId="VLpl").browse_id == "VLpl"

    def test_url(self):
        assert self._p(playlistId="X").playlist_url.endswith("?list=X")
        assert self._p().playlist_url == ""

    def test_year(self):
        assert self._p(year="2020").year == 2020
        assert self._p().year is None

    def test_track_count(self):
        assert self._p(trackCount=5).track_count == 5
        assert self._p(tracks=[{"videoId": "v"}]).track_count == 1

    def test_duration_seconds_default(self):
        assert self._p().duration_seconds == 0

    def test_artist_browse_id(self):
        p = self._p(artists=[{"name": "A", "browseId": "UCa"}])
        assert p.artist_browse_id == "UCa"
        assert self._p().artist_browse_id == ""

    def test_tracks_from_tracks_key(self):
        p = self._p(tracks=[{"videoId": "v"}, {"title": "no id"}])
        assert len(p.tracks) == 1

    def test_tracks_from_songs_key(self):
        p = self._p(songs={"results": [{"videoId": "v"}]})
        assert len(p.tracks) == 1

    def test_tracks_empty(self):
        assert self._p().tracks == []

    def test_as_dict(self):
        d = self._p(playlistId="P", title="T").as_dict
        assert d["playlistId"] == "P"
        assert d["title"] == "T"


class TestMusicAlbum:
    def test_label_and_name(self):
        from tutubo.ytmus import MusicAlbum
        a = MusicAlbum({"title": "Alb", "label": "Lbl"})
        assert a.name == "Alb"
        assert a.label == "Lbl"
        assert a.as_dict["label"] == "Lbl"

    def test_default_label(self):
        from tutubo.ytmus import MusicAlbum
        assert MusicAlbum({"title": "X"}).label == ""


class TestMusicArtist:
    def test_name_from_artists(self):
        from tutubo.ytmus import MusicArtist
        a = MusicArtist({"artists": [{"name": "X"}]})
        assert a.name == "X"
        assert a.title == "X"

    def test_name_from_artist_field(self):
        from tutubo.ytmus import MusicArtist
        assert MusicArtist({"artist": "Y"}).name == "Y"

    def test_name_from_title(self):
        from tutubo.ytmus import MusicArtist
        assert MusicArtist({"title": "Z"}).name == "Z"

    def test_name_empty(self):
        from tutubo.ytmus import MusicArtist
        assert MusicArtist({}).name == ""

    def test_browse_id_fallback_to_channel_id(self):
        from tutubo.ytmus import MusicArtist
        a = MusicArtist({"channelId": "UCa"})
        assert a.browse_id == "UCa"
        assert a.channel_id == "UCa"

    def test_channel_url(self):
        from tutubo.ytmus import MusicArtist
        a = MusicArtist({"browseId": "UCa"})
        assert a.channel_url.endswith("/UCa")
        assert MusicArtist({}).channel_url == ""

    def test_subscribers_fallback_views(self):
        from tutubo.ytmus import MusicArtist
        assert MusicArtist({"views": "1M"}).subscribers == "1M"

    def test_description(self):
        from tutubo.ytmus import MusicArtist
        assert MusicArtist({"description": "d"}).description == "d"
        assert MusicArtist({}).description == ""

    def test_tracks(self):
        from tutubo.ytmus import MusicArtist
        a = MusicArtist({"songs": {"results": [{"videoId": "v"}]}})
        assert len(a.tracks) == 1
        assert MusicArtist({}).tracks == []

    def test_as_dict(self):
        from tutubo.ytmus import MusicArtist
        d = MusicArtist({"artist": "X", "browseId": "UCx"}).as_dict
        assert d["artist"] == "X"
        assert d["browseId"] == "UCx"


class TestGetAlbum:
    def test_prefers_get_playlist_when_playlist_id_given(self, monkeypatch):
        from tutubo import ytmus

        class FakeYM:
            def get_playlist(self, pid): return {"title": "from_pl"}
            def get_album(self, bid):    return {"title": "from_al"}

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = ytmus.get_album("MPRb", "PLp")
        assert out["title"] == "from_pl"
        assert out["browseId"] == "MPRb"
        assert out["playlistId"] == "PLp"

    def test_falls_back_to_get_album_on_failure(self, monkeypatch):
        from tutubo import ytmus

        class FakeYM:
            def get_playlist(self, pid): raise RuntimeError("no")
            def get_album(self, bid):    return {"title": "from_al"}

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = ytmus.get_album("MPRb", "PLp")
        assert out["title"] == "from_al"
        assert out["browseId"] == "MPRb"

    def test_no_playlist_id(self, monkeypatch):
        from tutubo import ytmus

        class FakeYM:
            def get_album(self, bid): return {"title": "alb"}

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = ytmus.get_album("MPRb")
        assert out["browseId"] == "MPRb"


class TestSearchYtMusic:
    def test_yields_typed_objects(self, monkeypatch):
        from tutubo import ytmus

        class FakeYM:
            def search(self, q):
                return [
                    {"resultType": "video", "videoId": "v1", "title": "v"},
                    {"resultType": "song",  "videoId": "s1", "title": "s"},
                    {"resultType": "album", "browseId": "MPRa", "title": "a"},
                    {"resultType": "playlist", "browseId": "PLp", "title": "p"},
                    {"resultType": "artist", "browseId": "UCa", "title": "ar"},
                    {"resultType": "junk"},
                ]
            def get_album(self, b):    return {"genre": "rock"}
            def get_playlist(self, b): return {"author": "x"}
            def get_artist(self, b):   return {"description": "d"}

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = list(ytmus.search_yt_music("q", as_dict=False))
        # 5 typed (junk skipped)
        assert len(out) == 5

    def test_skips_album_when_get_album_fails(self, monkeypatch):
        from tutubo import ytmus

        class FakeYM:
            def search(self, q):
                return [
                    {"resultType": "album", "browseId": "MPRa", "title": "a"},
                    {"resultType": "playlist", "browseId": "PLp", "title": "p"},
                    {"resultType": "artist", "browseId": "UCa", "title": "ar"},
                ]
            def get_album(self, b):    raise RuntimeError("x")
            def get_playlist(self, b): raise RuntimeError("x")
            def get_artist(self, b):   raise RuntimeError("x")

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = list(ytmus.search_yt_music("q", as_dict=True))
        assert out == []  # all three failed and were skipped


class TestGetYtmusRetry:
    def test_returns_cached(self, monkeypatch):
        from tutubo import ytmus
        sentinel = object()
        monkeypatch.setattr(ytmus, "_YTMUS", sentinel)
        assert ytmus._get_ytmus() is sentinel

    def test_retries_then_gives_up(self, monkeypatch):
        from tutubo import ytmus
        monkeypatch.setattr(ytmus, "_YTMUS", None)

        def boom(*a, **kw): raise RuntimeError("nope")

        monkeypatch.setattr(ytmus, "YTMusic", boom)
        monkeypatch.setattr(ytmus.time, "sleep", lambda *a: None)
        result = ytmus._get_ytmus(max_retries=2)
        assert result is None


# ---------------------------------------------------------------------------
# YoutubeMusicSearch — error paths (filter_type branches)
# ---------------------------------------------------------------------------

class TestYoutubeMusicSearchPaths:
    def test_raw_search_returns_empty_when_client_none(self, monkeypatch):
        from tutubo import ytmus
        from tutubo.search import YoutubeMusicSearch
        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: None)
        s = YoutubeMusicSearch("x")
        assert s._raw_search("songs") == []

    def test_iterate_videos_yields_only_videos(self, monkeypatch):
        from tutubo import ytmus
        from tutubo.search import YoutubeMusicSearch
        from tutubo.ytmus import MusicVideo

        class FakeYM:
            def search(self, q, **kw):
                return [
                    {"resultType": "video", "videoId": "a", "title": "v"},
                    {"resultType": "song",  "videoId": "b", "title": "s"},
                ]

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = list(YoutubeMusicSearch("q").iterate_videos(max_res=5))
        assert all(isinstance(r, MusicVideo) for r in out)

    def test_iterate_albums_swallows_get_album_error(self, monkeypatch):
        from tutubo import ytmus
        from tutubo.search import YoutubeMusicSearch
        from tutubo.ytmus import MusicAlbum

        class FakeYM:
            def search(self, q, **kw):
                return [{"resultType": "album", "browseId": "MPRa", "title": "alb"}]
            def get_album(self, b): raise RuntimeError("boom")

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = list(YoutubeMusicSearch("q").iterate_albums(max_res=2))
        assert len(out) == 1
        assert isinstance(out[0], MusicAlbum)

    def test_iterate_playlists_skips_non_playlists(self, monkeypatch):
        from tutubo import ytmus
        from tutubo.search import YoutubeMusicSearch
        from tutubo.ytmus import MusicPlaylist

        class FakeYM:
            def search(self, q, **kw):
                return [
                    {"resultType": "song", "title": "s"},
                    {"resultType": "playlist", "browseId": "PLp", "title": "p"},
                ]
            def get_playlist(self, b): return {}

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = list(YoutubeMusicSearch("q").iterate_playlists(max_res=5))
        assert len(out) == 1
        assert isinstance(out[0], MusicPlaylist)

    def test_iterate_artists_swallows_get_artist_error(self, monkeypatch):
        from tutubo import ytmus
        from tutubo.search import YoutubeMusicSearch
        from tutubo.ytmus import MusicArtist

        class FakeYM:
            def search(self, q, **kw):
                return [{"resultType": "artist", "browseId": "UCa", "title": "x"}]
            def get_artist(self, b): raise RuntimeError("boom")

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = list(YoutubeMusicSearch("q").iterate_artists(max_res=2))
        assert len(out) == 1
        assert isinstance(out[0], MusicArtist)

    def test_iterate_all_max_res_breaks_early(self, monkeypatch):
        from tutubo import ytmus
        from tutubo.search import YoutubeMusicSearch

        class FakeYM:
            def search(self, q, **kw):
                return [{"resultType": "song", "videoId": str(i), "title": "x"} for i in range(10)]

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = list(YoutubeMusicSearch("q").iterate_all(max_res=2))
        assert len(out) == 2

    def test_iterate_tracks_skips_other_types(self, monkeypatch):
        from tutubo import ytmus
        from tutubo.search import YoutubeMusicSearch

        class FakeYM:
            def search(self, q, **kw):
                return [
                    {"resultType": "album", "title": "a"},
                    {"resultType": "song", "videoId": "v", "title": "s"},
                    {"resultType": "video", "videoId": "v2", "title": "v"},
                ]

        monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **kw: FakeYM())
        out = list(YoutubeMusicSearch("q").iterate_tracks(max_res=5))
        assert len(out) == 2  # album skipped


# ---------------------------------------------------------------------------
# search.py — search_yt convenience + iterate_youtube preview=False branch
# ---------------------------------------------------------------------------

class TestSearchYtConvenience:
    def test_search_yt_as_dict(self, patch_innertube):
        from tutubo.search import search_yt
        out = list(search_yt("rob zombie", as_dict=True, max_res=3))
        assert all(isinstance(r, dict) for r in out)
        assert len(out) <= 3

    def test_search_yt_objects(self, patch_innertube):
        from tutubo.search import search_yt
        out = list(search_yt("rob zombie", as_dict=False, max_res=2))
        assert len(out) <= 2
        # not dicts
        assert all(not isinstance(r, dict) for r in out)

    @pytest.mark.parametrize("method,ct_name", [
        ("iterate_movies", "MOVIE"),
        ("iterate_short_films", "SHORT_FILM"),
        ("iterate_trailers", "TRAILER"),
        ("iterate_documentaries", "DOCUMENTARY"),
        ("iterate_behind_the_scenes", "BEHIND_THE_SCENES"),
        ("iterate_anime", "ANIME"),
        ("iterate_tv_episodes", "TV_EPISODE"),
        ("iterate_audiobooks", "AUDIOBOOK"),
        ("iterate_audio_dramas", "AUDIOBOOK"),
        ("iterate_podcasts", "PODCAST"),
        ("iterate_stand_up", "STAND_UP"),
        ("iterate_interviews", "INTERVIEW"),
        ("iterate_lectures", "LECTURE"),
        ("iterate_concerts", "CONCERT"),
        ("iterate_news", "NEWS"),
        ("iterate_live_news", "LIVE_NEWS"),
        ("iterate_live_radio", "LIVE_RADIO"),
        ("iterate_iptv", "IPTV"),
        ("iterate_sport", "SPORT"),
        ("iterate_gaming", "GAMING"),
        ("iterate_tutorials", "TUTORIAL"),
        ("iterate_reactions", "REACTION"),
        ("iterate_compilations", "COMPILATION"),
        ("iterate_kids", "KIDS"),
        ("iterate_music_videos", "MUSIC_VIDEO"),
        ("iterate_music_audio", "MUSIC_AUDIO"),
        ("iterate_social_clips", "SOCIAL_CLIP"),
    ])
    def test_iterate_shortcuts_route_to_content_type(self, monkeypatch, method, ct_name):
        """Each iterate_* shortcut must call iterate_by_content_type with the right ContentType."""
        from tutubo import YoutubeSearch
        from tutubo import ContentType
        captured = {}

        def fake(self, ct, max_res=-1):
            captured["ct"] = ct
            captured["max_res"] = max_res
            return iter([])

        monkeypatch.setattr(YoutubeSearch, "iterate_by_content_type", fake)
        list(getattr(YoutubeSearch("q"), method)(max_res=2))
        assert captured["ct"] == ContentType[ct_name]
        assert captured["max_res"] == 2

    @pytest.mark.parametrize("method,suffix", [
        ("for_movies", "full movie"),
        ("for_short_films", "short film"),
        ("for_trailers", "official trailer"),
        ("for_documentaries", "documentary"),
        ("for_behind_the_scenes", "behind the scenes"),
        ("for_anime", "anime"),
        ("for_tv_episodes", "full episode"),
        ("for_audiobooks", "full audiobook"),
        ("for_audio_dramas", "audio drama"),
        ("for_podcasts", "podcast"),
        ("for_stand_up", "stand up comedy special"),
        ("for_interviews", "interview"),
        ("for_lectures", "lecture"),
        ("for_concerts", "full concert"),
        ("for_news", "news"),
        ("for_live_news", "live news"),
        ("for_sport", "full match"),
        ("for_gaming", "gameplay"),
        ("for_tutorials", "tutorial"),
        ("for_reactions", "reaction"),
        ("for_compilations", "compilation"),
        ("for_kids", "for kids"),
        ("for_music_videos", "official music video"),
        ("for_music_audio", "official audio"),
    ])
    def test_for_factories_enrich_query(self, method, suffix):
        from tutubo import YoutubeSearch
        s = getattr(YoutubeSearch, method)("query")
        assert isinstance(s, YoutubeSearch)
        assert suffix in s.query

    def test_for_music_alias(self):
        from tutubo import YoutubeSearch
        # for_music is an alias for for_music_videos
        assert YoutubeSearch.for_music("x").query == YoutubeSearch.for_music_videos("x").query

    def test_iterate_youtube_handles_all_renderer_types(self, monkeypatch):
        """Synthetic search response covering shelf/radio/playlist/channel/refinement/ads."""
        from tutubo import _innertube
        from tutubo.search import YoutubeSearch, SearchType
        from tutubo.models import (
            ChannelPreview, PlaylistPreview,
            YoutubeMixPreview, RelatedSearch, RelatedVideoPreview,
        )

        synthetic = {"contents": {"twoColumnSearchResultsRenderer": {"primaryContents": {
            "sectionListRenderer": {"contents": [
                {"itemSectionRenderer": {"contents": [
                    {"searchPyvRenderer": {"ads": [1]}},  # ad — skipped
                    {"didYouMeanRenderer": {}},  # skipped
                    {"backgroundPromoRenderer": {}},  # skipped
                    {"shelfRenderer": {"content": {"verticalListRenderer": {"items": [
                        {"videoRenderer": {
                            "videoId": "rv1",
                            "title": {"runs": [{"text": "rel"}]},
                            "ownerText": {"runs": [{"text": "C", "navigationEndpoint": {
                                "commandMetadata": {"webCommandMetadata": {"url": "/c"}}
                            }}]},
                            "viewCountText": {"simpleText": "0"},
                            "publishedTimeText": {"simpleText": ""},
                            "shortViewCountText": {"simpleText": ""},
                        }}
                    ]}}}},
                    {"radioRenderer": {
                        "playlistId": "RDmix",
                        "title": {"simpleText": "Mix"},
                        "thumbnail": {"thumbnails": [{"url": "u"}]},
                    }},
                    {"playlistRenderer": {
                        "playlistId": "PL1",
                        "title": {"simpleText": "PL"},
                        "videoCount": 5,
                        "thumbnails": [{"thumbnails": [{"url": "u"}]}],
                    }},
                    {"channelRenderer": {
                        "channelId": "UCxxx",
                        "title": {"simpleText": "Ch"},
                        "thumbnail": {"thumbnails": [{"url": "u"}]},
                    }},
                    {"horizontalCardListRenderer": {"cards": [
                        {"searchRefinementCardRenderer": {
                            "query": {"runs": [{"text": "more"}]},
                            "thumbnail": {"thumbnails": [{"url": "u"}]},
                        }}
                    ]}},
                    {"videoRenderer": {
                        "videoId": "v1",
                        "title": {"runs": [{"text": "T"}]},
                        "ownerText": {"runs": [{"text": "C", "navigationEndpoint": {
                            "commandMetadata": {"webCommandMetadata": {"url": "/c"}}
                        }}]},
                        "viewCountText": {"simpleText": "0"},
                        "publishedTimeText": {"simpleText": ""},
                        "shortViewCountText": {"simpleText": ""},
                    }},
                ]}},
            ]}
        }}}}

        def fake_search(query, continuation=None):
            if continuation:
                return {}
            return synthetic

        monkeypatch.setattr(_innertube, "search", fake_search)
        # Re-import the symbol used inside YoutubeSearch
        import tutubo.search as _search
        monkeypatch.setattr(_search, "_innertube_search", fake_search)

        s = YoutubeSearch("q")
        results = list(s.iterate_youtube(search_type=SearchType.ALL))
        types = {type(r).__name__ for r in results}
        assert "RelatedVideoPreview" in types
        assert "YoutubeMixPreview" in types
        assert "PlaylistPreview" in types
        assert "ChannelPreview" in types
        assert "RelatedSearch" in types
        assert "VideoPreview" in types

        # Typed iterators
        assert any(isinstance(r, RelatedVideoPreview) for r in YoutubeSearch("q").iterate_related_videos())
        assert any(isinstance(r, YoutubeMixPreview) for r in YoutubeSearch("q").iterate_mixes())
        assert any(isinstance(r, RelatedSearch) for r in YoutubeSearch("q").iterate_queries())
        assert any(isinstance(r, ChannelPreview) for r in YoutubeSearch("q").iterate_channels())
        assert any(isinstance(r, PlaylistPreview) for r in YoutubeSearch("q").iterate_playlists())

    def test_iterate_message_renderer_terminates(self, monkeypatch):
        from tutubo.search import YoutubeSearch
        synthetic = {"contents": {"twoColumnSearchResultsRenderer": {"primaryContents": {
            "sectionListRenderer": {"contents": [
                {"itemSectionRenderer": {"contents": [
                    {"messageRenderer": {}},
                    # would be yielded but messageRenderer returns first
                    {"videoRenderer": {"videoId": "v"}},
                ]}}
            ]}
        }}}}
        import tutubo.search as _search
        monkeypatch.setattr(_search, "_innertube_search", lambda q, c=None: synthetic)
        out = list(YoutubeSearch("q").iterate_youtube())
        assert out == []

    def test_iterate_no_sections(self, monkeypatch):
        import tutubo.search as _search
        from tutubo.search import YoutubeSearch
        monkeypatch.setattr(_search, "_innertube_search", lambda q, c=None: {})
        assert list(YoutubeSearch("q").iterate_youtube()) == []

    def test_iterate_by_content_type_max_res(self, patch_innertube):
        from tutubo import YoutubeSearch
        from tutubo import ContentType
        # max_res=1: must yield at most 1 even if more match
        out = list(YoutubeSearch("rob zombie").iterate_by_content_type(
            ContentType.MUSIC_VIDEO, max_res=1
        ))
        assert len(out) <= 1


# ---------------------------------------------------------------------------
# download.py — subprocess wrapper paths (mocked)
# ---------------------------------------------------------------------------

def _dl_module():
    """Return the tutubo.download submodule (shadowed by the download function in tutubo)."""
    import importlib
    return importlib.import_module("tutubo.download")


class TestDownload:
    def test_require_ytdlp_missing(self, monkeypatch):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError, match="yt-dlp not found"):
            dl._require_ytdlp()

    def test_download_video_audio_only(self, monkeypatch, tmp_path):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: "/usr/bin/yt-dlp")
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return MagicMock(returncode=0,
                             stdout="[ExtractAudio] Destination: out.mp3\n",
                             stderr="")

        monkeypatch.setattr(dl.subprocess, "run", fake_run)
        result = dl.download("http://x/v=abc", str(tmp_path), audio_only=True)
        assert result == "out.mp3"
        assert "-x" in captured["cmd"]

    def test_download_video_quality(self, monkeypatch, tmp_path):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: "/usr/bin/yt-dlp")

        def fake_run(cmd, **kw):
            return MagicMock(returncode=0,
                             stdout="[download] Destination: vid.mp4\n",
                             stderr="")

        monkeypatch.setattr(dl.subprocess, "run", fake_run)
        result = dl.download("http://x/v=abc", str(tmp_path), quality="720", filename="myfile")
        assert result == "vid.mp4"

    def test_download_merging_format_branch(self, monkeypatch, tmp_path):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: "/usr/bin/yt-dlp")

        def fake_run(cmd, **kw):
            return MagicMock(returncode=0,
                             stdout='Merging formats into "merged.mkv"\n',
                             stderr="")

        monkeypatch.setattr(dl.subprocess, "run", fake_run)
        assert dl.download("http://x", str(tmp_path)) == "merged.mkv"

    def test_download_failure_raises(self, monkeypatch, tmp_path):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: "/usr/bin/yt-dlp")
        monkeypatch.setattr(dl.subprocess, "run", lambda *a, **kw: MagicMock(
            returncode=1, stdout="", stderr="boom"))
        with pytest.raises(RuntimeError, match="yt-dlp failed"):
            dl.download("http://x", str(tmp_path))

    def test_download_fallback_to_newest_file(self, monkeypatch, tmp_path):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: "/usr/bin/yt-dlp")
        # Create a file in tmp_path so the fallback finds it
        f = tmp_path / "result.mp4"
        f.write_text("x")
        monkeypatch.setattr(dl.subprocess, "run", lambda *a, **kw: MagicMock(
            returncode=0, stdout="no Destination here", stderr=""))
        result = dl.download("http://x", str(tmp_path))
        assert result == str(f)

    def test_download_no_output_files_raises(self, monkeypatch, tmp_path):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: "/usr/bin/yt-dlp")
        monkeypatch.setattr(dl.subprocess, "run", lambda *a, **kw: MagicMock(
            returncode=0, stdout="", stderr=""))
        with pytest.raises(RuntimeError, match="no output file found"):
            dl.download("http://x", str(tmp_path))

    def test_download_playlist(self, monkeypatch, tmp_path):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: "/usr/bin/yt-dlp")
        monkeypatch.setattr(dl.subprocess, "run", lambda *a, **kw: MagicMock(
            returncode=0,
            stdout="[download] Destination: a.mp4\n[download] Destination: b.mp4\n",
            stderr="",
        ))
        out = dl.download_playlist("http://x", str(tmp_path))
        assert out == ["a.mp4", "b.mp4"]

    def test_download_playlist_audio_only(self, monkeypatch, tmp_path):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: "/usr/bin/yt-dlp")
        called = {}

        def fake_run(cmd, **kw):
            called["cmd"] = cmd
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(dl.subprocess, "run", fake_run)
        dl.download_playlist("http://x", str(tmp_path), audio_only=True, quality="1080")
        assert "-x" in called["cmd"]

    def test_download_playlist_fail(self, monkeypatch, tmp_path):
        dl = _dl_module()
        monkeypatch.setattr(dl.shutil, "which", lambda name: "/usr/bin/yt-dlp")
        monkeypatch.setattr(dl.subprocess, "run", lambda *a, **kw: MagicMock(
            returncode=1, stdout="", stderr="boom"))
        with pytest.raises(RuntimeError):
            dl.download_playlist("http://x", str(tmp_path))


# ---------------------------------------------------------------------------
# Channel/Playlist/Video — branches not exercised by patch_channel_data tests
# ---------------------------------------------------------------------------

class TestVideoModel:
    def test_video_thumbnail_default(self):
        from tutubo.channel import Video
        v = Video("abc123xyz12")
        assert "abc123xyz12" in v.thumbnail_url

    def test_video_thumbnail_override(self):
        from tutubo.channel import Video
        v = Video("v", thumbnail_url="http://t")
        assert v.thumbnail_url == "http://t"

    def test_video_repr(self):
        from tutubo.channel import Video
        v = Video("v", title="X")
        assert "X" in repr(v)

    def test_video_as_dict(self):
        from tutubo.channel import Video
        v = Video("v", title="X", description="d")
        d = v.as_dict
        assert d["videoId"] == "v"
        assert d["title"] == "X"
        assert "content_type" in d


class TestPlaylistInit:
    def test_invalid_url_raises(self):
        from tutubo.channel import Playlist
        with pytest.raises(ValueError):
            Playlist("https://youtube.com/watch?v=abc")

    def test_playlist_url(self):
        from tutubo.channel import Playlist
        p = Playlist("https://youtube.com/playlist?list=PLabc")
        assert p.playlist_url.endswith("?list=PLabc")
        # repr triggers .title which fetches; pre-seed _title to avoid network
        p._title = "Stub"
        assert "PLabc" in repr(p)

    def test_extract_video_ids_empty(self):
        from tutubo.channel import Playlist
        ids, cont = Playlist._extract_video_ids("{}")
        assert ids == []
        assert cont is None

    def test_extract_video_ids_section0_path(self):
        from tutubo.channel import Playlist
        data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
            {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [
                {"itemSectionRenderer": {"contents": [
                    {"playlistVideoListRenderer": {"contents": [
                        {"playlistVideoRenderer": {"videoId": "v1"}},
                        {"playlistVideoRenderer": {"videoId": "v2"}},
                        {"continuationItemRenderer": {"continuationEndpoint": {
                            "continuationCommand": {"token": "TOK"}
                        }}},
                    ]}}
                ]}}
            ]}}}}
        ]}}}
        import json as _j
        ids, cont = Playlist._extract_video_ids(_j.dumps(data))
        assert ids == ["v1", "v2"]
        assert cont == "TOK"

    def test_playlist_html_data_title_and_video_urls(self, monkeypatch):
        from tutubo.channel import Playlist
        # Build a fake initial-data blob and inject via a session.get returning HTML
        initial = {
            "metadata": {"playlistMetadataRenderer": {"title": "My PL"}},
            "contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
                {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [
                    {"itemSectionRenderer": {"contents": [
                        {"playlistVideoListRenderer": {"contents": [
                            {"playlistVideoRenderer": {"videoId": "v1"}},
                        ]}}
                    ]}}
                ]}}}}
            ]}}
        }
        ytcfg = {"INNERTUBE_API_KEY": "K"}
        html = (
            f'var ytInitialData = {json.dumps(initial)};\n'
            f'ytcfg.set({json.dumps(ytcfg)});'
        )

        class _Resp:
            def __init__(self, text): self.text = text
            def raise_for_status(self): pass

        class _Session:
            def get(self, *a, **kw): return _Resp(html)
            def post(self, *a, **kw): return _Resp(json.dumps({}))

        p = Playlist("https://youtube.com/playlist?list=PLx", session=_Session())
        assert p.title == "My PL"
        assert p.yt_api_key == "K"
        urls = p.video_urls
        assert urls == ["https://www.youtube.com/watch?v=v1"]
        # videos generator
        vids = list(p.videos)
        assert len(vids) == 1
        assert vids[0].video_id == "v1"
        assert "PLx" in repr(p)

    def test_playlist_continuation_post(self, monkeypatch):
        from tutubo.channel import Playlist
        # Use an instance with a manually-set initial state to test _continuation_post directly
        p = Playlist("https://youtube.com/playlist?list=PLx")
        p._ytcfg = {"INNERTUBE_API_KEY": "KEY"}

        class _Resp:
            text = '{"ok": true}'
            def raise_for_status(self): pass

        captured = {}

        class _Session:
            def post(self, url, **kw):
                captured["url"] = url
                captured["json"] = kw.get("json")
                return _Resp()

        p._session = _Session()
        out = p._continuation_post("TOK")
        assert out == '{"ok": true}'
        assert "KEY" in captured["url"]
        assert captured["json"]["continuation"] == "TOK"

    def test_playlist_title_missing(self, monkeypatch):
        from tutubo.channel import Playlist
        p = Playlist("https://youtube.com/playlist?list=PLx")
        # Set initial_data without metadata.playlistMetadataRenderer
        p._initial_data = {"foo": "bar"}
        assert p.title is None

    def test_extract_video_ids_continuation_path(self):
        from tutubo.channel import Playlist
        data = {
            "onResponseReceivedActions": [{
                "appendContinuationItemsAction": {
                    "continuationItems": [
                        {"playlistVideoRenderer": {"videoId": "v1"}},
                        {"playlistVideoRenderer": {"videoId": "v2"}},
                        {"playlistVideoRenderer": {"videoId": "v1"}},  # duplicate
                    ]
                }
            }]
        }
        ids, cont = Playlist._extract_video_ids(json.dumps(data))
        assert ids == ["v1", "v2"]
        assert cont is None


class TestChannelMisc:
    def test_keywords_string_form(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        ch._initial_data_cache[ch.channel_url] = {
            "metadata": {"channelMetadataRenderer": {"keywords": '"hip hop" rock'}}
        }
        kws = ch.keywords
        assert "hip hop" in kws
        assert "rock" in kws

    def test_keywords_empty_string(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        ch._initial_data_cache[ch.channel_url] = {
            "metadata": {"channelMetadataRenderer": {"keywords": ""}}
        }
        assert ch.keywords == []

    def test_keywords_list_form(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        ch._initial_data_cache[ch.channel_url] = {
            "metadata": {"channelMetadataRenderer": {"keywords": ["a", "b"]}}
        }
        assert ch.keywords == ["a", "b"]

    def test_extract_playlist_ids_empty(self):
        from tutubo.channel import Channel
        ids, cont = Channel._extract_playlist_ids({})
        assert ids == []

    def test_extract_playlist_ids_grid_form(self):
        from tutubo.channel import Channel
        data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
            {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [
                {"itemSectionRenderer": {"contents": [
                    {"gridRenderer": {"items": [
                        {"gridPlaylistRenderer": {"playlistId": "PL1"}},
                        {"lockupViewModel": {"contentId": "PL2"}},
                    ]}}
                ]}}
            ]}}}}
        ]}}}
        ids, _ = Channel._extract_playlist_ids(data)
        assert "PL1" in ids
        assert "PL2" in ids

    def test_repr(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@foo")
        assert "foo" in repr(ch)

    def test_metadata_properties_from_seeded_data(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        ch._initial_data_cache[ch.channel_url] = {
            "metadata": {"channelMetadataRenderer": {
                "title": "Some Channel", "externalId": "UCxxx",
                "vanityChannelUrl": "https://youtube.com/@x",
                "rssUrl": "http://rss",
                "description": "metadata desc",
                "availableCountryCodes": ["US"],
                "avatar": {"thumbnails": [{"url": "http://avatar"}]},
            }},
            "header": {"pageHeaderRenderer": {"content": {"pageHeaderViewModel": {
                "metadata": {"contentMetadataViewModel": {"metadataRows": [
                    {"metadataParts": [
                        {"text": {"content": "10K subscribers"}},
                    ]},
                    {"metadataParts": [
                        {"text": {"content": "120 videos"}},
                    ]},
                ]}},
                "description": {"descriptionPreviewViewModel": {
                    "description": {"content": "Header desc"}
                }},
            }}}}
        }
        assert ch.channel_name == "Some Channel"
        assert ch.channel_id == "UCxxx"
        assert ch.vanity_url == "https://youtube.com/@x"
        assert ch.title == "Some Channel"
        assert ch.description == "Header desc"  # header preferred
        assert ch.subscribers == "10K subscribers"
        assert ch.video_count_label == "120 videos"
        assert ch.thumbnail_url == "http://avatar"
        assert ch.available_countries == ["US"]
        assert ch.rss_url == "http://rss"
        # as_dict aggregates
        d = ch.as_dict
        assert d["channelId"] == "UCxxx"

    def test_description_falls_back_to_metadata(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        ch._initial_data_cache[ch.channel_url] = {
            "metadata": {"channelMetadataRenderer": {"description": "fallback"}}
        }
        assert ch.description == "fallback"

    def test_subscribers_missing_returns_empty(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        ch._initial_data_cache[ch.channel_url] = {
            "metadata": {"channelMetadataRenderer": {}},
        }
        assert ch.subscribers == ""
        assert ch.video_count_label == ""
        assert ch.thumbnail_url == ""

    def test_live_returns_none_when_no_data(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        # Make _get_data raise → live should return None
        def boom(url): raise RuntimeError("nope")
        ch._get_data = boom  # type: ignore
        assert ch.live is None

    def test_live_returns_none_when_no_video_id(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        ch._initial_data_cache[ch.channel_url + "/live"] = {}
        assert ch.live is None

    def test_live_returns_none_when_not_live(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        # video id present but not live
        ch._initial_data_cache[ch.channel_url + "/live"] = {
            "currentVideoEndpoint": {"watchEndpoint": {"videoId": "v"}},
            "videoDetails": {"isLiveContent": False},
        }
        ch._initial_data_cache[ch.channel_url] = {
            "metadata": {"channelMetadataRenderer": {}},
        }
        assert ch.live is None

    def test_live_returns_video_when_streaming(self):
        from tutubo.channel import Channel, Video
        ch = Channel("https://youtube.com/@x")
        ch._initial_data_cache[ch.channel_url + "/live"] = {
            "currentVideoEndpoint": {"watchEndpoint": {"videoId": "vlive"}},
            "videoDetails": {"isLiveContent": True},
            "contents": {"twoColumnWatchNextResults": {"results": {"results": {"contents": [
                {"videoPrimaryInfoRenderer": {"title": {"runs": [{"text": "Live Title"}]}}}
            ]}}}},
        }
        ch._initial_data_cache[ch.channel_url] = {
            "metadata": {"channelMetadataRenderer": {"keywords": ["news"]}},
        }
        v = ch.live
        assert isinstance(v, Video)
        assert v.video_id == "vlive"
        assert v.is_live is True
        assert v.title == "Live Title"

    def test_extract_items_with_visitor_data_and_continuation(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        data = {
            "responseContext": {"webResponseContextExtensionData": {
                "ytConfigData": {"visitorData": "VISITOR"}
            }},
            "contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
                {"tabRenderer": {
                    "endpoint": {"commandMetadata": {"webCommandMetadata": {
                        "url": "/@x/videos"
                    }}},
                    "content": {"richGridRenderer": {"contents": [
                        {"richItemRenderer": {"content": {"videoRenderer": {
                            "videoId": "v1",
                            "title": {"runs": [{"text": "title1"}]},
                            "shortViewCountText": {"simpleText": "100 views"},
                            "publishedTimeText": {"simpleText": "1 day ago"},
                        }}}},
                        {"continuationItemRenderer": {
                            "continuationEndpoint": {"continuationCommand": {
                                "token": "NEXT"
                            }}
                        }},
                    ]}}
                }}
            ]}}
        }
        import json as _j
        videos, cont = ch._extract_items(_j.dumps(data), "videos")
        assert len(videos) == 1
        assert videos[0].video_id == "v1"
        assert videos[0].view_count == "100 views"
        assert videos[0].published_time == "1 day ago"
        assert cont == "NEXT"
        assert ch._visitor_data == "VISITOR"

    def test_extract_items_continuation_response(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        data = {
            "onResponseReceivedActions": [{"appendContinuationItemsAction": {
                "continuationItems": [
                    {"richItemRenderer": {"content": {"videoRenderer": {
                        "videoId": "v2",
                        "title": {"runs": [{"text": "title2"}]},
                    }}}}
                ]
            }}]
        }
        import json as _j
        videos, cont = ch._extract_items(_j.dumps(data), "videos")
        assert len(videos) == 1
        assert videos[0].video_id == "v2"
        assert cont is None

    def test_extract_items_empty(self):
        from tutubo.channel import Channel
        ch = Channel("https://youtube.com/@x")
        v, c = ch._extract_items("{}", "videos")
        assert v == [] and c is None

    def test_metadata_rows_from_item_videoRenderer(self):
        from tutubo.channel import Channel
        item = {"richItemRenderer": {"content": {"videoRenderer": {
            "shortViewCountText": {"simpleText": "5K views"},
            "publishedTimeText": {"simpleText": "yesterday"},
        }}}}
        rows = Channel._metadata_rows_from_item(item)
        assert "5K views" in rows
        assert "yesterday" in rows

    def test_metadata_rows_from_item_lockup(self):
        from tutubo.channel import Channel
        item = {"richItemRenderer": {"content": {"lockupViewModel": {
            "metadata": {"lockupMetadataViewModel": {
                "metadata": {"contentMetadataViewModel": {"metadataRows": [
                    {"metadataParts": [{"text": {"content": "row1"}}]}
                ]}}
            }}
        }}}}
        rows = Channel._metadata_rows_from_item(item)
        assert "row1" in rows

    def test_title_and_description_from_item_lockup(self):
        from tutubo.channel import Channel
        item = {"richItemRenderer": {"content": {"lockupViewModel": {
            "metadata": {"lockupMetadataViewModel": {
                "title": {"content": "lockup title"}
            }}
        }}}}
        assert Channel._title_from_item(item) == "lockup title"
        # description from videoRenderer form
        item2 = {"richItemRenderer": {"content": {"videoRenderer": {
            "descriptionSnippet": {"runs": [{"text": "hi "}, {"text": "there"}]}
        }}}}
        assert Channel._description_from_item(item2) == "hi  there"

    def test_extract_playlist_ids_shelf_form(self):
        from tutubo.channel import Channel
        data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
            {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [
                {"itemSectionRenderer": {"contents": [
                    {"shelfRenderer": {"content": {"horizontalListRenderer": {"items": [
                        {"gridPlaylistRenderer": {"playlistId": "PLshelf"}},
                    ]}}}},
                ]}}
            ]}}}}
        ]}}}
        ids, _ = Channel._extract_playlist_ids(data)
        assert "PLshelf" in ids

    def test_video_id_from_item_reel(self):
        from tutubo.channel import Channel
        item = {"richItemRenderer": {"content": {"reelItemRenderer": {"videoId": "rv"}}}}
        assert Channel._video_id_from_item(item) == "rv"

    def test_video_id_from_item_lockup(self):
        from tutubo.channel import Channel
        item = {"richItemRenderer": {"content": {"lockupViewModel": {"contentId": "lv"}}}}
        assert Channel._video_id_from_item(item) == "lv"

    def test_video_id_from_item_none(self):
        from tutubo.channel import Channel
        assert Channel._video_id_from_item({}) is None

    def test_is_live_lockup_form(self):
        from tutubo.channel import Channel
        item = {"richItemRenderer": {"content": {"lockupViewModel": {
            "contentImage": {"thumbnailViewModel": {"overlays": [
                {"thumbnailBottomOverlayViewModel": {"badges": [
                    {"thumbnailBadgeViewModel": {"badgeStyle": "LIVE"}}
                ]}}
            ]}}
        }}}}
        assert Channel._is_live_from_item(item) is True

    def test_is_live_false_when_no_badges(self):
        from tutubo.channel import Channel
        assert Channel._is_live_from_item({}) is False


# ---------------------------------------------------------------------------
# PodcastPreview model
# ---------------------------------------------------------------------------

class TestPodcastPreview:
    def test_dict_and_repr(self):
        from tutubo.channel import PodcastPreview
        p = PodcastPreview(title="P", playlist_id="PL1",
                            episode_count="5", last_updated="today",
                            thumbnail_url="http://t")
        d = p.as_dict
        assert d["title"] == "P"
        assert d["playlistId"] == "PL1"
        assert "P" in repr(p)

    def test_get_returns_playlist(self):
        from tutubo.channel import PodcastPreview, Playlist
        p = PodcastPreview(title="X", playlist_id="PL1")
        assert isinstance(p.get(), Playlist)


# ---------------------------------------------------------------------------
# YoutubeMixPreview / RelatedSearch / RelatedVideoPreview model
# ---------------------------------------------------------------------------

class TestMiscModels:
    def test_youtube_mix_preview_as_dict(self):
        from tutubo.models import YoutubeMixPreview
        raw = {
            "playlistId": "RDmix",
            "title": {"simpleText": "Mix - X"},
            "thumbnail": {"thumbnails": [{"url": "http://i"}]},
        }
        m = YoutubeMixPreview(raw)
        assert m.thumbnail_url == "http://i"
        d = m.as_dict
        assert d["playlistId"] == "RDmix"

    def test_related_search(self):
        from tutubo.models import RelatedSearch
        from tutubo.search import YoutubeSearch
        rs = RelatedSearch({
            "query": {"runs": [{"text": "another query"}]},
            "thumbnail": {"thumbnails": [{"url": "http://t"}]},
        })
        assert rs.query == "another query"
        assert rs.thumbnail_url == "http://t"
        assert "another query" in str(rs)
        d = rs.as_dict
        assert d["query"] == "another query"
        # get returns YoutubeSearch
        assert isinstance(rs.get(), YoutubeSearch)

    def test_related_video_preview_as_dict(self):
        from tutubo.models import RelatedVideoPreview
        raw = {
            "videoId": "abc",
            "title": {"runs": [{"text": "T"}]},
            "ownerText": {"runs": [{"text": "C", "navigationEndpoint": {
                "commandMetadata": {"webCommandMetadata": {"url": "/c/x"}}
            }}]},
            "publishedTimeText": {"simpleText": ""},
            "viewCountText": {"simpleText": "0"},
            "shortViewCountText": {"simpleText": ""},
        }
        v = RelatedVideoPreview(raw)
        d = v.as_dict
        assert d["videoId"] == "abc"

    def test_videopreview_channel_id_fallback(self):
        from tutubo.models import VideoPreview
        v = VideoPreview({
            "videoId": "v",
            "title": {"runs": [{"text": "t"}]},
            "ownerText": {"runs": [{"text": "C"}]},
        })
        assert v.channel_id == ""
        assert v.channel_url == ""
        assert v.channel_thumbnail_url == ""

    def test_videopreview_view_count_runs(self):
        from tutubo.models import VideoPreview
        v = VideoPreview({
            "videoId": "v",
            "title": {"runs": [{"text": "t"}]},
            "ownerText": {"runs": [{"text": "C", "navigationEndpoint": {
                "commandMetadata": {"webCommandMetadata": {"url": "/c"}}
            }}]},
            "viewCountText": {"runs": [{"text": "1234 views"}]},
            "publishedTimeText": {"simpleText": ""},
            "shortViewCountText": {"simpleText": ""},
        })
        assert v.view_count == 1234

    def test_channel_preview_subscriber_runs_fallback(self):
        from tutubo.models import ChannelPreview
        cp = ChannelPreview({
            "channelId": "UC",
            "title": {"simpleText": "x"},
            "videoCountText": {"runs": [{"text": "5K subscribers"}]},
            "thumbnail": {"thumbnails": [{"url": "u"}]},
        })
        assert "5K" in cp.subscriber_count
        assert cp.video_count == 5  # int filter

    def test_videopreview_length_seconds_only(self):
        from tutubo.models import VideoPreview
        v = VideoPreview({
            "videoId": "v", "title": {"runs": [{"text": "t"}]},
            "ownerText": {"runs": [{"text": "C", "navigationEndpoint": {
                "commandMetadata": {"webCommandMetadata": {"url": "/c"}}
            }}]},
            "viewCountText": {"simpleText": "0"},
            "publishedTimeText": {"simpleText": ""},
            "shortViewCountText": {"simpleText": ""},
            "lengthText": {"simpleText": "30"},
        })
        assert v.length == 30

    def test_videopreview_length_hh_mm_ss(self):
        from tutubo.models import VideoPreview
        v = VideoPreview({
            "videoId": "v", "title": {"runs": [{"text": "t"}]},
            "ownerText": {"runs": [{"text": "C", "navigationEndpoint": {
                "commandMetadata": {"webCommandMetadata": {"url": "/c"}}
            }}]},
            "viewCountText": {"simpleText": "0"},
            "publishedTimeText": {"simpleText": ""},
            "shortViewCountText": {"simpleText": ""},
            "lengthText": {"simpleText": "1:02:03"},
        })
        assert v.length == 3723

    def test_videopreview_channel_thumbnail(self):
        from tutubo.models import VideoPreview
        v = VideoPreview({
            "videoId": "v", "title": {"runs": [{"text": "t"}]},
            "ownerText": {"runs": [{"text": "C", "navigationEndpoint": {
                "commandMetadata": {"webCommandMetadata": {"url": "/c"}}
            }}]},
            "viewCountText": {"simpleText": "0"},
            "publishedTimeText": {"simpleText": ""},
            "shortViewCountText": {"simpleText": ""},
            "channelThumbnailSupportedRenderers": {
                "channelThumbnailWithLinkRenderer": {
                    "thumbnail": {"thumbnails": [{"url": "u1"}, {"url": "u2"}]}
                }
            },
        })
        assert v.channel_thumbnail_url == "u2"

    def test_playlist_preview_thumbnails_property(self):
        from tutubo.models import PlaylistPreview
        pl = PlaylistPreview({
            "playlistId": "PL", "title": {"simpleText": "T"},
            "thumbnails": [{"thumbnails": [{"url": "u1"}]}, {"thumbnails": [{"url": "u2"}]}],
        })
        assert pl.thumbnail_url == "u2"

    def test_playlist_preview_featured_videos(self):
        from tutubo.models import PlaylistPreview
        raw = {
            "playlistId": "PL",
            "title": {"simpleText": "T"},
            "videos": [{"childVideoRenderer": {
                "videoId": "v1",
                "title": {"simpleText": "title1"},
            }}],
            "thumbnails": [{"thumbnails": [{"url": "u"}]}],
        }
        pl = PlaylistPreview(raw)
        feats = pl.featured_videos
        assert feats[0]["videoId"] == "v1"
        assert "T" == str(pl)
