# Locale system

`mediavocab.locale` is the canonical home for the keyword vocab and the
loader API. tutubo just consumes it. Nothing locale-related ships in
tutubo any more.

Classification keywords live in plain `.voc` files, one phrase per
line, organized by language. This lets tutubo classify content in
languages other than English without changing Python code.

The locale loader is **stateless**. There is no `set_lang()`,
`get_lang()`, or `TUTUBO_LANG` any more. Pass `lang="xx-yy"` per call.
The default is read once from `MEDIAVOCAB_LANG` at import.

`en-us` is the only locale mediavocab currently ships `.voc` files for.
Any other `lang` code falls back to it through the chain below, so the
`.voc` files and example directories referenced further down (`es/`,
`pt-pt/`, and similar) describe the fallback mechanism, not locales
that exist yet.

---

## Directory layout

```
mediavocab/locale/
    en-us/
        movie_keywords.voc
        documentary_keywords.voc
        music_video_keywords.voc
        short_film_keywords.voc
        trailer_keywords.voc
        tv_episode_keywords.voc
        ... (one .voc file per keyword category)
```

Currently `en-us` is the only shipped locale. A regional variant directory
(e.g. a future `es-es`) would only need the files that differ from a shared
base language directory (e.g. `es`); everything else falls back through the
chain below.

---

## .voc file format

A `.voc` file contains one phrase per line.

- Blank lines are ignored.
- Lines starting with `#` are comments and are ignored.
- Leading and trailing whitespace is stripped.
- Phrases are matched case-insensitively.
- Multi-word phrases are supported: `full movie` is a single entry.

Example: `en-us/movie_keywords.voc`

```
# full-length feature film indicators
full movie
full film
full length
complete film
```

Example: `es/movie_keywords.voc`

```
película completa
pelicula completa
largometraje
```

---

## Fallback chain

When you request a `.voc` file for a given language, the loader walks
this chain and returns the first file it finds:

1. Exact locale match, e.g. `es-es`
2. Language-only code, e.g. `es`
3. `en-us`

So `es-es` and `es-mx` automatically inherit all `es/` files they do
not override. Any unsupported locale falls back to English.

Example: requesting `movie_keywords` with lang `de-de` (not supported)

```
de-de/movie_keywords.voc   -> not found
de/movie_keywords.voc      -> not found
en-us/movie_keywords.voc   -> found, use this
```

---

## Public API

The locale system is **stateless** and thread-safe. There is no global
mutable language. Pass `lang=` to every call. The default comes from the
`MEDIAVOCAB_LANG` environment variable, read once at import (falling back
to `"en-us"`). This default is read-only at runtime.

### `voc_regex(name, lang=None) -> Optional[re.Pattern]`

A compiled word-boundary alternation regex from the named `.voc` file.
Returns `None` if the file is empty or missing in the fallback chain.

```python
from mediavocab.locale import voc_regex
rx_en = voc_regex("cut_directors", lang="en-us")
rx_pt = voc_regex("cut_directors", lang="pt-pt")
rx_default = voc_regex("cut_directors")  # uses MEDIAVOCAB_LANG / "en-us"
```

### `voc_set(name, lang=None) -> frozenset[str]`

A frozenset of lowercased phrases from the named `.voc` file. Used for
intersection checks against tag-like input (channel tags, hashtags).

```python
from mediavocab.locale import voc_set
movie_tags = voc_set("channel_movie_tags", lang="en-us")
channel_tags = {"full movie", "bollywood films", "comedy"}
if channel_tags & movie_tags:
    # channel is a movie channel
    ...
```

### `get_default_lang() -> str`

Returns the import-time default language (the value of `MEDIAVOCAB_LANG`
or `"en-us"` if unset). Read-only.

### `MEDIAVOCAB_LANG` environment variable

Set this before you start the Python process, to switch the default language:

```bash
MEDIAVOCAB_LANG=it-it python my_script.py
```

---

## Per-call language

Concurrent callers should always pass `lang=` explicitly, so different
tenants, requests, or threads do not interfere. The cache is keyed on
`(name, lang)`, so different languages cannot collide.

```python
from mediavocab.text import classify_video, parse_title
ct_pt  = classify_video("Filme Completo HD", length=7200, lang="pt-pt")
ct_es  = classify_video("Película completa HD", length=7200, lang="es")
parsed = parse_title("Star Wars [Edição do Director]", lang="pt-pt")
```

---

## Caching behavior

All `.voc` loads and compiled patterns are cached with
`functools.lru_cache(maxsize=512)`, keyed on `(name, lang)`. The cache
is shared across calls for the same `(name, lang)` pair within a
process. Different languages are cached independently and never evict
each other.

There is no public cache-clear API. The only way to invalidate the cache is to
restart the process.

---

## Structural patterns that stay in Python

Some patterns are not expressed in `.voc` files because they are
numeric, structural, or language-universal:

| Pattern | Reason |
|---|---|
| `S01E02`, `Season N Episode N` | Standardized production codes, identical across all languages |
| `Top \d+` | Numeric; the word "top" plus a number needs no translation |
| Duration gates (`length < 62`, `length >= 3600`, and similar) | Numeric thresholds, not linguistic |
| `is_live`, `is_upcoming`, `is_podcast` flag checks | Boolean signals from publisher data |

---

## Supported languages

| Code | Notes |
|---|---|
| `en-us` | Only locale currently shipped; full `.voc` coverage |

Any other `lang=` value falls back to `en-us` through the chain above.
Adding a new language means adding a new `mediavocab/locale/<lang>/`
directory of translated `.voc` files in the mediavocab package.

---

## Adding a new language

### Step 1: create the directory

```bash
mkdir mediavocab/locale/de-de
```

If the language has regional variants (e.g. `de-at`, `de-ch`), create
`de/` as the shared base and add the variant directories with only the
files that differ.

### Step 2: translate `.voc` files

Copy from `en-us/` and translate phrase by phrase. You only need to
provide files for patterns that have meaningful translations. Skip
files where the English phrases work (episode codes, brand names).

### Step 3: test your translation

```python
from mediavocab.text import classify_video
from tutubo import Category, classify_category

result = classify_video("Der Pate — Ganzer Film Deutsch", lang="de-de")
assert classify_category(result) == Category.MOVIE
```

No network access is needed. `classify_video()` works entirely offline.

---
[← Transport](transport.md) · [Home](index.md) · [Downloading →](downloading.md)
