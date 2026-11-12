"""Fetch one video for a speech corpus: its details, its caption files as YouTube serves them, and its audio in the codec YouTube
stores, with no re-encode.

``video_details`` reads the watch page once. ``fetch_captions`` and ``fetch_audio`` run yt-dlp, which keeps up with the tokens
YouTube asks of its clients; the caption files are then fetched from the addresses yt-dlp found. ``python -m tutubo.fetch`` does
all three for a list of video ids and writes, under the destination folder::

    audio/<id>.<ext>                       the original audio track, as YouTube stores it (m4a or webm)
    captions/<id>.<lang>.<kind>.<format>   one file per caption track and format, as YouTube serves it
    meta/<id>.json                         what was fetched; written last, and ``complete`` says whether every file is there

Every request goes through the shared back-off (:mod:`tutubo.backoff`): the watch page is a ``details`` request, yt-dlp and the
caption files are ``download`` requests. A bot check pauses its kind and stops the run, also when yt-dlp only warns about it;
nothing is retried. With ``TUTUBO_BACKOFF=off`` nothing is paused or recorded: a check then fails that video and the run goes
on. Requests go through a
plain ``requests`` session whatever ``TUTUBO_TRANSPORT`` says, so nothing here impersonates a browser or falls back to an archive.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, urlparse

from tutubo import backoff
from tutubo.captions import CaptionError, CaptionTrack, parse_caption_tracks, watch_player
from tutubo.download import _family_args
from tutubo.transport import FamilyAdapter, resolve_family
from tutubo.version import __version__

AUDIO_FORMAT = "bestaudio[format_note*=original][format_id!*=drc]/bestaudio[format_id!*=drc]/bestaudio"
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_PAUSED = backoff.PAUSED_EXIT
EXIT_TERMINATED = 128 + signal.SIGTERM
_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_SAFE = re.compile(r"[A-Za-z0-9_-]+")
_TERMINATE_WAIT_S = 10.0
_PROGRESS, _AUDIO = "TUTUBO-PROGRESS", "TUTUBO-AUDIO"
_TOKEN = r"[^\s'\"<>)\]]"
_START = r"(?<![^\s'\"<>])"  # a match begins at the start of a word, so a long word is scanned once and not once per character
_WRAP = r"(?:\r?\n" + _TOKEN + r"+(?=\r?\n|\Z))*"  # a token the producer wrapped onto lines of its own
_COLON, _SLASH, _EQUALS = r"(?:%(?:25)*3A|:)", r"(?:/|%(?:25)*2F)", r"(?:=|%(?:25)*3D|:|%(?:25)*3A)"
_URL = re.compile(r"(?:https?" + _COLON + r")?" + _SLASH + _SLASH + _TOKEN + r"+" + _WRAP, re.I)
_PLAYBACK = re.compile(_START + r"[^\s'\"<>]*/videoplayback\b" + _TOKEN + r"*" + _WRAP, re.I)
_QUERY = re.compile(_START + r"[^\s'\"<>?]*\?[^\s'\"<>]*=[^\s'\"<>]*" + _WRAP)
_URL_NAMES = r"signature|sig|lsig|ip|ipbits|expire|sparams|pot|key|token"  # names a media address holds as path segments
_NAMES = (_URL_NAMES + r"|apikey|password|client_secret|visitor[_-]?data|visitor[_-]?id|visitor_info1_live|login_info"
          r"|sapisid|apisid|sid|sidcc|hsid|ssid|lsid|osid"
          r"|__(?:secure|host)-(?=[a-z0-9]*(?:psid|apisid|osid|lsid))[a-z0-9]+")
_AFTER_ESCAPE = r"(?<=%[0-9a-f]{2})|(?<=%25[0-9a-f]{2})"  # a name that follows a percent-escaped separator such as %26 or %3F
_QUOTE = r"(?:\\*[\"'])?"  # a quote, also one escaped for a JSON string inside a JSON string
_SEGMENT = re.compile(r"/(?:" + _URL_NAMES + r")/[^/\s'\"<>)\]]+" + _WRAP, re.I)
_PARAM = re.compile(r"(?:(?<![A-Za-z0-9])|" + _AFTER_ESCAPE + r")(?:" + _NAMES + r")" + _QUOTE + r"[ \t]*" + _EQUALS + r"[ \t]*" + _QUOTE + r"[^\s&'\"<>)]*" + _WRAP, re.I)
_HEADER = re.compile(r"(?<![A-Za-z0-9])(?:cookie|authorization)" + _QUOTE + r"[ \t]*" + _EQUALS + r"[^\r\n]*", re.I)
_TUPLE = re.compile(r"(?:(?<![A-Za-z0-9])|" + _AFTER_ESCAPE + r")(?:" + _NAMES + r")[\"'][ \t]*,[ \t]*[\"'][^\"'\r\n]*", re.I)  # ('SID', 'value')
_ROW = re.compile(r"(?<=\t)(?:" + _NAMES + r")\t[^\r\n]*", re.I)  # a row of a Netscape cookie file
_HASH = re.compile(r"(?<![A-Za-z0-9])sapisid(?:[13]p)?hash[ \t]+[^\s'\"<>)]+", re.I)
_BEARER = re.compile(r"(?<![A-Za-z0-9])bearer[ \t]+[A-Za-z0-9._~+/=-]{8,}", re.I)


def _scrub(text: object) -> str:
    """``text`` without any address or credential. Replaced: a URL, also percent-encoded once or twice; a media path with or without a
    host; a path with a query string; a ``/signature/...`` style path segment; a ``name=value``, ``name: value`` or ``"name": "value"``
    pair, also inside an escaped JSON string or after a percent-escaped ``&`` or ``?``, for the names signature, sig, lsig, ip,
    ipbits, expire, sparams, pot, key, apikey, token, password, client_secret, visitor data and visitor id (any case, with or
    without ``_`` or ``-``), and the Google cookies SID, SIDCC, HSID, SSID, LSID, OSID, SAPISID, APISID, LOGIN_INFO, VISITOR_INFO1_LIVE and every
    ``__Secure-`` or ``__Host-`` cookie whose name holds PSID, APISID, OSID or LSID; a ``Cookie:`` or ``Authorization:`` line; ``Bearer <token>``; ``SAPISIDHASH
    <hash>``; the Python form ``('SID', 'value')`` and a tab-separated row of a Netscape cookie file for those names; and a token that continues on lines of its own. Every pattern is linear in the length of the text. Not covered: HTML
    entities, a name or separator spelled with percent escapes or with fullwidth or look-alike characters, and a secret under
    any other name."""
    text = _URL.sub("<url>", str(text))
    text = _PLAYBACK.sub("<url>", text)
    text = _QUERY.sub("<query>", text)
    text = _SEGMENT.sub("<removed>", text)
    text = _HEADER.sub("<removed>", text)
    text = _BEARER.sub("<removed>", text)
    text = _HASH.sub("<removed>", text)
    text = _TUPLE.sub("<removed>", text)
    text = _ROW.sub("<removed>", text)
    return _PARAM.sub("<removed>", text)


class FetchError(RuntimeError):
    """A video, a caption file or an audio track could not be fetched, for a reason other than a bot check. The message never
    holds an address."""

    def __init__(self, message: object = ""):
        super().__init__(_scrub(message))


class Terminated(BaseException):
    """The command line received SIGTERM."""


@dataclass(frozen=True)
class AudioTrack:
    """One audio-only stream the watch page offers. ``original`` is True for the track in the language the video was made in,
    False for a dub, and None when the page does not say which track is the original."""
    itag: int
    codec: str
    container: str
    sample_rate: Optional[int]
    channels: Optional[int]
    bitrate: Optional[int]
    size: Optional[int]
    language: Optional[str]
    name: Optional[str]
    original: Optional[bool]
    default: bool
    drc: bool


@dataclass(frozen=True)
class VideoDetails:
    """What one watch-page read says about a video. ``upload_date`` and ``publish_date`` are the page's own strings, a date or a
    date with time and offset; ``live_start`` is set for a live recording."""
    video_id: str
    title: str
    channel_id: str
    channel: str
    duration_s: Optional[int]
    upload_date: Optional[str]
    publish_date: Optional[str]
    live_start: Optional[str]
    is_live_content: bool
    audio_tracks: List[AudioTrack] = field(default_factory=list)
    caption_tracks: List[CaptionTrack] = field(default_factory=list)
    is_live: bool = False
    is_upcoming: bool = False
    playability_reason: Optional[str] = None

    @property
    def as_dict(self) -> dict:
        out = asdict(self)
        out["caption_tracks"] = [_without_url(t) for t in self.caption_tracks]
        return out


@dataclass(frozen=True)
class OfferedCaption:
    """A caption track yt-dlp found, with the address of each format YouTube serves it in."""
    track: CaptionTrack
    formats: Dict[str, str]


@dataclass(frozen=True)
class CaptionFile:
    """One caption file written, or the reason it was not (``error``)."""
    language: str
    kind: str
    is_translation: bool
    format: str
    path: Optional[str] = None
    bytes: Optional[int] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class AudioFile:
    """The audio file written, as yt-dlp reports it."""
    path: str
    format_id: str
    ext: str
    codec: Optional[str]
    sample_rate: Optional[int]
    channels: Optional[int]
    bitrate_kbps: Optional[float]
    language: Optional[str]
    note: Optional[str]
    bytes: int


def _without_url(track: CaptionTrack) -> dict:
    out = track.as_dict
    out.pop("url", None)
    return out


def plain_session(family: Optional[str] = None):
    """A ``requests`` session, pinned to ``family`` when one is in effect."""
    import requests
    session = requests.Session()
    fam = resolve_family(family)
    if fam is not None:
        adapter = FamilyAdapter(fam)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    return session


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _audio_tracks(player: dict) -> List[AudioTrack]:
    formats = [f for f in (player.get("streamingData") or {}).get("adaptiveFormats") or ()
               if isinstance(f, dict) and str(f.get("mimeType", "")).startswith("audio/")]
    multi = any(f.get("audioTrack") for f in formats)
    named_original = any("original" in str((f.get("audioTrack") or {}).get("displayName", "")).lower() for f in formats)
    tracks = []
    for f in formats:
        mime = f["mimeType"]
        codecs = re.search(r'codecs="([^"]+)"', mime)
        audio = f.get("audioTrack") or {}
        name = audio.get("displayName")
        if not multi:
            original = True
        elif named_original:
            original = "original" in str(name or "").lower()
        else:
            original = None
        tracks.append(AudioTrack(
            itag=_int(f.get("itag")) or 0,
            codec=codecs.group(1) if codecs else "",
            container=mime.split(";")[0].split("/")[-1],
            sample_rate=_int(f.get("audioSampleRate")),
            channels=_int(f.get("audioChannels")),
            bitrate=_int(f.get("averageBitrate") or f.get("bitrate")),
            size=_int(f.get("contentLength")),
            language=str(audio.get("id", "")).split(".")[0] or None,
            name=name,
            original=original,
            default=bool(audio.get("audioIsDefault", not multi)),
            drc=bool(f.get("isDrc")),
        ))
    return tracks


def parse_video_details(player: dict) -> VideoDetails:
    """The details in an already fetched player response. Raises :class:`CaptionError` when the video is not playable, except for a
    live stream or premiere that is not playable yet: its details are returned, with ``playability_reason`` saying why."""
    details = player.get("videoDetails") or {}
    status = player.get("playabilityStatus")
    waiting = isinstance(status, dict) and status.get("status") not in (None, "", "OK") and bool(
        details.get("isLive") or details.get("isUpcoming"))
    captions = [] if waiting else parse_caption_tracks(player)
    micro = (player.get("microformat") or {}).get("playerMicroformatRenderer") or {}
    live = micro.get("liveBroadcastDetails") or {}
    return VideoDetails(
        video_id=details.get("videoId", ""),
        title=details.get("title") or (micro.get("title") or {}).get("simpleText", ""),
        channel_id=details.get("channelId") or micro.get("externalChannelId", ""),
        channel=details.get("author") or micro.get("ownerChannelName", ""),
        duration_s=_int(details.get("lengthSeconds") or micro.get("lengthSeconds")),
        upload_date=micro.get("uploadDate"),
        publish_date=micro.get("publishDate"),
        live_start=live.get("startTimestamp"),
        is_live_content=bool(details.get("isLiveContent")),
        is_live=bool(details.get("isLive")),
        is_upcoming=bool(details.get("isUpcoming")),
        playability_reason=(str(status.get("reason") or status["status"]) if waiting else None),
        audio_tracks=_audio_tracks(player),
        caption_tracks=captions,
    )


def video_details(video: str, session: Optional[object] = None, family: Optional[str] = None,
                  language: str = "en-US,en;q=0.9") -> VideoDetails:
    """Read a video's watch page once and return its details: title, channel, duration, upload date, audio tracks and caption
    tracks. Raises :class:`tutubo.backoff.BackedOff` on a bot check or while ``details`` is paused, :class:`CaptionError` when
    the page cannot be read or the video is not playable."""
    vid, player = watch_player(video, session=session or plain_session(family), language=language)
    found = parse_video_details(player)
    if found.video_id != vid:
        raise CaptionError(f"player response is for {found.video_id!r}, requested {vid!r}")
    return found


# yt-dlp

def ytdlp_command() -> List[str]:
    """yt-dlp to run: ``$TUTUBO_YTDLP``, else the one installed beside this Python, else the one on PATH."""
    given = os.environ.get("TUTUBO_YTDLP")
    if given:
        return [given]
    beside = Path(sys.executable).with_name("yt-dlp")
    if beside.is_file():
        return [str(beside)]
    found = shutil.which("yt-dlp")
    if not found:
        raise FetchError("yt-dlp not found. Install it with: pip install yt-dlp")
    return [found]


@contextlib.contextmanager
def _sigterm_held():
    """Hold a SIGTERM that arrives inside the block, so that it cannot interrupt a step that has to finish for the caller to clean
    up after it, and hand it to the handler that was in place when the block ends. Without a Python-level handler, or off the main
    thread, nothing is held."""
    before = signal.getsignal(signal.SIGTERM) if threading.current_thread() is threading.main_thread() else None
    if not callable(before):
        yield
        return
    held = []
    signal.signal(signal.SIGTERM, lambda signum, frame: held.append(signum))
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, before)
        if held:
            before(signal.SIGTERM, None)


def _end(proc: "subprocess.Popen") -> None:
    """End yt-dlp and whatever it started: ask its process group to stop, wait, and kill the group whatever happened."""
    try:
        _signal_group(proc, signal.SIGTERM)
        proc.wait(timeout=_TERMINATE_WAIT_S)
    except subprocess.TimeoutExpired:
        pass
    finally:
        _signal_group(proc, getattr(signal, "SIGKILL", signal.SIGTERM))
        proc.wait()


def _signal_group(proc: "subprocess.Popen", signum: int) -> None:
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signum)
        else:
            proc.send_signal(signum)
    except (ProcessLookupError, PermissionError):
        pass


def _run_ytdlp(args: List[str], on_line: Callable[[str], None]) -> None:
    """Run yt-dlp once as a ``download`` request, passing each line it prints to ``on_line``. A bot check in its output stops the run
    even when yt-dlp only warns about it and exits 0. Whatever interrupts this call (a signal, an error in ``on_line``) ends yt-dlp
    and the programs it started first, also when the interruption arrives while yt-dlp is being started."""
    backoff.check("download")
    started = time.time()
    proc = None
    errors: List[str] = []
    try:
        with _sigterm_held():
            proc = subprocess.Popen(ytdlp_command() + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    start_new_session=True)
            reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
            reader.start()
        for line in proc.stdout:
            on_line(line.rstrip("\n"))
        code = proc.wait()
    except BaseException:
        if proc is not None:
            _end(proc)
        raise
    reader.join()
    err = "".join(errors).strip()
    if backoff.failed("download", err):
        raise backoff.paused("download")
    if code != 0:
        raise FetchError(f"yt-dlp failed: {err.splitlines()[-1] if err else f'exit {code}'}")
    backoff.after_success("download", started)


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def ytdlp_info(video_id: str, family: Optional[str] = "ipv4") -> dict:
    """yt-dlp's information about a video, without downloading anything."""
    out: List[str] = []
    _run_ytdlp(["--ignore-config", "--no-playlist", "--no-colors", "--ignore-no-formats-error", *_family_args(family),
                "--dump-single-json", _watch_url(video_id)], out.append)
    try:
        return json.loads("\n".join(out))
    except ValueError as e:
        raise FetchError(f"yt-dlp printed no information for {video_id}") from e


