from tutubo.channel import Channel

url = "https://www.youtube.com/channel/UC4BSeEq7XNtihGqI309vhYg"
c = Channel(url)
print(c.videos_url)
print(c.vanity_url)
print(c.playlist_urls)
for v in c.videos:
    print(v)
for pl in c.playlists:
    print(pl.title)
    for video in pl.videos:
        print("     ", video.title)

