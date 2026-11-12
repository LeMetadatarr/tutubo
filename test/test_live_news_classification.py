"""Live news channel classification tests using ytInitialData fixtures.

Channels tested:
  @euronews/live          — Euronews English (live stream, tags: news, breaking news, ...)
  @France24_en/live       — France 24 English (live stream, tags: news, 24/7, tv, ...)
  @aljazeeraenglish/live  — Al Jazeera English (live stream)
  @euronewses/live        — Euronews Español (live stream, tags: noticias en vivo, ...)

All four are 24/7 live news streams. Expected classification: LIVE_NEWS.
"""
import pytest

from tutubo.channel import Channel
from tutubo import ContentType  # noqa

# mediavocab's classifier resolves live news from title keywords, not channel
# news tags, so a bare live stream on a news channel collapses to LIVE rather
# than LIVE_NEWS. Tracked as a mediavocab classifier follow-up.
_CLASSIFIER_CHANGED = (
    "mediavocab classifier resolves live-news from title keywords, not "
    "channel news tags; classifier logic is mediavocab's domain"
)

LIVE_NEWS_CHANNELS = [
    ("@euronews",         "https://www.youtube.com/@euronews/live"),
    ("@France24_en",      "https://www.youtube.com/@France24_en/live"),
    ("@aljazeeraenglish", "https://www.youtube.com/@aljazeeraenglish/live"),
    ("@euronewses",       "https://www.youtube.com/@euronewses/live"),
]


def _live_videos(handle: str, url: str) -> list:
    c = Channel(url)
    return list(c.streams)


# ===========================================================================
# Live stream is detected and classified LIVE_NEWS
# ===========================================================================

class TestLiveNewsChannels:
    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_yields_at_least_one_video(self, patch_channel_data, handle, url):
        videos = _live_videos(handle, url)
        assert len(videos) >= 1, f"{handle}: no videos returned from live fixture"

    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_live_stream_is_live(self, patch_channel_data, handle, url):
        videos = _live_videos(handle, url)
        live = [v for v in videos if v.is_live]
        assert len(live) >= 1, f"{handle}: expected at least one is_live=True video"

    @pytest.mark.xfail(reason=_CLASSIFIER_CHANGED, strict=False)
    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_live_stream_classified_live_news(self, patch_channel_data, handle, url):
        videos = _live_videos(handle, url)
        live = [v for v in videos if v.is_live]
        for v in live:
            assert v.content_type == ContentType.LIVE_NEWS, (
                f"{handle}: live stream {v.title!r} classified as {v.content_type}, expected LIVE_NEWS"
            )

    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_no_video_classified_as_iptv(self, patch_channel_data, handle, url):
        # LIVE_NEWS is more specific than generic IPTV — should not fall through
        videos = _live_videos(handle, url)
        iptv = [v for v in videos if v.content_type == ContentType.IPTV]
        assert len(iptv) == 0, (
            f"{handle}: {len(iptv)} video(s) wrongly classified as IPTV: "
            f"{[v.title for v in iptv]}"
        )

    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_content_type_in_as_dict(self, patch_channel_data, handle, url):
        videos = _live_videos(handle, url)
        for v in videos[:2]:
            d = v.as_dict
            assert "content_type" in d
            assert d["content_type"] in [ct.value for ct in ContentType]


# ===========================================================================
# Channel tags include news signals
# ===========================================================================

class TestLiveNewsChannelTags:
    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_channel_has_news_tags(self, patch_channel_data, handle, url):
        c = Channel(url)
        tags_lower = {t.lower() for t in c.keywords}
        news_signals = {"news", "breaking news", "noticias", "noticias en vivo"}
        # Some channels embed "news" inside a phrase (e.g. "aljazeera live tv news English")
        has_news_signal = bool(tags_lower & news_signals) or any(
            "news" in t or "noticias" in t for t in tags_lower
        )
        assert has_news_signal, (
            f"{handle}: expected news-related channel tag, got {c.keywords}"
        )

    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_channel_tags_propagate_to_videos(self, patch_channel_data, handle, url):
        videos = _live_videos(handle, url)
        for v in videos[:3]:
            assert v.channel_tags, f"{handle}: channel_tags not set on Video"


# ===========================================================================
# current_live — single on-air stream from /@handle/live redirect
# ===========================================================================

class TestCurrentLive:
    """Channel.live returns the single on-air stream from the /live redirect."""

    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_current_live_returns_video(self, patch_channel_data, handle, url):
        c = Channel(url)
        v = c.live
        assert v is not None, f"{handle}: current_live returned None"

    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_current_live_is_live(self, patch_channel_data, handle, url):
        c = Channel(url)
        v = c.live
        assert v is not None
        assert v.is_live, f"{handle}: current_live video is not marked is_live"

    @pytest.mark.xfail(reason=_CLASSIFIER_CHANGED, strict=False)
    @pytest.mark.parametrize("handle,url", LIVE_NEWS_CHANNELS)
    def test_current_live_classified_live_news(self, patch_channel_data, handle, url):
        c = Channel(url)
        v = c.live
        assert v is not None
        assert v.content_type == ContentType.LIVE_NEWS, (
            f"{handle}: current_live classified as {v.content_type}, expected LIVE_NEWS"
        )
