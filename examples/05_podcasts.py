"""05 — Podcasts: channel podcast shows and episode listing.

YouTube channels with a Podcasts tab expose grouped shows. Each show is
a PodcastPreview backed by a playlist of episodes.

Note: episodes are NOT auto-classified as ContentType.PODCAST. Pass
is_podcast=True to classify_video() explicitly when needed.
"""
from tutubo import Channel
from mediavocab.text import classify_video

c = Channel("https://www.youtube.com/@TheDissenterRL")
print(f"Channel: {c.channel_name}\n")

for pod in c.podcasts:
    print(f"Show: {pod.title}")
    print(f"  episodes:    {pod.episode_count}")
    print(f"  last update: {pod.last_updated}")
    print(f"  playlist:    {pod.playlist_url}")

    # Hydrate to a Playlist for full episode iteration
    pl = pod.get()
    print("  First 3 episodes:")
    for i, ep in enumerate(pl.videos):
        # Classify as PODCAST explicitly (publisher-defined, not title-inferred)
        ct = classify_video(ep.title or "", is_podcast=True)
        print(f"    {ep.watch_url}  type={ct}")
        if i >= 2:
            break
    print()
