"""tutubo search-facet categories.

mediavocab classifies content along orthogonal axes — a
:class:`~mediavocab.text.classify.ClassificationResult` carries
``media_type``, ``content_form``, ``programme_format`` and
``content_genres``. tutubo's search API is organised around single,
human-facing *facets* ("documentaries", "live news", "music videos"), so
:class:`Category` collapses a ``ClassificationResult`` (plus the live /
upcoming flags YouTube exposes) back to one facet for filtering and
display.

`Category` is tutubo-owned; mediavocab is the source of truth for the
underlying multi-axis classification.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING, Iterable, Optional

from mediavocab.taxonomy import MediaType, ContentForm, ProgrammeFormat

if TYPE_CHECKING:
    from mediavocab.text.classify import ClassificationResult


class Category(str, Enum):
    """A single YouTube search facet, derived from a ``ClassificationResult``."""

    # Live
    LIVE = "live"
    LIVE_NEWS = "live_news"
    LIVE_RADIO = "live_radio"
    IPTV = "iptv"
    # Scheduled
    UPCOMING = "upcoming"
    # Film / TV
    MOVIE = "movie"
    SHORT_FILM = "short_film"
    TV_EPISODE = "tv_episode"
    ANIME = "anime"
    DOCUMENTARY = "documentary"
    CONCERT = "concert"
    STAND_UP = "stand_up"
    # Supplementary forms
    TRAILER = "trailer"
    BEHIND_THE_SCENES = "behind_the_scenes"
    REACTION = "reaction"
    SOCIAL_CLIP = "social_clip"
    COMPILATION = "compilation"
    # Talk / non-fiction
    NEWS = "news"
    SPORT = "sport"
    INTERVIEW = "interview"
    LECTURE = "lecture"
    TUTORIAL = "tutorial"
    PODCAST = "podcast"
    AUDIOBOOK = "audiobook"
    # Music
    MUSIC_VIDEO = "music_video"
    MUSIC_AUDIO = "music_audio"
    # Other
    GAMING = "gaming"
    KIDS = "kids"
    VIDEO = "video"


# ClassificationResult.content_form → Category (supplementary forms)
_FORM_TO_CATEGORY = {
    ContentForm.TRAILER: Category.TRAILER,
    ContentForm.TEASER: Category.TRAILER,
    ContentForm.BEHIND_SCENES: Category.BEHIND_THE_SCENES,
    ContentForm.REACTION: Category.REACTION,
    ContentForm.SOCIAL_CLIP: Category.SOCIAL_CLIP,
    ContentForm.EXCERPT: Category.SOCIAL_CLIP,
}

# ClassificationResult.programme_format → Category (non-fiction formats)
_FORMAT_TO_CATEGORY = {
    ProgrammeFormat.DOCUMENTARY: Category.DOCUMENTARY,
    ProgrammeFormat.NEWS: Category.NEWS,
    ProgrammeFormat.SPORTS: Category.SPORT,
    ProgrammeFormat.STAND_UP: Category.STAND_UP,
    ProgrammeFormat.CONCERT: Category.CONCERT,
    ProgrammeFormat.TALK_SHOW: Category.INTERVIEW,
}

# ClassificationResult.media_type → Category (structural fallback)
_MEDIA_TO_CATEGORY = {
    MediaType.MOVIE: Category.MOVIE,
    MediaType.SHORT_FILM: Category.SHORT_FILM,
    MediaType.EPISODIC_SERIES: Category.TV_EPISODE,
    MediaType.TV: Category.IPTV,
    MediaType.MUSIC_VIDEO: Category.MUSIC_VIDEO,
    MediaType.MUSIC: Category.MUSIC_AUDIO,
    MediaType.PODCAST: Category.PODCAST,
    MediaType.AUDIOBOOK: Category.AUDIOBOOK,
    MediaType.AUDIO_DRAMA: Category.AUDIOBOOK,
    MediaType.RADIO: Category.LIVE_RADIO,
    MediaType.GAME: Category.GAMING,
}


# mediavocab's own classifier has no children's-content signal (no genre,
# media_type or programme_format maps to it), so Category.KIDS is detected
# here from title / channel-keyword text — the same free-text sources
# ``extract_tags`` already draws on for the rest of tutubo's facets.
_KIDS_PATTERN = re.compile(
    r"\bkids\b|\bchild(?:ren)?\b|\btoddlers?\b|\bpreschool(?:er)?\b|nursery rhymes?",
    re.IGNORECASE,
)


def _looks_like_kids_content(title: str, tags: Optional[Iterable[str]] = None) -> bool:
    """True if ``title`` or any of ``tags`` reads as children's content."""
    if title and _KIDS_PATTERN.search(title):
        return True
    for t in tags or ():
        if t and _KIDS_PATTERN.search(t):
            return True
    return False


def classify_category(
    result: "ClassificationResult",
    *,
    is_live: bool = False,
    is_upcoming: bool = False,
    title: str = "",
    tags: Optional[Iterable[str]] = None,
) -> Category:
    """Collapse a mediavocab ``ClassificationResult`` to a single tutubo facet.

    Live and upcoming flags win first (they describe delivery, which
    overrides the content classification), then supplementary form, then
    programme format, then a media-type / genre fallback.

    ``title`` and ``tags`` (channel keywords) are optional and used only to
    detect :attr:`Category.KIDS` — mediavocab's ``ClassificationResult``
    carries no children's-content signal of its own.
    """
    genres = set(result.content_genres or [])

    if is_live:
        if result.programme_format == ProgrammeFormat.NEWS or "news" in genres:
            return Category.LIVE_NEWS
        if result.media_type == MediaType.RADIO:
            return Category.LIVE_RADIO
        return Category.LIVE

    if is_upcoming:
        return Category.UPCOMING

    # Supplementary form (trailer / reaction / behind-the-scenes / clip)
    form_cat = _FORM_TO_CATEGORY.get(result.content_form)
    if form_cat is not None:
        return form_cat

    # Genre-driven facets that have no dedicated MediaType
    if "anime" in genres:
        return Category.ANIME
    if "gaming" in genres:
        return Category.GAMING
    if _looks_like_kids_content(title, tags):
        return Category.KIDS

    # Non-fiction programme format
    fmt_cat = _FORMAT_TO_CATEGORY.get(result.programme_format)
    if fmt_cat is not None:
        return fmt_cat

    # Structural media-type fallback
    return _MEDIA_TO_CATEGORY.get(result.media_type, Category.VIDEO)
