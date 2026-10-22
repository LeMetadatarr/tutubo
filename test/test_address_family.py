"""Per-session IP address family: connections really use only the chosen family."""
from __future__ import annotations

import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests
import urllib3.util.connection as urllib3_connection


def _has_ipv6_loopback() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


needs_ipv6 = pytest.mark.skipif(not _has_ipv6_loopback(), reason="no IPv6 loopback")


class _Handler(BaseHTTPRequestHandler):
    def _reply(self):
        family = "ipv6" if self.server.address_family == socket.AF_INET6 else "ipv4"
        body = json.dumps({"family": family}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._reply()

    def log_message(self, *args):
        pass


class _V4(HTTPServer):
    address_family = socket.AF_INET


class _V6(HTTPServer):
    address_family = socket.AF_INET6


def _serve(cls, host, port):
    server = cls((host, port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def dual_servers():
    """One server on 127.0.0.1 and one on ::1, same port; each reports its family."""
    for _ in range(20):
        v4 = _serve(_V4, "127.0.0.1", 0)
        port = v4.server_address[1]
        try:
            v6 = _serve(_V6, "::1", port)
        except OSError:
            v4.shutdown()
            v4.server_close()
            continue
        break
    else:
        pytest.skip("could not bind the same port on 127.0.0.1 and ::1")
    yield port
    for srv in (v4, v6):
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def localhost_resolves_both(monkeypatch):
    """Make 'tutubo.test' resolve to both loopbacks, IPv6 first."""
    real = socket.getaddrinfo
    # the patch only reaches requests-based sessions, not libcurl's resolver
    monkeypatch.setitem(sys.modules, "unblock_requests", None)
    monkeypatch.delenv("TUTUBO_TRANSPORT", raising=False)

    def fake(host, port, *args, **kwargs):
        if host == "tutubo.test":
            return [
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port, 0, 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
            ]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture(autouse=True)
def _reset_default_family():
    from tutubo import transport
    yield
    if hasattr(transport, "set_default_family"):
        transport.set_default_family(None)


@needs_ipv6
@pytest.mark.parametrize("family", ["ipv4", "ipv6"])
def test_session_connects_over_requested_family(dual_servers, localhost_resolves_both, family):
    from tutubo.transport import make_session
    s = make_session(family=family)
    r = s.get(f"http://tutubo.test:{dual_servers}/", timeout=5)
    assert r.json() == {"family": family}


@needs_ipv6
def test_unset_family_takes_first_resolved_address(dual_servers, localhost_resolves_both, monkeypatch):
    from tutubo.transport import make_session
    monkeypatch.setitem(sys.modules, "unblock_requests", None)  # plain requests session
    r = make_session().get(f"http://tutubo.test:{dual_servers}/", timeout=5)
    assert r.json() == {"family": "ipv6"}


@needs_ipv6
def test_pinned_family_does_not_fall_back_to_the_other(localhost_resolves_both):
    """A v6-only server is unreachable through an ipv4 session."""
    from tutubo.transport import make_session
    v6 = _serve(_V6, "::1", 0)
    try:
        port = v6.server_address[1]
        with pytest.raises(requests.ConnectionError):
            make_session("ipv4").get(f"http://tutubo.test:{port}/", timeout=5)
        assert make_session("ipv6").get(
            f"http://tutubo.test:{port}/", timeout=5).json() == {"family": "ipv6"}
    finally:
        v6.shutdown()
        v6.server_close()


@needs_ipv6
def test_concurrent_sessions_keep_their_own_family(dual_servers, localhost_resolves_both):
    from tutubo.transport import make_session
    results = {"ipv4": set(), "ipv6": set()}
    sessions = {f: make_session(f) for f in results}
    errors = []

    def worker(fam):
        try:
            for _ in range(15):
                r = sessions[fam].get(f"http://tutubo.test:{dual_servers}/", timeout=5)
                results[fam].add(r.json()["family"])
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(f,)) for f in ("ipv4", "ipv6") * 3]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert results == {"ipv4": {"ipv4"}, "ipv6": {"ipv6"}}


def test_no_global_state_touched():
    from tutubo.transport import make_session
    before = urllib3_connection.allowed_gai_family
    getaddrinfo = socket.getaddrinfo
    make_session("ipv4")
    make_session("ipv6")
    assert urllib3_connection.allowed_gai_family is before
    assert socket.getaddrinfo is getaddrinfo


def test_unset_session_has_no_family_adapter(monkeypatch):
    from tutubo.transport import FamilyAdapter, make_session, default_session
    monkeypatch.delenv("TUTUBO_TRANSPORT", raising=False)
    for s in (make_session(), make_session(None), default_session()):
        assert _family_of(s) is None
        assert not any(isinstance(a, FamilyAdapter) for a in s.adapters.values())


def test_invalid_family_rejected():
    from tutubo.transport import make_session
    with pytest.raises(ValueError):
        make_session("ipx")


def test_family_accepts_socket_constants_and_case():
    from tutubo.transport import normalize_family
    assert normalize_family(socket.AF_INET) == "ipv4"
    assert normalize_family(socket.AF_INET6) == "ipv6"
    assert normalize_family("IPv6") == "ipv6"
    assert normalize_family("any") is None


def test_default_family_applies_and_any_opts_out(monkeypatch):
    from tutubo.transport import get_default_family, make_session, set_default_family
    monkeypatch.delenv("TUTUBO_TRANSPORT", raising=False)
    set_default_family("ipv6")
    assert get_default_family() == "ipv6"
    assert _family_of(make_session()) == ("::", 0)
    assert _family_of(make_session("any")) is None
    set_default_family(None)
    assert _family_of(make_session()) is None


def test_adapter_survives_pickle():
    import pickle
    from tutubo.transport import make_session
    s = pickle.loads(pickle.dumps(make_session("ipv4")))
    assert s.get_adapter("https://x.test")._source_address == ("0.0.0.0", 0)


@needs_ipv6
@pytest.mark.parametrize("env", ["", "curl_cffi"])
def test_curl_cffi_session_stays_on_pinned_family(dual_servers, monkeypatch, env):
    """curl-based sessions (env transport and CloudflareSession) honour the family.

    libcurl does its own name resolution, so this resolves the real 'localhost'.
    """
    from tutubo.transport import make_session
    monkeypatch.setenv("TUTUBO_TRANSPORT", env)
    url = f"http://localhost:{dual_servers}/"
    assert make_session("ipv4").get(url, timeout=5).json() == {"family": "ipv4"}
    assert make_session("ipv6").get(url, timeout=5).json() == {"family": "ipv6"}


@needs_ipv6
@pytest.mark.parametrize("env", ["", "curl_cffi"])
def test_curl_cffi_pinned_session_does_not_fall_back(monkeypatch, env):
    from tutubo.transport import make_session
    monkeypatch.setenv("TUTUBO_TRANSPORT", env)
    v6 = _serve(_V6, "::1", 0)
    try:
        url = f"http://localhost:{v6.server_address[1]}/"
        with pytest.raises(OSError):
            make_session("ipv4").get(url, timeout=5)
        assert make_session("ipv6").get(url, timeout=5).json() == {"family": "ipv6"}
    finally:
        v6.shutdown()
        v6.server_close()


def test_pinned_curl_session_is_curl_based_when_requested(monkeypatch):
    from curl_cffi import requests as cffi
    from tutubo.transport import make_session
    monkeypatch.setenv("TUTUBO_TRANSPORT", "curl_cffi")
    assert isinstance(make_session("ipv4"), cffi.Session)


# ---------------------------------------------------------------------------
# Objects pass the family through
# ---------------------------------------------------------------------------

def _family_of(session):
    """Source address of a pinned session (requests adapter or unblock_requests ip_family)."""
    from tutubo.transport import FamilyAdapter, _SOURCE_ADDRESSES
    if getattr(session, "ip_family", None):
        return _SOURCE_ADDRESSES[session.ip_family]
    a = session.get_adapter("https://www.youtube.com")
    return a._source_address if isinstance(a, FamilyAdapter) else None


def test_channel_family_builds_pinned_session():
    from tutubo import Channel
    ch = Channel("https://www.youtube.com/@LinusTechTips", family="ipv6")
    assert _family_of(ch._session) == ("::", 0)
    assert _family_of(Channel("https://www.youtube.com/@LinusTechTips")._session) is None


def test_channel_explicit_session_wins_over_family():
    from tutubo import Channel
    fake = object()
    assert Channel("https://www.youtube.com/@x", session=fake, family="ipv4")._session is fake


def test_playlist_family_builds_pinned_session():
    from tutubo import Playlist
    pl = Playlist("https://www.youtube.com/playlist?list=PL123", family="ipv4")
    assert _family_of(pl._session) == ("0.0.0.0", 0)


def test_channel_playlists_inherit_session(monkeypatch):
    from tutubo import Channel
    ch = Channel("https://www.youtube.com/@x", family="ipv4")
    monkeypatch.setattr(ch, "_get_data", lambda url: {})
    monkeypatch.setattr(ch, "_extract_playlist_ids", lambda data: (["PL1"], None))
    (pl,) = list(ch._playlist_generator())
    assert pl._session is ch._session


def test_channel_fetch_uses_pinned_session_for_http(dual_servers, localhost_resolves_both, monkeypatch):
    """Channel page fetch goes through the pinned session end to end."""
    from tutubo import Channel
    ch = Channel("https://www.youtube.com/@x", family="ipv4")
    seen = {}
    real_get = ch._session.get

    def get(url, **kw):
        seen["url"] = url
        return real_get(f"http://tutubo.test:{dual_servers}/", **kw)

    monkeypatch.setattr(ch._session, "get", get)
    monkeypatch.setattr(requests.Response, "raise_for_status", lambda self: None)
    assert json.loads(ch._get_html("https://www.youtube.com/@x/videos"))["family"] == "ipv4"


@needs_ipv6
@pytest.mark.parametrize("family", ["ipv4", "ipv6"])
def test_search_requests_use_requested_family(dual_servers, localhost_resolves_both,
                                              monkeypatch, family):
    import tutubo._innertube as it
    from tutubo import YoutubeSearch
    monkeypatch.setattr(it, "_BASE_URL", f"http://tutubo.test:{dual_servers}/youtubei/v1")
    assert YoutubeSearch("cats", family=family).fetch_query() == {"family": family}


def test_search_without_family_keeps_urllib_path(monkeypatch):
    import tutubo._innertube as it
    from tutubo import YoutubeSearch
    calls = []
    monkeypatch.setattr(it, "_post", lambda endpoint, params, body: calls.append(1) or {})
    s = YoutubeSearch("cats")
    assert s._session is None
    s.fetch_query()
    assert calls == [1]


def test_search_helper_and_factories_accept_family():
    from tutubo import YoutubeSearch, YoutubeMusicSearch
    assert _family_of(YoutubeSearch.for_movies("x", family="ipv6")._session) == ("::", 0)
    assert _family_of(YoutubeMusicSearch("x", family="ipv4")._session) == ("0.0.0.0", 0)


def test_search_yt_passes_family(monkeypatch):
    import tutubo.search as search_mod
    seen = []
    real = search_mod.YoutubeSearch

    class Spy(real):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            seen.append(self._session)

        def iterate_youtube(self, *a, **kw):
            return iter(())

    monkeypatch.setattr(search_mod, "YoutubeSearch", Spy)
    list(search_mod.search_yt("x", family="ipv4"))
    assert _family_of(seen[0]) == ("0.0.0.0", 0)


def test_previews_hand_session_to_upgraded_objects(monkeypatch, load_fixture):
    import tutubo.search as search_mod
    from tutubo import YoutubeSearch
    page = load_fixture("search_rob_zombie")
    monkeypatch.setattr(search_mod, "_innertube_search",
                        lambda q, c=None, session=None: {} if c else page)
    s = YoutubeSearch("rob zombie", family="ipv4")
    previews = list(s._iterate_and_parse())
    assert previews and all(p._session is s._session for p in previews)


def test_default_family_reaches_new_objects():
    from tutubo import Channel, YoutubeSearch
    from tutubo.transport import set_default_family
    set_default_family("ipv6")
    assert _family_of(Channel("https://www.youtube.com/@x")._session) == ("::", 0)
    assert _family_of(YoutubeSearch("x")._session) == ("::", 0)


def test_ytmusic_client_is_bound_to_the_pinned_session(monkeypatch):
    import tutubo.ytmus as ytmus
    from tutubo import YoutubeMusicSearch
    captured = []

    class FakeYTMusic:
        def __init__(self, requests_session=None, **kw):
            captured.append(requests_session)

        def search(self, q, **kw):
            return []

    monkeypatch.setattr(ytmus, "YTMusic", FakeYTMusic)
    s = YoutubeMusicSearch("x", family="ipv4")
    list(s.iterate_tracks())
    assert captured == [s._session]
    assert _family_of(captured[0]) == ("0.0.0.0", 0)


# ---------------------------------------------------------------------------
# unblock_requests (tutubo[stealth]), proxies, YT Music timeout, previews, yt-dlp
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_unblock(monkeypatch):
    """A CloudflareSession stand-in: its default path ignores adapters and uses
    a raw socket (like curl_cffi), its Wayback fallback uses unpinned sockets."""
    import sys
    import types

    wayback_calls = []

    class FakeCloudflareSession(requests.Session):
        def __init__(self, *, mode=None, wayback_fallback=None,
                     flaresolverr_fallback=None, env_prefix="X", ip_family=None, **kw):
            super().__init__()
            self.cf_mode = mode
            self.wayback_fallback = wayback_fallback
            self.ip_family = ip_family

        def _raw(self, url):
            from urllib.parse import urlparse
            u = urlparse(url)
            return requests.get(url, timeout=5)  # unpinned, like curl / module-level requests

        def request(self, method, url, **kw):
            if self.cf_mode == "requests":
                return super().request(method, url, **kw)
            try:
                return self._raw(url)
            except Exception:
                if self.wayback_fallback:
                    wayback_calls.append(url)
                    r = requests.Response()
                    r.status_code = 200
                    r._content = b"wayback"
                    return r
                raise

    mod = types.ModuleType("unblock_requests")
    mod.CloudflareSession = FakeCloudflareSession
    monkeypatch.setitem(sys.modules, "unblock_requests", mod)
    monkeypatch.delenv("TUTUBO_TRANSPORT", raising=False)
    return wayback_calls


def test_cloudflare_session_receives_the_family(fake_unblock):
    """The pinning itself is unblock_requests' ip_family option, not a private attribute."""
    from tutubo.transport import make_session
    s = make_session("ipv4")
    assert s.ip_family == "ipv4" and not s.wayback_fallback


def test_cloudflare_session_unpinned_keeps_stealth_defaults(fake_unblock):
    from tutubo.transport import make_session
    s = make_session()
    assert s.cf_mode is None and s.wayback_fallback is True and s.ip_family is None


@needs_ipv6
def test_real_unblock_requests_stays_on_pinned_family(monkeypatch):
    import unblock_requests.session as us
    from tutubo.transport import make_session
    monkeypatch.delenv("TUTUBO_TRANSPORT", raising=False)
    wayback = []
    monkeypatch.setattr(us, "wayback_html", lambda url, **kw: wayback.append(url) or "<html>copy</html>")
    v6 = _serve(_V6, "::1", 0)
    try:
        url = f"http://localhost:{v6.server_address[1]}/"
        with pytest.raises(OSError):
            make_session("ipv4").get(url, timeout=5)
        assert wayback == []
        assert make_session("ipv6").get(url, timeout=5).json() == {"family": "ipv6"}
    finally:
        v6.shutdown()
        v6.server_close()


@pytest.mark.parametrize("family,source", [("ipv4", ("0.0.0.0", 0)), ("ipv6", ("::", 0))])
def test_proxy_manager_is_pinned(family, source):
    from tutubo.transport import FamilyAdapter
    pm = FamilyAdapter(family).proxy_manager_for("http://127.0.0.1:3128")
    assert pm.connection_pool_kw["source_address"] == source


def _silent_server():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    return srv


def test_pinned_ytmusic_session_times_out(monkeypatch):
    """Run in a thread so that dropping the timeout fails fast instead of hanging."""
    import time
    import tutubo.ytmus as ytmus
    monkeypatch.setattr(ytmus, "_SESSION_TIMEOUT", 1)
    srv = _silent_server()
    outcome = {}

    def run():
        s = ytmus.pinned_session("ipv4")
        url = f"http://127.0.0.1:{srv.getsockname()[1]}/"
        t = time.time()
        try:
            s.get(url)
        except requests.Timeout:
            outcome["default"] = time.time() - t
        try:
            s.get(url, timeout=0.3)
        except requests.Timeout:
            outcome["explicit"] = True

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(15)
    srv.close()
    assert not th.is_alive(), "request without timeout is still blocked"
    assert outcome.get("default", 99) < 10 and outcome.get("explicit")


@pytest.mark.parametrize("env", ["", "curl_cffi"])
def test_pinned_ytmusic_session_is_a_requests_session_with_the_family(monkeypatch, env):
    """ytmusicapi only uses requests.Session instances, whatever TUTUBO_TRANSPORT says."""
    import tutubo.ytmus as ytmus
    from tutubo.transport import FamilyAdapter
    monkeypatch.setenv("TUTUBO_TRANSPORT", env)
    s = ytmus.pinned_session("ipv6")
    assert isinstance(s, requests.Session)
    assert isinstance(s.get_adapter("https://music.youtube.com"), FamilyAdapter)
    client = ytmus._get_ytmus(1, session=s)
    assert client._session is s


def test_ytmusic_search_pinned_session_has_default_timeout(monkeypatch):
    import tutubo.ytmus as ytmus
    from tutubo import YoutubeMusicSearch
    s = YoutubeMusicSearch("x", family="ipv4")
    assert s._session.request.keywords == {"timeout": ytmus._SESSION_TIMEOUT}


def test_search_yt_music_pinned_session_has_default_timeout(monkeypatch):
    import tutubo.ytmus as ytmus
    seen = []
    monkeypatch.setattr(ytmus, "_get_ytmus", lambda n, session=None: seen.append(session) or None)
    with pytest.raises(AttributeError):
        list(ytmus.search_yt_music("x", family="ipv6"))
    assert seen[0].request.keywords == {"timeout": ytmus._SESSION_TIMEOUT}


def test_channel_preview_get_keeps_session():
    from tutubo.models import ChannelPreview
    p = ChannelPreview({"channelId": "UC123"})
    p._session = sentinel = object()
    assert p.get()._session is sentinel


def test_playlist_preview_get_keeps_session():
    from tutubo.models import PlaylistPreview
    p = PlaylistPreview({"playlistId": "PL123"})
    p._session = sentinel = object()
    assert p.get()._session is sentinel


def test_related_search_get_keeps_session():
    from tutubo.models import RelatedSearch
    p = RelatedSearch({"query": {"runs": [{"text": "cats"}]}})
    p._session = sentinel = object()
    assert p.get()._session is sentinel


@pytest.mark.parametrize("family,flag", [("ipv4", "--force-ipv4"), ("ipv6", "--force-ipv6")])
def test_download_passes_family_to_ytdlp(monkeypatch, tmp_path, family, flag):
    dl = sys.modules["tutubo.download"]
    cmds = []

    def fake_run(cmd, **kw):
        cmds.append(cmd)
        return types_ns(returncode=0, stdout="[download] Destination: x.mp4\n", stderr="")

    from types import SimpleNamespace as types_ns
    monkeypatch.setattr(dl, "_require_ytdlp", lambda: None)
    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    dl.download("https://youtu.be/x", str(tmp_path), family=family)
    dl.download_playlist("https://youtu.be/p", str(tmp_path), family=family)
    assert all(flag in c for c in cmds) and len(cmds) == 2


def test_download_default_family_and_unset(monkeypatch, tmp_path):
    dl = sys.modules["tutubo.download"]
    from types import SimpleNamespace
    from tutubo.transport import set_default_family
    cmds = []
    monkeypatch.setattr(dl, "_require_ytdlp", lambda: None)
    monkeypatch.setattr(dl.subprocess, "run", lambda cmd, **kw: cmds.append(cmd) or SimpleNamespace(
        returncode=0, stdout="[download] Destination: x.mp4\n", stderr=""))
    dl.download("u", str(tmp_path))
    set_default_family("ipv6")
    dl.download("u", str(tmp_path))
    assert "--force-ipv6" not in cmds[0] and "--force-ipv6" in cmds[1]


@needs_ipv6
@pytest.mark.parametrize("form", ["2130706433", "0x7f.1", "127.1"])
def test_curl_env_transport_ipv6_pin_refuses_other_forms_of_ipv4(dual_servers, monkeypatch, form):
    from tutubo.transport import make_session
    monkeypatch.setenv("TUTUBO_TRANSPORT", "curl_cffi")
    assert make_session(None).get(f"http://{form}:{dual_servers}/", timeout=5).json() == {"family": "ipv4"}
    with pytest.raises(OSError):
        make_session("ipv6").get(f"http://{form}:{dual_servers}/", timeout=5)


# ---------------------------------------------------------------------------
# search error rule, podcasts, get_album
# ---------------------------------------------------------------------------

class _Status500(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(500)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture(params=["plain", "stealth", "curl_env"])
def transport(request, monkeypatch):
    monkeypatch.delenv("TUTUBO_TRANSPORT", raising=False)
    if request.param == "plain":
        monkeypatch.setitem(sys.modules, "unblock_requests", None)
    elif request.param == "curl_env":
        monkeypatch.setenv("TUTUBO_TRANSPORT", "curl_cffi")
    return request.param


@pytest.mark.parametrize("family", ["ipv4", "ipv6"])
def test_search_raises_runtime_error_on_a_refused_port(transport, monkeypatch, family):
    import tutubo._innertube as it
    from tutubo import YoutubeSearch
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setattr(it, "_BASE_URL", f"http://localhost:{port}/youtubei/v1")
    with pytest.raises(RuntimeError):
        YoutubeSearch("cats", family=family).fetch_query()


def test_search_raises_runtime_error_on_http_500(transport, monkeypatch):
    import tutubo._innertube as it
    from tutubo import YoutubeSearch
    srv = _serve(_V4, "127.0.0.1", 0)
    srv.RequestHandlerClass = _Status500
    try:
        monkeypatch.setattr(it, "_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}/youtubei/v1")
        with pytest.raises(RuntimeError, match="500"):
            YoutubeSearch("cats", family="ipv4").fetch_query()
    finally:
        srv.shutdown()
        srv.server_close()


def test_channel_raises_oserror_on_a_refused_port(transport, monkeypatch):
    from tutubo import Channel
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    ch = Channel("https://www.youtube.com/@x", family="ipv4")
    real_get = ch._session.get
    monkeypatch.setattr(ch._session, "get", lambda url, **kw: real_get(f"http://127.0.0.1:{port}/", **kw))
    with pytest.raises(OSError):
        ch._get_html("https://www.youtube.com/@x/videos")


def test_podcast_preview_get_carries_the_channel_session(monkeypatch):
    from tutubo import Channel
    ch = Channel("https://www.youtube.com/@x", family="ipv4")
    lvm = {"x": 1}
    data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [{"tabRenderer": {
        "endpoint": {"commandMetadata": {"webCommandMetadata": {"url": "/@x/podcasts"}}},
        "content": {"richGridRenderer": {"contents": [
            {"richItemRenderer": {"content": {"lockupViewModel": lvm}}}]}}}}]}}}
    monkeypatch.setattr(ch, "_get_data", lambda url: data)
    from tutubo.channel import PodcastPreview
    monkeypatch.setattr(Channel, "_parse_podcast_item",
                        staticmethod(lambda lvm: PodcastPreview("t", "PL1")))
    (pod,) = list(ch._podcast_generator())
    assert pod.get()._session is ch._session
    assert _family_of(pod.get()._session) == ("0.0.0.0", 0)


