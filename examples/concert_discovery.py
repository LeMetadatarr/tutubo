"""
Find full concert recordings on Live Nation's channel.

Channel: @livenation
Classifies videos and separates full concerts from clips and trailers.
"""
from tutubo.channel import Channel
from tutubo import ContentType

url = "https://www.youtube.com/@livenation/videos"
c = Channel(url)

concerts, trailers, clips = [], [], []

for v in c.videos:
    ct = v.content_type
    if ct == ContentType.CONCERT:
        concerts.append(v)
    elif ct == ContentType.TRAILER:
        trailers.append(v)
    else:
        clips.append(v)
    if len(concerts) + len(trailers) + len(clips) >= 50:
        break

if concerts:
    print(f"Full concerts ({len(concerts)} found):")
    for v in concerts[:8]:
        print(f"  {v.title}")
        print(f"    {v.watch_url}")

if trailers:
    print(f"\nTrailers / teasers ({len(trailers)} found):")
    for v in trailers[:5]:
        print(f"  {v.title}")
        print(f"    {v.watch_url}")

print(f"\nOther clips: {len(clips)}")
for v in clips[:3]:
    print(f"  [{v.content_type.value}]  {v.title}")
