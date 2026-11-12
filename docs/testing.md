# Testing

tutubo uses a **fixture-based** test strategy. The test suite never touches the network. Raw YouTube API responses are stored as JSON files in `test/fixtures/` and replayed by pytest through `monkeypatch`.

---

## Running the full suite

```bash
pip install -e ".[test]"
pytest
```

`test/test_content_type.py` and `test/test_models.py` are fully offline and always runnable. `test/test_search.py` and `test/test_channel_classification.py` require recorded fixture files and skip automatically if any fixture is missing.

---

## Fixture-based testing philosophy

Recording a real API response once and replaying it in all future test runs gives you:

- Deterministic tests: the same JSON is parsed every time.
- Fast tests: no DNS, TLS, or network latency.
- Documentation of expected API response shapes: a fixture file also serves as a reference for what a real YouTube API response looks like.
- Reproducible regressions: when someone reports a bug, attach the fixture and reproduce the failure offline, without replicating the reporter's network conditions.

The trade-off is that fixtures go stale when YouTube changes its response schema. When that happens, record fresh fixtures and commit them.

---

## `patch_innertube` fixture

`test/conftest.py:52`

Patches `tutubo._innertube._post` to serve responses from JSON files instead of hitting the YouTube innertube API.

**Fixture file naming**: tutubo derives the fixture name from the search query.

1. Take the `query` key from the request body (or `params`).
2. Lowercase it and replace all non-word characters with `_`.
3. Truncate to 60 characters.
4. Prepend `search_` (the endpoint name).

Example: query `"rob zombie"` becomes `search_rob_zombie.json`.

Continuation requests (requests containing a `continuation` token instead of a `query`) return an empty terminator that stops pagination cleanly:

```json
{"onResponseReceivedCommands": [{"appendContinuationItemsAction": {"continuationItems": []}}]}
```

This means fixture tests cover only the first page of results. If a test needs multi-page behavior, you must provide the continuation fixture manually.

If the expected fixture file does not exist, the monkeypatched function raises `FileNotFoundError` with a message that points to the expected path and gives instructions for recording it.

**Usage in tests:**

```python
def test_video_results(patch_innertube):
    from tutubo import YoutubeSearch
    results = list(YoutubeSearch("rob zombie").iterate_videos(max_res=5))
    assert len(results) > 0
    assert results[0].title
```

---

## `patch_channel_data` fixture

`test/conftest.py:84`

Patches `Channel._get_data` to serve `ytInitialData` dicts from JSON fixture files instead of fetching live channel pages.

Also patches `requests.post` (for continuation requests) to return an empty action list, stopping pagination after the first page.

**Fixture file naming** is controlled by the `_SLUG_MAP` dictionary and a fallback:

1. The URL path is lowercased and the leading `@` is preserved, e.g. `@watchdust/videos`.
2. tutubo looks up the path in `_SLUG_MAP`.
3. If found, tutubo uses the mapped slug directly.
4. If not found, tutubo sanitizes the path (replaces non-word characters with `_`, strips a leading `@`) and truncates it to 60 characters.
5. The fixture file is `test/fixtures/channel_{slug}.json`.

**`_SLUG_MAP`, full listing** (`test/conftest.py:95`)

| URL path | Fixture slug | Content |
|---|---|---|
| `@watchdust/videos` | `watchdust_videos` | Short film channel: videos tab |
| `@watchalter/videos` | `watchalter_videos` | Short film channel: videos tab |
| `@omeleto/videos` | `omeleto_videos` | Short film channel: videos tab |
| `@mosfilm_eng/videos` | `mosfilm_eng_videos` | Full movie channel: videos tab |
| `@cultcinemaclassics/videos` | `cultcinemaclassics_videos` | Full movie channel: videos tab |
| `@moonflix_official/videos` | `moonflix_official_videos` | Full movie channel: videos tab |
| `@thedissenterrl/videos` | `thedissenterrl_videos` | Podcast/interview channel: videos tab |
| `@overlysarcasticproductions/videos` | `overlysarcasticproductions_videos` | Educational channel |
| `@pbsspacetime/videos` | `pbsspacetime_videos` | Physics/science channel |
| `@eons/videos` | `eons_videos` | Science channel |
| `@pbsinfiniteseries/videos` | `pbsinfiniteseries_videos` | Math channel |
| `@pbsdocumentaries/videos` | `pbsdocumentaries_videos` | Documentary channel |
| `@kurzgesagt/videos` | `kurzgesagt_videos` | Animated science channel |
| `@knowledgia/videos` | `knowledgia_videos` | History channel |
| `@markiplier/videos` | `markiplier_videos` | Gaming channel |
| `@bbcnews/videos` | `bbcnews_videos` | News channel |
| `@pinkfongbabyshark/videos` | `pinkfongbabyshark_videos` | Kids channel |
| `@3blue1brown/videos` | `3blue1brown_videos` | Math tutorial channel |
| `@comedycentral/videos` | `comedycentral_videos` | Stand-up comedy channel |
| `@livenation/videos` | `livenation_videos` | Concert channel |
| `@thedissenterrl/podcasts` | `thedissenterrl_podcasts` | Podcasts tab |
| `@euronews/streams` | `euronews_live` | Live news streams tab |
| `@france24_en/streams` | `france24_live` | Live news streams tab |
| `@aljazeeraenglish/streams` | `aljazeera_live` | Live news streams tab |
| `@euronewses/streams` | `euronewses_live` | Live news streams tab |
| `@euronews/live` | `euronews_current_live` | Live redirect page |
| `@france24_en/live` | `france24_current_live` | Live redirect page |
| `@aljazeeraenglish/live` | `aljazeera_current_live` | Live redirect page |
| `@euronewses/live` | `euronewses_current_live` | Live redirect page |
| `@watchdust` (home) | `watchdust_home` | Channel home: keywords/tags |
| `@bbcnews` (home) | `bbcnews_home` | Channel home: keywords/tags |
| `@markiplier` (home) | `markiplier_home` | Channel home: keywords/tags |
| *(and all other channel handles listed in the map)* | | Channel home: keywords/tags |

