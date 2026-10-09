"""03 — Channel: metadata, videos tab, shorts tab, live streams.

Demonstrates Channel metadata properties, lazy video iteration with
content-type classification, and the distinction between:
  - Channel.streams  (/@handle/streams browse tab — all archived streams)
  - Channel.live     (/@handle/live redirect — single on-air Video or None)
"""
from tutubo import Channel

c = Channel("https://www.youtube.com/@Metallica")

print("=== Channel metadata ===")
print(f"  name:        {c.channel_name}")
print(f"  channel_id:  {c.channel_id}")
print(f"  subscribers: {c.subscribers}")
print(f"  videos:      {c.video_count_label}")
print(f"  keywords:    {c.keywords[:5]}")
print(f"  rss:         {c.rss_url}")
print(f"  vanity_url:  {c.vanity_url}")

print("\n=== Recent uploads (videos tab, first 10) ===")
for i, v in enumerate(c.videos):
    print(f"  {v.title}")
    print(f"    views={v.view_count}  published={v.published_time}  type={v.content_type}")
    if i >= 9:
        break

print("\n=== Recent shorts (first 5) ===")
for i, v in enumerate(c.shorts):
    print(f"  {v.title}  {v.watch_url}")
    if i >= 4:
        break

print("\n=== Current on-air stream (Channel.live) ===")
live = c.live   # single Video or None — reads /@handle/live
if live:
    print(f"  LIVE NOW: {live.title}")
    print(f"  Watch:    {live.watch_url}")
else:
    print("  (channel is offline)")

print("\n=== Stream archive (Channel.streams, first 5) ===")
news = Channel("https://www.youtube.com/@euronews")
for i, v in enumerate(news.streams):  # reads /@handle/streams browse tab
    status = "LIVE" if v.is_live else "archived"
    print(f"  [{status}]  {v.title}  {v.published_time}")
    if i >= 4:
        break
