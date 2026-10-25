"""tutubo as an arrkit indexer and download client: offline, with a fake YouTube, a fake yt-dlp and a structural stand-in for arrkit."""
import http.server
import importlib.metadata
import json
import os
import stat
import sys
import subprocess
import threading
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

import requests

from tutubo import arr, backoff

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import fake_arrkit  # noqa: E402

FAKE = Path(__file__).parent / "fixtures" / "fake_yt_dlp.py"
APHEX = {"resultType": "album", "browseId": "MPREb_1", "title": "Selected Ambient Works 85-92", "year": "1992", "isExplicit": False,
         "artists": [{"name": "Aphex Twin", "id": "UC1"}], "thumbnails": [{"url": "https://img/small"}, {"url": "https://img/big"}]}
OTHER = dict(APHEX, browseId="MPREb_2", title="Selected Ambient Works Volume II")
LIVE = dict(APHEX, browseId="MPREb_3", artists=[{"name": "Somebody Else"}])
ALBUM = {"audioPlaylistId": "OLAK5uy_x", "tracks": [
    {"videoId": "aaaaaaaaaaa", "title": "Xtal", "trackNumber": 1, "duration_seconds": 291},
    {"videoId": "bbbbbbbbbbb", "title": "Tha", "trackNumber": 2, "duration_seconds": 540}]}
SONG = {"resultType": "song", "videoId": "ccccccccccc", "title": "Windowlicker", "artists": [{"name": "Aphex Twin"}],
        "album": {"name": "Windowlicker", "id": "MPREb_9"}, "year": "1999", "duration_seconds": 366, "isExplicit": True,
        "videoType": "MUSIC_VIDEO_TYPE_ATV", "thumbnails": [{"url": "https://img/t"}]}
VIDEO = {"resultType": "video", "videoId": "ddddddddddd", "title": "Windowlicker (official video)", "artists": [{"name": "Aphex Twin"}],
         "videoType": "MUSIC_VIDEO_TYPE_OMV"}


class FakeBackend:
    calls = []

    def __init__(self, family):
        self.family = family

    def music(self, query, kind):
        FakeBackend.calls.append(("music", query, kind, self.family))
        return {"albums": [APHEX, OTHER, LIVE], "songs": [SONG, VIDEO, dict(SONG, videoId="")]}[kind]

    def album(self, browse_id):
        FakeBackend.calls.append(("album", browse_id))
        return ALBUM

    def videos(self, query, limit):
        FakeBackend.calls.append(("videos", query, limit))
        return [{"video_id": "eeeeeeeeeee", "title": "Aphex Twin - Xtal", "author": "Aphex Twin - Topic", "channel_id": "UC1", "length": 291},
                {"video_id": "fffffffffff", "title": "Xtal live", "author": "Some Fan", "channel_id": "UC2", "length": 0}]


class Reply:
    def __init__(self, body=None, status=200):
        self.body, self.status_code = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        yield json.dumps(self.body).encode()


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    for name in [m for m in sys.modules if m == "arrkit" or m.startswith("arrkit.")]:
        monkeypatch.delitem(sys.modules, name)
    fresh = {}
    fake_arrkit.install(fresh)
    for name, module in fresh.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(arr, "_built", {})
    monkeypatch.setattr(arr, "_workers", {})
    monkeypatch.setattr(arr, "_clients", {})
    FakeBackend.calls = []
    monkeypatch.setattr(arr, "pace", lambda delay: None)
    monkeypatch.setattr(arr.Tutubo, "backend", FakeBackend)
    monkeypatch.setattr(arr.TutuboClient, "backend", FakeBackend)


def indexer(**settings):
    return arr.Tutubo({"id": 3, "name": "Tube", "settings": settings})


# discovery

def entry_point(group):
    (point,) = [e for e in importlib.metadata.entry_points(group=group) if e.name == "tutubo"]
    return point


