"""Caption tracks of a video, read from the watch page's player response.

YouTube lists a video's own tracks (``captionTracks``: human-made, or the
speech recogniser's output with ``kind: "asr"``) and, separately, the languages
any translatable track can be machine-translated into
(``translationLanguages``, fetched with a ``tlang`` query parameter). A
translation is not a transcript of the audio, so :class:`CaptionTrack` marks
it and :func:`original_tracks` leaves it out.

Every failure to read a video's tracks raises :class:`CaptionError`, so an
empty list always means the video is playable and offers none. The watch-page
read is a ``details`` request of the shared back-off (:mod:`tutubo.backoff`):
while that kind is paused, or when YouTube answers with a bot check, it raises
:class:`tutubo.backoff.BackedOff` instead.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from tutubo import backoff
from tutubo._utils import _HTMLParseError, player_response, video_id as _video_id
from tutubo.transport import default_session, make_session


class CaptionError(RuntimeError):
    """The tracks of a video could not be read: the request failed, the page
    holds no usable player response, the response is for another video, or the
    video is not playable. Not raised when a playable video has no captions."""


@dataclass(frozen=True)
class CaptionTrack:
    """One caption track offered for a video.

    ``kind`` is ``"manual"`` (uploaded by a person), ``"asr"`` (YouTube's
    automatic recognition) or ``"translation"`` (machine translation of
    another track). For a translation ``is_translation`` is True,
    ``source_language`` is the language of the track it was translated from
    and ``source_kind`` is that track's kind.
    """
    language: str
    name: str
    kind: str
    is_translation: bool = False
    source_language: Optional[str] = None
    source_kind: Optional[str] = None
    url: str = ""

    @property
    def as_dict(self) -> dict:
        return {
            "language": self.language,
            "name": self.name,
            "kind": self.kind,
            "is_translation": self.is_translation,
            "source_language": self.source_language,
            "source_kind": self.source_kind,
            "url": self.url,
        }


def _label(node: dict) -> str:
    if "simpleText" in node:
        return node["simpleText"]
    return "".join(r.get("text", "") for r in node.get("runs", []))


def _kind(track: dict) -> str:
    # asr tracks carry kind "asr" and a vssId of the form "a.<lang>"
    if track.get("kind") == "asr" or track.get("vssId", "").startswith("a."):
        return "asr"
    return "manual"


def parse_caption_tracks(player: dict) -> List[CaptionTrack]:
    """Tracks listed in a player response: the video's own tracks first, then
    one machine translation per translatable track and translation language.

    Raises :class:`CaptionError` when the video is not playable or the
    response is malformed, since its captions cannot then be told apart from
    having none.
    """
    try:
        return _parse(player)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CaptionError(f"malformed player response: {exc}") from exc


def _parse(player: dict) -> List[CaptionTrack]:
    status = player.get("playabilityStatus")
    if not isinstance(status, dict) or not status.get("status"):
        raise CaptionError("player response has no playability status")
    if status["status"] != "OK":
        raise CaptionError(
            f"video not playable ({status['status']}): {status.get('reason', '')}")
    listing = player.get("captions", {}).get("playerCaptionsTracklistRenderer", {})
    raw_tracks = listing.get("captionTracks", [])
    languages = listing.get("translationLanguages", [])
    if not isinstance(raw_tracks, list) or not isinstance(languages, list):
        raise CaptionError("caption listing holds no track lists")
    tracks: List[CaptionTrack] = []
    translatable: List[CaptionTrack] = []
    for raw in raw_tracks:
        url = raw.get("baseUrl", "")
        tlang = parse_qs(urlparse(url).query).get("tlang", [None])[0]
        kind = _kind(raw)
        track = CaptionTrack(
            language=tlang or raw.get("languageCode", ""),
            name=_label(raw.get("name", {})),
            kind="translation" if tlang else kind,
            is_translation=tlang is not None,
            source_language=raw.get("languageCode") if tlang else None,
            source_kind=kind if tlang else None,
            url=url,
        )
        tracks.append(track)
        if raw.get("isTranslatable") and not track.is_translation:
            translatable.append(track)
    for source in translatable:
        for lang in languages:
            code = lang.get("languageCode", "")
            if code and code != source.language:
                tracks.append(CaptionTrack(
                    language=code,
                    name=_label(lang.get("languageName", {})),
                    kind="translation",
                    is_translation=True,
                    source_language=source.language,
                    source_kind=source.kind,
                    url=f"{source.url}&tlang={code}",
                ))
    return tracks


def original_tracks(tracks: List[CaptionTrack]) -> List[CaptionTrack]:
    """The tracks that are not machine translations: automatic tracks, which
    transcribe the audio, and manual ones, which may be subtitles in another
    language."""
    return [t for t in tracks if not t.is_translation]


def watch_player(video: str, session: Optional[object] = None,
                 family: Optional[str] = None,
                 language: str = "en-US,en;q=0.9") -> Tuple[str, dict]:
    """``(video id, player response)`` read from the video's watch page: one
    request of the back-off kind ``details``.

    Raises :class:`tutubo.backoff.BackedOff` without sending anything while
    ``details`` is paused, and after starting the pause when YouTube answers
    with a bot check (HTTP 429, or a page that asks to confirm you are not a
    bot). Raises :class:`CaptionError` when the page cannot be read.
    """
    from tutubo.channel import _YT_COOKIES, _YT_HEADERS
    if session is None:
        session = default_session() if family is None else make_session(family)
    vid = _video_id(video) if "/" in video or "=" in video else video
    backoff.check("details")
    started = time.time()
    try:
        resp = session.get(
            f"https://www.youtube.com/watch?v={vid}",
            headers={**_YT_HEADERS, "Accept-Language": language},
            cookies=_YT_COOKIES,
            timeout=30,
        )
    except Exception as exc:
        raise CaptionError(f"could not read the watch page of {vid}: {exc}") from exc
    status = getattr(resp, "status_code", 200)
    if status == 429 or (isinstance(status, int) and status >= 400
                         and backoff.is_bot_check(getattr(resp, "text", ""))):
        _bot_check(f"HTTP {status}")
    try:
        resp.raise_for_status()
        player = player_response(resp.text)
    except Exception as exc:
        raise CaptionError(f"could not read the watch page of {vid}: {exc}") from exc
    playability = player.get("playabilityStatus") if isinstance(player, dict) else None
    if isinstance(playability, dict) and playability.get("status") != "OK":
        reason = " ".join(str(playability.get(k) or "") for k in ("reason", "messages"))
        if backoff.is_bot_check(reason):
            _bot_check(reason)
    backoff.after_success("details", started)
    return vid, player


def _bot_check(reason: str) -> None:
    if backoff.failed("details", reason):
        raise backoff.paused("details")


def list_caption_tracks(video: str, session: Optional[object] = None,
                        family: Optional[str] = None,
                        language: str = "en-US,en;q=0.9") -> List[CaptionTrack]:
    """Fetch a video's watch page and list its caption tracks.

    ``video`` is a video id or URL. An empty list means the video is playable
    and offers no captions (including captions disabled by the uploader).
    Raises :class:`CaptionError` when that cannot be told.
    """
    vid, player = watch_player(video, session=session, family=family, language=language)
    tracks = parse_caption_tracks(player)
    returned = (player.get("videoDetails") or {}).get("videoId")
    if returned != vid:
        raise CaptionError(f"player response is for {returned!r}, requested {vid!r}")
    return tracks
