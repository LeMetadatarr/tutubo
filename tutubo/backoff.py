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
sign in to confirm you are not a bot, or the watch page's own "This content isn't available, try again later" rate-limit text).
``TUTUBO_BACKOFF=off`` turns the file off: nothing reads it and nothing writes it, so a program that stops on a bot check only because of
the pause carries on asking. tutubo never tries to get past a check: it stops asking.

The default folder belongs to one user, so a pause is shared by that user's programs and not by other accounts. Both files are created with
the process's umask (group readable when the umask allows it) and are never made more open than that. A file that cannot be read
(permissions, a directory in its place) fails closed: requests are refused with ``BackedOff`` naming the file, because a pause may be
hidden in it. A file that reads but holds nothing usable (not JSON, or rows with the wrong types) counts as no pause and is replaced the
next time a check is recorded. A check that cannot be recorded (an unwritable folder) still raises ``BackedOff``, and this process
keeps the pause in memory."""
from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

try:
    import fcntl
except ImportError:  # no advisory locks (Windows): writers in different processes can overwrite each other's pause
    fcntl = None

KINDS = ("details", "listing", "feed", "thumb", "search", "download")
INITIAL_WAIT_S = 30 * 60.0
MAX_WAIT_S = 24 * 3600.0
ENV_DIR = "TUTUBO_STATE_DIR"
ENV_SWITCH = "TUTUBO_BACKOFF"
BOT_CHECK = re.compile(r"not a bot|HTTP Error 429|HTTP 429|Too Many Requests|rate-limited by YouTube"
                       r"|This content isn['\u2019]t available, try again later", re.I)
_MAX_EPOCH = 253402300799.0  # 9999-12-31: the last second datetime formats
PAUSED_EXIT = 75  # EX_TEMPFAIL: try again after the pause

_threads = threading.RLock()


class BackedOff(RuntimeError):
    """A request was not sent because YouTube asked for a check and the pause has not run out."""

    def __init__(self, kind: str, until: float, reason: str = ""):
        self.kind, self.until, self.reason = kind, until, reason
        when = datetime.fromtimestamp(until, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if reason:
            super().__init__(f"{kind} requests paused until {when}: {reason}")
        else:
            super().__init__(f"YouTube is asking for a check: {kind} requests paused until {when}")


class StateUnreadable(OSError):
    """The back-off file exists and cannot be read."""


def state_dir() -> Path:
    given = os.environ.get(ENV_DIR)
    if given:
        return Path(given).expanduser()
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".local" / "state") / "tutubo"


def is_bot_check(text: object) -> bool:
    """True when ``text`` (an error message, a program's stderr) says YouTube refused the request as a bot check or a rate limit."""
    return bool(BOT_CHECK.search(str(text or "")))


def _number(value: object, low: float = -_MAX_EPOCH, high: float = _MAX_EPOCH) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


class Backoff:
    _unsaved: Dict[Tuple[str, str], float] = {}  # pauses this process could not write, by (file, kind)

    def __init__(self, path=None, *, initial: float = INITIAL_WAIT_S, maximum: float = MAX_WAIT_S,
                 clock: Callable[[], float] = time.time):
        self._path = Path(path) if path else None
        self.initial, self.maximum, self.clock = initial, maximum, clock

    @property
    def path(self) -> Path:
        return self._path or state_dir() / "backoff.json"

    def _row(self, value: object) -> Optional[dict]:
        """A stored row with every field a number in range, or None for a row that is not usable."""
        if not isinstance(value, dict):
            return None
        retry_at, wait, at = value.get("retry_at"), value.get("wait_s"), value.get("at")
        if not (_number(retry_at, 0) and _number(wait, 0, self.maximum) and wait > 0):
            return None
        return {"retry_at": float(retry_at), "wait_s": float(wait), "at": float(at) if _number(at, 0) else float(retry_at) - wait}

    def _rows(self) -> Dict[str, dict]:
        """The usable rows. No file, a file that is not JSON and rows with the wrong types are no pause; a file that cannot be
        read raises StateUnreadable."""
        try:
            text = self.path.read_text()
        except (FileNotFoundError, NotADirectoryError):
            return {}
        except OSError as e:
            raise StateUnreadable(f"cannot read the back-off file {self.path}: {e.strerror or e}") from e
        except ValueError:
            return {}
        try:
            rows = json.loads(text).get("kinds")
        except (ValueError, AttributeError):
            return {}
        if not isinstance(rows, dict):
            return {}
        usable = {k: self._row(v) for k, v in rows.items() if k in KINDS}
        return {k: v for k, v in usable.items() if v}

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
                os.chmod(tmp, stat.S_IMODE(os.fstat(lock.fileno()).st_mode))  # as open as the lock file, which the umask decided
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
        now, row = self.clock(), self._rows().get(kind)
        until = min(row["retry_at"], now + row["wait_s"]) if row else 0.0  # a clock stepped back must not stretch the wait
        until = max(until, self._unsaved.get((str(self.path), kind), 0.0))
        return until if until > now else None

    def remaining(self, kind: str) -> float:
        until = self.blocked_until(kind)
        return max(0.0, until - self.clock()) if until else 0.0

    def guard(self, kind: str) -> None:
        """Raise BackedOff when ``kind`` is paused."""
        try:
            until = self.blocked_until(kind)
        except StateUnreadable as e:
            raise BackedOff(kind, self.clock() + self.initial, str(e)) from e
        if until:
            raise BackedOff(kind, until)

    def mark_blocked(self, kind: str) -> float:
        """Record a bot check for ``kind``; the seconds the pause lasts."""
        self._check(kind)
        with self._write() as rows:
            now = self.clock()
            row = rows.get(kind)
            if row and now < row["retry_at"]:
                return min(row["retry_at"] - now, row["wait_s"])
            wait = min(row["wait_s"] * 2, self.maximum) if row else self.initial
            rows[kind] = {"retry_at": now + wait, "wait_s": wait, "at": now}
            return wait

    def record(self, kind: str) -> None:
        """Record a bot check for ``kind``. When the file cannot be written the pause is kept in memory for this process and
        BackedOff is raised, saying why."""
        try:
            self.mark_blocked(kind)
        except OSError as e:
            until = self.clock() + self.initial
            self._unsaved[(str(self.path), kind)] = until
            raise BackedOff(kind, until, f"the check could not be recorded ({e})") from e

    def mark_clear(self, kind: str, started_at: Optional[float] = None) -> None:
        """A request of ``kind`` succeeded: end its pause and reset the wait. With ``started_at`` (the clock when the request began) a
        pause recorded since then stays, since the request was sent before the check that set it."""
        self._check(kind)
        self._unsaved.pop((str(self.path), kind), None)
        if kind not in self._rows():
            return
        with self._write() as rows:
            row = rows.get(kind)
            if row is not None and not (started_at is not None and row.get("at", 0) >= started_at):
                del rows[kind]

    def state(self) -> Dict[str, dict]:
        """Every kind, shaped as media-archivist's ``GET /api/v1/youtube/backoff`` shows it."""
        rows = self._rows()
        out = {}
        for kind in KINDS:
            until = self.blocked_until(kind)
            if until:
                row = rows.get(kind) or {"wait_s": self.initial, "at": until - self.initial}
                out[kind] = {"paused": True, "until": _iso(until), "wait": int(row["wait_s"]), "since": _iso(row["at"])}
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
            shared().record(kind)
        elif status < 400:
            _clear(kind, started_at)
    response.raise_for_status()


def after_success(kind: str, started_at: Optional[float] = None) -> None:
    """Called when a request of ``kind`` was answered: its pause, if any, ends (see Backoff.mark_clear for ``started_at``)."""
    if enabled():
        _clear(kind, started_at)


def _clear(kind: str, started_at: Optional[float]) -> None:
    """End the pause of ``kind``. A pause that cannot be ended because the file cannot be written or read stays, which is the safe side."""
    with contextlib.suppress(OSError):
        shared().mark_clear(kind, started_at)


def failed(kind: str, error: object) -> bool:
    """Called when a request of ``kind`` raised ``error``: the pause starts when the error is a bot check. True when it did. When the
    pause cannot be written to the state folder, raises BackedOff instead, so the caller stops all the same."""
    if enabled() and is_bot_check(error):
        shared().record(kind)
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


def main() -> int:
    """``python -m tutubo.backoff``: print every kind's state as JSON; exit 75 while any kind is paused or the file cannot be read."""
    try:
        state = shared().state()
    except StateUnreadable as e:
        print(e, file=sys.stderr)
        return PAUSED_EXIT
    print(json.dumps(state, indent=2))
    return PAUSED_EXIT if any(row["paused"] for row in state.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
