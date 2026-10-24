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
    with open(path, "rb") as f:
        head = f.read(144)
        ver, status, tick_rate, si_update, si_len, si_off, num_vars, vh_off, num_buf, buf_len = struct.unpack_from("<10i", head, 0)
        buf_off = struct.unpack_from("<i", head, 48 + 4)[0]   # varBuf[0].bufOffset
        f.seek(112)
        disk = f.read(32)
        rec_count = struct.unpack_from("<i", disk, 28)[0]
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


def list_sessions(folder=TELEMETRY_DIR):
    out = []
    for p in glob.glob(os.path.join(folder, "*.ibt")):
        st = os.stat(p)
        if st.st_size < 1_500_000:   # too short to hold a lap
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


class Session:
    def __init__(self, path, landmarks=None):
        self.path = path
        self.id = _sid(path)
        data, si, self.tick = read_ibt(path)
        self.d = data
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
            complete = (pct[: self.tick].min() < 0.03 and pct[-self.tick:].max() > 0.97 and on_track.all()
                        and covered > 0.95 * self.track_len)
            # lap time: iRacing posts it in LapLastLapTime shortly after the line
            t = None
            if b < n:
                post = d["LapLastLapTime"][b: min(n, b + self.tick * 3)]
                post = post[post > 0]
                if len(post):
                    t = float(post[-1])
            if t is None or abs(t - (d["SessionTime"][b - 1] - d["SessionTime"][a])) > 2.5:
                t = float(d["SessionTime"][b - 1] - d["SessionTime"][a])
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
        dist = d["LapDist"][a:b].copy()
        # keep it monotonic (LapDist can wobble at the line)
        dist = np.maximum.accumulate(np.clip(dist, 0, None))
        keep = np.concatenate([[True], np.diff(dist) > 1e-4])
        dist = dist[keep]
        grid = np.arange(0, min(self.track_len, dist[-1]), step)
        tr = {"d": grid}
        t = d["SessionTime"][a:b][keep]
        tr["t"] = np.interp(grid, dist, t - t[0])
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
        n = n or (self.best and self.best["n"])
        tr = self.trace(n)
        lat, lon = tr["Lat"], tr["Lon"]
        lat0, lon0 = lat.mean(), lon.mean()
        R = 6371000.0
        x = (lon - lon0) * math.cos(math.radians(lat0)) * math.pi / 180 * R
        y = (lat - lat0) * math.pi / 180 * R
        idx = np.linspace(0, len(x) - 1, points).astype(int)
        return {"x": x[idx].round(1).tolist(), "y": y[idx].round(1).tolist(), "d": tr["d"][idx].round(1).tolist()}

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
            nm = {"Radillion": "Raidillon", "Lesmos 1": "Lesmo 1", "Lesmos 2": "Lesmo 2"}.get(nm, nm).replace("Nascar", "NASCAR")
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
