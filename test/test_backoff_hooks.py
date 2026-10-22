"""Every place tutubo talks to YouTube reads the shared pause first and writes it on a bot check."""
import json
import os
import stat
from pathlib import Path

import pytest
import requests

from tutubo import _innertube, backoff
from tutubo.backoff import BackedOff

FAKE = Path(__file__).parent / "fixtures" / "fake_yt_dlp.py"


class Reply:
    def __init__(self, status, text="", payload=None):
        self.status_code, self.text, self._payload = status, text, payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code}")
            err.response = self
            raise err


class Session:
    def __init__(self, *replies):
        self.replies, self.sent = list(replies), 0

    def _answer(self, *a, **kw):
        self.sent += 1
        return self.replies.pop(0)
    get = post = _answer


# innertube search

def test_a_429_from_the_search_endpoint_pauses_search():
    with pytest.raises(RuntimeError, match="HTTP 429"):
        _innertube.search("x", session=Session(Reply(429)))
    assert backoff.shared().blocked_until("search")


def test_a_paused_search_sends_nothing():
    backoff.shared().mark_blocked("search")
    session = Session(Reply(200))
    with pytest.raises(BackedOff):
        _innertube.search("x", session=session)
    assert session.sent == 0


def test_a_search_that_answers_ends_the_pause_of_its_kind_only():
    backoff.shared().mark_blocked("download")
    backoff.shared().mark_blocked("search")
    backoff.shared().mark_clear("search")
    assert _innertube.search("x", session=Session(Reply(200, payload={"a": 1}))) == {"a": 1}
    assert backoff.shared().blocked_until("search") is None and backoff.shared().blocked_until("download")


def test_an_error_that_is_not_a_bot_check_pauses_nothing():
    with pytest.raises(RuntimeError, match="HTTP 500"):
        _innertube.search("x", session=Session(Reply(500)))
    assert not any(v["paused"] for v in backoff.shared().state().values())


# channel and playlist pages

def test_a_playlist_page_that_asks_for_a_check_pauses_listing():
    from tutubo.channel import Playlist
    page = Playlist("https://www.youtube.com/playlist?list=PL12345678901", session=Session(Reply(429, "Sign in to confirm you're not a bot")))
    with pytest.raises(requests.HTTPError):
        page.html
    assert backoff.shared().blocked_until("listing")


def test_a_paused_listing_fetches_no_page():
    from tutubo.channel import Playlist
    backoff.shared().mark_blocked("listing")
    session = Session(Reply(200, "<html>"))
    with pytest.raises(BackedOff):
        Playlist("https://www.youtube.com/playlist?list=PL12345678901", session=session).html
    assert session.sent == 0


def test_a_403_page_that_asks_to_confirm_you_are_not_a_bot_pauses_listing():
    from tutubo.channel import Playlist
    page = Playlist("https://www.youtube.com/playlist?list=PL12345678901", session=Session(Reply(403, "Sign in to confirm you’re not a bot")))
    with pytest.raises(requests.HTTPError):
        page.html
    assert backoff.shared().blocked_until("listing")


# YouTube Music

def test_a_music_search_refused_with_429_pauses_search(monkeypatch):
    from tutubo import ytmus

    class Music:
        def search(self, query):
            raise RuntimeError("Server returned HTTP 429: Too Many Requests")
    monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **k: Music())
    with pytest.raises(BackedOff):
        list(ytmus.search_yt_music("x"))
    assert backoff.shared().blocked_until("search")


def test_a_paused_music_search_does_not_call_ytmusicapi(monkeypatch):
    from tutubo import YoutubeMusicSearch, ytmus
    called = []

    class Music:
        def search(self, *a, **k):
            called.append(a)
            return []
    monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **k: Music())
    backoff.shared().mark_blocked("search")
    with pytest.raises(BackedOff):
        list(YoutubeMusicSearch("x").iterate_tracks())
    assert called == []


def _channel_with_a_key(session):
    from tutubo.channel import Channel
    page = Channel("https://www.youtube.com/@someone", session=session)
    page._ytcfg = {"INNERTUBE_API_KEY": "key"}  # so the only request is the continuation
    return page


