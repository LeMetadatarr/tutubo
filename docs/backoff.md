# Back-off

`tutubo.backoff` holds one pause per kind of request for the whole machine. YouTube challenges some kinds of request and not others, so the kinds pause apart: `details`, `listing`, `feed`, `thumb`, `search` and `download`.

The first bot check of a kind pauses it for 30 minutes. A further check after that pause has run out doubles the wait, up to 24 hours. A check that arrives while the kind is already paused leaves the pause as it is. A request that succeeds ends the pause and resets the wait. The rules and the field names of a row (`retry_at`, `wait_s`, `at`) are media-archivist's, so one server and its neighbours can share a file.

## Where tutubo checks

| Call | Kind |
|---|---|
| innertube search (`YoutubeSearch`) | `search` |
| YouTube Music search (`search_yt_music`, `YoutubeMusicSearch`) | `search` |
| channel and playlist pages and their continuations | `listing` |
| `download()`, `download_playlist()` and the arrkit client | `download` |

Before each of these tutubo reads the file and raises `tutubo.backoff.BackedOff` (a `RuntimeError`) while the kind is paused. A response with HTTP 429, a page that asks to confirm you are not a bot, or yt-dlp output saying so starts or extends the pause.

## The file

The state folder is `$TUTUBO_STATE_DIR`, else `$XDG_STATE_HOME/tutubo`, else `~/.local/state/tutubo`. It holds `backoff.json` and `backoff.lock`. Every write takes an advisory lock on the lock file, builds the new file beside the old one and replaces it in one step, so concurrent processes do not lose each other's pause and a reader never sees a half-written file. Readers take no lock. Keep the folder on a local disk: advisory locks do not work across a network mount. On Windows there is no lock, and two processes recording at the same instant can overwrite each other.

`TUTUBO_BACKOFF=off` turns the checks off.

## From code

```python
from tutubo import backoff

backoff.shared().state()          # {"download": {"paused": False}, ...}
backoff.shared().remaining("download")
backoff.shared().mark_clear("download")   # lift a pause by hand
```

`Backoff(path, clock=...)` builds an independent instance for tests.
