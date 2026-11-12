"""Video durations in channel and playlist listings, and the playlist thumbnail.

Unit tests run on trimmed renderer JSON for each length format; the fixture
tests use ``ytInitialData`` recorded from a real channel and a real playlist
(trimmed to six items), including the item's own thumbnail badge text as the
expected value.
"""
import pytest

from tutubo._utils import duration_from_item, parse_duration
from tutubo.channel import Channel, Playlist, Video

CHANNEL_FIXTURE = "channel_watchalter_listing_durations"
PLAYLIST_ID = "PLtmNpo8LSL8Z281xsX_iBixKvIRQpSWtU"
PLAYLIST_FIXTURE = f"playlist_{PLAYLIST_ID}_durations"

CHANNEL_IDS_AND_SECONDS = [
    ("z9il8Si2x_0", 808), ("Ri2KLr77h7k", 758), ("OX9oy5QXEck", 909),
    ("EhaFs44OyUI", 657), ("B8GeINznhNs", 702), ("JrKiwFFf-r8", 825),
]
PLAYLIST_IDS_AND_SECONDS = [
    ("OZmP2Fv06-s", 1421), ("OrOYvVf6tIM", 923), ("OqSmb3n0j8o", 544),
    ("WHgh2ajazTw", 807), ("6eaZZc7O2PE", 1049), ("zk-eY5S1Nck", 382),
]


def _lockup(text=None):
    badges = [] if text is None else [
        {"thumbnailBadgeViewModel": {"text": text}}]
    return {"lockupViewModel": {
        "contentId": "abc",
        "contentImage": {"thumbnailViewModel": {"overlays": [
            {"thumbnailBottomOverlayViewModel": {"badges": badges}}]}},
    }}


@pytest.mark.parametrize("text,seconds", [
    ("1:02:03", 3723), ("11:07", 667), ("0:45", 45), ("10:00:00", 36000),
    ("13.28", 808), ("1.02.03", 3723), ("90:00", 5400), ("999999", None),
])
def test_parse_duration_clock_formats(text, seconds):
    assert parse_duration(text) == seconds


def test_parse_duration_bare_seconds_only_when_allowed():
    assert parse_duration("30") is None
    assert parse_duration("30", allow_bare=True) == 30
    assert parse_duration("1000000", allow_bare=True) is None


@pytest.mark.parametrize("text", ["1:75:00", "1:30:75", "12:60", "5:99", "1:2:3",
                                  "9999:00:00", "999:59:59", "-1:30"])
def test_parse_duration_rejects_out_of_range_fields(text):
    assert parse_duration(text) is None


@pytest.mark.parametrize("text", [None, "", "LIVE", "UPCOMING", "Shorts", "12 videos", "12", 5, {}])
def test_parse_duration_rejects_non_clock_values(text):
    assert parse_duration(text) is None


@pytest.mark.parametrize("text,seconds", [
    ("1:02:03", 3723), ("11:07", 667), ("0:45", 45),
])
def test_lockup_badge_duration(text, seconds):
    assert duration_from_item({"richItemRenderer": {"content": _lockup(text)}}) == seconds
    assert duration_from_item(_lockup(text)) == seconds


@pytest.mark.parametrize("item", [_lockup(None), _lockup("LIVE"), _lockup("UPCOMING"),
                                  {"lockupViewModel": {"contentId": "x"}}, {}])
def test_lockup_without_duration_is_none(item):
    assert duration_from_item(item) is None


def test_video_renderer_length_text():
    item = {"richItemRenderer": {"content": {"videoRenderer": {
        "videoId": "v", "lengthText": {"simpleText": "1:02:03"}}}}}
    assert duration_from_item(item) == 3723


def test_video_renderer_time_status_overlay():
    vr = {"videoId": "v", "thumbnailOverlays": [
        {"thumbnailOverlayTimeStatusRenderer": {"text": {"simpleText": "4:05"}}}]}
    assert duration_from_item({"videoRenderer": vr}) == 245


@pytest.mark.parametrize("overlay_text", ["LIVE", "UPCOMING"])
def test_video_renderer_live_or_upcoming_is_none(overlay_text):
    vr = {"videoId": "v", "thumbnailOverlays": [
        {"thumbnailOverlayTimeStatusRenderer": {"text": {"simpleText": overlay_text}}}]}
    assert duration_from_item({"videoRenderer": vr}) is None
    assert duration_from_item({"videoRenderer": {"videoId": "v"}}) is None


def test_playlist_video_renderer_length_seconds():
    assert duration_from_item(
        {"playlistVideoRenderer": {"videoId": "p", "lengthSeconds": "3723"}}) == 3723


@pytest.mark.parametrize("seconds", ["-5", "-1", "1000000", "abc", None])
def test_playlist_video_renderer_bad_length_seconds_is_none(seconds):
    item = {"playlistVideoRenderer": {"videoId": "p", "lengthSeconds": seconds}}
    assert duration_from_item(item) is None