def _playlist_with_a_key(session):
    from tutubo.channel import Playlist
    page = Playlist("https://www.youtube.com/playlist?list=PL12345678901", session=session)
    page._ytcfg = {"INNERTUBE_API_KEY": "key"}
    return page


def test_a_channel_page_that_asks_for_a_check_pauses_listing_and_a_paused_listing_fetches_none():
    from tutubo.channel import Channel
    session = Session(Reply(429, ""))
    with pytest.raises(requests.HTTPError):
        Channel("https://www.youtube.com/@someone", session=session)._get_html("https://www.youtube.com/@someone")
    assert backoff.shared().blocked_until("listing")
    with pytest.raises(BackedOff):
        Channel("https://www.youtube.com/@someone", session=session)._get_html("https://www.youtube.com/@other")
    assert session.sent == 1


@pytest.mark.parametrize("make", [_channel_with_a_key, _playlist_with_a_key], ids=["channel", "playlist"])
def test_a_continuation_checks_the_pause_first_and_a_429_starts_it(make):
    session = Session(Reply(429, ""), Reply(200, "{}"))
    with pytest.raises(requests.HTTPError):
        make(session)._continuation_post("token")
    assert backoff.shared().blocked_until("listing")
    with pytest.raises(BackedOff):
        make(session)._continuation_post("token")
    assert session.sent == 1


@pytest.mark.parametrize("make", [_channel_with_a_key, _playlist_with_a_key], ids=["channel", "playlist"])
def test_a_continuation_that_answers_ends_an_expired_pause(make):
    path = backoff.shared().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kinds": {"listing": {"retry_at": 1.0, "wait_s": 7200.0, "at": 0.0}}}))
    assert make(Session(Reply(200, "{}")))._continuation_post("token") == "{}"
    assert json.loads(path.read_text())["kinds"] == {}


# innertube search without a session (urllib)

def _urllib_answers(monkeypatch, code=None):
    import io
    from urllib import error
    calls = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        calls.append(req)
        if code:
            raise error.HTTPError(req.full_url, code, "refused", {}, io.BytesIO(b""))
        return Answer(b'{"a": 1}')
    monkeypatch.setattr(_innertube.urllib_request, "urlopen", urlopen)
    return calls


def test_a_429_on_the_urllib_path_pauses_search_and_the_next_call_sends_nothing(monkeypatch):
    calls = _urllib_answers(monkeypatch, 429)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        _innertube.search("x")
    assert backoff.shared().blocked_until("search") and len(calls) == 1
    with pytest.raises(BackedOff):
        _innertube.search("x")
    assert len(calls) == 1


def test_a_500_on_the_urllib_path_pauses_nothing(monkeypatch):
    _urllib_answers(monkeypatch, 500)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        _innertube.search("x")
    assert backoff.shared().blocked_until("search") is None


def test_an_answer_on_the_urllib_path_ends_an_expired_pause(monkeypatch):
    _urllib_answers(monkeypatch)
    path = backoff.shared().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kinds": {"search": {"retry_at": 1.0, "wait_s": 7200.0, "at": 0.0}}}))
    assert _innertube.search("x") == {"a": 1}
    assert json.loads(path.read_text())["kinds"] == {}


# YouTube Music detail calls

class Detail:
    """A ytmusicapi stand-in: one search hit of ``result_type``, and detail calls that fail with ``error`` and count themselves."""

    def __init__(self, result_type, error=None):
        self.hit = {"resultType": result_type, "browseId": "MPREb_1", "title": "t", "artists": []}
        self.error, self.calls = error, []

    def search(self, *a, **k):
        return [dict(self.hit)]

    def _answer(self, name):
        self.calls.append(name)
        if self.error:
            raise RuntimeError(self.error)
        return {}

    def get_album(self, browse_id):
        return self._answer("get_album")

    def get_playlist(self, browse_id):
        return self._answer("get_playlist")

    def get_artist(self, browse_id):
        return self._answer("get_artist")


def _get_album_through_its_playlist(ytm):
    from tutubo import ytmus
    return ytmus.get_album("MPREb_1", "PLabc")


def _get_album(ytm):
    from tutubo import ytmus
    return ytmus.get_album("MPREb_1")


