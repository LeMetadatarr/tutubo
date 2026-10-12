"""
Channel content report — breakdown of ContentType distribution for any channel.

Usage:
    python channel_report.py https://www.youtube.com/@bbcnews/videos
    python channel_report.py  (uses BBC News as default)
"""
import sys
from collections import Counter
from tutubo.channel import Channel
from tutubo import ContentType
from mediavocab.text import extract_tags

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/@bbcnews/videos"

c = Channel(url)
print(f"Channel report: {url}\n" + "─" * 60)

counts: Counter = Counter()
tag_counts: Counter = Counter()
sample: dict = {}

for v in c.videos:
    ct = v.content_type
    counts[ct] += 1
    tags = extract_tags(v.title or "", channel_tags=v.channel_tags)
    tag_counts.update(tags)
    sample.setdefault(ct, v)
    if sum(counts.values()) >= 60:
        break

print(f"Scanned {sum(counts.values())} videos\n")
print(f"{'Content type':<22}  {'count':>5}  {'%':>5}  Sample title")
print("─" * 80)
total = sum(counts.values())
for ct, n in counts.most_common():
    pct = 100 * n / total
    title = (sample[ct].title or "")[:45]
    print(f"  {ct.value:<20}  {n:5d}  {pct:4.0f}%  {title}")

if tag_counts:
    print(f"\nTop tags: {', '.join(t for t, _ in tag_counts.most_common(8))}")
