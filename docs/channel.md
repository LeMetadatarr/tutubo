# Channel API

`Channel`: `tutubo/channel.py:276`

`Channel` fetches metadata and tab content from a YouTube channel page. All properties load lazily on first access and cache in-instance, so repeated reads of the same property issue no additional network requests.

---

## Constructing a Channel

`Channel` accepts any of the three common YouTube channel URL formats:

```python
from tutubo import Channel

# Handle URL (most common)
c = Channel("https://www.youtube.com/@Metallica")

# Legacy /c/ vanity URL
c = Channel("https://www.youtube.com/c/LofiGirl")

# Internal /channel/ UC… ID URL
c = Channel("https://www.youtube.com/channel/UC4BSeEq7XNtihGqI309vhYg")
```

The `channel_name()` utility in `tutubo/_utils.py:36` normalizes all three formats to a canonical URI path (`/@Handle`, `/c/name`, or `/channel/UC…`), which tutubo appends to `https://www.youtube.com`.

The optional `language` parameter controls the `Accept-Language` request header. This can affect the display language for auto-translated titles and some metadata:

```python
c = Channel("https://www.youtube.com/@RobZombieOfficial", language="pt-PT,pt;q=0.9")
```

The default is `"en-US,en;q=0.9"`.

---

## Channel metadata properties

All metadata properties read from two parsed data structures: `channelMetadataRenderer` (for IDs, keywords, RSS, vanity URL) and `pageHeaderViewModel` (for subscriber count, video count, description). Both come from `ytInitialData` embedded in the channel home page.

```python
c.channel_name        # str: display name, e.g. "Metallica"
c.channel_id          # str: UC… internal ID
c.vanity_url          # str or None: e.g. "https://www.youtube.com/@Metallica"
c.title               # str: alias for channel_name
c.channel_url         # str: canonical channel URL used internally
c.description         # str: full about text (prefers pageHeader; falls back to metadata)
c.thumbnail_url       # str: profile avatar URL (highest available resolution)
c.subscribers         # str: subscriber count label, e.g. "12.3M subscribers"
c.video_count_label   # str: video count label, e.g. "2.3K videos"
c.keywords            # list[str]: channel keyword tags (used for content classification)
c.available_countries # list[str]: ISO-3166-1 alpha-2 codes where the channel is available
c.rss_url             # str: RSS feed URL for this channel's uploads
```

`keywords` deserializes YouTube's raw keyword string, which uses shell-style quoting for multi-word tags, via `shlex.split`. A multi-word tag like `"full movie"` stays as a single list element rather than splitting on the space.

`as_dict` serializes all metadata fields:

```python
c.as_dict
# {
#   "channelId": "UC...",
#   "title": "Metallica",
#   "image": "https://...",
#   "url": "https://www.youtube.com/@Metallica",
#   "description": "...",
#   "subscribers": "12.3M subscribers",
#   "video_count": "2.3K videos",
#   "keywords": ["metallica", "metal", ...],
#   "rss_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC...",
# }
```

---

## URL shortcuts

tutubo builds these at `__init__` time from the canonical channel URL. They never trigger network fetches:

```python
c.videos_url     # str: /videos tab
c.shorts_url     # str: /shorts tab
c.streams_url    # str: /streams tab
c.playlists_url  # str: /playlists tab
c.podcasts_url   # str: /podcasts tab
```

---

## Videos tab: `channel.videos`

`tutubo/channel.py:598`

Returns a `DeferredGeneratorList` of `Video` objects from the `/videos` tab. tutubo fetches items page by page as you consume the list. YouTube returns roughly 30 items per page. tutubo resolves continuation tokens automatically.

```python
for video in c.videos:
    print(video.title, video.watch_url)
    print("  views:", video.view_count)
    print("  published:", video.published_time)
    print("  content_type:", video.content_type)
```

`DeferredGeneratorList` supports indexing and slicing:

