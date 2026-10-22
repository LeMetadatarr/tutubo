# Fetching videos for a corpus

`tutubo/fetch.py`

`python -m tutubo.fetch` fetches, for each video id, what a speech corpus needs: the video's details, its caption tracks as YouTube serves them, and its original audio track in the codec YouTube stores. Nothing is re-encoded. yt-dlp must be installed in the same environment or on `PATH`; `TUTUBO_YTDLP` names another one.

```bash
python -m tutubo.fetch dQw4w9WgXcQ --dest /data/job
```

Under `--dest` it writes:

| Path | Content |
|---|---|
| `audio/<id>.<ext>` | the original audio track, `m4a` (AAC) or `webm` (Opus), as YouTube stores it |
| `captions/<id>.<lang>.<kind>.<format>` | one file per caption track and format, the bytes YouTube served |
| `meta/<id>.json` | what was fetched, written last; `complete` says whether every file is there |

A video whose `meta/<id>.json` says `complete`, was made with the same options, and names files that are all present is skipped without a request. A video with any caption file that failed (a server error, a dropped connection, an empty file, a track the watch page lists and yt-dlp did not offer) is not complete: the run reports it as an error and the next run fetches it again. A live stream that is running or has not started is not fetched; its record says why under `skipped`, with the reason the page gives, and it is fetched on a later run.

A partial audio file is resumed. When yt-dlp's information lists the exact size of the audio formats, a finished or partial file whose size no such format has is deleted and downloaded again, and a downloaded file whose size differs from its format's is deleted and reported as an error.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--kinds` | `manual,asr` | caption kinds to fetch: tracks uploaded by a person, YouTube's automatic recognition. Machine translations are never fetched |
| `--formats` | `json3,vtt` | caption formats; `json3` keeps the word timings of automatic tracks |
| `--no-audio`, `--no-captions` | | leave out the audio or the captions |
| `--gap` | `5` | seconds between requests, including the one before the audio download |
| `--family` | `ipv4` | IP family: `ipv4`, `ipv6` or `any` |

## Output and exit status

Video ids are positional. An id that starts with `-` goes after `--` (`python -m tutubo.fetch --dest /data/job -- -abcdefghij`), and a lone `-` reads whitespace-separated ids from standard input. Options are not abbreviated.

Each line on standard output is one JSON object with an `event`: `progress` (`bytes`, `total`), `done` (`meta`), `skip`, `skipped` (`reason`), `error` (`error`), `paused` (`kind`, `until`) or `terminated`. No line holds a media or caption address: errors are written without any URL, query string, signature, token, `ip=`, `Cookie:` or `Authorization:` value, in plain, JSON, escaped-JSON and percent-encoded forms. A Bearer token, a visitor id and the Google session cookies are removed too. HTML entities, fullwidth or look-alike characters and names spelled with percent escapes are not covered.

| Exit status | Meaning |
|---|---|
| 0 | every video is done or skipped |
| 1 | a video failed or is incomplete |
| 2 | bad arguments |
| 75 | YouTube asked for a bot check and the run stopped |
| 143 | the run received SIGTERM; yt-dlp and any program it started are ended first, a second SIGTERM changes nothing, and no information file is left behind; a partial audio file stays for the next run |

A bot check stops the run at once, also when yt-dlp only warns about it and exits 0: the kind is paused in the shared [back-off](backoff.md) and nothing is retried. While a kind is paused, every tutubo process on the machine refuses requests of that kind. With `TUTUBO_BACKOFF=off` nothing is paused or recorded, so a check fails that video and the run goes on with the next one.

## The sidecar

`meta/<id>.json` holds `video_id`, `title`, `channel_id`, `channel`, `duration_s`, `upload_date` and `publish_date` (the watch page's own strings, a date with time and offset when the page gives one), `live_start` for a live recording, `playability_reason` for a live stream or premiere the page does not play yet, `caption_tracks` (every track the watch page lists, translations included), `captions` (each file written, or the `error` for a track that could not be), `audio` (file, format id, `codec`, `sample_rate`, `channels`, bitrate, language, and `original`: whether it is the track in the language the video was made in), `audio_tracks_offered`, `tools` (tutubo, Python, yt-dlp, yt-dlp-ejs and deno versions), `request` (the options used), `complete`, `skipped` (for a live stream) and `fetched_at`. It holds no media or caption address.

## From code

```python
from tutubo.fetch import video_details, fetch_captions, fetch_audio

d = video_details("dQw4w9WgXcQ")          # one watch-page read
d.upload_date, d.duration_s, d.audio_tracks, d.caption_tracks
fetch_captions(d.video_id, "/data/job")    # yt-dlp finds the tracks, tutubo fetches each file
fetch_audio(d.video_id, "/data/job")       # original track, no re-encode
```

`video_details` reads the watch page once and returns the title, channel, duration, upload date, every audio track with its codec, sample rate, channels, language and whether it is the original or a dub, and every caption track with its kind. `fetch_captions` writes the tracks of the requested kinds in each format. yt-dlp supplies the addresses, and only a file served whole over HTTP counts: a track yt-dlp found in a streaming manifest is a playlist and is left out. The command line fetches only the tracks the watch page itself lists, so a track another YouTube client offers under a different label is never saved as an original. `fetch_audio` runs yt-dlp with `bestaudio` limited to the original track. Requests go through a plain `requests` session whatever `TUTUBO_TRANSPORT` says, so nothing here impersonates a browser or falls back to an archive.
