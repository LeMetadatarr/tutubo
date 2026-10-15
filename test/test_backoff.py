"""The shared bot-check pause: rules, the file it lives in, and many writers at once."""
import json
import multiprocessing
import os
import threading
import time

import pytest

from tutubo import backoff
from tutubo.backoff import Backoff, BackedOff


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def pause(tmp_path, clock):
    return Backoff(tmp_path / "b" / "backoff.json", clock=clock)


def test_first_check_pauses_thirty_minutes_and_a_later_one_doubles_it(pause, clock):
    assert pause.mark_blocked("download") == 1800
    assert pause.blocked_until("download") == clock.now + 1800
    clock.now += 1801
    assert pause.blocked_until("download") is None
    assert pause.mark_blocked("download") == 3600
    clock.now += 3601
    assert pause.mark_blocked("download") == 7200


def test_the_wait_stops_doubling_at_a_day(pause, clock):
    for _ in range(12):
        pause.mark_blocked("search")
        clock.now += 24 * 3600 + 1
    assert pause.state()["search"] == {"paused": False}
    assert pause.mark_blocked("search") == 24 * 3600


def test_a_check_during_a_pause_leaves_it_as_it_is(pause, clock):
    pause.mark_blocked("download")
    clock.now += 600
    assert pause.mark_blocked("download") == 1200
    assert pause.blocked_until("download") == 1_000_000.0 + 1800


def test_kinds_pause_apart(pause):
    pause.mark_blocked("download")
    assert pause.remaining("search") == 0
    pause.guard("search")
    with pytest.raises(BackedOff) as e:
        pause.guard("download")
    assert "YouTube is asking for a check: download requests paused until" in str(e.value)
    assert str(e.value).endswith("UTC")


def test_success_ends_the_pause_and_resets_the_wait(pause, clock):
    pause.mark_blocked("download")
    pause.mark_clear("download")
    assert pause.blocked_until("download") is None
    assert pause.mark_blocked("download") == 1800


def test_a_success_of_a_request_sent_before_the_check_does_not_end_it(pause, clock):
    started = clock.now
    clock.now += 5
    pause.mark_blocked("download")
    pause.mark_clear("download", started_at=started)
    assert pause.blocked_until("download") is not None


def test_unknown_kind_is_refused(pause):
    with pytest.raises(ValueError):
        pause.mark_blocked("everything")


def test_state_has_the_shape_of_media_archivists_route(pause):
    pause.mark_blocked("listing")
    state = pause.state()
    assert set(state) == set(backoff.KINDS)
    assert state["listing"]["paused"] is True and state["listing"]["wait"] == 1800
    assert state["listing"]["until"].endswith("+00:00") and state["details"] == {"paused": False}


def test_rows_use_media_archivists_field_names(pause):
    pause.mark_blocked("feed")
    row = json.loads(pause.path.read_text())["kinds"]["feed"]
    assert set(row) == {"retry_at", "wait_s", "at"}


def test_a_damaged_file_reads_as_no_pause_and_is_rewritten(pause):
    pause.path.parent.mkdir(parents=True)
    pause.path.write_text("{not json")
    assert pause.blocked_until("download") is None
    pause.mark_blocked("download")
    assert pause.blocked_until("download") is not None


def test_state_folder_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("TUTUBO_STATE_DIR")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert backoff.state_dir() == tmp_path / "xdg" / "tutubo"
    monkeypatch.setenv("TUTUBO_STATE_DIR", str(tmp_path / "own"))
    assert backoff.state_dir() == tmp_path / "own"


def test_the_file_is_replaced_atomically(pause, monkeypatch):
    pause.mark_blocked("download")
    before = pause.path.read_text()
    seen = []
    real = os.replace

    def replace(src, dst):
        seen.append((pause.path.read_text(), json.loads(open(src).read())))
        real(src, dst)
    monkeypatch.setattr(os, "replace", replace)
    pause.mark_blocked("search")
    assert len(seen) == 1
    old, new = seen[0]
    assert old == before and set(new["kinds"]) == {"download", "search"}
    assert [p.name for p in pause.path.parent.iterdir() if p.name.startswith("backoff.json.")] == []


def _check_in_process(path, kind, slow, go):
    class Slow(Backoff):
        def _rows(self):
            rows = super()._rows()
            if slow:
                time.sleep(0.05)
            return rows
    go.wait()
    Slow(path).mark_blocked(kind)


def test_processes_recording_at_once_lose_no_pause(tmp_path):
    path = tmp_path / "state" / "backoff.json"
    go = multiprocessing.Barrier(len(backoff.KINDS))
    procs = [multiprocessing.Process(target=_check_in_process, args=(path, kind, True, go)) for kind in backoff.KINDS]
    [p.start() for p in procs]
    [p.join(30) for p in procs]
    assert [p.exitcode for p in procs] == [0] * len(procs)
    assert {k for k, v in Backoff(path).state().items() if v["paused"]} == set(backoff.KINDS)


def test_threads_recording_the_same_check_pause_once(tmp_path):
    pause = Backoff(tmp_path / "backoff.json")
    gate = threading.Barrier(16)
    waits = []

    def work():
        gate.wait()
        waits.append(pause.mark_blocked("download"))
    threads = [threading.Thread(target=work) for _ in range(16)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert len(waits) == 16 and max(waits) <= 1800 and min(waits) > 1700
    assert json.loads(pause.path.read_text())["kinds"]["download"]["wait_s"] == 1800


def test_readers_never_see_a_torn_file(tmp_path):
    pause = Backoff(tmp_path / "backoff.json")
    stop, bad = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                json.loads(pause.path.read_text())
            except FileNotFoundError:
                pass
            except ValueError:
                bad.append(1)
    t = threading.Thread(target=reader)
    t.start()
    for i in range(300):
        pause.mark_blocked(backoff.KINDS[i % 6])
        pause.mark_clear(backoff.KINDS[(i + 3) % 6])
    stop.set()
    t.join()
    assert bad == []


def test_it_can_be_turned_off(monkeypatch):
    backoff.shared().mark_blocked("search")
    with pytest.raises(BackedOff):
        backoff.check("search")
    monkeypatch.setenv("TUTUBO_BACKOFF", "off")
    backoff.check("search")
    assert backoff.failed("search", "HTTP 429") is False


@pytest.mark.parametrize("text,expected", [
    ("ERROR: Sign in to confirm you’re not a bot", True), ("HTTP Error 429: Too Many Requests", True), ("HTTP 429", True),
    ("ERROR: Video unavailable", False), ("HTTP 404", False), ("", False), (None, False)])
def test_what_counts_as_a_bot_check(text, expected):
    assert backoff.is_bot_check(text) is expected


def test_guarded_marks_a_bot_check_clears_on_success_and_refuses_while_paused():
    def refuse():
        raise RuntimeError("YouTube API returned HTTP 429 for search")
    with pytest.raises(BackedOff):
        backoff.guarded("search", refuse)
    calls = []
    with pytest.raises(BackedOff):
        backoff.guarded("search", calls.append, 1)
    assert calls == []
    backoff.shared().mark_clear("search")
    assert backoff.guarded("search", lambda: 7) == 7


def test_guarded_lets_other_errors_through_without_a_pause():
    with pytest.raises(KeyError):
        backoff.guarded("search", {}.__getitem__, "x")
    assert backoff.shared().blocked_until("search") is None
