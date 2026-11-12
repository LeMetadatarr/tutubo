"""
Discover award-winning short films from curated channels.

Channels: @watchdust, @WatchALTER, @Omeleto
These channels publish narrative short films — typically 5-30 minutes,
free to watch, classified as SHORT_FILM or VIDEO.
"""
from tutubo.channel import Channel
from tutubo import ContentType
from mediavocab.text import extract_tags

CHANNELS = [
    ("Dust",    "https://www.youtube.com/@watchdust/videos"),
    ("ALTER",   "https://www.youtube.com/@WatchALTER/videos"),
    ("Omeleto", "https://www.youtube.com/@Omeleto/videos"),
]

for name, url in CHANNELS:
    print(f"\n── {name} ──────────────────────────────")
    c = Channel(url)
    shown = 0
    for v in c.videos:
        if v.content_type not in (ContentType.SHORT_FILM, ContentType.VIDEO):
            continue
        tags = extract_tags(v.title or "", channel_tags=v.channel_tags)
        genre = ", ".join(t for t in tags if t in (
            "horror", "sci-fi", "thriller", "fantasy", "romance", "comedy", "animation"
        ))
        print(f"  {v.title}")
        if genre:
            print(f"    [{genre}]  {v.watch_url}")
        else:
            print(f"    {v.watch_url}")
        shown += 1
        if shown >= 10:
            break