def offered_captions(info: dict) -> List[OfferedCaption]:
    """The caption tracks in yt-dlp's information, classified from their addresses: a ``tlang`` makes a machine translation,
    ``kind=asr`` an automatic track, anything else in ``subtitles`` a manual one. Only files served whole over HTTP count: an
    entry yt-dlp found in a streaming manifest is a playlist, not a caption file. yt-dlp lists the original automatic track
    twice, as ``<lang>-orig`` and ``<lang>``; the ``-orig`` entry is read first."""
    found: Dict[tuple, OfferedCaption] = {}
    for group, default_kind in (("subtitles", "manual"), ("automatic_captions", "asr")):
        listed = sorted((info.get(group) or {}).items(), key=lambda item: not item[0].endswith("-orig"))
        for key, entries in listed:
            formats = {e["ext"]: e["url"] for e in entries or () if isinstance(e, dict) and e.get("ext") and e.get("url")
                       and e.get("protocol") in (None, "", "http", "https")}
            if not formats:
                continue
            query = parse_qs(urlparse(next(iter(formats.values()))).query)
            source = (query.get("lang") or [key])[0]
            tlang = (query.get("tlang") or [None])[0]
            kind = "asr" if (query.get("kind") or [""])[0] == "asr" else default_kind
            name = next((e.get("name") for e in entries if isinstance(e, dict) and e.get("name")), "") or ""
            track = CaptionTrack(
                language=tlang or source, name=name, kind="translation" if tlang else kind, is_translation=tlang is not None,
                source_language=source if tlang else None, source_kind=kind if tlang else None)
            found.setdefault((track.language, track.kind, track.source_language), OfferedCaption(track, formats))
    return list(found.values())


