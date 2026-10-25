# Transport

`tutubo/transport.py`

tutubo fetches channel and playlist HTML pages through a pluggable HTTP session. All page requests share consent cookies (`SOCS`, `CONSENT`), so EU/GDPR consent redirects do not interrupt scraping.

---

## Default session: `default_session()`

`tutubo/transport.py:37`

Returns a fresh HTTP session. By default this is a `requests.Session`. The function honors the `TUTUBO_TRANSPORT` environment variable:

```python
from tutubo.transport import default_session
session = default_session()
```

| `TUTUBO_TRANSPORT` value | Session returned |
|---|---|
| unset or any other value | `requests.Session` |
| `curl_cffi` | `curl_cffi.requests.Session(impersonate="chrome")` |

---

## Stealth transport: `curl_cffi`

`curl_cffi` mimics a real Chrome TLS/JA3 fingerprint. This helps bypass bot detection that some YouTube edge nodes apply to requests with atypical TLS fingerprints.

Install:

```bash
pip install tutubo[stealth]
```

Enable through an environment variable (applies to all `Channel` and `Playlist` instances):

```bash
export TUTUBO_TRANSPORT=curl_cffi
```

Or inject a session directly into a single instance:

```python
from curl_cffi import requests as cffi_requests
from tutubo.channel import Channel
ch = Channel(
    "https://www.youtube.com/@LinusTechTips",
    session=cffi_requests.Session(impersonate="chrome"),
)
```

If `TUTUBO_TRANSPORT=curl_cffi` is set but `curl_cffi` is not installed, tutubo logs a warning and falls back to `requests.Session` (`tutubo/transport.py:37`).

---

## Address family: `make_session(family=...)`

`tutubo/transport.py`

YouTube may treat IPv4 and IPv6 clients differently. A session can be pinned to one IP family, so a caller does not have to patch urllib3 for the whole process:

```python
from tutubo import Channel, Playlist, YoutubeSearch
from tutubo.transport import make_session

ch = Channel("https://www.youtube.com/@LinusTechTips", family="ipv4")
pl = Playlist("https://www.youtube.com/playlist?list=PL...", family="ipv6")
results = YoutubeSearch("lo-fi beats", family="ipv4")
session = make_session("ipv4")          # a plain requests.Session
```

The family lives in the session's adapters, so it affects only that session and is safe with threads. A pinned session never falls back to the other family: a connection to a host with no address in that family fails. The rule for callers: `Channel` and `Playlist` raise `OSError` subclasses (`requests.ConnectionError`, or curl_cffi's own error types on curl-based sessions), so catch `OSError`; search (`YoutubeSearch`) raises `RuntimeError` on every transport, and `RuntimeError` is not an `OSError`. With a proxy, the family applies to the connection to the proxy.

To pin everything created afterwards, call `tutubo.transport.set_default_family("ipv4")`; `family="any"` on one object opts out, and `set_default_family(None)` clears it. Nothing changes while no family is set.

`YoutubeSearch`, `search_yt`, `YoutubeSearch.for_*` and `YoutubeMusicSearch` accept `family=` (or `session=`). Previews returned by a search hand the same session to the `Channel`, `Playlist` or search that `.get()` creates. With `curl_cffi` (`TUTUBO_TRANSPORT=curl_cffi`, or the `unblock_requests` fast path of `tutubo[stealth]`) the family is set through curl's IP resolve option and the local bind address, so a target of the other family is refused however its literal is written and browser TLS impersonation is kept. A pinned `unblock_requests` session is created with its `ip_family` option and has its Wayback, solver and proxy fallbacks off, because those routes would leave the pinned family. `download` and `download_playlist` take `family=` (or the default) and pass `--force-ipv4` / `--force-ipv6` to yt-dlp.

---

## Scope of the transport setting

The transport setting applies to:

- `Channel`: all tab page fetches and continuation POSTs
- `Playlist`: initial page fetch and continuation POSTs

Search queries use stdlib `urllib.request` unless a session or family is given to `YoutubeSearch`, in which case they go through that session. `TUTUBO_TRANSPORT` does not affect the `urllib` path. `YoutubeMusicSearch` uses the shared `ytmusicapi` client unless a session, a family or a default family is given, which uses a dedicated client on a plain `requests` session pinned to that family (ytmusicapi accepts only `requests` sessions, so `TUTUBO_TRANSPORT` does not apply). `get_album` honours the default family as well.

---
[← mediavocab](mediavocab.md) · [Home](index.md) · [Locale →](locale.md)