def test_the_entry_points_load_classes_that_derive_from_arrkits_bases():
    indexer_class, client_class = entry_point("arrkit.indexers").load(), entry_point("arrkit.clients").load()
    assert issubclass(indexer_class, fake_arrkit.Indexer) and issubclass(client_class, fake_arrkit.Direct)
    assert indexer_class is arr.Tutubo and client_class is arr.TutuboClient and arr.IMPLEMENTATION is arr.Tutubo
    assert indexer_class.API_VERSION == client_class.API_VERSION == 1
    assert indexer_class.implementation == client_class.implementation == "tutubo"


def test_the_classes_raise_arrkits_own_errors():
    with pytest.raises(fake_arrkit.IndexerError):
        indexer(source="radio").search("x")
    with pytest.raises(fake_arrkit.ClientError):
        arr.TutuboClient({"settings": {}}, "/state").add({"release_type": "album"})


def test_importing_tutubo_and_its_plugin_module_never_imports_arrkit():
    code = "import sys, tutubo, tutubo.arr; assert not [m for m in sys.modules if m.split('.')[0] == 'arrkit'], 'arrkit imported'"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_without_arrkit_the_plugin_names_are_missing_and_the_helpers_work(monkeypatch):
    monkeypatch.setattr(arr, "_built", {})
    for name in [m for m in sys.modules if m.startswith("arrkit.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "arrkit", None)
    with pytest.raises(AttributeError, match="needs arrkit"):
        arr.Tutubo
    assert not hasattr(arr, "TutuboClient")
    assert arr.holds("Björk - Homogenic", "bjork homogenic") is True
    assert arr.holds("Björk - Homogenic", "bjork vespertine") is False
    with pytest.raises(AttributeError):
        arr.Nothing


# indexer

def test_artist_and_album_find_that_album_and_no_other():
    found = indexer().search({"artist": "aphex twin", "album": "Selected Ambient Works 85-92", "title": "x"})
    assert [r["guid"] for r in found] == ["tutubo:album:MPREb_1"]
    r = found[0]
    assert (r["release_type"], r["artist"], r["album"], r["year"], r["protocol"], r["kind"]) == (
        "album", "Aphex Twin", "Selected Ambient Works 85-92", 1992, "youtube", "download")
    assert r["title"] == "Aphex Twin - Selected Ambient Works 85-92 (1992)"
    assert [t["video_id"] for t in r["tracks"]] == ["aaaaaaaaaaa", "bbbbbbbbbbb"] and r["track_count"] == 2
    assert r["seconds"] == 831 == r["duration_seconds"]
    assert r["playlist_id"] == "OLAK5uy_x" and r["url"].endswith("list=OLAK5uy_x") and r["entry"] == "MPREb_1"
    assert r["thumbnail"] == "https://img/big" and r["audio_only"] is True and r["published"] == "1992-01-01"


def test_the_album_search_asks_for_albums_with_artist_and_album_words_on_ipv4():
    indexer().search({"artist": "Aphex Twin", "album": "Selected Ambient Works"})
    assert FakeBackend.calls[0] == ("music", "Aphex Twin Selected Ambient Works", "albums", "ipv4")


def test_title_is_the_album_when_album_is_missing_and_accents_do_not_matter():
    found = indexer().search({"artist": "aphéx twin", "title": "SELECTED ambient works volume ii"})
    assert [r["guid"] for r in found] == ["tutubo:album:MPREb_2"]


def test_only_the_first_albums_get_their_track_list():
    found = indexer(resolve="1").search({"artist": "Aphex Twin", "album": "Selected Ambient Works"})
    assert [bool(r["tracks"]) for r in found] == [True, False]
    assert [c for c in FakeBackend.calls if c[0] == "album"] == [("album", "MPREb_1")]


def test_a_track_list_that_cannot_be_read_does_not_lose_the_album(monkeypatch):
    monkeypatch.setattr(FakeBackend, "album", lambda self, b: (_ for _ in ()).throw(RuntimeError("HTTP 500")))
    found = indexer().search({"artist": "Aphex Twin", "album": "Selected Ambient Works 85-92"})
    assert found[0]["tracks"] == [] and found[0]["guid"] == "tutubo:album:MPREb_1"


def test_a_track_query_finds_songs_and_marks_official_audio():
    found = indexer().search({"artist": "Aphex Twin", "track": "Windowlicker"})
    assert [r["guid"] for r in found] == ["tutubo:video:ccccccccccc", "tutubo:video:ddddddddddd"]
    song, video = found
    assert (song["audio_only"], song["topic"], song["album"], song["year"], song["explicit"], song["seconds"]) == (
        True, True, "Windowlicker", 1999, True, 366)
    assert song["url"] == "https://music.youtube.com/watch?v=ccccccccccc" and "official audio" in song["tags"]
    assert video["audio_only"] is False and video["url"].startswith("https://www.youtube.com/watch?v=") and video["tags"] == []


def test_a_plain_term_searches_songs():
    assert len(indexer().search("windowlicker")) == 2
    assert FakeBackend.calls[0][:3] == ("music", "windowlicker", "songs")


def test_youtube_source_reads_topic_channels_as_artists():
    found = indexer(source="youtube").search({"artist": "Aphex Twin", "track": "Xtal"})
    assert FakeBackend.calls == [("videos", "Aphex Twin Xtal audio", 20)]
    assert [(r["topic"], r["artist"], r["audio_only"]) for r in found] == [(True, "Aphex Twin", True), (False, "", False)]
    assert found[1]["duration_seconds"] is None and found[0]["channel"] == "Aphex Twin - Topic"


def test_both_sources_are_added_up_and_cut_to_max_results():
    assert len(indexer(source="both", max_results="3").search({"artist": "Aphex Twin", "track": "Windowlicker"})) == 3


def test_delivery_stream_changes_kind_and_protocol_only():
    r = indexer(delivery="stream").search({"artist": "Aphex Twin", "track": "Windowlicker"})[0]
    assert (r["kind"], r["protocol"]) == ("stream", "stream")
    with pytest.raises(fake_arrkit.IndexerError):
        indexer(delivery="sideways").search("x")


def test_nothing_to_look_for_asks_nothing():
    assert indexer().search({}) == [] and FakeBackend.calls == []


def test_a_bad_source_is_refused():
    with pytest.raises(fake_arrkit.IndexerError):
        indexer(source="radio").search("x")


def test_the_shared_pause_stops_a_search_before_any_request():
    backoff.shared().mark_blocked("search")
    with pytest.raises(fake_arrkit.IndexerError, match="YouTube is asking for a check: search requests paused until"):
        indexer().search("windowlicker")
    assert FakeBackend.calls == []


def test_a_pause_in_media_archivist_stops_a_search_too(monkeypatch):
    asked = []
    until = datetime.fromtimestamp(time.time() + 7200, tz=timezone.utc).isoformat()

    def get(url, headers=None, **kw):
        asked.append(("GET", url, headers))
        return Reply({"kinds": {"search": {"paused": True, "until": until}, "download": {"paused": False}}})
    monkeypatch.setattr(requests, "get", get)
    ix = indexer(media_archivist_url="http://archivist:8488/", media_archivist_api_key="k")
    with pytest.raises(fake_arrkit.IndexerError, match="paused until"):
        ix.search("windowlicker")
    assert asked == [("GET", "http://archivist:8488/api/v1/youtube/backoff", {"Accept": "application/json", "X-Api-Key": "k"})]
    assert FakeBackend.calls == []


def test_an_archivist_that_does_not_answer_is_ignored(monkeypatch):
    def get(*a, **kw):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", get)
    assert indexer(media_archivist_url="http://archivist:8488").search("windowlicker")


def test_a_failure_on_youtube_is_an_indexer_error_and_a_bot_check_pauses(monkeypatch):
    def refuse(self, query, kind):
        raise RuntimeError("HTTP 500")
    monkeypatch.setattr(FakeBackend, "music", refuse)
    with pytest.raises(fake_arrkit.IndexerError, match="RuntimeError: HTTP 500"):
        indexer().search("x")
    assert backoff.shared().blocked_until("search") is None


def test_the_indexer_test_makes_no_request_and_reports_a_pause():
    ok, msg = indexer().test()
    assert ok and FakeBackend.calls == []
    backoff.shared().mark_blocked("search")
    assert indexer().test()[0] is False


def test_pacing_waits_between_requests(monkeypatch):
    monkeypatch.undo()
    arr._last[0] = 0
    slept = []
    monkeypatch.setattr(arr.time, "sleep", slept.append)
    arr.pace(5)
    arr.pace(5)
    assert len(slept) == 1 and 4 < slept[0] <= 5


# client

@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_CONTROL", str(tmp_path / "control.json"))
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(tmp_path / "calls.jsonl"))
    FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(arr.TutuboClient, "start", lambda self: None)

    class Box:
        root = tmp_path
        downloads = tmp_path / "music"

        def mode(self, mode="ok", **kw):
            (tmp_path / "control.json").write_text(json.dumps({"mode": mode, **kw}))

        def calls(self):
            p = tmp_path / "calls.jsonl"
            return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

        def client(self, **settings):
            (tmp_path / "state").mkdir(exist_ok=True)
            return arr.TutuboClient({"id": 1, "settings": {"download_dir": str(self.downloads), "yt_dlp": str(FAKE), "embed": "true",
                                                           **settings}}, str(tmp_path / "state"))
    b = Box()
    b.downloads.mkdir()
    b.mode()
    return b


class Ctl:
    cancelled = False

    def set(self, **changes):
        pass

    progress = on_cancel = set


def album_release(**kw):
    return indexer().search({"artist": "Aphex Twin", "album": "Selected Ambient Works 85-92"})[0] | kw


def run_all(client):
    done = []
    for _ in range(10):
        job = client.queue.run_one(client.run, client.waiting)
        if job is None:
            return done
        done.append(client.queue.get(job))
    raise AssertionError("the queue never settled: a job went back to the queue every time it ran")


def test_an_album_becomes_numbered_audio_files_in_the_jobs_folder(box):
    c = box.client()
    jid = c.add(album_release())
    (job,) = run_all(c)
    assert job["status"] == "Completed" and job["files"] == ["01 - Xtal.m4a", "02 - Tha.m4a"]
    folder = box.downloads / job["folder"]
    assert sorted(p.name for p in folder.iterdir()) == job["files"]
    row = c.status()[0]
    assert (row["client_id"], row["state"], row["files"], row["path"]) == (jid, "completed", job["files"], str(folder))
    assert row["size"] == 200


def test_it_asks_yt_dlp_for_audio_only_with_tags_and_cover_on_ipv4(box):
    c = box.client()
    c.add(album_release())
    run_all(c)
    first, second = box.calls()
    assert first[-2:] == ["--", "https://www.youtube.com/watch?v=aaaaaaaaaaa"] and "bbbbbbbbbbb" in second[-1]
    assert {"-x", "--no-playlist", "--force-ipv4", "--embed-metadata", "--embed-thumbnail"} <= set(first)
    assert first[first.index("-f") + 1] == "bestaudio/best" and first[first.index("--audio-format") + 1] == "best"
    parsed = [first[i + 1] for i, a in enumerate(first) if a == "--parse-metadata"]
    assert "Aphex Twin:%(artist)s" in parsed and "Selected Ambient Works 85-92:%(album)s" in parsed and "1:%(track_number)s" in parsed
    assert "1992:%(release_year)s" in parsed and "Xtal:%(title)s" in parsed


def test_tags_with_colons_and_percent_signs_stay_literal(box):
    c = box.client()
    argv = c.ytdlp("https://x", "/s", "stem", {"artist": "AC:DC", "album": "100% Live", "title": "T"}, 1)
    assert "AC\\:DC:%(artist)s" in argv and "100%% Live:%(album)s" in argv


def test_embedding_and_the_format_can_be_changed(box):
    c = box.client(embed="false", audio_format="mp3", ip_family="any")
    argv = c.ytdlp("https://x", "/s", "stem", {}, None)
    assert "--embed-metadata" not in argv and "--parse-metadata" not in argv and "--force-ipv4" not in argv
    assert argv[argv.index("--audio-format") + 1] == "mp3"


def test_a_single_track_is_one_run_named_by_its_title(box):
    c = box.client()
    c.add(indexer().search({"artist": "Aphex Twin", "track": "Windowlicker"})[0])
    (job,) = run_all(c)
    assert job["files"] == ["Windowlicker.m4a"] and len(box.calls()) == 1


def test_file_names_stay_within_255_bytes_with_room_for_yt_dlps_suffixes(box):
    c = box.client()
    long = {**album_release(), "tracks": [{"video_id": "aaaaaaaaaaa", "title": "漢" * 200, "track_number": 1}]}
    c.add(long)
    (job,) = run_all(c)
    (name,) = job["files"]
    assert len(name.encode()) <= 255 - 16 and name.endswith(".m4a")
    assert (box.downloads / job["folder"] / name).exists()


def test_a_track_list_missing_from_the_release_is_read_when_the_job_runs(box):
    c = box.client()
    c.add(album_release(tracks=[]))
    (job,) = run_all(c)
    assert job["files"] == ["01 - Xtal.m4a", "02 - Tha.m4a"]
    assert ("album", "MPREb_1") in FakeBackend.calls


def test_a_bot_check_pauses_the_queue_and_keeps_the_job(box):
    box.mode("botcheck")
    c = box.client()
    jid = c.add(album_release())
    (job,) = run_all(c)
    assert job["status"] == "Queued" and "YouTube is asking for a check: download requests paused until" in job["error"]
    assert backoff.shared().blocked_until("download")
    assert c.queue.run_one(c.run, c.waiting) is None and len(box.calls()) == 1
    row = c.status()[0]
    assert row["state"] == "queued" and "paused until" in row["message"]
    assert not (box.downloads / job["folder"]).exists()


def test_a_pause_set_by_another_program_stops_the_job_before_yt_dlp_starts(box):
    backoff.shared().mark_blocked("download")
    c = box.client()
    c.add(album_release())
    job = c.queue.load()[0]
    assert c.run(job, Ctl()) == "blocked" and box.calls() == []


def test_a_pause_in_media_archivist_stops_downloads(box, monkeypatch):
    until = datetime.fromtimestamp(time.time() + 7200, tz=timezone.utc).isoformat()
    monkeypatch.setattr(requests, "get", lambda *a, **k: Reply({"kinds": {"download": {"paused": True, "until": until}}}))
    c = box.client(media_archivist_url="http://archivist:8488")
    c.add(album_release())
    assert c.queue.run_one(c.run, c.waiting) is None and box.calls() == []
    assert "paused until" in c.status()[0]["message"]


def test_a_failed_track_fails_the_job_and_says_how_far_it_got(box):
    box.mode("fail")
    c = box.client()
    c.add(album_release())
    (job,) = run_all(c)
    assert job["status"] == "Failed" and "yt-dlp failed: ERROR: [youtube] abc: Video unavailable" in job["error"]
    assert backoff.shared().blocked_until("download") is None
    assert not (box.downloads / job["folder"]).exists()


def test_a_cancelled_download_leaves_no_partial_file(box):
    box.mode("slow")
    c = box.client()
    jid = c.add(album_release())
    worker = threading.Thread(target=lambda: c.queue.run_one(c.run, c.waiting))
    worker.start()
    for _ in range(100):
        if (box.root / "calls.jsonl.started").exists():
            break
        time.sleep(0.05)
    folder = box.downloads / c.queue.get(jid)["folder"]
    assert any(folder.rglob("*.part"))
    c.remove(jid)
    worker.join(10)
    assert not worker.is_alive()
    assert not folder.exists() or not any(folder.rglob("*"))


def test_removing_a_finished_job_with_its_files(box):
    c = box.client()
    jid = c.add(album_release())
    (job,) = run_all(c)
    c.remove(jid, delete_files=True)
    assert not (box.downloads / job["folder"]).exists() and c.status() == []


def test_a_release_that_names_nothing_is_refused(box):
    c = box.client()
    with pytest.raises(fake_arrkit.ClientError):
        c.add({"release_type": "track", "video_id": "short"})
    with pytest.raises(fake_arrkit.ClientError):
        c.add({"release_type": "album"})


def test_the_client_test_reports_a_missing_program_and_a_pause(box, monkeypatch):
    assert box.client(embed="false").test()[0] is True
    with monkeypatch.context() as m:
        m.setattr(arr.shutil, "which", lambda name: None if name == "ffmpeg" else str(FAKE))
        ok, msg = box.client().test()
    assert not ok and "ffmpeg is not installed" in msg
    assert box.client(yt_dlp="no-such-yt-dlp").test() == (False, "yt-dlp is not installed")
    backoff.shared().mark_blocked("download")
    ok, msg = box.client().test()
    assert not ok and "paused until" in msg


def test_a_download_that_works_resets_the_wait_of_an_expired_pause(box):
    path = backoff.shared().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kinds": {"download": {"retry_at": 1.0, "wait_s": 7200.0, "at": 0.0}}}))
    c = box.client()
    c.add(album_release())
    (job,) = run_all(c)
    assert job["status"] == "Completed" and json.loads(path.read_text())["kinds"] == {}


# real music client

def test_a_bot_check_while_building_the_music_client_is_tried_once_and_pauses_search(monkeypatch):
    tries = []

    def refuse(**kw):
        tries.append(kw)
        raise RuntimeError("HTTP Error 429: Too Many Requests")
    monkeypatch.setattr(arr, "YTMusic", refuse)
    with pytest.raises(backoff.BackedOff):
        arr.Backend("ipv4").music("x", "songs")
    assert len(tries) == 1 and backoff.shared().blocked_until("search")
    with pytest.raises(backoff.BackedOff):
        arr.Backend("ipv4").album("MPREb_1")
    assert len(tries) == 1


def test_the_music_client_is_built_once_per_family(monkeypatch):
    built = []

    class Client:
        def __init__(self, **kw):
            built.append(kw)

        def search(self, query, filter=None):
            return []

        def get_album(self, browse_id):
            return {}
    monkeypatch.setattr(arr, "YTMusic", Client)
    for _ in range(3):
        arr.Backend("ipv4").music("x", "songs")
        arr.Backend("ipv4").album("a")
    arr.Backend("ipv6").music("x", "songs")
    assert len(built) == 2


# media-archivist answers

@pytest.fixture
def archivist():
    seen, mode = [], {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("X-Api-Key")))
            if self.path.startswith("/other"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
                return
            if mode.get("redirect"):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/other")
                self.end_headers()
                return
            body = mode.get("body") or b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body) + mode.get("lie", 0)))
            self.end_headers()
            try:
                if mode.get("trickle"):
                    for i in range(len(body)):
                        self.wfile.write(body[i:i + 1])
                        self.wfile.flush()
                        time.sleep(0.4)
                else:
                    self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield types.SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", seen=seen, mode=mode)
    server.shutdown()
    server.server_close()