def test_playlist_video_renderer_falls_back_to_length_text_then_none():
    assert duration_from_item({"playlistVideoRenderer": {
        "videoId": "p", "lengthText": {"simpleText": "2:00"}}}) == 120
    assert duration_from_item({"playlistVideoRenderer": {"videoId": "p"}}) is None


def test_bare_integer_length_text_is_not_a_duration():
    assert duration_from_item({"videoRenderer": {"lengthText": {"simpleText": "12"}}}) is None


def test_video_defaults_and_as_dict():
    assert Video("abc").duration_seconds is None
    assert Video("abc").as_dict["duration_seconds"] is None
    assert Video("abc", duration_seconds=90).as_dict["duration_seconds"] == 90


def test_preview_length_still_shares_the_parser():
    from tutubo.models import VideoPreview
    assert VideoPreview({"lengthText": {"simpleText": "1:02:03"}}).length == 3723
    assert VideoPreview({"lengthText": {"simpleText": "0:09"}}).length == 9
    assert VideoPreview({}).length == 0


def test_channel_videos_carry_durations_from_real_listing(load_fixture, monkeypatch):
    data = load_fixture(CHANNEL_FIXTURE)
    monkeypatch.setattr(Channel, "_get_data", lambda self, url: data)
    ch = Channel("https://www.youtube.com/@WatchALTER")
    monkeypatch.setattr(Channel, "keywords", property(lambda self: []))
    videos = list(ch.videos)
    assert [(v.video_id, v.duration_seconds) for v in videos] == CHANNEL_IDS_AND_SECONDS
    assert all(isinstance(v.duration_seconds, int) for v in videos)
    assert videos[0].as_dict["duration_seconds"] == 808


def test_channel_extract_items_matches_badge_text(load_fixture):
    """Each parsed duration equals the badge text printed on the thumbnail."""
    data = load_fixture(CHANNEL_FIXTURE)
    ch = Channel("https://www.youtube.com/@WatchALTER")
    videos, _ = ch._extract_items(data, "videos")
    tab = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]
    items = tab["tabRenderer"]["content"]["richGridRenderer"]["contents"]
    labels = [
        o["thumbnailBottomOverlayViewModel"]["badges"][0]["thumbnailBadgeViewModel"]["text"]
        for i in items
        for o in i["richItemRenderer"]["content"]["lockupViewModel"][
            "contentImage"]["thumbnailViewModel"]["overlays"]
        if "thumbnailBottomOverlayViewModel" in o
    ]
    assert labels[0] == "13:28"
    assert [parse_duration(t) for t in labels] == [v.duration_seconds for v in videos]


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self, html):
        self.html = html

    def get(self, *a, **kw):
        return _Resp(self.html)

    def post(self, *a, **kw):
        return _Resp("{}")


def _playlist(data):
    import json
    html = (f"<script>var ytInitialData = {json.dumps(data)};</script>"
            '<script>ytcfg.set({"INNERTUBE_API_KEY": "K"});</script>')
    return Playlist(f"https://www.youtube.com/playlist?list={PLAYLIST_ID}",
                    session=_Session(html))


def test_playlist_videos_carry_durations_from_real_page(load_fixture):
    pl = _playlist(load_fixture(PLAYLIST_FIXTURE))
    assert [(v.video_id, v.duration_seconds) for v in pl.videos] == PLAYLIST_IDS_AND_SECONDS
    assert pl.video_urls[0].endswith("OZmP2Fv06-s")


def test_playlist_thumbnail_from_real_page(load_fixture):
    pl = _playlist(load_fixture(PLAYLIST_FIXTURE))
    assert pl.thumbnail_url.startswith(
        f"https://i.ytimg.com/pl_c/{PLAYLIST_ID}/studio_square_thumbnail.jpg")


def test_playlist_thumbnail_prefers_largest_sidebar_image_then_microformat():
    data = {"sidebar": {"playlistSidebarRenderer": {"items": [
        {"playlistSidebarPrimaryInfoRenderer": {"thumbnailRenderer": {
            "playlistVideoThumbnailRenderer": {"thumbnail": {"thumbnails": [
                {"url": "small"}, {"url": "large"}]}}}}}]}}}
    assert _playlist(data).thumbnail_url == "large"
    micro = {"microformat": {"microformatDataRenderer": {
        "thumbnail": {"thumbnails": [{"url": "micro"}]}}}}
    assert _playlist(micro).thumbnail_url == "micro"


def test_playlist_thumbnail_falls_back_to_first_video(load_fixture):
    data = load_fixture(PLAYLIST_FIXTURE)
    del data["sidebar"], data["microformat"]
    pl = _playlist(data)
    assert pl.thumbnail_url == "https://img.youtube.com/vi/OZmP2Fv06-s/hqdefault.jpg"


