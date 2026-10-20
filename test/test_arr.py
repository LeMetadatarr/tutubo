"""tutubo as an arrkit indexer and download client: offline, with a fake YouTube and a fake yt-dlp."""
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("arrkit")
from arrkit import net, plugins  # noqa: E402
from arrkit.clients import ClientError  # noqa: E402
from arrkit.indexers import IndexerError  # noqa: E402

from tutubo import arr, backoff  # noqa: E402

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


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    FakeBackend.calls = []
    monkeypatch.setattr(arr, "pace", lambda delay: None)
    monkeypatch.setattr(arr.Tutubo, "backend", FakeBackend)
    monkeypatch.setattr(arr.TutuboClient, "backend", FakeBackend)


def indexer(**settings):
    return arr.Tutubo({"id": 3, "name": "Tube", "settings": settings})


# discovery

def test_arrkit_lists_both_plugins_under_one_name():
    assert plugins.classes("indexer", ["tutubo"])["tutubo"] is arr.Tutubo
    assert plugins.classes("client", ["tutubo"])["tutubo"] is arr.TutuboClient
    assert arr.Tutubo.API_VERSION == arr.TutuboClient.API_VERSION == plugins.API_VERSION


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
    with pytest.raises(IndexerError):
        indexer(delivery="sideways").search("x")


def test_nothing_to_look_for_asks_nothing():
    assert indexer().search({}) == [] and FakeBackend.calls == []


def test_a_bad_source_is_refused():
    with pytest.raises(IndexerError):
        indexer(source="radio").search("x")


def test_the_shared_pause_stops_a_search_before_any_request():
    backoff.shared().mark_blocked("search")
    with pytest.raises(IndexerError, match="YouTube is asking for a check: search requests paused until"):
        indexer().search("windowlicker")
    assert FakeBackend.calls == []


def test_a_pause_in_media_archivist_stops_a_search_too(monkeypatch):
    asked = []
    until = "2099-01-01T00:00:00+00:00"

    def request(method, url, headers=None, **kw):
        asked.append((method, url, headers))
        return net.Response(200, {}, json.dumps({"kinds": {"search": {"paused": True, "until": until}, "download": {"paused": False}}}).encode())
    monkeypatch.setattr(net, "request", request)
    ix = indexer(media_archivist_url="http://archivist:8488/", media_archivist_api_key="k")
    with pytest.raises(IndexerError, match="paused until 2099-01-01"):
        ix.search("windowlicker")
    assert asked == [("GET", "http://archivist:8488/api/v1/youtube/backoff", {"Accept": "application/json", "X-Api-Key": "k"})]
    assert FakeBackend.calls == []


def test_an_archivist_that_does_not_answer_is_ignored(monkeypatch):
    def request(*a, **kw):
        raise net.NetError("down")
    monkeypatch.setattr(net, "request", request)
    assert indexer(media_archivist_url="http://archivist:8488").search("windowlicker")


def test_a_failure_on_youtube_is_an_indexer_error_and_a_bot_check_pauses(monkeypatch):
    def refuse(self, query, kind):
        raise RuntimeError("HTTP 500")
    monkeypatch.setattr(FakeBackend, "music", refuse)
    with pytest.raises(IndexerError, match="RuntimeError: HTTP 500"):
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
    until = "2099-01-01T00:00:00Z"
    monkeypatch.setattr(net, "request", lambda *a, **k: net.Response(200, {}, json.dumps(
        {"kinds": {"download": {"paused": True, "until": until}}}).encode()))
    c = box.client(media_archivist_url="http://archivist:8488")
    c.add(album_release())
    assert c.queue.run_one(c.run, c.waiting) is None and box.calls() == []
    assert "2099-01-01" in c.status()[0]["message"]


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
    with pytest.raises(ClientError):
        c.add({"release_type": "track", "video_id": "short"})
    with pytest.raises(ClientError):
        c.add({"release_type": "album"})


def test_the_client_test_reports_a_missing_program_and_a_pause(box):
    assert box.client().test()[0] is True
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
