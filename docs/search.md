# Search API

`YoutubeSearch` — `tutubo/search.py:37`

`YoutubeSearch` searches both YouTube and YouTube Music, and returns typed Python objects. It handles pagination automatically through continuation tokens. It fetches each page of results lazily as you consume the iterator.

---

## Constructing a search

```python
from tutubo import YoutubeSearch

s = YoutubeSearch("rob zombie")
```

Constructor parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | required | The search query string sent to YouTube |
| `preview` | `bool` | `True` | When `True`, yields lightweight preview objects. When `False`, calls `.get()` on each item, producing full `Video`/`Channel` objects at the cost of one extra network request per item |
| `thumbnail_url` | `str` | `""` | Optional thumbnail URL to associate with the search itself. It is exposed through `as_dict` for UIs that display search history |

`YoutubeSearch` caches the raw innertube response in `_initial_results` after the first call, so repeated iteration of the same page does not re-fetch it.

---

## Factory classmethods

Every factory appends a fixed keyword phrase to the caller's query string, then returns a `YoutubeSearch` for the enriched query. This pushes YouTube's ranking algorithm toward the wanted content type. The factory itself does no filtering. Use the paired typed `iterate_*` method when you also want content-type enforcement on the results.

`for_music` is an alias for `for_music_videos`.

| Factory | Enriched query | Paired typed iterator |
|---|---|---|
| `for_movies(query)` | `"{query} full movie"` | `iterate_movies()` |
| `for_short_films(query)` | `"{query} short film"` | `iterate_short_films()` |
| `for_trailers(query)` | `"{query} official trailer"` | `iterate_trailers()` |
| `for_documentaries(query)` | `"{query} documentary"` | `iterate_documentaries()` |
| `for_behind_the_scenes(query)` | `"{query} behind the scenes"` | `iterate_behind_the_scenes()` |
| `for_anime(query)` | `"{query} anime"` | `iterate_anime()` |
| `for_tv_episodes(query)` | `"{query} full episode"` | `iterate_tv_episodes()` |
| `for_audiobooks(query)` | `"{query} full audiobook"` | `iterate_audiobooks()` |
| `for_audio_dramas(query)` | `"{query} audio drama"` | `iterate_audio_dramas()`, yields AUDIOBOOK results |
| `for_podcasts(query)` | `"{query} podcast"` | `iterate_podcasts()` |
| `for_stand_up(query)` | `"{query} stand up comedy special"` | `iterate_stand_up()` |
| `for_interviews(query)` | `"{query} interview"` | `iterate_interviews()` |
| `for_lectures(query)` | `"{query} lecture"` | `iterate_lectures()` |
| `for_concerts(query)` | `"{query} full concert"` | `iterate_concerts()` |
| `for_news(query)` | `"{query} news"` | `iterate_news()` |
| `for_live_news(query)` | `"{query} live news"` | `iterate_live_news()` |
| `for_sport(query)` | `"{query} full match"` | `iterate_sport()` |
| `for_gaming(query)` | `"{query} gameplay"` | `iterate_gaming()` |
| `for_tutorials(query)` | `"{query} tutorial"` | `iterate_tutorials()` |
| `for_reactions(query)` | `"{query} reaction"` | `iterate_reactions()` |
| `for_compilations(query)` | `"{query} compilation"` | `iterate_compilations()` |
| `for_kids(query)` | `"{query} for kids"` | `iterate_kids()` |
| `for_music_videos(query)` | `"{query} official music video"` | `iterate_music_videos()` |
| `for_music_audio(query)` | `"{query} official audio"` | `iterate_music_audio()` |

**Example: factory plus typed iterator**

```python
from tutubo import YoutubeSearch

# Search "blade runner full movie", then filter results to MOVIE content type
for v in YoutubeSearch.for_movies("blade runner").iterate_movies(max_res=5):
    print(v.title, v.length)      # length is seconds

# Search "black sabbath full concert", filter to CONCERT
for v in YoutubeSearch.for_concerts("black sabbath").iterate_concerts():
    print(v.title)

# For maximum recall, always use factory + typed iterator together.
# Using iterate_movies() on a plain YoutubeSearch("blade runner") works but
# returns fewer hits because YouTube surfaces more non-movie results.
```

---

## Core iteration

### `iterate_youtube(max_res=-1, search_type=SearchType.YOUTUBE)`

`tutubo/search.py:182`