def fetch_captions(video_id: str, dest, kinds: Sequence[str] = ("manual", "asr"), original_only: bool = True,
                   formats: Sequence[str] = ("json3", "vtt"), info: Optional[dict] = None, session: Optional[object] = None,
                   family: Optional[str] = "ipv4", pace: Callable[[], None] = lambda: None,
                   listed: Optional[Sequence[CaptionTrack]] = None) -> List[CaptionFile]:
    """Write each caption track of ``kinds`` in each of ``formats``, as YouTube serves it, to
    ``dest/captions/<id>.<lang>.<kind>.<format>``. Translations are left out unless ``original_only`` is False and ``kinds``
    holds ``"translation"``. With ``listed`` (the tracks :func:`video_details` found), only a track the watch page lists with
    the same language and kind is fetched. A track YouTube does not serve in a format, or serves empty, and a listed track yt-dlp
    did not offer, is returned with ``error`` set. Raises :class:`tutubo.backoff.BackedOff` on a bot check; ``info`` is yt-dlp's
    information, read when not given."""
    _check_id(video_id)
    if info is None:
        info = ytdlp_info(video_id, family)
    session = session or plain_session(family)
    folder = Path(dest) / "captions"
    written: List[CaptionFile] = []
    for offered in offered_captions(info):
        track = offered.track
        if track.kind not in kinds or (original_only and track.is_translation):
            continue
        if listed is not None and (track.language, track.kind, track.source_language) not in {
                (t.language, t.kind, t.source_language) for t in listed}:
            continue
        for fmt in formats:
            result = dict(language=track.language, kind=track.kind, is_translation=track.is_translation, format=fmt)
            if not (_SAFE.fullmatch(track.language) and _SAFE.fullmatch(fmt)):
                written.append(CaptionFile(**result, error="unsafe language or format name"))
                continue
            url = offered.formats.get(fmt)
            if not url:
                written.append(CaptionFile(**result, error=f"not offered as {fmt}"))
                continue
            pace()
            try:
                body = _get_caption(session, url)
            except FetchError as e:
                written.append(CaptionFile(**result, error=str(e)))
                continue
            path = folder / f"{video_id}.{track.language}.{track.kind}.{fmt}"
            _write_atomic(path, body)
            written.append(CaptionFile(**result, path=str(path), bytes=len(body)))
    if listed is not None:
        offered_keys = {(o.track.language, o.track.kind, o.track.source_language) for o in offered_captions(info)}
        for t in listed:
            if (t.language, t.kind, t.source_language) not in offered_keys:
                written.extend(CaptionFile(language=t.language, kind=t.kind, is_translation=t.is_translation, format=fmt,
                                           error="the watch page lists this track and yt-dlp did not offer it") for fmt in formats)
    return written


