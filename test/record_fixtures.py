"""Record live YouTube API responses as test fixtures.

Usage:
    TUTUBO_RECORD_DIR=test/fixtures python test/record_fixtures.py

Each query/channel below will hit the live YouTube API and save the raw
response JSON to TUTUBO_RECORD_DIR.  Commit the resulting files to enable
offline test runs.

Channel HTML fixtures are saved alongside JSON fixtures with a .html extension.
"""
import os
import pathlib
import sys

# Allow running from repo root or test/
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

record_dir = os.environ.get("TUTUBO_RECORD_DIR", "test/fixtures")
os.environ["TUTUBO_RECORD_DIR"] = record_dir

# ---------------------------------------------------------------------------
# Patch channel.py requests.get to also record HTML responses
# ---------------------------------------------------------------------------

import json  # noqa: E402
import pathlib as _pl  # noqa: E402
import re  # noqa: E402

import requests as _requests  # noqa: E402

_out = _pl.Path(record_dir)
_out.mkdir(parents=True, exist_ok=True)

_real_get = _requests.get


def _recording_get(url, **kwargs):
    resp = _real_get(url, **kwargs)
    from urllib.parse import urlparse
    path = urlparse(url).path.strip("/").replace("/", "_")
    safe = re.sub(r"[^\w\-]", "_", path)[:60]
    fixture_path = _out / f"channel_{safe}.html"
    fixture_path.write_text(resp.text, encoding="utf-8")
    print(f"  [html fixture] {fixture_path.name}")
    return resp


_requests.get = _recording_get

# ---------------------------------------------------------------------------
# Search queries to record
# ---------------------------------------------------------------------------

from tutubo import YoutubeSearch  # noqa: E402 (after env var set)

SEARCH_QUERIES = [
    # general / channels / playlists
    "rob zombie",
    "metallica",
    "lofi hip hop",
    # content type: full movies
    "full movie free 2023",
    "full movie action free",
    # content type: trailers
    "official trailer 2024",
    "movie teaser 2024",
    # content type: documentary
    "nature documentary full",
    # content type: podcast
    "tech talk podcast interview",
    "lex fridman podcast",
    # content type: music
    "black sabbath paranoid",
    "rob zombie dragula official music video",
    "billie eilish official audio",
    # live / upcoming
    "live stream concert",
    # content type: behind the scenes
    "behind the scenes making of film",
    "bloopers gag reel 2023",
    # content type: anime
    "anime full episode english sub",
    "one piece anime episode",
    # content type: tv episode
    "breaking bad full episode",
    "game of thrones S01E01 full episode",
    # content type: short film
    "award winning short film",
    "dust sci-fi short film",
    # content type: audiobook
    "full audiobook free fiction",
    "narrated by audiobook classic",
    # content type: stand-up comedy
    "stand up comedy special full show",
    "comedy special netflix",
    # content type: interview
    "interview with celebrity",
    "in conversation with author",
    # content type: lecture
    "TED talk best lectures",
    "university lecture physics",
    # content type: concert
    "full concert live performance",
    "live at wembley full show",
    # content type: news
    "breaking news report today",
    "news briefing analysis",
    # content type: sport
    "full match football highlights",
    "NBA game highlights recap",
    # content type: gaming
    "gameplay walkthrough 2024",
    "lets play minecraft episode",
    # content type: tutorial
    "tutorial beginners python",
    "DIY woodworking how to",
    # content type: reaction
    "reaction video first time watching",
    "reacting to viral videos",
    # content type: compilation
    "best of compilation funny moments",
    "top 10 moments",
    # content type: kids
    "nursery rhymes for kids",
    "kids cartoon full episode",
    # content type: silent film
    "silent film chaplin classic",
    "nosferatu 1922 silent movie",
    # content type: black and white
    "classic black and white movie full",
    "casablanca full film black white",
    # content type: educational
    "educational science explained",
    "crash course history",
    # specific movie titles
    "Inception 2010 full movie",
    "The Dark Knight full movie",
    "Pulp Fiction 1994 full film",
    "Casablanca 1942 full movie",
    "2001 A Space Odyssey full film",
    "Metropolis 1927 silent film",
    "Nosferatu 1922 restored",
    "The Godfather full movie",
    "Schindler's List full movie",
    "Parasite 2019 full movie",
    # specific TV shows
    "Breaking Bad S01E01",
    "Game of Thrones Season 1 Episode 1 full",
    "The Wire full episode HBO",
    # specific concerts
    "Metallica live Wembley full concert",
    "Pink Floyd live Pompeii full show",
    "Queen Live Aid 1985 full performance",
    # specific interviews
    "Interview with Barack Obama",
    "Elon Musk talks with Joe Rogan",
    "Oprah sits down with Prince Harry",
    # specific stand-up
    "Dave Chappelle comedy special Netflix",
    "John Mulaney Baby J comedy special",
    # specific lectures / TED talks
    "TED Talk Simon Sinek",
    "Richard Feynman lecture physics",
    # specific audiobooks
    "1984 George Orwell audiobook narrated by",
    "Harry Potter audiobook full",
]

