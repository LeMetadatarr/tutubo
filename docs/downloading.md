# Downloading videos

tutubo delegates downloading to **yt-dlp**, which handles YouTube's
proof-of-origin token (`po_token`) requirement and stays maintained.

## Install

```bash
pip install yt-dlp
```

## Quick usage

```python
from tutubo.download import download, download_playlist
# Download video (best quality, saves as .mp4)
path = download("https://www.youtube.com/watch?v=EqQuihD0hoI")
print(path)  # -> ./Rob Zombie - Dragula.mp4
# Audio only (mp3)
path = download("https://www.youtube.com/watch?v=EqQuihD0hoI", audio_only=True)
# Specific quality
path = download("https://www.youtube.com/watch?v=EqQuihD0hoI", quality="720")
# Custom output directory and filename
path = download(
    "https://www.youtube.com/watch?v=EqQuihD0hoI",
    output_path="/music",
    filename="dragula",
    audio_only=True,
)
# -> /music/dragula.mp3
```

## With search

```python
from tutubo import YoutubeSearch
from tutubo.download import download
s = YoutubeSearch("black sabbath paranoid")
v = next(s.iterate_videos(max_res=1))
print(f"Downloading: {v.title}")
path = download(v.watch_url, output_path="/music", audio_only=True)
```

## Download a playlist

```python
from tutubo.download import download_playlist
paths = download_playlist(
    "https://www.youtube.com/playlist?list=PLBxwSF9JxLuJea2Hn2b_xw-3X7IAfBMZT",
    output_path="/music/rob_zombie",
    audio_only=True,
)
for p in paths:
    print(p)
```

## API

### `download(url, output_path=".", audio_only=False, quality=None, filename=None) -> str`

| Parameter | Type | Description |
|---|---|---|
| `url` | str | YouTube watch URL |
| `output_path` | str | Directory to write the file (created if needed) |
| `audio_only` | bool | Extract audio as mp3 (default: False) |
| `quality` | str | Max video height, e.g. `"720"` or `"1080"` (ignored for audio) |
| `filename` | str | Output filename stem without extension |

Returns the path of the downloaded file.

### `download_playlist(url, output_path=".", audio_only=False, quality=None) -> list[str]`

Downloads all videos in a playlist. Returns a list of file paths.

---
[← Locale](locale.md) · [Home](index.md) · [Testing →](testing.md)