def _search_yt_music(ytm):
    from tutubo import ytmus
    return list(ytmus.search_yt_music("x"))


def _iterate(method):
    def run(ytm):
        from tutubo import YoutubeMusicSearch
        return list(getattr(YoutubeMusicSearch("x"), method)())
    return run


SITES = [  # (name, what the search returns, how to reach the detail call, the call it makes)
    ("get_album through its playlist", "album", _get_album_through_its_playlist, "get_playlist"),
    ("get_album", "album", _get_album, "get_album"),
    ("search_yt_music album", "album", _search_yt_music, "get_album"),
    ("search_yt_music playlist", "playlist", _search_yt_music, "get_playlist"),
    ("search_yt_music artist", "artist", _search_yt_music, "get_artist"),
    ("iterate_albums", "album", _iterate("iterate_albums"), "get_album"),
    ("iterate_artists", "artist", _iterate("iterate_artists"), "get_artist"),
    ("iterate_playlists", "playlist", _iterate("iterate_playlists"), "get_playlist"),
    ("iterate_all album", "album", _iterate("iterate_all"), "get_album"),
    ("iterate_all playlist", "playlist", _iterate("iterate_all"), "get_playlist"),
    ("iterate_all artist", "artist", _iterate("iterate_all"), "get_artist"),
]


def _client(monkeypatch, result_type, error=None):
    from tutubo import ytmus
    ytm = Detail(result_type, error)
    monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **k: ytm)
    return ytm


@pytest.mark.parametrize("name,result_type,run,call", SITES, ids=[s[0] for s in SITES])
def test_a_paused_search_kind_does_not_reach_the_music_client_for_details(monkeypatch, name, result_type, run, call):
    ytm = _client(monkeypatch, result_type)
    backoff.shared().mark_blocked("search")
    with pytest.raises(BackedOff):
        run(ytm)
    assert ytm.calls == []


@pytest.mark.parametrize("name,result_type,run,call", SITES, ids=[s[0] for s in SITES])
def test_a_429_from_a_music_detail_call_pauses_search_and_stops_the_run(monkeypatch, name, result_type, run, call):
    ytm = _client(monkeypatch, result_type, "HTTP 429: Too Many Requests")
    with pytest.raises(BackedOff):
        run(ytm)
    assert backoff.shared().blocked_until("search")
    assert ytm.calls == [call]
    with pytest.raises(BackedOff):
        run(ytm)
    assert ytm.calls == [call]


@pytest.mark.parametrize("name,result_type,run,call", SITES, ids=[s[0] for s in SITES])
def test_a_music_detail_call_that_answers_ends_an_expired_pause(monkeypatch, name, result_type, run, call):
    ytm = _client(monkeypatch, result_type)
    path = backoff.shared().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kinds": {"search": {"retry_at": 1.0, "wait_s": 7200.0, "at": 0.0}}}))
    run(ytm)
    assert ytm.calls[-1] == call
    assert json.loads(path.read_text())["kinds"] == {}


def test_a_music_detail_call_that_fails_for_another_reason_is_skipped_without_a_pause(monkeypatch):
    ytm = _client(monkeypatch, "album", "HTTP 500")
    assert _search_yt_music(ytm) == []
    assert backoff.shared().blocked_until("search") is None and ytm.calls == ["get_album"]


def test_an_album_whose_playlist_lookup_fails_for_another_reason_falls_back_to_the_album_call(monkeypatch):
    class Half(Detail):
        def get_playlist(self, browse_id):
            raise RuntimeError("HTTP 500")
    from tutubo import ytmus
    ytm = Half("album")
    monkeypatch.setattr(ytmus, "_get_ytmus", lambda *a, **k: ytm)
    assert ytmus.get_album("MPREb_1", "PLabc")["browseId"] == "MPREb_1"
    assert backoff.shared().blocked_until("search") is None


# yt-dlp

@pytest.fixture
def ytdlp(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "yt-dlp").symlink_to(FAKE)
    FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_YTDLP_CONTROL", str(tmp_path / "control.json"))
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(tmp_path / "calls.jsonl"))

    (tmp_path / "control.json").write_text(json.dumps({"mode": "ok"}))
    return tmp_path


