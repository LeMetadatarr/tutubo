# tutubo

A YouTube and YouTube Music metadata library. It searches videos, channels, playlists, music tracks, albums, and artists. It classifies each item by content type and iterates channel tabs lazily. tutubo has no pytube dependency.

## Install

```bash
pip install tutubo
# Downloading requires yt-dlp (optional):
pip install yt-dlp
# Stealth transport: browser-fingerprinted TLS via curl_cffi (optional)
pip install tutubo[stealth]
```

## 30-second quickstart

```python
from tutubo import YoutubeSearch

# Search and classify
for v in YoutubeSearch("rob zombie").iterate_videos(max_res=5):
    print(v.title, v.length, v.published_time)
    print("  content_type:", v.content_type)
    print("  badges:", v.badges)

# Intent-focused factory: appends "full movie" to the query
for v in YoutubeSearch.for_movies("blade runner").iterate_movies(max_res=3):
    print(v.title, v.length)
```

## High-level shape

| Class | What it gives you |
|---|---|
| `YoutubeSearch` | Searches youtube.com. Yields `VideoPreview`, `ChannelPreview`, `PlaylistPreview`, mixes, related queries |
| `YoutubeMusicSearch` | Searches music.youtube.com. Yields `MusicTrack`, `MusicAlbum`, `MusicArtist`, `MusicPlaylist`, `MusicVideo` |
| `Channel` | Fetches a channel page. Exposes `.videos`, `.shorts`, `.streams`, `.live`, `.playlists`, `.podcasts` |
| `Playlist` | Fetches a playlist page. Exposes `.videos` (lazy-paginated generator) |
| `Category` | Single search facet (`.content_type` on a video) collapsed from mediavocab's multi-axis `ClassificationResult`. `ContentType` is a back-compat alias |

## Key invariants

- A `Video` from a channel tab has `view_count` as a human string (e.g. `"31K views"`) and `published_time` as a relative string (e.g. `"5 hours ago"`). It has **no `length` field** because duration is not available from channel-page renderers.
- A `VideoPreview` from a search result has `length` as seconds (int) and `view_count` as an exact integer.
- `MusicAlbum` is a subclass of `MusicPlaylist`. Both expose `.tracks` as a `list[MusicTrack]`, `.track_count`, `.year`, and `.playlist_url`.
- `Channel.live` fetches `/@handle/live` (a watch-page redirect) and returns **one `Video` or `None`**, the stream that is currently on air.
- `Channel.streams` fetches `/@handle/streams` (a browse tab) and returns a lazy list of **all** livestream videos (past and current).
- `VideoPreview.content_type` does not use channel tags, because search results do not include them. `Video.content_type` (from `Channel.videos`) does use channel tags, and this gives better accuracy for ambiguous titles.

## Factory classmethods: 24 intent-focused search shortcuts

Every factory appends a keyword phrase to improve YouTube's ranking. Pair each factory with the matching typed iterator for content-type enforcement:

```python
from tutubo import YoutubeSearch

for v in YoutubeSearch.for_concerts("black sabbath").iterate_concerts(max_res=5):
    print(v.title, v.length)

for v in YoutubeSearch.for_podcasts("lex fridman").iterate_podcasts():
    print(v.title)
```

All 24 factories: `for_movies`, `for_short_films`, `for_trailers`, `for_documentaries`, `for_behind_the_scenes`, `for_anime`, `for_tv_episodes`, `for_audiobooks`, `for_audio_dramas`, `for_podcasts`, `for_stand_up`, `for_interviews`, `for_lectures`, `for_concerts`, `for_news`, `for_live_news`, `for_sport`, `for_gaming`, `for_tutorials`, `for_reactions`, `for_compilations`, `for_kids`, `for_music_videos`, `for_music_audio`. See [docs/search.md](docs/search.md).

## YouTube Music search

`YoutubeMusicSearch` is a separate class from `YoutubeSearch`. It queries the YouTube Music API and returns structured music objects:

```python
from tutubo import YoutubeMusicSearch

s = YoutubeMusicSearch("black sabbath paranoid")

for track in s.iterate_tracks(max_res=5):
    print(track.title, track.artist, track.length)
    print("  audio_only:", track.is_audio_only, "| music_video:", track.is_music_video)

for album in s.iterate_albums(max_res=3):
    print(album.title, album.artist, album.year, f"({album.track_count} tracks)")
    for t in album.tracks:
        print(f"  {t.track_number}. {t.title} [{t.length}s]")

for artist in s.iterate_artists(max_res=2):
    print(artist.name, artist.subscribers)
```

## Channel metadata and tab iteration

```python
from tutubo import Channel

c = Channel("https://www.youtube.com/@Metallica")
print(c.channel_name, c.subscribers, c.video_count_label)
print("keywords:", c.keywords[:5])
print("rss:", c.rss_url)

# Regular uploads
for video in c.videos:
    print(video.title, video.view_count, video.published_time)
    print("  content_type:", video.content_type)

# Currently on-air stream: one Video or None (reads /@handle/live)
live = c.live
if live:
    print("LIVE:", live.title, live.watch_url)

# Full stream archive: paginated list from /@handle/streams
for stream in c.streams:
    print(stream.title, stream.is_live)

# Podcast shows
c2 = Channel("https://www.youtube.com/@TheDissenterRL")
for pod in c2.podcasts:
    print(pod.title, pod.episode_count)
    pl = pod.get()
    for ep in pl.videos:
        print("  episode:", ep.watch_url)
        break
```

