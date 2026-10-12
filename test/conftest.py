"""Pytest configuration and fixture helpers for tutubo tests.

Offline testing strategy
------------------------
Raw YouTube/innertube API responses are stored as JSON files under
``test/fixtures/``.  The ``innertube_fixture`` fixture monkeypatches
``tutubo._innertube._post`` so tests never touch the network.

Recording fixtures
------------------
Set ``TUTUBO_RECORD_DIR=test/fixtures`` and run:

    python test/record_fixtures.py

or any script that exercises tutubo.  All innertube responses will be
written to that directory automatically.

Submitting fixtures for bug reports
------------------------------------
If you encounter geo-blocked or region-specific behaviour, run::

    TUTUBO_RECORD_DIR=/tmp/my_fixtures python -c "
    from tutubo import YoutubeSearch
    list(YoutubeSearch('your query').iterate_videos(max_res=5))
    "

and attach the resulting JSON files to your GitHub issue.
"""
import json
import re
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    """Load a JSON fixture by filename (with or without .json extension)."""
    if not name.endswith(".json"):
        name += ".json"
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def load_fixture():
    """Return a callable that loads a fixture file by name."""
    return _load


@pytest.fixture
def patch_innertube(monkeypatch):
    """Patch _innertube._post to serve responses from fixture files.

    The fixture name is derived from the query: spaces → underscores, lowercased,
    prefixed with ``search_``.  Example: query ``"rob zombie"`` → ``search_rob_zombie.json``.

    If a matching fixture does not exist the test will raise FileNotFoundError —
    run ``test/record_fixtures.py`` to capture it first.
    """
    import tutubo._innertube as _it

    # Empty response that terminates pagination cleanly (no contents, no continuation)
    _EMPTY_CONTINUATION = {"onResponseReceivedCommands": [{"appendContinuationItemsAction": {"continuationItems": []}}]}

    def _fake_post(endpoint: str, params: dict, body: dict) -> dict:
        if "continuation" in body:
            # Continuation page — return empty terminator; fixture tests cover only page 1
            return _EMPTY_CONTINUATION
        query = body.get("query") or params.get("query") or "unknown"
        safe = re.sub(r"[^\w]", "_", query.lower())[:60]
        path = FIXTURES_DIR / f"{endpoint}_{safe}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No fixture for query {query!r}.\n"
                f"Expected: {path}\n"
                "Run test/record_fixtures.py to capture it."
            )
        return json.loads(path.read_text())

    monkeypatch.setattr(_it, "_post", _fake_post)


@pytest.fixture
def patch_channel_data(monkeypatch):
    """Patch Channel._get_data to serve ytInitialData from JSON fixture files.

    Fixture files are stored as ``test/fixtures/channel_{slug}.json``.
    Slug mapping: ``@Handle/tab`` → ``handle_tab`` (handle lowercased, @ stripped).

    Continuation POSTs return an empty action list to stop pagination after page 1.
    """
    import tutubo.channel as _ch

    _SLUG_MAP = {
        # videos tabs
        "@watchdust/videos":          "watchdust_videos",
        "@watchalter/videos":         "watchalter_videos",
        "@omeleto/videos":            "omeleto_videos",
        "@mosfilm_eng/videos":        "mosfilm_eng_videos",
        "@cultcinemaclassics/videos": "cultcinemaclassics_videos",
        "@moonflix_official/videos":  "moonflix_official_videos",
        "@thedissenterrl/videos":     "thedissenterrl_videos",
        "@overlysarcasticproductions/videos": "overlysarcasticproductions_videos",
        "@pbsspacetime/videos":       "pbsspacetime_videos",
        "@eons/videos":               "eons_videos",
        "@pbsinfiniteseries/videos":  "pbsinfiniteseries_videos",
        "@pbsdocumentaries/videos":   "pbsdocumentaries_videos",
        "@kurzgesagt/videos":         "kurzgesagt_videos",
        "@knowledgia/videos":         "knowledgia_videos",
        "@markiplier/videos":         "markiplier_videos",
        "@bbcnews/videos":            "bbcnews_videos",
        "@pinkfongbabyshark/videos":  "pinkfongbabyshark_videos",
        "@3blue1brown/videos":        "3blue1brown_videos",
        "@comedycentral/videos":      "comedycentral_videos",
        "@livenation/videos":         "livenation_videos",
        # podcasts tab
        "@thedissenterrl/podcasts":   "thedissenterrl_podcasts",
        # youtube-only music channels (not on YouTube Music)
        "@stonedmeadowofdoom/videos": "stonedmeadowofdoom_videos",
        "@bmpromotion/videos":        "bmpromotion_videos",
        "@newsovietwave/videos":      "newsovietwave_videos",
        # home pages (for channel keywords / tags)
        "@watchdust":          "watchdust_home",
        "@watchalter":         "watchalter_home",
        "@omeleto":            "omeleto_home",
        "@mosfilm_eng":        "mosfilm_eng_home",
        "@cultcinemaclassics": "cultcinemaclassics_home",
        "@moonflix_official":  "moonflix_official_home",
        "@thedissenterrl":     "thedissenterrl_home",
        "@pbsdocumentaries":   "pbsdocumentaries_home",
        "@kurzgesagt":         "kurzgesagt_home",
        "@knowledgia":         "knowledgia_home",
        "@markiplier":         "markiplier_home",
        "@bbcnews":            "bbcnews_home",
        "@pinkfongbabyshark":  "pinkfongbabyshark_home",
        "@3blue1brown":        "3blue1brown_home",
        "@comedycentral":      "comedycentral_home",
        "@livenation":         "livenation_home",
        # youtube-only music channels — home pages
        "@stonedmeadowofdoom": "stonedmeadowofdoom_home",
        "@bmpromotion":        "bmpromotion_home",
        "@newsovietwave":      "newsovietwave_home",
        # live news channels — /streams tab (Channel.streams) and /live redirect (Channel.live)
        "@euronews/streams":          "euronews_live",
        "@france24_en/streams":       "france24_live",
        "@aljazeeraenglish/streams":  "aljazeera_live",
        "@euronewses/streams":        "euronewses_live",
        "@euronews/live":             "euronews_current_live",
        "@france24_en/live":          "france24_current_live",
        "@aljazeeraenglish/live":     "aljazeera_current_live",
        "@euronewses/live":           "euronewses_current_live",
        "@euronews":               "euronews_home",
        "@france24_en":            "france24_home",
        "@aljazeeraenglish":       "aljazeera_home",
        "@euronewses":             "euronewses_home",
    }

    _EMPTY_CONT = json.dumps({"onResponseReceivedActions": [
        {"appendContinuationItemsAction": {"continuationItems": []}}
    ]})

    def _fake_get_data(self, url):
        from urllib.parse import urlparse
        path = urlparse(url).path.lower().lstrip("/")   # e.g. "@watchdust/videos"
        key = path if path.startswith("@") else f"/{path}"
        slug = _SLUG_MAP.get(key)
        if slug is None:
            raise KeyError(
                f"No _SLUG_MAP entry for {key!r} (from URL {url!r}).\n"
                f"Add an entry to _SLUG_MAP in conftest.py, then record the fixture."
            )
        fixture = FIXTURES_DIR / f"channel_{slug}.json"
        if not fixture.exists():
            raise FileNotFoundError(
                f"No channel fixture for {url!r}\n"
                f"Expected: {fixture}\n"
                "Run test/record_fixtures.py to capture it."
            )
        return json.loads(fixture.read_text())

    class _FakePostResp:
        text = _EMPTY_CONT

        def raise_for_status(self):
            pass

    class _FakeSession:
        def get(self, *a, **kw):
            return _FakePostResp()

        def post(self, *a, **kw):
            return _FakePostResp()

    monkeypatch.setattr(_ch.Channel, "_get_data", _fake_get_data)
    monkeypatch.setattr(_ch, "default_session", lambda: _FakeSession())
    # ``yt_api_key`` would otherwise trigger a real HTTP fetch via ``_get_html``
    # to scrape ytcfg; short-circuit it for offline fixture-driven tests.
    monkeypatch.setattr(
        _ch.Channel, "yt_api_key",
        property(lambda self: "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"),
    )


