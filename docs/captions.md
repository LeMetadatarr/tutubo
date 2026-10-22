# Caption tracks

`tutubo/captions.py`

`list_caption_tracks(video, session=None, family=None)` fetches a video's watch page (one request, through the same session and address-family options as `Channel`) and returns its caption tracks as `CaptionTrack` objects. `Video.caption_tracks()` does the same for a channel-tab `Video`. `parse_caption_tracks(player_response)` parses an already fetched player response without any request.

| Field | Meaning |
|---|---|
| `language` | Language code of the track |
| `name` | Track name as YouTube shows it |
| `kind` | `"manual"` (uploaded by a person), `"asr"` (YouTube's automatic recognition) or `"translation"` (machine translation of another track) |
| `is_translation` | True for a machine translation of another track |
| `source_language` | For a translation, the language of the track it comes from; otherwise `None` |
| `source_kind` | For a translation, the `kind` of the track it comes from; otherwise `None` |
| `url` | Timed-text URL of the track (a translation carries `tlang=<code>`) |

## Original tracks and translations

YouTube offers a translatable track in every language of `translationLanguages`. These are listed with `kind="translation"` and `is_translation=True`, so a filter on `kind` alone never returns one as `"manual"` or `"asr"`. A translation is not a transcript of what is said, so `original_tracks(tracks)` returns only the tracks that are not translations.

Only an `"asr"` track is guaranteed to be in the language spoken in the video. A `"manual"` track is whatever the uploader provided and may be a human translation or a subtitle in another language.

```python
originals = original_tracks(list_caption_tracks(video_id))
automatic = [t for t in originals if t.kind == "asr"]
```

## Errors

An empty list means the video is playable and has no captions, or the uploader disabled them. Every case where that cannot be told raises `CaptionError`, a subclass of `RuntimeError` exported from `tutubo`: a failed request or HTTP error status, a page without a readable player response, a response for a different video than the one requested, a response without a playability status, a video that is not playable (private, removed, age or login gated), and a malformed response (for example `"captions": null` or a track name that is not an object).
