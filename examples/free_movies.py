"""
Browse full-length movies available free on YouTube.

Channels: @Mosfilm_eng (Soviet classics), @CultCinemaClassics, @moonflix_official
"""
from tutubo.channel import Channel
from tutubo import ContentType
from mediavocab.text import extract_tags

CHANNELS = [
    ("Mosfilm (English)",    "https://www.youtube.com/@Mosfilm_eng/videos"),
    ("Cult Cinema Classics", "https://www.youtube.com/@CultCinemaClassics/videos"),
    ("Moonflix",             "https://www.youtube.com/@moonflix_official/videos"),
]

for name, url in CHANNELS:
    print(f"\n── {name} ──────────────────────────────")
    c = Channel(url)
    shown = 0
    for v in c.videos:
        if v.content_type != ContentType.MOVIE:
            continue
        tags = extract_tags(v.title or "", channel_tags=v.channel_tags)
        era   = next((t for t in tags if t in ("silent-era", "classic", "colorized", "4k")), "")
        genre = next((t for t in tags if t in (
            "horror", "sci-fi", "thriller", "fantasy", "romance", "comedy",
            "action", "crime", "war", "western", "animation"
        )), "")
        label = "  ".join(filter(None, [era, genre]))
        if label:
            print(f"  [{label}]  {v.title}")
        else:
            print(f"  {v.title}")
        print(f"    {v.watch_url}")
        shown += 1
        if shown >= 8:
            break
