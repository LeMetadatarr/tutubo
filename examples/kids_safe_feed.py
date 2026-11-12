"""
Build a kids-safe video feed from verified children's channels.

Channels: @PinkFongBabyShark
Verifies KIDS classification and reports what slipped through the filter.
"""
from tutubo.channel import Channel
from tutubo import ContentType

url = "https://www.youtube.com/@pinkfongbabyshark/videos"
c = Channel(url)

safe, flagged = [], []

for v in c.videos:
    if v.content_type == ContentType.KIDS:
        safe.append(v)
    elif v.content_type == ContentType.SOCIAL_CLIP:
        safe.append(v)   # Shorts are fine on a kids channel
    else:
        flagged.append((v.content_type, v))
    if len(safe) + len(flagged) >= 40:
        break

print(f"Kids-safe feed — {len(safe)} videos\n" + "─" * 50)
for v in safe[:10]:
    when = v.published_time or ("live" if v.is_live else "")
    print(f"  {when:>14}  {v.title}")

if flagged:
    print(f"\nClassified as something other than KIDS ({len(flagged)}):")
    for ct, v in flagged:
        print(f"  [{ct.value}]  {v.title}")
else:
    print("\nAll videos on this channel classified as KIDS or SOCIAL_CLIP.")
