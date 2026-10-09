"""tutubo — a typed, dependency-light YouTube/YouTube Music search & metadata client.

Public API:
    YoutubeSearch, YoutubeMusicSearch, SearchType, search_yt, search_yt_music
    Channel, Playlist, Video, PodcastPreview
    Category, classify_category, classify_video, ClassificationResult, extract_tags
    TitleParseResult, parse_title
    download, download_playlist
    MusicTrack, MusicVideo, MusicAlbum, MusicPlaylist, MusicArtist

``classify_video`` returns a mediavocab ``ClassificationResult`` (media_type,
content_form, programme_format, content_genres); :func:`classify_category`
collapses it to one tutubo :class:`~tutubo.classification.Category` search
facet. classify_video, parse_title and the locale system live in
``mediavocab``; for non-default languages pass ``lang="xx-yy"`` to the
function call (the locale system is stateless / thread-safe).
"""
from tutubo.search import YoutubeSearch, YoutubeMusicSearch, SearchType, search_yt, search_yt_music
from tutubo.channel import Channel, Playlist, Video, PodcastPreview
from tutubo.classification import Category, classify_category
from mediavocab.text import (
    classify_video, extract_tags,
    parse_title, TitleParseResult,
)
from mediavocab.text.classify import ClassificationResult
from tutubo.download import download, download_playlist
from tutubo.ytmus import MusicTrack, MusicVideo, MusicAlbum, MusicPlaylist, MusicArtist

# Back-compat alias: tutubo historically exposed a ``ContentType`` enum (then
# owned by mediavocab). It is now the tutubo-local ``Category`` facet enum.
ContentType = Category

__all__ = [
    "YoutubeSearch", "YoutubeMusicSearch", "SearchType",
    "search_yt", "search_yt_music",
    "Channel", "Playlist", "Video", "PodcastPreview",
    "Category", "classify_category", "ContentType",
    "classify_video", "ClassificationResult", "extract_tags",
    "parse_title", "TitleParseResult",
    "download", "download_playlist",
    "MusicTrack", "MusicVideo", "MusicAlbum", "MusicPlaylist", "MusicArtist",
]
