"""Playlist pages that list items as ``lockupViewModel`` instead of
``playlistVideoRenderer``.

The fixture is the ``ytInitialData`` of a real playlist page, trimmed to the
title, the 31 items (id, title, one thumbnail) and the continuation entry.
"""
import json

import pytest

from tutubo.channel import Channel, Playlist

PLAYLIST_ID = "PLtmNpo8LSL8ZUANvP8S54oAkURYsLFr9V"
FIXTURE = f"playlist_lockupviewmodel_{PLAYLIST_ID}"

EXPECTED_IDS = [
    "KzdWLiaY7yo", "UPkx6aGR_2s", "FsHSmsUZtQg", "NX4_UlbJUL0", "cziqkD7iO-g",
    "rortKqLata8", "aGJYf03QXAU", "e-ta-kl-Bh4", "-4XQxd0rsFo", "AQGS98fThwo",
    "DLOfhWJ9NOc", "2O2tLkNnFEA", "HbTWzWKwB2o", "TDmL5ppl6Ts", "aF-E48eBX9o",
    "vBPd0RDMyhA", "PiQ9ksr8fFM", "khj7UvP3d2Q", "P1n6L_OoIoY", "j97eODbUCg8",
    "8Vki9Jcvppw", "kkE4CDN-ILo", "ez56onV24fk", "rtO-Wnyi4Hs", "33I7Px2N1Aw",
    "BC5UZWeppAw", "9Q4iIZYhqug", "7MgVcDu7ptc", "6UkGCVoctyc", "nsYs36ZLbww",
    "7JohEbtYr7k",
]
CONTINUATION_PREFIX = "4qmFsgJbEiRWTFBMdG1OcG84TFNMOFpVQU52UDhTNTRvQWtVUllz"


def _view_model_token(token):
    return {"continuationItemViewModel": {
        "trigger": "CONTINUATION_TRIGGER_ON_ITEM_SHOWN",
        "continuationCommand": {"innertubeCommand": {"continuationCommand": {
            "token": token}}},
    }}


def test_fixture_has_no_playlist_video_renderer(load_fixture):
    raw = json.dumps(load_fixture(FIXTURE))
    assert "playlistVideoRenderer" not in raw
    assert raw.count('"lockupViewModel"') == len(EXPECTED_IDS)


def test_extract_video_ids_from_lockup_view_models(load_fixture):
    ids, continuation = Playlist._extract_video_ids(load_fixture(FIXTURE))
    assert ids == EXPECTED_IDS
    assert continuation.startswith(CONTINUATION_PREFIX)


def test_extract_video_ids_accepts_raw_json_string(load_fixture):
    ids, _ = Playlist._extract_video_ids(json.dumps(load_fixture(FIXTURE)))
    assert len(ids) == 31


def test_playlist_yields_videos_from_page_html(load_fixture):
    data = load_fixture(FIXTURE)
    html = (f"<script>var ytInitialData = {json.dumps(data)};</script>"
            '<script>ytcfg.set({"INNERTUBE_API_KEY": "K"});</script>')

    class _Resp:
        text = html

        def raise_for_status(self):
            pass

    class _Session:
        def __init__(self):
            self.posts = []

        def get(self, *a, **kw):
            return _Resp()

        def post(self, url, json=None, **kw):
            self.posts.append(json)

            class _Empty:
                text = "{}"

                def raise_for_status(self):
                    pass
            return _Empty()

    session = _Session()
    pl = Playlist(f"https://www.youtube.com/playlist?list={PLAYLIST_ID}", session=session)
    assert pl.title == "Zombie Outbreak | ALTER Horror Short Films"
    assert [v.video_id for v in pl.videos] == EXPECTED_IDS
    assert pl.video_urls[0] == "https://www.youtube.com/watch?v=KzdWLiaY7yo"
    assert session.posts[0]["continuation"].startswith(CONTINUATION_PREFIX)


def test_continuation_response_with_lockups_and_view_model_token(load_fixture):
    sec = load_fixture(FIXTURE)["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0][
        "tabRenderer"]["content"]["sectionListRenderer"]["contents"][0][
        "itemSectionRenderer"]["contents"]
    page = {"onResponseReceivedActions": [{"appendContinuationItemsAction": {
        "continuationItems": sec[:3] + [_view_model_token("NEXT")]}}]}
    ids, continuation = Playlist._extract_video_ids(page)
    assert ids == EXPECTED_IDS[:3]
    assert continuation == "NEXT"


def test_last_continuation_response_has_no_token(load_fixture):
    sec = load_fixture(FIXTURE)["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0][
        "tabRenderer"]["content"]["sectionListRenderer"]["contents"][0][
        "itemSectionRenderer"]["contents"]
    page = {"onResponseReceivedActions": [{"appendContinuationItemsAction": {
        "continuationItems": sec[:2]}}]}
    assert Playlist._extract_video_ids(page) == (EXPECTED_IDS[:2], None)


def test_old_and_new_item_shapes_in_one_list():
    page = {"onResponseReceivedActions": [{"appendContinuationItemsAction": {
        "continuationItems": [
            {"playlistVideoRenderer": {"videoId": "old1"}},
            {"lockupViewModel": {"contentId": "new1"}},
            {"lockupViewModel": {"contentId": "new1"}},
        ]}}]}
    assert Playlist._extract_video_ids(page) == (["old1", "new1"], None)


def test_channel_video_tab_follows_view_model_continuation():
    ch = Channel("https://youtube.com/@x")
    data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
        {"tabRenderer": {
            "endpoint": {"commandMetadata": {"webCommandMetadata": {"url": "/@x/videos"}}},
            "content": {"richGridRenderer": {"contents": [
                {"richItemRenderer": {"content": {"lockupViewModel": {"contentId": "v1"}}}},
                {"richItemRenderer": {"content": {"lockupViewModel": {"contentId": "v2"}}}},
                _view_model_token("CH-NEXT"),
            ]}},
        }}
    ]}}}
    videos, continuation = ch._extract_items(data, "videos")
    assert [v.video_id for v in videos] == ["v1", "v2"]
    assert continuation == "CH-NEXT"


def test_channel_playlists_follow_view_model_continuation():
    data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
        {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [
            {"itemSectionRenderer": {"contents": [
                {"gridRenderer": {"items": [
                    {"lockupViewModel": {"contentId": "PL1"}},
                    _view_model_token("PL-NEXT"),
                ]}}
            ]}}
        ]}}}}
    ]}}}
    assert Channel._extract_playlist_ids(data) == (["PL1"], "PL-NEXT")
