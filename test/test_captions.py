"""Caption track listing from recorded-shape player responses (no network)."""
import json

import pytest

from tutubo.captions import (CaptionError, CaptionTrack, list_caption_tracks,
                             original_tracks, parse_caption_tracks)
from tutubo._utils import _HTMLParseError, player_response

WATCH = "https://www.youtube.com/api/timedtext?v=abcdefghijk&caps=asr&lang="

TRANSLATIONS = [
    {"languageCode": "pt", "languageName": {"simpleText": "Portuguese"}},
    {"languageCode": "en", "languageName": {"runs": [{"text": "English"}]}},
    {"languageCode": "de", "languageName": {"simpleText": "German"}},
]


def _manual(lang="en", name="English", translatable=True):
    return {"baseUrl": f"{WATCH}{lang}", "name": {"simpleText": name},
            "vssId": f".{lang}", "languageCode": lang, "isTranslatable": translatable}


def _asr(lang="en", name="English (auto-generated)", translatable=True):
    return {"baseUrl": f"{WATCH}{lang}&kind=asr", "name": {"runs": [{"text": name}]},
            "vssId": f"a.{lang}", "languageCode": lang, "kind": "asr",
            "isTranslatable": translatable}


def _player(tracks=None, translations=(), status="OK", **extra):
    resp = {"videoDetails": {"videoId": "abcdefghijk"},
            "playabilityStatus": {"status": status, **extra}}
    if tracks is not None:
        resp["captions"] = {"playerCaptionsTracklistRenderer": {
            "captionTracks": tracks, "translationLanguages": list(translations)}}
    return resp


def test_manual_track():
    tracks = parse_caption_tracks(_player([_manual("pt", "Portuguese")]))
    assert tracks == [CaptionTrack("pt", "Portuguese", "manual", url=WATCH + "pt")]


def test_asr_track_kind_and_run_name():
    (t,) = parse_caption_tracks(_player([_asr("pt")]))
    assert (t.language, t.kind, t.is_translation) == ("pt", "asr", False)
    assert t.name == "English (auto-generated)"


def test_asr_detected_from_kind_without_vssid():
    raw = _asr("fr")
    del raw["vssId"]
    (t,) = parse_caption_tracks(_player([raw]))
    assert t.kind == "asr"


def test_asr_detected_from_vssid_without_kind():
    raw = _asr("fr")
    del raw["kind"]
    (t,) = parse_caption_tracks(_player([raw]))
    assert t.kind == "asr"


def test_manual_and_asr_together():
    tracks = parse_caption_tracks(_player([_manual("pt"), _asr("pt")]))
    assert [(t.language, t.kind) for t in tracks] == [("pt", "manual"), ("pt", "asr")]


def test_no_captions_key():
    assert parse_caption_tracks(_player(None)) == []


def test_captions_disabled_empty_track_list():
    assert parse_caption_tracks(_player([], TRANSLATIONS)) == []


def test_translations_are_marked_and_point_to_source():
    tracks = parse_caption_tracks(_player([_asr("pt")], TRANSLATIONS))
    translated = [t for t in tracks if t.is_translation]
    assert [t.language for t in translated] == ["en", "de"]  # not pt into pt
    for t in translated:
        assert t.source_language == "pt"
        assert (t.kind, t.source_kind) == ("translation", "asr")
        assert t.url.endswith(f"&tlang={t.language}")
    assert translated[0].name == "English"


def test_original_tracks_exclude_translations():
    tracks = parse_caption_tracks(_player([_manual("pt"), _asr("pt")], TRANSLATIONS))
    assert len(tracks) == 2 + 2 * 2
    originals = original_tracks(tracks)
    assert [(t.language, t.kind) for t in originals] == [("pt", "manual"), ("pt", "asr")]
    assert not any(t.is_translation for t in originals)


def test_non_translatable_track_gets_no_translations():
    tracks = parse_caption_tracks(_player([_asr("pt", translatable=False)], TRANSLATIONS))
    assert len(tracks) == 1


def test_translation_languages_without_tracks_give_nothing():
    assert parse_caption_tracks(_player([], TRANSLATIONS)) == []


def test_track_with_tlang_url_is_a_translation():
    raw = _asr("pt")
    raw["languageCode"] = "pt"
    raw["baseUrl"] += "&tlang=en"
    (t,) = parse_caption_tracks(_player([raw]))
    assert (t.language, t.is_translation, t.source_language) == ("en", True, "pt")
    assert original_tracks([t]) == []


