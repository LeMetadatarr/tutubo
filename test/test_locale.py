"""Tests for the (stateless, thread-safe) mediavocab locale system."""
import shutil
from pathlib import Path
from unittest.mock import patch

import mediavocab.locale as _locale_mod
from mediavocab.locale import voc_regex, voc_set
from tutubo import ContentType, classify_category
from mediavocab.text import classify_video


def _facet(*a, **kw):
    return classify_category(classify_video(*a, **kw))


def test_voc_regex_movie_keywords_matches():
    rx = voc_regex("movie_keywords", lang="en-us")
    assert rx is not None
    assert rx.search("Full Movie 2024")
    assert rx.search("Watch this full film tonight")


def test_voc_regex_documentary_keywords_matches():
    rx = voc_regex("documentary_keywords", lang="en-us")
    assert rx is not None
    assert rx.search("A Documentary About Climate")
    assert rx.search("Watch this docuseries now")


def test_voc_regex_missing_file_returns_none(tmp_path):
    """A voc name that does not exist in any locale returns None."""
    with patch.object(_locale_mod, "_LOCALE_DIR", tmp_path):
        _locale_mod._load_voc.cache_clear()
        _locale_mod._voc_regex.cache_clear()
        _locale_mod._voc_set.cache_clear()
        result = voc_regex("nonexistent_file", lang="en-us")
    assert result is None


def test_fallback_unknown_lang_uses_en_us():
    rx = voc_regex("movie_keywords", lang="xx-xx")
    assert rx is not None
    assert rx.search("full movie")


def test_non_english_locale_classify_video(tmp_path):
    de_dir = tmp_path / "de-de"
    de_dir.mkdir()
    (de_dir / "movie_keywords.voc").write_text(
        "kompletter film\nganzer film\n", encoding="utf-8"
    )
    en_us_src = Path(_locale_mod._LOCALE_DIR) / "en-us"
    shutil.copytree(en_us_src, tmp_path / "en-us")

    with patch.object(_locale_mod, "_LOCALE_DIR", tmp_path):
        _locale_mod._load_voc.cache_clear()
        _locale_mod._voc_regex.cache_clear()
        _locale_mod._voc_set.cache_clear()

        result = _facet(
            "kompletter Film - Action 2024", length=7200, lang="de-de"
        )
        assert result == ContentType.MOVIE


def test_classify_video_english_defaults():
    assert _facet("Full Movie HD 2023", length=7200, lang="en-us") == ContentType.MOVIE
    assert _facet("Avengers Official Trailer", lang="en-us") == ContentType.TRAILER
    assert _facet("Nature Documentary Series", lang="en-us") == ContentType.DOCUMENTARY


def test_concurrent_lang_isolation():
    """Calls with different lang= are independently cached and never collide."""
    rx_en = voc_regex("movie_keywords", lang="en-us")
    rx_pt = voc_regex("movie_keywords", lang="pt-pt")
    assert rx_en is not None and rx_pt is not None
    assert voc_regex("movie_keywords", lang="en-us") is rx_en
