# Models

All model types come directly from search and channel iteration. tutubo needs no additional page fetches unless you call `.get()`. Preview types wrap raw YouTube renderer dicts. `.get()` hydrates a full object at the cost of one network request.

---

## VideoPreview

`tutubo/models.py:192`

Returned by `iterate_videos()`, `iterate_related_videos()`, and `search_yt()`. Wraps a `videoRenderer` dict from the YouTube search API.

```python
v.video_id               # str: 11-character YouTube video ID
v.watch_url              # str: https://www.youtube.com/watch?v={video_id}
v.title                  # str: full video title
v.author                 # str: channel display name
v.channel_url            # str: channel page URL (handle or /channel/UC...)
v.channel_thumbnail_url  # str: channel avatar, available directly from search results
# Timing and engagement
v.length                 # int: duration in seconds, 0 for live streams
v.published_time         # str: relative label, e.g. "2 years ago", empty for live streams
v.view_count             # int: exact view count as an integer, 0 if unavailable
v.short_view_count       # str: abbreviated label, e.g. "272M views"
# Thumbnails
v.thumbnail_url          # str: standard YouTube thumbnail (img.youtube.com, default.jpg size)
# Badges and signals
v.is_live                # bool: True when the result has a "Live" badge or length == 0
v.is_upcoming            # bool: True when the result has an "Upcoming" or "Premiere" badge
v.has_captions           # bool: True when a CC badge is present
v.is_verified_channel    # bool: channel has a standard verification badge
v.is_official_artist_channel  # bool: channel has BADGE_STYLE_TYPE_VERIFIED_ARTIST
v.badges                 # list[str]: all badge label strings, e.g. ['CC', '4K', 'Live']
v.description_snippet    # str: short excerpt returned by search, empty if absent
v.keywords               # list[str]: always [] (search API does not return per-video keywords)
# Classification
v.content_type           # ContentType: inferred from title, length, is_live, is_upcoming,
                         #               is_official_artist, and description_snippet
v.tags                   # list[str]: freeform labels from extract_tags() covering genre,
                         #             era, format subtype, audience, etc.
v.get()                  # returns a Video object (channel layer, triggers a network fetch)
v.as_dict                # full dict of all fields above
```

`as_dict` keys: `videoId`, `title`, `author`, `channel_url`, `channel_thumbnail`, `url`, `image`, `length`, `published`, `views`, `short_views`, `badges`, `has_captions`, `is_live`, `is_upcoming`, `is_official_artist`, `is_verified`, `description`, `content_type`, `tags`.

### `VideoPreview` vs `Video`

| | `VideoPreview` | `Video` |
|---|---|---|
| Source | YouTube search result | Channel tab (videos, shorts, streams) |
| `length` | int in seconds (from `lengthText`) | not present |
| `view_count` | int (exact) | str (human label, e.g. "31K views") |
| `published_time` | relative string | relative string |
| `channel_tags` | always `[]` | list from `Channel.keywords` |
| `is_live` | from badge | from badge in channel renderer |
| `description` | `description_snippet` (search excerpt) | description snippet from channel page |
| `content_type` | no `channel_tags`, uses `is_official_artist` | uses `channel_tags` for context |

`VideoPreview.content_type` is less accurate than `Video.content_type` for ambiguous titles, because it has no access to channel keyword context. Use `Video` (through `Channel.videos`) when you need channel-boosted classification.

### `RelatedVideoPreview`

`tutubo/models.py:437`

Identical to `VideoPreview`. Returned by `iterate_related_videos()` from "shelf" cards in search results. Shares all fields and `as_dict`.

---

## ChannelPreview

`tutubo/models.py:109`

Returned by `iterate_channels()`. Wraps a `channelRenderer` dict.

```python
ch.title              # str: display name
ch.channel_id         # str: UC... internal ID
ch.channel_url        # str: https://www.youtube.com/channel/{channel_id}
ch.description        # str: about snippet from the search result
ch.subscriber_count   # str: label, e.g. "1.28M subscribers"
ch.video_count        # int: count parsed from subscriber_count text (see note below)
ch.thumbnail_url      # str: channel avatar (highest resolution in thumbnails list)
ch.is_verified        # bool: has a VERIFIED or VERIFIED_ARTIST badge
ch.get()              # returns a full Channel object (network fetch)
ch.as_dict            # {channelId, title, image, url, description, verified}
```