def test_playlist_thumbnail_none_for_empty_playlist():
    assert _playlist({"metadata": {}}).thumbnail_url is None


class _PostSession(_Session):
    """Session that records POST bodies and answers with queued pages."""

    def __init__(self, html="", pages=()):
        super().__init__(html)
        self.pages = list(pages)
        self.posts = []

    def post(self, url, json=None, **kw):
        import json as _json
        self.posts.append(json)
        return _Resp(_json.dumps(self.pages.pop(0)))


def _token(value):
    return {"continuationItemRenderer": {"continuationEndpoint": {
        "continuationCommand": {"token": value}}}}


def test_channel_continuation_page_carries_durations(load_fixture, monkeypatch):
    first = load_fixture(CHANNEL_FIXTURE)
    grid = first["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0][
        "tabRenderer"]["content"]["richGridRenderer"]
    grid["contents"].append(_token("NEXT"))
    session = _PostSession(pages=[load_fixture(CHANNEL_FIXTURE + "_page2")])
    ch = Channel("https://www.youtube.com/@WatchALTER", session=session)
    monkeypatch.setattr(Channel, "_get_data", lambda self, url: first)
    monkeypatch.setattr(Channel, "keywords", property(lambda self: []))
    monkeypatch.setattr(Channel, "yt_api_key", property(lambda self: "K"))
    videos = list(ch.videos)
    assert session.posts[0]["continuation"] == "NEXT"
    assert [(v.video_id, v.duration_seconds) for v in videos[6:]] == [
        ("HnzcMpLyYl0", 498), ("BQz3poKzSsU", 496), ("R-6b_QwK_cU", 493)]


def test_playlist_continuation_page_carries_durations(load_fixture):
    first = load_fixture(PLAYLIST_FIXTURE)
    import json
    html = (f"<script>var ytInitialData = {json.dumps(first)};</script>"
            '<script>ytcfg.set({"INNERTUBE_API_KEY": "K"});</script>')
    session = _PostSession(html, [load_fixture(PLAYLIST_FIXTURE + "_page2")])
    pl = Playlist(f"https://www.youtube.com/playlist?list={PLAYLIST_ID}", session=session)
    videos = list(pl.videos)
    assert len(session.posts) == 1
    assert [(v.video_id, v.duration_seconds) for v in videos[6:]] == [
        ("Fv-MoOhVhqU", 612), ("3_DQmfFjTlU", 622), ("BTshCCwo5Tw", 760)]


FI = "fi-FI,fi;q=0.9"


def test_finnish_listing_uses_dot_separated_durations(load_fixture, monkeypatch):
    data = load_fixture(CHANNEL_FIXTURE + "_fi")
    badge = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0][
        "tabRenderer"]["content"]["richGridRenderer"]["contents"][0][
        "richItemRenderer"]["content"]["lockupViewModel"]["contentImage"][
        "thumbnailViewModel"]["overlays"][0]["thumbnailBottomOverlayViewModel"][
        "badges"][0]["thumbnailBadgeViewModel"]["text"]
    assert badge == "13.28"
    monkeypatch.setattr(Channel, "_get_data", lambda self, url: data)
    monkeypatch.setattr(Channel, "keywords", property(lambda self: []))
    ch = Channel("https://www.youtube.com/@WatchALTER", language=FI)
    assert [v.duration_seconds for v in ch.videos] == [808, 758, 909]


def test_channel_continuation_post_carries_language_and_region():
    session = _PostSession(pages=[{}])
    ch = Channel("https://www.youtube.com/@x", language=FI, session=session)
    ch._ytcfg = {"INNERTUBE_API_KEY": "K"}
    ch._continuation_post("T")
    client = session.posts[0]["context"]["client"]
    assert (client["hl"], client["gl"]) == ("fi", "FI")
    assert client["clientName"] == "WEB"


def test_channel_continuation_post_default_language_is_english():
    session = _PostSession(pages=[{}])
    ch = Channel("https://www.youtube.com/@x", session=session)
    ch._ytcfg = {"INNERTUBE_API_KEY": "K"}
    ch._continuation_post("T")
    client = session.posts[0]["context"]["client"]
    assert (client["hl"], client["gl"]) == ("en", "US")


@pytest.mark.parametrize("language,hl,gl", [
    ("zh-Hant-TW", "zh", "TW"), ("es-419", "es", None), ("pt_BR", "pt", "BR"),
    ("*", None, None), ("en-US,en;q=0.9", "en", "US"), ("de", "de", None),
    ("fil-PH", "fil", "PH"), ("", None, None),
])
def test_browse_context_normalises_language_tags(language, hl, gl):
    from tutubo.channel import _browse_context
    client = _browse_context(language)["client"]
    assert client.get("hl") == hl
    assert client.get("gl") == gl
    assert client["clientName"] == "WEB"