def test_translation_of_manual_track_has_its_own_kind():
    tracks = parse_caption_tracks(_player([_manual("pt")], TRANSLATIONS))
    translated = [t for t in tracks if t.is_translation]
    assert translated
    for t in translated:
        assert (t.kind, t.source_kind, t.source_language) == ("translation", "manual", "pt")


@pytest.mark.parametrize("kind", ["manual", "asr"])
def test_kind_filter_never_yields_a_translation(kind):
    tracks = parse_caption_tracks(_player([_manual("pt"), _asr("pt")], TRANSLATIONS))
    picked = [t for t in tracks if t.kind == kind]
    assert len(picked) == 1
    assert not any(t.is_translation for t in picked)


def test_translating_a_translated_track_is_not_offered():
    raw = _manual("pt")
    raw["baseUrl"] += "&tlang=en"
    tracks = parse_caption_tracks(_player([raw], TRANSLATIONS))
    assert len(tracks) == 1
    assert tracks[0].kind == "translation" and tracks[0].source_kind == "manual"


@pytest.mark.parametrize("status", ["ERROR", "LOGIN_REQUIRED", "UNPLAYABLE"])
def test_unplayable_video_raises(status):
    with pytest.raises(CaptionError, match=status):
        parse_caption_tracks(_player(None, status=status, reason="gone"))


def test_caption_error_is_a_runtime_error():
    assert issubclass(CaptionError, RuntimeError)


@pytest.mark.parametrize("player", [
    {}, {"playabilityStatus": {}}, {"playabilityStatus": None},
    {"playabilityStatus": {"status": None}},
])
def test_missing_playability_status_raises(player):
    with pytest.raises(CaptionError):
        parse_caption_tracks(player)


@pytest.mark.parametrize("renderer", [
    {"captions": None},
    {"captions": {"playerCaptionsTracklistRenderer": None}},
    {"captions": {"playerCaptionsTracklistRenderer": {"captionTracks": None}}},
    {"captions": {"playerCaptionsTracklistRenderer": {
        "captionTracks": [{**_manual(), "name": "English"}]}}},
    {"captions": {"playerCaptionsTracklistRenderer": {
        "captionTracks": [_manual()], "translationLanguages": None}}},
])
def test_malformed_shapes_raise(renderer):
    player = {"playabilityStatus": {"status": "OK"}, **renderer}
    with pytest.raises(CaptionError):
        parse_caption_tracks(player)


@pytest.mark.parametrize("renderer", [
    {"captionTracks": {}}, {"captionTracks": ""},
    {"captionTracks": [_manual()], "translationLanguages": {}},
    {"captionTracks": [_manual()], "translationLanguages": "en"},
])
def test_track_lists_must_be_lists(renderer):
    player = {"playabilityStatus": {"status": "OK"},
              "captions": {"playerCaptionsTracklistRenderer": renderer}}
    with pytest.raises(CaptionError):
        parse_caption_tracks(player)


def test_unparseable_track_url_raises_caption_error():
    track = {**_manual(), "baseUrl": "http://[::1/x?tlang=en"}
    with pytest.raises(CaptionError):
        parse_caption_tracks(_player([track]))


def test_as_dict():
    t = CaptionTrack("en", "English", "translation", True, "pt", "asr", "http://x")
    assert t.as_dict == {
        "language": "en", "name": "English", "kind": "translation",
        "is_translation": True, "source_language": "pt", "source_kind": "asr",
        "url": "http://x",
    }


class _Resp:
    def __init__(self, text, error=None):
        self.text = text
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error


class _Session:
    def __init__(self, text, error=None, raises=None):
        self.text = text
        self.error = error
        self.raises = raises
        self.urls = []
        self.calls = []

    def get(self, url, **kw):
        if self.raises:
            raise self.raises
        self.urls.append(url)
        self.calls.append(kw)
        return _Resp(self.text, self.error)


def _page(player):
    return ("<html><script>var ytInitialPlayerResponse = "
            + json.dumps(player) + ";var meta = document.createElement('div');</script></html>")


def test_list_from_watch_page_by_id_and_url():
    s = _Session(_page(_player([_manual("pt"), _asr("pt")], TRANSLATIONS)))
    by_id = list_caption_tracks("abcdefghijk", session=s)
    by_url = list_caption_tracks("https://youtu.be/abcdefghijk", session=s)
    assert by_id == by_url
    assert s.urls == ["https://www.youtube.com/watch?v=abcdefghijk"] * 2
    assert len(original_tracks(by_id)) == 2