**Note on `video_count`:** tutubo parses this field from `subscriber_count` text by stripping non-digit characters. This is a quirk of the underlying `videoCountText` renderer field name: that field actually holds the subscriber count label, not a video count. Use `ch.subscriber_count` (the raw string) for display. `ch.video_count` gives you an integer for comparison but carries a confusing name.

`ch.channel_url` always uses the `/channel/UC…` format, regardless of whether the channel has a handle. Call `ch.get()` to get a `Channel` object whose `vanity_url` property returns the handle form.

---

## PlaylistPreview

`tutubo/models.py:28`

Returned by `iterate_playlists()`. Wraps a `playlistRenderer` dict.

```python
pl.title              # str
pl.playlist_id        # str
pl.playlist_url       # str: https://www.youtube.com/playlist?list={playlist_id}
pl.video_count        # int: number of videos in the playlist
pl.thumbnail_url      # str: last (highest-res) thumbnail in thumbnails list
pl.featured_videos    # list of dicts: {videoId, url, image, title}
                      # Up to 3 sample videos shown in the search result card
pl.get()              # returns a Playlist object (network fetch for full video list)
pl.as_dict            # {playlistId, title, url, image, featured_videos}
```

---

## YoutubeMixPreview

`tutubo/models.py:85`

Returned by `iterate_mixes()`. Inherits from `PlaylistPreview` with a different thumbnail extraction path (reads from `thumbnail.thumbnails` rather than `thumbnails[].thumbnails[0]`). All other fields are identical to `PlaylistPreview`.

YouTube Mix previews represent auto-generated radio-style playlists. `get()` returns a `Playlist` object.

---

## RelatedSearch

`tutubo/models.py:449`

Returned by `iterate_queries()`. Represents a "People also searched for" suggestion card.

```python
rs.query              # str: the suggested search term
rs.thumbnail_url      # str: representative image for the suggestion
rs.get(preview=True)  # returns a new YoutubeSearch for this query
rs.as_dict            # {query, image}
```

`rs.get()` is a lightweight factory. It constructs a new `YoutubeSearch` without triggering any network fetch. The search only runs when you iterate its results.

```python
for q in YoutubeSearch("iron maiden").iterate_queries():
    print(q.query)
    for v in q.get().iterate_videos(max_res=3):
        print("  ", v.title)
```

---

## MusicTrack

`tutubo/ytmus.py:74`

Returned by `iterate_music_tracks()`. Represents a song from the YouTube Music catalogue.

```python
t.title               # str
t.artist               # str: comma-joined if multiple artists
t.album               # str: album name, or "" if not in an album
t.year                # int or None
t.watch_url           # str: https://music.youtube.com/watch?v=...
t.video_id            # str
t.length              # int or None: duration in seconds
t.views               # str: e.g. "682M views" (empty if unavailable)
# Content signals
t.is_explicit         # bool: explicit content flag from ytmusicapi
t.is_audio_only       # bool: True for ATV (auto-generated audio, no music video exists)
t.is_music_video      # bool: True for OMV (official music video) or UGC
t.video_type          # str: raw ytmusicapi video type string
t.category            # str: result category, e.g. "Songs", "Videos"
t.thumbnail_url       # str
t.track_number        # int or None: position within an album
t.as_dict             # {videoId, title, artist, album, year, image, url, duration,
                      #  views, explicit, audio_only, music_video, video_type}
```

### `video_type` values

| `video_type` | `is_audio_only` | `is_music_video` | Meaning |
|---|---|---|---|
| `MUSIC_VIDEO_TYPE_ATV` | `True` | `False` | Official Audio, auto-generated by YouTube, no separately produced music video exists |
| `MUSIC_VIDEO_TYPE_OFFICIAL_SOURCE_MUSIC` | `True` | `False` | Official audio from a label upload |
| `MUSIC_VIDEO_TYPE_OMV` | `False` | `True` | Official Music Video, a proper video production |
| `MUSIC_VIDEO_TYPE_UGC` | `False` | `True` | User-generated content |

`length` is `None` (not `0`) when the duration is genuinely unknown. Check `t.length is not None` before arithmetic.

---

## MusicVideo

`tutubo/ytmus.py:197`

