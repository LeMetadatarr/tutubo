"""06 — YouTube Music search: tracks, artists, playlists.

YoutubeMusicSearch queries music.youtube.com via ytmusicapi.
It is a completely separate surface from YoutubeSearch:
  - No ContentType classification (music entities don't use it)
  - MusicTrack.watch_url uses music.youtube.com
  - MusicVideo.watch_url uses youtube.com
"""
from tutubo import YoutubeMusicSearch

query = "black sabbath"
s = YoutubeMusicSearch(query)

print(f"=== Music tracks for '{query}' ===")
for track in s.iterate_tracks(max_res=5):
    dur = f"{track.length // 60}:{track.length % 60:02d}" if track.length else "?"
    print(f"  {track.title} — {track.artist}  [{dur}]")
    print(f"    audio_only={track.is_audio_only}  music_video={track.is_music_video}  explicit={track.is_explicit}")
    print(f"    url: {track.watch_url}")

print(f"\n=== Artists for '{query}' ===")
for artist in s.iterate_artists(max_res=2):
    print(f"  {artist.name}  {artist.subscribers}")
    print(f"  Top tracks:")
    for t in artist.tracks[:3]:
        print(f"    {t.title}")

print(f"\n=== Community playlists for '{query}' ===")
for pl in s.iterate_playlists(max_res=2):
    print(f"  {pl.title}  ({pl.track_count} tracks)  {pl.playlist_url}")