print(f"Recording fixtures to: {record_dir}")
print()

for query in SEARCH_QUERIES:
    print(f"Search: {query!r}")
    try:
        s = YoutubeSearch(query)
        # Force iteration to trigger API calls and fixture recording
        videos = list(s.iterate_videos(max_res=3))
        channels = list(s.iterate_channels(max_res=2))
        queries = list(s.iterate_queries(max_res=3))
        print(f"  videos={len(videos)} channels={len(channels)} queries={len(queries)}")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

# ---------------------------------------------------------------------------
# YouTube Music queries
# ---------------------------------------------------------------------------

from tutubo.ytmus import search_yt_music  # noqa: E402

MUSIC_QUERIES = [
    "black sabbath paranoid",
    "rob zombie dragula",
]

print("YouTube Music:")
for query in MUSIC_QUERIES:
    print(f"  Music: {query!r}")
    try:
        results = list(search_yt_music(query, as_dict=True))
        print(f"  results={len(results)}")
        # Save ytmusic results as fixture (ytmusicapi doesn't go through _innertube)
        safe = re.sub(r"[^\w]", "_", query.lower())[:50]
        fixture_path = _out / f"ytmusic_{safe}.json"
        fixture_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"  [ytmusic fixture] {fixture_path.name}")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

# ---------------------------------------------------------------------------
# Channel ytInitialData fixtures
# ---------------------------------------------------------------------------

from tutubo._utils import initial_data as _initial_data  # noqa: E402
from tutubo.channel import _YT_HEADERS, _YT_COOKIES      # noqa: E402
import requests as _req  # noqa: E402

CHANNEL_FIXTURES = [
    # (handle, videos_url, fixture_slug)
    # short film
    ("@watchdust",          "https://www.youtube.com/@watchdust/videos",          "watchdust_videos"),
    ("@WatchALTER",         "https://www.youtube.com/@WatchALTER/videos",         "watchalter_videos"),
    ("@Omeleto",            "https://www.youtube.com/@Omeleto/videos",            "omeleto_videos"),
    # full movie
    ("@Mosfilm_eng",        "https://www.youtube.com/@Mosfilm_eng/videos",        "mosfilm_eng_videos"),
    ("@CultCinemaClassics", "https://www.youtube.com/@CultCinemaClassics/videos", "cultcinemaclassics_videos"),
    ("@moonflix_official",  "https://www.youtube.com/@moonflix_official/videos",  "moonflix_official_videos"),
    # anime
    ("@CrunchyrollCollection", "https://www.youtube.com/@CrunchyrollCollection/videos", "crunchyrollcollection_videos"),
    # kids
    ("@CocomelanNurseryRhymes", "https://www.youtube.com/@CocomelanNurseryRhymes/videos", "cocomelannurseryrhymes_videos"),
    ("@PinkfongBabyShark", "https://www.youtube.com/@PinkfongBabyShark/videos", "pinkfongbabyshark_videos"),
    # gaming
    ("@Markiplier",         "https://www.youtube.com/@Markiplier/videos",         "markiplier_videos"),
    # news
    ("@BBCNews",            "https://www.youtube.com/@BBCNews/videos",            "bbcnews_videos"),
    # sport
    ("@NBASports",          "https://www.youtube.com/@NBASports/videos",          "nbasports_videos"),
    # tutorial / educational
    ("@3Blue1Brown",        "https://www.youtube.com/@3Blue1Brown/videos",        "3blue1brown_videos"),
    # stand-up comedy
    ("@ComedyCentral",      "https://www.youtube.com/@ComedyCentral/videos",      "comedycentral_videos"),
    # concert
    ("@LiveNation",         "https://www.youtube.com/@LiveNation/videos",         "livenation_videos"),
    # silent / b&w
    ("@SilentHallofFame",   "https://www.youtube.com/@SilentHallofFame/videos",   "silenthalloffame_videos"),
]

