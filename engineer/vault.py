"""The telemetry vault (2026-10-27, request: "make the telemetry save for all of our drives ... never lose telemetry;
store it on this PC and in a private folder on my Google Drive. A very robust system.").

Every recording - iRacing's own .ibt files and the engineer's own .renpz recordings - is kept twice:

  * on this PC, in the archive folder (E:\\RaceEngineer\\telemetry on the developer's PC), as an exact copy in <year>\\<month>\\
    folders, checked with SHA-256 after copying (a copy that doesn't match is thrown away and made again)
  * in Google Drive (G:\\My Drive\\Instability Control\\Telemetry - his personal account, never the business H: drive),
    packed about 6x smaller with vault_codec (lossless, checked after packing and again after copying), within a size
    cap (8 GB by default). When the cap is reached, the OLDEST packed copies in Drive make room - only ones whose copy on
    this PC still checks out. A small summary of every session (laps, best lap, incidents, per-corner times) is always
    kept in Drive, whatever the cap.

Rules it never breaks: iRacing's own files are only ever read. Nothing on the PC copy is ever deleted. A file iRacing
still has open is left alone until it's finished (checked with an exclusive open on Windows, plus "unchanged for 20 s").
0-byte stub files are noted and skipped. When G: isn't there (the Drive app not running) the Drive copies wait in a queue
and go up when it's back. While you drive, copying to the PC is slowed down and packing / Drive copies wait until you're
out of the car. The work runs in a low-priority (Windows background mode) thread; the engine never waits for it.

The index (vault_index.json, with a .bak of the one before) lives in the archive folder and a copy goes to Drive.
Command line (works with the app closed - the logon task in tools\\vault_logon_task.ps1 runs the first one):

    python -m engineer.vault --scan        copy / pack / upload anything not kept yet (catch-up)
    python -m engineer.vault --verify      re-check every copy against its checksum (--deep also unpacks Drive copies)
    python -m engineer.vault --status      what's kept where, what's waiting
    python -m engineer.vault --restore NAME [--out DIR]    unpack a Drive copy back to the original .ibt
"""
import hashlib, json, os, re, shutil, sys, threading, time

from . import vault_codec as C

DRIVE_DEFAULT = os.path.join("G:\\", "My Drive", "Instability Control", "Telemetry")
FORBIDDEN_DRIVES = ("H:",)          # the owner's BUSINESS Google Drive: never written to, whatever the settings say
INDEX = "vault_index.json"
LOCK = "vault.lock"
SETTLE_S = 20                       # an .ibt unchanged this long (and not open in iRacing) is finished
RENPZ_SETTLE_S = 600                # the engineer's own recording rewrites its file every 2 min while it records
STALE_LOCK_S = 900
FORCE_AFTER_S = 6 * 3600            # "in use" but unchanged for 6 h: iRacing hung or crashed - copy it anyway
E_MIN_FREE_GB = 15.0                # never fill the PC drive past this (C: on the developer's PC is nearly full)
DRIVE_MIN_FREE_GB = 0.5
SUMMARY_TRIES = 3
CHUNK = 8 << 20
_DATE = re.compile(r"(\d{4})-(\d\d)-(\d\d) (\d\d)-(\d\d)-(\d\d)")


# ---------------------------------------------------------------- small helpers
def _now():
    return time.time()


def _sha(path, pace=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
            pace and pace()
    return h.hexdigest()


def forbidden(path):
    """True for a path on the business Google Drive (H:)."""
    m = re.match(r"^\s*([A-Za-z]:)", str(path or ""))
    return bool(m) and m.group(1).upper() in FORBIDDEN_DRIVES


def _ym(name, mtime):
    m = _DATE.search(name)
    if m:
        return m.group(1), m.group(2)
    t = time.localtime(mtime or _now())
    return f"{t.tm_year:04d}", f"{t.tm_mon:02d}"


def _started(name, mtime):
    m = _DATE.search(name)
    if m:
        try:
            return time.mktime(time.strptime(m.group(0), "%Y-%m-%d %H-%M-%S"))
        except (ValueError, OverflowError):
            pass
    return mtime or 0.0


def _write_json(path, obj):
    """Atomic: temp file, flushed to disk, then renamed over."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def in_use_windows(path):
    """True while another program (iRacing) has the file open. Tries an exclusive read-only open (share mode 0), which
    fails while any other handle is open, and closes it straight away. Not Windows: False (size/time checks only)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.HANDLE]
        h = k.CreateFileW(path, 0x80000000, 0, None, 3, 0x80, None)      # GENERIC_READ, no sharing, OPEN_EXISTING
        if h in (None, 0) or h == ctypes.c_void_p(-1).value:
            return True
        k.CloseHandle(h)
        return False
    except Exception:
        return False


def background_thread():
    """This thread at Windows' background priority (CPU, disk and memory) - the sim and the engine always come first."""
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetThreadPriority(k.GetCurrentThread(), 0x00010000)         # THREAD_MODE_BACKGROUND_BEGIN
        except Exception:
            pass


