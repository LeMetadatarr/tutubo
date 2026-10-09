# tutubo

A YouTube and YouTube Music metadata library. It searches videos, music tracks, albums, artists, podcasts, and channels, and returns rich per-item metadata with content-type classification. tutubo has no pytube dependency.

## Overview

tutubo queries YouTube and YouTube Music search endpoints and channel pages, and returns typed Python objects. All metadata comes from search results or channel tabs. tutubo fetches a video's own page only when you call `.get()`.

## Key classes

| Class | Purpose | Source |
|---|---|---|
| `YoutubeSearch` | Search YouTube by query, yield typed results | `tutubo/search.py:37` |
| `VideoPreview` | Video result from a YouTube search | `tutubo/models.py:192` |
| `ChannelPreview` | Channel result from a YouTube search | `tutubo/models.py:109` |
| `PlaylistPreview` | Playlist result from a YouTube search | `tutubo/models.py:28` |
| `MusicTrack` | Track result from YouTube Music search | `tutubo/ytmus.py` |
| `MusicAlbum` | Album result from YouTube Music search | `tutubo/ytmus.py` |
| `MusicArtist` | Artist result from YouTube Music search | `tutubo/ytmus.py` |
| `Channel` | Full channel object with tab iteration | `tutubo/channel.py` |
| `Playlist` | Playlist object with video iteration | `tutubo/channel.py` |
| `Video` | Video stub from a channel tab | `tutubo/channel.py` |
| `PodcastPreview` | Podcast show card from channel podcasts tab | `tutubo/channel.py` |
| `YoutubeMusicSearch` | Search YouTube Music catalogue, yield music entities | `tutubo/search.py:416` |
| `Category` (alias `ContentType`) | Single search-facet enum, collapsed from mediavocab's classification | `tutubo/classification.py` |
| `classify_video` | Multi-axis `ClassificationResult` from metadata | `mediavocab.text.classify_video` |

## Contents

- [Installation and quick start](../README.md)
- [Search API](search.md): `YoutubeSearch`, 24 factories, `YoutubeMusicSearch`
- [Models reference](models.md): all preview types, `Video`, `MusicTrack`, `MusicAlbum`, and more
- [Channel API](channel.md): `Channel`, `Playlist`, `PodcastPreview`, `Video`
- [Content classification](content_type.md): `Category` facets and the `classify_category` collapse
- [mediavocab integration](mediavocab.md): the `to_work()` / `to_release()` / `to_entity()` bridge
- [Transport](transport.md): pluggable session, `curl_cffi` stealth extra, `TUTUBO_TRANSPORT`
- [Locale system](locale.md): `.voc` files, the `lang=` parameter, `MEDIAVOCAB_LANG`
- [Downloading](downloading.md): `download()` and `download_playlist()` via yt-dlp
- [Testing](testing.md): fixture-based offline test suite
