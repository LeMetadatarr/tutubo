"""04 — Playlist: channel playlists and direct playlist iteration.

Shows how to list a channel's playlists and iterate their videos.
Playlist pages are fetched lazily; continuation tokens are handled
automatically.
"""
from tutubo import Channel
from tutubo.channel import Playlist

# Channel playlists
c = Channel("https://www.youtube.com/channel/UC4BSeEq7XNtihGqI309vhYg")
print(f"Channel: {c.channel_name}")
print(f"Playlist URLs: {c.playlist_urls[:3]} (first 3)")

print("\n=== First 3 playlists and their first 5 videos ===")
for i, pl in enumerate(c.playlists):
    print(f"\nPlaylist: {pl.title or '(untitled)'}")
    for j, v in enumerate(pl.videos):
        print(f"  {v.watch_url}")
        if j >= 4:
            break
    if i >= 2:
        break

# Construct a Playlist directly from a URL
print("\n=== Direct Playlist from URL ===")
pl = Playlist("https://www.youtube.com/playlist?list=PLBxwSF9JxLuJea2Hn2b_xw-3X7IAfBMZT")
print(f"Playlist ID: {pl.playlist_id}")
print(f"Title:       {pl.title}")
print("First 5 video URLs:")
for i, v in enumerate(pl.videos):
    print(f"  {v.watch_url}")
    if i >= 4:
        break
