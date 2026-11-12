"""
Explore underground music channels — full albums and mixes not on YouTube Music.

Channels: @StonedMeadowOfDoom (stoner/doom), @bmpromotion (black metal), @NewSovietWave
These channels publish full albums and premieres (MUSIC_AUDIO) and long mixes (VIDEO).
They're absent from YouTube Music — YouTube is the only way to find this content.
"""
from tutubo.channel import Channel
from tutubo import ContentType
from mediavocab.text import extract_tags

CHANNELS = [
    ("Stoned Meadow of Doom", "https://www.youtube.com/@StonedMeadowOfDoom/videos", "stoner doom"),
    ("BM Promotion",          "https://www.youtube.com/@bmpromotion/videos",         "black metal"),
    ("New Soviet Wave",       "https://www.youtube.com/@NewSovietWave/videos",       "sovietwave"),
]

for name, url, genre in CHANNELS:
    print(f"\n── {name}  ({genre}) ───────────────────────")
    c = Channel(url)
    albums, mixes, other = [], [], []
    for v in c.videos:
        tags = extract_tags(v.title or "")
        if v.content_type == ContentType.MUSIC_AUDIO:
            if "full-album" in tags or "premiere" in tags or "ep" in tags:
                albums.append(v)
            else:
                other.append(v)
        elif "mix" in tags:
            mixes.append(v)
        if len(albums) + len(mixes) + len(other) >= 30:
            break

    if albums:
        print(f"  Full albums / premieres / EPs ({len(albums)}):")
        for v in albums[:6]:
            print(f"    {v.title}")
    if mixes:
        print(f"  Mixes ({len(mixes)}):")
        for v in mixes[:3]:
            print(f"    {v.title}")
    if not albums and not mixes:
        print("  (no full albums, mixes, or EPs found on first page)")
        for v in other[:3]:
            print(f"    [{v.content_type.value}]  {v.title}")
