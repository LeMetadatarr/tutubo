"""01 — Quickstart: search YouTube and inspect results.

Shows the basic search API, result types, content_type classification, and
the convenience dict interface. No channel fetches — everything comes from
search-result data already in memory.
"""
from tutubo import YoutubeSearch, search_yt

query = "rob zombie"
s = YoutubeSearch(query)

print(f"=== Videos for '{query}' ===")
for v in s.iterate_videos(max_res=5):
    print(f"\n{v.title}")
    print(f"  author:       {v.author}")
    print(f"  length:       {v.length}s")
    print(f"  published:    {v.published_time}")
    print(f"  views:        {v.short_view_count}")
    print(f"  content_type: {v.content_type}")
    print(f"  badges:       {v.badges}")
    print(f"  has_captions: {v.has_captions}")
    print(f"  tags:         {v.tags}")

print(f"\n=== Channels for '{query}' ===")
for ch in s.iterate_channels():
    print(f"  {ch.title}  verified={ch.is_verified}  {ch.subscriber_count}")

print(f"\n=== Playlists for '{query}' ===")
for pl in s.iterate_playlists():
    print(f"  {pl.title}  ({pl.video_count} videos)")

print(f"\n=== Dict interface (search_yt) ===")
for item in search_yt(query, max_res=3):
    print(item["title"], "|", item["content_type"], "|", item["url"])
