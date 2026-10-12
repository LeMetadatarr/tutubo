"""Tests for the pluggable HTTP transport layer."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock



def test_default_session_returns_requests_by_default(monkeypatch):
    monkeypatch.delenv("TUTUBO_TRANSPORT", raising=False)
    from tutubo.transport import default_session
    import requests
    s = default_session()
    assert isinstance(s, requests.Session)


def test_default_session_falls_back_when_curl_cffi_missing(monkeypatch):
    """env var asks for curl_cffi but the module isn't importable -> fall back."""
    monkeypatch.setenv("TUTUBO_TRANSPORT", "curl_cffi")
    # Ensure curl_cffi import fails
    monkeypatch.setitem(sys.modules, "curl_cffi", None)
    import requests
    from tutubo.transport import default_session
    s = default_session()
    assert isinstance(s, requests.Session)


def test_default_session_uses_curl_cffi_when_present(monkeypatch):
    monkeypatch.setenv("TUTUBO_TRANSPORT", "curl_cffi")
    fake_session = MagicMock(name="curl_cffi_session")
    fake_requests = types.SimpleNamespace(Session=MagicMock(return_value=fake_session))
    fake_pkg = types.ModuleType("curl_cffi")
    fake_pkg.requests = fake_requests
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_pkg)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_requests)
    from tutubo.transport import default_session
    s = default_session()
    fake_requests.Session.assert_called_once_with(impersonate="chrome")
    assert s is fake_session


def test_channel_accepts_session_kwarg():
    """Channel uses the injected session for its HTTP calls."""
    from tutubo.channel import Channel
    fake_session = MagicMock()
    resp = MagicMock()
    resp.text = "<html><script>var ytInitialData = {};</script></html>"
    resp.raise_for_status = MagicMock()
    fake_session.get.return_value = resp

    ch = Channel("https://www.youtube.com/@example", session=fake_session)
    assert ch._session is fake_session
    # Trigger an HTML fetch
    ch._get_html(ch.channel_url)
    fake_session.get.assert_called_once()
    args, kwargs = fake_session.get.call_args
    assert args[0] == ch.channel_url
    assert "User-Agent" in kwargs["headers"]


def test_playlist_accepts_session_kwarg():
    from tutubo.channel import Playlist
    fake_session = MagicMock()
    resp = MagicMock()
    resp.text = "<html></html>"
    resp.raise_for_status = MagicMock()
    fake_session.get.return_value = resp

    p = Playlist("https://www.youtube.com/playlist?list=PL123", session=fake_session)
    assert p._session is fake_session
    _ = p.html
    fake_session.get.assert_called_once()


def test_channel_default_session_is_requests(monkeypatch):
    monkeypatch.delenv("TUTUBO_TRANSPORT", raising=False)
    from tutubo.channel import Channel
    import requests
    ch = Channel("https://www.youtube.com/@example")
    assert isinstance(ch._session, requests.Session)
