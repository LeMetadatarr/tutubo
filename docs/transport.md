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

## Scope of the transport setting

The transport setting applies to:

- `Channel`: all tab page fetches and continuation POSTs
- `Playlist`: initial page fetch and continuation POSTs

It does **not** apply to:

- `tutubo._innertube._post`: the search path uses stdlib `urllib.request` directly. Sessions injected here have no effect on search queries.
- `YoutubeMusicSearch`: uses `ytmusicapi` internally, which manages its own HTTP session.

---
[← mediavocab](mediavocab.md) · [Home](index.md) · [Locale →](locale.md)