A low-level iterator that yields all result types mixed together: `VideoPreview`, `ChannelPreview`, `PlaylistPreview`, `YoutubeMixPreview`, `RelatedVideoPreview`, `RelatedSearch`. Pass `max_res` to stop after N items (counting from 1; the iterator stops as soon as it would yield item N+1).

```python
from tutubo import YoutubeSearch
from tutubo.search import SearchType

s = YoutubeSearch("lofi hip hop")
for item in s.iterate_youtube(max_res=20, search_type=SearchType.VIDEOS):
    print(type(item).__name__, item.title)
```

Passing `SearchType.VIDEOS` tells the parser to skip non-video renderers entirely, which avoids constructing unwanted objects. For most use cases, prefer the typed wrappers below.

### `iterate_videos(max_res=-1)`

`tutubo/search.py:281`

Yields only `VideoPreview` (and `Video` when `preview=False`). This is the most commonly used iterator. Results include all video types. Use `v.content_type` or `iterate_by_content_type()` to narrow further.

```python
for v in YoutubeSearch("python tutorials").iterate_videos(max_res=20):
    print(v.title, v.length, v.view_count)
    print("  type:", v.content_type)
    print("  cc:", v.has_captions)
    print("  badges:", v.badges)
```

### `iterate_related_videos(max_res=-1)`

`tutubo/search.py:287`

Yields `RelatedVideoPreview` objects from "shelf" cards that YouTube occasionally inserts alongside main results. These are algorithmically related video recommendations. They share all fields with `VideoPreview`.

### `iterate_channels(max_res=-1)`

`tutubo/search.py:293`

Yields `ChannelPreview` objects.

```python
for ch in YoutubeSearch("metallica").iterate_channels():
    print(ch.title, ch.subscriber_count, "verified:", ch.is_verified)
    full = ch.get()   # hydrates to a Channel; triggers a network fetch
```

### `iterate_playlists(max_res=-1)`

`tutubo/search.py:299`

Yields `PlaylistPreview` objects.

```python
for pl in YoutubeSearch("lofi beats").iterate_playlists():
    print(pl.title, pl.video_count)
    full = pl.get()   # hydrates to a Playlist
```

### `iterate_mixes(max_res=-1)`

`tutubo/search.py:305`

Yields `YoutubeMixPreview` objects, YouTube's auto-generated radio-style playlists (the "radio" or "mix" cards in search results). `YoutubeMixPreview` inherits from `PlaylistPreview` and exposes the same fields.

### `iterate_queries(max_res=-1)`

`tutubo/search.py:311`

Yields `RelatedSearch` objects from "People also searched for" horizontal card rows.

```python
for q in YoutubeSearch("iron maiden").iterate_queries():
    print(q.query)
    # Pivot to a related search
    new_search = q.get()
    for v in new_search.iterate_videos(max_res=3):
        print("  ", v.title)
```

---

## SearchType enum

`SearchType` — `tutubo/search.py:24`

`SearchType` is an `IntEnum`. Pass it to `iterate_youtube()` to restrict which renderer types are parsed. This is a parse-time filter, not a network filter. It does not change what YouTube returns, only which objects tutubo creates from the response.

| Value | What it lets through |
|---|---|
| `SearchType.YOUTUBE` | All YouTube result types (default for `iterate_youtube`) |
| `SearchType.VIDEOS` | `VideoPreview` only |
| `SearchType.RELATED_VIDEOS` | `RelatedVideoPreview` only |
| `SearchType.CHANNELS` | `ChannelPreview` only |
| `SearchType.PLAYLISTS` | `PlaylistPreview` only |
| `SearchType.YOUTUBE_MIX` | `YoutubeMixPreview` only |
| `SearchType.RELATED_QUERIES` | `RelatedSearch` only |
| `SearchType.ALL` | All YouTube result types mixed |

`SearchType` applies only to `YoutubeSearch.iterate_youtube()`. It is a parse-time filter on the YouTube search response and does not affect `YoutubeMusicSearch`.

---

## Content-type filtered iterators

### `iterate_by_content_type(content_type, max_res=-1)`

`tutubo/search.py:321`

Iterates the full video result stream and yields only `VideoPreview` objects whose `.content_type` property matches the given `ContentType` enum value. Classification runs entirely in-process on data already fetched, so it needs no extra network calls.

Because `iterate_by_content_type()` consumes from `iterate_videos()` without a query-side filter, it may need to page through many results before it finds enough matches. For best precision, combine a factory with the typed iterator:

```python
from tutubo import YoutubeSearch
from tutubo import ContentType

# Factory biases YouTube's ranking; typed iterator enforces classification
for v in YoutubeSearch.for_documentaries("nature ocean").iterate_documentaries(max_res=10):
    print(v.title)

# Direct content-type filter on any search
s = YoutubeSearch("free movies")
for v in s.iterate_by_content_type(ContentType.MOVIE, max_res=10):
    print(v.title, v.length)
```

The typed convenience methods below are all thin wrappers around `iterate_by_content_type()`:

| Method | `ContentType` filtered | Notes |
|---|---|---|
| `iterate_movies(max_res=-1)` | `MOVIE` | Title must contain "full movie/film" or the channel is a movie channel. Duration must be at least 3600 s if known |
| `iterate_short_films(max_res=-1)` | `SHORT_FILM` | Title has "short film/movie" or a short-film channel tag. Duration under 3600 s if known |
| `iterate_trailers(max_res=-1)` | `TRAILER` | Title matches "trailer" or "teaser". Duration at most 600 s if known |
| `iterate_documentaries(max_res=-1)` | `DOCUMENTARY` | Title or description matches "documentary/docu*", or the channel carries a doc/nature/history tag |
| `iterate_behind_the_scenes(max_res=-1)` | `BEHIND_THE_SCENES` | |
| `iterate_anime(max_res=-1)` | `ANIME` | |
| `iterate_tv_episodes(max_res=-1)` | `TV_EPISODE` | |
| `iterate_audiobooks(max_res=-1)` | `AUDIOBOOK` | |
| `iterate_audio_dramas(max_res=-1)` | `AUDIOBOOK` | Filters for `AUDIOBOOK` (full-cast productions classify as audiobook) |
| `iterate_podcasts(max_res=-1)` | `PODCAST` | Classification requires `is_podcast=True`. Title keywords alone never produce PODCAST |
| `iterate_stand_up(max_res=-1)` | `STAND_UP` | |
| `iterate_interviews(max_res=-1)` | `INTERVIEW` | |
| `iterate_lectures(max_res=-1)` | `LECTURE` | |
| `iterate_concerts(max_res=-1)` | `CONCERT` | |
| `iterate_news(max_res=-1)` | `NEWS` | Recorded news. Live news is `LIVE_NEWS` |
| `iterate_live_news(max_res=-1)` | `LIVE_NEWS` | Requires `is_live=True` plus a title/tag signal |
| `iterate_live_radio(max_res=-1)` | `LIVE_RADIO` | Requires `is_live=True` plus a title signal |
| `iterate_iptv(max_res=-1)` | `IPTV` | Requires `is_live=True` plus a title signal |
| `iterate_sport(max_res=-1)` | `SPORT` | |
| `iterate_gaming(max_res=-1)` | `GAMING` | |
| `iterate_tutorials(max_res=-1)` | `TUTORIAL` | |
| `iterate_reactions(max_res=-1)` | `REACTION` | |
| `iterate_compilations(max_res=-1)` | `COMPILATION` | |
| `iterate_kids(max_res=-1)` | `KIDS` | |
| `iterate_music_videos(max_res=-1)` | `MUSIC_VIDEO` | Also fires for Official Artist Channel videos |
| `iterate_music_audio(max_res=-1)` | `MUSIC_AUDIO` | Lyric videos, visualizers, official audio |
| `iterate_social_clips(max_res=-1)` | `SOCIAL_CLIP` | Duration under 62 s. Unrelated to the Shorts tab |

**Note on `iterate_live_news`, `iterate_live_radio`, `iterate_iptv`:** These rely on `is_live=True` being set in the `VideoPreview`. In a regular YouTube search, a "Live" badge on the result identifies live streams. If no live streams appear in the first few pages, these iterators return nothing.

---

## YouTube Music search: `YoutubeMusicSearch`

`tutubo/search.py:416`

`YoutubeMusicSearch` is a **separate class** from `YoutubeSearch`. It queries the YouTube Music API through `ytmusicapi` and yields music-domain objects. `ContentType` classification does not apply to its results.

