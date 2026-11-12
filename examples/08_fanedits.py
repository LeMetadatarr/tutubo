"""
Fan-edit discovery: search YouTube for fan edits of specific films and emit
mediavocab Work + Release objects for each result.

Example videos used as seeds:
  https://www.youtube.com/watch?v=wFZ9mv_ke88  — Lord of the Rings fan edit
  https://www.youtube.com/watch?v=S3VMfzoBO7Y  — Star Wars fan edit

Fan edits are unofficial re-cuts of existing films.  tutubo's title parser
detects fan-edit vocabulary (fan edit, fanedit, despecialized, purist edition,
etc.) and emits VariantKind.FANEDIT which the mediavocab bridge maps to
VariantKind.FANEDIT automatically.
"""
from tutubo.search import YoutubeSearch
from mediavocab import VariantKind
from mediavocab.text import parse_title

SEED_QUERIES = [
    "Lord of the Rings fan edit",
    "Star Wars fan edit",
]

SEED_IDS = [
    "wFZ9mv_ke88",   # Lord of the Rings — Purist Edition fan edit
    "S3VMfzoBO7Y",   # Star Wars fan edit
]


def _describe_work(work, release) -> None:
    vk = work.variant_kind.value if work.variant_kind else "canonical"
    genres = ", ".join(work.content_genres) if work.content_genres else "—"
    year_str = str(work.year) if work.year else "?"
    runtime_str = (
        f"{int(work.runtime // 3600)}h{int((work.runtime % 3600) // 60)}m"
        if work.runtime else "?"
    )
    print(f"  title:       {work.title}")
    print(f"  year:        {year_str}")
    print(f"  runtime:     {runtime_str}")
    print(f"  media_type:  {work.media_type.value}")
    print(f"  variant:     {vk}")
    print(f"  edition:     {work.edition or '—'}")
    print(f"  genres:      {genres}")
    print(f"  uri:         {release.uri}")
    print(f"  thumbnail:   {release.image}")


print("=" * 60)
print("Fan-edit search results → mediavocab Work + Release")
print("=" * 60)

for query in SEED_QUERIES:
    print(f"\n── Query: {query!r} ──────────────────────────")
    search = YoutubeSearch(query)
    shown = 0
    for preview in search.iterate_videos():
        work = preview.to_work()
        release = preview.to_release()

        # The title parser now detects FANEDIT directly; filter on it
        if work.variant_kind != VariantKind.FANEDIT:
            continue

        print(f"\n  [{shown + 1}]")
        _describe_work(work, release)
        shown += 1
        if shown >= 5:
            break
    if shown == 0:
        print("  (no fan-edit results detected in this query)")


print("\n" + "=" * 60)
print("Seed videos — parse known fan-edit titles")
print("=" * 60)

# Demonstrate title parser on known-good fanedit titles without network calls
KNOWN_TITLES = [
    ("wFZ9mv_ke88", "The Fellowship of the Ring - Purist Edition [Fan Edit] (2001) [Extended]"),
    ("S3VMfzoBO7Y", "Star Wars: The Phantom Menace [Fan Edit] (1999)"),
]

for vid_id, raw_title in KNOWN_TITLES:
    parsed = parse_title(raw_title)
    print(f"\n  video_id:  {vid_id}")
    print(f"  raw:       {raw_title}")
    print(f"  title:     {parsed.title}")
    print(f"  year:      {parsed.year}")
    print(f"  variant:   {parsed.variant_kind}")
    print(f"  edition:   {parsed.edition}")
    assert parsed.variant_kind == VariantKind.FANEDIT, f"expected FANEDIT for {raw_title!r}"

print("\nSeed title assertions passed.")