@pytest.fixture
def patch_channel_requests(monkeypatch):
    """Patch requests.get in tutubo.channel to serve HTML fixture files.

    Fixture files are stored as ``test/fixtures/channel_<slug>.html``.
    """
    import tutubo.channel as _ch

    class _FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            pass

    def _fake_get(url, **kwargs):
        # derive a slug from the URL path
        from urllib.parse import urlparse
        path = urlparse(url).path.strip("/").replace("/", "_")
        safe = path[:60]
        html_path = FIXTURES_DIR / f"channel_{safe}.html"
        if not html_path.exists():
            raise FileNotFoundError(
                f"No channel fixture for {url!r}.\n"
                f"Expected: {html_path}\n"
                "Run test/record_fixtures.py to capture it."
            )
        return _FakeResponse(html_path.read_text())

    class _FakeSession:
        def get(self, url, **kwargs):
            return _fake_get(url, **kwargs)

        def post(self, *a, **kw):
            return _FakeResponse("")

    monkeypatch.setattr(_ch, "default_session", lambda: _FakeSession())


@pytest.fixture
def patch_ytmusic(monkeypatch):
    """Patch tutubo.ytmus._get_ytmus to return a fake YTMusic that serves fixture files.

    Fixture files are stored as ``test/fixtures/ytmusic_raw_{slug}.json`` and contain
    the raw list returned by ``ytmusicapi.YTMusic.search()``.

    Slug mapping:  query → re.sub(r'[^\\w]', '_', query.lower())[:40]
    e.g.  "Pink Floyd" → "pink_floyd"

    The fake supports:
      - ``search(query, filter=None)`` → loads the matching fixture
      - ``get_album(browseId)``        → returns an empty dict (fixture tests don't need enrichment)
      - ``get_artist(browseId)``       → returns an empty dict
      - ``get_playlist(browseId)``     → returns an empty dict
    """
    import tutubo.ytmus as _ym

    _SLUG_MAP = {
        "pink floyd":        "pink_floyd",
        "black sabbath":     "black_sabbath",
        "beethoven symphony":"beethoven",
    }

    class _FakeYTMusic:
        def search(self, query, filter=None):
            key = query.lower().strip()
            slug = _SLUG_MAP.get(key) or re.sub(r"[^\w]", "_", key)[:40]
            path = FIXTURES_DIR / f"ytmusic_raw_{slug}.json"
            if not path.exists():
                raise FileNotFoundError(
                    f"No YTMusic fixture for query {query!r}.\n"
                    f"Expected: {path}\n"
                    "Record with: ym.search(query) → json.dump to that path."
                )
            return json.loads(path.read_text())

        def get_album(self, browse_id):
            return {}

        def get_artist(self, browse_id):
            return {}

        def get_playlist(self, browse_id):
            return {}

    _fake = _FakeYTMusic()
    monkeypatch.setattr(_ym, "_YTMUS", _fake)
    monkeypatch.setattr(_ym, "_get_ytmus", lambda *a, **kw: _fake)
