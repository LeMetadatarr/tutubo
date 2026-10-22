"""Video details, caption files and original audio for a corpus, and the command line that fetches them. No network: watch pages
are served from hand-built player responses in YouTube's shape, caption files from a server on 127.0.0.1, and yt-dlp is a fake."""
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from tutubo import backoff, fetch
from tutubo.backoff import BackedOff
from tutubo.captions import CaptionError

FAKE = Path(__file__).parent / "fixtures" / "fake_yt_dlp_fetch.py"
VID, OTHER = "abcdefghijk", "zyxwvutsrqp"


# watch pages

def _aformat(itag, mime, rate, track=None, **extra):
    f = {"itag": itag, "mimeType": mime, "bitrate": 130000, "averageBitrate": 129000, "audioSampleRate": rate,
         "audioChannels": 2, "contentLength": "4200000", **extra}
    if track:
        f["audioTrack"] = track
    return f


M4A = _aformat(140, 'audio/mp4; codecs="mp4a.40.2"', "44100")
OPUS = _aformat(251, 'audio/webm; codecs="opus"', "48000")
VIDEO = {"itag": 137, "mimeType": 'video/mp4; codecs="avc1.640028"', "bitrate": 4000000}
TT = "https://www.youtube.com/api/timedtext?v=abcdefghijk&lang="


def _manual(lang, name):
    return {"baseUrl": f"{TT}{lang}", "name": {"simpleText": name}, "vssId": f".{lang}", "languageCode": lang,
            "isTranslatable": True}


def _asr(lang):
    return {"baseUrl": f"{TT}{lang}&kind=asr", "name": {"simpleText": "auto"}, "vssId": f"a.{lang}", "languageCode": lang,
            "kind": "asr", "isTranslatable": True}


def _player(vid=VID, tracks=(), translations=(), audio=(M4A, OPUS), status="OK", reason=None):
    return {
        "videoDetails": {"videoId": vid, "title": "Título original", "lengthSeconds": "258", "channelId": "UC0123456789abcdefghijkl",
                         "author": "Canal", "isLiveContent": False},
        "playabilityStatus": {"status": status, **({"reason": reason} if reason else {})},
        "microformat": {"playerMicroformatRenderer": {"uploadDate": "2023-04-07T05:00:12-07:00",
                                                      "publishDate": "2023-04-07T05:00:12-07:00",
                                                      "title": {"simpleText": "Translated title"}}},
        "streamingData": {"adaptiveFormats": [VIDEO, *audio]},
        "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": list(tracks),
                                                         "translationLanguages": list(translations)}},
    }


NORMAL = _player(tracks=[_manual("fr", "French"), _asr("pt")])
ONLY_AUTOMATIC = _player(tracks=[_asr("pt")])
TRANSLATED = _player(tracks=[_asr("pt")], translations=[{"languageCode": "en", "languageName": {"simpleText": "English"}}])
DUBBED = _player(tracks=[_asr("pt")], audio=[
    _aformat(251, 'audio/webm; codecs="opus"', "48000",
             {"displayName": "Portuguese (Brazil) original", "id": "pt-BR.4", "audioIsDefault": True}),
    _aformat(251, 'audio/webm; codecs="opus"', "48000",
             {"displayName": "English (United States)", "id": "en-US.3", "audioIsDefault": False})])
UNPLAYABLE = _player(status="ERROR", reason="Video unavailable")


def _page(player):
    return f"<html><script>var ytInitialPlayerResponse = {json.dumps(player)};</script></html>"


class Reply:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.content = status, text, text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Session:
    """Serves watch pages from ``pages`` (video id -> player response or Reply) and passes any other address to the local
    caption server."""

    def __init__(self, pages):
        self.pages, self.watch_reads = pages, []

    def get(self, url, **kw):
        if "youtube.com/watch" in url:
            vid = parse_qs(urlparse(url).query)["v"][0]
            self.watch_reads.append(vid)
            page = self.pages[vid]
            return page if isinstance(page, Reply) else Reply(200, _page(page))
        assert url.startswith("http://127.0.0.1:"), url
        return requests.get(url, timeout=10)


def test_details_of_a_normal_video():
    d = fetch.video_details(VID, session=Session({VID: NORMAL}))
    assert (d.video_id, d.title, d.channel_id, d.channel) == (VID, "Título original", "UC0123456789abcdefghijkl", "Canal")
    assert d.duration_s == 258 and d.upload_date == "2023-04-07T05:00:12-07:00" and d.is_live_content is False
    assert [(t.itag, t.codec, t.container, t.sample_rate, t.channels, t.original) for t in d.audio_tracks] == [
        (140, "mp4a.40.2", "mp4", 44100, 2, True), (251, "opus", "webm", 48000, 2, True)]
    assert [(t.language, t.kind) for t in d.caption_tracks] == [("fr", "manual"), ("pt", "asr")]


def test_details_of_a_video_with_only_automatic_captions():
    d = fetch.video_details(VID, session=Session({VID: ONLY_AUTOMATIC}))
    assert [(t.language, t.kind, t.is_translation) for t in d.caption_tracks] == [("pt", "asr", False)]


def test_details_mark_machine_translations():
    d = fetch.video_details(VID, session=Session({VID: TRANSLATED}))
    assert [(t.language, t.kind, t.is_translation, t.source_language) for t in d.caption_tracks] == [
        ("pt", "asr", False, None), ("en", "translation", True, "pt")]
    assert all("url" not in t for t in d.as_dict["caption_tracks"])


def test_details_of_a_dubbed_video_tell_the_original_track_from_the_dub():
    d = fetch.video_details(VID, session=Session({VID: DUBBED}))
    assert [(t.language, t.original, t.default) for t in d.audio_tracks] == [("pt-BR", True, True), ("en-US", False, False)]


def test_tracks_that_do_not_say_which_is_original_are_unknown():
    player = json.loads(json.dumps(DUBBED).replace(" original", ""))
    assert [t.original for t in fetch.video_details(VID, session=Session({VID: player})).audio_tracks] == [None, None]


def test_an_unplayable_video_raises_and_pauses_nothing():
    with pytest.raises(CaptionError, match="not playable"):
        fetch.video_details(VID, session=Session({VID: UNPLAYABLE}))
    assert not any(v["paused"] for v in backoff.shared().state().values())


def test_a_page_for_another_video_is_refused():
    with pytest.raises(CaptionError, match="requested"):
        fetch.video_details(VID, session=Session({VID: _player(vid=OTHER)}))


def test_details_are_not_read_while_paused():
    backoff.shared().mark_blocked("details")
    session = Session({VID: NORMAL})
    with pytest.raises(BackedOff):
        fetch.video_details(VID, session=session)
    assert session.watch_reads == []


# caption files

class Captions(BaseHTTPRequestHandler):
    hits = []
    broken = True  # lang "ee" answers HTTP 500 while this is set

    def do_GET(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        Captions.hits.append(q)
        if q["lang"] == "xx":
            self._send(429, b"Too Many Requests")
        elif q["lang"] == "ee" and Captions.broken:
            self._send(500, b"Internal Server Error")
        elif q["lang"] == "zz":
            self._send(200, b"")
        else:
            self._send(200, f"{q['fmt']} {q['lang']} {q.get('kind', 'manual')} {q.get('tlang', '-')}".encode())

    def _send(self, status, body):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    Captions.hits, Captions.broken = [], True
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Captions)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/api/timedtext?v={VID}"
    httpd.shutdown()
    httpd.server_close()


def _entries(base, query, formats=("json3", "srv1", "vtt"), name=""):
    return [{"ext": f, "url": f"{base}&{query}&fmt={f}", "name": name} for f in formats]


def _info(base, subtitles=None, automatic=None):
    subtitles = {"fr": _entries(base, "lang=fr", name="French")} if subtitles is None else subtitles
    automatic = {"pt-orig": _entries(base, "lang=pt&kind=asr"), "pt": _entries(base, "lang=pt&kind=asr"),
                 "en": _entries(base, "lang=pt&kind=asr&tlang=en")} if automatic is None else automatic
    return {"id": VID, "subtitles": subtitles, "automatic_captions": automatic}


