"""A stand-in for yt-dlp as tutubo.fetch runs it: no network.

FAKE_YTDLP_CONTROL names a JSON file: {"mode": "ok" | "botcheck" | "warn_botcheck" | "fail" | "interrupt" | "hang" | "stubborn" (ignores SIGTERM; "grandchild": true starts a process of its own), "info": {...}, "audio": {...},
"size": bytes}. Every call is appended to FAKE_YTDLP_LOG as {"argv": [...], ...}. A download resumes from the ``.part``
file it finds, as yt-dlp's --continue does, and reports where it resumed from in the log.
"""
import json
import os
import signal
import subprocess
import sys
import time

argv = sys.argv[1:]
control = json.loads(open(os.environ["FAKE_YTDLP_CONTROL"]).read())
entry = {"argv": argv}


def log(**extra):
    entry.update(extra)
    with open(os.environ["FAKE_YTDLP_LOG"], "a") as f:
        f.write(json.dumps(entry) + "\n")


mode = control.get("mode", "ok")
if argv == ["--version"]:
    log()
    print("2026.10.21")
    sys.exit(0)
if mode == "botcheck":
    log()
    sys.stderr.write("ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. Use --cookies-from-browser\n")
    sys.exit(1)
if mode == "fail_url":
    log()
    sys.stderr.write("ERROR: unable to download video data: HTTP Error 403: Forbidden "
                     "(https://rr1---sn-x.googlevideo.com/videoplayback?expire=1&ip=203.0.113.9&signature=AB12CD)\n")
    sys.exit(1)
if mode == "fail":
    log()
    sys.stderr.write("ERROR: [youtube] abcdefghijk: Video unavailable\n")
    sys.exit(1)
if "--dump-single-json" in argv:
    log()
    print(json.dumps(control.get("info", {})))
    if mode == "warn_botcheck":  # --ignore-no-formats-error turns the refusal into a warning and the exit status stays 0
        sys.stderr.write("WARNING: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. Use --cookies-from-browser\n")
    sys.exit(0)

loaded = None
if "--load-info-json" in argv:
    with open(argv[argv.index("--load-info-json") + 1]) as f:
        loaded = json.load(f).get("id")
audio = control.get("audio", {})
template = argv[argv.index("-o") + 1]
path = template.replace("%(ext)s", audio.get("ext", "m4a"))
size = control.get("size", 1000)
report = "TUTUBO-AUDIO " + json.dumps({**audio, "filepath": path})
if os.path.exists(path):
    log(loaded=loaded, already=True)
    print(report, flush=True)
    sys.exit(0)
if mode == "stubborn":  # prints a line, then ignores SIGTERM
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen(["sleep", "20"]) if control.get("grandchild") else None  # an ffmpeg of its own
    log(loaded=loaded, pid=os.getpid(), grandchild=child.pid if child else None)
    print("TUTUBO-PROGRESS 1 2 NA", flush=True)
    time.sleep(20)
if mode == "hang":
    log(loaded=loaded, pid=os.getpid(), info_path=argv[argv.index("--load-info-json") + 1] if loaded else None)
    if control.get("line"):
        print("TUTUBO-PROGRESS 1 2 NA", flush=True)
    time.sleep(20)
part = path + ".part"
start = os.path.getsize(part) if os.path.exists(part) else 0
stop = size // 2 if mode == "interrupt" else size
with open(part, "ab") as f:
    f.write(b"a" * max(0, stop - start))
print(f"TUTUBO-PROGRESS {stop} {size} NA", flush=True)
log(loaded=loaded, resumed_from=start)
if mode == "interrupt":
    sys.stderr.write("ERROR: unable to download: connection reset\n")
    sys.exit(1)
os.replace(part, path)
print(report, flush=True)
