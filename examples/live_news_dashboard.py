"""
Live news dashboard — check which channels are currently on air.

Channels: @euronews, @France24_en, @AJEnglish, @euronewses
Uses Channel.live (/@handle/live redirect) to check the current on-air stream.
Uses Channel.streams (/@handle/streams tab) for the recent stream archive.
"""
from tutubo.channel import Channel
from tutubo import ContentType

NEWS_CHANNELS = [
    ("Euronews EN",  "https://www.youtube.com/@euronews"),
    ("France 24 EN", "https://www.youtube.com/@france24_en"),
    ("Al Jazeera",   "https://www.youtube.com/@aljazeeraenglish"),
    ("Euronews ES",  "https://www.youtube.com/@euronewses"),
]

print("Live news status\n" + "─" * 50)
for name, url in NEWS_CHANNELS:
    c = Channel(url)

    # Channel.live → /@handle/live redirect — single on-air video or None
    current = c.live
    if current:
        print(f"  🔴  {name:20s}  {current.title}")
        print(f"       {current.watch_url}")
    else:
        print(f"  ○   {name:20s}  (offline)")

print("\nRecent stream archive (last 5 per channel)")
print("─" * 50)
for name, url in NEWS_CHANNELS:
    c = Channel(url)
    print(f"\n  {name}")
    # Channel.streams → /@handle/streams tab — paginated list
    for i, v in enumerate(c.streams):
        status = "LIVE" if v.is_live else "recorded"
        when = v.published_time or ""
        print(f"    [{status:8s}] {when:>14}  {v.title}")
        if i >= 4:
            break
