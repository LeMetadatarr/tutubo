from tutubo.ytmus import (
    MusicAlbum,
    MusicArtist,
    MusicPlaylist,
    search_yt_music,
)


def test_search(phrase):
    for v in search_yt_music(phrase, as_dict=False):
        if isinstance(v, (MusicPlaylist, MusicArtist)):
            # albums / artists / playlists
            pl = [
                {
                    "length": entry.length * 1000 if entry.length else 0,
                    "uri": entry.watch_url,
                    "image": v.thumbnail_url,
                    "bg_image": v.thumbnail_url,
                    "title": entry.title,
                    "album": v.title,
                    "artist": entry.artist,
                } for entry in v.tracks
            ]
            if pl:
                if isinstance(v, MusicArtist):
                    title = v.name + " (Featured Tracks)"
                elif isinstance(v, MusicAlbum):
                    title = v.title + " (Full Album)"
                elif isinstance(v, MusicPlaylist):
                    title = v.title + " (Playlist)"
                else:
                    title = v.title

                yield {
                    "playlist": pl,
                    "image": v.thumbnail_url,
                    "bg_image": v.thumbnail_url,
                    "title": title
                }

        else:
            # return as a video result (single track dict)
            yield {
                "length": v.length * 1000 if v.length else 0,
                "uri": v.watch_url,
                "image": v.thumbnail_url,
                "bg_image": v.thumbnail_url,
                "title": v.title,
                "artist": v.artist,
            }


for res in test_search("ozzy osbourne"):
    print(res)
