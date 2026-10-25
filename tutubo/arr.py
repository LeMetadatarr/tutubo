"""tutubo as an arrkit indexer and download client, music first.

Installing tutubo into an app built on arrkit makes both available under the name ``tutubo`` (entry points in the groups
``arrkit.indexers`` and ``arrkit.clients``). The app lists them as plugins and uses them only once its settings enable them.

tutubo does not depend on arrkit and this module never imports it. arrkit finds a plugin by loading the entry point and checking that the
class derives from its own base, so ``Tutubo`` and ``TutuboClient`` are built the first time an attribute of that name is read: the
behaviour lives in ``IndexerPlugin`` and ``ClientPlugin`` here, and the classes put them in front of ``arrkit.indexers.Indexer`` and
``arrkit.clients.direct.Direct``. Without arrkit installed, reading either name raises AttributeError, so ``hasattr`` says no and nothing else is affected.

Indexer. ``search(query)`` looks for music on YouTube Music (``source`` music, the default), on YouTube (``youtube``) or both. A query
with ``artist`` and ``album`` (``title`` is read as the album name when ``album`` is missing) finds albums: one release per album whose
name and artist hold the words asked for, its tracks listed for the first ``resolve`` albums. A query with ``track`` or only a ``term``
finds tracks: one release per song or video, with ``audio_only`` true for the auto-generated "Official Audio" uploads of an artist's Topic
channel, which carry the album, track number and year and are the best source of tags. A release adds to arrkit's keys: ``release_type``
("album" or "track"), ``artist``, ``album``, ``track``, ``track_number``, ``year``, ``duration_seconds`` and ``seconds``, ``channel``,
``thumbnail``, ``explicit``, ``audio_only``, ``topic``, ``video_id``, ``browse_id``, ``playlist_id``, ``tracks`` ([{video_id, title,
track_number, seconds}] of an album) and ``tags``. ``protocol`` is ``youtube``, so only this client takes the releases; ``kind`` is
``download``, or ``stream`` when ``delivery`` says so (no client here takes those). ``rss`` is empty: tutubo follows no feed.

Client. ``add(release)`` queues a job in a job queue in the app's state folder (arrkit's direct client, one job at a time). The job
downloads the audio only, one yt-dlp run per track, into ``<download_dir>/<release title>-<job>/`` as ``<NN> - <title>.<ext>`` (names
cut to 200 bytes), through a staging folder that is removed whether the run ends, fails or is cancelled. Tags and the cover are embedded
with yt-dlp (``embed``), and the artist, album, track and year the indexer knew are written as well. ``status()`` lists the files.

Pacing and back-off. Requests are spaced ``delay`` seconds apart across the whole process. Before each one the plugin reads tutubo's
shared back-off (tutubo.backoff), and writes it when YouTube asks for a check; when ``media_archivist_url`` is set it also reads
media-archivist's ``/api/v1/youtube/backoff`` and honours a pause there. A paused queue waits and its jobs say "YouTube is asking for a
check: paused until ...". Nothing here goes around a check. ``ip_family`` (default ipv4) pins every connection to one address family."""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from datetime import datetime, timezone

import requests
from ytmusicapi import YTMusic

from tutubo import backoff
from tutubo.fetch import _scrub

API_VERSION = 1
SLUG = "tutubo"
PROTOCOL = "youtube"
NAME_BYTES = 200
STDERR_BYTES = 1 << 16
MARK_PROGRESS, MARK_FILE = "TUTUBO-PROGRESS", "TUTUBO-FILE"
log = logging.getLogger(__name__)

_pace_lock, _last = threading.Lock(), [0.0]
_workers, _workers_lock = {}, threading.Lock()
_built = {}
_clients, _clients_lock = {}, threading.Lock()
_build_lock = threading.Lock()


def pace(delay):
    """Waits until ``delay`` seconds have passed since the last request of any instance in this process."""
    with _pace_lock:
        wait = _last[0] + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def safe(text):
    """``text`` usable as a folder name."""
    return re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "-", text or "").strip(" .")[:150]


def fold(text):
    text = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return " ".join(re.findall(r"\w+", "".join(c for c in text if not unicodedata.combining(c))))


def holds(name, wanted):
    """True when every word of ``wanted`` is in ``name`` (accents and case ignored); an empty ``wanted`` matches."""
    have = set(fold(name).split())
    return all(w in have for w in fold(wanted).split())


