"""Search YouTube Music for albums and artists, print track listings."""
from tutubo import YoutubeMusicSearch

query = "black sabbath"
s = YoutubeMusicSearch(query)

print(f"=== Albums for '{query}' ===")
for album in s.iterate_albums(max_res=3):
    print(f"\n{album.title} — {album.artist}")
    for track in album.tracks:
        dur = f"{track.length // 60}:{track.length % 60:02d}" if track.length else "?"
        print(f"  {track.title} [{dur}]  {track.watch_url}")

print(f"\n=== Artists for '{query}' ===")
for artist in s.iterate_artists(max_res=2):
    print(f"\n{artist.name}")
    for track in artist.tracks[:5]:
        print(f"  {track.title}  {track.watch_url}")
