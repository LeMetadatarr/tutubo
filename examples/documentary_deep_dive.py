"""
Documentary deep dive across PBS Documentaries and The Dissenter (academic interviews).

Channels: @pbsdocumentaries, @TheDissenterRL
Shows how the same channel can contain both DOCUMENTARY and INTERVIEW content,
and how the podcast tab differs from the video tab.
"""
from tutubo.channel import Channel
from tutubo import ContentType

print("PBS Documentaries\n" + "─" * 50)
c = Channel("https://www.youtube.com/@pbsdocumentaries/videos")
by_type: dict = {}
for v in c.videos:
    by_type.setdefault(v.content_type, []).append(v)
    if sum(len(x) for x in by_type.values()) >= 40:
        break

for ct, videos in sorted(by_type.items(), key=lambda x: -len(x[1])):
    print(f"\n  {ct.value} ({len(videos)}):")
    for v in videos[:3]:
        print(f"    {v.published_time or '':>12s}  {v.title}")

print("\n\nThe Dissenter — videos vs podcasts\n" + "─" * 50)
c = Channel("https://www.youtube.com/@thedissenterrl")

print("\nVideos tab (interviews with researchers):")
for i, v in enumerate(c.videos):
    print(f"  [{v.content_type.value:12s}]  {v.title[:70]}")
    if i >= 4:
        break

print("\nPodcasts tab:")
for i, v in enumerate(c.podcasts):
    print(f"  [{v.episode_count:>10s}]  {v.title[:70]}")
    if i >= 4:
        break
