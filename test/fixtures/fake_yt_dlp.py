#!/usr/bin/env python3
"""A stand-in for yt-dlp: no network. FAKE_YTDLP_CONTROL names a JSON file {"mode": ...}; every call is appended to FAKE_YTDLP_LOG."""
import json
import os
import sys
import time

argv = sys.argv[1:]
control = json.loads(open(os.environ["FAKE_YTDLP_CONTROL"]).read())
with open(os.environ["FAKE_YTDLP_LOG"], "a") as log:
    log.write(json.dumps(argv) + "\n")
mode = control.get("mode", "ok")
template = argv[argv.index("-o") + 1]
url = argv[-1]
if mode == "botcheck":
    sys.stderr.write("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser\n")
    sys.exit(1)
if mode == "leak":
    sys.stderr.write("ERROR: unable to download: HTTP Error 403: Forbidden https://rr1.googlevideo.com/videoplayback?sig=SIGVALUE&ip=203.0.113.9 Cookie: SID=COOKIEVALUE Bearer TOKENVALUE\n")
    sys.exit(1)
if mode == "orphan":
    import subprocess
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(6)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    sys.stderr.write("ERROR: [youtube] abc: Video unavailable\n")
    sys.exit(3)
if mode == "fail":
    sys.stderr.write("ERROR: [youtube] abc: Video unavailable\n")
    sys.exit(1)
ext = control.get("ext", "m4a")
path = template.replace("%(ext)s", ext).replace("%%", "%")
with open(path + ".part", "wb") as f:
    f.write(b"x" * 100)
print("TUTUBO-PROGRESS 50 100 NA", flush=True)
if mode == "slow":
    open(os.environ["FAKE_YTDLP_LOG"] + ".started", "w").close()
    for _ in range(300):
        time.sleep(0.1)
os.replace(path + ".part", path)
print("TUTUBO-PROGRESS 100 100 NA", flush=True)
print("TUTUBO-FILE " + path, flush=True)