Home page fixtures (`*_home`) load when tutubo calls `Channel._get_data` for the bare channel URL (e.g. `https://www.youtube.com/@watchdust`). They are needed for `Channel.keywords`, which populates `Video.channel_tags`, and therefore for channel-context-boosted classification tests.

**Usage in tests:**

```python
def test_short_film_channel(patch_channel_data):
    from tutubo import Channel
    from tutubo import ContentType
    c = Channel("https://www.youtube.com/@watchdust")
    for v in c.videos:
        assert v.content_type in (ContentType.SHORT_FILM, ContentType.VIDEO)
        break
```

---

## `patch_channel_requests` fixture

`test/conftest.py:178`

An alternative fixture that patches `requests.get` in `tutubo.channel` to serve raw HTML from `.html` files. Use it when you need to test the full `initial_data()` parsing path rather than injecting already-parsed dicts.

Fixture files are stored as `test/fixtures/channel_<path_slug>.html`, where the slug comes from the URL path with slashes replaced by `_`.

---

## Recording fixtures

### Automated recording

```bash
TUTUBO_RECORD_DIR=test/fixtures python test/record_fixtures.py
```

`test/record_fixtures.py` records:

1. **Search fixtures**: calls `YoutubeSearch(query).iterate_videos()` for a large set of predefined queries covering every `ContentType`. It saves each innertube response as `search_{query_slug}.json`.
2. **YouTube Music fixtures**: calls `search_yt_music(query)` for two queries and saves results as `ytmusic_{query_slug}.json`.
3. **Channel JSON fixtures**: fetches `ytInitialData` for a predefined list of channel handles (both `/videos` tabs and home pages) and saves them as `channel_{slug}.json`.
4. **Channel HTML fixtures**: also patches `requests.get` during the run to save raw HTML responses as `channel_{path_slug}.html`.

Commit all resulting files to enable offline CI runs.

### Ad-hoc recording

Set `TUTUBO_RECORD_DIR` before you run any script that uses tutubo. The innertube client checks `os.environ.get("TUTUBO_RECORD_DIR")` on module import (`tutubo/_innertube.py:18`) and automatically writes every API response to that directory:

```bash
TUTUBO_RECORD_DIR=test/fixtures python examples/search.py
TUTUBO_RECORD_DIR=test/fixtures python examples/livestreams.py
```

### Recording for bug reports

Capture the exact API response you received and attach it to a GitHub issue:

```bash
TUTUBO_RECORD_DIR=/tmp/my_fixtures python -c "
from tutubo import YoutubeSearch
list(YoutubeSearch('your failing query').iterate_videos(max_res=5))
"
```

Then attach the files from `/tmp/my_fixtures/`. The maintainer can replay them offline without replicating your region, ISP, or account state.

---

## Test files

| File | Coverage |
|---|---|
| `test/test_content_type.py` | All 30 `ContentType` values, every regex, priority conflicts, duration gates, channel-tag boosting. Fully offline |
| `test/test_models.py` | `VideoPreview`, `ChannelPreview`, `PlaylistPreview`, `RelatedSearch`, `YoutubeMixPreview` field access. Fully offline |
| `test/test_search.py` | `YoutubeSearch` iteration, factories, typed iterators. Requires search fixtures |
| `test/test_channel_classification.py` | `Channel.videos` content-type distribution by channel. Requires channel fixtures |
| `test/test_live_news_classification.py` | Live stream sub-classification (LIVE_RADIO, LIVE_NEWS, IPTV). Requires live-stream channel fixtures |
| `test/test_import.py` | Smoke test that verifies top-level imports work |

---
[← Downloading](downloading.md) · [Home](index.md)