def _get_caption(session, url: str) -> bytes:
    backoff.check("download")
    started = time.time()
    try:
        resp = session.get(url, timeout=30)
    except Exception as e:
        raise FetchError(f"caption request failed: {e}") from e
    status = getattr(resp, "status_code", 200)
    if status == 429 or (status >= 400 and backoff.is_bot_check(getattr(resp, "text", ""))):
        if backoff.failed("download", f"HTTP {status} {getattr(resp, 'text', '')}"):
            raise backoff.paused("download")
    if status >= 400:
        raise FetchError(f"caption request answered HTTP {status}")
    backoff.after_success("download", started)
    if not resp.content:
        raise FetchError("YouTube served an empty caption file")
    return resp.content


def fetch_audio(video_id: str, dest, info: Optional[dict] = None, family: Optional[str] = "ipv4",
                fmt: str = AUDIO_FORMAT, on_progress: Callable[[int, Optional[int]], None] = lambda done, total: None) -> AudioFile:
    """Download the original audio track to ``dest/audio/<id>.<ext>`` with no re-encode, resuming a partial file. With ``info``
    (yt-dlp's information, fresh) yt-dlp reuses it instead of reading the video again, and the sizes it lists are checked: a
    finished or partial file of a size no listed audio format has is deleted before the download, and a downloaded file whose size
    differs from its format's is deleted and refused. Raises :class:`tutubo.backoff.BackedOff` on a bot check and
    :class:`FetchError` on any other failure; neither is retried."""
    _check_id(video_id)
    folder = Path(dest) / "audio"
    folder.mkdir(parents=True, exist_ok=True)
    args = ["--ignore-config", "--no-playlist", "--newline", "--no-colors", "--no-mtime", "--continue", "--progress",
            "-f", fmt, *_family_args(family),
            "--progress-template", f"download:{_PROGRESS} %(progress.downloaded_bytes)s %(progress.total_bytes)s "
                                   "%(progress.total_bytes_estimate)s",
            "--print", f"after_move:{_AUDIO} %(.{{filepath,format_id,ext,acodec,asr,audio_channels,abr,language,format_note}})j",
            "-o", str(folder / f"{video_id}.%(ext)s")]
    reported: List[dict] = []

    def line(text: str) -> None:
        if text.startswith(_PROGRESS + " "):
            done, total, estimate = (text.split() + ["NA", "NA", "NA"])[1:4]
            if _int(done) is not None:
                on_progress(int(done), _int(total) or _int(estimate))
        elif text.startswith(_AUDIO + " "):
            reported.append(json.loads(text[len(_AUDIO) + 1:]))

    if info is None:
        _run_ytdlp(args + [_watch_url(video_id)], line)
    else:
        _drop_untrusted(folder, video_id, info)
        with tempfile.TemporaryDirectory(prefix="tutubo-info-") as private:  # signed media addresses stay out of the destination
            loaded = Path(private) / "info.json"
            loaded.write_text(json.dumps(info))
            _run_ytdlp(args + ["--load-info-json", str(loaded)], line)
    if not reported or not os.path.isfile(reported[-1].get("filepath") or ""):
        raise FetchError("yt-dlp finished without reporting an audio file")
    got = reported[-1]
    expected = _format_sizes(info).get(str(got.get("format_id") or "")) if info is not None else None
    if expected is not None and os.path.getsize(got["filepath"]) != expected:
        size = os.path.getsize(got["filepath"])
        os.unlink(got["filepath"])
        raise FetchError(f"the audio file is {size} bytes and YouTube lists {expected} for format {got.get('format_id')}")
    return AudioFile(path=got["filepath"], format_id=str(got.get("format_id") or ""), ext=got.get("ext") or "",
                     codec=got.get("acodec"), sample_rate=_int(got.get("asr")), channels=_int(got.get("audio_channels")),
                     bitrate_kbps=got.get("abr"), language=got.get("language"), note=got.get("format_note"),
                     bytes=os.path.getsize(got["filepath"]))