def test_offered_captions_are_classified_from_their_addresses(server):
    tracks = [(o.track.language, o.track.kind, o.track.is_translation, o.track.source_kind)
              for o in fetch.offered_captions(_info(server))]
    assert tracks == [("fr", "manual", False, None), ("pt", "asr", False, None), ("en", "translation", True, "asr")]


def test_entries_from_a_streaming_manifest_are_not_caption_files(server):
    hls = [{"ext": "vtt", "url": f"{server}&caps=asr&lang=en", "protocol": "m3u8_native"}]
    info = _info(server, subtitles={}, automatic={"en": hls, "de": [{**hls[0], "url": f"{server}&caps=asr&lang=de"}],
                                                  "en-orig": _entries(server, "lang=en&kind=asr")})
    (offered,) = fetch.offered_captions(info)
    assert (offered.track.language, offered.track.kind) == ("en", "asr")
    assert set(offered.formats) == {"json3", "srv1", "vtt"} and "kind=asr" in offered.formats["vtt"]


def test_only_tracks_the_watch_page_lists_are_fetched(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server))
    code, _ = _run([VID, "--dest", str(tmp_path), "--gap", "0", "--no-audio"],
                   Session({VID: _player(tracks=[_manual("fr", "French")])}))
    assert code == 0 and sorted(os.listdir(tmp_path / "captions")) == [f"{VID}.fr.manual.json3", f"{VID}.fr.manual.vtt"]


def test_original_tracks_are_written_as_served_and_translations_left_out(server, tmp_path):
    files = fetch.fetch_captions(VID, tmp_path, info=_info(server), session=Session({}))
    assert sorted(os.listdir(tmp_path / "captions")) == [
        f"{VID}.fr.manual.json3", f"{VID}.fr.manual.vtt", f"{VID}.pt.asr.json3", f"{VID}.pt.asr.vtt"]
    assert (tmp_path / "captions" / f"{VID}.pt.asr.json3").read_text() == "json3 pt asr -"
    assert all(f.error is None and f.bytes for f in files)
    assert not any("tlang" in hit for hit in Captions.hits)


def test_kinds_choose_the_tracks(server, tmp_path):
    files = fetch.fetch_captions(VID, tmp_path, kinds=("asr",), formats=("vtt",), info=_info(server), session=Session({}))
    assert [(f.language, f.kind, f.format) for f in files] == [("pt", "asr", "vtt")]


def test_an_empty_file_or_a_missing_format_is_reported_and_the_rest_written(server, tmp_path):
    info = _info(server, subtitles={"zz": _entries(server, "lang=zz")},
                 automatic={"pt-orig": _entries(server, "lang=pt&kind=asr", formats=("json3",))})
    files = {(f.language, f.format): f for f in fetch.fetch_captions(VID, tmp_path, info=info, session=Session({}))}
    assert files["zz", "json3"].error == "YouTube served an empty caption file"
    assert files["pt", "vtt"].error == "not offered as vtt"
    assert files["pt", "json3"].error is None and files["pt", "json3"].bytes
    assert sorted(os.listdir(tmp_path / "captions")) == [f"{VID}.pt.asr.json3"]


def test_a_429_from_the_caption_server_pauses_downloads_and_stops(server, tmp_path):
    info = _info(server, subtitles={"xx": _entries(server, "lang=xx")})
    with pytest.raises(BackedOff, match="download requests paused"):
        fetch.fetch_captions(VID, tmp_path, info=info, session=Session({}))
    assert len(Captions.hits) == 1 and backoff.shared().blocked_until("download")


# audio

AUDIO = {"format_id": "140", "ext": "m4a", "acodec": "mp4a.40.2", "asr": 44100, "audio_channels": 2, "abr": 129.5,
         "language": "pt", "format_note": "Portuguese original (default), medium"}


@pytest.fixture
def ytdlp(tmp_path, monkeypatch):
    wrapper = tmp_path / "yt-dlp"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv("TUTUBO_YTDLP", str(wrapper))
    monkeypatch.setenv("FAKE_YTDLP_CONTROL", str(tmp_path / "control.json"))
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(tmp_path / "calls.jsonl"))

    def control(**c):
        (tmp_path / "control.json").write_text(json.dumps({"mode": "ok", "audio": AUDIO, "size": 1000, **c}))

    def calls():
        log = tmp_path / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    control()
    return control, calls


def test_audio_is_the_original_track_in_its_own_codec(ytdlp, tmp_path):
    _, calls = ytdlp
    got = fetch.fetch_audio(VID, tmp_path / "out")
    assert Path(got.path) == tmp_path / "out" / "audio" / f"{VID}.m4a" and got.bytes == 1000
    assert (got.codec, got.sample_rate, got.channels, got.format_id) == ("mp4a.40.2", 44100, 2, "140")
    argv = calls()[-1]["argv"]
    assert argv[argv.index("-f") + 1] == fetch.AUDIO_FORMAT and "format_note*=original" in fetch.AUDIO_FORMAT
    assert "--continue" in argv and "--force-ipv4" in argv
    assert not {"-x", "--extract-audio", "--audio-format", "--recode-video", "--remux-video"} & set(argv)


def test_a_bot_check_from_yt_dlp_pauses_downloads_and_the_next_call_sends_nothing(ytdlp, tmp_path):
    control, calls = ytdlp
    control(mode="botcheck")
    with pytest.raises(BackedOff):
        fetch.fetch_audio(VID, tmp_path)
    sent = len(calls())
    with pytest.raises(BackedOff):
        fetch.fetch_audio(VID, tmp_path)
    assert len(calls()) == sent and backoff.shared().blocked_until("download")


def test_a_failure_that_is_not_a_bot_check_pauses_nothing(ytdlp, tmp_path):
    control, _ = ytdlp
    control(mode="fail")
    with pytest.raises(fetch.FetchError, match="Video unavailable"):
        fetch.fetch_audio(VID, tmp_path)
    assert backoff.shared().blocked_until("download") is None


def test_an_interrupted_download_resumes_from_its_partial_file(ytdlp, tmp_path):
    control, calls = ytdlp
    control(mode="interrupt")
    with pytest.raises(fetch.FetchError, match="connection reset"):
        fetch.fetch_audio(VID, tmp_path)
    assert (tmp_path / "audio" / f"{VID}.m4a.part").stat().st_size == 500
    control()
    got = fetch.fetch_audio(VID, tmp_path)
    assert calls()[-1]["resumed_from"] == 500 and got.bytes == 1000
    assert sorted(os.listdir(tmp_path / "audio")) == [f"{VID}.m4a"]


def test_fresh_information_is_reused_and_not_left_behind(ytdlp, tmp_path):
    _, calls = ytdlp
    fetch.fetch_audio(VID, tmp_path, info={"id": VID})
    call = calls()[-1]
    assert call["loaded"] == VID and fetch._watch_url(VID) not in call["argv"]
    assert os.listdir(tmp_path / "audio") == [f"{VID}.m4a"]


# command line

def _run(argv, session):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fetch.main(argv, session=session)
    out = [json.loads(line) for line in buf.getvalue().splitlines()]
    return code, out


def test_one_video_lands_as_audio_captions_and_a_sidecar(ytdlp, server, tmp_path):
    control, calls = ytdlp
    control(info=_info(server))
    dest = tmp_path / "job"
    code, events = _run([VID, "--dest", str(dest), "--gap", "0"], Session({VID: NORMAL}))
    assert code == 0
    assert [e["event"] for e in events][-1] == "done" and any(e["event"] == "progress" for e in events)
    assert sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()) == [
        f"audio/{VID}.m4a", f"captions/{VID}.fr.manual.json3", f"captions/{VID}.fr.manual.vtt",
        f"captions/{VID}.pt.asr.json3", f"captions/{VID}.pt.asr.vtt", f"meta/{VID}.json"]
    text = (dest / "meta" / f"{VID}.json").read_text()
    meta = json.loads(text)
    assert (meta["video_id"], meta["title"], meta["duration_s"], meta["upload_date"]) == (
        VID, "Título original", 258, "2023-04-07T05:00:12-07:00")
    assert meta["audio"] == {"file": f"audio/{VID}.m4a", "format_id": "140", "ext": "m4a", "codec": "mp4a.40.2",
                             "sample_rate": 44100, "channels": 2, "bitrate_kbps": 129.5, "language": "pt",
                             "note": "Portuguese original (default), medium", "original": True, "bytes": 1000}
    assert {(c["file"], c["kind"], c["format"]) for c in meta["captions"]} == {
        (f"captions/{VID}.fr.manual.json3", "manual", "json3"), (f"captions/{VID}.fr.manual.vtt", "manual", "vtt"),
        (f"captions/{VID}.pt.asr.json3", "asr", "json3"), (f"captions/{VID}.pt.asr.vtt", "asr", "vtt")}
    assert [(t["language"], t["kind"]) for t in meta["caption_tracks"]] == [("fr", "manual"), ("pt", "asr")]
    assert meta["tools"]["yt-dlp"] == "2026.10.21" and meta["tools"]["tutubo"] and meta["tools"]["python"]
    assert {"yt-dlp-ejs", "deno"} <= set(meta["tools"])
    assert "://" not in text
    assert sum("--dump-single-json" in c["argv"] for c in calls()) == 1


