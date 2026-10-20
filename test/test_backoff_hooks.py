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