def paused_body(until):
    return json.dumps({"kinds": {"search": {"paused": True, "until": until}}}).encode()


def test_a_redirect_from_the_archivist_is_not_followed_and_the_key_stays_home(archivist):
    archivist.mode["redirect"] = True
    assert arr.remote_pause(archivist.url, "secret", "search") == 0
    assert archivist.seen == [("/api/v1/youtube/backoff", "secret")]


def test_a_server_that_trickles_its_answer_is_given_up_on_at_the_deadline(archivist):
    archivist.mode.update(trickle=True, body=paused_body("2099-01-01T00:00:00Z") + b" " * 40)
    started = time.monotonic()
    assert arr.remote_pause(archivist.url, "", "search", timeout=1) == 0
    assert time.monotonic() - started < 2


def test_an_oversized_answer_is_not_read_to_the_end(archivist):
    archivist.mode["body"] = paused_body("2099-01-01T00:00:00Z") + b" " * (arr.REMOTE_BYTES * 2)
    assert arr.remote_pause(archivist.url, "", "search") == 0


def test_a_remote_pause_never_runs_longer_than_the_local_maximum(archivist):
    archivist.mode["body"] = paused_body("2099-01-01T00:00:00Z")
    until = arr.remote_pause(archivist.url, "", "search")
    assert 0 < until <= time.time() + backoff.MAX_WAIT_S