def test_a_finished_video_is_skipped_without_a_request(ytdlp, server, tmp_path):
    control, calls = ytdlp
    control(info=_info(server))
    argv = [VID, "--dest", str(tmp_path), "--gap", "0"]
    assert _run(argv, Session({VID: NORMAL}))[0] == 0
    sent, session = len(calls()), Session({VID: NORMAL})
    code, events = _run(argv, session)
    assert code == 0 and [e["event"] for e in events] == ["skip"]
    assert session.watch_reads == [] and len(calls()) == sent


def test_a_bot_check_stops_the_run_with_its_own_exit_status(ytdlp, tmp_path):
    _, calls = ytdlp
    bot = _player(status="LOGIN_REQUIRED", reason="Sign in to confirm you’re not a bot")
    session = Session({VID: bot, OTHER: _player(vid=OTHER)})
    code, events = _run([VID, OTHER, "--dest", str(tmp_path), "--gap", "0"], session)
    assert code == fetch.EXIT_PAUSED == 75
    assert events[-1]["event"] == "paused" and events[-1]["kind"] == "details" and events[-1]["until"]
    assert session.watch_reads == [VID] and not (tmp_path / "meta").exists()
    assert not any("--dump-single-json" in c["argv"] or "-f" in c["argv"] for c in calls())


def test_a_failed_video_does_not_stop_the_next(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server))
    code, events = _run([OTHER, VID, "--dest", str(tmp_path), "--gap", "0"], Session({OTHER: UNPLAYABLE, VID: NORMAL}))
    assert code == fetch.EXIT_ERROR
    assert [(e["event"], e["video_id"]) for e in events if e["event"] != "progress"] == [("error", OTHER), ("done", VID)]


def test_details_and_captions_only(ytdlp, server, tmp_path):
    control, calls = ytdlp
    control(info=_info(server))
    code, _ = _run([VID, "--dest", str(tmp_path), "--gap", "0", "--no-audio"], Session({VID: NORMAL}))
    assert code == 0 and json.loads((tmp_path / "meta" / f"{VID}.json").read_text())["audio"] is None
    assert not (tmp_path / "audio").exists()
    assert all("-f" not in c["argv"] for c in calls())


def test_the_command_line_refuses_a_bad_id_and_exits_75_while_paused(tmp_path):
    env = {**os.environ, "TUTUBO_YTDLP": str(tmp_path / "no-such-yt-dlp")}
    bad = subprocess.run([sys.executable, "-m", "tutubo.fetch", "../etc", "--dest", str(tmp_path)], capture_output=True,
                         text=True, env=env)
    assert bad.returncode == 2 and "not a YouTube video id" in bad.stderr
    backoff.shared().mark_blocked("details")
    paused = subprocess.run([sys.executable, "-m", "tutubo.fetch", VID, "--dest", str(tmp_path), "--gap", "0"],
                            capture_output=True, text=True, env=env, timeout=120)
    assert paused.returncode == 75
    assert json.loads(paused.stdout.splitlines()[-1])["event"] == "paused"


# a bot check yt-dlp only warns about, and a video that did not finish

def _sidecar(dest):
    return json.loads((dest / "meta" / f"{VID}.json").read_text())


def test_a_bot_check_that_yt_dlp_only_warns_about_pauses_downloads_and_stops_the_run(ytdlp, server, tmp_path):
    control, calls = ytdlp
    control(mode="warn_botcheck", info=_info(server))
    code, events = _run([VID, OTHER, "--dest", str(tmp_path), "--gap", "0"], Session({VID: NORMAL, OTHER: NORMAL}))
    assert code == 75 and events[-1]["event"] == "paused" and events[-1]["kind"] == "download"
    assert backoff.shared().blocked_until("download") and not (tmp_path / "meta").exists()
    assert sum("--dump-single-json" in c["argv"] for c in calls()) == 1  # the second video was not even looked at


def test_a_listed_track_that_yt_dlp_does_not_offer_is_an_error_and_the_video_is_not_done(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server, subtitles={}, automatic={}))
    argv = [VID, "--dest", str(tmp_path), "--gap", "0", "--no-audio"]
    session = Session({VID: NORMAL})
    code, events = _run(argv, session)
    assert code == 1 and [e["event"] for e in events] == ["error"] and "did not offer" in events[0]["error"]
    meta = _sidecar(tmp_path)
    assert meta["complete"] is False and {(c["language"], c["kind"]) for c in meta["captions"]} == {("fr", "manual"), ("pt", "asr")}
    assert all(c["error"] for c in meta["captions"])
    code, events = _run(argv, session)
    assert session.watch_reads == [VID, VID] and code == 1  # not skipped: the next run tries again


def test_a_caption_server_error_leaves_the_video_incomplete_until_a_rerun_gets_it(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server, subtitles={"ee": _entries(server, "lang=ee")}, automatic={}))
    argv = [VID, "--dest", str(tmp_path), "--gap", "0", "--no-audio"]
    session = Session({VID: _player(tracks=[_manual("ee", "E")])})
    code, events = _run(argv, session)
    assert code == 1 and events[-1]["event"] == "error" and "HTTP 500" in events[-1]["error"]
    assert _sidecar(tmp_path)["complete"] is False
    Captions.broken = False
    code, events = _run(argv, session)
    assert code == 0 and events[-1]["event"] == "done" and _sidecar(tmp_path)["complete"] is True
    assert _run(argv, session)[1][-1]["event"] == "skip"


def test_a_dropped_connection_leaves_the_video_incomplete(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server))

    class Dropped(Session):
        def get(self, url, **kw):
            if "youtube.com/watch" in url:
                return super().get(url, **kw)
            raise requests.ConnectionError("connection reset by peer")
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0", "--no-audio"], Dropped({VID: NORMAL}))
    assert code == 1 and events[-1]["event"] == "error" and not (tmp_path / "captions").exists()
    assert _sidecar(tmp_path)["complete"] is False


def test_a_video_fetched_with_other_options_is_fetched_again(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server))
    assert _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({VID: NORMAL}))[0] == 0
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0", "--formats", "vtt"], Session({VID: NORMAL}))
    assert code == 0 and events[-1]["event"] == "done"
    assert _sidecar(tmp_path)["request"]["formats"] == ["vtt"]


def test_a_video_that_finished_says_so(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server))
    assert _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({VID: NORMAL}))[0] == 0
    assert _sidecar(tmp_path)["complete"] is True and "skipped" not in _sidecar(tmp_path)


@pytest.mark.parametrize("gone", [f"audio/{VID}.m4a", f"captions/{VID}.pt.asr.vtt"])
def test_a_finished_video_with_a_missing_file_is_fetched_again(ytdlp, server, tmp_path, gone):
    control, _ = ytdlp
    control(info=_info(server))
    argv = [VID, "--dest", str(tmp_path), "--gap", "0"]
    assert _run(argv, Session({VID: NORMAL}))[0] == 0
    (tmp_path / gone).unlink()
    session = Session({VID: NORMAL})
    code, events = _run(argv, session)
    assert code == 0 and events[-1]["event"] == "done" and session.watch_reads == [VID]
    assert (tmp_path / gone).is_file()


def test_a_sidecar_from_a_run_that_did_not_finish_is_never_written(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(mode="interrupt", info=_info(server))
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({VID: NORMAL}))
    assert code == 1 and events[-1]["event"] == "error" and "connection reset" in events[-1]["error"]
    assert not (tmp_path / "meta").exists()


