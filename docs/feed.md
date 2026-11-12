# Channel upload feed

`tutubo/feed.py`

YouTube serves the latest uploads of a channel as an Atom feed, about fifteen entries in one small response. Reading it costs one request per channel, against several for a full channel listing, so a program that keeps a channel current reads the feed first and lists the channel only when the feed holds a video it does not know.

```python
from tutubo.feed import refresh_channel

update = refresh_channel("UCxxxxxxxxxxxxxxxxxxxxxx", known_ids=seen)
for entry in update.new:                 # newest first
    entry.video_id, entry.title, entry.published, entry.views
if update.needs_listing:
    ...                                  # list the channel with tutubo.Channel
```

`channel_feed(channel_id)` returns the entries (`FeedEntry`: `video_id`, `title`, `channel_id`, `channel`, `published`, `updated`, `url`, `thumbnail`, `description`, `views`) without comparing them. The channel id must be the 24-character `UC...` form; a handle or URL is refused before any request.

The request is a `feed` request of the shared [back-off](backoff.md): it is refused with `BackedOff` while the kind is paused and a bot check pauses it. The request goes through a plain `requests` session pinned to the IP family (`ipv4` by default), so it never falls back to an archive copy or a solver. The answer is read in at most 2 MB, a failed answer in at most 64 KB, and a document that declares a DTD or entities, in any encoding, or whose root is not an Atom `feed` is refused. Any other failure raises `FeedError`, whose message holds no address.

## From a shell

```bash
python -m tutubo.feed UCxxxxxxxxxxxxxxxxxxxxxx --known dQw4w9WgXcQ
```

prints one JSON object per entry that is not in `--known` (repeatable; write `--known=ID` for an id that starts with `-`), with `event` set to `entry`. A pause prints a `paused` object and exits with status 75; an unreadable feed prints an `error` object and ends with status 1.
