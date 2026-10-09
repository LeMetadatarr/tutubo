"""10 — Advanced: custom session and transport configuration.

Demonstrates three ways to control the HTTP transport:
  1. Default (requests.Session) — no configuration needed.
  2. Environment variable: TUTUBO_TRANSPORT=curl_cffi
  3. Direct session injection — most flexible, per-instance.

Note: the search path (YoutubeSearch / _innertube._post) always uses
stdlib urllib.request and is NOT affected by the session setting.
Only Channel and Playlist page fetches honour the injected session.
"""
import os
from tutubo.transport import default_session
from tutubo.channel import Channel

# 1. Default session — requests.Session
session = default_session()
print(f"Default session type: {type(session).__name__}")

c = Channel("https://www.youtube.com/@Metallica", session=session)
print(f"Channel via default session: {c.channel_name}")

# 2. Via environment variable (curl_cffi must be installed)
# export TUTUBO_TRANSPORT=curl_cffi
if os.environ.get("TUTUBO_TRANSPORT", "").lower() == "curl_cffi":
    stealth_session = default_session()
    print(f"Stealth session type: {type(stealth_session).__name__}")
    c2 = Channel("https://www.youtube.com/@Metallica", session=stealth_session)
    print(f"Channel via stealth session: {c2.channel_name}")
else:
    print("TUTUBO_TRANSPORT not set to curl_cffi — skipping stealth demo.")
    print("To enable: pip install tutubo[stealth] && export TUTUBO_TRANSPORT=curl_cffi")

# 3. Direct injection (no env var needed)
try:
    from curl_cffi import requests as cffi_requests  # type: ignore
    cffi_session = cffi_requests.Session(impersonate="chrome")
    c3 = Channel("https://www.youtube.com/@Metallica", session=cffi_session)
    print(f"Channel via injected curl_cffi: {c3.channel_name}")
except ImportError:
    print("curl_cffi not installed. Install with: pip install tutubo[stealth]")

# Accept-Language affects display language of some metadata fields
c_pt = Channel(
    "https://www.youtube.com/@Metallica",
    language="pt-PT,pt;q=0.9",
)
# language is sent as Accept-Language header; affects auto-translated
# titles and some metadata on pages served to non-English locales.
print(f"Channel with pt-PT language: {c_pt.channel_name}")