def test_a_download_stopped_by_a_bot_check_pauses_every_download(ytdlp):
    from tutubo.download import download, download_playlist
    ytdlp.joinpath("control.json").write_text(json.dumps({"mode": "botcheck"}))
    with pytest.raises(BackedOff, match="download requests paused"):
        download("https://www.youtube.com/watch?v=aaaaaaaaaaa", str(ytdlp / "out"))
    calls = len(ytdlp.joinpath("calls.jsonl").read_text().splitlines())
    with pytest.raises(BackedOff):
        download_playlist("https://www.youtube.com/playlist?list=PL12345678901", str(ytdlp / "out"))
    with pytest.raises(BackedOff):
        download("https://www.youtube.com/watch?v=bbbbbbbbbbb", str(ytdlp / "out"))
    assert len(ytdlp.joinpath("calls.jsonl").read_text().splitlines()) == calls


def test_a_failed_download_that_is_not_a_bot_check_pauses_nothing(ytdlp):
    from tutubo.download import download
    ytdlp.joinpath("control.json").write_text(json.dumps({"mode": "fail"}))
    with pytest.raises(RuntimeError, match="Video unavailable"):
        download("https://www.youtube.com/watch?v=aaaaaaaaaaa", str(ytdlp / "out"))
    assert backoff.shared().blocked_until("download") is None


def test_a_download_that_works_resets_the_wait_of_an_expired_pause(ytdlp):
    from tutubo.download import download
    path = backoff.shared().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kinds": {"download": {"retry_at": 1.0, "wait_s": 7200.0, "at": 0.0}}}))
    assert download("https://www.youtube.com/watch?v=aaaaaaaaaaa", str(ytdlp / "out"))
    assert json.loads(path.read_text())["kinds"] == {}


# watch pages

OK_PAGE = ('<script>var ytInitialPlayerResponse = {"videoDetails": {"videoId": "abcdefghijk"}, '
           '"playabilityStatus": {"status": "OK"}};</script>')
BOT_PAGE = ('<script>var ytInitialPlayerResponse = {"videoDetails": {"videoId": "abcdefghijk"}, '
            '"playabilityStatus": {"status": "LOGIN_REQUIRED", '
            '"reason": "Sign in to confirm you\\u2019re not a bot"}};</script>')


def test_a_paused_details_kind_reads_no_watch_page():
    from tutubo.captions import list_caption_tracks
    backoff.shared().mark_blocked("details")
    session = Session(Reply(200, OK_PAGE))
    with pytest.raises(BackedOff, match="details requests paused"):
        list_caption_tracks("abcdefghijk", session=session)
    assert session.sent == 0


def test_a_watch_page_that_asks_to_confirm_you_are_not_a_bot_pauses_details():
    from tutubo.captions import list_caption_tracks
    with pytest.raises(BackedOff):
        list_caption_tracks("abcdefghijk", session=Session(Reply(200, BOT_PAGE)))
    assert backoff.shared().blocked_until("details")
    assert backoff.shared().blocked_until("download") is None


def test_a_429_on_the_watch_page_pauses_details():
    from tutubo.captions import list_caption_tracks
    with pytest.raises(BackedOff):
        list_caption_tracks("abcdefghijk", session=Session(Reply(429, "")))
    assert backoff.shared().blocked_until("details")


def test_a_watch_page_that_answers_ends_an_expired_details_pause():
    from tutubo.captions import list_caption_tracks
    path = backoff.shared().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kinds": {"details": {"retry_at": 1.0, "wait_s": 7200.0, "at": 0.0}}}))
    assert list_caption_tracks("abcdefghijk", session=Session(Reply(200, OK_PAGE))) == []
    assert json.loads(path.read_text())["kinds"] == {}


def test_an_unplayable_video_is_a_caption_error_and_pauses_nothing():
    from tutubo.captions import CaptionError, list_caption_tracks
    page = OK_PAGE.replace('"status": "OK"', '"status": "ERROR", "reason": "Video unavailable"')
    with pytest.raises(CaptionError, match="not playable"):
        list_caption_tracks("abcdefghijk", session=Session(Reply(200, page)))
    assert not any(v["paused"] for v in backoff.shared().state().values())
