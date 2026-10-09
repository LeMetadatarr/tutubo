# Content classification

Classification runs on multiple axes. `mediavocab.text.classify_video` returns a
`ClassificationResult` with orthogonal fields: `media_type`,
`content_form`, `programme_format`, `content_genres`. It uses only
information already available in search results or channel-page data, with no
extra per-video network fetches.

tutubo's search API is organized around single, human-facing **facets**
("documentaries", "live news", "music videos"), so
`tutubo.classification.Category` collapses a `ClassificationResult` (plus
the live and upcoming flags) to one facet through `classify_category`. Every
video exposes both:

- `Video.classification`: the full `ClassificationResult` (rich, multi-axis)
- `Video.content_type`: a single `Category` facet (for filtering or display)

```python
from tutubo import Category, classify_category, classify_video
result = classify_video(title="Dune: Part Two - Official Trailer")
result.media_type        # MediaType.MOVIE
result.content_form      # ContentForm.TRAILER
classify_category(result)  # Category.TRAILER
```

`Category` is tutubo-owned. mediavocab is the source of truth for the
underlying classification logic: priority order, keyword vocabularies,
duration thresholds. `ContentType` remains as a back-compat alias of
`Category`.

---

## Category facets

`Category` is both a `str` and an `enum.Enum`, so values compare equal to their string representations:

```python
from tutubo import Category
Category.MOVIE == "movie"   # True
Category.MOVIE.value        # "movie"
```

| Value | String | Description | Example title |
|---|---|---|---|
| `VIDEO` | `"video"` | Generic YouTube video, the default when no other type matches | "Random vlog #42" |
| `SOCIAL_CLIP` | `"social_clip"` | Under 62 seconds (YouTube Shorts / social clip format) | Any reel at most 61 s |
| `SHORT_FILM` | `"short_film"` | Narrative short film, distinct from YouTube Shorts | "Dust - Short Film: Parallel" |
| `LIVE` | `"live"` | Currently broadcasting, no sub-classification matched | "Playing chess with viewers" |
| `UPCOMING` | `"upcoming"` | Scheduled premiere or waiting room | "Album Release Party - Premiering Soon" |
| `LIVE_RADIO` | `"live_radio"` | Live radio station or 24/7 music stream | "24/7 Jazz Radio - Smooth Jazz" |
| `LIVE_NEWS` | `"live_news"` | Live news broadcast stream | "BBC News Live" |
| `IPTV` | `"iptv"` | Live TV channel that is not a news channel | "Sky Sports Live TV" |
| `MOVIE` | `"movie"` | Full feature-length film (at least 60 min if duration is known) | "Nosferatu 1922 Full Movie" |
| `TRAILER` | `"trailer"` | Movie or show trailer or teaser (at most 10 min if duration is known) | "Dune Part Two - Official Trailer" |
| `BEHIND_THE_SCENES` | `"behind_the_scenes"` | Making-of, bloopers, deleted scenes, on-set footage | "Making of Oppenheimer - Featurette" |
| `DOCUMENTARY` | `"documentary"` | Documentary, docu-series, docufilm, or docudrama | "Planet Earth III - Full Documentary" |
| `ANIME` | `"anime"` | Anime episode or series | "One Piece Episode 1 - Full English Sub" |
| `TV_EPISODE` | `"tv_episode"` | Scripted TV series episode | "Breaking Bad S01E01 Full Episode" |
| `AUDIOBOOK` | `"audiobook"` | Audiobook, audio drama, or radio play: spoken audio without video (single-narrator readings and full-cast productions) | "1984 George Orwell Full Audiobook Narrated by" |
| `PODCAST` | `"podcast"` | Podcast episode, publisher-defined only, never inferred from title | (see PODCAST note below) |
| `STAND_UP` | `"stand_up"` | Stand-up comedy special or comedy show | "Dave Chappelle - The Closer Comedy Special" |
| `INTERVIEW` | `"interview"` | Dedicated one-on-one or panel interview | "Elon Musk in conversation with Lex Fridman" |
| `LECTURE` | `"lecture"` | Academic lecture, TED Talk, Masterclass, or open course | "Richard Feynman - Lecture on Quantum Mechanics" |
| `CONCERT` | `"concert"` | Live concert recording or full performance | "Metallica Live at Wembley - Full Concert" |
| `NEWS` | `"news"` | Recorded news segment, report, briefing, or recap | "Breaking News: Today's Market Roundup" |
| `SPORT` | `"sport"` | Sports match, highlights reel, or game recap | "Full Match: Arsenal vs Chelsea - Game Highlights" |
| `GAMING` | `"gaming"` | Gameplay footage, let's play, or playthrough | "Minecraft Survival - Let's Play Episode 1" |
| `TUTORIAL` | `"tutorial"` | Instructional how-to, DIY, or step-by-step guide | "How to Build a REST API in Python - Tutorial" |
| `REACTION` | `"reaction"` | Reaction or first-watch video | "First Time Watching 'The Godfather' - Reaction" |
| `COMPILATION` | `"compilation"` | Clip compilation, best-of, or top-N list | "Best of Gordon Ramsay - Top 10 Moments" |
| `KIDS` | `"kids"` | Children's content, cartoons, nursery rhymes | "Baby Shark - Kids Song for Toddlers" |
| `MUSIC_VIDEO` | `"music_video"` | Official music video | "Rob Zombie - Dragula Official Music Video" |
| `MUSIC_AUDIO` | `"music_audio"` | Audio-only: lyric video, visualizer, or official audio track | "Billie Eilish - bad guy (Official Audio)" |

