"""Tests for tutubo's ``classify_category`` collapse.

The multi-axis classification logic (duration thresholds, keyword regexes,
priority ordering) lives in ``mediavocab.text.classify`` and is tested there.
tutubo's responsibility is collapsing a ``ClassificationResult`` to a single
search facet (:class:`tutubo.classification.Category`), so these tests build
``ClassificationResult`` objects directly and assert the facet — independent
of the classifier's keyword behaviour.

A handful of integration checks at the end run real titles through
``classify_video`` → ``classify_category`` for the facets the classifier
reliably emits.
"""
import pytest

from mediavocab.taxonomy import MediaType, ContentForm, ProgrammeFormat
from mediavocab.text import classify_video
from mediavocab.text.classify import ClassificationResult

from tutubo import Category, ContentType, classify_category


def _r(media_type=None, content_form=ContentForm.PRIMARY,
       programme_format=None, content_genres=None):
    return ClassificationResult(
        media_type=media_type,
        content_form=content_form,
        programme_format=programme_format,
        content_genres=content_genres or [],
    )


# ---------------------------------------------------------------------------
# Back-compat alias
# ---------------------------------------------------------------------------

def test_contenttype_is_category_alias():
    assert ContentType is Category


# ---------------------------------------------------------------------------
# Live / upcoming flags win first (delivery overrides content)
# ---------------------------------------------------------------------------

class TestLiveUpcoming:
    def test_generic_live(self):
        assert classify_category(_r(media_type=MediaType.MOVIE), is_live=True) == Category.LIVE

    def test_live_news_via_programme_format(self):
        r = _r(media_type=MediaType.TV, programme_format=ProgrammeFormat.NEWS)
        assert classify_category(r, is_live=True) == Category.LIVE_NEWS

    def test_live_news_via_genre(self):
        r = _r(media_type=MediaType.TV, content_genres=["news"])
        assert classify_category(r, is_live=True) == Category.LIVE_NEWS

    def test_live_radio(self):
        assert classify_category(_r(media_type=MediaType.RADIO), is_live=True) == Category.LIVE_RADIO

    def test_live_beats_trailer_form(self):
        r = _r(media_type=MediaType.MOVIE, content_form=ContentForm.TRAILER)
        assert classify_category(r, is_live=True) == Category.LIVE

    def test_upcoming(self):
        assert classify_category(_r(media_type=MediaType.MOVIE), is_upcoming=True) == Category.UPCOMING

    def test_live_beats_upcoming(self):
        r = _r(media_type=MediaType.MOVIE)
        assert classify_category(r, is_live=True, is_upcoming=True) == Category.LIVE


# ---------------------------------------------------------------------------
# Supplementary content_form
# ---------------------------------------------------------------------------

class TestContentForm:
    @pytest.mark.parametrize("form,expected", [
        (ContentForm.TRAILER, Category.TRAILER),
        (ContentForm.TEASER, Category.TRAILER),
        (ContentForm.BEHIND_SCENES, Category.BEHIND_THE_SCENES),
        (ContentForm.REACTION, Category.REACTION),
        (ContentForm.SOCIAL_CLIP, Category.SOCIAL_CLIP),
        (ContentForm.EXCERPT, Category.SOCIAL_CLIP),
    ])
    def test_form_maps_to_facet(self, form, expected):
        assert classify_category(_r(media_type=MediaType.MOVIE, content_form=form)) == expected

    def test_form_beats_media_type(self):
        # A trailer for a movie is a TRAILER, not a MOVIE.
        r = _r(media_type=MediaType.MOVIE, content_form=ContentForm.TRAILER)
        assert classify_category(r) == Category.TRAILER


# ---------------------------------------------------------------------------
# Genre-driven facets (no dedicated MediaType)
# ---------------------------------------------------------------------------