def test_request_options():
    from tutubo.channel import _YT_COOKIES
    s = _Session(_page(_player([])))
    list_caption_tracks("abcdefghijk", session=s, language="pt-PT")
    (kw,) = s.calls
    assert kw["headers"]["Accept-Language"] == "pt-PT"
    assert kw["cookies"] == _YT_COOKIES
    assert kw["timeout"] == 30


def test_video_method():
    from tutubo.channel import Video
    s = _Session(_page(_player([_asr("pt")])))
    (t,) = Video("abcdefghijk").caption_tracks(session=s)
    assert t.kind == "asr"


def test_family_selects_the_session(monkeypatch):
    from tutubo import captions
    from tutubo.channel import Video
    s = _Session(_page(_player([_asr("pt")])))
    families = []
    monkeypatch.setattr(captions, "make_session", lambda f: families.append(f) or s)
    list_caption_tracks("abcdefghijk", family="ipv4")
    Video("abcdefghijk").caption_tracks(family="ipv6")
    assert families == ["ipv4", "ipv6"]


def test_page_without_player_response_raises():
    with pytest.raises(CaptionError):
        list_caption_tracks("abcdefghijk", session=_Session("<html></html>"))


def test_http_error_raises():
    s = _Session(_page(_player([_manual()])), error=OSError("503"))
    with pytest.raises(CaptionError, match="503"):
        list_caption_tracks("abcdefghijk", session=s)


def test_connection_error_raises():
    with pytest.raises(CaptionError):
        list_caption_tracks("abcdefghijk", session=_Session("", raises=ConnectionError("down")))


@pytest.mark.parametrize("page", [
    "<script>ytInitialPlayerResponse =", "<script>ytInitialPlayerResponse = ",
    "<script>ytInitialPlayerResponse = null;</script>",
    "<script>ytInitialPlayerResponse = {\"a\": ",
])
def test_truncated_or_non_object_page_raises(page):
    with pytest.raises(CaptionError):
        list_caption_tracks("abcdefghijk", session=_Session(page))


def test_response_for_another_video_raises():
    player = _player([_manual()])
    player["videoDetails"]["videoId"] = "zzzzzzzzzzz"
    with pytest.raises(CaptionError, match="zzzzzzzzzzz"):
        list_caption_tracks("abcdefghijk", session=_Session(_page(player)))


def test_response_without_video_id_raises():
    player = _player([_manual()])
    del player["videoDetails"]
    with pytest.raises(CaptionError):
        list_caption_tracks("abcdefghijk", session=_Session(_page(player)))


def test_player_response_skips_a_non_object_match():
    page = ("<script>var ytInitialPlayerResponse = [1];</script>"
            "<script>ytInitialPlayerResponse = " + json.dumps({"ok": 1}) + ";</script>")
    assert player_response(page) == {"ok": 1}


def test_player_response_truncated_raises_parse_error():
    with pytest.raises(_HTMLParseError):
        player_response("ytInitialPlayerResponse =")


def test_unplayable_page_without_video_details_reports_the_status():
    player = {"playabilityStatus": {"status": "LOGIN_REQUIRED", "reason": "private"}}
    with pytest.raises(CaptionError, match=r"not playable \(LOGIN_REQUIRED\): private"):
        list_caption_tracks("abcdefghijk", session=_Session(_page(player)))


def test_playable_response_with_another_video_id_raises_wrong_video():
    player = _player([_manual()])
    player["videoDetails"]["videoId"] = "zzzzzzzzzzz"
    with pytest.raises(CaptionError, match="requested 'abcdefghijk'"):
        list_caption_tracks("abcdefghijk", session=_Session(_page(player)))


def test_player_response_skips_an_unparseable_match():
    page = ("<script>ytInitialPlayerResponse = {\"a\": </script>"
            "<script>ytInitialPlayerResponse = " + json.dumps({"ok": 1}) + ";</script>")
    assert player_response(page) == {"ok": 1}


def test_public_names_are_exported():
    import tutubo
    from tutubo import CaptionError, CaptionTrack, list_caption_tracks, original_tracks
    for name in ("CaptionError", "CaptionTrack", "list_caption_tracks", "original_tracks"):
        assert name in tutubo.__all__
