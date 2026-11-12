# Use from an arrkit app

tutubo registers itself with apps built on arrkit as an indexer and as a download client, both named `tutubo`. Install tutubo and yt-dlp next to the app and enable the plugin in the app's settings:

```bash
pip install tutubo yt-dlp
```

The app lists the plugin and builds instances from its settings pages.

## No dependency on arrkit

tutubo does not require arrkit, and `import tutubo` or `import tutubo.arr` never imports it. arrkit accepts a plugin only when its class derives from arrkit's own base class, so the entry points `tutubo.arr:Tutubo` and `tutubo.arr:TutuboClient` name classes that are built the first time the app reads them, with arrkit's `Indexer` and `Direct` as bases. Reading either name in a program without arrkit raises `AttributeError`, so `hasattr(tutubo.arr, "Tutubo")` is false there. The search, matching and download logic lives in `IndexerPlugin` and `ClientPlugin` in the same module and does not need arrkit.

## The indexer

`search(query)` is built for a music library. A query with `artist` and `album` (`title` counts as the album when `album` is missing) searches YouTube Music albums and keeps those whose name holds the album's words and whose artist holds the artist's. Accents and case do not matter. A query with `track`, or only a `term`, searches songs and keeps the ones whose title and artist match.

| Setting | Default | Meaning |
|---|---|---|
| `source` | `music` | `music` (YouTube Music), `youtube` (YouTube search; "Artist - Topic" channels give the artist) or `both` |
| `delay` | 3 | seconds between requests, across the whole process |
| `max_results` | 20 | releases per answer |
| `resolve` | 3 | albums whose track list is read (one request each) |
| `delivery` | `download` | `download`, or `stream` for releases an app plays |
| `ip_family` | `ipv4` | `ipv4`, `ipv6` or `any` |
| `media_archivist_url` | empty | a media-archivist server whose pause is honoured; optional |

An album release carries `release_type` "album", `artist`, `album`, `year`, `browse_id`, `playlist_id`, `tracks` (video id, title, track number, seconds) and `track_count`. A track release carries `release_type` "track", `artist`, `album`, `track`, `track_number`, `year`, `video_id`, `explicit` and `audio_only`. `audio_only` and `topic` are true for the auto-generated "Official Audio" uploads of an artist, which come with the album, track number and year. Every release has `duration_seconds`, `seconds`, `channel`, `thumbnail`, `tags` and `protocol` "youtube". `rss()` returns nothing: tutubo follows no feed.

`test()` makes no request. It reports a running pause and a missing ytmusicapi.

## The download client

`add(release)` queues a job in a state file of the app (one file per instance). The worker takes one job at a time. An album job runs yt-dlp once per track; a track job runs it once. Each run extracts the audio only and keeps the original codec unless `audio_format` names another.

Files land in `<download_dir>/<release title>-<job id>/`, named `<NN> - <title>.<ext>` for an album and `<title>.<ext>` for a track, cut to 200 bytes of UTF-8 so yt-dlp's temporary suffixes still fit in 255. yt-dlp writes into a hidden staging folder first; the staging folder is removed when the job ends, fails or is cancelled, so no partial file stays. The files of a finished job are listed in `status()` under `files`. A track that fails stops the job, which says how many tracks were downloaded; the finished files stay.

With `embed` on (the default), yt-dlp embeds the tags and the cover (`--embed-metadata`, `--embed-thumbnail`, which need ffmpeg), and the artist, album, title, track number and year the indexer knew are written over what the upload carried.

| Setting | Default | Meaning |
|---|---|---|
| `download_dir` | | where jobs write |
| `delay` | 3 | seconds between yt-dlp runs |
| `ip_family` | `ipv4` | passed to yt-dlp as `--force-ipv4` or `--force-ipv6` |
| `audio_format` | `best` | `best`, `m4a`, `mp3`, `opus`, `flac` |
| `embed` | `true` | embed tags and cover |
| `yt_dlp` | `yt-dlp` | the program |
| `media_archivist_url` | empty | a media-archivist server whose pause is honoured; optional |

## One pause for everything

YouTube answers too many requests with a bot check. tutubo then stops asking, and it stops for every program on the machine that uses it, not only the one that was challenged. [Back-off](backoff.md) describes the shared file. The plugin reads it before each request, writes it when yt-dlp or a search is refused, and with `media_archivist_url` set also reads `GET /api/v1/youtube/backoff` of that server. While a pause runs, searches fail with "YouTube is asking for a check: search requests paused until ..." and the download queue waits; its jobs show the same message. The plugin never tries to get past a check.
