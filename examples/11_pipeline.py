"""Title -> classify -> route -> Signals (resolver-ready).

Shows the canonical tutubo -> mediavocab pipeline: take a raw YouTube
title, parse it with ``parse_title``, classify it with ``classify_video``
(which returns a multi-axis ``ClassificationResult``), and pack its
``media_type`` / ``content_genres`` into a ``Signals`` object that any
mediavocab-aware resolver can route on.
"""
from mediavocab import Signals
from mediavocab.text import parse_title, classify_video


def signals_from_youtube(title: str, length: int) -> Signals:
    parsed = parse_title(title)
    result = classify_video(title, length=length)

    return Signals(
        title=parsed.title or title,
        year=parsed.year,
        season=parsed.season,
        episode=parsed.episode,
        runtime=float(length) if length else None,
        medium=result.media_type,
        content_genres=result.content_genres,
        variant_kind=parsed.variant_kind,
        edition=parsed.edition or None,
        language=parsed.language_hint,
    )


if __name__ == "__main__":
    examples = [
        ("Blade Runner (1982) [Director's Cut] 1080p", 7000),
        ("Dune Part Two — Official Trailer", 150),
        ("Metallica — Live in Berlin — Full Concert", 9000),
        ("Stranger Things S04E07 [HDR]", 4500),
    ]
    for title, length in examples:
        s = signals_from_youtube(title, length)
        print(f"{title!r}")
        print(f"  medium={s.medium} "
              f"genres={s.content_genres} variant={s.variant_kind}")
