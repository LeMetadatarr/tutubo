"""
Comedy digest — top clips from Comedy Central, Markiplier, and Overly Sarcastic Productions.

Channels: @ComedyCentral, @markiplier, @OverlySarcasticProductions
Sorted by view count. Skips full specials and VODs (CONCERT / STAND_UP).
"""
from tutubo.channel import Channel
from tutubo import ContentType

CHANNELS = [
    ("Comedy Central",               "https://www.youtube.com/@ComedyCentral/videos"),
    ("Markiplier",                   "https://www.youtube.com/@markiplier/videos"),
    ("Overly Sarcastic Productions", "https://www.youtube.com/@overlysarcasticproductions/videos"),
]

SKIP_TYPES = {ContentType.CONCERT, ContentType.STAND_UP, ContentType.MOVIE}

print("Top comedy clips\n" + "─" * 60)

hits = []
for name, url in CHANNELS:
    c = Channel(url)
    channel_hits = 0
    for v in c.videos:
        if v.content_type in SKIP_TYPES:
            continue
        try:
            views = int(''.join(ch for ch in str(v.view_count) if ch.isdigit()) or 0)
        except Exception:
            views = 0
        hits.append((views, name, v))
        channel_hits += 1
        if channel_hits >= 15:
            break

hits.sort(reverse=True, key=lambda h: h[0])
for views, channel, v in hits[:15]:
    print(f"  {views:>10,}  [{channel}]  {v.title}")
    print(f"             {v.watch_url}")