def test_a_bot_check_in_the_middle_of_the_captions_writes_no_sidecar(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server, subtitles={"xx": _entries(server, "lang=xx")}, automatic={}))
    code, _ = _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({VID: _player(tracks=[_manual("xx", "X")])}))
    assert code == 75 and not (tmp_path / "meta").exists()


def test_a_live_stream_is_skipped_with_its_reason_and_fetched_when_it_has_ended(ytdlp, server, tmp_path):
    control, calls = ytdlp
    control(info=_info(server))
    live = {**NORMAL, "videoDetails": {**NORMAL["videoDetails"], "isLive": True}}
    argv = [VID, "--dest", str(tmp_path), "--gap", "0"]
    code, events = _run(argv, Session({VID: live}))
    assert code == 0 and events[-1]["event"] == "skipped" and events[-1]["reason"] == "live stream in progress"
    assert [c for c in calls() if c["argv"] != ["--version"]] == [] and not (tmp_path / "audio").exists()
    meta = _sidecar(tmp_path)
    assert meta["complete"] is False and meta["skipped"] == "live stream in progress" and meta["audio"] is None
    code, events = _run(argv, Session({VID: NORMAL}))
    assert code == 0 and events[-1]["event"] == "done" and "skipped" not in _sidecar(tmp_path)


def test_a_premiere_that_has_not_started_is_skipped(ytdlp, tmp_path):
    upcoming = {**NORMAL, "videoDetails": {**NORMAL["videoDetails"], "isUpcoming": True}}
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({VID: upcoming}))
    assert code == 0 and events[-1]["event"] == "skipped" and "not started" in events[-1]["reason"]


# the command line

def test_options_are_not_abbreviated(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        fetch.main([VID, "--dest", str(tmp_path), "--no-aud"])
    assert stop.value.code == 2 and "unrecognized" in capsys.readouterr().err


def test_an_id_that_starts_with_a_dash_goes_after_a_double_dash(ytdlp, tmp_path):
    dashed = "-abcdefghij"
    code, events = _run(["--dest", str(tmp_path), "--gap", "0", "--", dashed], Session({dashed: UNPLAYABLE}))
    assert code == 1 and events[-1]["video_id"] == dashed


def test_ids_can_be_read_from_standard_input(ytdlp, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"-abcdefghij\n{OTHER}\n"))
    code, events = _run(["--dest", str(tmp_path), "--gap", "0", "-"], Session({"-abcdefghij": UNPLAYABLE, OTHER: UNPLAYABLE}))
    assert code == 1 and [e["video_id"] for e in events] == ["-abcdefghij", OTHER]


def test_a_bad_id_on_standard_input_is_a_usage_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("../etc\n"))
    with pytest.raises(SystemExit) as stop:
        fetch.main(["--dest", str(tmp_path), "-"])
    assert stop.value.code == 2 and "not a YouTube video id" in capsys.readouterr().err


def test_the_help_lists_the_exit_codes(capsys):
    with pytest.raises(SystemExit):
        fetch.main(["--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert all(code in text for code in ("0 done", "1 a video failed", "2 bad arguments", "75 ", "143 "))


def test_the_family_defaults_to_ipv4_and_reaches_yt_dlp(ytdlp, tmp_path):
    control, calls = ytdlp
    control(info={"id": VID})
    argv = [VID, "--dest", str(tmp_path), "--gap", "0", "--no-captions"]
    assert _run(argv, Session({VID: NORMAL}))[0] == 0
    assert all("--force-ipv4" in c["argv"] for c in calls() if "-f" in c["argv"] or "--dump-single-json" in c["argv"])
    assert any("--dump-single-json" in c["argv"] for c in calls())


def test_the_family_option_is_passed_on(ytdlp, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(fetch, "fetch_video", lambda vid, dest, **kw: seen.append(kw["family"]) or {"complete": True, "captions": []})
    for family in ([], ["--family", "any"], ["--family", "ipv6"]):
        _run([VID, "--dest", str(tmp_path), *family], Session({}))
    assert seen == ["ipv4", "any", "ipv6"]


def test_the_gap_is_kept_before_the_details_the_information_and_the_audio(ytdlp, tmp_path, monkeypatch):
    control, _ = ytdlp
    control(info={"id": VID})
    now, slept = [100.0], []
    monkeypatch.setattr(fetch, "time", types.SimpleNamespace(
        monotonic=lambda: now[0], time=time.time, sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s))))
    code, _ = _run([VID, "--dest", str(tmp_path), "--gap", "7", "--no-captions"], Session({VID: NORMAL}))
    assert code == 0 and slept == [7.0, 7.0]


def test_fetch_video_asks_for_a_gap_before_each_request_it_makes(ytdlp, server, tmp_path, monkeypatch):
    control, _ = ytdlp
    control(info=_info(server, subtitles={"fr": _entries(server, "lang=fr", formats=("json3",))}, automatic={}))
    order = []
    for name in ("video_details", "ytdlp_info", "fetch_audio"):
        real = getattr(fetch, name)
        monkeypatch.setattr(fetch, name, lambda *a, _real=real, _name=name, **k: (order.append(_name), _real(*a, **k))[1])
    fetch.fetch_video(VID, tmp_path, formats=("json3",), session=Session({VID: _player(tracks=[_manual("fr", "French")])}),
                      pace=lambda: order.append("pace"))
    assert order == ["pace", "video_details", "pace", "ytdlp_info", "pace", "pace", "fetch_audio"]


# terminating the run

def test_sigterm_ends_yt_dlp_and_leaves_no_information_file_behind(ytdlp, tmp_path, monkeypatch):
    control, calls = ytdlp
    control(mode="hang", info={"id": VID})
    private = tmp_path / "private-tmp"
    private.mkdir()
    monkeypatch.setenv("TMPDIR", str(private))
    monkeypatch.setattr(tempfile, "tempdir", None)
    unhandled = []

    def sentinel(*a):  # what the process would do without the command line's own handler
        unhandled.append("SIGTERM reached the test process")
    before = signal.signal(signal.SIGTERM, sentinel)
    stop = threading.Event()

    def terminate_once_yt_dlp_is_downloading():
        while not stop.is_set():
            if any("pid" in c for c in calls()):
                os.kill(os.getpid(), signal.SIGTERM)
                return
            time.sleep(0.05)
    killer = threading.Thread(target=terminate_once_yt_dlp_is_downloading, daemon=True)
    killer.start()
    dest = tmp_path / "job"
    try:
        code, events = _run([VID, "--dest", str(dest), "--gap", "0", "--no-captions"], Session({VID: NORMAL}))
    finally:
        stop.set()
        after = signal.signal(signal.SIGTERM, before)
    assert unhandled == [] and after is sentinel
    started = next(c for c in calls() if "pid" in c)
    assert code == 143 == fetch.EXIT_TERMINATED and events[-1] == {"event": "terminated", "video_id": VID}
    with pytest.raises(ProcessLookupError):
        os.kill(started["pid"], 0)
    assert not Path(started["info_path"]).exists() and list(private.iterdir()) == []
    assert not list(dest.rglob("*.info.json")) and not (dest / "meta").exists()


def test_the_info_file_is_not_written_under_the_destination(ytdlp, tmp_path):
    control, calls = ytdlp
    control(info={"id": VID})
    fetch.fetch_audio(VID, tmp_path / "out", info={"id": VID})
    assert not Path(calls()[-1]["argv"][calls()[-1]["argv"].index("--load-info-json") + 1]).is_relative_to(tmp_path / "out")


# no address in anything written or printed

@pytest.mark.parametrize("text", [
    "caption request failed: HTTPSConnectionPool(host='www.youtube.com'): Max retries exceeded with url: "
    "/api/timedtext?v=abcdefghijk&signature=AB12CD&ip=203.0.113.9&lang=en (Caused by NewConnectionError)",
    "see https://www.youtube.com/api/timedtext?v=abcdefghijk&signature=AB12CD&ip=203.0.113.9",
    "failed at //rr1.googlevideo.com/videoplayback?expire=1&ip=203.0.113.9&sig=AB",
    "retry with signature=AB12CD and ip=203.0.113.9 later",
    "ERROR: unable to download video data: HTTP Error 403: Forbidden (https://rr1---sn.googlevideo.com/videoplayback?sig=Z)",
    "HTTP Error 403 for https://rr1.googlevideo.com/videoplayback",
])
def test_errors_never_carry_an_address(text):
    cleaned = fetch._scrub(text)
    assert not any(bit in cleaned for bit in ("signature=", "AB12CD", "203.0.113.9", "://", "googlevideo", "sig=", "ip=", "timedtext?"))
    assert str(fetch.FetchError(text)) == cleaned


def test_text_without_an_address_is_left_alone():
    assert fetch._scrub("caption request answered HTTP 500") == "caption request answered HTTP 500"
    assert fetch._scrub("Video unavailable") == "Video unavailable"


def test_the_sidecar_and_standard_output_hold_no_caption_address(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server))
    leak = ("HTTPSConnectionPool(host='www.youtube.com', port=443): Max retries exceeded with url: "
            "/api/timedtext?v=abcdefghijk&signature=AB12CD&ip=203.0.113.9 (Caused by ConnectTimeoutError)")

    class Leaky(Session):
        def get(self, url, **kw):
            if "youtube.com/watch" in url:
                return super().get(url, **kw)
            raise requests.ConnectionError(leak)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fetch.main([VID, "--dest", str(tmp_path), "--gap", "0", "--no-audio"], session=Leaky({VID: NORMAL}))
    sidecar = (tmp_path / "meta" / f"{VID}.json").read_text()
    assert code == 1 and "Max retries exceeded" in sidecar
    for text in (sidecar, buf.getvalue()):
        assert not any(bit in text for bit in ("signature", "AB12CD", "203.0.113.9", "timedtext?", "://"))