def stderr_tail(file, keep=STDERR_BYTES):
    """The last ``keep`` bytes of what a finished process wrote to ``file``. A file, unlike a pipe, cannot be held open past the end of
    the process by a child it left behind, and is closed here."""
    with file:
        file.seek(0, os.SEEK_END)
        file.seek(max(0, file.tell() - keep))
        return file.read().decode("utf-8", "replace")


def cut(text, limit=NAME_BYTES):
    """``text`` as a file name stem of at most ``limit`` bytes of UTF-8, cut between characters."""
    text = safe(text) or "track"
    while len(text.encode()) > limit:
        text = text[:-1]
    return text.rstrip(" .") or "track"


def stamp(until):
    return datetime.fromtimestamp(until, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


REMOTE_BYTES = 1 << 16


def _read_pause(url, api_key, kind, deadline, out):
    headers = {"Accept": "application/json", **({"X-Api-Key": api_key} if api_key else {})}
    try:
        with requests.get(url.rstrip("/") + "/api/v1/youtube/backoff", headers=headers, timeout=min(deadline, 2), stream=True,
                          allow_redirects=False) as reply:
            if reply.status_code != 200:
                return
            body, stop = b"", time.monotonic() + deadline
            for chunk in reply.iter_content(8192):
                body += chunk
                if len(body) > REMOTE_BYTES or time.monotonic() > stop:
                    return
        row = json.loads(body)["kinds"][kind]
        if row.get("paused"):
            until = datetime.fromisoformat(row["until"].replace("Z", "+00:00")).timestamp()
            out.append(min(until, time.time() + backoff.MAX_WAIT_S))
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as e:
        log.debug("media-archivist back-off not read: %s", e)


def remote_pause(url, api_key, kind, timeout=5):
    """Epoch seconds until which media-archivist pauses ``kind``, or 0 (not paused, or it did not answer within ``timeout`` seconds).
    Redirects are not followed, the answer is read up to 64 KiB, and the pause never runs longer than tutubo's own longest."""
    if not url:
        return 0
    out = []
    reader = threading.Thread(target=_read_pause, args=(url, api_key, kind, timeout, out), daemon=True)
    reader.start()
    reader.join(timeout)
    return out[0] if out and not reader.is_alive() else 0


class Backend:
    """What the plugin asks of YouTube, in plain dicts. Tests give the classes another one."""

    def __init__(self, family):
        self.family = family

    def _music(self):
        """The YouTube Music client of this family, built once. Building it makes a request, so it counts as one: a bot check pauses
        ``search`` and is not retried."""
        with _clients_lock:
            if self.family not in _clients:
                from tutubo.ytmus import pinned_session
                _clients[self.family] = backoff.guarded("search", YTMusic, requests_session=pinned_session(self.family))
            return _clients[self.family]

    def music(self, query, kind):
        """Raw YouTube Music results for ``query`` of one kind ("songs", "albums", "videos")."""
        return backoff.guarded("search", self._music().search, query, filter=kind)

    def album(self, browse_id):
        """The raw album: tracks, year, audioPlaylistId."""
        return backoff.guarded("details", self._music().get_album, browse_id)

    def videos(self, query, limit):
        """[{video_id, title, author, channel_id, length, thumbnail}] from a YouTube search."""
        from tutubo import YoutubeSearch
        out = []
        for v in YoutubeSearch(query, family=self.family).iterate_videos(max_res=limit):
            out.append({"video_id": v.video_id, "title": v.title, "author": v.author, "channel_id": v.channel_id, "length": v.length,
                        "thumbnail": v.thumbnail_url})
        return out


def artists_of(raw):
    return ", ".join(a.get("name", "") for a in raw.get("artists") or () if isinstance(a, dict) and a.get("name")) or raw.get("artist") or ""


class IndexerPlugin:
    """The behaviour of the indexer; ``Tutubo`` adds arrkit's Indexer as its base and ``Error`` as IndexerError."""

    implementation = SLUG
    name = "YouTube (tutubo)"
    protocol = PROTOCOL
    caps = {"search": True, "rss": False}
    API_VERSION = API_VERSION
    backend = Backend
    fields = [("source", "Search music, youtube or both", "music", {"address": False}),
              ("delay", "Seconds between requests to YouTube", "3", {"address": False}),
              ("max_results", "Releases per answer at most", "20", {"address": False}),
              ("resolve", "Albums per answer whose track list is read (one request each)", "3", {"address": False}),
              ("delivery", "Deliver as download or stream", "download", {"address": False}),
              ("ip_family", "Address family for every request (ipv4, ipv6 or any)", "ipv4", {"address": False}),
              ("media_archivist_url", "media-archivist address, to honour its pause (empty: none)", "", {"address": True}),
              ("media_archivist_api_key", "media-archivist API key", "", {"secret": True})]

    def family(self):
        return None if self.settings["ip_family"].lower() in ("", "any") else self.settings["ip_family"].lower()

    def pause(self, kind):
        return max(backoff.shared().blocked_until(kind) or 0,
                   remote_pause(self.settings["media_archivist_url"], self.settings["media_archivist_api_key"], kind))

    def ask(self, kind, fn, *args):
        """One request of ``kind`` through the pacing and both back-offs; IndexerError for a pause or a failure."""
        until = self.pause(kind)
        if until > time.time():
            raise self.Error(str(backoff.BackedOff(kind, until)))
        pace(self.num("delay", 3))
        try:
            return fn(*args)
        except backoff.BackedOff as e:
            raise self.Error(str(e)) from None
        except Exception as e:  # ytmusicapi, requests and urllib each raise their own; any of them means YouTube did not answer as expected
            raise self.Error(f"tutubo: {type(e).__name__}: {e}") from None

    def kind(self, query):
        kind = str((query or {}).get("kind") or self.settings["delivery"] or "download").lower()
        if kind not in ("download", "stream"):
            raise self.Error(f"delivery must be download or stream, not {kind!r}")
        return kind

    def release_of(self, kind, **kw):
        base = dict(info_url=kw["url"], kind=kind, protocol=PROTOCOL if kind == "download" else "stream", size=None)
        return self.release(**base | kw)

    def track(self, raw, kind):
        vid = raw.get("videoId") or ""
        if not vid:
            return None
        video_type = raw.get("videoType") or ""
        audio_only = "ATV" in video_type or "OFFICIAL_SOURCE_MUSIC" in video_type
        artist = artists_of(raw)
        album = raw.get("album")
        album = album.get("name", "") if isinstance(album, dict) else album or ""
        year = int(raw["year"]) if str(raw.get("year") or "").isdigit() else None
        seconds = raw.get("duration_seconds")
        seconds = int(seconds) if isinstance(seconds, (int, float)) else None
        thumbs = raw.get("thumbnails") or []
        title = raw.get("title") or ""
        return self.release_of(
            kind, title=f"{artist} - {title}" if artist else title, guid=f"{SLUG}:video:{vid}",
            url=("https://music.youtube.com/watch?v=" if audio_only else "https://www.youtube.com/watch?v=") + vid,
            published=f"{year}-01-01" if year else "", release_type="track", artist=artist, album=album, track=title,
            track_number=raw.get("trackNumber"), year=year, duration_seconds=seconds, seconds=seconds, channel=artist,
            thumbnail=thumbs[-1]["url"] if thumbs else "", explicit=bool(raw.get("isExplicit")), audio_only=audio_only,
            topic=audio_only, video_id=vid, entry=vid,
            tags=["official audio", "topic"] if audio_only else [])

    def video(self, v, kind):
        author = v["author"] or ""
        topic = author.endswith(" - Topic")
        artist = author[:-len(" - Topic")] if topic else ""
        seconds = int(v["length"]) if v.get("length") else None
        return self.release_of(
            kind, title=v["title"], guid=f"{SLUG}:video:{v['video_id']}", url="https://www.youtube.com/watch?v=" + v["video_id"],
            published="", release_type="track", artist=artist, album="", track=v["title"], year=None, duration_seconds=seconds,
            seconds=seconds, channel=author, channel_id=v.get("channel_id") or "", thumbnail=v.get("thumbnail") or "", explicit=False,
            audio_only=topic, topic=topic, video_id=v["video_id"], entry=v["video_id"], tags=["topic"] if topic else [])

    def album(self, raw, kind, backend, resolve):
        browse = raw.get("browseId") or ""
        if not browse:
            return None
        artist, year = artists_of(raw), (int(raw["year"]) if str(raw.get("year") or "").isdigit() else None)
        full = {}
        if resolve:
            try:
                full = self.ask("details", backend.album, browse)
            except self.Error as e:
                log.info("album %s listed without its tracks: %s", browse, e)
        tracks = [{"video_id": t["videoId"], "title": t.get("title") or "", "track_number": t.get("trackNumber") or i,
                   "seconds": t.get("duration_seconds")} for i, t in enumerate(full.get("tracks") or (), 1) if t.get("videoId")]
        playlist = full.get("audioPlaylistId") or raw.get("audioPlaylistId") or ""
        thumbs = raw.get("thumbnails") or []
        name = raw.get("title") or ""
        return self.release_of(
            kind, title=f"{artist} - {name}" + (f" ({year})" if year else ""), guid=f"{SLUG}:album:{browse}",
            url=f"https://music.youtube.com/playlist?list={playlist}" if playlist else f"https://music.youtube.com/browse/{browse}",
            published=f"{year}-01-01" if year else "", release_type="album", artist=artist, album=name, track="", year=year,
            duration_seconds=sum(t["seconds"] or 0 for t in tracks) or None, seconds=sum(t["seconds"] or 0 for t in tracks) or None,
            channel=artist, thumbnail=thumbs[-1]["url"] if thumbs else "", explicit=bool(raw.get("isExplicit")), audio_only=True,
            topic=False, browse_id=browse, playlist_id=playlist, track_count=len(tracks) or None, tracks=tracks, entry=browse, tags=["album"])

    def search(self, query):
        query = {"term": query} if isinstance(query, str) else dict(query or {})
        kind = self.kind(query)
        artist, album = str(query.get("artist") or "").strip(), str(query.get("album") or query.get("title") or "").strip()
        track = str(query.get("track") or "").strip()
        term = str(query.get("term") or "").strip()
        limit = int(self.num("max_results", 20)) or 20
        source = self.settings["source"].lower()
        if source not in ("music", "youtube", "both"):
            raise self.Error(f"source must be music, youtube or both, not {source!r}")
        backend = self.backend(self.family())
        out = []
        if source in ("music", "both"):
            if artist and album and not track:
                text = f"{artist} {album}"
                found = [r for r in self.ask("search", backend.music, text, "albums")
                         if r.get("resultType") == "album" and holds(r.get("title"), album) and holds(artists_of(r), artist)]
                resolve = int(self.num("resolve", 3))
                out += [self.album(r, kind, backend, i < resolve) for i, r in enumerate(found[:limit])]
            else:
                text = " ".join(x for x in (artist, track or term or album) if x)
                if not text:
                    return []
                for r in self.ask("search", backend.music, text, "songs"):
                    if r.get("resultType") in ("song", "video") and holds(r.get("title"), track) and holds(artists_of(r), artist):
                        out.append(self.track(r, kind))
        if source in ("youtube", "both"):
            text = " ".join(x for x in (artist, album, track, term) if x)
            if text:
                out += [self.video(v, kind) for v in self.ask("search", backend.videos, text + (" audio" if artist else ""), limit)]
        return [r for r in out if r][:limit]

    def test(self):
        try:
            import ytmusicapi  # noqa: F401
        except ImportError:
            return False, "ytmusicapi is not installed"
        until = self.pause("search")
        if until > time.time():
            return False, str(backoff.BackedOff("search", until))
        return True, "ready (this check makes no request)"


class ClientPlugin:
    """The behaviour of the download client; ``TutuboClient`` adds arrkit's Direct as its base, ``Error`` as ClientError and ``JobQueue``."""

    implementation = SLUG
    name = "YouTube (tutubo)"
    protocols = (PROTOCOL,)
    category = ""
    API_VERSION = API_VERSION
    backend = Backend
    fields = [("download_dir", "Download folder", ""),
              ("delay", "Seconds between requests to YouTube", "3", {"address": False}),
              ("ip_family", "Address family for every request (ipv4, ipv6 or any)", "ipv4", {"address": False}),
              ("audio_format", "Audio format (best keeps the original codec; or m4a, mp3, opus, flac)", "best", {"address": False}),
              ("embed", "Embed tags and the cover with yt-dlp", "true", {"address": False}),
              ("yt_dlp", "yt-dlp program", "yt-dlp", {"address": False}),
              ("media_archivist_url", "media-archivist address, to honour its pause (empty: none)", "", {"address": True}),
              ("media_archivist_api_key", "media-archivist API key", "", {"secret": True})]

    def __init__(self, inst=None, state_dir=None):
        super().__init__(inst, state_dir)
        self.queue = self.JobQueue(state_dir, f"{SLUG}-{self.inst.get('id') or 0}.json", prefix=f"{SLUG}_")

    # back-off

    def pause(self):
        return max(backoff.shared().blocked_until("download") or 0,
                   remote_pause(self.settings["media_archivist_url"], self.settings["media_archivist_api_key"], "download"))

    def waiting(self):
        return max(0, self.pause() - time.time())

    def start(self):
        key = self.queue.store.path(self.queue.name)
        with _workers_lock:
            q, t = _workers.get(key, (None, None))
            if t and t.is_alive():
                return t
            _workers[key] = (self.queue, self.queue.start(self.run, blocked=self.waiting, idle=30))
            return _workers[key][1]

    def stop(self):
        """Stops this instance's worker (it finishes the track it is downloading first)."""
        with _workers_lock:
            q, t = _workers.pop(self.queue.store.path(self.queue.name), (None, None))
        if q:
            q.stop()

    # queue

    def add(self, release):
        kind = release.get("release_type") or ("album" if release.get("browse_id") else "track")
        if kind == "album" and not (release.get("browse_id") or release.get("tracks")):
            raise self.Error("the release names no album")
        if kind == "track" and not re.fullmatch(r"[\w-]{11}", str(release.get("video_id") or "")):
            raise self.Error("the release names no YouTube video")
        self.folder()
        extra = {k: release.get(k) for k in ("release_type", "video_id", "browse_id", "tracks", "artist", "album", "track", "track_number", "year")}
        extra["release_type"] = kind
        jid = self.queue.add(release.get("video_id") or release.get("browse_id"), cut(release.get("title") or "download", 150),
                             self.category or "*", 0, own_folder=True, **extra)
        self.start()
        return jid

    def status(self):
        rows, jobs = super().status(), {j["id"]: j for j in self.queue.load()}
        until = self.pause()
        for r in rows:
            j = jobs.get(r["client_id"]) or {}
            r["files"] = list(j.get("files") or [])
            if j.get("status") == "Queued" and until > time.time():
                r["message"] = str(backoff.BackedOff("download", until))
        return rows

    # one job

    def ytdlp(self, url, staging, stem, tags, number=None):
        s = self.settings
        argv = [s["yt_dlp"] or "yt-dlp", "--ignore-config", "--no-playlist", "--newline", "--no-mtime", "--no-colors", "-f", "bestaudio/best",
                "-x", "--audio-format", s["audio_format"] or "best",
                "--progress-template", f"download:{MARK_PROGRESS} %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s",
                "--print", f"after_move:{MARK_FILE} %(filepath)s", "-o", os.path.join(staging, stem).replace("%", "%%") + ".%(ext)s"]
        if s["ip_family"].lower() == "ipv4":
            argv.append("--force-ipv4")
        elif s["ip_family"].lower() == "ipv6":
            argv.append("--force-ipv6")
        if s["embed"].lower() not in ("false", "0", "no", "off", ""):
            argv += ["--embed-metadata", "--embed-thumbnail", "--convert-thumbnails", "jpg"]
            song = tags.get("title") or tags.get("track")
            names = {"artist": tags.get("artist"), "album": tags.get("album"), "title": song, "track": song,
                     "track_number": number, "release_year": tags.get("year")}
            for field, value in names.items():
                if value:
                    value = str(value).replace("\x00", "")
                    # a literal as the "from" template: % doubled, : escaped
                    argv += ["--parse-metadata", f"{str(value).replace('%', '%%').replace(':', chr(92) + ':')}:%({field})s"]
        return argv + ["--", url]

    def run(self, job, ctl):
        until = self.pause()
        if until > time.time():
            ctl.set(error=str(backoff.BackedOff("download", until)))
            return "blocked"
        target = os.path.join(self.folder(), job.get("folder") or job["title"] or "download")
        staging = os.path.join(target, ".tutubo-part")
        os.makedirs(target, exist_ok=True)
        try:
            tracks = self.tracks_of(job)
            files, total = [], len(tracks)
            for i, t in enumerate(tracks):
                if ctl.cancelled:
                    return "cancelled"
                made, result = self.fetch(t, i, total, job, ctl, staging, target)
                if result == "blocked":
                    ctl.set(files=files)
                    return "blocked"
                if result != "done":
                    if files:
                        result = f"{len(files)} of {total} tracks downloaded; {result}"
                    ctl.set(files=files)
                    return result
                files += made
            ctl.set(files=files, bytes=sum(os.path.getsize(os.path.join(target, f)) for f in files), path=target, file=files[0] if files else "",
                    error="")
            return "done" if files else "yt-dlp finished without a file"
        except RuntimeError as e:
            return str(e)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            if not os.listdir(target):
                os.rmdir(target)

    def tracks_of(self, job):
        """[{video_id, title, track_number, artist, album, year}] to download for a job."""
        base = {k: job.get(k) for k in ("artist", "album", "year")}
        if job.get("release_type") != "album":
            return [base | {"video_id": job["ref"], "title": job.get("track") or job["title"], "track_number": job.get("track_number")}]
        listed = job.get("tracks") or []
        if not listed:
            pace(self.num("delay", 3))
            raw = self.backend(None if self.settings["ip_family"].lower() in ("", "any") else self.settings["ip_family"].lower()).album(job["ref"])
            listed = [{"video_id": t["videoId"], "title": t.get("title") or "", "track_number": t.get("trackNumber") or i}
                      for i, t in enumerate(raw.get("tracks") or (), 1) if t.get("videoId")]
        if not listed:
            raise self.Error("YouTube Music lists no track for this album")
        return [base | {"video_id": t["video_id"], "title": t["title"], "track_number": t.get("track_number") or i}
                for i, t in enumerate(listed, 1)]

    def fetch(self, t, i, total, job, ctl, staging, target):
        """([file names placed], "done" | "blocked" | message) for one track."""
        until = self.pause()
        if until > time.time():
            ctl.set(error=str(backoff.BackedOff("download", until)))
            return [], "blocked"
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging)
        number = t.get("track_number")
        stem = cut(f"{int(number):02d} - {t['title']}" if number and total > 1 else t["title"])
        pace(self.num("delay", 3))
        started = time.time()
        errfile = tempfile.TemporaryFile()
        proc = subprocess.Popen(self.ytdlp("https://www.youtube.com/watch?v=" + t["video_id"], staging, stem, t, number),
                                stdout=subprocess.PIPE, stderr=errfile, text=True)
        ctl.on_cancel(proc.terminate)
        done = None
        for line in proc.stdout:
            if line.startswith(MARK_PROGRESS + " "):
                p = line.split()[1:4]
                try:
                    got, size = float(p[0]), float(p[1] if p[1] != "NA" else p[2])
                    ctl.progress((i * 100 + 100 * got / size) / total)
                except (ValueError, IndexError, ZeroDivisionError):
                    pass
            elif line.startswith(MARK_FILE + " "):
                done = line[len(MARK_FILE) + 1:].strip()
        code = proc.wait()
        raw = stderr_tail(errfile)
        err = _scrub(raw)
        if ctl.cancelled:
            return [], "cancelled"
        if code != 0:
            if backoff.failed("download", raw):
                ctl.set(error=str(backoff.paused("download")))
                return [], "blocked"
            return [], f"yt-dlp failed: {err.strip().splitlines()[-1] if err.strip() else 'exit ' + str(code)}"
        backoff.after_success("download", started)
        if not done or not os.path.isfile(done):
            return [], "yt-dlp finished without a file"
        name = stem + os.path.splitext(done)[1]
        os.replace(done, os.path.join(target, name))
        return [name], "done"

    def test(self):
        ok, msg = super().test()
        if not ok:
            return ok, msg
        if not shutil.which(self.settings["yt_dlp"] or "yt-dlp"):
            return False, "yt-dlp is not installed"
        until = self.pause()
        if until > time.time():
            return False, str(backoff.BackedOff("download", until))
        if self.settings["embed"].lower() not in ("false", "0", "no", "off", "") and not shutil.which("ffmpeg"):
            return False, "ffmpeg is not installed; tags and covers cannot be embedded (set embed to false to go without)"
        return True, msg



def _build():
    from arrkit.clients import ClientError
    from arrkit.clients.direct import Direct
    from arrkit.clients.jobs import JobQueue
    from arrkit.indexers import Indexer, IndexerError

    _built["Tutubo"] = type("Tutubo", (IndexerPlugin, Indexer), {"Error": IndexerError, "__module__": __name__})
    _built["TutuboClient"] = type("TutuboClient", (ClientPlugin, Direct), {"Error": ClientError, "JobQueue": JobQueue, "__module__": __name__})
    _built["IMPLEMENTATION"] = _built["Tutubo"]


def __getattr__(name):
    """``Tutubo``, ``TutuboClient`` and ``IMPLEMENTATION`` are built on first use, because they derive from arrkit's classes."""
    if name not in ("Tutubo", "TutuboClient", "IMPLEMENTATION"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    with _build_lock:
        if name not in _built:
            try:
                _build()
            except ImportError as e:
                raise AttributeError(f"{name} needs arrkit: {e}") from e
    return _built[name]