# ---------------------------------------------------------------- session summary (the small dataset)
def summarise(se, ent):
    """telemetry.Session -> the small per-session record kept for every drive (and always uploaded to Drive)."""
    import numpy as np
    d = se.d
    info = se.info or {}
    wk = info.get("WeekendInfo", {}) or {}
    di = info.get("DriverInfo", {}) or {}
    sessions = {x.get("SessionNum"): x.get("SessionType") for x in (info.get("SessionInfo", {}) or {}).get("Sessions", []) or []}
    sn = d.get("SessionNum")
    fuel = d.get("FuelLevel")
    laps = []
    for L in se.laps:
        a, b = L["a"], L["b"]
        row = {"n": L["n"], "t": L["time"], "ok": L["complete"], "valid": L["valid"], "pit": L["pit"],
               "inc": L["incidents"], "off": L["off"]}
        if sn is not None:
            row["s"] = int(sn[a])
        if fuel is not None and L["complete"]:
            used = float(fuel[a] - fuel[b - 1])
            if 0.05 < used < 40:
                row["fuel"] = round(used, 3)
        laps.append(row)
    inc = d.get("PlayerCarMyIncidentCount")
    incidents = int(sum(max(0, L["incidents"]) for L in se.laps)) if inc is not None else None
    corners = None
    try:
        cs = se.find_corners() or []
        if cs and se.best:
            times, mins = {}, {}
            for L in [x for x in se.laps if x["valid"]][:150]:
                tr = se.trace(L["n"])
                row_t, row_v = [], []
                for c in cs:
                    m = C_metrics(tr, c)
                    row_t.append(round(m["time"], 3) if m else None)
                    row_v.append(round(m["min_kmh"], 1) if m else None)
                times[str(L["n"])], mins[str(L["n"])] = row_t, row_v
                se._traces.clear()
            cols = list(zip(*times.values())) if times else []
            corners = {"names": [c["name"] for c in cs], "lap_times": times, "lap_min_kmh": mins,
                       "best": [min([x for x in col if x is not None], default=None) for col in cols],
                       "median": [round(float(np.median([x for x in col if x is not None])), 3) if any(x is not None for x in col) else None
                                  for col in cols]}
    except Exception as e:
        corners = {"error": repr(e)[:200]}
    def mid(ch):
        a = d.get(ch)
        return round(float(np.median(a)), 1) if a is not None and len(a) else None
    wet = d.get("TrackWetness")
    t = d.get("SessionTime")
    return {
        "v": 1, "name": ent["name"], "kind": ent.get("kind"), "sha256": ent.get("sha256"), "size": ent.get("size"),
        "car": se.car_path, "car_name": se.car, "class": se.car_class, "track": se.track_name, "track_name": se.track_display,
        "subsession": wk.get("SubSessionID"), "session_id": wk.get("SessionID"), "event": wk.get("EventType"),
        "session_types": sorted({str(sessions.get(int(s), "")) for s in (set(np.unique(sn).tolist()) if sn is not None else set())} - {""}),
        "started": ent.get("started"), "duration_s": round(float(t[-1] - t[0]), 1) if t is not None and len(t) else None,
        "tick": se.tick, "setup": di.get("DriverSetupName"),
        "laps": laps, "laps_complete": sum(1 for L in se.laps if L["complete"]),
        "best": se.best["time"] if se.best else None, "best_lap": se.best["n"] if se.best else None,
        "incidents": incidents,
        "weather": {"track_temp": mid("TrackTempCrew"), "air": mid("AirTemp"),
                    "wet_max": int(np.max(wet)) if wet is not None and len(wet) else None},
        "corners": corners,
    }


def C_metrics(tr, c):
    from .telemetry import corner_metrics
    try:
        return corner_metrics(tr, c["start"], c["end"])
    except Exception:
        return None