def test_a_watch_page_error_that_names_an_address_is_printed_without_it(tmp_path):
    class Leaky(Session):
        def get(self, url, **kw):
            raise requests.ConnectionError("Max retries exceeded with url: /watch?v=abcdefghijk&signature=AB12CD&ip=203.0.113.9")
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0"], Leaky({}))
    assert code == 1 and events[-1]["event"] == "error" and "Max retries exceeded" in events[-1]["error"]
    assert "signature" not in events[-1]["error"] and "203.0.113.9" not in events[-1]["error"]


def test_a_yt_dlp_error_that_names_an_address_is_written_without_it(ytdlp, tmp_path):
    control, _ = ytdlp
    control(mode="fail_url")
    with pytest.raises(fetch.FetchError) as caught:
        fetch.fetch_audio(VID, tmp_path)
    assert "signature" not in str(caught.value) and "googlevideo" not in str(caught.value) and "403" in str(caught.value)


# resume safety

FORMATS = {"id": VID, "formats": [
    {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "filesize": 1000},
    {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "filesize": 800},
    {"format_id": "18", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a.40.2", "filesize": 99999}]}


def test_a_finished_file_of_the_wrong_size_is_downloaded_again(ytdlp, tmp_path):
    _, calls = ytdlp
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / f"{VID}.m4a").write_bytes(b"x" * 7)
    got = fetch.fetch_audio(VID, tmp_path, info=FORMATS)
    assert "already" not in calls()[-1] and got.bytes == 1000


def test_a_finished_file_of_the_listed_size_is_kept(ytdlp, tmp_path):
    _, calls = ytdlp
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / f"{VID}.m4a").write_bytes(b"x" * 1000)
    fetch.fetch_audio(VID, tmp_path, info=FORMATS)
    assert calls()[-1]["already"] is True


def test_a_partial_file_larger_than_the_format_is_not_resumed(ytdlp, tmp_path):
    _, calls = ytdlp
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / f"{VID}.m4a.part").write_bytes(b"x" * 3000)
    got = fetch.fetch_audio(VID, tmp_path, info=FORMATS)
    assert calls()[-1]["resumed_from"] == 0 and got.bytes == 1000


def test_a_partial_file_smaller_than_the_format_is_resumed(ytdlp, tmp_path):
    _, calls = ytdlp
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / f"{VID}.m4a.part").write_bytes(b"x" * 400)
    fetch.fetch_audio(VID, tmp_path, info=FORMATS)
    assert calls()[-1]["resumed_from"] == 400


def test_files_of_another_extension_or_without_a_listed_size_are_left_alone(ytdlp, tmp_path):
    _, calls = ytdlp
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / f"{VID}.webm").write_bytes(b"x" * 5)
    (tmp_path / "audio" / f"{OTHER}.m4a").write_bytes(b"x" * 5)
    fetch.fetch_audio(VID, tmp_path, info={"id": VID, "formats": [{"format_id": "140", "ext": "m4a", "vcodec": "none"}]})
    assert (tmp_path / "audio" / f"{VID}.webm").stat().st_size == 5 and (tmp_path / "audio" / f"{OTHER}.m4a").stat().st_size == 5


def test_a_file_of_another_extension_is_judged_by_the_sizes_of_its_own_formats(ytdlp, tmp_path):
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / f"{VID}.webm").write_bytes(b"x" * 800)
    (tmp_path / "audio" / f"{VID}.webm.part").write_bytes(b"x" * 500)
    fetch.fetch_audio(VID, tmp_path, info=FORMATS)
    assert (tmp_path / "audio" / f"{VID}.webm").stat().st_size == 800
    assert (tmp_path / "audio" / f"{VID}.webm.part").stat().st_size == 500


def test_a_download_of_another_size_than_its_format_is_deleted_and_refused(ytdlp, tmp_path):
    control, _ = ytdlp
    control(size=900)
    with pytest.raises(fetch.FetchError, match="900 bytes and YouTube lists 1000"):
        fetch.fetch_audio(VID, tmp_path, info=FORMATS)
    assert os.listdir(tmp_path / "audio") == []


def test_a_download_with_no_listed_size_is_accepted(ytdlp, tmp_path):
    control, _ = ytdlp
    control(size=900)
    assert fetch.fetch_audio(VID, tmp_path, info={"id": VID}).bytes == 900


# what the earlier tests did not pin

def test_a_caption_request_is_refused_while_downloads_are_paused(server, tmp_path):
    backoff.shared().mark_blocked("download")
    with pytest.raises(BackedOff):
        fetch.fetch_captions(VID, tmp_path, info=_info(server), session=Session({}))
    assert Captions.hits == [] and not (tmp_path / "captions").exists()


def test_a_language_or_format_that_is_not_a_plain_name_writes_nothing(server, tmp_path):
    info = _info(server, subtitles={"x": _entries(server, "lang=..%2F..%2Fescape")}, automatic={})
    files = fetch.fetch_captions(VID, tmp_path / "out", formats=("json3",), info=info, session=Session({}))
    assert [(f.language, f.error) for f in files] == [("../../escape", "unsafe language or format name")]
    assert Captions.hits == [] and not [p for p in tmp_path.rglob("*") if p.is_file()]
    good = fetch.fetch_captions(VID, tmp_path / "out", formats=("../evil", "json3"), info=_info(server), session=Session({}))
    assert [f.error for f in good if f.format == "../evil"] == ["unsafe language or format name"] * 2
    assert {p.name for p in (tmp_path / "out" / "captions").iterdir()} == {f"{VID}.fr.manual.json3", f"{VID}.pt.asr.json3"}


def test_the_session_a_fetch_builds_is_a_plain_requests_session(monkeypatch):
    from tutubo import transport
    monkeypatch.setattr(transport, "default_session", lambda *a, **k: pytest.fail("fetch must not use the TUTUBO_TRANSPORT session"))
    monkeypatch.setenv("TUTUBO_TRANSPORT", "curl_cffi")
    assert type(fetch.plain_session()) is requests.Session
    assert type(fetch.plain_session("ipv4")) is requests.Session


@pytest.mark.parametrize("bad", ["../etc", "short", "has space!!", "", "abcdefghijkl"])
def test_every_entry_point_refuses_an_id_that_is_not_one(ytdlp, tmp_path, bad):
    _, calls = ytdlp
    for call in (lambda: fetch.fetch_audio(bad, tmp_path / "out"), lambda: fetch.fetch_captions(bad, tmp_path / "out", info={}),
                 lambda: fetch.fetch_video(bad, tmp_path / "out")):
        with pytest.raises(ValueError, match="not a YouTube video id"):
            call()
    assert calls() == [] and not (tmp_path / "out").exists()