def _format_sizes(info: dict) -> Dict[str, int]:
    """Format id -> exact size in bytes, for each audio-only format yt-dlp's information gives a size."""
    return {str(f.get("format_id")): size for f in info.get("formats") or ()
            if isinstance(f, dict) and f.get("vcodec") == "none" and (size := _int(f.get("filesize")))}


def _drop_untrusted(folder: Path, video_id: str, info: dict) -> None:
    """Delete a finished audio file whose size no audio format of its extension has, and a partial one larger than every such
    format, so that yt-dlp downloads them again instead of resuming or accepting them."""
    sizes: Dict[str, set] = {}
    for f in info.get("formats") or ():
        if isinstance(f, dict) and f.get("vcodec") == "none" and _int(f.get("filesize")):
            sizes.setdefault(str(f.get("ext")), set()).add(int(f["filesize"]))
    for path in folder.glob(f"{video_id}.*"):
        partial = path.suffix == ".part"
        expected = sizes.get((Path(path.stem) if partial else path).suffix.lstrip("."))
        if expected:
            size = path.stat().st_size
            if size > max(expected) if partial else size not in expected:
                path.unlink()


# tools, sidecar, command line

def tool_versions() -> Dict[str, Optional[str]]:
    """Versions of the programs a fetch ran with; None for one that is not installed."""
    from importlib import metadata

    def first_line(argv: List[str]) -> Optional[str]:
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else None

    try:
        ejs = metadata.version("yt-dlp-ejs")
    except metadata.PackageNotFoundError:
        ejs = None
    try:
        ytdlp = first_line(ytdlp_command() + ["--version"])
    except FetchError:
        ytdlp = None
    deno = Path(sys.executable).with_name("deno")
    deno = str(deno) if deno.is_file() else shutil.which("deno")
    return {"tutubo": __version__, "python": platform.python_version(), "yt-dlp": ytdlp, "yt-dlp-ejs": ejs,
            "deno": first_line([deno, "--version"]) if deno else None}


