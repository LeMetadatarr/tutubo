"""07 — YouTube Music albums: full track listings.

MusicAlbum is a subclass of MusicPlaylist. iterate_albums() fetches the
full album page (one API call per album) to populate tracks, label, and
duration. Each MusicTrack in album.tracks has track_number set.
"""
from tutubo import YoutubeMusicSearch

query = "black sabbath paranoid"
s = YoutubeMusicSearch(query)

for album in s.iterate_albums(max_res=3):
    print(f"\n{album.title} — {album.artist}  ({album.year})")
    print(f"  tracks: {album.track_count}  label: {album.label or '(none)'}")
    print(f"  explicit: {album.is_explicit}")
    print(f"  url: {album.playlist_url}")
    if album.duration_seconds:
        total = f"{album.duration_seconds // 60}m"
        print(f"  total duration: {total}")
    print("  Track listing:")
    for t in album.tracks:
        dur = f"{t.length // 60}:{t.length % 60:02d}" if t.length else "?"
        print(f"    {t.track_number or '?':>2}. {t.title}  [{dur}]  {t.watch_url}")