```python
from tutubo import YoutubeMusicSearch

s = YoutubeMusicSearch("black sabbath")

# Albums — each result has full track listing fetched
for album in s.iterate_albums(max_res=3):
    print(album.title, album.year, f"({album.track_count} tracks)")
    for t in album.tracks:
        print(f"  {t.track_number}. {t.title} [{t.length}s]")
        print(f"    audio_only={t.is_audio_only}  music_video={t.is_music_video}")

# Tracks
for track in s.iterate_tracks(max_res=5):
    print(track.title, track.artist, track.length)

# Artists (enriched with top-tracks)
for artist in s.iterate_artists(max_res=2):
    print(artist.name, artist.subscribers)

# All result types in API order
for obj in s.iterate_all(max_res=10):
    print(type(obj).__name__, obj.title)
```

tutubo creates the `ytmusicapi` singleton lazily on first call and caches it globally. If the initial connection fails, `_get_ytmus()` retries up to 5 times with a short exponential back-off before it returns `None`.

### `YoutubeMusicSearch` iterators

All accept `max_res=-1`. For albums, playlists, and artists, tutubo automatically fetches the full detail page (one extra API call per item). If any detail fetch fails, tutubo silently skips the item.

| Method | Result type | URL domain | Notes |
|---|---|---|---|
| `iterate_tracks(max_res=-1)` | `MusicTrack` or `MusicVideo` | `music.youtube.com` | Songs from the Music catalogue |
| `iterate_videos(max_res=-1)` | `MusicVideo` | `youtube.com` | Music videos from regular YouTube |
| `iterate_albums(max_res=-1)` | `MusicAlbum` | `music.youtube.com` | Full album and track listing fetched |
| `iterate_playlists(max_res=-1)` | `MusicPlaylist` | `music.youtube.com` | Community and editorial playlists |
| `iterate_artists(max_res=-1)` | `MusicArtist` | — | Full artist page including top tracks |
| `iterate_all(max_res=-1)` | mixed | — | All result types in API order |

`MusicTrack.watch_url` points to `music.youtube.com/watch?v=…`. `MusicVideo.watch_url` points to `youtube.com/watch?v=…`. Call `MusicVideo.get()` to get a `Video` object from the regular channel layer.

---

## Convenience functions

### `search_yt(query, as_dict=True, parse=False, max_res=50)`

`tutubo/search.py:572`

A thin wrapper over `YoutubeSearch.iterate_youtube()` that returns dicts by default.

```python
from tutubo import search_yt

for item in search_yt("lofi beats", max_res=20):
    print(item["title"], item["url"], item["published"])
    print("  content_type:", item["content_type"])
    print("  badges:", item["badges"])
```

Parameters:

| Parameter | Default | Description |
|---|---|---|
| `query` | required | Search query |
| `as_dict` | `True` | Yield `as_dict` from each result. Set to `False` to yield model objects |
| `parse` | `False` | When `True`, sets `preview=False`, so each video is fully fetched. This is slow and rarely needed |
| `max_res` | `50` | Stop after this many results |

### `search_yt_music(query, as_dict=True, n_retries=3)`

`tutubo/ytmus.py:392`

A direct YouTube Music search that yields dicts (`as_dict=True`) or model objects. Unlike `YoutubeMusicSearch`'s iterators, this function does not support `max_res`. It yields everything returned by `ytmusicapi.search()`.

```python
from tutubo import search_yt_music

for item in search_yt_music("iron maiden"):
    # item is a dict; keys vary by result type
    print(item.get("title"), item.get("artist"), item.get("audio_only"))
```

---

## Pagination and continuation

tutubo fetches the first result page on the first call to `fetch_query()`. When the iterator exhausts that page's items, `_iterate_and_parse()` automatically requests the next continuation token. YouTube returns roughly 20 items per page. To avoid unnecessary page fetches, always pass `max_res`:

```python
# Stops after 10 items — may not request a second page at all
for v in YoutubeSearch("rock classics").iterate_videos(max_res=10):
    print(v.title)
```

The continuation mechanism reads `continuationItemRenderer.continuationEndpoint.continuationCommand.token` from the response. If that key is missing (for example, only one page of results exists), pagination ends silently. If YouTube changes the response shape so tutubo cannot find the continuation token, iteration stops after the first page rather than raising an exception.

---

## `as_dict` on YoutubeSearch

```python
s = YoutubeSearch("jazz piano", thumbnail_url="https://example.com/jazz.jpg")
print(s.as_dict)
# {'query': 'jazz piano', 'image': 'https://example.com/jazz.jpg'}
```

Use this to persist search state or pass search context to a UI component.

---
[Home](index.md) · [Channel →](channel.md)