def _check_id(video_id: str) -> None:
    if not _ID.fullmatch(video_id or ""):
        raise ValueError(f"not a YouTube video id: {video_id!r}")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _relative(path: Optional[str], dest: Path) -> Optional[str]:
    return os.path.relpath(path, dest) if path else None


def _complete(meta: Path, dest: Path, request: dict) -> bool:
    """True when ``meta`` records a fetch made with the same ``request`` that finished (``complete``) and every file it names is
    still there."""
    try:
        record = json.loads(meta.read_text())
        if record.get("request") != request or record.get("complete") is not True:
            return False
        files = [c["file"] for c in record.get("captions") or () if c.get("file")]
        files += [record["audio"]["file"]] if record.get("audio") else []
        return all((dest / f).is_file() for f in files)
    except Exception:  # a sidecar that is not a record this program wrote, however deeply it is nested
        return False


def fetch_video(video_id: str, dest, kinds: Sequence[str] = ("manual", "asr"), formats: Sequence[str] = ("json3", "vtt"),
                audio: bool = True, captions: bool = True, family: Optional[str] = "ipv4", session: Optional[object] = None,
                pace: Callable[[], None] = lambda: None, on_progress: Callable[[int, Optional[int]], None] = lambda d, t: None,
                tools: Optional[dict] = None) -> dict:
    """Fetch one video's details, captions and audio into ``dest`` and write ``meta/<id>.json`` last; returns that record. The record
    says ``complete`` only when no caption file has an ``error`` and the audio, when asked for, was written. A live stream that is
    running or has not started is not fetched: the record gives the reason as ``skipped``."""
    _check_id(video_id)
    dest = Path(dest)
    session = session or plain_session(family)
    pace()
    details = video_details(video_id, session=session)
    wanted = [t for t in details.caption_tracks if t.kind in kinds and not t.is_translation]
    skipped = "live stream in progress" if details.is_live else "live stream or premiere has not started" if details.is_upcoming else None
    if skipped and details.playability_reason:
        skipped = f"{skipped}: {details.playability_reason}"
    info, caption_files, got = None, [], None
    if skipped is None:
        if audio or (captions and wanted):
            pace()
            info = ytdlp_info(video_id, family)
        if captions and wanted:
            caption_files = fetch_captions(video_id, dest, kinds, True, formats, info, session, family, pace, listed=wanted)
        if audio:
            pace()
            got = fetch_audio(video_id, dest, info=info, family=family, on_progress=on_progress)
    original = None
    if got:
        if "original" in (got.note or "").lower() or not any(t.language for t in details.audio_tracks):
            original = True
        elif any(t.original for t in details.audio_tracks):
            original = False
    record = {
        **{k: v for k, v in details.as_dict.items() if k != "audio_tracks"},
        "request": _request(kinds, formats, audio, captions),
        "complete": skipped is None and not any(c.error for c in caption_files) and (got is not None or not audio),
        **({"skipped": skipped} if skipped else {}),
        "captions": [{"file": _relative(c.path, dest), "language": c.language, "kind": c.kind,
                      "is_translation": c.is_translation, "format": c.format, "bytes": c.bytes,
                      **({"error": c.error} if c.error else {})} for c in caption_files],
        "audio": None if got is None else {
            "file": _relative(got.path, dest), "format_id": got.format_id, "ext": got.ext, "codec": got.codec,
            "sample_rate": got.sample_rate, "channels": got.channels, "bitrate_kbps": got.bitrate_kbps,
            "language": got.language, "note": got.note, "original": original, "bytes": got.bytes},
        "audio_tracks_offered": [asdict(t) for t in details.audio_tracks],
        "tools": tools if tools is not None else tool_versions(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_atomic(dest / "meta" / f"{video_id}.json", (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode())
    return record


def _request(kinds: Sequence[str], formats: Sequence[str], audio: bool, captions: bool) -> dict:
    return {"audio": audio, "captions": captions, "kinds": list(kinds), "formats": list(formats)}


def _names(text: str) -> List[str]:
    names = [n.strip() for n in text.split(",") if n.strip()]
    if not names or not all(_SAFE.fullmatch(n) for n in names):
        raise argparse.ArgumentTypeError(f"expected a comma-separated list of names, got {text!r}")
    return names


def _kinds(text: str) -> List[str]:
    names = _names(text)
    unknown = [n for n in names if n not in ("manual", "asr")]
    if unknown:
        raise argparse.ArgumentTypeError(f"caption kinds are manual and asr, got {', '.join(unknown)}")
    return names


def main(argv: Optional[Sequence[str]] = None, session: Optional[object] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tutubo.fetch", allow_abbrev=False,
        description="Fetch videos' details, original caption tracks and original audio into a folder. Prints one JSON object "
                    "per line. A video id that starts with '-' goes after '--', and '-' reads the ids from standard input. "
                    "Exit status: 0 done, 1 a video failed or is incomplete, 2 bad arguments, 75 YouTube asked for a bot check "
                    "and the run stopped, 143 terminated by SIGTERM.")
    parser.add_argument("video_ids", nargs="+", metavar="VIDEO_ID")
    parser.add_argument("--dest", required=True, type=Path, help="folder to write audio/, captions/ and meta/ under")
    parser.add_argument("--kinds", type=_kinds, default=["manual", "asr"], help="caption kinds: manual,asr (default both)")
    parser.add_argument("--formats", type=_names, default=["json3", "vtt"], help="caption formats (default json3,vtt)")
    parser.add_argument("--no-audio", action="store_true", help="details and captions only")
    parser.add_argument("--no-captions", action="store_true", help="details and audio only")
    parser.add_argument("--gap", type=float, default=5.0, help="seconds between requests (default 5)")
    parser.add_argument("--family", choices=("ipv4", "ipv6", "any"), default="ipv4", help="IP family (default ipv4)")
    args = parser.parse_args(argv)
    ids = [i for given in args.video_ids for i in (sys.stdin.read().split() if given == "-" else [given])]
    for given in ids:
        if not _ID.fullmatch(given):
            parser.error(f"not a YouTube video id: {given!r}")

    def emit(event: str, **fields) -> None:
        print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)

    last = [0.0]

    def pace() -> None:
        wait = last[0] + args.gap - time.monotonic()
        if last[0] and wait > 0:
            time.sleep(wait)
        last[0] = time.monotonic()

    session = session or plain_session(args.family)
    tools = None
    failed = False
    current = [None]
    terminating: List[int] = []

    def terminate(signum, frame):
        if terminating:
            return  # the first SIGTERM is being answered: a second must not cut that short
        terminating.append(signum)
        raise Terminated()

    handler = signal.signal(signal.SIGTERM, terminate) if threading.current_thread() is threading.main_thread() else None
    try:
        for vid in ids:
            current[0] = vid
            meta = args.dest / "meta" / f"{vid}.json"
            if _complete(meta, args.dest, _request(args.kinds, args.formats, not args.no_audio, not args.no_captions)):
                emit("skip", video_id=vid, meta=_relative(str(meta), args.dest))
                continue
            tools = tools or tool_versions()
            try:
                record = fetch_video(vid, args.dest, kinds=args.kinds, formats=args.formats, audio=not args.no_audio,
                                     captions=not args.no_captions, family=args.family, session=session, pace=pace, tools=tools,
                                     on_progress=lambda done, total, vid=vid: emit("progress", video_id=vid, bytes=done, total=total))
            except backoff.BackedOff as e:
                emit("paused", video_id=vid, kind=e.kind, until=datetime.fromtimestamp(e.until, timezone.utc).isoformat(
                    timespec="seconds"), error=_scrub(e))
                return EXIT_PAUSED
            except (CaptionError, FetchError, OSError) as e:
                failed = True
                emit("error", video_id=vid, error=_scrub(e))
                continue
            if record.get("skipped"):
                emit("skipped", video_id=vid, reason=record["skipped"], meta=_relative(str(meta), args.dest))
            elif not record["complete"]:
                failed = True
                errors = [c["error"] for c in record["captions"] if c.get("error")]
                emit("error", video_id=vid, error=f"{len(errors)} caption files failed: {errors[0]}", meta=_relative(str(meta), args.dest))
            else:
                emit("done", video_id=vid, meta=_relative(str(meta), args.dest))
    except Terminated:
        emit("terminated", video_id=current[0])
        return EXIT_TERMINATED
    finally:
        if handler is not None:
            signal.signal(signal.SIGTERM, handler)
    return EXIT_ERROR if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
