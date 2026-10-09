"""Rich Release output — show every typed field tutubo populates from a YouTube
video search renderer, without any network calls.

Demonstrates that ``VideoPreview.to_release()`` lifts the badge/caption signals
YouTube exposes in the search-result renderer into typed mediavocab fields:

  * ``Release.resolution``      — from ``4K`` / ``8K`` / ``HD`` quality badge
  * ``Release.accessibility``   — ``AccessibilityTrack(kind="captions")`` from CC badge
  * ``Release.container``       — from title parser (``WEBRip``, ``BluRay``, …)
  * ``Release.stream_mode``     — ``LIVE`` / ``CONTINUOUS`` / ``ON_DEMAND`` from ContentType
  * ``Release.external_ids``    — ``{"youtube": <video_id>}``

What is NOT populated, and why: YouTube's search-result renderer does not
include codec, bitrate, audio_channels, defaultAudioLanguage, caption
language list, chapters, or localizations.  Those fields require an extra
``/youtubei/v1/player`` request per video — out of scope for the search
wrapper.  tutubo does not invent values for fields YouTube does not return.
"""
from tutubo.models import VideoPreview


# A synthetic videoRenderer mirroring the shape YouTube actually returns
# for a 4K HDR-tagged "Best Movie [BluRay] (2010)" search hit with captions.
RAW = {
    "videoId": "rich01",
    "title": {"runs": [{"text": "Best Movie [BluRay] (2010)"}]},
    "ownerText": {"runs": [{
        "text": "Cult Cinema Classics",
        "navigationEndpoint": {
            "browseEndpoint": {"browseId": "UC_cult_classics"},
            "commandMetadata": {"webCommandMetadata": {"url": "/@CultCinemaClassics"}},
        },
    }]},
    "publishedTimeText": {"simpleText": "1 year ago"},
    "viewCountText": {"simpleText": "12,345,678 views"},
    "shortViewCountText": {"simpleText": "12M views"},
    "lengthText": {"simpleText": "1:42:00"},
    "badges": [
        {"metadataBadgeRenderer": {"label": "4K"}},
        {"metadataBadgeRenderer": {"label": "CC"}},
    ],
    "ownerBadges": [
        {"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_VERIFIED"}},
    ],
    "thumbnailOverlays": [],
    "detailedMetadataSnippets": [{"snippetText": {"runs": [
        {"text": "Restored full feature film, 4K UHD remaster."},
    ]}}],
}


def _print(label, value):
    print(f"  {label:<22} {value!r}")


preview = VideoPreview(RAW)
work = preview.to_work()
release = preview.to_release()

print("=" * 60)
print("VideoPreview → mediavocab.Work")
print("=" * 60)
_print("title", work.title)
_print("year", work.year)
_print("media_type", work.media_type.value)
_print("runtime (s)", work.runtime)
_print("variant_kind", work.variant_kind.value if work.variant_kind else None)
_print("edition", work.edition)
_print("source_format", work.source_format)
_print("content_genres", work.content_genres)
_print("release_status", work.release_status.value)
_print("external_ids", work.external_ids)
_print("credits", [(c.entity.name, c.role) for c in work.credits])

print()
print("=" * 60)
print("VideoPreview → mediavocab.Release")
print("=" * 60)
_print("uri", release.uri)
_print("platform", release.platform)
_print("stream_mode", release.stream_mode.value)
_print("container", release.container)
_print("resolution", release.resolution)
_print("accessibility", [(t.kind, t.language) for t in release.accessibility])
_print("release_status", release.release_status.value)
_print("external_ids", release.external_ids)

# Sanity assertions so the example doubles as a smoke test
assert release.resolution == "2160p", "4K badge must lift to 2160p"
assert any(t.kind == "captions" for t in release.accessibility), "CC badge must lift"
assert release.external_ids.get("youtube") == "rich01"
assert work.media_type.value == "movie", "Title parser detected (2010) → MOVIE"
print("\nAll rich-output assertions passed.")