Returned by `iterate_yt_music_videos()`. Same as `MusicTrack` except:

```python
t.watch_url           # str: https://www.youtube.com/watch?v=...  (not music.youtube.com)
t.get()               # returns a Video object from the regular YouTube channel layer
```

All other properties are identical to `MusicTrack`.

---

## MusicAlbum

`tutubo/ytmus.py:304`

Returned by `iterate_music_albums()`. Extends `MusicPlaylist` with a `label` field.

```python
a.title               # str
a.name                # str: alias for title
a.artist              # str
a.year                # int or None
a.track_count         # int: from API data or len(tracks)
a.duration_seconds    # int: total album duration, or 0 if unknown
a.is_explicit         # bool
a.label               # str: record label, or ""
a.thumbnail_url       # str
a.playlist_url        # str: https://music.youtube.com/playlist?list=...
a.tracks              # list[MusicTrack]: fully populated track listing
a.as_dict             # {title, artist, year, image, url, track_count, explicit, label,
                      #  playlist: [MusicTrack.as_dict, ...]}
```

tutubo populates `tracks` from the full album page fetched during `iterate_music_albums()`. Each `MusicTrack` in `tracks` has `track_number` set.

---

## MusicPlaylist

`tutubo/ytmus.py:214`

Returned by `iterate_music_playlists()`. Community or editorial playlists.

```python
p.title               # str
p.artist              # str: curator or creator
p.year                # int or None
p.track_count         # int
p.duration_seconds    # int: total duration, or 0
p.is_explicit         # bool
p.thumbnail_url       # str
p.playlist_url        # str: https://music.youtube.com/playlist?list=...
p.tracks              # list[MusicTrack]
p.as_dict             # {title, artist, year, image, url, track_count, explicit,
                      #  playlist: [...]}
```

---

## MusicArtist

`tutubo/ytmus.py:323`

Returned by `iterate_music_artists()`.

```python
a.name                # str: artist name (prefers "artist" key over "title")
a.artist              # str: alias for name
a.subscribers         # str: e.g. "1.2M subscribers" (falls back to "views" field)
a.description         # str: artist biography, or ""
a.thumbnail_url       # str
a.tracks              # list[MusicTrack]: top tracks from the artist page
a.as_dict             # {artist, image, subscribers, description,
                      #  playlist: [MusicTrack.as_dict, ...]}
```

`tracks` comes from the artist's top-songs section, not the full discography. Expect 5 to 10 tracks.

---

## ContentType / classify_video

`Category` (aliased as `ContentType`): `tutubo/classification.py`
`classify_video`: `mediavocab.text.classify_video` (mediavocab package)

`VideoPreview` and `Video` both expose a `.content_type` computed property. It calls mediavocab's `classify_video()`, which returns a multi-axis `ClassificationResult` (`media_type`, `content_form`, `programme_format`, `content_genres`), then collapses that result to a single tutubo `Category` facet through `classify_category()`.

```python
from tutubo import Category, classify_category, classify_video

result = classify_video(title="My Documentary Film", length=5400)
classify_category(result)  # Category.DOCUMENTARY
```

`Category` is a `str` subclass, so values compare equal to their string form (`Category.DOCUMENTARY == "documentary"`). `ContentType` is a back-compat alias for `Category`.

See [docs/content_type.md](content_type.md) for the full list of `Category` facets and how the collapse works.

---

## Content differentiation summary

tutubo exposes enough metadata to distinguish between closely related content types without additional page fetches:

| Goal | How to detect |
|---|---|
| Official music video vs audio-only | `MusicTrack.is_music_video` vs `MusicTrack.is_audio_only`, or `video_type` |
| YouTube Music track vs YouTube video | `MusicTrack.watch_url` contains `music.youtube.com`, `MusicVideo.watch_url` contains `youtube.com` |
| Currently live vs archived stream | `Video.is_live` from `Channel.live` |
| Upcoming premiere | `VideoPreview.is_upcoming` |
| Closed captions available | `VideoPreview.has_captions` |
| Official Artist Channel | `VideoPreview.is_official_artist_channel` |
| YouTube Shorts (Reels) | From `Channel.shorts` tab iteration |
| Podcast shows | From `Channel.podcasts` as `PodcastPreview` objects |

---
[← Channel](channel.md) · [Home](index.md) · [Content classification →](content_type.md)
