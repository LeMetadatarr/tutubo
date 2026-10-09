"""Named regression guards for parser/API-shape bugs found during 2026.

Each test pins the post-fix behaviour of a real, previously-shipped bug.
When upstream YouTube drifts or someone refactors the parser, these
named tests are the first-line tripwire — the test name itself documents
what regression class is being guarded against.

Live-API drift coverage is provided separately by the ``nightly-live``
workflow which re-records every fixture and re-runs the suite.

History (commit summaries — see ``git log`` for details):

* ``Channel`` star-import: ``from tutubo.channel import *`` failed because
  ``__all__`` referenced symbols that no longer existed after the pytube
  rip-out.
* ``Channel.video_urls`` — the public surface had a ``video_urls``
  property that delegated to a removed pytube helper. The fix removed
  the property; consumers must use ``Channel.videos`` (an iterator).
* ``Video.length`` was unconditionally read on channel-page Videos but
  channel-tab innertube payloads don't always carry ``lengthText`` →
  AttributeError on shorts/live items. Fix: default to 0.
* ``Video.published_time`` on channel-page videos was lost when the
  meta-row parser filtered too aggressively — ended up empty for every
  Video. Fix: take the first non-view meta row.
* ``MusicArtist`` was not a subclass of ``YTMusicResult`` after a
  refactor, breaking ``isinstance(r, YTMusicResult)`` checks in
  downstream code (mediavocab bridge).
* ``iterate_music_albums`` was added to ``YoutubeMusicSearch`` only
  (not ``YoutubeSearch``) — verifying the surface stays separate.
* ``Category.KIDS`` / ``YoutubeSearch.iterate_kids`` / the documented
  ``examples/kids_safe_feed.py`` were dead: ``classify_category`` had no
  code path that ever returned ``Category.KIDS`` because mediavocab's
  ``ClassificationResult`` carries no children's-content signal (no genre,
  media_type or programme_format maps to it). Verified against the real
  ``@PinkfongBabyShark`` channel fixture: every video title/tag reading as
  kids' content (e.g. "CoComelon Nursery Rhymes & Kids Songs") classified
  as ``TV_EPISODE`` instead of ``KIDS``. Fix: ``classify_category`` now
  accepts ``title``/``tags`` and detects kids content via a keyword
  heuristic (mirroring how tutubo already free-text-derives ``tags`` via
  ``extract_tags``), wired in from both ``VideoPreview.content_type`` and
  ``channel.Video.content_type``.
* ``Channel._continuation_post`` swallowed HTTP errors — unlike
  ``Playlist._continuation_post`` it never called ``resp.raise_for_status()``,
  so a failed continuation request (rate-limit, 5xx) silently truncated
  channel pagination instead of raising, masking data loss.
"""
from __future__ import annotations

import importlib
import json

import pytest

from tutubo import YoutubeSearch, YoutubeMusicSearch
from tutubo.channel import Channel, Playlist, Video
from tutubo.classification import Category, classify_category, _looks_like_kids_content
from tutubo.ytmus import (
    MusicAlbum,
    MusicArtist,
    MusicPlaylist,
    MusicTrack,
    MusicVideo,
    YTMusicResult,
)


# ---------------------------------------------------------------------------
# Channel — star-import & surface
# ---------------------------------------------------------------------------

def test_regression_channel_star_import_clean():
    """``from tutubo.channel import *`` must not raise (broken Mar 2026)."""
    # Re-import in a fresh namespace and verify __all__ resolves.
    mod = importlib.import_module("tutubo.channel")
    if hasattr(mod, "__all__"):
        for name in mod.__all__:
            assert hasattr(mod, name), (
                f"tutubo.channel.__all__ references missing symbol {name!r}"
            )


def test_regression_channel_has_no_video_urls_property():
    """``Channel.video_urls`` was removed when pytube was ripped out.

    Consumers must iterate ``Channel.videos`` instead.  This test pins the
    removed surface so it doesn't silently come back as a stub.
    """
    assert not hasattr(Channel, "video_urls"), (
        "Channel.video_urls was removed (pytube delegate); use Channel.videos"
    )


def test_regression_playlist_still_has_video_urls():
    """Playlist.video_urls is the legitimate API; only Channel lost it."""
    assert hasattr(Playlist, "video_urls")


# ---------------------------------------------------------------------------
# Video on channel pages — length defaulting + published_time
# ---------------------------------------------------------------------------

def test_regression_channel_video_has_no_length_attr():
    """Channel-tab ``Video`` deliberately omits ``length``.

    Earlier code accessed ``video.length`` on channel-tab Videos and
    crashed because innertube channel-tab payloads don't carry
    ``lengthText`` (especially for shorts/live).  Fix: keep ``length``
    off ``Channel.Video`` entirely; consumers that need length must
    upgrade via the search-result ``VideoPreview`` or fetch the watch
    page.  This test pins the surface so length doesn't silently come
    back as a stub returning 0 (which would mask real upstream drift).
    """
    from tutubo.models import VideoPreview
    v = Video(video_id="x" * 11)
    assert not hasattr(v, "length")
    # VideoPreview (search-result) DOES carry length — verify the
    # surface stays where it belongs.
    assert "length" in dir(VideoPreview)


def test_regression_video_published_time_attribute_exists():
    v = Video(video_id="x" * 11)
    assert hasattr(v, "published_time")
    # Default should be a string (possibly empty), never missing/None.
    assert isinstance(v.published_time, str)