# Home pages for channel keyword/tag extraction
CHANNEL_HOME_FIXTURES = [
    # (handle, home_url, fixture_slug)
    ("@watchdust",             "https://www.youtube.com/@watchdust",             "watchdust_home"),
    ("@WatchALTER",            "https://www.youtube.com/@WatchALTER",            "watchalter_home"),
    ("@Omeleto",               "https://www.youtube.com/@Omeleto",               "omeleto_home"),
    ("@Mosfilm_eng",           "https://www.youtube.com/@Mosfilm_eng",           "mosfilm_eng_home"),
    ("@CultCinemaClassics",    "https://www.youtube.com/@CultCinemaClassics",    "cultcinemaclassics_home"),
    ("@moonflix_official",     "https://www.youtube.com/@moonflix_official",     "moonflix_official_home"),
    ("@CrunchyrollCollection", "https://www.youtube.com/@CrunchyrollCollection", "crunchyrollcollection_home"),
    ("@CocomelanNurseryRhymes","https://www.youtube.com/@CocomelanNurseryRhymes","cocomelannurseryrhymes_home"),
    ("@PinkfongBabyShark",     "https://www.youtube.com/@PinkfongBabyShark",     "pinkfongbabyshark_home"),
    ("@Markiplier",            "https://www.youtube.com/@Markiplier",            "markiplier_home"),
    ("@BBCNews",               "https://www.youtube.com/@BBCNews",               "bbcnews_home"),
    ("@NBASports",             "https://www.youtube.com/@NBASports",             "nbasports_home"),
    ("@3Blue1Brown",           "https://www.youtube.com/@3Blue1Brown",           "3blue1brown_home"),
    ("@ComedyCentral",         "https://www.youtube.com/@ComedyCentral",         "comedycentral_home"),
    ("@LiveNation",            "https://www.youtube.com/@LiveNation",            "livenation_home"),
    ("@SilentHallofFame",      "https://www.youtube.com/@SilentHallofFame",      "silenthalloffame_home"),
    ("@PBSDocumentaries",      "https://www.youtube.com/@PBSDocumentaries",      "pbsdocumentaries_home"),
    ("@kurzgesagt",            "https://www.youtube.com/@kurzgesagt",            "kurzgesagt_home"),
    ("@Knowledgia",            "https://www.youtube.com/@Knowledgia",            "knowledgia_home"),
    ("@TheDissenterRL",        "https://www.youtube.com/@TheDissenterRL",        "thedissenterrl_home"),
]

def _fetch_and_save(url, slug):
    resp = _req.get(
        url,
        headers={**_YT_HEADERS, "Accept-Language": "en-US,en;q=0.9"},
        cookies=_YT_COOKIES,
        timeout=30,
    )
    resp.raise_for_status()
    data = _initial_data(resp.text)
    fixture_path = _out / f"channel_{slug}.json"
    fixture_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  [channel fixture] {fixture_path.name}")


print("Channel video fixtures:")
for handle, url, slug in CHANNEL_FIXTURES:
    print(f"  Channel: {handle}")
    try:
        _fetch_and_save(url, slug)
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

print("Channel home fixtures (for keyword/tag extraction):")
for handle, url, slug in CHANNEL_HOME_FIXTURES:
    print(f"  Home: {handle}")
    try:
        _fetch_and_save(url, slug)
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

print("Done.")