## mediavocab integration

mediavocab is a hard runtime dependency. It provides `classify_video()` (which returns a multi-axis `ClassificationResult`), `parse_title()`, `extract_tags()`, and the `Work` / `Release` / `Entity` data model. tutubo adds the `Category` search facet and the `classify_category()` collapse.

```python
# Classifiers re-exported from tutubo for convenience
from tutubo import Category, classify_category, classify_video, parse_title, extract_tags

# Convert a search result to typed mediavocab objects
from tutubo import YoutubeSearch

for v in YoutubeSearch.for_movies("nosferatu").iterate_movies(max_res=3):
    work = v.to_work()       # mediavocab.Work
    release = v.to_release() # mediavocab.Release
    print(work.title, work.year, work.media_type)
    print(release.resolution, release.accessibility)
    print(release.external_ids)   # {"youtube": "<video_id>"}
```

Badge to resolution mapping: `"4K"` maps to `"2160p"`, `"8K"` maps to `"4320p"`, `"HD"` maps to `"1080p"`. A CC badge maps to `AccessibilityTrack(kind="captions")`. See [docs/mediavocab.md](docs/mediavocab.md).

## Pluggable session and `TUTUBO_TRANSPORT`

tutubo fetches channel and playlist HTML pages through a pluggable session (`requests.Session` by default). Set `TUTUBO_TRANSPORT=curl_cffi` to use browser-fingerprinted TLS:

```bash
export TUTUBO_TRANSPORT=curl_cffi   # requires: pip install tutubo[stealth]
```

Or inject a session object directly:

```python
from curl_cffi import requests as cffi_requests
from tutubo.channel import Channel

ch = Channel("https://www.youtube.com/@LinusTechTips",
             session=cffi_requests.Session(impersonate="chrome"))
```

**Note:** `tutubo._innertube._post` (the search path) uses stdlib `urllib.request` and ignores the transport setting. See [docs/transport.md](docs/transport.md).

## Configuration

| Env var | Effect |
|---|---|
| `TUTUBO_TRANSPORT` | Set to `curl_cffi` to enable stealth transport for channel/playlist fetches |
| `MEDIAVOCAB_LANG` | Default language for classification (e.g. `es-es`, `fr-fr`). Default is `en-us` |

## Examples

| File | What it shows |
|---|---|
| `examples/01_quickstart.py` | Search, result types, content_type, dict interface |
| `examples/02_search_factories.py` | 24 intent-focused factory methods + typed iterators |
| `examples/03_channel.py` | Channel metadata, videos tab, `Channel.live` vs `Channel.streams` |
| `examples/04_playlist.py` | Channel playlists and direct playlist iteration |
| `examples/05_podcasts.py` | Podcast shows, episode listing, `is_podcast=True` classification |
| `examples/06_music_search.py` | `YoutubeMusicSearch`: tracks, artists, community playlists |
| `examples/07_music_album.py` | `MusicAlbum` with full track listing |
| `examples/08_fanedits.py` | Fan-edit detection via `parse_title()` + `VariantKind.FANEDIT` |
| `examples/09_to_mediavocab.py` | All mediavocab fields from `to_work()` / `to_release()` |
| `examples/10_custom_session.py` | Pluggable session, `TUTUBO_TRANSPORT`, `curl_cffi` injection |
| `examples/11_pipeline.py` | Full `parse_title` → `classify_video` → `Signals` pipeline |

## Documentation

- [docs/index.md](docs/index.md): class index and overview
- [docs/search.md](docs/search.md): `YoutubeSearch`, 24 factories, `YoutubeMusicSearch`
- [docs/channel.md](docs/channel.md): `Channel`, `Playlist`, `Video`, `PodcastPreview`
- [docs/models.md](docs/models.md): all model types with typed field reference
- [docs/content_type.md](docs/content_type.md): `Category` facets and the `classify_category` collapse
- [docs/mediavocab.md](docs/mediavocab.md): `to_work()` / `to_release()` bridge
- [docs/transport.md](docs/transport.md): pluggable session and stealth transport
- [docs/locale.md](docs/locale.md): locale system and supported languages
- [docs/downloading.md](docs/downloading.md): `download()` and `download_playlist()`
- [docs/testing.md](docs/testing.md): fixture-based offline testing

## Related projects

- [mediavocab](https://github.com/TigreGotico/mediavocab): the classification and data model (`Work`, `Release`, `Entity`, `classify_video`) tutubo builds on
- [unblock_requests](https://github.com/LeMetadatarr/unblock_requests): Cloudflare-bypassing `requests.Session` subclass, used by tutubo's `stealth` extra
- [media-archivist](https://github.com/LeMetadatarr/media-archivist): indexes and deduplicates catalogues (including YouTube, via tutubo) into a typed mediavocab dataset
- [py_bandcamp](https://github.com/LeMetadatarr/py_bandcamp), [nuvem_de_som](https://github.com/LeMetadatarr/nuvem_de_som), [tunein](https://github.com/LeMetadatarr/tunein), [audiobooker](https://github.com/LeMetadatarr/audiobooker): sibling scraper clients that emit the same typed mediavocab `Release` objects for other sources

## License

Apache 2.0