def test_regression_video_published_time_populated_on_channel_page(patch_channel_data):
    """published_time was being filtered to empty for every channel-tab Video."""
    ch = Channel("https://www.youtube.com/@kurzgesagt")
    populated = 0
    for v in ch.videos:
        if v.published_time:
            populated += 1
        if populated >= 1:
            break
    assert populated >= 1, (
        "Expected at least one Video with a populated published_time; "
        "regression of channel-tab meta-row parser."
    )


# ---------------------------------------------------------------------------
# Music — type hierarchy & search-class separation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [MusicTrack, MusicVideo, MusicAlbum, MusicPlaylist, MusicArtist])
def test_regression_music_classes_subclass_ytmusicresult(cls):
    """All Music* result types must subclass YTMusicResult.

    A refactor briefly broke ``MusicArtist``'s base class, which silently
    broke isinstance() dispatch in the mediavocab bridge.
    """
    assert issubclass(cls, YTMusicResult), (
        f"{cls.__name__} must subclass YTMusicResult"
    )


def test_regression_music_video_subclasses_music_track():
    """MusicVideo extends MusicTrack — preserves track-shape consumers."""
    assert issubclass(MusicVideo, MusicTrack)


def test_regression_music_album_subclasses_music_playlist():
    assert issubclass(MusicAlbum, MusicPlaylist)


# ---------------------------------------------------------------------------
# Search-class separation: iterate_music_* lives only on YoutubeMusicSearch
# ---------------------------------------------------------------------------

def test_regression_youtube_search_has_no_iterate_albums():
    """YoutubeSearch must NOT expose ytmusic-only iterators."""
    assert not hasattr(YoutubeSearch, "iterate_albums")
    assert not hasattr(YoutubeSearch, "iterate_artists")
    assert not hasattr(YoutubeSearch, "iterate_tracks")


def test_regression_youtube_music_search_has_iterate_albums():
    """The corresponding ytmusic iterators live on YoutubeMusicSearch."""
    assert hasattr(YoutubeMusicSearch, "iterate_albums")
    assert hasattr(YoutubeMusicSearch, "iterate_artists")
    assert hasattr(YoutubeMusicSearch, "iterate_tracks")


def test_regression_classes_are_distinct():
    """YoutubeSearch and YoutubeMusicSearch must remain separate types."""
    assert YoutubeSearch is not YoutubeMusicSearch
    assert not issubclass(YoutubeMusicSearch, YoutubeSearch)
    assert not issubclass(YoutubeSearch, YoutubeMusicSearch)


# ---------------------------------------------------------------------------
# Category.KIDS was unreachable — classify_category never returned it
# ---------------------------------------------------------------------------

def test_regression_looks_like_kids_content_detects_title_keywords():
    assert _looks_like_kids_content("CoComelon Nursery Rhymes & Kids Songs")
    assert _looks_like_kids_content("Songs for Toddlers")
    assert _looks_like_kids_content("A preschool learning video")
    assert not _looks_like_kids_content("Crash Course World History")


def test_regression_looks_like_kids_content_detects_channel_tags():
    """Title alone may carry no signal; channel keywords still trigger KIDS."""
    assert not _looks_like_kids_content("Baby Shark Dance Remix")
    assert _looks_like_kids_content(
        "Baby Shark Dance Remix", tags=["Nursery rhymes", "cartoon"]
    )


def test_regression_classify_category_can_return_kids():
    """classify_category must have a live code path to Category.KIDS.

    Previously no genre / media_type / programme_format mapped to KIDS,
    so this facet was dead even though it's documented (docs/content_type.md)
    and shipped in examples/kids_safe_feed.py.
    """
    from mediavocab.text.classify import classify_video

    result = classify_video(
        title="Breakfast song | CoComelon Nursery Rhymes & Kids Songs",
        description="",
    )
    cat = classify_category(
        result, title="Breakfast song | CoComelon Nursery Rhymes & Kids Songs"
    )
    assert cat == Category.KIDS


def test_regression_pinkfong_channel_videos_classify_as_kids(patch_channel_data):
    """Real @PinkfongBabyShark fixture: every kids-song video must classify KIDS.

    Before the fix, every one of these classified as TV_EPISODE.
    """
    ch = Channel("https://www.youtube.com/@pinkfongbabyshark")
    videos = list(ch.videos)[:15]
    assert len(videos) >= 5, "expected videos from the PinkfongBabyShark fixture"
    kids = [v for v in videos if v.content_type == Category.KIDS]
    assert len(kids) == len(videos), (
        f"expected all {len(videos)} PinkfongBabyShark videos to classify KIDS, "
        f"got: {[(v.title, v.content_type.value) for v in videos if v not in kids]}"
    )


# ---------------------------------------------------------------------------
# Channel continuation requests must raise on HTTP errors, not swallow them
# ---------------------------------------------------------------------------

def test_regression_channel_continuation_post_raises_on_http_error(monkeypatch):
    """``Channel._continuation_post`` silently ignored HTTP errors (unlike
    ``Playlist._continuation_post``, which always called raise_for_status()),
    so a failed continuation page truncated pagination without any signal.
    """
    import tutubo.channel as _ch

    class _FailingResponse:
        text = json.dumps({"error": {"code": 429, "message": "rate limited"}})

        def raise_for_status(self):
            raise RuntimeError("HTTP 429")

    class _FailingSession:
        def get(self, *a, **kw):
            raise AssertionError("not used")

        def post(self, *a, **kw):
            return _FailingResponse()

    ch = Channel.__new__(Channel)
    ch._session = _FailingSession()
    ch._ytcfg = {"INNERTUBE_API_KEY": "x"}
    ch._visitor_data = None

    with pytest.raises(RuntimeError):
        ch._continuation_post("sometoken")
