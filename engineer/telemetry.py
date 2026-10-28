"""Reads iRacing .ibt telemetry: laps, track map, corners, setup, and per-corner driving metrics.

Fast reader: the file's sample buffers are viewed with numpy instead of decoding sample by sample.
"""
import glob, hashlib, json, math, os, re, struct, time
import numpy as np

def _documents():
    """# beta (2026-10-24): the real Documents folder (OneDrive often moves it); same as before when it isn't moved."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x05, None, 0, buf) == 0 and os.path.isdir(buf.value):
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


TELEMETRY_DIR = os.path.join(_documents(), "iRacing", "telemetry")
CACHE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RaceEngineer", "cache")

CHANNELS = ["SessionTime", "SessionNum", "Lap", "LapDist", "LapDistPct", "LapLastLapTime", "LapCurrentLapTime",
            "Lat", "Lon", "Alt", "Speed", "Throttle", "Brake", "BrakeABSactive", "SteeringWheelAngle", "Gear", "RPM",
            "LatAccel", "LongAccel", "VertAccel", "YawRate", "VelocityX", "VelocityY", "OnPitRoad", "IsOnTrack",
            "PlayerTrackSurface", "PlayerCarMyIncidentCount", "dcBrakeBias", "dcABS", "dcTractionControl",
            "dcTractionControl2", "dcAntiRollFront", "dcAntiRollRear", "dcBrakeMisc",
            "LFrideHeight", "RFrideHeight", "LRrideHeight", "RRrideHeight",
            "LFshockDefl", "RFshockDefl", "LRshockDefl", "RRshockDefl",
            "TireLF_RumblePitch", "TireRF_RumblePitch", "TireLR_RumblePitch", "TireRR_RumblePitch",
            "FuelLevel", "TrackTempCrew", "TrackWetness", "AirTemp", "PitSvFlags", "SessionTimeRemain"]

_DT = {0: "S1", 1: "?", 2: "<i4", 3: "<u4", 4: "<f4", 5: "<f8"}
_SZ = {0: 1, 1: 1, 2: 4, 3: 4, 4: 4, 5: 8}


# ---------------------------------------------------------------- raw file
def read_ibt(path, channels=CHANNELS):
    """-> (data dict name->np.array, session-info yaml text, tick rate)."""
    if str(path).lower().endswith(".renpz"):          # the engineer's own recording (recorder.py), same shape
        from .recorder import read_renpz
        return read_renpz(path)
    with open(path, "rb") as f:
        head = f.read(144)
        ver, status, tick_rate, si_update, si_len, si_off, num_vars, vh_off, num_buf, buf_len = struct.unpack_from("<10i", head, 0)
        buf_off = struct.unpack_from("<i", head, 48 + 4)[0]   # varBuf[0].bufOffset
        f.seek(112)
        disk = f.read(32)
        rec_count = struct.unpack_from("<i", disk, 28)[0]
        # 2026-10-27: a file iRacing never finished (crash, power cut) has no record count in its header - use its size
        whole = (os.path.getsize(path) - buf_off) // buf_len if buf_len > 0 else 0
        if rec_count <= 0 or rec_count > whole:
            rec_count = whole
        f.seek(vh_off)
        vh = f.read(num_vars * 144)
        f.seek(si_off)
        si = f.read(si_len).rstrip(b"\x00").decode("cp1252", "replace")
    headers = {}
    for i in range(num_vars):
        typ, off, cnt = struct.unpack_from("<3i", vh, i * 144)
        name = vh[i * 144 + 16: i * 144 + 48].split(b"\x00")[0].decode()
        headers[name] = (typ, off, cnt)
    mm = np.memmap(path, dtype=np.uint8, mode="r", offset=buf_off, shape=(rec_count, buf_len))
    data = {}
    for name in channels:
        if name not in headers:
            continue
        typ, off, cnt = headers[name]
        if cnt != 1 or typ == 0:
            continue
        sz = _SZ[typ]
        col = np.ascontiguousarray(mm[:, off:off + sz]).view(_DT[typ]).reshape(-1)
        data[name] = col.astype(np.float64) if typ in (4, 5) else col.astype(np.int64) if typ in (2, 3) else col.astype(bool)
    del mm
    return data, si, tick_rate


def parse_yaml(text):
    import yaml
    # iRacing's YAML has unquoted values that trip strict parsers (e.g. team names with ':' or '@')
    text = re.sub(r"(\w+: )([^\n]*@[^\n]*)", lambda m: m.group(1) + "'" + m.group(2).replace("'", "''") + "'", text)
    try:
        return yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or {}
    except Exception:
        out = {}
        for sec in ("WeekendInfo", "DriverInfo", "CarSetup"):   # salvage the sections we need
            m = re.search(rf"^{sec}:\n(?: .*\n)+", text, re.M)
            if m:
                try:
                    out.update(yaml.safe_load(m.group(0)) or {})
                except Exception:
                    pass
        return out


# ---------------------------------------------------------------- sessions
_NAME = re.compile(r"^(?P<car>[^_]+)_(?P<track>.+) (?P<date>\d{4}-\d\d-\d\d \d\d-\d\d-\d\d)$")


# 2026-10-26 (the developer's recordings vanished: the Garage 61 agent deletes every .ibt 7 days after it was written).
# The engineer keeps its own copy of each recording, on the drive with the most room (E: on the developer's PC), capped in
# size - only these copies are ever trimmed, never iRacing's own files. Analysis / Series read both folders.
ARCHIVE_CAP_GB = 20.0
ARCHIVE_MIN_FREE_GB = 15.0


ARCHIVE_DIR_OVERRIDE = ""          # 2026-10-27: the app sets this from Settings > Telemetry vault ("" = automatic)


def fallback_dir():
    """2026-10-27 (#359, request: "E: is an external hard drive... be careful"): where recordings go while the
    archive drive is unplugged - Documents\\RaceEngineer\\telemetry on the system drive. Analysis lists it, and the
    vault copies anything left here into the archive once the drive is back."""
    return os.path.join(_documents(), "RaceEngineer", "telemetry")


def _drive_ok(path):
    try:
        root = os.path.splitdrive(os.path.abspath(path))[0]
        return not root or os.path.isdir(root + "\\")
    except Exception:
        return False


def archive_dir():
    if ARCHIVE_DIR_OVERRIDE and _drive_ok(ARCHIVE_DIR_OVERRIDE):     # a chosen folder on an unplugged drive: automatic
        return ARCHIVE_DIR_OVERRIDE
    cands = []
    for root in ("E:\\", "D:\\"):
        try:
            if os.path.isdir(root):
                import shutil as _sh
                cands.append((_sh.disk_usage(root).free, os.path.join(root, "RaceEngineer", "telemetry")))
        except Exception:
            pass
    home = os.path.join(_documents(), "RaceEngineer", "telemetry")
    try:
        import shutil as _sh
        cands.append((_sh.disk_usage(_documents()).free, home))
    except Exception:
        cands.append((0, home))
    for _, d in sorted(cands, reverse=True):          # an existing archive wins (never split it), else the roomiest drive
        if os.path.isdir(d) and (glob.glob(os.path.join(d, "*.ibt")) or os.path.exists(os.path.join(d, "vault_index.json"))
                                 or glob.glob(os.path.join(d, "[12][0-9][0-9][0-9]", "[01][0-9]", "*.ibt"))):
            return d
    return sorted(cands, reverse=True)[0][1]


def archive_new(log=print, trim=False):
    """Copy every finished recording that isn't kept yet. Returns copies made. 2026-10-27: the telemetry vault
    (vault.py) does this job now, with checksums and the Drive copy; this is only its fallback and never trims
    (trim=True is the old behaviour: the oldest copies over the cap were deleted)."""
    import shutil
    dst = archive_dir()
    try:
        os.makedirs(dst, exist_ok=True)
    except OSError as e:
        log(f"[archive] can't make {dst}: {e!r}")
        return 0
    n, now = 0, time.time()
    for p in glob.glob(os.path.join(TELEMETRY_DIR, "*.ibt")):
        try:
            st = os.stat(p)
            if st.st_size < 1_500_000 or now - st.st_mtime < 30:     # too short, or iRacing is still writing it
                continue
            q = os.path.join(dst, os.path.basename(p))
            if os.path.exists(q) and os.path.getsize(q) == st.st_size:
                continue
            if shutil.disk_usage(dst).free < (ARCHIVE_MIN_FREE_GB * 1e9 + st.st_size):
                log("[archive] not enough free space to keep a copy")
                break
            shutil.copy2(p, q + ".part"); os.replace(q + ".part", q)
            n += 1
        except Exception as e:
            log(f"[archive] {os.path.basename(p)}: {e!r}")
    try:                                           # trim: oldest copies first, only inside the archive
        if not trim:
            raise StopIteration
        files = sorted(glob.glob(os.path.join(dst, "*.ibt")), key=os.path.getmtime)
        total = sum(os.path.getsize(f) for f in files)
        while files and total > ARCHIVE_CAP_GB * 1e9:
            f = files.pop(0)
            if os.path.exists(os.path.join(TELEMETRY_DIR, os.path.basename(f))):
                continue                           # iRacing still has it: keep the copy anyway, trim older ones
            total -= os.path.getsize(f); os.remove(f)
    except StopIteration:
        pass
    except Exception as e:
        log(f"[archive] trim: {e!r}")
    if n:
        log(f"[archive] kept a copy of {n} recording(s) in {dst}")
    return n


def list_sessions(folder=None):
    """Recordings from iRacing's folder plus the engineer's own copies (same file name = one session)."""
    if folder is not None:
        return _list_one(folder)
    seen, out = set(), []
    dirs = [TELEMETRY_DIR]
    try:
        dirs.append(archive_dir())
    except Exception:
        pass
    fb = fallback_dir()                              # #359: anything recorded while the archive drive was unplugged
    if os.path.isdir(fb) and all(os.path.normcase(os.path.abspath(fb)) != os.path.normcase(os.path.abspath(d)) for d in dirs):
        dirs.append(fb)
    for k, d in enumerate(dirs):
        for s in _list_one(d, deep=k > 0):         # the archive keeps <year>\<month>\ folders (vault.py)
            b = os.path.basename(s["path"]).lower()
            if b not in seen:
                seen.add(b); out.append(s)
    out.sort(key=lambda s: s["mtime"], reverse=True)
    return out


def _list_one(folder, deep=False):
    out = []
    pats = ["*.ibt", "*.renpz"]
    if deep:
        pats += [os.path.join("[12][0-9][0-9][0-9]", "[01][0-9]", x) for x in ("*.ibt", "*.renpz")]
    for p in [q for pat in pats for q in glob.glob(os.path.join(folder, pat))]:
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_size < (150_000 if p.lower().endswith(".renpz") else 1_500_000):   # too short to hold a lap
            continue
        base = os.path.splitext(os.path.basename(p))[0]
        m = _NAME.match(base)
        car, track, date = (m.group("car"), m.group("track"), m.group("date")) if m else ("?", base, "")
        out.append({"id": _sid(p, st), "path": p, "car": car, "track": track, "date": date.replace("-", ":", 0),
                    "size_mb": round(st.st_size / 1e6, 1), "mtime": st.st_mtime})
    out.sort(key=lambda s: s["mtime"], reverse=True)
    return out


def _sid(path, st=None):
    st = st or os.stat(path)
    return hashlib.md5(f"{os.path.basename(path)}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]


CAR_NAMES = {"bmwlmdh": "BMW M Hybrid V8", "bmwm4gt3": "BMW M4 GT3", "bmwm4evogt3": "BMW M4 GT3 EVO",
             "bmwm2g87": "BMW M2", "bmwm4gt4": "BMW M4 GT4"}


def car_name(path_name):
    return CAR_NAMES.get(path_name, path_name)


_SRC_CACHE = {}


def recording_meta(path):
    """2026-10-27 (Analysis bug, replay recordings): what kind of recording this is, without reading its channels.
    -> {"src": "ibt" | "live" | "replay", "pos": "gps" | "map"}. "replay" = the engineer's recording of a replay you
    watched (the car on screen, maybe not you); "map" = its Lat/Lon were made from the cached track map (no GPS in
    replays): metres around (0, 0), not real coordinates. Older replay recordings have no "_pos" marker: a replay
    recording always means map positions."""
    if not str(path).lower().endswith(".renpz"):
        return {"src": "ibt", "pos": "gps"}
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_size, int(st.st_mtime))
    except OSError:
        key = None
    if key in _SRC_CACHE:
        return _SRC_CACHE[key]
    out = {"src": "live", "pos": "gps"}
    try:
        z = np.load(path, allow_pickle=False)
        if "_src" in z.files:
            out["src"] = str(z["_src"])
        if "_pos" in z.files:
            out["pos"] = str(z["_pos"])
        elif out["src"] == "replay":
            out["pos"] = "map"
    except Exception:
        pass
    if key:
        _SRC_CACHE[key] = out
    return out


def is_replay(path):
    return recording_meta(path).get("src") == "replay"


def synthetic_pos(lat, lon):
    """Lat/Lon that are really map metres around (0, 0) (or missing): no real racetrack sits within 0.5 deg of 0N 0E."""
    try:
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        if not len(lat) or not np.isfinite(lat).any():
            return True
        return bool(np.nanmax(np.abs(lat)) < 0.5 and np.nanmax(np.abs(lon)) < 0.5)
    except Exception:
        return True


def lap_dist(d, a, b, track_len):
    """Distance along the lap for samples a..b, monotonic. 2026-10-27: iRacing (and replays most of all) can bump
    Lap a sample or two before LapDist wraps, so a lap can start with ~13553 m and end with ~1 m. Those samples belong
    to the line crossing: they become negative / beyond-the-line distances instead of flattening the whole lap
    (that made every replay lap a single point: no map, the delta = minus the reference's whole lap time)."""
    dist = d["LapDist"][a:b].astype(np.float64).copy()
    n, L = len(dist), float(track_len or 0)
    if L <= 0 and n:
        L = float(np.nanmax(dist))
    if n > 4 and L > 0:
        dist = np.nan_to_num(dist)
        edge = max(2, n // 10)
        lo = np.flatnonzero(dist[:edge] < 0.5 * L)
        if len(lo):
            k = int(lo[0])
            dist[:k] = np.where(dist[:k] > 0.5 * L, dist[:k] - L, dist[:k])
        hi = np.flatnonzero(dist[n - edge:] > 0.5 * L)
        if len(hi):
            k = n - edge + int(hi[-1]) + 1
            dist[k:] = np.where(dist[k:] < 0.5 * L, dist[k:] + L, dist[k:])
    return np.maximum.accumulate(dist)


class Session:
    def __init__(self, path, landmarks=None, channels=None):
        self.path = path
        self.id = _sid(path)
        data, si, self.tick = read_ibt(path, channels or CHANNELS)   # forensics (2026-10-27) asks for a few more channels
        self.d = data
        meta = recording_meta(path)
        self.source = meta["src"]                       # "ibt" / "live" / "replay" (2026-10-27)
        self.pos_synthetic = meta["pos"] == "map" or ("Lat" in data and synthetic_pos(data["Lat"][::600], data["Lon"][::600]))
        self.info = parse_yaml(si)
        wk = self.info.get("WeekendInfo", {}) or {}
        di = self.info.get("DriverInfo", {}) or {}
        me = next((x for x in di.get("Drivers", []) or [] if x.get("CarIdx") == di.get("DriverCarIdx")), {})
        self.track_name = wk.get("TrackName", "")
        self.track_display = wk.get("TrackDisplayName", self.track_name)
        self.car_path = me.get("CarPath") or os.path.basename(path).split("_")[0]
        self.car = me.get("CarScreenName") or car_name(self.car_path)
        self.car_class = me.get("CarClassShortName") or ""
        tl = str(wk.get("TrackLength", "0 km"))
        self.track_len = float(tl.split()[0]) * (1609.34 if "mi" in tl else 1000.0)
        if landmarks is None:
            landmarks = track_landmarks(self.track_name)
        self.setup = self.info.get("CarSetup", {}) or {}
        self.gtp = any(k in (self.car_path + " " + self.car_class).lower() for k in ("lmdh", "gtp"))
        self._split_laps()
        self._traces = {}
        self.landmarks = landmarks
        self.corners = None

    # ---- laps ----
    def _split_laps(self):
        d = self.d
        lap = d["Lap"]
        n = len(lap)
        starts = np.flatnonzero(np.diff(lap) != 0) + 1
        bounds = [0] + list(starts) + [n]
        self.laps = []
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a < self.tick * 20:
                continue
            pct = d["LapDistPct"][a:b]
            on_track = d.get("IsOnTrack", np.ones(n, bool))[a:b]
            pit = d.get("OnPitRoad", np.zeros(n, bool))[a:b]
            # distance actually driven (speed x time) - catches resets/teleports and short out-laps
            covered = float(np.sum(d["Speed"][a:b]) / self.tick)
            # 2026-10-27 (#391): a replay's speed channel adds up a few % short (12873 m on a 13554 m lap) - every
            # replay lap failed the 95 % test and Analysis had nothing to show. Replays: 85 % (the line crossings
            # at both ends still prove it's a whole lap)
            need = 0.85 if self.source == "replay" else 0.95
            complete = (pct[: self.tick].min() < 0.03 and pct[-self.tick:].max() > 0.97 and on_track.all()
                        and covered > need * self.track_len)
            # lap time: iRacing posts it in LapLastLapTime shortly after the line
            t = None
            if b < n and "LapLastLapTime" in d:
                post = d["LapLastLapTime"][b: min(n, b + self.tick * 3)]
                post = post[post > 0]
                if len(post):
                    t = float(post[-1])
            # 2026-10-27: no posted time (replay recordings: LapLastLapTime is always 0 there) - from the moments the
            # car crossed the line, interpolated between samples
            raw = (self._cross_t(b) - self._cross_t(a)) if b < n else float(d["SessionTime"][b - 1] - d["SessionTime"][a])
            if t is None or abs(t - raw) > 2.5:
                t = float(raw)
            inc = d.get("PlayerCarMyIncidentCount")
            incidents = int(inc[b - 1] - inc[a]) if inc is not None else 0
            off = bool((d.get("PlayerTrackSurface", np.full(n, 3))[a:b] == 0).any())
            self.laps.append({"n": int(lap[a]), "a": int(a), "b": int(b), "time": round(t, 3),
                              "complete": bool(complete and b < n), "pit": bool(pit.any()),
                              "incidents": incidents, "off": off})
        valid = [L for L in self.laps if L["complete"] and not L["pit"]]
        for L in self.laps:
            L["valid"] = L in valid and not L["off"] and L["incidents"] == 0
        good = [L for L in self.laps if L["valid"]] or valid
        self.best = min(good, key=lambda L: L["time"]) if good else None

    def _cross_t(self, i):
        """SessionTime the car crossed the line near sample i (where LapDistPct wraps), interpolated."""
        d = self.d
        st = d["SessionTime"]
        pct = d.get("LapDistPct")
        if pct is None:
            return float(st[i])
        w = max(2, int(self.tick))
        lo, hi = max(1, i - w), min(len(pct), i + w)
        jumps = np.flatnonzero(pct[lo:hi] - pct[lo - 1:hi - 1] < -0.5)
        if not len(jumps):
            return float(st[i])
        j = lo + int(jumps[np.argmin(np.abs(jumps + lo - i))])
        before, after = 1.0 - float(pct[j - 1]), float(pct[j])
        f = before / (before + after) if before + after > 1e-9 else 0.0
        return float(st[j - 1] + (st[j] - st[j - 1]) * f)

    def lap(self, n):
        return next((L for L in self.laps if L["n"] == n), None)

    # ---- one lap resampled on distance (1 m grid) ----
    def trace(self, n, step=1.0):
        key = (n, step)
        if key in self._traces:
            return self._traces[key]
        L = self.lap(n)
        d = self.d
        a, b = L["a"], L["b"]
        # keep it monotonic (LapDist can wobble at the line, and can wrap a sample after Lap changes)
        dist = lap_dist(d, a, b, self.track_len)
        keep = np.concatenate([[True], np.diff(dist) > 1e-4])
        dist = dist[keep]
        grid = np.arange(0, min(self.track_len, dist[-1]), step)
        tr = {"d": grid}
        t = d["SessionTime"][a:b][keep]
        tr["t"] = np.interp(grid, dist, t) - float(np.interp(0.0, dist, t))   # 0 at the line itself
        for ch in ("Speed", "Throttle", "Brake", "SteeringWheelAngle", "Gear", "RPM", "LatAccel", "LongAccel",
                   "VertAccel", "YawRate", "VelocityY", "Lat", "Lon", "LFrideHeight", "RFrideHeight", "LRrideHeight",
                   "RRrideHeight", "LFshockDefl", "RFshockDefl", "LRshockDefl", "RRshockDefl", "BrakeABSactive",
                   "TireLF_RumblePitch", "TireRF_RumblePitch", "TireLR_RumblePitch", "TireRR_RumblePitch",
                   "dcBrakeBias", "dcABS", "dcTractionControl", "dcAntiRollFront", "dcAntiRollRear"):
            if ch in d:
                tr[ch] = np.interp(grid, dist, d[ch][a:b][keep].astype(np.float64))
        tr["kmh"] = tr["Speed"] * 3.6
        self._traces[key] = tr
        return tr

    # ---- map ----
    def track_map(self, n=None, points=1600):
        """This session's lap as x/y metres (+ "frame": "gps" or "map"). 2026-10-27: a lap without usable positions
        (a replay recording, a broken lap) draws the app's cached map of the track instead - placed by distance, so
        corner labels, colours and the hover dot sit where they belong whichever recording the reference came from."""
        n = n or (self.best and self.best["n"])
        tr = self.trace(n)
        d = tr["d"]
        idx = np.linspace(0, len(d) - 1, points).astype(int)
        frame = "map" if self.pos_synthetic else "gps"
        x = y = None
        if "Lat" in tr and "Lon" in tr:
            lat, lon = tr["Lat"], tr["Lon"]
            lat0, lon0 = float(np.mean(lat)), float(np.mean(lon))
            R = 6371000.0
            x = (lon - lon0) * math.cos(math.radians(lat0)) * math.pi / 180 * R
            y = (lat - lat0) * math.pi / 180 * R
        if not _map_ok(x, y, self.track_len):
            m = cached_map(self.track_name)
            if m is not None:
                md, mx, my = m
                L = float(md[-1]) or 1.0
                x, y, frame = np.interp(d % L, md, mx), np.interp(d % L, md, my), "map"
            else:
                a = d / max(1.0, self.track_len) * 2 * math.pi        # nothing else: a plain loop, labels in order
                r = max(100.0, self.track_len) / (2 * math.pi)
                x, y, frame = r * np.cos(a), r * np.sin(a), "none"
        return {"x": x[idx].round(1).tolist(), "y": y[idx].round(1).tolist(), "d": d[idx].round(1).tolist(), "frame": frame}

    # ---- corners ----
    def find_corners(self):
        if self.corners is not None:
            return self.corners
        out = []
        if self.landmarks:
            out = [dict(c) for c in self.landmarks]
        if not out:
            out = self._detect_corners()
        self.corners = out
        return out

    def _detect_corners(self):
        """No map for this track: corners = braking zones / speed minima on the best lap."""
        if not self.best:
            return []
        tr = self.trace(self.best["n"])
        v = tr["kmh"]
        from numpy.lib.stride_tricks import sliding_window_view as sw
        w = 151
        pad = np.pad(v, (w // 2, w // 2), mode="edge")
        local_min = v <= sw(pad, w).min(axis=1) + 1e-9
        cands = np.flatnonzero(local_min)
        out, last = [], -1e9
        for i in cands:
            lo, hi = max(0, i - 400), min(len(v) - 1, i + 400)
            if v[lo:hi].max() - v[i] < 12 or tr["d"][i] - last < 120 or tr["d"][i] < 60 or tr["d"][i] > tr["d"][-1] - 60:
                continue
            last = tr["d"][i]
            out.append({"name": f"Turn {len(out) + 1}", "key": f"turn_{len(out) + 1}",
                        "start": float(max(0, tr["d"][i] - 120)), "end": float(min(tr["d"][-1], tr["d"][i] + 80))})
        return out


def _map_ok(x, y, track_len):
    """A drawable track outline: finite and spread over a sensible part of the track length."""
    if x is None or y is None or len(x) < 10:
        return False
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        return False
    span = max(float(np.ptp(x)), float(np.ptp(y)))
    return span > max(50.0, 0.05 * float(track_len or 0)) and span < max(20000.0, 2.0 * float(track_len or 0))


def cached_map(track):
    """The app's cached map of a track (CACHE_DIR/maps/<track>.json: d, x, y in metres) -> (d, x, y) arrays or None."""
    try:
        with open(os.path.join(CACHE_DIR, "maps", f"{track}.json".replace(" ", "_")), encoding="utf-8") as f:
            m = json.load(f)
        d, x, y = (np.asarray(m[k], float) for k in ("d", "x", "y"))
        if len(d) < 10 or not _map_ok(x, y, float(m.get("len") or d[-1])):
            return None
        o = np.argsort(d)
        return d[o], x[o], y[o]
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------- corner names
LANDMARKS_FILE = r"C:\Program Files (x86)\Britton IT Ltd\CrewChiefV4\trackLandmarksData.json"
_LM_CACHE = None


def track_landmarks(track_name, path=None):
    """Named corners for this track from CrewChief's map: [{name, key, start, end}] in metres."""
    global _LM_CACHE
    if _LM_CACHE is None:
        _LM_CACHE = {}
        for p in [path, LANDMARKS_FILE, os.path.join(os.path.dirname(__file__), "trackLandmarksData.json")]:
            if p and os.path.exists(p):
                try:
                    dd = json.load(open(p, encoding="utf-8-sig"))
                    for t in dd.get("trackLandmarksData", []):
                        if t.get("irTrackName"):
                            _LM_CACHE[t["irTrackName"].lower()] = t.get("trackLandmarks", [])
                    break
                except Exception:
                    pass
    lms = _LM_CACHE.get((track_name or "").lower().replace("_", " "), [])
    out = []
    for lm in lms:
        names = lm.get("landmarkNames", [])
        named = [n for n in names if not re.match(r"(?i)^turn_?\d+", n)]
        num = next((re.match(r"(?i)^turn_?(\d+)", n).group(1) for n in names if re.match(r"(?i)^turn_?\d+", n)), None)
        if named:
            nm = named[0].replace("_", " ").strip().title()
            nm = re.sub(r"(\D)(\d+)$", r"\1 \2", nm)
            nm = {"Radillion": "Raidillon", "Lesmos 1": "Lesmo 1", "Lesmos 2": "Lesmo 2", "Mulsanne": "Mulsanne Corner"}.get(nm, nm).replace("Nascar", "NASCAR")
        elif num:
            nm = f"Turn {int(num)}"
        else:
            continue
        out.append({"name": nm, "key": re.sub(r"[^a-z0-9]+", "_", nm.lower()).strip("_"),
                    "start": float(lm["distanceRoundLapStart"]), "end": float(lm["distanceRoundLapEnd"])})
    out.sort(key=lambda c: c["start"])
    return out


# ---------------------------------------------------------------- comparing laps
def delta(trA, trB):
    """Time difference A - B along distance (positive = A slower)."""
    n = min(len(trA["d"]), len(trB["d"]))
    return trA["d"][:n], trA["t"][:n] - trB["t"][:n]


def corner_metrics(tr, c0, c1):
    d = tr["d"]
    i0 = int(np.searchsorted(d, max(0, c0 - 250)))
    i1 = int(np.searchsorted(d, min(d[-1], c1 + 150)))
    a0, a1 = int(np.searchsorted(d, c0 - 60)), int(np.searchsorted(d, c1 + 60))
    if a1 <= a0 + 2 or i1 <= i0 + 5:
        return None
    v, thr, brk, st = tr["kmh"], tr["Throttle"], tr["Brake"], tr["SteeringWheelAngle"]
    apex = a0 + int(np.argmin(v[a0:a1]))
    m = {"apex_d": float(d[apex]), "min_kmh": float(v[apex]), "gear_apex": int(round(tr["Gear"][apex]))}
    # braking point = first real brake press after the last full-throttle moment on the approach
    j0 = int(np.searchsorted(d, max(0, c0 - 350)))
    ft = np.flatnonzero(thr[j0:apex] > 0.9)
    start = j0 + (int(ft[-1]) + 1 if len(ft) else 0)
    hard = np.flatnonzero(brk[start:apex + 1] > 0.15)
    b0 = start + int(hard[0]) if len(hard) else None
    if b0 is not None:
        m.update(brake_d=float(d[b0]), entry_kmh=float(v[b0]), peak_brake=float(brk[b0:apex + 1].max() * 100))
        rel = np.flatnonzero(brk[b0:apex + 1] > 0.05)
        m["brake_release_d"] = float(d[b0 + int(rel[-1])]) if len(rel) else float(d[b0])
        if "BrakeABSactive" in tr:
            m["abs_pct"] = float((tr["BrakeABSactive"][b0:apex + 1] > 0.5).mean() * 100)
    else:
        m.update(brake_d=None, entry_kmh=float(v[i0]), peak_brake=0.0, brake_release_d=None)
    on = np.flatnonzero(thr[apex:i1] > 0.15)
    m["throttle_on_d"] = float(d[apex + int(on[0])]) if len(on) else None
    full = np.flatnonzero(thr[apex:i1] > 0.95)
    m["full_throttle_d"] = float(d[apex + int(full[0])]) if len(full) else None
    rel_d = m.get("brake_release_d") or m["apex_d"]
    if m["throttle_on_d"]:
        seg = slice(int(np.searchsorted(d, rel_d)), int(np.searchsorted(d, m["throttle_on_d"])))
        m["coast_m"] = float(((thr[seg] < 0.1) & (brk[seg] < 0.05)).sum() * (d[1] - d[0]))
    else:
        m["coast_m"] = 0.0
    sd = np.diff(st[a0:a1])
    sd = sd[np.abs(sd) > 0.002]
    m["steer_reversals"] = int((np.diff(np.sign(sd)) != 0).sum()) if len(sd) > 2 else 0
    ex = min(len(d) - 1, int(np.searchsorted(d, c1 + 120)))
    m["exit_kmh"] = float(v[ex])
    m["time"] = float(tr["t"][i1] - tr["t"][i0])
    m["span"] = (float(d[i0]), float(d[i1]))
    if "TireLF_RumblePitch" in tr:
        rum = sum((tr[k][a0:a1] > 0).astype(int) for k in ("TireLF_RumblePitch", "TireRF_RumblePitch", "TireLR_RumblePitch", "TireRR_RumblePitch"))
        m["kerb_m"] = float((rum > 0).sum() * (d[1] - d[0]))
    return m