---

## `classify_video()` signature

`mediavocab.text.classify_video`

```python
classify_video(
    title: str,
    description: str = "",
    length: int = 0,
    is_live: bool = False,
    is_upcoming: bool = False,
    is_official_artist: bool = False,
    is_podcast: bool = False,
    channel_tags: list = None,
    lang: str = None,
) -> ClassificationResult
```

| Parameter | Type | Description |
|---|---|---|
| `title` | `str` | Video title. Required. |
| `description` | `str` | Description text or snippet, combined with `title` for keyword matching. |
| `length` | `int` | Duration in seconds. `0` means unknown; duration thresholds are skipped when unknown. |
| `is_live` | `bool` | When `True`, classification runs the live-stream branch (news, radio, sport, generic TV) and returns immediately. |
| `is_upcoming` | `bool` | Read by `classify_category()`, not by `classify_video()` itself; a scheduled premiere maps to `Category.UPCOMING`. |
| `is_official_artist` | `bool` | Raises confidence for `MediaType.MUSIC_VIDEO` when set. |
| `is_podcast` | `bool` | When `True` (or a `"podcast"` channel tag is present), returns `MediaType.PODCAST`. This should come from publisher-defined data such as `Channel.podcasts`, not inferred from title keywords. |
| `channel_tags` | `list` | Channel keyword tags. Checked as a lowercased set against several branches (news, sport, music, documentary, gaming, comedy, audiobooks). |
| `lang` | `str` | BCP 47 language tag for keyword matching. Defaults to `en-us`. See [docs/locale.md](locale.md). |

`VideoPreview.content_type` calls `classify_video()` with `title`, `description_snippet`, `length`, `is_live`, `is_upcoming`, and `is_official_artist` from the search result; it passes no `channel_tags`, because search results carry no channel keyword data. `Video.content_type` (from channel tabs) passes `channel_tags=self.channel_tags`, populated from `Channel.keywords`.

`classify_video()` returns as soon as a branch matches; later branches never run. Roughly, in order: live stream, podcast, anime, news, sport, TV episode (`S01E01`-style patterns), behind-the-scenes, reaction, trailer, music video, concert, stand-up, documentary, gaming, audiobook, short film (keyword or duration under 60 minutes), full movie (keyword or duration at least 60 minutes), falling back to a generic episodic/video result when nothing else matches.

---

## `classify_category()` collapse

`tutubo.classification.classify_category`

```python
classify_category(
    result: ClassificationResult, *,
    is_live: bool = False, is_upcoming: bool = False,
    title: str = "", tags: Optional[Iterable[str]] = None,
) -> Category
```

`title` and `tags` (channel keywords) are optional and used only to detect
`Category.KIDS` — mediavocab's `ClassificationResult` carries no
children's-content signal of its own (no genre, `media_type`, or
`programme_format` maps to it), so tutubo detects it directly from
free text, the same way `extract_tags` already does for the rest of
tutubo's facets.

Collapse order:

1. `is_live=True`: `Category.LIVE_NEWS` if `result.programme_format == ProgrammeFormat.NEWS` or `"news"` is in `content_genres`; `Category.LIVE_RADIO` if `result.media_type == MediaType.RADIO`; otherwise `Category.LIVE`.
2. `is_upcoming=True`: `Category.UPCOMING`.
3. `result.content_form`: `TRAILER`/`TEASER` to `Category.TRAILER`, `BEHIND_SCENES` to `Category.BEHIND_THE_SCENES`, `REACTION` to `Category.REACTION`, `SOCIAL_CLIP`/`EXCERPT` to `Category.SOCIAL_CLIP`.
4. `content_genres`: `"anime"` to `Category.ANIME`, `"gaming"` to `Category.GAMING`.
5. `title`/`tags` keyword match (`kids`, `children`, `toddler`, `preschool`, `nursery rhymes`) to `Category.KIDS`.
6. `result.programme_format`: `DOCUMENTARY`, `NEWS` to `Category.NEWS`, `SPORTS` to `Category.SPORT`, `STAND_UP`, `CONCERT`, `TALK_SHOW` to `Category.INTERVIEW`.
7. `result.media_type` fallback: `MOVIE`, `SHORT_FILM`, `EPISODIC_SERIES` to `Category.TV_EPISODE`, `TV` to `Category.IPTV`, `MUSIC_VIDEO`, `MUSIC` to `Category.MUSIC_AUDIO`, `PODCAST`, `AUDIOBOOK`, `AUDIO_DRAMA` to `Category.AUDIOBOOK`, `RADIO` to `Category.LIVE_RADIO`, `GAME` to `Category.GAMING`.
8. Anything unmatched: `Category.VIDEO`.

`Category.SOCIAL_CLIP` is a `content_form`, not a duration check in tutubo's own code — mediavocab decides `ContentForm.SOCIAL_CLIP` from its own title/duration signals before `classify_category()` ever runs.

---

## PODCAST classification

`Category.PODCAST` should come from publisher-defined data, not title keywords: passing `is_podcast=True` to `classify_video()` (or a `"podcast"` channel tag) is the reliable path. The correct source for `is_podcast=True` is `Channel.podcasts`, which reads from the YouTube Podcasts tab — a tab that appears only when the channel owner has explicitly created podcast shows.

```python
from mediavocab.text import classify_video
from tutubo import classify_category, ContentType

result = classify_video(title=ep_title, is_podcast=True)
assert classify_category(result) == ContentType.PODCAST
```

---

## Auto-tagging

`extract_tags` - `mediavocab.text.extract_tags`

```python
extract_tags(title: str, description: str = "", channel_tags: list = None) -> list[str]
```

Returns a sorted list of freeform string labels derived from the title, description, and channel tags. Tags are orthogonal to `Category` — they answer "what genre, era, or format subtype?" rather than "what facet is this?".

```python
from mediavocab.text import extract_tags
extract_tags("Lovecraft narrated by Wayne June")
extract_tags("The War of the Worlds - Full Cast Audio Drama", channel_tags=["sci-fi"])
```

`VideoPreview.tags` and `Video.tags` both expose this as a computed property. Both `as_dict` outputs include a `"tags"` key.

---

## Locale-driven keyword matching

Keyword patterns in `classify_video()` come from `.voc` files under `mediavocab/locale/<lang>/` (in the mediavocab package). This makes classification work across multiple languages without changing Python code. Numeric duration thresholds and structural patterns (like `S01E01` episode codes) are not translatable and stay in Python.

```python
from tutubo import classify_video
# Per-call (recommended for concurrent / multi-tenant use):
classify_video("Film complet en français", length=7200, lang="fr-fr")
# Or set the process-wide default at startup:
# MEDIAVOCAB_LANG=fr-fr python my_script.py
```

See [docs/locale.md](locale.md) for the full locale reference.

---

## Extending: adding a new facet

`ClassificationResult`'s axes (`media_type`, `content_form`, `programme_format`, `content_genres`) and the keyword matching that produces them live in the mediavocab package. `Category` — the single-facet collapse tutubo's search API is built on — lives in `tutubo/classification.py`. To add a new facet:

1. Confirm mediavocab already exposes (or can be extended to expose) a `media_type` / `content_form` / `programme_format` / genre combination that identifies the new facet.
2. Add a value to the `Category` enum in `tutubo/classification.py`.
3. Add a mapping entry in `classify_category()` (or one of its `_FORM_TO_CATEGORY` / `_FORMAT_TO_CATEGORY` / `_MEDIA_TO_CATEGORY` lookup tables) at the right point in the collapse order.
4. Add a paired `for_*` factory and `iterate_*` method in `tutubo/search.py` if the facet should be searchable, following the existing factories.
5. Add test cases covering the new facet and any priority conflicts with neighboring facets.

---
[← Models](models.md) · [Home](index.md) · [mediavocab →](mediavocab.md)