def test_a_bot_check_when_the_shared_pause_is_off_fails_that_video_and_the_run_goes_on(server, tmp_path, monkeypatch):
    monkeypatch.setenv("TUTUBO_BACKOFF", "off")
    info = _info(server, subtitles={"xx": _entries(server, "lang=xx"), "fr": _entries(server, "lang=fr")}, automatic={})
    files = fetch.fetch_captions(VID, tmp_path, formats=("json3",), info=info, session=Session({}))
    assert {(f.language, bool(f.error)) for f in files} == {("xx", True), ("fr", False)}
    assert backoff.shared().blocked_until("download") is None


def test_a_bot_check_that_cannot_be_recorded_still_stops_the_run(ytdlp, server, tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setenv("TUTUBO_STATE_DIR", str(blocker / "state"))
    control, _ = ytdlp
    control(info=_info(server, subtitles={"xx": _entries(server, "lang=xx")}, automatic={}))
    code, events = _run([VID, OTHER, "--dest", str(tmp_path / "job"), "--gap", "0", "--no-audio"],
                        Session({VID: _player(tracks=[_manual("xx", "X")]), OTHER: NORMAL}))
    assert code == 75 and events[-1]["event"] == "paused" and "could not be recorded" in events[-1]["error"]
    assert len(Captions.hits) == 1


# a SIGTERM between the spawn and the first line read

def _gone(pid, wait=3.0):
    """True when ``pid`` is not running; a zombie that nothing has collected yet is not running."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            return True
        if state in "ZX":
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("after", ["Popen", "Thread.start"])
def test_a_sigterm_right_after_the_spawn_still_ends_yt_dlp(ytdlp, tmp_path, monkeypatch, after):
    control, calls = ytdlp
    control(mode="hang", info={"id": VID})
    spawned, armed = [], []
    real_popen, real_start = subprocess.Popen, threading.Thread.start

    def term():
        deadline = time.monotonic() + 5
        while not any("pid" in c for c in calls()) and time.monotonic() < deadline:
            time.sleep(0.02)  # yt-dlp has read its information file and is hanging: it does not die of the missing file
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(0.05)  # the handler runs in this thread, before this call returns

    class Spawner(real_popen):
        def __init__(self, argv, *a, **k):
            super().__init__(argv, *a, **k)
            spawned.append(self.pid)
            if "--load-info-json" in argv:  # the download that hangs
                armed.append(self.pid)
                if after == "Popen":
                    term()

    def start(self):
        if after == "Thread.start" and armed and not getattr(start, "done", False):
            start.done = True
            term()
        return real_start(self)
    monkeypatch.setattr(fetch.subprocess, "Popen", Spawner)
    monkeypatch.setattr(threading.Thread, "start", start)
    before = signal.signal(signal.SIGTERM, signal.SIG_DFL)
    try:
        code, events = _run([VID, "--dest", str(tmp_path / "job"), "--gap", "0", "--no-captions"], Session({VID: NORMAL}))
    finally:
        signal.signal(signal.SIGTERM, before)
    assert len(armed) == 1 and code == 143 and events[-1]["event"] == "terminated"
    alive = not _gone(armed[0])
    if alive:
        os.kill(armed[0], signal.SIGKILL)
    assert not alive


def test_a_child_that_ignores_sigterm_is_killed(ytdlp, tmp_path, monkeypatch):
    control, calls = ytdlp
    control(mode="stubborn")
    monkeypatch.setattr(fetch, "_TERMINATE_WAIT_S", 0.5)

    def stop(line):
        raise RuntimeError("stop")
    began = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="stop"):
            fetch._run_ytdlp(["-o", str(tmp_path / "x.%(ext)s")], stop)
        took = time.monotonic() - began
    finally:
        pids = [c["pid"] for c in calls() if "pid" in c]
        stuck = [p for p in pids if not _gone(p, 0.1)]
        for pid in stuck:
            os.kill(pid, signal.SIGKILL)
    assert pids and stuck == [] and took < 8


def test_the_command_line_of_each_yt_dlp_call_ignores_the_user_config(ytdlp, tmp_path):
    control, calls = ytdlp
    control(info={"id": VID})
    fetch.ytdlp_info(VID)
    fetch.fetch_audio(VID, tmp_path, info={"id": VID})
    runs = [c["argv"] for c in calls() if "--version" not in c["argv"]]
    assert len(runs) == 2 and all("--ignore-config" in argv for argv in runs)


def test_the_audio_format_never_picks_a_drc_stream():
    *wanted, last = fetch.AUDIO_FORMAT.split("/")
    assert len(wanted) == 2 and all("format_id!*=drc" in alternative for alternative in wanted) and "drc" not in last


def test_stderr_is_read_to_its_end_before_the_exit_status_is_judged(ytdlp, tmp_path, monkeypatch):
    control, _ = ytdlp
    control(mode="botcheck")
    real = threading.Thread

    class Slow(real):
        def run(self):
            time.sleep(0.5)
            super().run()
    monkeypatch.setattr(fetch.threading, "Thread", Slow)
    with pytest.raises(BackedOff):
        fetch.fetch_audio(VID, tmp_path)


# a request that ends after a pause began does not end that pause

def _pause_during(kind, reply):
    def mid_request(*a, **k):
        backoff.shared().mark_blocked(kind)
        return reply
    return mid_request


def test_a_watch_page_answered_after_a_pause_began_does_not_end_the_pause():
    session = Session({})
    session.get = _pause_during("details", Reply(200, _page(NORMAL)))
    fetch.video_details(VID, session=session)
    assert backoff.shared().blocked_until("details")


def test_a_caption_file_served_after_a_pause_began_does_not_end_the_pause():
    session = types.SimpleNamespace(get=_pause_during("download", Reply(200, "text")))
    assert fetch._get_caption(session, "http://127.0.0.1:9/x") == b"text"
    assert backoff.shared().blocked_until("download")


def test_yt_dlp_finishing_after_a_pause_began_does_not_end_the_pause(ytdlp):
    control, _ = ytdlp
    control(info={"id": VID})
    fetch._run_ytdlp(["--dump-single-json", "x"], lambda line: backoff.shared().mark_blocked("download"))
    assert backoff.shared().blocked_until("download")


# a 4xx answer that says it is a bot check

BOT_PAGE = "Sign in to confirm you’re not a bot"


def test_a_watch_page_refused_with_a_4xx_bot_check_pauses_details():
    with pytest.raises(BackedOff):
        fetch.video_details(VID, session=Session({VID: Reply(403, BOT_PAGE)}))
    assert backoff.shared().blocked_until("details")


def test_a_caption_file_refused_with_a_4xx_bot_check_pauses_downloads(server, tmp_path):
    class Refusing(Session):
        def get(self, url, **kw):
            return Reply(403, BOT_PAGE)
    with pytest.raises(BackedOff):
        fetch.fetch_captions(VID, tmp_path, info=_info(server), session=Refusing({}))
    assert backoff.shared().blocked_until("download")


def test_a_4xx_that_is_not_a_bot_check_pauses_nothing(server, tmp_path):
    class Refusing(Session):
        def get(self, url, **kw):
            return Reply(403, "Forbidden")
    files = fetch.fetch_captions(VID, tmp_path, formats=("json3",), info=_info(server), session=Refusing({}))
    assert files and all(f.error == "caption request answered HTTP 403" for f in files)
    assert backoff.shared().blocked_until("download") is None


# files and errors

def test_a_file_that_cannot_be_moved_into_place_leaves_no_temporary_file(tmp_path, monkeypatch):
    def refuse(*a):
        raise OSError("disk full")
    monkeypatch.setattr(fetch.os, "replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        fetch._write_atomic(tmp_path / "meta" / "x.json", b"{}")
    assert list((tmp_path / "meta").iterdir()) == []


def test_an_error_from_the_disk_fails_that_video_and_the_run_goes_on(tmp_path):
    dest = tmp_path / "not-a-folder"
    dest.write_text("")
    code, events = _run([VID, OTHER, "--dest", str(dest), "--gap", "0", "--no-audio", "--no-captions"],
                        Session({VID: NORMAL, OTHER: _player(vid=OTHER)}))
    assert code == 1 and [(e["event"], e["video_id"]) for e in events] == [("error", VID), ("error", OTHER)]


# ids and names end where they end

@pytest.mark.parametrize("bad", [VID + "\n", "\n" + VID])
def test_an_id_with_a_trailing_newline_is_not_an_id(ytdlp, tmp_path, bad):
    _, calls = ytdlp
    with pytest.raises(ValueError, match="not a YouTube video id"):
        fetch.fetch_audio(bad, tmp_path / "out")
    with pytest.raises(SystemExit) as stop:
        fetch.main(["--dest", str(tmp_path), "--", bad])
    assert stop.value.code == 2 and calls() == []


def test_a_caption_language_ending_in_a_newline_writes_nothing(server, tmp_path):
    info = _info(server, subtitles={"en": _entries(server, "lang=en%0A")}, automatic={})
    files = fetch.fetch_captions(VID, tmp_path / "out", formats=("json3",), info=info, session=Session({}))
    assert [f.error for f in files] == ["unsafe language or format name"]
    assert Captions.hits == [] and not (tmp_path / "out" / "captions").exists()
    files = fetch.fetch_captions(VID, tmp_path / "out", formats=("json3\n",), info=_info(server), session=Session({}))
    assert {f.error for f in files} == {"unsafe language or format name"} and Captions.hits == []


# a premiere that has not started

def test_a_premiere_that_has_not_started_is_skipped_whatever_the_page_says_about_playability(ytdlp, tmp_path):
    waiting = {**NORMAL, "playabilityStatus": {"status": "LIVE_STREAM_OFFLINE", "reason": "Premieres in 2 hours"},
               "videoDetails": {**NORMAL["videoDetails"], "isUpcoming": True}}
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({VID: waiting}))
    assert code == 0 and events[-1]["event"] == "skipped" and "not started" in events[-1]["reason"]
    assert "Premieres in 2 hours" in events[-1]["reason"]
    meta = _sidecar(tmp_path)
    assert meta["complete"] is False and meta["skipped"] == events[-1]["reason"] and meta["audio"] is None


def test_a_live_stream_the_page_calls_offline_is_skipped_too(ytdlp, tmp_path):
    live = {**NORMAL, "playabilityStatus": {"status": "LIVE_STREAM_OFFLINE", "reason": "This live event has ended"},
            "videoDetails": {**NORMAL["videoDetails"], "isLive": True}}
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({VID: live}))
    assert code == 0 and events[-1]["event"] == "skipped" and events[-1]["reason"].startswith("live stream in progress")


def test_a_video_that_is_not_playable_and_not_a_live_stream_is_still_an_error(tmp_path):
    gone = {**NORMAL, "playabilityStatus": {"status": "ERROR", "reason": "Video unavailable"}}
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({VID: gone}))
    assert code == 1 and events[-1]["event"] == "error" and "not playable" in events[-1]["error"]


# a sidecar that is not what this program wrote

REQUEST = {"audio": True, "captions": True, "kinds": ["manual", "asr"], "formats": ["json3", "vtt"]}


@pytest.mark.parametrize("text", [
    "[]", "null", '"x"', "5", "true", "{", "", '{"captions": [1]}', '{"request": [], "complete": true}',
    json.dumps({"request": REQUEST, "complete": True, "captions": [1]}),
    json.dumps({"request": REQUEST, "complete": True, "captions": [{"file": 5}]}),
    json.dumps({"request": REQUEST, "complete": True, "captions": "x"}),
    json.dumps({"request": REQUEST, "complete": True, "captions": [], "audio": "x"}),
    json.dumps({"request": REQUEST, "complete": True, "captions": [], "audio": {"file": ["a"]}}),
    "[" * 100000, '{"a":' * 100000])
def test_a_sidecar_that_is_not_a_record_is_not_a_finished_video(tmp_path, text):
    meta = tmp_path / "meta" / f"{VID}.json"
    meta.parent.mkdir()
    meta.write_text(text)
    assert fetch._complete(meta, tmp_path, REQUEST) is False


def test_a_run_over_a_malformed_sidecar_fetches_the_video_again(ytdlp, server, tmp_path):
    control, _ = ytdlp
    control(info=_info(server))
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / f"{VID}.json").write_text("[" * 100000)
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({VID: NORMAL}))
    assert code == 0 and events[-1]["event"] == "done"


# no address survives the scrubber

@pytest.mark.parametrize("text,gone", [
    ("see https%3A%2F%2Frr1---sn.googlevideo.com%2Fvideoplayback%3Fexpire%3D1%26ip%3D203.0.113.9%26signature%3DAB12CD", ["AB12CD", "203.0.113.9"]),
    ("see %2F%2Frr1.googlevideo.com%2Fvideoplayback%3Fsig%3DAB12CD", ["AB12CD"]),
    ("failed rr1.googlevideo.com/videoplayback/ip/203.0.113.9/sig/AB12CD", ["AB12CD", "203.0.113.9", "googlevideo"]),
    ("failed at /api/x/ip/203.0.113.9/sig/AB12CD/id/5", ["AB12CD", "203.0.113.9"]),
    ("bad request&sig=AB12CD&x=1", ["AB12CD"]),
    ("header x-goog-signature: AB12CD seen", ["AB12CD"]),
    ("X-Goog-Signature=AB12CD", ["AB12CD"]),
    ("the api_key=AB12CD was refused", ["AB12CD"]),
    ("the api-key: AB12CD was refused", ["AB12CD"]),
    ("signature%3DAB12CD", ["AB12CD"]),
    ("see https://rr1.googlevideo.com/videoplayback?expire=1&sig=AB12\nCD34EF\nnext", ["AB12", "CD34EF"]),
    ("with signature=AB12\nCD34EF\nnext", ["AB12", "CD34EF"]),
    ("caption request failed: https://www.youtube.com/api/timedtext?v=x&sig=AB12\r\nCD34EF\r\nnext", ["AB12", "CD34EF"]),
])
def test_the_scrubber_also_removes_encoded_path_style_and_wrapped_addresses(text, gone):
    cleaned = fetch._scrub(text)
    assert not any(bit in cleaned for bit in gone), cleaned


def test_the_scrubber_keeps_the_words_around_an_address():
    assert fetch._scrub("see https://a.example/videoplayback?sig=AB\nnext line here") == "see <url>\nnext line here"
    assert fetch._scrub("a design: fine, a keyboard key press, a chip") == "a design: fine, a keyboard key press, a chip"
    assert fetch._scrub("Traceback (most recent call last):") == "Traceback (most recent call last):"


# two SIGTERMs

@pytest.mark.parametrize("grandchild", [False, True])
@pytest.mark.parametrize("gaps", [(0.3,), (0.3, 1.0), (0.3, 0.05, 0.05, 0.6)])
def test_repeated_sigterms_leave_no_process_that_ignores_them(ytdlp, tmp_path, monkeypatch, gaps, grandchild):
    control, calls = ytdlp
    control(mode="stubborn", grandchild=grandchild, info={"id": VID})
    monkeypatch.setattr(fetch, "_TERMINATE_WAIT_S", 1.5)
    before = signal.signal(signal.SIGTERM, signal.SIG_DFL)
    stop = threading.Event()

    def terminate():
        while not stop.is_set() and not any("pid" in c for c in calls()):
            time.sleep(0.02)
        for gap in gaps:
            time.sleep(gap)
            os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=terminate, daemon=True).start()
    began = time.monotonic()
    try:
        code, events = _run([VID, "--dest", str(tmp_path / "job"), "--gap", "0", "--no-captions"], Session({VID: NORMAL}))
        took = time.monotonic() - began
    finally:
        stop.set()
        signal.signal(signal.SIGTERM, before)
        started = next((c for c in calls() if "pid" in c), {})
        alive = [p for p in (started.get("pid"), started.get("grandchild")) if p and not _gone(p, 0.5)]
        for pid in alive:
            os.kill(pid, signal.SIGKILL)
    assert code == 143 and events[-1] == {"event": "terminated", "video_id": VID} and alive == []
    assert took < 8  # the child sleeps 20 s: it was killed, not waited for
    assert started.get("grandchild") or not grandchild


def test_an_error_before_yt_dlp_exists_is_not_hidden_by_the_cleanup(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise OSError("no such program")
    monkeypatch.setattr(fetch.subprocess, "Popen", refuse)
    with pytest.raises(OSError, match="no such program"):
        fetch._run_ytdlp(["--version"], lambda line: None)


def test_a_failure_while_ending_yt_dlp_still_kills_it(ytdlp, tmp_path, monkeypatch):
    control, calls = ytdlp
    control(mode="stubborn")
    monkeypatch.setattr(fetch, "_TERMINATE_WAIT_S", 30)
    real_wait = subprocess.Popen.wait
    state = {"n": 0}

    def wait(self, timeout=None):
        if timeout == 30 and not state["n"]:
            state["n"] = 1
            raise KeyboardInterrupt
        return real_wait(self, timeout)
    monkeypatch.setattr(subprocess.Popen, "wait", wait)

    def stop(line):
        raise RuntimeError("stop")
    try:
        with pytest.raises(KeyboardInterrupt):
            fetch._run_ytdlp(["-o", str(tmp_path / "x.%(ext)s")], stop)
    finally:
        pids = [c["pid"] for c in calls() if "pid" in c]
        alive = [p for p in pids if not _gone(p, 0.5)]
        for pid in alive:
            os.kill(pid, signal.SIGKILL)
    assert pids and alive == []


# the scrubber is linear and names what it removes

@pytest.mark.parametrize("text", ["a-" * 50000, "a" * 100000, "a?" * 50000, "a/" * 50000, "x\n" * 50000, "sig " * 25000,
                                  "https://" + "a" * 100000, "a=b?" * 25000, "/videoplayback" * 7000, "%25" * 33000,
                                  "x\nhttps://a/b\n" * 8000 + "z" * 50000 + " end"])
def test_the_scrubber_takes_linear_time(text):
    started = time.monotonic()
    fetch._scrub(text)
    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize("text,gone", [
    ("x-goog-signature%3ASECRET", ["SECRET"]),
    ('{"sig":"SECRET","a":1}', ["SECRET"]), ("{'sig': 'SECRET'}", ["SECRET"]),
    ("sig%253DSECRET", ["SECRET"]), ("sig%3ASECRET", ["SECRET"]),
    ("see http%253A%252F%252Frr1.googlevideo.com%252Fvideoplayback%253Fsig%253DSECRET%2526ip%253D203.0.113.9", ["SECRET", "203.0.113"]),
    ("token=SECRET", ["SECRET"]), ('"token": "SECRET"', ["SECRET"]), ("pot=SECRET", ["SECRET"]), ("lsig=SECRET", ["SECRET"]),
    ("expire=1700000000", ["1700000000"]), ("sparams=expire,ip,id", ["expire,ip"]), ("ipbits=0", ["ipbits=0"]),
    ("ip=203.0.113.9", ["203.0.113.9"]), ("key=SECRET", ["SECRET"]), ("visitor_data=SECRET", ["SECRET"]),
    ("api_key=SECRET", ["SECRET"]), ("my-api-key: SECRET", ["SECRET"]),
    ("Cookie: VISITOR=SECRET; A=B", ["SECRET", "A=B"]), ("set-cookie: A=SECRET", ["SECRET"]),
    ("Authorization: Bearer SECRET", ["SECRET"]), ('"authorization": "Bearer SECRET"', ["SECRET"]),
    ('{\\"sig\\":\\"SECRET\\"}', ["SECRET"]), ('{\\"signature\\": \\"SECRET\\"}', ["SECRET"]),
    ('{\\\\\\"sig\\\\\\":\\\\\\"SECRET\\\\\\"}', ["SECRET"]),
    ('{\\"authorization\\": \\"SECRET\\"}', ["SECRET"]),
    ("visitorData=SECRET", ["SECRET"]), ('"visitorData":"SECRET"', ["SECRET"]), ("X-Goog-Visitor-Id: SECRET", ["SECRET"]),
    ("visitor_id=SECRET", ["SECRET"]), ("apikey=SECRET", ["SECRET"]), ("api-key=SECRET", ["SECRET"]),
    ("password=SECRET", ["SECRET"]), ('{"client_secret": "SECRET"}', ["SECRET"]),
    ("SAPISID=SECRET", ["SECRET"]), ("APISID=SECRET", ["SECRET"]), ("HSID=SECRET", ["SECRET"]), ("SSID=SECRET", ["SECRET"]),
    ("__Secure-3PSID=SECRET", ["SECRET"]), ("__Secure-1PSIDTS: SECRET", ["SECRET"]), ("__Secure-3PSIDCC=SECRET", ["SECRET"]),
    ("sent Bearer abc123SECRET456 to the server", ["SECRET"]),
])
def test_the_scrubber_names(text, gone):
    cleaned = fetch._scrub(text)
    assert not any(bit in cleaned for bit in gone), cleaned


def test_the_scrubber_leaves_words_that_only_contain_a_name():
    for text in ("a monkey= here", "design: fine", "keyboard key press", "sigma=2", "ipv4=on", "tokenizer: fast"):
        assert fetch._scrub(text) == text


def test_a_paused_event_is_scrubbed(tmp_path, monkeypatch):
    def paused(*a, **k):
        raise BackedOff("download", time.time() + 60, "see https://a.example/x?sig=SECRET and ip=203.0.113.9")
    monkeypatch.setattr(fetch, "fetch_video", paused)
    code, events = _run([VID, "--dest", str(tmp_path), "--gap", "0"], Session({}))
    assert code == 75 and events[-1]["event"] == "paused"
    assert "SECRET" not in events[-1]["error"] and "203.0.113.9" not in events[-1]["error"]


def test_a_child_that_obeys_sigterm_is_not_left_to_the_kill(ytdlp, tmp_path, monkeypatch):
    control, calls = ytdlp
    control(mode="hang", line=True)
    monkeypatch.setattr(fetch, "_TERMINATE_WAIT_S", 30)
    info = tmp_path / "info.json"
    info.write_text("{}")

    def stop(line):
        raise RuntimeError("stop")
    began = time.monotonic()
    with pytest.raises(RuntimeError, match="stop"):
        fetch._run_ytdlp(["--load-info-json", str(info), "-o", str(tmp_path / "x.%(ext)s")], stop)
    assert time.monotonic() - began < 8
    assert _gone(next(c["pid"] for c in calls() if "pid" in c), 0.5)


@pytest.mark.parametrize("text", [
    "ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies for the authentication",
    "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    "[download]  45.3% of 3.21MiB at 1.20MiB/s ETA 00:02",
    "TUTUBO-PROGRESS 1048576 4200000 NA",
    "[youtube] abcdefghijk: Downloading webpage", "[info] abcdefghijk: Downloading 1 format(s): 140",
    "size=    1024kB time=00:01:02.03 bitrate= 128.0kbits/s speed=1.5x",
    "Stream #0:0: Audio: aac (LC), 44100 Hz, stereo, fltp, 129 kb/s",
    "[ExtractAudio] Destination: /home/user/job/audio/abcdefghijk.m4a",
    "WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is enabled by default",
    "caption request answered HTTP 500", "YouTube served an empty caption file", "yt-dlp finished without reporting an audio file",
    "the audio file is 999 bytes and YouTube lists 1000 for format 140", "video not playable (ERROR): Video unavailable",
    "the bearer of this news", "pallbearer abcdefghijkl", "bearer token", "a password manager", "a visitor id card", "an apikey holder",
    "sidecar for session id and hsidden", "deprecated: use sigint", "ssidx=1"])
def test_ordinary_lines_are_left_as_they_are(text):
    assert fetch._scrub(text) == text


@pytest.mark.parametrize("text", [
    "Bearer abcdefgh " * 60000, "bearer " * 140000, '\\"' * 500000, "visitor-" * 120000, "__Secure-" * 110000,
    "apikey" * 160000, "password " * 110000, "client_secret" * 80000, "sapisid " * 120000, "visitorData\\\\\\\"" * 70000,
    "a" * 1000000, "a-" * 500000])
def test_the_scrubber_takes_linear_time_on_a_megabyte(text):
    started = time.monotonic()
    fetch._scrub(text)
    assert time.monotonic() - started < 1.0
