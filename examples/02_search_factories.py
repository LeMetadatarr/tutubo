"""02 — Search factories: intent-focused queries with typed iterators.

Each factory appends a keyword phrase to improve YouTube's result ranking.
Pairing factory + typed iterator gives both a ranking boost and a
content-type filter — double-filtering for precision.
"""
from tutubo import YoutubeSearch

# MOVIE: "blade runner full movie" + filter to MOVIE content type
print("=== Movies ===")
for v in YoutubeSearch.for_movies("blade runner").iterate_movies(max_res=3):
    mins = v.length // 60
    print(f"  {v.title}  [{mins}m]  {v.watch_url}")

# CONCERT: "black sabbath full concert" + filter to CONCERT
print("\n=== Concerts ===")
for v in YoutubeSearch.for_concerts("black sabbath").iterate_concerts(max_res=3):
    mins = v.length // 60
    print(f"  {v.title}  [{mins}m]")

# DOCUMENTARY: "david attenborough documentary" + filter to DOCUMENTARY
print("\n=== Documentaries ===")
for v in YoutubeSearch.for_documentaries("david attenborough").iterate_documentaries(max_res=3):
    print(f"  {v.title}")

# TUTORIAL: "python asyncio tutorial" + filter to TUTORIAL
print("\n=== Tutorials ===")
for v in YoutubeSearch.for_tutorials("python asyncio").iterate_tutorials(max_res=3):
    print(f"  {v.title}  {v.short_view_count}")

# MUSIC_VIDEO: "rob zombie official music video" + filter to MUSIC_VIDEO
print("\n=== Music videos ===")
for v in YoutubeSearch.for_music_videos("rob zombie").iterate_music_videos(max_res=3):
    print(f"  {v.title}  official_artist={v.is_official_artist_channel}")

# Related search queries
print("\n=== Related search suggestions for 'black metal' ===")
s = YoutubeSearch("black metal")
for q in s.iterate_queries():
    print(f"  -> {q.query}")