```python
first = c.videos[0]            # fetches only the first page
recent_five = c.videos[:5]     # fetches all pages, returns first 5
all_videos = list(c.videos)    # fetches all pages
```

## Shorts tab: `channel.shorts`

`tutubo/channel.py:603`

Same interface as `videos` but reads from the `/shorts` tab. Items are `Video` objects with `is_live=False` and typically very short durations.

```python
for short in c.shorts:
    print(short.title, short.video_id)
```

## Streams tab: `channel.streams`

`tutubo/channel.py:608`

Returns a `DeferredGeneratorList` of `Video` objects from the `/@handle/streams` tab. This tab contains the channel's full stream archive: both currently active streams (`is_live=True`) and recordings of past streams (`is_live=False`).

```python
for stream in c.streams:
    if stream.is_live:
        print("ON AIR:", stream.title, stream.watch_url)
    else:
        print("archived:", stream.title, stream.published_time)
```

Archived streams appear after active ones, so you can break early to avoid fetching the full archive:

```python
for stream in c.streams:
    if not stream.is_live:
        break
    print("currently live:", stream.title, stream.watch_url)
```

## Current live stream: `channel.live`

`tutubo/channel.py:618`

Returns a single `Video` object for the stream currently on air, or `None` if the channel is offline.

This property fetches `{channel_url}/live`, YouTube's `/@handle/live` URL, which redirects to a watch page for the most recent livestream video. It is not a browse tab. tutubo reads `currentVideoEndpoint.watchEndpoint.videoId` from the page data and confirms liveness through `playerMicroformat.liveBroadcastDetails.isLiveNow`. When no stream is active, the redirect leads to a regular video or the channel home, and tutubo returns `None` in that case.

```python
live = c.live
if live:
    print("LIVE NOW:", live.title)
    print("Watch:", live.watch_url)
    print("Content type:", live.content_type)
else:
    print("Channel is offline")
```

`live` returns `None` on network errors or when tutubo cannot parse the page. It never raises. The returned `Video` has `is_live=True` and `channel_tags` populated from `c.keywords`, which enables content-type sub-classification (for example `LIVE_NEWS` for a news channel).

**`channel.streams` vs `channel.live` at a glance:**

| Property | URL fetched | Returns | Use case |
|---|---|---|---|
| `channel.streams` | `/@handle/streams` | `DeferredGeneratorList[Video]` | Browse the full stream archive |
| `channel.live` | `/@handle/live` | `Video` or `None` | Check if the channel is on air right now |

---

## Video object

`Video`: `tutubo/channel.py:36`

A lightweight object populated from channel-page renderer data. It does not represent a fully fetched video page.

```python
v.video_id        # str: 11-character YouTube video ID
v.watch_url       # str: https://www.youtube.com/watch?v={video_id}
v.title           # str or None
v.thumbnail_url   # str: falls back to maxresdefault if not set by channel page
v.is_live         # bool: True only for currently active streams
v.view_count      # str: human-formatted, e.g. "31K views" (from channel page data)
v.published_time  # str: relative label, e.g. "5 hours ago" or "3 months ago"
v.keywords        # list[str]: always [] (channel pages do not expose per-video keywords)
v.channel_tags    # list[str]: inherited from the channel's keyword list at fetch time
v.description     # str: description snippet if returned by the channel page (may be "")
v.content_type    # ContentType: classified from title, description, is_live, channel_tags
v.tags            # list[str]: freeform labels from extract_tags() covering genre,
                  #             era, format subtype, audience, etc.
v.as_dict         # dict
```

`as_dict` keys: `videoId`, `url`, `title`, `image`, `is_live`, `views`, `published`, `description`, `content_type`, `tags`.

### Content type from channel context

`Video.content_type` calls `classify_video()` with `channel_tags=self.channel_tags`. Because `channel_tags` are populated at construction time from `Channel.keywords`, even a video with a plain title can receive a specific content type when the channel itself carries strong tags.