# ---------------------------------------------------------------- the vault
class Vault:
    def __init__(self, root=None, sources=None, drive=DRIVE_DEFAULT, drive_on=True, quota_gb=8.0, log=print,
                 busy=None, in_use=None, on_new=None, drive_anchor=None, e_min_free_gb=None):
        from . import telemetry as T
        self.root = root or T.archive_dir()
        self.sources = list(sources) if sources is not None else [T.TELEMETRY_DIR]
        # 2026-10-27 (#359): recordings made while the archive drive was unplugged are picked up from the fallback folder
        if sources is None and self.root and os.path.normcase(os.path.abspath(T.fallback_dir())) != os.path.normcase(os.path.abspath(self.root)):
            self.sources.append(T.fallback_dir())
        self.drive = drive or ""
        self.drive_on = bool(drive_on and self.drive)
        self.quota = float(quota_gb or 0) * 1e9
        self.log = log
        self.busy = busy or (lambda: False)
        self.in_use = in_use or in_use_windows
        self.on_new = on_new
        self.anchor = drive_anchor
        self.e_min_free = (E_MIN_FREE_GB if e_min_free_gb is None else e_min_free_gb) * 1e9
        self.alive = True
        self.idx = {"v": 1, "files": {}}
        self._seen = {}                 # path -> ((size, mtime), first time seen like that)
        self.status = {"state": "starting"}
        self._dirty = False

    # ------------------------------------------------ index
    @property
    def ipath(self):
        return os.path.join(self.root, INDEX)

    def load(self):
        for p in (self.ipath, self.ipath + ".bak"):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict) and isinstance(d.get("files"), dict):
                    self.idx = d
                    if p.endswith(".bak"):
                        self.log("[vault] the index was damaged - using its backup (the files themselves are fine)")
                    return
            except (OSError, ValueError):
                continue
        self.idx = {"v": 1, "files": {}}

    def save(self):
        self.idx["updated"] = _now()
        try:
            if os.path.exists(self.ipath):
                shutil.copyfile(self.ipath, self.ipath + ".bak")
        except OSError:
            pass
        _write_json(self.ipath, self.idx)
        self._dirty = False

    @property
    def files(self):
        return self.idx["files"]

    # ------------------------------------------------ one worker at a time (the app and the logon task)
    def lock(self):
        p = os.path.join(self.root, LOCK)
        os.makedirs(self.root, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {_now():.0f}".encode())
                os.close(fd)
                return True
            except FileExistsError:
                try:
                    if _now() - os.path.getmtime(p) > STALE_LOCK_S:
                        os.remove(p)                       # left behind by a worker that died
                        continue
                except OSError:
                    continue
                return False
        return False

    def touch_lock(self):
        try:
            os.utime(os.path.join(self.root, LOCK))
        except OSError:
            pass

    def unlock(self):
        try:
            os.remove(os.path.join(self.root, LOCK))
        except OSError:
            pass

    # ------------------------------------------------ pacing: never in the driver's way
    def _pace_light(self):
        """Copy to the PC: allowed while driving, but slowed (about 80 MB/s at most)."""
        if self.busy():
            time.sleep(0.1)

    def _pace_heavy(self):
        """Packing / Drive: waits while you're in the car."""
        while self.alive and self.busy():
            self.touch_lock()
            time.sleep(2.0)
        if not self.alive:
            raise InterruptedError("vault stopped")

    # ------------------------------------------------ discovery
    def discover(self):
        """-> {name: {"src": iRacing path or None, "e": [copies found in the archive], "kind"}}"""
        from . import telemetry as T
        found = {}
        def add(name, key, path, kind):
            r = found.setdefault(name, {"src": None, "e": [], "kind": kind})
            if key == "src":
                r["src"] = path
            else:
                r["e"].append(path)
        for d in self.sources:
            try:
                for n in os.listdir(d):
                    if n.lower().endswith(".ibt"):
                        add(n, "src", os.path.join(d, n), "ibt")
                    elif n.lower().endswith(".renpz") and d != T.TELEMETRY_DIR:     # #359: the engineer's own, from the fallback
                        add(n, "src", os.path.join(d, n), "renpz")
            except OSError:
                pass
        dirs = [self.root]
        try:
            for y in os.listdir(self.root):
                py = os.path.join(self.root, y)
                if len(y) == 4 and y.isdigit() and os.path.isdir(py):
                    dirs += [os.path.join(py, m) for m in os.listdir(py) if os.path.isdir(os.path.join(py, m))]
        except OSError:
            pass
        for d in dirs:
            try:
                for n in os.listdir(d):
                    low = n.lower()
                    if low.endswith(".ibt"):
                        add(n, "e", os.path.join(d, n), "ibt")
                    elif low.endswith(".renpz"):
                        add(n, "e", os.path.join(d, n), "renpz")
            except OSError:
                pass
        return found

    def _settled(self, path, kind):
        """(finished?, reason)"""
        st = os.stat(path)
        key = (st.st_size, int(st.st_mtime))
        prev = self._seen.get(path)
        if prev is None or prev[0] != key:
            self._seen[path] = prev = (key, _now())
        age = _now() - st.st_mtime
        need = RENPZ_SETTLE_S if kind == "renpz" else SETTLE_S
        if age < need or (_now() - prev[1] < need and age < 120):
            return False, "being written"
        if kind == "ibt" and self.in_use(path):
            if age > FORCE_AFTER_S:
                return True, "forced"
            return False, "open in iRacing"
        return True, ""

    # ------------------------------------------------ one pass over everything
    def run_once(self, heavy=True):
        """Copy, summarise, pack and upload whatever needs it. Returns the status dict."""
        from . import telemetry as T
        if not T._drive_ok(self.root):        # #359: the external archive drive is unplugged - wait, touch nothing
            self.status = dict(self.status, state="the archive drive isn't connected - recordings wait on this PC")
            return self.status
        if not self.lock():
            self.status = dict(self.status, state="another vault worker is busy (logon task?)")
            return self.status
        try:
            self.load()
            found = self.discover()
            new_e = 0
            # newest first: if anything runs short (Drive cap, time) it's the newest drives that are safe first
            order = sorted(found.items(), key=lambda kv: -_started(kv[0], self._mtime(kv[1])))
            for name, r in order:
                if not self.alive:
                    break
                try:
                    if self._step_e(name, r):
                        new_e += 1
                except InterruptedError:
                    break
                except Exception as e:
                    self._err(name, "pc", e)
                self.touch_lock()
            for name, ent in self.files.items():          # kept before, now nowhere on this PC: say so loudly
                if name not in found and ent.get("state") == "kept":
                    if ent.get("kind") == "renpz":             # the engineer's own copy of a drive iRacing also recorded
                        self._set(ent, state="gone", why="replaced by iRacing's own recording of that drive")
                        continue
                    on_drive = (ent.get("drive") or {}).get("state") == "ok"
                    self._set(ent, state="lost", why="the PC copy is gone" + (" - the Drive copy is safe (--restore)" if on_drive else ""))
                    self.log(f"[vault] {name}: the PC copy is gone!" + (" Its Drive copy is safe." if on_drive else ""))
            if self._dirty:
                self.save()
            if heavy and self.alive and not self.busy():
                for name, ent in sorted(self.files.items(), key=lambda kv: -(kv[1].get("started") or 0)):
                    if not self.alive or self.busy():
                        break
                    try:
                        self._step_summary(ent)
                    except InterruptedError:
                        break
                    except Exception as e:
                        self._err(name, "summary", e)
                    if self._dirty:
                        self.save()
                self._step_drive()
            if self._dirty:
                self.save()
            self.status = self._status(new_e)
            return self.status
        finally:
            self.unlock()

    @staticmethod
    def _mtime(r):
        for p in [r.get("src")] + list(r.get("e") or []):
            try:
                if p:
                    return os.path.getmtime(p)
            except OSError:
                pass
        return 0.0

    def _err(self, name, where, e):
        ent = self.files.get(name)
        msg = f"{where}: {e!r}"[:300]
        if ent is not None and ent.get("error") != msg:
            ent["error"] = msg
            self._dirty = True
            self.log(f"[vault] {name}: {msg}")

    # ------------------------------------------------ step 1: the exact copy on this PC
    def _step_e(self, name, r):
        ent = self.files.get(name)
        if ent is None:
            ent = self.files[name] = {"name": name, "kind": r["kind"], "first_seen": _now(), "state": "new"}
            self._dirty = True
        src, cands = r["src"], [p for p in r["e"] if os.path.exists(p)]
        ent["src"] = src
        if ent.get("e_path") and ent["e_path"] not in cands and os.path.exists(ent["e_path"]):
            cands.append(ent["e_path"])
        # the engineer's own recording: it already lives in the archive
        if ent["kind"] == "renpz":
            if not cands and src and os.path.exists(src):
                # #359: recorded while the archive drive was unplugged (in the fallback folder): copy it into the archive
                ok, why = self._settled(src, "renpz")
                if not ok:
                    self._set(ent, state="waiting", why=why)
                    return False
                if self.busy():
                    return False
                return self._copy_in(ent, src, os.stat(src), cands)
            if not cands:
                if ent.get("state") != "gone":
                    ent["state"] = "gone"; self._dirty = True        # replaced by iRacing's own file of that drive
                return False
            p = cands[0]
            ok, why = self._settled(p, "renpz")
            if not ok:
                self._set(ent, state="waiting", why=why)
                return False
            st = os.stat(p)
            if ent.get("sha256") and ent.get("size") == st.st_size and ent.get("mtime") == int(st.st_mtime):
                return False
            if self.busy():
                return False
            sha = _sha(p, self._pace_light)
            self._adopt(ent, p, sha, st)
            return True
        if src and os.path.exists(src):
            st = os.stat(src)
            if st.st_size == 0:
                self._set(ent, state="empty", why="0-byte file (iRacing stub) - nothing to keep")
                return False
            done = ent.get("state") == "kept" and ent.get("sha256") and ent.get("e_path") and os.path.exists(ent["e_path"])
            cur = [st.st_size, int(st.st_mtime)]
            if done and ([ent.get("size"), ent.get("mtime")] == cur or ent.get("src_seen") == cur):
                return False
            ok, why = self._settled(src, "ibt")
            if not ok:
                self._set(ent, state="waiting", why=why)
                return False
            if done:
                # iRacing changed the file after we kept it (rare): keep this version too, next to the first
                stem, ext = os.path.splitext(name)
                k = 2
                while f"{stem} ({k}){ext}" in self.files:
                    k += 1
                name2 = f"{stem} ({k}){ext}"
                self.log(f"[vault] {name} changed after it was kept - keeping the new version as {name2}")
                ent2 = self.files[name2] = {"name": name2, "kind": "ibt", "first_seen": _now(), "state": "new", "src": src}
                if self._copy_in(ent2, src, st, []):
                    ent["src_seen"] = cur                    # this version is kept now (as name2)
                    return True
                del self.files[name2]
                return False
            return self._copy_in(ent, src, st, cands)
        # only the archive copy is left (iRacing's file was deleted, or an old copy): make sure it's indexed
        if ent.get("state") == "damaged":
            return False                                 # never accept a changed copy as the real thing
        if not cands:
            if ent.get("state") not in ("empty", "lost"):
                self._set(ent, state="lost", why="no copy anywhere on this PC")
                self.log(f"[vault] {name}: no copy left on this PC!")
            return False
        p = ent["e_path"] if ent.get("e_path") in cands else cands[0]
        st = os.stat(p)
        if st.st_size == 0:
            self._set(ent, state="empty", why="0-byte file")
            return False
        if ent.get("state") == "kept" and ent.get("sha256") and ent.get("e_path") == p and ent.get("size") == st.st_size:
            return False
        if self.busy():
            return False
        sha = _sha(p, self._pace_light)
        if ent.get("sha256") and sha != ent["sha256"]:
            self._set(ent, state="damaged", why="PC copy changed - the Drive copy is never removed")
            self.log(f"[vault] {name}: the PC copy no longer matches its checksum!")
            return False
        self._adopt(ent, p, sha, st)
        return True

    def _set(self, ent, **kw):
        for k, v in kw.items():
            if ent.get(k) != v:
                ent[k] = v
                self._dirty = True

    def _adopt(self, ent, path, sha, st):
        ent.update(e_path=path, sha256=sha, size=st.st_size, mtime=int(st.st_mtime), state="kept", why="",
                   e_verified=_now(), kept_at=_now(), started=_started(ent["name"], st.st_mtime))
        ent.setdefault("summary", {"state": "pending", "tries": 0})
        ent.setdefault("drive", {"state": "pending"})
        ent.pop("error", None)
        self._dirty = True
        self.status["last_saved"] = {"name": ent["name"], "at": _now()}

    def _copy_in(self, ent, src, st, cands):
        # an older archive copy of the same file (the flat folder from before the vault)? use it when it matches
        for c in cands:
            try:
                if os.path.getsize(c) == st.st_size:
                    hs, hc = _sha(src, self._pace_light), _sha(c, self._pace_light)
                    if hs == hc:
                        self._adopt(ent, c, hs, st)
                        return True
            except OSError:
                pass
        free = shutil.disk_usage(self.root).free if os.path.isdir(self.root) else 0
        if free < self.e_min_free + st.st_size:
            self._set(ent, state="waiting", why=f"the archive drive is nearly full ({free / 1e9:.0f} GB free) - nothing is deleted; make room")
            if not self.status.get("e_full_said"):
                self.status["e_full_said"] = True
                self.log(f"[vault] the archive drive ({self.root}) is nearly full - recordings wait in iRacing's folder")
            return False
        y, m = _ym(ent["name"], st.st_mtime)
        dst = os.path.join(self.root, y, m, ent["name"])
        if os.path.exists(dst):                          # a different file under the same name: never overwrite
            stem, ext = os.path.splitext(dst)
            k = 2
            while os.path.exists(f"{stem} ({k}){ext}"):
                k += 1
            dst = f"{stem} ({k}){ext}"
        sha, n = copy_verified(src, dst, pace=self._pace_light)
        self._adopt(ent, dst, sha, st)
        self.log(f"[vault] kept {ent['name']} ({n / 1e6:.0f} MB) in {os.path.dirname(dst)} - checked")
        return True

    # ------------------------------------------------ step 2: the session summary (+ rebuilding the lap memory)
    def _sum_path(self, ent):
        y, m = _ym(ent["name"], ent.get("mtime"))
        return os.path.join(self.root, "summaries", y, m, ent["name"] + ".json")

    def _step_summary(self, ent):
        s = ent.get("summary") or {}
        if ent.get("state") != "kept" or s.get("state") == "ok" and os.path.exists(s.get("path") or ""):
            return
        if s.get("state") == "error" and s.get("tries", 0) >= SUMMARY_TRIES:
            return
        from .telemetry import Session
        try:
            se = Session(ent["e_path"])
            data = summarise(se, ent)
        except Exception as e:
            s["tries"] = s.get("tries", 0) + 1
            s["state"] = "error"; s["error"] = repr(e)[:200]
            ent["summary"] = s; self._dirty = True
            if s["tries"] >= SUMMARY_TRIES:
                self.log(f"[vault] {ent['name']}: can't read it for a summary ({e!r}) - the file itself is kept")
            return
        p = self._sum_path(ent)
        _write_json(p, data)
        ent["summary"] = {"state": "ok", "path": p, "tries": s.get("tries", 0)}
        for k in ("car", "track", "track_name", "subsession", "session_types", "best", "incidents", "laps_complete"):
            ent[k] = data.get(k)
        self._dirty = True
        if self.on_new:
            try:
                self.on_new(ent, se)
            except Exception as e:
                self.log(f"[vault] after {ent['name']}: {e!r}")
        del se

    # ------------------------------------------------ step 3: Google Drive
    def drive_state(self):
        if not self.drive_on:
            return "off"
        if forbidden(self.drive):
            return "blocked"
        anchor = self.anchor or _anchor(self.drive)
        if not os.path.isdir(anchor):
            return "offline"
        try:
            os.makedirs(self.drive, exist_ok=True)
        except OSError:
            return "offline"
        return "ok"

    def drive_usage(self):
        tot = 0
        for dp, _, fs in os.walk(os.path.join(self.drive, "raw")):
            for f in fs:
                try:
                    tot += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
        return tot

    def _step_drive(self):
        st = self.drive_state()
        self.status["drive"] = st
        if st == "blocked" and not self.status.get("blocked_said"):
            self.status["blocked_said"] = True
            self.log("[vault] the Drive folder is on H: (the business account) - not used. Pick a folder on G:.")
        if st != "ok":
            return
        ents = sorted((e for e in self.files.values() if e.get("state") == "kept"), key=lambda e: -(e.get("started") or 0))
        # summaries first (tiny, always kept)
        for ent in ents:
            s = ent.get("summary") or {}
            if s.get("state") != "ok" or not os.path.exists(s.get("path") or ""):
                continue
            y, m = _ym(ent["name"], ent.get("mtime"))
            dst = os.path.join(self.drive, "summaries", y, m, os.path.basename(s["path"]))
            try:
                if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(s["path"]):
                    copy_verified(s["path"], dst)
                    s["drive_path"] = dst; self._dirty = True
            except Exception as e:
                self._err(ent["name"], "drive summary", e)
                self.status["drive"] = "offline" if self.drive_state() != "ok" else "error"
                return
        # packed raw copies, newest first, within the cap
        for ent in ents:
            if not self.alive or self.busy():
                break
            dv = ent.setdefault("drive", {"state": "pending"})
            if dv.get("state") == "ok" and os.path.exists(dv.get("path") or ""):
                continue
            if dv.get("state") in ("trimmed", "quota"):
                continue
            try:
                self._upload(ent)
            except InterruptedError:
                break
            except Exception as e:
                dv["state"] = "pending"; dv["tries"] = dv.get("tries", 0) + 1
                self._err(ent["name"], "drive", e)
                if self.drive_state() != "ok":
                    self.status["drive"] = "offline"
                    break
            if self._dirty:
                self.save()
        try:
            if self._dirty:
                self.save()
            dst = os.path.join(self.drive, INDEX)
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(self.ipath) - 1:
                copy_verified(self.ipath, dst)
            readme = os.path.join(self.drive, "README.txt")
            if not os.path.exists(readme):
                with open(readme, "w", encoding="utf-8") as f:
                    f.write(README)
        except Exception as e:
            self.log(f"[vault] Drive index: {e!r}")

    def _upload(self, ent):
        dv = ent["drive"]
        y, m = _ym(ent["name"], ent.get("mtime"))
        est = ent["size"] / 12.0 if ent["kind"] == "ibt" else ent["size"]     # optimistic: only skips packing a sure no-fit
        if not self._room(est, ent, trim=False):
            dv.update(state="quota"); self._dirty = True
            self.log(f"[vault] Drive cap ({self.quota / 1e9:.0f} GB) is full of newer drives - {ent['name']} kept on this PC only")
            return
        staged = None
        if ent["kind"] == "ibt":
            stage_dir = os.path.join(self.root, "_staging")
            os.makedirs(stage_dir, exist_ok=True)
            staged = os.path.join(stage_dir, ent["name"] + ".ibtz")
            if not (os.path.exists(staged) and _staged_ok(staged, ent["sha256"])):
                part = staged + ".part"
                C.pack(ent["e_path"], part, sha256=ent["sha256"], pace=self._pace_heavy)
                self._pace_heavy()
                if not C.verify(part, ent["sha256"]):
                    os.remove(part)
                    raise IOError("packed copy didn't unpack to the original")
                os.replace(part, staged)
            up = staged
        else:
            up = ent["e_path"]
        zsize = os.path.getsize(up)
        if not self._room(zsize, ent, trim=True):
            dv.update(state="quota"); self._dirty = True
            self.log(f"[vault] Drive cap ({self.quota / 1e9:.0f} GB) is full of newer drives - {ent['name']} kept on this PC only")
            if staged:
                _rm(staged)
            return
        self._pace_heavy()
        dst = os.path.join(self.drive, "raw", y, m, os.path.basename(up))
        zsha, _ = copy_verified(up, dst, pace=self._pace_heavy)
        dv.update(state="ok", path=dst, zsize=zsize, zsha=zsha, at=_now())
        dv.pop("tries", None)
        ent.pop("error", None)
        self._dirty = True
        self.status["last_drive"] = {"name": ent["name"], "at": _now()}
        self.log(f"[vault] {ent['name']} is in Google Drive ({zsize / 1e6:.0f} MB packed, {ent['size'] / max(1, zsize):.1f}x smaller) - checked")
        if staged:
            _rm(staged)

    def _room(self, need, ent, trim):
        """Is there room in the Drive cap for `need` bytes? With trim: make it, removing the OLDEST packed copies
        (older than this drive) whose copy on this PC still checks out."""
        if self.quota <= 0:
            return False
        try:
            free = shutil.disk_usage(self.anchor or _anchor(self.drive)).free
        except OSError:
            free = None
        if free is not None and free < need + DRIVE_MIN_FREE_GB * 1e9:
            self.status["drive_full"] = True
            return False
        used = self.drive_usage()
        if used + need <= self.quota:
            return True
        mine = ent.get("started") or 0
        olds = sorted((e for e in self.files.values() if (e.get("drive") or {}).get("state") == "ok" and e.get("state") == "kept"
                       and (e.get("started") or 0) < mine and e is not ent), key=lambda e: e.get("started") or 0)
        room = used
        plan = []
        for o in olds:
            if room + need <= self.quota:
                break
            plan.append(o); room -= (o["drive"].get("zsize") or 0)
        if room + need > self.quota:
            return False
        if not trim:
            return True
        for o in plan:
            if used + need <= self.quota:
                break
            if not self.verify_e(o):
                self.log(f"[vault] {o['name']}: the PC copy doesn't check out - its Drive copy is kept")
                continue
            try:
                os.remove(o["drive"]["path"])
            except FileNotFoundError:
                pass
            used -= o["drive"].get("zsize") or 0
            o["drive"].update(state="trimmed", trimmed_at=_now())
            self._dirty = True
            self.log(f"[vault] Drive cap: made room by removing the oldest Drive copy ({o['name']}) - the PC copy is checked and kept")
        return used + need <= self.quota

    # ------------------------------------------------ checks
    def verify_e(self, ent):
        p = ent.get("e_path")
        try:
            ok = bool(p and os.path.exists(p) and os.path.getsize(p) == ent.get("size") and _sha(p, self._pace_light) == ent.get("sha256"))
        except OSError:
            ok = False
        if ok:
            ent["e_verified"] = _now(); self._dirty = True
        return ok

    def verify_all(self, deep=False, out=print):
        """Re-check every copy. -> list of problems (strings)."""
        self.load()
        bad = []
        for name, ent in sorted(self.files.items()):
            if ent.get("state") != "kept":
                if ent.get("state") == "lost":
                    bad.append(f"{name}: no copy left on this PC")
                continue
            if not self.verify_e(ent):
                bad.append(f"{name}: PC copy missing or changed ({ent.get('e_path')})")
                if ent.get("src") and os.path.exists(ent["src"]):
                    ent["state"] = "new"; ent.pop("sha256", None)        # iRacing still has it: copied again on the next scan
                else:
                    ent["state"] = "damaged"; ent["why"] = "PC copy changed - the Drive copy is never removed"
                self._dirty = True
            dv = ent.get("drive") or {}
            if dv.get("state") == "ok":
                p = dv.get("path")
                if not p or not os.path.exists(p):
                    bad.append(f"{name}: Drive copy missing - queued again")
                    dv["state"] = "pending"; self._dirty = True
                elif os.path.getsize(p) != dv.get("zsize") or _sha(p) != dv.get("zsha"):
                    bad.append(f"{name}: Drive copy damaged - queued again")
                    dv["state"] = "pending"; self._dirty = True
                elif deep and ent["kind"] == "ibt" and not C.verify(p, ent.get("sha256")):
                    bad.append(f"{name}: Drive copy doesn't unpack to the original - queued again")
                    dv["state"] = "pending"; self._dirty = True
            out(f"  {'ok ' if not bad or not bad[-1].startswith(name) else 'BAD'} {name}")
        if self._dirty and self.lock():
            try:
                self.save()
            finally:
                self.unlock()
        return bad

    # ------------------------------------------------ status
    def _status(self, new_e=0):
        files = self.files.values()
        kept = [e for e in files if e.get("state") == "kept"]
        waiting = [e for e in files if e.get("state") == "waiting"]
        dpend = [e for e in kept if (e.get("drive") or {}).get("state") in ("pending", None)]
        ds = self.status.get("drive") or self.drive_state()
        last = max(kept, key=lambda e: e.get("kept_at") or 0, default=None)
        st = {"state": "ok", "kept": len(kept), "waiting": len(waiting), "drive": ds, "drive_pending": len(dpend),
              "drive_ok": sum(1 for e in kept if (e.get("drive") or {}).get("state") == "ok"),
              "drive_quota_skipped": sum(1 for e in kept if (e.get("drive") or {}).get("state") == "quota"),
              "lost": [e["name"] for e in files if e.get("state") in ("lost", "damaged")],
              "errors": [f"{e['name']}: {e['error']}" for e in files if e.get("error")][:5],
              "root": self.root, "drive_dir": self.drive, "quota_gb": self.quota / 1e9, "new": new_e,
              "last_saved": self.status.get("last_saved") or ({"name": last["name"], "at": last.get("kept_at")} if last else None),
              "last_drive": self.status.get("last_drive")}
        try:
            st["e_free_gb"] = round(shutil.disk_usage(self.root).free / 1e9, 1)
        except OSError:
            pass
        if ds == "ok":
            try:
                st["drive_used_gb"] = round(self.drive_usage() / 1e9, 2)
            except OSError:
                pass
        for k in ("e_full_said", "blocked_said", "drive_full"):
            if self.status.get(k):
                st[k] = True
        return st


def status_line(st):
    """One line for the app: 'Telemetry: 41 drives kept · last 21:07 · Drive OK (2.1 of 8 GB) · 1 waiting'."""
    if not st:
        return "Telemetry vault: starting"
    if st.get("state") == "off":
        return "Telemetry vault: off"
    if st.get("state") not in ("ok",):
        return f"Telemetry vault: {st.get('state')}"
    bits = [f"{st.get('kept', 0)} recordings kept"]
    ls = st.get("last_saved")
    if ls and ls.get("at"):
        bits.append("last saved " + time.strftime("%a %H:%M", time.localtime(ls["at"])))
    ds = st.get("drive")
    if ds == "ok":
        u = st.get("drive_used_gb")
        bits.append(f"Drive OK ({u:.1f} of {st.get('quota_gb', 0):.0f} GB)" if u is not None else "Drive OK")
    elif ds == "offline":
        bits.append("Drive OFFLINE - copies wait (is Google Drive running?)")
    elif ds == "blocked":
        bits.append("Drive folder is on H: - not used")
    elif ds == "off":
        bits.append("Drive copy off")
    pend = (st.get("waiting") or 0) + (st.get("drive_pending") or 0)
    if pend:
        bits.append(f"{pend} waiting")
    if st.get("lost"):
        bits.append(f"{len(st['lost'])} MISSING")
    if st.get("e_full_said"):
        bits.append("PC archive drive nearly full")
    return "Telemetry: " + " · ".join(bits)


def _anchor(drive):
    """The folder that must exist for Drive to count as running: the 'My Drive' folder in the path, else the drive root."""
    parts = os.path.normpath(drive).split(os.sep)
    for i, p in enumerate(parts):
        if p.lower() == "my drive":
            return os.sep.join(parts[: i + 1]) or os.sep
    d = os.path.splitdrive(drive)[0]
    return (d + os.sep) if d else os.path.dirname(drive)


def _staged_ok(path, sha):
    try:
        return C.read_header(path)[0].get("sha256") == sha and C.verify(path, sha)
    except Exception:
        return False


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def copy_verified(src, dst, pace=None):
    """src -> dst through a temp file: hashed while reading, flushed to disk, the temp re-read and compared, then
    renamed into place (with the original's times). The source must not change while it's copied. -> (sha256, bytes)"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + ".partial"
    st0 = os.stat(src)
    h, n = hashlib.sha256(), 0
    try:
        with open(src, "rb") as f, open(part, "wb") as o:
            while True:
                b = f.read(CHUNK)
                if not b:
                    break
                h.update(b); o.write(b); n += len(b)
                pace and pace()
            o.flush()
            os.fsync(o.fileno())
        st1 = os.stat(src)
        if (st1.st_size, st1.st_mtime) != (st0.st_size, st0.st_mtime) or n != st1.st_size:
            raise IOError("the file changed while it was copied - trying again later")
        if _sha(part) != h.hexdigest():
            raise IOError("the copy didn't match the original - trying again later")
        shutil.copystat(src, part)
        os.replace(part, dst)
    except BaseException:
        _rm(part)
        raise
    return h.hexdigest(), n


README = """Instability Control - telemetry vault (made by the Race Engineer app)

raw\\<year>\\<month>\\*.ibt.ibtz   iRacing telemetry, packed (lossless, about 6x smaller).
                                Unpack: python -m engineer.vault --restore "<file name>.ibt" --out <folder>
raw\\<year>\\<month>\\*.renpz     the engineer's own recordings (already compressed)
summaries\\<year>\\<month>\\*.json laps, best lap, incidents and per-corner times of every session
vault_index.json                what is kept where, with SHA-256 checksums

The full-size originals are on the PC (E:\\RaceEngineer\\telemetry). This folder is capped in size: when it's full the
oldest packed copies are removed here (only after the PC copy is checked). Summaries are always kept.
This folder is private: don't share it.
"""


# ---------------------------------------------------------------- the app's background worker
class Worker:
    """Runs the vault in the app: a pass every 30 s (sooner after you leave the car), background priority."""

    def __init__(self, settings, log=print, busy=None, on_new=None, on_kept=None):
        self.s = settings
        self.log = log
        self.busy = busy or (lambda: False)
        self.on_new = on_new
        self.on_kept = on_kept
        self.status = {"state": "starting"}
        self.alive = True
        self._kick = threading.Event()
        self.v = None
        threading.Thread(target=self._run, daemon=True, name="vault").start()

    def kick(self):
        self._kick.set()

    def stop(self):
        self.alive = False
        if self.v:
            self.v.alive = False
        self._kick.set()

    def _make(self):
        s = self.s
        return Vault(root=(getattr(s, "vault_dir", "") or None), drive=(getattr(s, "vault_drive_dir", "") or DRIVE_DEFAULT),
                     drive_on=bool(getattr(s, "vault_drive_on", False)), quota_gb=float(getattr(s, "vault_drive_quota_gb", 8.0) or 0),
                     log=self.log, busy=self.busy, on_new=self.on_new)

    def _run(self):
        background_thread()
        time.sleep(6)
        was_busy = False
        while self.alive:
            try:
                if not getattr(self.s, "vault_on", True):
                    self.status = {"state": "off"}
                else:
                    v = self._make()
                    if self.v is not None:
                        v._seen, v.status = self.v._seen, dict(self.v.status)
                    self.v = v
                    st = v.run_once(heavy=True)
                    self.status = st
                    if st.get("new") and self.on_kept:
                        self.on_kept(st["new"])
            except Exception as e:
                self.status = dict(self.status, state=f"problem: {e!r}"[:120])
                self.log(f"[vault] {e!r}")
            # wait 30 s, or less once you've just left the car (the file closes then)
            t_end = time.time() + 30
            while self.alive and time.time() < t_end:
                b = self.busy()
                if was_busy and not b:
                    t_end = min(t_end, time.time() + SETTLE_S + 3)
                was_busy = b
                if self._kick.wait(1.0):
                    self._kick.clear()
                    break


# ---------------------------------------------------------------- command line
def _cli_busy():
    """Command line: pause the heavy work while iRacing says you're in the car (no SDK: never busy)."""
    try:
        import irsdk
        ir = irsdk.IRSDK()
        if not ir.startup():
            return lambda: False
    except Exception:
        return lambda: False
    last = [0.0, False]
    def busy():
        if time.time() - last[0] > 2:
            last[0] = time.time()
            try:
                last[1] = bool(ir.is_connected and ir["IsOnTrack"] and not ir["IsReplayPlaying"])
            except Exception:
                last[1] = False
        return last[1]
    return busy


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m engineer.vault", description="Instability Control telemetry vault")
    ap.add_argument("--scan", action="store_true", help="copy / pack / upload anything not kept yet")
    ap.add_argument("--verify", action="store_true", help="re-check every copy against its checksum")
    ap.add_argument("--deep", action="store_true", help="with --verify: also unpack every Drive copy")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--restore", metavar="NAME", help="unpack the Drive copy of NAME back to an .ibt")
    ap.add_argument("--out", default=".", help="folder for --restore")
    ap.add_argument("--root", help="the PC archive folder (default: the app's setting / E:\\RaceEngineer\\telemetry)")
    ap.add_argument("--src", action="append", help="iRacing telemetry folder (default: Documents\\iRacing\\telemetry)")
    ap.add_argument("--drive", help="the Google Drive folder")
    ap.add_argument("--no-drive", action="store_true")
    ap.add_argument("--quota", type=float, help="Drive cap in GB")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--log", help="also append what happens to this file (the logon task uses vault_log.txt)")
    a = ap.parse_args(argv)
    try:
        from .settings import Settings
        s = Settings.load()
    except Exception:
        s = None
    g = lambda k, d: getattr(s, k, d) if s is not None else d
    def log(m):
        if not a.quiet:
            print(m)
        if a.log:
            try:
                with open(a.log, "a", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")
            except OSError:
                pass
    v = Vault(root=a.root or g("vault_dir", "") or None, sources=a.src,
              drive=a.drive or g("vault_drive_dir", "") or DRIVE_DEFAULT,
              drive_on=not a.no_drive and (bool(a.drive) or g("vault_drive_on", False)), quota_gb=a.quota if a.quota is not None else g("vault_drive_quota_gb", 8.0),
              log=log, busy=_cli_busy() if a.scan else None)
    if a.restore:
        v.load()
        ent = v.files.get(a.restore) or v.files.get(os.path.basename(a.restore))
        if not ent:
            print(f"not in the vault: {a.restore}"); return 2
        dv = ent.get("drive") or {}
        if ent.get("e_path") and os.path.exists(ent["e_path"]):
            print(f"the full copy is on this PC: {ent['e_path']}")
        if dv.get("state") != "ok" or not os.path.exists(dv.get("path") or ""):
            print("no Drive copy to unpack"); return 1 if not ent.get("e_path") else 0
        out = os.path.join(a.out, ent["name"])
        if dv["path"].endswith(".ibtz"):
            C.unpack(dv["path"], out)
        else:
            shutil.copy2(dv["path"], out)
        print(f"restored {out} (checksum OK)")
        return 0
    if a.scan:
        st = v.run_once(heavy=True)
        log(status_line(st))
        return 0 if not st.get("lost") else 1
    if a.verify:
        bad = v.verify_all(deep=a.deep, out=log)
        print("all copies check out" if not bad else "PROBLEMS:\n  " + "\n  ".join(bad))
        return 0 if not bad else 1
    v.load()
    st = v._status()
    print(status_line(st))
    print(f"  PC archive: {v.root} ({st.get('e_free_gb', '?')} GB free)")
    print(f"  Drive:      {v.drive} - {st.get('drive')}")
    for e in sorted(v.files.values(), key=lambda e: -(e.get("started") or 0))[:25]:
        dv = (e.get("drive") or {}).get("state", "-")
        print(f"  {e.get('state', '?'):8} drive:{dv:8} {e['name']}" + (f"  ({e['why']})" if e.get("why") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