def test_a_short_remote_pause_is_kept_as_it_is(archivist):
    soon = datetime.fromtimestamp(time.time() + 600, tz=timezone.utc).isoformat()
    archivist.mode["body"] = paused_body(soon)
    assert abs(arr.remote_pause(archivist.url, "", "search") - (time.time() + 600)) < 5


# building the classes

def test_threads_reading_the_plugin_name_during_the_first_build_get_one_class(monkeypatch):
    real, found, gate = arr._build, [], threading.Barrier(8)

    def slow():
        time.sleep(0.2)
        real()
    monkeypatch.setattr(arr, "_build", slow)
    monkeypatch.setattr(arr, "_built", {})

    def read():
        gate.wait()
        found.append(arr.Tutubo)
    threads = [threading.Thread(target=read) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(found) == 8 and len({id(c) for c in found}) == 1


# titles

HOSTILE = ["../../escape", "a/b\\c", "x\x00y", "Foo %(live", "%(id)s", "%(title)s%%", "con:aux", ".. ", "漢" * 300]


def test_hostile_titles_stay_inside_the_download_folder_and_in_one_piece(box):
    c = box.client()
    for title in HOSTILE:
        c.add({"release_type": "album", "browse_id": "MPREb_1", "title": title, "artist": "A",
               "tracks": [{"video_id": "aaaaaaaaaaa", "title": title, "track_number": 1},
                          {"video_id": "bbbbbbbbbbb", "title": title, "track_number": 2}]})
    jobs = run_all(c) + run_all(c)
    root = os.path.realpath(box.downloads)
    assert len(jobs) == len(HOSTILE) and all(j["status"] == "Completed" for j in jobs)
    for job in jobs:
        folder = os.path.realpath(box.downloads / job["folder"])
        assert os.path.dirname(folder) == root
        for name in job["files"]:
            assert os.path.dirname(os.path.realpath(os.path.join(folder, name))) == folder
    assert not (box.root / "escape").exists() and not list(box.root.glob("escape*"))
    assert sorted(p.name for p in box.root.iterdir()) == ["calls.jsonl", "control.json", "music", "state"]


def test_percent_signs_in_a_title_do_not_reach_yt_dlp_as_a_template():
    argv = arr.ClientPlugin.ytdlp(types.SimpleNamespace(settings={"yt_dlp": "y", "ip_family": "any", "audio_format": "best", "embed": "false"}),
                                  "https://x", "/s", "01 - %(id)s Foo %(live", {})
    assert argv[argv.index("-o") + 1] == "/s/01 - %%(id)s Foo %%(live.%(ext)s"


def test_a_child_left_behind_holding_stderr_does_not_hold_up_the_worker(box):
    box.mode("orphan")
    c = box.client()
    c.add(album_release())
    started = time.monotonic()
    (job,) = run_all(c)
    assert time.monotonic() - started < 3
    assert job["status"] == "Failed" and "Video unavailable" in job["error"]


def test_cookies_tokens_and_signed_addresses_never_reach_a_job_error(box):
    box.mode("leak")
    c = box.client()
    c.add(album_release())
    (job,) = run_all(c)
    assert job["status"] == "Failed" and "yt-dlp failed" in job["error"]
    for secret in ("COOKIEVALUE", "TOKENVALUE", "SIGVALUE", "googlevideo", "203.0.113.9"):
        assert secret not in job["error"]


def test_only_the_tail_of_a_huge_stderr_is_kept(tmp_path):
    file = (tmp_path / "e").open("w+b")
    file.write(b"x" * 200_000 + b"\nlast line\n")
    text = arr.stderr_tail(file, 1000)
    assert len(text) == 1000 and text.endswith("last line\n") and file.closed