Example: a video titled "Episode 42" on a channel tagged `["podcast", "interview"]` classifies as `ContentType.VIDEO` (no title keyword match), but a live stream on the same channel classifies as `ContentType.LIVE_NEWS` if the channel also carries a `"news"` tag.

```python
c = Channel("https://www.youtube.com/@BBCNews")
v = c.live
if v:
    print(v.title, v.content_type)
    # typical output: "BBC News Live" ContentType.LIVE_NEWS
```

---

## Playlists

`tutubo/channel.py:734`

```python
# Just the URLs, no Playlist objects constructed
c.playlist_urls   # list[str]

# Full Playlist objects, lazy
for playlist in c.playlists:
    print(playlist.title, playlist.playlist_id)
    for video in playlist.videos:
        print("  ", video.watch_url)
```

`Channel.playlists` returns a `DeferredGeneratorList` of `Playlist` objects. `Playlist.videos` is a generator that pages through the playlist using continuation tokens.

`Playlist`: `tutubo/channel.py:113`

```python
pl.playlist_id    # str
pl.playlist_url   # str: https://www.youtube.com/playlist?list=...
pl.title          # str or None
pl.video_urls     # list[str]: all video watch URLs (fetches all pages)
pl.videos         # generator of Video objects (one per video)
```

Construct a `Playlist` directly from any URL containing a `list=` parameter:

```python
from tutubo.channel import Playlist

pl = Playlist("https://www.youtube.com/playlist?list=PLSomeListId")
for v in pl.videos:
    print(v.watch_url)
```

---

## Podcasts

`tutubo/channel.py:810`

YouTube channels with a Podcasts tab expose grouped podcast shows. Each show is a `PodcastPreview` backed by a YouTube playlist of episodes.

```python
c = Channel("https://www.youtube.com/@TheDissenterRL")
for pod in c.podcasts:
    print(pod.title)
    print("  episodes:", pod.episode_count)   # e.g. "142 episodes"
    print("  updated:", pod.last_updated)      # e.g. "Updated 4 days ago"
    print("  url:", pod.playlist_url)

    # Hydrate to a Playlist for full episode iteration
    pl = pod.get()
    for ep in pl.videos:
        print("    episode:", ep.watch_url)
        break
```

`PodcastPreview`: `tutubo/channel.py:242`

```python
pod.title           # str: show title
pod.playlist_id     # str: backing playlist ID
pod.playlist_url    # str: https://www.youtube.com/playlist?list=...
pod.episode_count   # str: e.g. "142 episodes" (empty if not shown)
pod.last_updated    # str: e.g. "Updated 4 days ago" (empty if not shown)
pod.thumbnail_url   # str
pod.as_dict         # {title, playlistId, url, episodeCount, lastUpdated, image}
pod.get()           # returns a Playlist
```

`pod.episode_count` is a badge text string extracted from the podcast thumbnail overlay, not an integer. Parse it yourself if you need arithmetic:

```python
count = int(pod.episode_count.split()[0]) if pod.episode_count else 0
```

tutubo does not set the `is_podcast=True` flag automatically for episodes obtained through `Channel.podcasts`. To classify podcast episodes as `ContentType.PODCAST`, pass `is_podcast=True` explicitly when you call `classify_video()` yourself. Videos found in search results or channel `/videos` tabs are never auto-classified as PODCAST, regardless of their title.

---

## Building an M3U8 playlist from live channels

See [`examples/iptv.py`](../examples/iptv.py) for a script that iterates `Channel.live` across multiple channels and writes results to an `.m3u8` file suitable for media players.

---

## Lazy loading and caching

HTML pages are fetched at most once per tab URL per `Channel` instance. The mapping lives in `_html_cache` (URL to raw HTML text) and `_initial_data_cache` (URL to parsed `ytInitialData` dict). Constructing a second `Channel` for the same handle re-fetches everything.

Continuation POSTs, for fetching additional pages of videos or playlists, are not cached. Each scroll triggers a network call, matching YouTube's own behavior.

---
[← Search](search.md) · [Home](index.md) · [Models →](models.md)