def test_get_album_honours_the_default_family(monkeypatch):
    import tutubo.ytmus as ytmus
    from tutubo.transport import set_default_family
    seen = []

    class FakeYT:
        def __init__(self, requests_session=None, **kw):
            seen.append(requests_session)

        def get_album(self, b):
            return {}

    monkeypatch.setattr(ytmus, "YTMusic", FakeYT)
    monkeypatch.setattr(ytmus, "_YTMUS", None)
    monkeypatch.setattr(ytmus, "_PINNED_CLIENTS", {})
    set_default_family("ipv6")
    ytmus.get_album("MPRE1")
    ytmus.get_album("MPRE2")
    assert len(seen) == 1
    from tutubo.transport import FamilyAdapter
    assert isinstance(seen[0].get_adapter("https://music.youtube.com"), FamilyAdapter)


def test_ipv6_pinned_requests_session_refuses_a_v4_mapped_literal(monkeypatch):
    """IPV6_V6ONLY keeps ::ffff:a.b.c.d from reaching an IPv4-only server."""
    from tutubo.transport import make_session
    monkeypatch.delenv("TUTUBO_TRANSPORT", raising=False)
    monkeypatch.setitem(sys.modules, "unblock_requests", None)
    v4 = _serve(_V4, "127.0.0.1", 0)
    try:
        url = f"http://[::ffff:127.0.0.1]:{v4.server_address[1]}/"
        assert requests.Session().get(url, timeout=5).json() == {"family": "ipv4"}  # control
        with pytest.raises(OSError):
            make_session("ipv6").get(url, timeout=5)
    finally:
        v4.shutdown()
        v4.server_close()


def test_default_family_clients_are_cached_per_family(monkeypatch):
    import tutubo.ytmus as ytmus
    from tutubo.transport import set_default_family

    class FakeYT:
        def __init__(self, requests_session=None, **kw):
            self._session = requests_session

    monkeypatch.setattr(ytmus, "YTMusic", FakeYT)
    monkeypatch.setattr(ytmus, "_YTMUS", None)
    monkeypatch.setattr(ytmus, "_PINNED_CLIENTS", {})
    set_default_family("ipv4")
    c4 = ytmus._get_ytmus()
    assert _family_of(c4._session) == ("0.0.0.0", 0)
    set_default_family("ipv6")
    c6 = ytmus._get_ytmus()
    assert c6 is not c4 and _family_of(c6._session) == ("::", 0)
    set_default_family("ipv4")
    assert ytmus._get_ytmus() is c4
