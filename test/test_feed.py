"""The channel upload feed: one request, parsed, bounded, and under the shared back-off."""
import json

import pytest
import requests

from tutubo import backoff, feed
from tutubo.feed import FeedError

CHANNEL = "UC" + "a" * 22


def atom(*ids, extra=""):
    entries = "".join(
        f"""<entry><id>yt:video:{v}</id><yt:videoId>{v}</yt:videoId><yt:channelId>{CHANNEL[2:]}</yt:channelId>
<title>Title {v}</title><author><name>Chan</name></author><published>2026-01-01T00:00:00+00:00</published>
<updated>2026-01-02T00:00:00+00:00</updated><media:group><media:title>t</media:title>
<media:thumbnail url="https://i.ytimg.com/vi/{v}/hqdefault.jpg"/><media:description>desc {v}</media:description>
<media:community><media:statistics views="42"/></media:community></media:group></entry>""" for v in ids)
    return (f'<?xml version="1.0"?>{extra}<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
            f'xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">{entries}</feed>').encode()


class Reply:
    def __init__(self, status=200, body=b"", text=""):
        self.status_code, self.body, self.text = status, body, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def close(self):
        pass


class Session:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTUBO_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("TUTUBO_BACKOFF", raising=False)


def test_parses_entries_in_one_request():
    s = Session(Reply(body=atom("aaaaaaaaaaa", "bbbbbbbbbbb")))
    entries = feed.channel_feed(CHANNEL, session=s)
    assert len(s.calls) == 1 and s.calls[0][1]["params"] == {"channel_id": CHANNEL}
    first = entries[0]
    assert (first.video_id, first.title, first.channel, first.views) == ("aaaaaaaaaaa", "Title aaaaaaaaaaa", "Chan", 42)
    assert first.url.endswith("watch?v=aaaaaaaaaaa") and first.thumbnail.endswith("hqdefault.jpg")
    assert (first.description, first.published, first.updated, first.channel_id) == (
        "desc aaaaaaaaaaa", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00", CHANNEL[2:])


def test_refresh_splits_new_from_known():
    s = Session(Reply(body=atom("aaaaaaaaaaa", "bbbbbbbbbbb")))
    up = feed.refresh_channel(CHANNEL, ["bbbbbbbbbbb"], session=s)
    assert [e.video_id for e in up.new] == ["aaaaaaaaaaa"] and up.needs_listing
    s = Session(Reply(body=atom("aaaaaaaaaaa")))
    assert not feed.refresh_channel(CHANNEL, ["aaaaaaaaaaa"], session=s).needs_listing


@pytest.mark.parametrize("bad", ["", "UCshort", CHANNEL + "x", "../etc", "UC" + "a" * 21 + "&"])
def test_bad_channel_id_sends_nothing(bad):
    s = Session()
    with pytest.raises(FeedError):
        feed.channel_feed(bad, session=s)
    assert not s.calls


def test_dtd_and_entities_refused():
    body = atom("aaaaaaaaaaa", extra='<!DOCTYPE feed [<!ENTITY a "aaaa">]>')
    with pytest.raises(FeedError, match="DTD"):
        feed.parse_feed(body)
    with pytest.raises(FeedError, match="DTD"):
        feed.parse_feed(atom("aaaaaaaaaaa", extra="<!DOCTYPE feed>"))


def test_entity_declaration_refused_by_its_own_hook(monkeypatch):
    """The entity hook refuses even when the doctype hook does not fire."""
    body = atom("aaaaaaaaaaa", extra='<!DOCTYPE feed [<!ENTITY a "aaaa">]>')
    real = feed.expat.ParserCreate

    def create():
        p = real()
        return _Quiet(p)
    monkeypatch.setattr(feed.expat, "ParserCreate", create)
    with pytest.raises(FeedError, match="DTD"):
        feed.parse_feed(body)


class _Quiet:
    """An expat parser whose doctype hook is switched off after the feed code sets it."""

    def __init__(self, parser):
        self.__dict__["p"] = parser

    def __setattr__(self, name, value):
        if name != "StartDoctypeDeclHandler":
            setattr(self.p, name, value)

    def Parse(self, *a):
        return self.p.Parse(*a)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-8-sig"])
def test_dtd_refused_in_every_encoding(encoding):
    text = ('<?xml version="1.0" encoding="%s"?><!DOCTYPE feed [<!ENTITY a "aaaa">]>'
            '<feed xmlns="http://www.w3.org/2005/Atom">&a;</feed>' % ("utf-16" if encoding.startswith("utf-16") else encoding))
    if encoding.startswith("utf-8"):
        text = text.replace('encoding="utf-8-sig"', 'encoding="utf-8"')
    with pytest.raises(FeedError):
        feed.parse_feed(text.encode(encoding))


def test_root_must_be_an_atom_feed():
    with pytest.raises(FeedError, match="Atom"):
        feed.parse_feed(b"<html><entry/></html>")
    with pytest.raises(FeedError, match="Atom"):
        feed.parse_feed(b'<feed xmlns="urn:other"/>')


@pytest.mark.parametrize("views", ["\u00b2", "\u0663", "-1", "1" * 40, ""])
def test_odd_view_counts_do_not_crash(views):
    body = atom("aaaaaaaaaaa").replace(b'views="42"', ('views="%s"' % views).encode())
    (e,) = feed.parse_feed(body)
    assert e.views is None


def test_failed_answer_is_read_only_in_part():
    read = []

    class Huge(Reply):
        def iter_content(self, size):
            for _ in range(1000):
                read.append(size)
                yield b"x" * size

    with pytest.raises(FeedError):
        feed.channel_feed(CHANNEL, session=Session(Huge(500)))
    assert len(read) == 1 and read[0] <= 65536


def test_response_is_closed_after_success_and_after_failure():
    closed = []

    class R(Reply):
        def close(self):
            closed.append(1)

    feed.channel_feed(CHANNEL, session=Session(R(body=atom("aaaaaaaaaaa"))))
    with pytest.raises(FeedError):
        feed.channel_feed(CHANNEL, session=Session(R(500)))
    assert len(closed) == 2


def test_default_session_is_plain_and_pinned_to_the_family(monkeypatch):
    seen = []
    s = Session(Reply(body=atom("aaaaaaaaaaa")))
    monkeypatch.setattr(feed, "plain_session", lambda family=None: seen.append(family) or s)
    feed.channel_feed(CHANNEL, family="ipv6")
    assert seen == ["ipv6"] and s.calls


def run_cli(monkeypatch, *replies):
    s = Session(*replies)
    seen = []
    monkeypatch.setattr(feed, "plain_session", lambda family=None: seen.append(family) or s)
    return s, seen


def test_cli_prints_only_new_entries(monkeypatch, capsys):
    run_cli(monkeypatch, Reply(body=atom("aaaaaaaaaaa", "bbbbbbbbbbb")))
    assert feed.main([CHANNEL, "--known", "bbbbbbbbbbb"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [(x["event"], x["video_id"]) for x in lines] == [("entry", "aaaaaaaaaaa")]


def test_cli_known_id_starting_with_a_dash(monkeypatch, capsys):
    run_cli(monkeypatch, Reply(body=atom("-aaaaaaaaaa", "bbbbbbbbbbb")))
    assert feed.main([CHANNEL, "--known=-aaaaaaaaaa"]) == 0
    assert [json.loads(x)["video_id"] for x in capsys.readouterr().out.splitlines()] == ["bbbbbbbbbbb"]


def test_cli_defaults_to_ipv4_and_passes_the_family(monkeypatch, capsys):
    _, seen = run_cli(monkeypatch, Reply(body=atom("aaaaaaaaaaa")), Reply(body=atom("aaaaaaaaaaa")))
    feed.main([CHANNEL])
    feed.main([CHANNEL, "--family", "any"])
    assert seen == ["ipv4", "any"]


def test_cli_exits_1_on_an_error_and_goes_on(monkeypatch, capsys):
    run_cli(monkeypatch, Reply(404), Reply(body=atom("aaaaaaaaaaa")))
    assert feed.main([CHANNEL, CHANNEL]) == 1
    events = [json.loads(x)["event"] for x in capsys.readouterr().out.splitlines()]
    assert events == ["error", "entry"]


def test_oversize_refused_while_streaming():
    with pytest.raises(FeedError, match="larger"):
        feed.channel_feed(CHANNEL, session=Session(Reply(body=b"x" * (feed.MAX_BYTES + 1))))


def test_malformed_xml_and_bad_video_id():
    with pytest.raises(FeedError):
        feed.parse_feed(b"<feed")
    assert feed.parse_feed(atom("short")) == []


def test_http_error_is_feed_error_and_does_not_pause():
    with pytest.raises(FeedError):
        feed.channel_feed(CHANNEL, session=Session(Reply(404)))
    assert not backoff.shared().state()["feed"]["paused"]


def test_429_pauses_feed_for_every_caller():
    with pytest.raises(backoff.BackedOff):
        feed.channel_feed(CHANNEL, session=Session(Reply(429)))
    s = Session()
    with pytest.raises(backoff.BackedOff):
        feed.channel_feed(CHANNEL, session=s)
    assert not s.calls and not backoff.shared().state()["details"]["paused"]


def test_bot_check_page_pauses():
    r = Reply(403, body=b"Please confirm you are not a bot")
    with pytest.raises(backoff.BackedOff):
        feed.channel_feed(CHANNEL, session=Session(r))


def test_connection_error_hides_url():
    with pytest.raises(FeedError) as e:
        feed.channel_feed(CHANNEL, session=Session(requests.ConnectionError("https://x/?sig=SECRET")))
    assert "SECRET" not in str(e.value)


def test_cli_exit_75_when_paused(capsys):
    backoff.shared().record("feed")
    assert feed.main([CHANNEL]) == 75
    assert json.loads(capsys.readouterr().out)["event"] == "paused"


def test_oversize_stops_reading_early():
    chunks = []

    class Big(Reply):
        def iter_content(self, size):
            for _ in range(1000):
                chunks.append(1)
                yield b"x" * 65536

    with pytest.raises(FeedError):
        feed.channel_feed(CHANNEL, session=Session(Big()))
    assert len(chunks) < 50


def test_parse_feed_itself_bounded():
    with pytest.raises(FeedError, match="larger"):
        feed.parse_feed(b"x" * (feed.MAX_BYTES + 1))


def test_bot_check_error_from_transport_pauses():
    with pytest.raises(backoff.BackedOff):
        feed.channel_feed(CHANNEL, session=Session(requests.ConnectionError("429 Too Many Requests")))
    assert backoff.shared().state()["feed"]["paused"]


@pytest.mark.parametrize("fail", [requests.exceptions.ChunkedEncodingError("broken"), requests.ConnectionError("read timed out"),
                                  OSError("reset")])
def test_a_body_that_breaks_midway_is_a_feed_error(fail):
    class Broken(Reply):
        def iter_content(self, size):
            yield b"<feed"
            raise fail

    with pytest.raises(FeedError, match="read failed"):
        feed.channel_feed(CHANNEL, session=Session(Broken()))


def test_cli_goes_on_to_the_next_channel_after_a_broken_body(monkeypatch, capsys):
    class Broken(Reply):
        def iter_content(self, size):
            raise requests.exceptions.ChunkedEncodingError("broken")

    s, _ = run_cli(monkeypatch, Broken(), Reply(body=atom("aaaaaaaaaaa")))
    assert feed.main([CHANNEL, CHANNEL]) == 1
    events = [json.loads(x)["event"] for x in capsys.readouterr().out.splitlines()]
    assert events == ["error", "entry"] and len(s.calls) == 2


def test_library_functions_default_to_ipv4(monkeypatch):
    seen = []
    s = Session(Reply(body=atom("aaaaaaaaaaa")), Reply(body=atom("aaaaaaaaaaa")))
    monkeypatch.setattr(feed, "plain_session", lambda family=None: seen.append(family) or s)
    feed.channel_feed(CHANNEL)
    feed.refresh_channel(CHANNEL, [])
    assert seen == ["ipv4", "ipv4"]
