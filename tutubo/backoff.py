"""One bot-check pause for every program on the machine that uses tutubo.

YouTube challenges some kinds of request and not others, so each kind pauses on its own: ``details`` (per-video metadata), ``listing``
(channel and playlist pages), ``feed``, ``thumb``, ``search`` and ``download``. The first bot check of a kind pauses it for 30 minutes;
a further check after that pause has run out doubles the wait, up to 24 hours. A check that arrives while the kind is already paused
leaves the pause as it is, and a request that succeeds ends the pause and resets the wait. These are the rules media-archivist keeps
for its own index, and the rows have the same fields (``retry_at``, ``wait_s``, ``at``).

The state is a JSON file, ``backoff.json``, in tutubo's state folder: ``$TUTUBO_STATE_DIR``, else ``$XDG_STATE_HOME/tutubo``, else
``~/.local/state/tutubo``. It is replaced atomically on every write, and a write holds an advisory lock on ``backoff.lock`` in the same
folder, so processes and threads that record a check at the same moment do not lose each other's pause. Locks do not work across a
network mount: keep the folder on a local disk. A reader takes no lock; the replace guarantees it sees a whole file.

tutubo reads the file before each request it sends and writes it when YouTube answers with a bot check (HTTP 429 or the page that asks to
sign in to confirm you are not a bot). ``TUTUBO_BACKOFF=off`` turns this off. tutubo never tries to get past a check: it stops asking."""
from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

try:
    import fcntl
except ImportError:  # no advisory locks (Windows): writers in different processes can overwrite each other's pause
    fcntl = None

KINDS = ("details", "listing", "feed", "thumb", "search", "download")
INITIAL_WAIT_S = 30 * 60.0
MAX_WAIT_S = 24 * 3600.0
ENV_DIR = "TUTUBO_STATE_DIR"
ENV_SWITCH = "TUTUBO_BACKOFF"
BOT_CHECK = re.compile(r"not a bot|HTTP Error 429|HTTP 429|Too Many Requests", re.I)

_threads = threading.RLock()


class BackedOff(RuntimeError):
    """A request was not sent because YouTube asked for a check and the pause has not run out."""

    def __init__(self, kind: str, until: float, reason: str = ""):
        self.kind, self.until, self.reason = kind, until, reason
        when = datetime.fromtimestamp(until, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        super().__init__(f"YouTube is asking for a check: {kind} requests paused until {when}")


def state_dir() -> Path:
    given = os.environ.get(ENV_DIR)
    if given:
        return Path(given).expanduser()
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".local" / "state") / "tutubo"


def is_bot_check(text: object) -> bool:
    """True when ``text`` (an error message, a program's stderr) says YouTube refused the request as a bot check or a rate limit."""
    return bool(BOT_CHECK.search(str(text or "")))


