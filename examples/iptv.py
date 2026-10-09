from tutubo.channel import Channel

kids = [
    "https://www.youtube.com/@hasbroOfficial",
    "https://www.youtube.com/@BoomerangUK",
    "https://www.youtube.com/@MarvelHQ",
    "https://www.youtube.com/@DinoKids",
    "https://www.youtube.com/@TheSmurfsEnglish",
    "https://www.youtube.com/@ZipZipOfficial",
    "https://www.youtube.com/@cartoonito",
    "https://www.youtube.com/@HorridHenry",
    "https://www.youtube.com/@teletubbies",
    "https://www.youtube.com/@PowerRangersOfficial",
]

movies = [
    "https://www.youtube.com/@ClassicMrBean",
    "https://www.youtube.com/@ShoutStudios",
    "https://www.youtube.com/@MST3K",
    "https://www.youtube.com/@adultswim",
]
news = [
    "https://www.youtube.com/@tpaonline3152",  # Angola
    "https://www.youtube.com/@euronewspt",
    "https://www.youtube.com/@airevolutionx"
]
misc = [
    "https://www.youtube.com/@SpacedustDOC",
    "https://www.youtube.com/@DryBarComedy",
    "https://www.youtube.com/@EnglishClass101",
    # "https://www.youtube.com/@pixeldry",
    "https://www.youtube.com/@BitcoinLIVEyt"
]
space = [
    "https://www.youtube.com/@Whataboutit",
    "https://www.youtube.com/@WorldCamLIVE",
    "https://www.youtube.com/@WNSPACELIVE",
]

reading = [
    "https://www.youtube.com/@AgroSquerril",
    "https://www.youtube.com/@Frequency2156",
    "https://www.youtube.com/@CreepsMcPasta"
]

music = [
    "https://www.youtube.com/@NuclearBlastRecords",
    "https://www.youtube.com/@centurymedia",
    "https://www.youtube.com/@Herknungr",
    "https://www.youtube.com/@solitudeprod",
    "https://www.youtube.com/@dadabots_",
    "https://www.youtube.com/@LofiGirl",
]
pets = [
    "https://www.youtube.com/@TVfordogs-2106",
    "https://www.youtube.com/@sweetpetmusic",
    "https://www.youtube.com/@BirderKing"
]
wildlife_cams = [
    "https://www.youtube.com/@nature-live",
    "https://www.youtube.com/@NamibiaCam",
    "https://www.youtube.com/c/Africamvideos",
    "https://www.youtube.com/c/ExploreAfrica"
    # @ExploreAfrica ??  goes to wrong channel, https://www.youtube.com/@exploreafrica6302
]
beach_cams = [
    "https://www.youtube.com/@PlayoceanLive",
    "https://www.youtube.com/@MadeiraWebLive"
]

def get_readings():
    m3u_content = '#EXTM3U\n'

    for url in reading:
        print(666, url)
        try:
            c = Channel(url)
            for v in c.live:
                if not v.is_live:
                    break  # always come after current lives
                print(v.title, v.keywords)
                m3u_content += f'\n#EXTINF:-1 group-title="TV" tvg-logo="{v.thumbnail_url}",{v.title}\n{v.watch_url}\n'
        except Exception as e:
            print("error - rate limited?", e)

    with open("youtubeTV_Readings.m3u8", "w") as f:
        f.write(m3u_content)


def get_channels():
    m3u_content = '#EXTM3U\n'

    for url in news + movies + misc + space:
        print(666, url)
        try:
            c = Channel(url)
            for v in c.live:
                if not v.is_live:
                    break  # always come after current lives
                print(v.title, v.keywords)
                m3u_content += f'\n#EXTINF:-1 group-title="TV" tvg-logo="{v.thumbnail_url}",{v.title}\n{v.watch_url}\n'
        except Exception as e:
            print("error - rate limited?", e)

    with open("youtubeTV.m3u8", "w") as f:
        f.write(m3u_content)


def get_kids():
    m3u_content = '#EXTM3U\n'

    for url in kids:
        print(666, url)
        try:
            c = Channel(url)
            for v in c.live:
                if not v.is_live:
                    break  # always come after current lives
                print(v.title, v.keywords)
                m3u_content += f'\n#EXTINF:-1 group-title="TV" tvg-logo="{v.thumbnail_url}",{v.title}\n{v.watch_url}\n'
        except Exception as e:
            print("error - rate limited?", e)

    with open("youtubeTV_Kids.m3u8", "w") as f:
        f.write(m3u_content)


def get_music():
    m3u_content = '#EXTM3U\n'

    for url in music:
        print(666, url)
        try:
            c = Channel(url)
            for v in c.live:
                if not v.is_live:
                    break  # always come after current lives
                print(v.title, v.keywords)
                m3u_content += f'\n#EXTINF:-1 group-title="TV" tvg-logo="{v.thumbnail_url}",{v.title}\n{v.watch_url}\n'
        except Exception as e:
            print("error - rate limited?", e)

    with open("youtubeTV_Music.m3u8", "w") as f:
        f.write(m3u_content)


def get_pets():
    m3u_content = '#EXTM3U\n'

    for url in pets:
        print(666, url)
        try:
            c = Channel(url)
            for v in c.live:
                if not v.is_live:
                    break  # always come after current lives
                print(v.title, v.keywords)
                m3u_content += f'\n#EXTINF:-1 group-title="TV" tvg-logo="{v.thumbnail_url}",{v.title}\n{v.watch_url}\n'
        except Exception as e:
            print("error - rate limited?", e)

    with open("youtubeTV_Pets.m3u8", "w") as f:
        f.write(m3u_content)


def get_wildlife_cams():
    m3u_content = '#EXTM3U\n'

    for url in wildlife_cams:
        print(666, url)
        try:
            c = Channel(url)
            for v in c.live:
                if not v.is_live:
                    break  # always come after current lives
                print(v.title, v.keywords)
                m3u_content += f'\n#EXTINF:-1 group-title="TV" tvg-logo="{v.thumbnail_url}",{v.title}\n{v.watch_url}\n'
        except Exception as e:
            print("error - rate limited?", e)

    with open("youtubeTV_wildLife.m3u8", "w") as f:
        f.write(m3u_content)


def get_beachcams():
    m3u_content = '#EXTM3U\n'

    for url in beach_cams:
        print(666, url)
        try:
            c = Channel(url)
            for v in c.live:
                if not v.is_live:
                    break  # always come after current lives
                print(v.title, v.keywords)
                m3u_content += f'\n#EXTINF:-1 group-title="TV" tvg-logo="{v.thumbnail_url}",{v.title}\n{v.watch_url}\n'
        except Exception as e:
            print("error - rate limited?", e)

    with open("youtubeTV_beachCams.m3u8", "w") as f:
        f.write(m3u_content)


get_readings()
get_channels()
get_kids()
get_music()
get_wildlife_cams()
get_pets()
get_beachcams()