class TestGenreFacets:
    def test_anime(self):
        r = _r(media_type=MediaType.MOVIE, content_genres=["anime"])
        assert classify_category(r) == Category.ANIME

    def test_gaming(self):
        r = _r(media_type=MediaType.GAME, content_genres=["gaming"])
        assert classify_category(r) == Category.GAMING


# ---------------------------------------------------------------------------
# Programme format → non-fiction facet
# ---------------------------------------------------------------------------

class TestProgrammeFormat:
    @pytest.mark.parametrize("fmt,expected", [
        (ProgrammeFormat.DOCUMENTARY, Category.DOCUMENTARY),
        (ProgrammeFormat.NEWS, Category.NEWS),
        (ProgrammeFormat.SPORTS, Category.SPORT),
        (ProgrammeFormat.STAND_UP, Category.STAND_UP),
        (ProgrammeFormat.CONCERT, Category.CONCERT),
        (ProgrammeFormat.TALK_SHOW, Category.INTERVIEW),
    ])
    def test_format_maps_to_facet(self, fmt, expected):
        assert classify_category(_r(media_type=MediaType.MOVIE, programme_format=fmt)) == expected


# ---------------------------------------------------------------------------
# Structural media-type fallback
# ---------------------------------------------------------------------------

class TestMediaTypeFallback:
    @pytest.mark.parametrize("mt,expected", [
        (MediaType.MOVIE, Category.MOVIE),
        (MediaType.SHORT_FILM, Category.SHORT_FILM),
        (MediaType.EPISODIC_SERIES, Category.TV_EPISODE),
        (MediaType.TV, Category.IPTV),
        (MediaType.MUSIC_VIDEO, Category.MUSIC_VIDEO),
        (MediaType.MUSIC, Category.MUSIC_AUDIO),
        (MediaType.PODCAST, Category.PODCAST),
        (MediaType.AUDIOBOOK, Category.AUDIOBOOK),
        (MediaType.GAME, Category.GAMING),
    ])
    def test_media_type_maps_to_facet(self, mt, expected):
        assert classify_category(_r(media_type=mt)) == expected

    def test_unknown_falls_through_to_video(self):
        assert classify_category(_r(media_type=None)) == Category.VIDEO


# ---------------------------------------------------------------------------
# Integration — real titles through classify_video → classify_category
# (only facets the mediavocab classifier reliably emits)
# ---------------------------------------------------------------------------

def _facet(title, **kw):
    is_live = kw.pop("is_live", False)
    is_upcoming = kw.pop("is_upcoming", False)
    result = classify_video(title=title, is_live=is_live, is_upcoming=is_upcoming, **kw)
    return classify_category(result, is_live=is_live, is_upcoming=is_upcoming)


class TestIntegration:
    def test_live(self):
        assert _facet("anything", is_live=True) == Category.LIVE

    def test_upcoming(self):
        assert _facet("anything", is_upcoming=True) == Category.UPCOMING

    def test_trailer(self):
        assert _facet("Dune: Part Two — Official Trailer") == Category.TRAILER

    def test_documentary(self):
        assert _facet("The Universe — Documentary") == Category.DOCUMENTARY

    def test_music_video(self):
        assert _facet("Artist - Song (Official Music Video)") == Category.MUSIC_VIDEO

    def test_movie(self):
        assert _facet("Full Movie HD", length=7200) == Category.MOVIE

    def test_podcast(self):
        assert _facet("Episode 400", is_podcast=True) == Category.PODCAST

    def test_reaction(self):
        assert _facet("My reaction to the new trailer") == Category.REACTION

    def test_stand_up(self):
        assert _facet("Comedian — Full Stand-Up Comedy Special") == Category.STAND_UP

    def test_gaming(self):
        assert _facet("Minecraft Gameplay Walkthrough") == Category.GAMING

    def test_as_value_serialisable(self):
        # Category is a str enum — facets serialise to their string value.
        assert _facet("anything", is_live=True).value == "live"