class Backoff:
    def __init__(self, path=None, *, initial: float = INITIAL_WAIT_S, maximum: float = MAX_WAIT_S,
                 clock: Callable[[], float] = time.time):
        self._path = Path(path) if path else None
        self.initial, self.maximum, self.clock = initial, maximum, clock

    @property
    def path(self) -> Path:
        return self._path or state_dir() / "backoff.json"

    def _rows(self) -> Dict[str, dict]:
        try:
            rows = json.loads(self.path.read_text()).get("kinds")
        except (OSError, ValueError, AttributeError):
            return {}
        return {k: v for k, v in rows.items() if k in KINDS and isinstance(v, dict)} if isinstance(rows, dict) else {}

    @contextlib.contextmanager
    def _write(self):
        """The rows under the lock; they are saved when the block ends without an error."""
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        with _threads, open(folder / (self.path.stem + ".lock"), "a") as lock:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_EX)
            rows = self._rows()
            yield rows
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=self.path.name + ".")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump({"kinds": rows}, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise

    @staticmethod
    def _check(kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown back-off kind {kind!r}; expected one of {', '.join(KINDS)}")

    def blocked_until(self, kind: str) -> Optional[float]:
        """When the pause of ``kind`` ends (epoch seconds), or None when it is not paused."""
        self._check(kind)
        row = self._rows().get(kind)
        return row["retry_at"] if row and row.get("retry_at", 0) > self.clock() else None

    def remaining(self, kind: str) -> float:
        until = self.blocked_until(kind)
        return max(0.0, until - self.clock()) if until else 0.0

    def guard(self, kind: str) -> None:
        """Raise BackedOff when ``kind`` is paused."""
        until = self.blocked_until(kind)
        if until:
            raise BackedOff(kind, until)

    def mark_blocked(self, kind: str) -> float:
        """Record a bot check for ``kind``; the seconds the pause lasts."""
        self._check(kind)
        with self._write() as rows:
            now = self.clock()
            row = rows.get(kind)
            if row and now < row["retry_at"]:
                return row["retry_at"] - now
            wait = min(row["wait_s"] * 2, self.maximum) if row else self.initial
            rows[kind] = {"retry_at": now + wait, "wait_s": wait, "at": now}
            return wait

    def mark_clear(self, kind: str, started_at: Optional[float] = None) -> None:
        """A request of ``kind`` succeeded: end its pause and reset the wait. With ``started_at`` (the clock when the request began) a
        pause recorded since then stays, since the request was sent before the check that set it."""
        self._check(kind)
        if kind not in self._rows():
            return
        with self._write() as rows:
            row = rows.get(kind)
            if row is not None and not (started_at is not None and row.get("at", 0) >= started_at):
                del rows[kind]

    def state(self) -> Dict[str, dict]:
        """Every kind, shaped as media-archivist's ``GET /api/v1/youtube/backoff`` shows it."""
        now, rows = self.clock(), self._rows()
        out = {}
        for kind in KINDS:
            row = rows.get(kind)
            if row and row.get("retry_at", 0) > now:
                out[kind] = {"paused": True, "until": _iso(row["retry_at"]), "wait": int(row["wait_s"]), "since": _iso(row["at"])}
            else:
                out[kind] = {"paused": False}
        return out


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "").strip().lower() not in ("off", "0", "false", "no")


def shared() -> Backoff:
    """The back-off every tutubo caller on this machine reads and writes."""
    return Backoff()


def check(kind: str) -> None:
    """Called before a request of ``kind``: raises BackedOff while the shared pause runs."""
    if enabled():
        shared().guard(kind)


def after(kind: str, response, started_at: Optional[float] = None) -> None:
    """Called with the response of a request of ``kind``: a bot check starts or extends the pause, a success ends it, and an error status
    is raised as ``response.raise_for_status()`` raises it."""
    status = getattr(response, "status_code", 200)
    status = status if isinstance(status, int) else 200
    if enabled():
        if status == 429 or (status >= 400 and is_bot_check(getattr(response, "text", ""))):
            shared().mark_blocked(kind)
        elif status < 400:
            shared().mark_clear(kind, started_at)
    response.raise_for_status()


def after_success(kind: str, started_at: Optional[float] = None) -> None:
    """Called when a request of ``kind`` was answered: its pause, if any, ends (see Backoff.mark_clear for ``started_at``)."""
    if enabled():
        shared().mark_clear(kind, started_at)


def failed(kind: str, error: object) -> bool:
    """Called when a request of ``kind`` raised ``error``: the pause starts when the error is a bot check. True when it did."""
    if enabled() and is_bot_check(error):
        shared().mark_blocked(kind)
        return True
    return False


def paused(kind: str) -> BackedOff:
    """The BackedOff to raise after ``failed`` returned True."""
    return BackedOff(kind, shared().blocked_until(kind) or time.time())


def guarded(kind: str, fn: Callable, *args, **kwargs):
    """``fn(*args, **kwargs)`` as one request of ``kind``: refused while the pause runs, a pause started when it raises a bot check, the
    pause ended when it returns."""
    check(kind)
    started = time.time()
    try:
        result = fn(*args, **kwargs)
    except BackedOff:
        raise
    except Exception as e:
        if failed(kind, e):
            raise paused(kind) from e
        raise
    after_success(kind, started)
    return result
