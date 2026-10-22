# Back-off

`tutubo.backoff` holds one pause per kind of request for the whole machine. YouTube challenges some kinds of request and not others, so the kinds pause apart: `details`, `listing`, `feed`, `thumb`, `search` and `download`.

The first bot check of a kind pauses it for 30 minutes. A further check after that pause has run out doubles the wait, up to 24 hours. A check that arrives while the kind is already paused leaves the pause as it is. A request that succeeds ends the pause and resets the wait. The rules and the field names of a row (`retry_at`, `wait_s`, `at`) are media-archivist's, so one server and its neighbours can share a file.

## Where tutubo checks

| Call | Kind |
|---|---|
| innertube search (`YoutubeSearch`) | `search` |
| YouTube Music search and the album, playlist and artist lookups that follow it (`search_yt_music`, `YoutubeMusicSearch`, `get_album`) | `search` |
| channel and playlist pages and their continuations | `listing` |
| watch pages (`list_caption_tracks`, `Video.caption_tracks`) | `details` |
| `download()` and `download_playlist()` | `download` |

Before each of these tutubo reads the file and raises `tutubo.backoff.BackedOff` (a `RuntimeError`) while the kind is paused. A response with HTTP 429, a page that asks to confirm you are not a bot, a watch page whose player refuses the video for that reason or says "This content isn't available, try again later", or yt-dlp output saying so (including its "rate-limited" message) starts or extends the pause. tutubo never tries to get past a check: it stops asking until the pause runs out.

## The file

The state folder is `$TUTUBO_STATE_DIR`, else `$XDG_STATE_HOME/tutubo`, else `~/.local/state/tutubo`. It holds `backoff.json` and `backoff.lock`. Every write takes an advisory lock on the lock file, builds the new file beside the old one and replaces it in one step, so concurrent processes do not lose each other's pause and a reader never sees a half-written file. Readers take no lock. Keep the folder on a local disk: advisory locks do not work across a network mount. On Windows there is no lock, and two processes recording at the same instant can overwrite each other.

The default folder is under the home directory of one user, so a pause is shared by that user's programs and not by other accounts. To share one pause between accounts, point `TUTUBO_STATE_DIR` at a folder they can all write. Both files are created with the process's umask, so they are group readable when the umask allows it, and `backoff.json` always gets the same mode as `backoff.lock`.

A file that exists and cannot be read (wrong permissions, a directory in its place) fails closed: every request is refused with `BackedOff`, and the message names the file, because a pause may be hidden in it. Fix the permissions or move the file away. A file that reads but holds nothing usable (not JSON, or a row whose `retry_at`, `wait_s` or `at` is not a number in range) counts as no pause, and the next recorded check replaces it. When the folder cannot be written, a bot check still raises `BackedOff`, and the process keeps that pause in memory until it ends, so it stops asking even though nothing else can see the pause. A pause never lasts longer than its own `wait_s` from now, so a clock that was stepped back does not stretch it.

`TUTUBO_BACKOFF=off` turns the checks off completely: nothing reads the file and nothing writes it. A program that stops on a bot check only because of the pause then keeps sending requests, which YouTube may punish with a longer block. Leave it on unless you manage the rate yourself.

## From code

```python
from tutubo import backoff

backoff.shared().state()          # {"download": {"paused": False}, ...}
backoff.shared().remaining("download")
backoff.shared().mark_clear("download")   # lift a pause by hand
```

`Backoff(path, clock=...)` builds an independent instance for tests.

## From a shell

`python -m tutubo.backoff` prints the state of every kind as one JSON object, in the shape shown above. It exits with status 75 while any kind is paused and 0 otherwise, so a script on the same machine can check before it starts work.
