"""Download YouTube videos/audio via yt-dlp.

Thin subprocess wrapper around the ``yt-dlp`` CLI; ``yt-dlp`` must be on PATH.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional


def _require_ytdlp() -> None:
    """Raise RuntimeError if the ``yt-dlp`` binary is not on PATH."""
    if not shutil.which("yt-dlp"):
        raise RuntimeError(
            "yt-dlp not found. Install it with: pip install yt-dlp"
        )


def download(url: str, output_path: str = ".", audio_only: bool = False,
             quality: Optional[str] = None, filename: Optional[str] = None) -> str:
    """Download a YouTube video or audio track using yt-dlp.

    :param url:        YouTube watch URL.
    :param output_path: Directory to save the file (default: current directory).
    :param audio_only: Extract audio only (mp3). Default False.
    :param quality:    Video quality hint, e.g. ``"720"``, ``"1080"``, ``"best"``.
                       Ignored when ``audio_only=True``.
    :param filename:   Output filename stem (without extension). Optional.
    :returns:          Path to the downloaded file.
    """
    _require_ytdlp()
    Path(output_path).mkdir(parents=True, exist_ok=True)

    template = str(Path(output_path) / (f"{filename}.%(ext)s" if filename else "%(title)s.%(ext)s"))

    cmd = ["yt-dlp", "--no-playlist", "-o", template]

    if audio_only:
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        fmt = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]" if quality else "bestvideo+bestaudio/best"
        cmd += ["-f", fmt, "--merge-output-format", "mp4"]

    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{result.stderr}")

    # Parse the output filename from yt-dlp's stdout
    for line in reversed(result.stdout.splitlines()):
        if "[download] Destination:" in line:
            return line.split("Destination:")[-1].strip()
        if "[ExtractAudio] Destination:" in line:
            return line.split("Destination:")[-1].strip()
        if "Merging formats into" in line:
            return line.split('"')[1]

    # Fallback: find the newest file in output_path matching expected extensions
    exts = {".mp3", ".mp4", ".webm", ".mkv", ".m4a", ".ogg"}
    files = sorted(
        (p for p in Path(output_path).iterdir() if p.suffix in exts),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if files:
        return str(files[0])
    raise RuntimeError(f"yt-dlp reported success but no output file found in {output_path!r}")


def download_playlist(playlist_url: str, output_path: str = ".",
                      audio_only: bool = False, quality: Optional[str] = None) -> List[str]:
    """Download all videos in a playlist.

    :returns: List of downloaded file paths.
    """
    _require_ytdlp()
    Path(output_path).mkdir(parents=True, exist_ok=True)

    template = str(Path(output_path) / "%(playlist_index)s - %(title)s.%(ext)s")
    cmd = ["yt-dlp", "-o", template]

    if audio_only:
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        fmt = f"bestvideo[height<={quality}]+bestaudio/best" if quality else "bestvideo+bestaudio/best"
        cmd += ["-f", fmt, "--merge-output-format", "mp4"]

    cmd.append(playlist_url)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{result.stderr}")

    paths = []
    for line in result.stdout.splitlines():
        if "[download] Destination:" in line:
            paths.append(line.split("Destination:")[-1].strip())
    return paths
