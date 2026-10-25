"""A structural stand-in for the parts of arrkit that tutubo.arr builds on: the Indexer and DownloadClient bases, Direct, JobQueue and the
two error types, with the signatures and behaviour arrkit documents. It lets the suite run without arrkit installed."""
import os
import shutil
import threading
import time
import types
import uuid

ACTIVE_STATES = {"Queued": "queued", "Downloading": "downloading", "Completed": "completed", "Failed": "failed"}


def defaults(fields):
    return {f[0]: f[2] for f in fields}


class IndexerError(RuntimeError):
    pass


class ClientError(RuntimeError):
    pass


class Indexer:
    implementation = ""
    name = ""
    protocol = ""
    caps = {"search": True, "rss": False}
    fields = []

    def __init__(self, inst=None):
        self.inst = dict(inst or {})
        given = self.inst.get("settings") or {}
        self.settings = {k: str(given.get(k, d)).strip() for k, d in defaults(self.fields).items()}

    def num(self, key, default):
        try:
            return float(str(self.settings.get(key) or default).replace(",", "."))
        except ValueError:
            return float(default)

    def release(self, **kw):
        base = {"title": "", "guid": "", "indexer": self.inst.get("name") or self.name, "indexer_id": self.inst.get("id"), "size": 0, "published": "",
                "seeders": None, "leechers": None, "url": "", "protocol": self.protocol, "info_url": "", "kind": "download"}
        return base | kw


class Control:
    def __init__(self, queue, job_id):
        self.queue, self.job_id, self.cancelled, self._cancel = queue, job_id, False, []

    def progress(self, percent):
        self.queue.set(self.job_id, percent=max(0, min(int(percent), 99)))

    def set(self, **changes):
        self.queue.set(self.job_id, **changes)

    def on_cancel(self, fn):
        self._cancel.append(fn)

    def cancel(self):
        self.cancelled = True
        for fn in self._cancel:
            fn()


class Store:
    def __init__(self, folder):
        self.folder = folder

    def path(self, name):
        return os.path.join(self.folder, name)


class JobQueue:
    def __init__(self, folder, name="jobs.json", prefix="SABnzbd_nzo_", log=None):
        self.store, self.name, self.prefix = Store(folder), name, prefix
        self.jobs, self.lock, self.running = [], threading.RLock(), {}
        self.wake, self.halt, self.thread = threading.Event(), threading.Event(), None

    def load(self):
        return self.jobs

    def add(self, ref, title="", cat="*", size=0, own_folder=False, **extra):
        job = {"id": self.prefix + uuid.uuid4().hex[:16], "ref": ref, "title": title or "", "cat": cat or "*", "status": "Queued",
               "added": int(time.time()), "mb": round((size or 0) / 1048576, 2), "percent": 0, "bytes": 0, "error": "", "started": 0, "finished": 0} | extra
        if own_folder:
            job["folder"] = f"{job['title']}-{job['id'][-8:]}" if job["title"] else job["id"][-8:]
        with self.lock:
            self.jobs.append(job)
        self.wake.set()
        return job["id"]

    def get(self, job_id):
        return next((j for j in self.jobs if j["id"] == job_id), None)

    def set(self, job_id, **changes):
        with self.lock:
            job = self.get(job_id)
            if job:
                job.update({k: v for k, v in changes.items() if k != "id"})
            return job

    def remove(self, ids, history=None, before=None):
        out = []
        with self.lock:
            for j in list(self.jobs):
                if j["id"] in ids:
                    if j["id"] in self.running:
                        self.running[j["id"]].cancel()
                    if before:
                        before(j)
                    self.jobs.remove(j)
                    out.append(j)
        return out

    def run_one(self, runner, blocked=lambda: 0):
        if blocked():
            return None
        job = next((j for j in self.jobs if j["status"] == "Queued"), None)
        if not job:
            return None
        ctl = Control(self, job["id"])
        self.running[job["id"]] = ctl
        try:
            self.set(job["id"], status="Downloading", started=int(time.time()), error="")
            result = runner(self.get(job["id"]), ctl)
        except Exception as e:
            result = f"{type(e).__name__}: {e}"
        finally:
            self.running.pop(job["id"], None)
        if ctl.cancelled or not self.get(job["id"]):
            return job["id"]
        if result == "blocked":
            self.set(job["id"], status="Queued", percent=0)
        elif result == "done":
            self.set(job["id"], status="Completed", percent=100, error="", finished=int(time.time()))
        else:
            self.set(job["id"], status="Failed", percent=100, error=str(result)[:500], finished=int(time.time()))
        return job["id"]

    def start(self, runner, blocked=lambda: 0, idle=30):
        self.thread = threading.Thread(target=lambda: None)
        self.thread.start()
        return self.thread

    def stop(self, timeout=5):
        self.halt.set()


class DownloadClient:
    implementation = ""
    name = ""
    protocols = ()
    category = ""
    fields = []

    def __init__(self, inst=None, state_dir=None):
        self.inst = dict(inst or {})
        given = self.inst.get("settings") or {}
        self.settings = {k: str(given.get(k, d)).strip() for k, d in defaults(self.fields).items()}
        self.category = str(self.inst.get("category") or type(self).category)
        self.state_dir = state_dir

    def num(self, key, default):
        try:
            return float(str(self.settings.get(key) or default).replace(",", "."))
        except ValueError:
            return float(default)


class Direct(DownloadClient):
    def __init__(self, inst=None, state_dir=None):
        super().__init__(inst, state_dir)
        if not state_dir:
            raise ClientError("the direct client needs the app's state folder")
        self.queue = JobQueue(state_dir, f"direct-{self.inst.get('id') or 0}.json", prefix="direct_")

    def folder(self):
        d = self.settings["download_dir"]
        if not d:
            raise ClientError("no download folder set")
        return os.path.expanduser(d)

    def status(self):
        return [{"client_id": j["id"], "title": j["title"], "progress": j.get("percent", 0), "state": ACTIVE_STATES.get(j["status"], "queued"),
                 "path": j.get("path") or os.path.join(self.folder(), j.get("folder") or j["title"]),
                 "size": j.get("bytes") or int(j.get("mb", 0) * 1048576), "message": j.get("error") or "", "added": j.get("added")}
                for j in self.queue.load()]

    def remove(self, client_id, delete_files=False):
        root = os.path.realpath(self.folder())
        self.queue.remove([client_id], None, lambda j: delete_files and shutil.rmtree(
            os.path.join(root, j.get("folder") or j["title"]), ignore_errors=True))

    def test(self):
        d = self.folder()
        if not os.path.isdir(d):
            return False, f"download folder {d} does not exist"
        return True, f"downloads to {d}"


def install(modules):
    """Puts the stand-in under the module names arrkit has, in ``modules`` (sys.modules)."""
    def module(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        modules[name] = m
        return m
    arrkit = module("arrkit", __path__=[])
    clients = module("arrkit.clients", __path__=[], ClientError=ClientError, DownloadClient=DownloadClient)
    module("arrkit.clients.direct", Direct=Direct)
    module("arrkit.clients.jobs", JobQueue=JobQueue)
    indexers = module("arrkit.indexers", Indexer=Indexer, IndexerError=IndexerError)
    arrkit.clients, arrkit.indexers = clients, indexers
