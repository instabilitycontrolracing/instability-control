"""Incident forensics (2026-10-27): every spin, crash, contact and off in a session, and WHY it happened.

Reads iRacing's .ibt telemetry (or the engineer's own .renpz recordings) and, for each event, rebuilds the
~5 seconds before it and compares them with what the driver normally does at that same spot on his clean laps:
speed, braking point, peak brake and release, gear, steering, throttle and how fast it went in, wheel spin and
lock-ups, kerbs, track wetness, tyre age, traction control, and how close the cars ahead and behind were.
Fixed rules then name the root cause, explain it in plain English and give a fix and a drill. A setup change is
only suggested when the same kind of mistake repeats (rulebook: technique before setup, 3+ times).

Nothing is invented: every sentence is built from a measured number, and when the evidence is thin the cause
is "not sure" with the numbers that were seen.

    python -m engineer.forensics <file.ibt> [more.ibt ...] [--landmarks trackLandmarksData.json] [--md out.md]

What the telemetry file can't tell us (said so in the text when it matters): which car touched you (the .ibt
has no per-car positions, only the distance to the next car ahead and behind on track), cars side by side,
damage levels, and live tyre temperatures (iRacing only updates them in the pits).
"""
import json, math, os, re, sys, time
import numpy as np

from .telemetry import Session, CHANNELS, CACHE_DIR, track_landmarks

VERSION = 3

EXTRA = ["Yaw", "LFspeed", "RFspeed", "LRspeed", "RRspeed", "PlayerTrackSurfaceMaterial", "CarDistAhead", "CarDistBehind",
         "Precipitation", "PlayerCarClassPosition", "PlayerCarPosition", "PlayerTireCompound", "LapCompleted", "SessionState",
         "PlayerCarTowTime", "LapBestLapTime", "WeatherDeclaredWet", "LRtempCM", "RRtempCM", "LFtempCM", "RFtempCM", "ThrottleRaw"]
FX_CHANNELS = list(dict.fromkeys(CHANNELS + EXTRA))

WETNESS = {0: "unknown", 1: "dry", 2: "mostly dry", 3: "very lightly wet", 4: "lightly wet", 5: "moderately wet",
           6: "very wet", 7: "extremely wet"}
# iRacing's surface materials (irsdk_TrkSurf)
KERB = set(range(11, 15))
GRASS = {15, 16, 17, 18, 26, 27}
DIRT = {19, 20, 21, 22, 7, 8}
SAND = {23}
GRAVEL = {24, 25}

SPIN_DEG = 45.0          # body slip angle: past this the car is pointing well away from where it's going = a spin
MOMENT_DEG = 15.0        # a big slide you caught
ONSET_DEG = 3.0
IMPACT_G = 4.0           # horizontal g no tyre can make: something was hit
IMPACT_JERK = 180.0      # g per second, sample to sample
NEAR_CAR_M = 10.0


def _f(x, n=0):
    return f"{x:.{n}f}"


def surface_kind(m):
    m = int(m)
    if m in GRAVEL:
        return "gravel"
    if m in SAND:
        return "sand"
    if m in GRASS:
        return "grass"
    if m in DIRT:
        return "dirt"
    if m in KERB:
        return "kerb"
    return "track"


def fmt_lap(t):
    return f"{int(t // 60)}:{t % 60:06.3f}" if t and t > 0 else "-"


# ======================================================================================== one recording
class Run:
    """One .ibt prepared for forensics: the Session (laps, corners) plus derived per-sample signals."""

    def __init__(self, path, landmarks=None):
        self.path = path
        self.s = s = Session(path, landmarks=landmarks, channels=FX_CHANNELS)
        d, self.tick = s.d, s.tick
        n = len(d["SessionTime"])
        self.n = n
        g = lambda k, dv=0.0: d[k] if k in d else np.full(n, dv)
        self.t = d["SessionTime"]
        self.v = d["Speed"]
        self.kmh = self.v * 3.6
        vx, vy = g("VelocityX"), g("VelocityY")
        self.has_slip = "VelocityX" in d and "VelocityY" in d
        self.beta = np.degrees(np.arctan2(vy, np.abs(vx) + 0.01)) if self.has_slip else np.zeros(n)
        self.beta[self.v < 5] = 0.0
        self.yr = np.degrees(g("YawRate"))
        self.steer = np.degrees(g("SteeringWheelAngle"))
        # the driver's own pedal (ThrottleRaw): the car's Throttle channel also carries the downshift blips
        self.thr, self.brk = (d["ThrottleRaw"] if "ThrottleRaw" in d else g("Throttle")), g("Brake")
        self.gear = g("Gear").astype(int)
        self.lat, self.lon = g("LatAccel") / 9.81, g("LongAccel") / 9.81
        self.vert = g("VertAccel", 9.81) / 9.81
        ok_gps = "Lat" in d and "Lon" in d and np.abs(d["Lat"]).max() > 0.01
        self.glat, self.glon = (d["Lat"], d["Lon"]) if ok_gps else (None, None)          # GPS, for the line on the map
        self.dist = g("LapDist")
        self.lapn = g("Lap").astype(int)
        self.surf = g("PlayerTrackSurface", 3).astype(int)
        self.mat = g("PlayerTrackSurfaceMaterial", 1).astype(int)
        self.inc = g("PlayerCarMyIncidentCount").astype(int)
        self.pit = g("OnPitRoad", 0).astype(bool)
        self.wet = g("TrackWetness", 0).astype(int)
        self.rain = g("Precipitation", 0.0)
        self.tyre = g("PlayerTireCompound", -1).astype(int)
        self.ahead, self.behind = g("CarDistAhead", 9999.0), g("CarDistBehind", 9999.0)
        self.has_gaps = "CarDistAhead" in d
        self.cpos = g("PlayerCarClassPosition", 0).astype(int)
        self.state = g("SessionState", 4).astype(int)
        self.tc1, self.tc2 = g("dcTractionControl", np.nan), g("dcTractionControl2", np.nan)
        self.bias = g("dcBrakeBias", np.nan)
        self.wheels = {w: d[w + "speed"] for w in ("LF", "RF", "LR", "RR") if w + "speed" in d}
        rum = [d[k] for k in ("TireLF_RumblePitch", "TireRF_RumblePitch", "TireLR_RumblePitch", "TireRR_RumblePitch") if k in d]
        self.rumble = (np.sum([np.asarray(r) > 0 for r in rum], axis=0) > 0) if rum else np.zeros(n, bool)
        self.kerb = self.rumble | np.isin(self.mat, list(KERB))
        a = np.hypot(self.lat, self.lon)
        self.acc = a
        self.jerk = np.concatenate([[0.0], np.abs(np.diff(a)) * self.tick])
        self.L = s.track_len or float(np.nanmax(self.dist) or 1)
        info = s.info or {}
        wk = info.get("WeekendInfo", {}) or {}
        self.weekend = wk
        self.sessions = {int(x.get("SessionNum", -1)): str(x.get("SessionType") or "") for x in (info.get("SessionInfo", {}) or {}).get("Sessions", []) or []}
        sn = d.get("SessionNum")
        sni = sn.astype(np.int64) if sn is not None and len(sn) else None
        self.sess_num = int(np.bincount(sni - sni.min()).argmax() + sni.min()) if sni is not None else 0
        self.sess_type = self.sessions.get(self.sess_num, "")
        self.date = _date_of(path, wk)
        self._lap_index()
        self._damage = self._find_damage()

    # ---------------------------------------------------------------- laps
    def _lap_index(self):
        d = self.s.d
        llt = d.get("LapLastLapTime")
        self.laps = []
        for L in self.s.laps:
            a, b = L["a"], L["b"]
            posted = None
            if llt is not None and b < self.n:
                post = llt[b: min(self.n, b + self.tick * 4)]
                prev = llt[max(0, b - 2)]
                ch = post[(post != prev)]
                if len(ch) and ch[-1] > 0:
                    posted = float(ch[-1])
            pit = bool(self.pit[a:b].any())
            wet = int(np.median(self.wet[a:b])) if b > a else 0
            tyre = int(np.median(self.tyre[a:b])) if b > a else -1
            self.laps.append(dict(L, posted=posted, pit=pit, wet=wet, tyre=tyre,
                                  cond="wet" if (wet >= 3 or tyre == 1) else "dry"))
        # stint lap = laps since the session start or the last pit exit
        stint = 0
        for L in self.laps:
            stint += 1
            L["stint_lap"] = stint
            if L["pit"]:
                stint = 0
        self.lap_by_n = {L["n"]: L for L in self.laps}

    def lap_at(self, i):
        for L in self.laps:
            if L["a"] <= i < L["b"]:
                return L
        return None

    def clean_laps(self):
        """Laps that are a fair picture of normal driving: whole, no pit, no off, no incident, not the start lap."""
        out = []
        for L in self.laps:
            if not L["complete"] or L["pit"] or L["off"] or L["incidents"]:
                continue
            if L["n"] <= 1 and "race" in self.sess_type.lower():
                continue                                    # race start lap: rolling start + pack
            out.append(L)
        if out:
            med = float(np.median([L["time"] for L in out]))
            out = [L for L in out if L["time"] < med * 1.04]   # drop slow laps (traffic, caution, saving)
        return out

    # ---------------------------------------------------------------- per-lap traces on distance
    def light_trace(self, a, b, step=1.0):
        """Driver inputs between samples a..b, resampled on a 1 m distance grid."""
        if b - a < 5:                                       # #392: an incident right at the start of a lap (empty span)
            return None
        dist = np.maximum.accumulate(np.clip(self.dist[a:b].astype(np.float64), 0, None))
        keep = np.concatenate([[True], np.diff(dist) > 1e-4])
        dd = dist[keep]
        if len(dd) < 5:
            return None
        grid = np.arange(math.floor(dd[0]), dd[-1], step)
        tr = {"d": grid}
        idx = np.arange(a, b)[keep]
        for k, arr in (("t", self.t), ("kmh", self.kmh), ("Throttle", self.thr), ("Brake", self.brk), ("steer", self.steer),
                       ("Gear", self.gear), ("lat", self.lat), ("gLat", self.glat), ("gLon", self.glon)):
            if arr is not None:
                tr[k] = np.interp(grid, dd, arr[idx].astype(np.float64))
        tr["SteeringWheelAngle"] = np.radians(tr["steer"])
        return tr

    # ---------------------------------------------------------------- damage
    def _find_damage(self):
        """A wheel that stops turning properly while the car rolls (bent or broken suspension) -> [(i, wheel)]."""
        out = []
        ok = (self.v > 20) & ~self.pit & (self.brk < 0.05)
        need = int(self.tick * 3)
        for w, ws in self.wheels.items():
            bad = ok & (ws < self.v * 0.7)
            if bad.sum() < need:
                continue
            # first time it stays bad for 3 s of running
            idx = np.flatnonzero(bad)
            starts = np.concatenate([[0], np.flatnonzero(np.diff(idx) > self.tick * 0.5) + 1])
            for si, s0 in enumerate(starts):
                e0 = starts[si + 1] if si + 1 < len(starts) else len(idx)
                if e0 - s0 >= need:
                    out.append((int(idx[s0]), w))
                    break
        out.sort()
        return out

    def damaged_before(self, i):
        return [w for j, w in self._damage if j < i]


def _date_of(path, wk):
    m = re.search(r"(\d{4}-\d\d-\d\d) (\d\d)-(\d\d)-(\d\d)", os.path.basename(path))
    if m:
        return f"{m.group(1)} {m.group(2)}:{m.group(3)}"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))


# ======================================================================================== baseline (what you normally do)
class Baseline:
    """Median of the driver's clean laps (same car + track + conditions) on a 1 m grid, plus each lap kept for
    braking-point comparisons."""

    def __init__(self, laps, L):
        self.laps = laps                                   # list of light traces
        self.n = len(laps)
        self.L = L
        if not laps:
            self.med = None
            return
        n = int(min(len(tr["d"]) for tr in laps))
        self.med = {"d": laps[0]["d"][:n]}
        for k in ("t", "kmh", "Throttle", "Brake", "steer", "Gear", "lat", "gLat", "gLon"):
            if not all(k in tr for tr in laps):
                continue
            M = np.vstack([tr[k][:n] for tr in laps])
            if k == "t":
                M = M - M[:, :1]
            self.med[k] = np.median(M, axis=0)
        self.med["SteeringWheelAngle"] = np.radians(self.med["steer"])

    def at(self, k, d):
        if self.med is None:
            return None
        i = int(np.clip(np.searchsorted(self.med["d"], d), 0, len(self.med["d"]) - 1))
        return float(self.med[k][i])

    def approach(self, d_on):
        """Median of each clean lap's approach to this spot (brake point etc.)."""
        rows = [approach_metrics(tr, d_on, full=True) for tr in self.laps]
        rows = [r for r in rows if r]
        if not rows:
            return None
        out = {}
        for k in rows[0]:
            xs = [r[k] for r in rows if r.get(k) is not None]
            out[k] = float(np.median(xs)) if xs else None
            if k in ("brake_d",) and xs:
                out["brake_d_spread"] = float(np.percentile(xs, 90) - np.percentile(xs, 10))
        out["n"] = len(rows)
        return out


def approach_metrics(tr, d_on, full=False, ref_brake=None):
    """The braking zone and inputs leading to distance d_on. tr = light trace; for the incident lap it ends at
    the onset (full=False), for clean laps it runs past it (full=True). ref_brake = the usual brake point: the
    zone that starts closest to it is the one compared (so a light dab earlier doesn't count as 'the' brake point)."""
    d = tr["d"]
    if len(d) < 10 or d[0] > d_on - 30:
        return None
    i_on = int(np.clip(np.searchsorted(d, d_on), 0, len(d) - 1))
    i0 = int(np.searchsorted(d, d_on - 600))
    brk, thr, v = tr["Brake"], tr["Throttle"], tr["kmh"]
    out = {"v_on": float(v[i_on]), "thr_on": float(thr[i_on]), "brk_on": float(brk[i_on]), "steer_on": float(tr["steer"][i_on]),
           "gear_on": int(round(tr["Gear"][i_on]))}
    zone = brk[i0:i_on + 1] > 0.15
    starts = [i0 + int(x) for x in np.flatnonzero(np.diff(np.concatenate([[0], zone.astype(int)])) == 1)]
    b0 = None
    if starts:
        if ref_brake is None:
            b0 = starts[-1]
        else:
            k = min(starts, key=lambda j: abs(d[j] - ref_brake))
            b0 = k if abs(d[k] - ref_brake) <= 120 else None
    if b0 is not None:
        out["brake_d"] = float(d[b0])
        out["v_brake"] = float(v[b0])
        end = len(d) if full else i_on + 1
        seg = brk[b0:end]
        out["peak_brake"] = float(seg.max() * 100) if len(seg) else None
        rel = np.flatnonzero(seg < 0.05)
        out["release_d"] = float(d[b0 + int(rel[0])]) if len(rel) else None      # None: still braking at the onset
        st = np.abs(tr["steer"][b0:min(len(d), i_on + 120)])
        if len(st) > 3 and st.max() > 8:
            ti = np.flatnonzero(st > 0.3 * st.max())
            out["turnin_d"] = float(d[b0 + int(ti[0])]) if len(ti) else None
        out["v_min"] = float(v[b0:i_on + 1].min())
    else:
        out.update(brake_d=None, v_brake=None, peak_brake=None, release_d=None, turnin_d=None, v_min=float(v[i0:i_on + 1].min()))
    return out


def _pool_key(run):
    return (run.s.car_path, run.s.track_name)


class Pool:
    """All recordings of the same car + track given to the analysis; baselines per condition (dry / wet)."""

    def __init__(self, runs):
        self.runs = runs
        self._base = {}

    def baseline(self, run, cond):
        key = (_pool_key(run), cond, id(run))
        if key in self._base:
            return self._base[key]
        own = [(run, L) for L in run.clean_laps() if L["cond"] == cond]
        other = [(r, L) for r in self.runs if r is not run and _pool_key(r) == _pool_key(run)
                 for L in r.clean_laps() if L["cond"] == cond]
        laps = own + other
        src = "this session" if own and not other else ("this session and your other sessions" if own else "your other sessions")
        if not laps:            # nothing in these conditions: use whatever clean laps exist, and say so
            laps = [(run, L) for L in run.clean_laps()] + [(r, L) for r in self.runs if r is not run and _pool_key(r) == _pool_key(run) for L in r.clean_laps()]
            src = "clean laps in other conditions (rough comparison)"
        traces = []
        for r, L in laps[:40]:
            tr = r.light_trace(L["a"], L["b"])
            if tr is not None and len(tr["d"]) > 0.9 * run.L:
                traces.append(tr)
        b = Baseline(traces, run.L)
        b.src = src
        b.cond = cond
        self._base[key] = b
        return b


# ======================================================================================== detection
def _segments(mask, gap):
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    br = np.flatnonzero(np.diff(idx) > gap)
    starts = np.concatenate([[idx[0]], idx[br + 1]])
    ends = np.concatenate([idx[br], [idx[-1]]])
    return list(zip(starts.tolist(), ends.tolist()))


def detect(run):
    """Raw detections -> list of components {type, i0, i1, ...} in time order."""
    R, tk = run, run.tick
    live = (R.v > 5) & ~R.pit & (R.surf >= 0)
    comps = []
    # slides and spins
    if R.has_slip:
        big = live & (np.abs(R.beta) > 8) & (R.v > 8)
        for a, b in _segments(big, int(tk * 0.5)):
            seg = np.abs(R.beta[a:b + 1])
            k = a + int(np.argmax(seg))
            peak = float(R.beta[k])
            if abs(peak) < MOMENT_DEG:
                continue
            o = k
            lo = max(0, k - int(tk * 4))
            while o > lo and abs(R.beta[o]) > ONSET_DEG:
                o -= 1
            comps.append({"type": "spin" if abs(peak) >= SPIN_DEG else "moment", "i0": int(o), "i1": int(b), "ipk": int(k),
                          "peak": round(peak, 1)})
    # offs (all four wheels off the track surface)
    off = live & (R.surf == 0)
    for a, b in _segments(off, int(tk * 1.0)):
        if b - a < tk * 0.15:
            continue
        mats = [surface_kind(m) for m in R.mat[a:b + 1]]
        mats = [m for m in mats if m not in ("track", "kerb")] or ["grass"]
        comps.append({"type": "off", "i0": int(a), "i1": int(b), "ipk": int(a), "surface": max(set(mats), key=mats.count),
                      "dur": round((b - a) / tk, 1)})
    # impacts
    hit = live & ((R.acc > IMPACT_G) | (R.jerk > IMPACT_JERK))
    for a, b in _segments(hit, int(tk * 0.6)):
        k = a + int(np.argmax(R.acc[a:b + 1]))
        comps.append({"type": "impact", "i0": int(a), "i1": int(b), "ipk": int(k), "g": round(float(R.acc[a:b + 1].max()), 1),
                      "jerk": round(float(R.jerk[a:b + 1].max())), "dv": round(float(R.kmh[max(0, a - 3)] - R.kmh[min(R.n - 1, b + int(tk * 0.3))]))})
    # incident points
    inc = np.diff(R.inc)
    for i in np.flatnonzero(inc > 0):
        comps.append({"type": "points", "i0": int(i + 1), "i1": int(i + 1), "ipk": int(i + 1), "pts": int(inc[i])})
    comps.sort(key=lambda c: c["i0"])
    return comps


def episodes_of(run, comps):
    """Group components that belong to one moment (a spin that ends in the gravel and the wall = one episode)."""
    eps = []
    for c in comps:
        if c["type"] == "points":
            # iRacing posts the points a moment after the event: attach to an episode up to 8 s earlier
            cand = [e for e in eps if run.t[c["i0"]] - run.t[e["i1"]] <= 8 and run.t[c["i0"]] >= run.t[e["i0"]] - 1]
            if cand:
                cand[-1]["pts"] += c["pts"]; cand[-1]["pts_list"].append(c["pts"]); continue
            eps.append({"i0": c["i0"], "i1": c["i1"], "comps": [], "pts": c["pts"], "pts_list": [c["pts"]]})
            continue
        if eps and run.t[c["i0"]] - run.t[eps[-1]["i1"]] <= 4.0:
            e = eps[-1]
            e["comps"].append(c); e["i1"] = max(e["i1"], c["i1"])
            if not [x for x in e["comps"] if x is not c] and e["pts"]:      # points-only episode gets its cause
                e["i0"] = min(e["i0"], c["i0"])
            continue
        eps.append({"i0": c["i0"], "i1": c["i1"], "comps": [c], "pts": 0, "pts_list": []})
    # a lone "moment" without points or an off is a save: keep it (it tells a story) but mark it minor
    return eps


# ======================================================================================== the story before each event
def _first(comps, kind):
    return next((c for c in comps if c["type"] == kind), None)


def corner_name(run, d):
    """Name of the corner at distance d, or 'after X' / 'approaching Y' between corners."""
    cs = run.s.find_corners() or []
    for c in cs:
        if c["start"] - 20 <= d <= c["end"] + 20:
            return c["name"]
    prev = [c for c in cs if c["end"] < d]
    nxt = [c for c in cs if c["start"] > d]
    if prev and d - prev[-1]["end"] < 350:
        return f"the exit of {prev[-1]['name']}"
    if nxt and nxt[0]["start"] - d < 350:
        return f"the approach to {nxt[0]['name']}"
    if prev:
        return f"after {prev[-1]['name']}"
    return f"{d:.0f} m into the lap"


def corner_key(run, d):
    cs = run.s.find_corners() or []
    for c in cs:
        if c["start"] - 20 <= d <= c["end"] + 20:
            return c["name"]
    prev = [c for c in cs if c["end"] < d]
    nxt = [c for c in cs if c["start"] > d]
    if prev and d - prev[-1]["end"] < 350:
        return prev[-1]["name"]
    if nxt and nxt[0]["start"] - d < 350:
        return nxt[0]["name"]
    return prev[-1]["name"] if prev else "Start/finish"


def context(run, pool, ep):
    """Everything around the start of the episode: what the driver did, the car, the track, the traffic, and how
    that compares with his clean laps at the same spot."""
    R, tk = run, run.tick
    comps = ep["comps"]
    first = comps[0] if comps else None
    if first is None:
        i_on = ep["i0"]
    elif first["type"] == "impact":
        i_on = first["ipk"]
    else:
        i_on = first["i0"]
    if 4 in ep["pts_list"] and not _first(comps, "impact"):
        # heavy contact without a hard hit: find the sideways shove (sudden change of lateral g) before the points
        pi = ep["i0"] if first is None else min(ep["i0"], i_on)
        a0 = max(2, pi - int(tk * 3))
        win = np.abs(R.lat[a0:pi + 1] - R.lat[a0 - 2:pi - 1]) if pi > a0 + 3 else np.zeros(0)
        if len(win) and win.max() > 0.8:
            i_on = a0 + int(np.argmax(win))
            ep["touch"] = True
    # an off right after a slide starts at the slide
    lap = R.lap_at(i_on) or (R.laps[-1] if R.laps else None)
    d_on = float(R.dist[i_on])
    if lap and d_on < 30 and R.t[i_on] - R.t[lap["a"]] > 20:      # LapDist resets a moment before the lap counter
        d_on = float(R.L)
    c = {"i_on": int(i_on), "t_on": float(R.t[i_on]), "d_on": d_on, "lap": lap["n"] if lap else int(R.lapn[i_on]),
         "stint_lap": lap["stint_lap"] if lap else None, "corner": corner_name(R, d_on), "corner_key": corner_key(R, d_on),
         "v": float(R.kmh[i_on]), "thr": float(R.thr[i_on]), "brk": float(R.brk[i_on]), "steer": float(R.steer[i_on]),
         "gear": int(R.gear[i_on]), "lat": float(R.lat[i_on]), "beta": float(R.beta[i_on]), "yr": float(R.yr[i_on])}
    # pedals and steering in the 1.2 s before
    p0 = max(0, i_on - int(tk * 1.2))
    c["thr_max_before"] = float(R.thr[p0:i_on + 1].max())
    c["thr_min_before"] = float(R.thr[p0:i_on + 1].min())
    c["thr_rise"] = float(R.thr[i_on] - R.thr[p0:i_on + 1].min())
    dthr = np.diff(R.thr[p0:i_on + 1]) * tk
    c["thr_rate"] = float(dthr.max()) if len(dthr) else 0.0                       # throttle opening speed, per second
    c["thr_drop"] = float(R.thr[p0:i_on + 1].max() - R.thr[i_on])
    c["brk_max_before"] = float(R.brk[p0:i_on + 1].max())
    c["steer_max_before"] = float(np.abs(R.steer[p0:i_on + 1]).max())
    c["lat_max_before"] = float(np.abs(R.lat[p0:i_on + 1]).max())
    q1 = min(R.n - 1, i_on + int(tk * 0.6))
    gs = R.gear[p0:q1 + 1]
    downs = [p0 + 1 + int(x) for x in np.flatnonzero(np.diff(gs) < 0) if gs[x + 1] > 0]
    c["downshift"] = None
    if downs:
        before = [j for j in downs if j <= i_on]
        j = before[-1] if before else downs[0]
        # the gearbox goes through neutral (0) between gears on this car: find the gear before the change
        prev_g = next((int(g) for g in R.gear[max(0, j - int(tk * 0.6)):j][::-1] if g > R.gear[j]), int(R.gear[j]) + 1)
        c["downshift"] = {"to": int(R.gear[j]), "from": prev_g, "dt": round(float(R.t[i_on] - R.t[j]), 2), "after": j > i_on,
                          "lat": round(float(abs(R.lat[j])), 2), "steer": round(float(abs(R.steer[j]))), "kmh": round(float(R.kmh[j]))}
    # kerb in the 1 s before
    k0, k1 = max(0, i_on - int(tk * 1.0)), min(R.n - 1, i_on + int(tk * 0.8))
    kerb_idx = np.flatnonzero(R.kerb[k0:k1 + 1])
    c["kerb"] = None
    if len(kerb_idx):
        j = k0 + int(kerb_idx[0])
        vz = float(np.abs(R.vert[k0:k1 + 1] - 1.0).max())
        c["kerb"] = {"dt": round(float(R.t[i_on] - R.t[j]), 2), "jolt": round(vz, 2), "after": j > i_on}
    # wheels: spin and lock-ups just before
    if R.wheels:
        rr = [R.wheels[w] for w in ("LR", "RR") if w in R.wheels]
        sl = slice(max(0, i_on - int(tk * 0.8)), i_on + 1)
        vg = np.maximum(R.v[sl], 1)
        if rr:
            slip = (np.mean([x[sl] for x in rr], axis=0) / vg - 1) * 100
            c["rear_slip"] = float(slip.max())
            c["rear_slip_normal"] = _normal_slip(R, c["gear"])
        lock = {}
        for w in ("LF", "RF", "LR", "RR"):
            if w in R.wheels and w not in R.damaged_before(i_on):
                r_ = R.wheels[w][sl] / vg
                lock[w] = float(r_.min())
        c["lock"] = {w: round(x, 2) for w, x in lock.items() if x < 0.75}
    # car and track
    c["wet"] = int(R.wet[i_on]); c["wet_txt"] = WETNESS.get(int(R.wet[i_on]), "?")
    c["rain"] = float(R.rain[i_on])
    c["tyre"] = int(R.tyre[i_on])
    c["tc1"] = None if np.isnan(R.tc1[i_on]) else float(R.tc1[i_on])
    c["tc2"] = None if np.isnan(R.tc2[i_on]) else float(R.tc2[i_on])
    run_mask = (R.v > 20) & ~R.pit
    if run_mask.any() and c["tc1"] is not None:
        vals, cnt = np.unique(R.tc1[run_mask], return_counts=True)
        c["tc1_usual"] = float(vals[np.argmax(cnt)])
        c["tc1_later"] = float(R.tc1[min(R.n - 1, i_on + 1):][run_mask[min(R.n - 1, i_on + 1):]].max()) if run_mask[i_on + 1:].any() else None
    c["damage"] = R.damaged_before(i_on)
    c["damage_new"] = [w for j, w in R._damage if i_on <= j <= ep["i1"] + int(tk * 15)]
    # steering while off (a straight line through a chicane shows here)
    off_c = _first(comps, "off")
    c["steer_off"] = float(np.median(np.abs(R.steer[off_c["i0"]:off_c["i0"] + int(tk)]))) if off_c else None
    # traffic
    if R.has_gaps:
        g0 = max(0, i_on - int(tk * 3))
        a_, b_ = R.ahead[g0:i_on + int(tk * 0.5)], R.behind[g0:i_on + int(tk * 0.5)]
        c["ahead"], c["behind"] = float(R.ahead[i_on]), float(R.behind[i_on])
        c["ahead_min"], c["behind_min"] = float(a_.min()), float(b_.min())
        c["ahead_3s"], c["behind_3s"] = float(R.ahead[g0]), float(R.behind[g0])
    c["race_lap1"] = bool("race" in R.sess_type.lower() and c["lap"] is not None and c["lap"] <= 1)
    # what he normally does here
    cond = lap["cond"] if lap else "dry"
    base = pool.baseline(R, cond)
    c["base_n"], c["base_src"] = base.n, getattr(base, "src", "")
    if base.n >= 2 and lap:
        tr = R.light_trace(lap["a"], i_on + 1)
        us = base.approach(d_on)
        me = approach_metrics(tr, d_on, ref_brake=(us or {}).get("brake_d")) if tr is not None else None
        c["me"], c["usual"] = me, us
        c["v_usual"] = base.at("kmh", d_on)
        c["thr_usual"] = base.at("Throttle", d_on)
        c["brk_usual"] = base.at("Brake", d_on)
        c["steer_usual"] = base.at("steer", d_on)
        c["gear_usual"] = int(round(base.at("Gear", d_on)))
        if tr is not None:
            c.update(_profile(tr, base, d_on, (us or {}).get("brake_d")))
    else:
        c["me"] = c["usual"] = None
    c["loss"] = _time_lost(R, base, lap, d_on)
    c["pos_before"], c["pos_after"] = _positions(R, i_on, ep["i1"])
    return c


def _profile(tr, base, d_on, brake_us=None):
    """How the run-up to the onset differed from the clean laps, metre by metre: from just before the usual brake
    point of this corner (or 250 m) up to the onset."""
    out = {}
    start = d_on - 250 if brake_us is None or brake_us > d_on or brake_us < d_on - 600 else brake_us - 80
    lo = max(tr["d"][0] + 1, start)
    ds = np.arange(lo, d_on + 0.5, 5.0)
    if len(ds) < 4:
        return out
    me_v = np.interp(ds, tr["d"], tr["kmh"])
    us_v = np.interp(ds, base.med["d"], base.med["kmh"])
    dv = me_v - us_v
    k = int(np.argmax(dv))
    out["dv_entry"] = round(float(dv[k]), 1)
    out["dv_entry_back"] = round(float(d_on - ds[k]))
    out["v_entry"], out["v_entry_usual"] = round(float(me_v[k])), round(float(us_v[k]))
    # where he came off full throttle, against his clean laps (median of each lap's own lift point), 400 m window
    ds = np.arange(max(tr["d"][0] + 1, d_on - 400), d_on + 0.5, 5.0)
    me_t = np.interp(ds, tr["d"], tr["Throttle"])
    full = np.flatnonzero(me_t > 0.8)
    lifts = []
    for L in base.laps:
        t_ = np.interp(ds, L["d"], L["Throttle"])
        f_ = np.flatnonzero(t_ > 0.8)
        if len(f_) and f_[-1] < len(ds) - 1:
            lifts.append(ds[f_[-1]])
    if len(full) and full[-1] < len(ds) - 1 and lifts and len(lifts) >= len(base.laps) / 2:
        out["lift_d"], out["lift_usual"] = float(ds[full[-1]]), float(np.median(lifts))
    ds = np.arange(lo, d_on + 0.5, 5.0)
    # brake pressure in the second half of the braking zone (coming off the pedal too early shows here)
    us_b = np.interp(ds, base.med["d"], base.med["Brake"])
    me_b = np.interp(ds, tr["d"], tr["Brake"])
    zone = np.flatnonzero(us_b > 0.15)
    if len(zone) >= 6:
        half = zone[len(zone) // 2:]
        out["brk_zone"], out["brk_zone_usual"] = round(float(me_b[half].mean() * 100)), round(float(us_b[half].mean() * 100))
    # gear and speed at the turn-in: where the clean laps start steering for THIS corner (the last steering rise
    # before the onset, so a kink before it doesn't count)
    st = np.abs(np.interp(ds, base.med["d"], base.med["steer"]))
    if st.max() > 10:
        pk = int(np.argmax(st))
        calm = np.flatnonzero(st[:pk + 1] < max(5.0, 0.15 * st[pk]))
        ti = int(calm[-1]) + 1 if len(calm) else 0
        ti = min(ti, len(ds) - 1)
        out["gear_turnin"] = int(round(np.interp(ds[ti], tr["d"], tr["Gear"])))
        out["gear_turnin_usual"] = int(round(np.interp(ds[ti], base.med["d"], base.med["Gear"])))
        out["v_turnin"], out["v_turnin_usual"] = round(float(me_v[ti])), round(float(us_v[ti]))
    return out


def approach_story(c):
    """Plain sentences about the run-up: lift point, brake point, brake pressure, speed at turn-in, gear.
    -> (sentences, overspeed km/h or 0)"""
    S = []
    me, us = c.get("me") or {}, c.get("usual") or {}
    if c.get("lift_d") is not None and c["lift_d"] - c["lift_usual"] >= 25:
        S.append(f"You stayed on the throttle {c['lift_d'] - c['lift_usual']:.0f} m longer than on your clean laps before lifting.")
    spread = us.get("brake_d_spread") or 0
    hard_me, hard_us = me.get("peak_brake") or 0, us.get("peak_brake") or 0
    if me.get("brake_d") is not None and us.get("brake_d") is not None and spread <= 60:
        late = me["brake_d"] - us["brake_d"]
        if hard_me >= 0.6 * hard_us:
            if late >= 8:
                S.append(f"You braked {late:.0f} m later than usual.")
            elif late <= -8:
                S.append(f"You braked {abs(late):.0f} m earlier than usual.")
        elif hard_us:
            S.append(f"You only braked lightly (peak {hard_me:.0f}% against your usual {hard_us:.0f}%).")
    if c.get("brk_zone") is not None and c["brk_zone_usual"] - c["brk_zone"] >= 12 and not any("lightly" in x for x in S):
        S.append(f"You came off the brake too early: in the second half of the braking zone you used {c['brk_zone']}% against your usual {c['brk_zone_usual']}%.")
    over = c.get("dv_entry") or 0
    if over >= 6:
        if c.get("v_turnin") is not None and c["v_turnin"] - c["v_turnin_usual"] >= 6:
            S.append(f"You arrived at the turn-in {c['v_turnin'] - c['v_turnin_usual']:.0f} km/h faster than normal ({c['v_turnin']} against {c['v_turnin_usual']} km/h).")
        else:
            S.append(f"You were {over:.0f} km/h faster than normal {c['dv_entry_back']:.0f} m before it happened ({c['v_entry']} against {c['v_entry_usual']} km/h).")
    if c.get("gear_turnin") is not None and c["gear_turnin"] > c["gear_turnin_usual"] and over >= 6:
        S.append(f"You were still in {c['gear_turnin']}{_th(c['gear_turnin'])} at the turn-in where you're normally already in {c['gear_turnin_usual']}{_th(c['gear_turnin_usual'])}.")
    return S, over if over >= 6 else 0


_SLIP = {}


def _normal_slip(R, gear):
    key = (id(R), gear)
    if key not in _SLIP:
        rr = [R.wheels[w] for w in ("LR", "RR") if w in R.wheels]
        m = (R.v > 15) & (np.abs(R.beta) < 3) & ~R.pit & (R.thr > 0.8) & (R.gear == gear)
        if rr and m.sum() > 60:
            s = (np.mean([x[m] for x in rr], axis=0) / R.v[m] - 1) * 100
            _SLIP[key] = float(np.percentile(s, 90))
        else:
            _SLIP[key] = None
    return _SLIP[key]


def _time_lost(R, base, lap, d_on):
    """Seconds lost from 150 m before to 700 m after the onset vs the clean-lap median (None if unknown)."""
    if base.n < 2 or lap is None:
        return None
    tr = R.light_trace(lap["a"], lap["b"])
    if tr is None:
        return None
    d0, d1 = d_on - 150, d_on + 700
    if d0 < tr["d"][0] + 1:
        return None
    end = min(d1, tr["d"][-1] - 1, base.med["d"][-1] - 1)
    if end <= d0 + 50:
        return None
    me = np.interp(end, tr["d"], tr["t"]) - np.interp(d0, tr["d"], tr["t"])
    us = np.interp(end, base.med["d"], base.med["t"]) - np.interp(d0, base.med["d"], base.med["t"])
    extra = 0.0
    if d1 > end + 50:                                    # ran over the line: carry on into the next lap
        nx = R.lap_by_n.get(lap["n"] + 1)
        if nx:
            tn = R.light_trace(nx["a"], nx["b"])
            if tn is not None:
                e2 = min(d1 - R.L, tn["d"][-1] - 1)
                if e2 > tn["d"][0] + 20:
                    extra = (np.interp(e2, tn["d"], tn["t"]) - np.interp(tn["d"][0], tn["d"], tn["t"])) - \
                            (np.interp(e2, base.med["d"], base.med["t"]) - np.interp(tn["d"][0], base.med["d"], base.med["t"]))
    return round(float(me - us + extra), 1)


def _positions(R, i0, i1):
    if not R.cpos.any():
        return None, None
    a = R.cpos[max(0, i0 - int(R.tick * 3))]
    b = R.cpos[min(R.n - 1, i1 + int(R.tick * 20))]
    return (int(a) or None), (int(b) or None)


# ======================================================================================== root cause
# 2026-10-28: the two drills that name corners were written at Le Mans and named Le Mans' corners at every track.
# Now the corners come from series.TRACKS[...]["drill"] (Le Mans gives exactly the old text).
DRILL_AT = {
    "contact_ahead": "Practice behind AI cars: follow one car into {brake} for 5 laps, braking 10 m before your usual marker every time, never closer than one car length.",
    "contact_side": "In practice with AI, run side by side through {side} for a few laps leaving a full car width every time.",
}


def drill_text(code, *track_names):
    t = DRILL_AT.get(code)
    if not t:
        return CAUSES[code]["drill"]
    try:
        from .series import drill_spots
        return t.format(**drill_spots(*track_names))
    except Exception:
        return CAUSES[code]["drill"]


CAUSES = {
    # ---- contact
    "contact_ahead": {"title": "Ran into the car ahead",
        "what": "When a car is close in front going into a braking zone, brake at your normal marker or a little earlier, never later, and leave a car's length: he may brake early or miss a gear.",
        "drill": "Practice behind AI cars: follow one car into the Ford Chicanes, Dunlop and Mulsanne Corner for 5 laps, braking 10 m before your usual marker every time, never closer than one car length.",
        "family": "contact", "setup": None},
    "contact_behind": {"title": "Hit from behind",
        "what": "Be predictable with a car right behind you: brake at your usual point, avoid sudden lifts on the straights and in fast corners, and hold your line into the corner.",
        "drill": "On lap 1 and when a car is within 10 m behind, brake at the same marker as your clean laps. Look in the mirror before the braking zone so you know he's there.",
        "family": "contact", "setup": None},
    "contact_side": {"title": "Contact with a car next to you",
        "what": "Leave a car's width when someone is alongside, and use the spotter call: 'car left/right' means no squeezing until 'clear'.",
        "drill": "In practice with AI, run side by side through Dunlop and the Esses for a few laps leaving a full car width every time.",
        "family": "contact", "setup": None},
    # ---- spins and slides
    "power_oversteer": {"title": "Too much throttle with the wheel still turned",
        "what": "Unwind the steering first, then squeeze the throttle in. In 1st and 2nd gear the hybrid has huge torque: open the throttle in about one second, not in a stab.",
        "drill": "10 laps of practice: on every slow-corner exit count 'one-and' from 20% throttle to full, only going past half throttle once the steering is coming back to straight.",
        "family": "exit_os", "setup": "exit_os"},
    "lift_off": {"title": "Lift-off oversteer",
        "what": "A big lift in a fast corner throws the weight forward and the rear goes light. Either stay committed, or lift a little and early, before you turn in, never mid-corner.",
        "drill": "Practice the corner flat or with one small, early lift at the same marker for 5 laps; no lifts once the car is loaded up in the corner.",
        "family": "entry_os", "setup": "entry_os"},
    "downshift_turning": {"title": "Downshift while turning",
        "what": "Do your downshifts in a straight line while braking. A downshift while the car is already turning adds engine braking to the rear wheels and the rear lets go.",
        "drill": "Practice: finish all downshifts before you turn the wheel. Say 'down, down, turn' out loud into the chicanes for 5 laps.",
        "family": "entry_os", "setup": "entry_os"},
    "trail_brake_deep": {"title": "Still braking too much while turning in",
        "what": "Release the brake progressively as you add steering. Heavy brake plus steering overloads the front and makes the rear light, so the rear comes round.",
        "drill": "Practice trail braking: brake hard in a straight line, then bleed the pedal off over the first part of the turn so it's near zero at the apex.",
        "family": "entry_os", "setup": "entry_os"},
    "rear_lock": {"title": "Rear wheels locked on the brakes",
        "what": "The rears locked and the car swapped ends. Less pedal at the end of the braking zone, and brake in a straight line before turning.",
        "drill": "Practice your braking: hard at the start, then come off the pedal as the speed drops. Watch for the yellow lock lights on the dash.",
        "family": "lock_rear", "setup": "lock_rear"},
    "kerb_snap": {"title": "The kerb kicked the car out",
        "what": "Hitting that kerb with the car loaded unsettled the rear. Stay off it, or take less of it, with the steering straighter when you touch it.",
        "drill": "Run this corner 5 laps with the inside wheels just touching, not riding the kerb, and compare the exit speed.",
        "family": "kerbs", "setup": "kerbs"},
    "overspeed": {"title": "Too fast for the corner",
        "what": "You arrived quicker than normal and the grip ran out. Brake at your usual marker and roll the speed you know works.",
        "drill": "Use your clean-lap braking marker here for 5 laps, then move it later 5 m at a time only when the corner feels easy.",
        "family": "overspeed", "setup": None},
    "cold_tyres": {"title": "Cold tyres",
        "what": "The tyres weren't up to temperature. On the out-lap and the first lap of a stint brake earlier and use the throttle gently: the grip comes after a lap.",
        "drill": "On every out-lap, brake 20 m early and go to full throttle only with the steering straight.",
        "family": "cold", "setup": None},
    "damaged_car": {"title": "The car was already damaged",
        "what": "After the earlier hit the car didn't steer or brake properly. With damage like this, pit for repairs (or fast repair) instead of pushing.",
        "drill": "If a wheel feels wrong after contact, slow down, call the pit and check the damage before pushing again.",
        "family": "damage", "setup": None},
    # ---- offs without a spin
    "late_brake": {"title": "Braked too late / too fast into the corner",
        "what": "You braked later or arrived faster than usual and ran out of road. Brake at your normal marker; if you're late, give up the corner rather than forcing it.",
        "drill": "5 laps of practice braking exactly at your marker here; then try 5 m later only when the apex speed matches your clean laps.",
        "family": "overspeed", "setup": None},
    "front_lock": {"title": "Front wheels locked",
        "what": "The fronts locked so the car couldn't turn. Hit the brake hard at the start, then ease off as the speed drops, and don't add steering while the wheels are locked.",
        "drill": "Practice: 5 laps of braking at 90% peak here, releasing earlier, watching the pink lock lights.",
        "family": "lock_front", "setup": "lock_front"},
    "chicane_straight": {"title": "Went straight through the chicane",
        "what": "Too fast at the turn-in, so you missed the chicane. Brake at your usual marker and get the car turned before you go back to the throttle.",
        "drill": "5 laps of the chicane braking 10 m earlier than normal, then bring the marker back.",
        "family": "overspeed", "setup": None},
    "exit_wide": {"title": "Ran wide on the exit",
        "what": "You were on the throttle with lots of steering still on, so the car ran out of road. Get the car turned first, then open the throttle as the wheel comes straight.",
        "drill": "Practice this exit: wait until the steering starts to come back before going past half throttle, for 5 laps.",
        "family": "exit_us", "setup": "exit_us"},
    "understeer": {"title": "Understeer: the front didn't grip",
        "what": "You turned more and more but the car didn't turn: too fast at the turn-in for the grip. Slow a little more before the corner and don't keep adding lock.",
        "drill": "5 laps of this corner 3 km/h slower at the turn-in, then build back up.",
        "family": "mid_us", "setup": None},
    "traffic_wide": {"title": "Pushed wide in traffic",
        "what": "A car was right next to you and you ran out of room. Give up the corner when you're on the outside: it costs less than an off.",
        "drill": "In practice, run around the outside of an AI car through this corner and practise lifting to tuck in behind.",
        "family": "contact", "setup": None},
    "unclear": {"title": "Not sure from the data",
        "what": "The telemetry doesn't show one clear mistake here; the numbers below are what I see.",
        "drill": "Watch the replay of this moment and tell me what you felt: I'll add it to your notes.",
        "family": "unclear", "setup": None},
    "points_only": {"title": "Incident points with no spin or off",
        "what": "iRacing gave incident points, but the telemetry shows no spin, off or big hit: most likely a light touch with a car or the barrier.",
        "drill": "Watch the replay at this moment to see the touch.",
        "family": "unclear", "setup": None},
}


def _pct(x):
    return f"{x * 100:.0f}%"


def classify(run, ep, c):
    """-> (code, kind, why sentences, evidence list, factors list, confidence)"""
    comps = ep["comps"]
    ev, factors = [], []
    me, us = c.get("me") or {}, c.get("usual") or {}
    pts = ep["pts"]
    impact = _first(comps, "impact")
    spin = _first(comps, "spin") or _first(comps, "moment")
    off = _first(comps, "off")
    # -------------------------------------------------- kind
    near_ahead = c.get("ahead_min") is not None and c["ahead_min"] <= NEAR_CAR_M
    near_behind = c.get("behind_min") is not None and c["behind_min"] <= NEAR_CAR_M
    car_contact = 4 in ep["pts_list"] or (impact is not None and (near_ahead or near_behind) and impact["i0"] <= (spin or impact)["i0"])
    if car_contact:
        kind = "contact"
    elif impact is not None and impact["g"] >= IMPACT_G:
        kind = "crash"
    elif spin is not None and spin["type"] == "spin":
        kind = "spin"
    elif off is not None:
        kind = "off"
    elif spin is not None:
        kind = "moment"
    elif impact is not None:
        kind = "crash"
    else:
        kind = "incident"
    # -------------------------------------------------- evidence (always the same shape, so it reads like a table)
    dv_on = (c["v"] - c["v_usual"]) if c.get("v_usual") is not None else None
    late = None
    if me.get("brake_d") is not None and us.get("brake_d") is not None and (us.get("brake_d_spread") or 0) <= 60:
        late = me["brake_d"] - us["brake_d"]                         # + = braked later (deeper) than usual
    if c.get("v_usual") is not None:
        ev.append(f"Speed when it started: {c['v']:.0f} km/h (your clean laps at the same spot: {c['v_usual']:.0f}).")
    if c.get("dv_entry") is not None and c["dv_entry"] >= 4:
        ev.append(f"Fastest against normal: +{c['dv_entry']:.0f} km/h, {c['dv_entry_back']:.0f} m before.")
    if late is not None:
        soft = me.get("peak_brake") and us.get("peak_brake") and me["peak_brake"] < 0.6 * us["peak_brake"]
        ev.append(f"Brake point: {abs(late):.0f} m {'later' if late > 0 else 'earlier'} than usual" + (", but only lightly." if soft else ".")
                  if abs(late) >= 5 else "Brake point: same as usual.")
    if me.get("peak_brake") and us.get("peak_brake"):
        ev.append(f"Peak brake {me['peak_brake']:.0f}% (usual {us['peak_brake']:.0f}%).")
    ev.append(f"Inputs at that moment: throttle {_pct(c['thr'])}, brake {_pct(c['brk'])}, steering {abs(c['steer']):.0f}°, {c['gear']}{_th(c['gear'])} gear.")
    if c.get("thr_usual") is not None and c.get("steer_usual") is not None:
        ev.append(f"Clean laps there: throttle {_pct(c['thr_usual'])}, brake {_pct(c['brk_usual'])}, steering {abs(c['steer_usual']):.0f}°, {c['gear_usual']}{_th(c['gear_usual'])} gear.")
    if c.get("base_n", 0) < 2:
        ev.append("Not enough clean laps of this car here to compare with: the cause comes from the inputs alone.")
    if dv_on is not None and dv_on < -15:
        ev.insert(0, f"You were {abs(dv_on):.0f} km/h slower than normal at this point" + (" (the car was damaged)." if c.get("damage") else "."))
    # -------------------------------------------------- factors (things that made it more likely)
    if c.get("race_lap1"):
        factors.append("Race lap 1: cold tyres and a tight pack.")
    elif c.get("stint_lap") is not None and c["stint_lap"] <= 1 and kind != "contact":
        factors.append("First lap of the stint (out-lap): tyres not up to temperature yet.")
    if c["wet"] >= 3:
        factors.append(f"Track {c['wet_txt']}" + (" on dry tyres." if c["tyre"] == 0 else " (wet tyres on)." if c["tyre"] == 1 else "."))
    if c.get("damage"):
        factors.append(f"Car already damaged: the {', '.join(_wheel(w) for w in c['damage'])} wheel wasn't turning properly.")
    if c.get("tc1") is not None and c.get("tc1_usual") is not None and c["tc1"] < c["tc1_usual"] - 0.5:
        factors.append(f"Traction control (TC) was on {c['tc1']:.0f} here; you ran most of the session on {c['tc1_usual']:.0f}.")
    k = c.get("kerb")
    if k and kind != "contact" and (k.get("after") or k["dt"] > 0.6):
        factors.append("You were also over a kerb " + ("as it started to go." if k.get("after") else f"{k['dt']:.1f} s before."))
    if kind != "contact":
        nb = [_car_near(c["behind_min"], "behind")] if near_behind else []
        na = [_car_near(c["ahead_min"], "ahead")] if near_ahead else []
        factors += list(dict.fromkeys(nb + na))
    conf, why, code = "likely", [], "unclear"
    # -------------------------------------------------- contact
    if kind == "contact":
        code, why, conf = _why_contact(c, near_ahead, near_behind, late, dv_on)
    # -------------------------------------------------- spins / slides (and crashes that started with one)
    elif kind in ("spin", "moment") or (kind == "crash" and spin is not None and spin["i0"] <= impact["i0"]):
        code, why, conf = _why_slide(run, c, spin, late)
        if kind == "crash":
            why.append(f"Then the car hit the barrier ({impact['g']:.0f} g).")
    # -------------------------------------------------- offs (and crashes that started with one)
    elif kind == "off" or (kind == "crash" and off is not None):
        code, why, conf = _why_off(run, c, off, late)
        if kind == "crash":
            why.append(f"Then the car hit the barrier ({impact['g']:.0f} g).")
    elif kind == "crash":
        code, why, conf = _why_off(run, c, None, late)
        if code != "damaged_car":
            why.insert(0, f"A hard hit ({impact['g']:.0f} g) with no car close by: the barrier.")
    else:
        code = "points_only"
        why.append(f"iRacing gave {pts}x here but I see no spin, off or hard hit.")
        conf = "unsure"
    if c.get("damage") and code != "damaged_car" and kind != "contact":
        why.append("The car was already damaged at this point, which made it harder to control.")
    if c.get("damage_new") and kind != "contact":
        why.append(f"This broke the {', '.join(_wheel(w) for w in c['damage_new'])} wheel: it stopped turning properly after this, and the rest of the race was with a damaged car.")
    return code, kind, why, ev, factors, conf


def _car_near(m, where):
    return f"A car was right beside you ({m:.0f} m)." if m <= 2 else f"A car was {m:.0f} m {where} of you." if where == "ahead" else f"A car was {m:.0f} m behind you."


def _th(n):
    return {1: "st", 2: "nd", 3: "rd"}.get(n, "th")


def _wheel(w):
    return {"LF": "left-front", "RF": "right-front", "LR": "left-rear", "RR": "right-rear"}.get(w, w)


def _why_contact(c, near_ahead, near_behind, late, dv_on):
    why, conf = [], "likely"
    a3, a0 = c.get("ahead_3s"), c.get("ahead_min")
    b3, b0 = c.get("behind_3s"), c.get("behind_min")
    close_a = (a3 - a0) if a3 is not None and a0 is not None else 0
    close_b = (b3 - b0) if b3 is not None and b0 is not None else 0
    normal = (c.get("steer_usual") is not None and abs(abs(c["steer"]) - abs(c["steer_usual"])) < 8
              and c.get("thr_usual") is not None and abs(c["thr"] - c["thr_usual"]) < 0.3 and abs(c["brk"] - (c.get("brk_usual") or 0)) < 0.25)
    story, over = approach_story(c)
    if near_ahead and close_a >= 4 and (not near_behind or a0 <= b0):
        code = "contact_ahead"
        why.append(f"The gap to the car ahead closed from {a3:.0f} m to {a0:.0f} m in the last 3 seconds and you made contact.")
        if (late is not None and late >= 8) or over:
            why += story
            conf = "clear"
        else:
            why.append("Your braking was close to normal, so he was slower there than you expected (braking early, a mistake or a gear problem) and the gap was too small to react.")
    elif near_behind and (close_b >= 4 or (b0 <= 6 and (a0 is None or a0 > 12))):
        if close_b >= 4:
            code = "contact_behind"
            why.append(f"The car behind closed from {b3:.0f} m to {b0:.0f} m in the last 3 seconds and hit you.")
        else:
            code = "contact_side"
            why.append(f"A car was only {b0:.0f} m behind you for the 3 seconds before - that close, its nose is beside your rear wheels - and you touched as you went into {c['corner_key']}.")
        if c["thr_drop"] > 0.4 and (c.get("thr_usual") or 0) > 0.8:
            why.append(f"Just before, you lifted from {_pct(c['thr_max_before'])} to {_pct(c['thr'])} throttle where you're normally flat: he didn't expect it.")
            conf = "clear"
        elif late is not None and late <= -15:
            why.append(f"You braked {abs(late):.0f} m earlier than usual: he didn't expect it.")
            conf = "clear"
        elif dv_on is not None and dv_on < -15:
            why.append(f"You were {abs(dv_on):.0f} km/h slower than your normal there" + (" because of the damage" if c.get("damage") else "") + ", so he came up on you fast.")
        elif normal:
            why.append("Your speed, steering and pedals matched your clean laps at that spot, so you didn't brake-check or chop him: most of this one is on him.")
            conf = "clear"
        else:
            why.append(f"At the moment of contact: {_pct(c['thr'])} throttle, {_pct(c['brk'])} brake, {abs(c['steer']):.0f}° steering "
                       f"({_pct(c.get('thr_usual') or 0)} / {_pct(c.get('brk_usual') or 0)} / {abs(c.get('steer_usual') or 0):.0f}° on your clean laps).")
    elif near_ahead or near_behind:
        code = "contact_side"
        why.append(f"Cars were {min(a0 or 999, b0 or 999):.0f} m away along the track when it happened, but the gaps weren't closing much: most likely a car alongside.")
        why.append("The telemetry file doesn't record cars next to you, so I can't tell which one.")
        conf = "unsure"
    else:
        code = "contact_side"
        why.append("iRacing gave 4x (heavy contact) but no car shows close ahead or behind: most likely a car alongside.")
        conf = "unsure"
    if c.get("race_lap1"):
        why.append("It was lap 1, with the whole pack together.")
    if c.get("damage_new"):
        why.append(f"The contact damaged the {', '.join(_wheel(w) for w in c['damage_new'])} wheel: it stopped turning properly after this.")
    return code, why, conf


def _why_slide(run, c, spin, late):
    why, conf = [], "likely"
    story, over = approach_story(c)
    phase_power = c["thr"] > 0.3 and c["thr_rise"] > 0.25
    lift = c["thr_drop"] > 0.45 and c["brk_max_before"] < 0.1 and c["v"] > 110
    braking = c["brk"] > 0.05 or c["brk_max_before"] > 0.15
    ds = c.get("downshift")
    ds_before = ds if ds and not ds.get("after") and ds["dt"] <= 1.3 and ds["lat"] >= 1.0 else None
    ds_during = ds if ds and ds.get("after") and ds["dt"] > -0.7 and ds["lat"] >= 1.0 else None
    rear_lock = any(w in (c.get("lock") or {}) for w in ("LR", "RR"))
    slip, slip_n = c.get("rear_slip"), c.get("rear_slip_normal")
    kerb = c.get("kerb")
    direction = "the rear stepped out" if abs(spin["peak"]) < 100 else "the car went right round"
    if c.get("damage") and not phase_power and not braking:
        return "damaged_car", [f"With the damaged {', '.join(_wheel(w) for w in c['damage'])} wheel the car lost control at {c['v']:.0f} km/h."], "likely"
    if kerb and not kerb.get("after") and kerb["dt"] <= 0.6 and (kerb["jolt"] > 0.6 or not (phase_power or braking or lift)):
        why.append(f"You hit the kerb {kerb['dt']:.1f} s before the slide started (a {kerb['jolt']:.1f} g jolt) and {direction}.")
        if phase_power:
            why.append(f"You were also on the throttle ({_pct(c['thr'])}) at the time.")
        return "kerb_snap", why, "likely"
    if phase_power:
        lock_on = abs(c["steer"]) > max(25, 0.5 * c["steer_max_before"]) or (c.get("steer_usual") is not None and abs(c["steer"]) > abs(c["steer_usual"]) + 10)
        why.append(f"You went from {_pct(c['thr_min_before'])} to {_pct(c['thr'])} throttle in the last second"
                   + (f" with {abs(c['steer']):.0f}° of steering still on" if lock_on else "")
                   + f", in {c['gear']}{_th(c['gear'])} gear, and {direction}.")
        if c.get("steer_usual") is not None and abs(c["steer"]) > abs(c["steer_usual"]) + 10:
            why.append(f"On your clean laps you only have {abs(c['steer_usual']):.0f}° of steering at this spot: you were on a tighter line and still turning.")
            conf = "clear"
        if slip is not None and slip_n is not None and slip > slip_n + 5:
            why.append(f"The rear wheels were spinning {slip:.0f}% faster than the car (normal for you in this gear: about {slip_n:.0f}%).")
            conf = "clear"
        if c.get("thr_usual") is not None and c["thr"] > c["thr_usual"] + 0.25:
            why.append(f"On your clean laps you're at {_pct(c['thr_usual'])} throttle at this spot.")
            conf = "clear"
        if c["gear"] <= 2:
            why.append("Low gear means lots of torque at the rear wheels.")
        return "power_oversteer", why, conf
    if ds_before:
        why.append(f"You downshifted to {ds['to']}{_th(ds['to'])} {ds['dt']:.1f} s before the slide, while the car was already turning ({ds['lat']:.1f} g sideways, {ds['steer']:.0f}° of steering), and {direction}.")
        if c.get("gear_usual") is not None and c["gear_usual"] > ds["to"]:
            why.append(f"On your clean laps you're still in {c['gear_usual']}{_th(c['gear_usual'])} at this point.")
            conf = "clear"
        if braking:
            why.append(f"You were trailing the brake at the same time ({_pct(c['brk_max_before'])} in the last second).")
        why += story
        return "downshift_turning", why, conf
    if braking and rear_lock:
        w = [x for x in ("LR", "RR") if x in c["lock"]]
        why.append(f"The {' and '.join(_wheel(x) for x in w)} wheel{'s' if len(w) > 1 else ''} locked under braking ({_pct(c['brk_max_before'])} brake) and {direction}.")
        why += story
        return "rear_lock", why, "clear"
    if braking and abs(c["steer"]) > 15:
        why.append(f"You were still on the brake ({_pct(c['brk_max_before'])}) with {abs(c['steer']):.0f}° of steering when the rear went"
                   + (f"; on your clean laps you're at {_pct(c['brk_usual'])} brake there." if c.get("brk_usual") is not None and c["brk"] > c["brk_usual"] + 0.08 else "."))
        why += story
        if over or (late is not None and late >= 8):
            conf = "clear"
        if ds_during:
            why.append(f"You also downshifted to {ds['to']}{_th(ds['to'])} while it was starting to slide, which added engine braking to the rear.")
        return ("overspeed" if over >= 12 else "trail_brake_deep"), why, conf
    if ds_during and not lift:
        why.append(f"You downshifted to {ds['to']}{_th(ds['to'])} while turning ({ds['lat']:.1f} g) just as the rear started to go, and {direction}.")
        why += story
        return "downshift_turning", why, "likely"
    if lift:
        why.append(f"You lifted from {_pct(c['thr_max_before'])} to {_pct(c['thr'])} throttle at {c['v']:.0f} km/h while turning ({c['lat_max_before']:.1f} g), and {direction}.")
        if c.get("thr_usual") is not None and c["thr_usual"] > 0.8:
            why.append(f"On your clean laps you're at {_pct(c['thr_usual'])} throttle at this spot.")
            conf = "clear"
        return "lift_off", why, conf
    if over:
        why.append(f"Your inputs at the moment it went look normal, but {direction} because you came in too fast:")
        why += story
        return "overspeed", why, "likely"
    if (c.get("race_lap1") or (c.get("stint_lap") or 9) <= 1) and c["wet"] < 3:
        why.append(f"Nothing unusual in your inputs, on the {'first lap of the race' if c.get('race_lap1') else 'first lap of the stint'}: the tyres were cold.")
        return "cold_tyres", why, "unsure"
    why.append(f"{direction[0].upper() + direction[1:]} at {c['v']:.0f} km/h, but your inputs look close to normal.")
    if c["wet"] >= 3:
        why.append(f"The track was {c['wet_txt']}: there may have been a wetter patch here.")
    return "unclear", why, "unsure"


def _why_off(run, c, off, late):
    why, conf = [], "likely"
    story, over = approach_story(c)
    surf = off["surface"] if off else "barrier"
    where = f"onto the {surf}" if off else ""
    front_lock = any(w in (c.get("lock") or {}) for w in ("LF", "RF"))
    ck = (c.get("corner_key") or "").lower()
    chicane = "chicane" in ck or "ford" in ck
    steer_ratio = None
    if c.get("steer_usual") is not None and abs(c["steer_usual"]) > 5:
        steer_ratio = abs(c["steer"]) / abs(c["steer_usual"])
    if c.get("damage"):
        why.append(f"The car was damaged (the {', '.join(_wheel(w) for w in c['damage'])} wheel wasn't turning properly) and "
                   + (f"went off {where}." if off else "hit the barrier."))
        if steer_ratio and steer_ratio > 1.4:
            why.append(f"You had {abs(c['steer']):.0f}° of steering on where you normally need {abs(c['steer_usual']):.0f}°: the car wouldn't turn.")
        return "damaged_car", why, "clear"
    if front_lock and c["brk_max_before"] > 0.3:
        w = [x for x in ("LF", "RF") if x in c["lock"]]
        why.append(f"The {' and '.join(_wheel(x) for x in w)} wheel{'s' if len(w) > 1 else ''} locked under braking, so the car went straight {where}.")
        why += story
        return "front_lock", why, "clear"
    st_off = c.get("steer_off") if c.get("steer_off") is not None else abs(c["steer"])
    if chicane and min(abs(c["steer"]), st_off) < 15 and c["v"] > 60:
        why.append(f"You went straight across {c['corner_key']} at {c['v']:.0f} km/h with almost no steering.")
        why += story
        if over or (late is not None and late >= 5):
            conf = "clear"
        if min(c.get("ahead_min", 99), c.get("behind_min", 99)) <= 10:
            why.append("There was a car close by: you may have been avoiding him.")
        return "chicane_straight", why, conf
    if min(c.get("ahead_min", 99), c.get("behind_min", 99)) <= 4:
        why.append(f"A car was {min(c.get('ahead_min', 99), c.get('behind_min', 99)):.0f} m away - side by side - when you went off {where}: probably no room.")
        return "traffic_wide", why, "unsure"
    if over >= 12 or (late is not None and late >= 15):
        # way too fast in: that's the cause, whatever happened on the exit
        why += story or [f"You braked {late:.0f} m later than usual."]
        if c["thr"] > 0.3:
            why.append(f"With the extra speed the car ran wide; you were at {_pct(c['thr'])} throttle with {abs(c['steer']):.0f}° of steering and ran out of road {where}.")
        elif c["brk"] > 0.05 or c["brk_max_before"] > 0.15:
            why.append(f"You were still braking ({_pct(c['brk_max_before'])}) in the corner, and ran out of road {where}.")
        else:
            why.append(f"The car ran wide and went off {where}.")
        if steer_ratio and steer_ratio > 1.3:
            why.append(f"You had {abs(c['steer']):.0f}° of steering where you normally use {abs(c['steer_usual']):.0f}°: the front had no grip left.")
        return "late_brake", why, "clear" if over >= 12 and late is not None and late >= 8 else "likely"
    if c["thr"] > 0.3 and abs(c["steer"]) > 20:
        why.append(f"You were at {_pct(c['thr'])} throttle with {abs(c['steer']):.0f}° of steering on and ran out of road {where}.")
        if c.get("steer_usual") is not None and abs(c["steer"]) > abs(c["steer_usual"]) + 12:
            why.append(f"On your clean laps the wheel is almost straight here ({abs(c['steer_usual']):.0f}°): you were still turning, on a wider or later line.")
        if c.get("thr_usual") is not None and c["thr"] > c["thr_usual"] + 0.2:
            why.append(f"On your clean laps you're only at {_pct(c['thr_usual'])} throttle at this spot: you went to the throttle too early.")
            conf = "clear"
        why += story
        return "exit_wide", why, conf
    if over or (late is not None and late >= 8):
        why += story or [f"You braked {late:.0f} m later than usual."]
        if c["brk"] > 0.05 or c["brk_max_before"] > 0.15:
            why.append(f"You were still braking ({_pct(c['brk_max_before'])}) in the corner, and ran out of road {where}.")
        else:
            why.append(f"The car ran wide and went off {where}.")
        if steer_ratio and steer_ratio > 1.3:
            why.append(f"You had {abs(c['steer']):.0f}° of steering where you normally use {abs(c['steer_usual']):.0f}°: the front had no grip left.")
        return "late_brake", why, "clear" if over and late is not None and late >= 8 else "likely"
    if steer_ratio and steer_ratio > 1.3 and abs(c["steer"]) > 25:
        why.append(f"You had {abs(c['steer']):.0f}° of steering where you normally use {abs(c['steer_usual']):.0f}°, and the car didn't turn: the front tyres gave up.")
        return "understeer", why, "likely"
    if (c.get("race_lap1") or (c.get("stint_lap") or 9) <= 1):
        why.append(f"Your inputs look close to normal, on the {'first lap of the race' if c.get('race_lap1') else 'first lap of the stint'}: cold tyres.")
        return "cold_tyres", why, "unsure"
    why.append(f"Went off {where} at {c['v']:.0f} km/h; your inputs look close to normal.")
    return "unclear", why, "unsure"


# ======================================================================================== one session
def analyse_run(run, pool):
    comps = detect(run)
    eps = episodes_of(run, comps)
    out = []
    n = 0
    fin = np.flatnonzero(run.state >= 5)
    last_lap = int(run.lapn[fin[0]]) if len(fin) and "race" in run.sess_type.lower() else None
    for ep in eps:
        if last_lap is not None and int(run.lapn[ep["i0"]]) > last_lap:
            continue                                       # after the flag: the cool-down lap doesn't count
        types = [c["type"] for c in ep["comps"]]
        if not ep["pts"] and types and set(types) <= {"impact"}:
            # a big jolt alone with no points and no slide = a kerb or a bump, not an incident
            if max(c["g"] for c in ep["comps"]) < 6:
                continue
        c = context(run, pool, ep)
        code, kind, why, ev, factors, conf = classify(run, ep, c)
        if kind == "moment" and not ep["pts"] and abs(_first(ep["comps"], "moment")["peak"]) < 20:
            continue                                       # small slides you held: counted in habits, not listed
        n += 1
        cz = CAUSES[code]
        title = _title(kind, c, ep)
        spin_c = _first(ep["comps"], "spin") or _first(ep["comps"], "moment")
        off_c = _first(ep["comps"], "off")
        imp = _first(ep["comps"], "impact")
        e = {"n": n, "kind": kind, "title": title, "lap": c["lap"], "stint_lap": c["stint_lap"], "t": round(c["t_on"], 1),
             "d": round(c["d_on"]), "corner": c["corner"], "corner_key": c["corner_key"], "pts": ep["pts"], "pts_list": ep["pts_list"],
             "cause": code, "cause_title": cz["title"], "why": why, "what": cz["what"], "drill": drill_text(code, run.s.track_name, run.s.track_display), "family": cz["family"],
             "evidence": ev, "factors": factors, "confidence": conf, "loss": c.get("loss"),
             "pos_before": c.get("pos_before"), "pos_after": c.get("pos_after"),
             "spin_deg": spin_c["peak"] if spin_c else None, "off_surface": off_c["surface"] if off_c else None,
             "impact_g": imp["g"] if imp else None, "wet": c["wet_txt"], "base_n": c.get("base_n"), "base_src": c.get("base_src"),
             "race_lap1": c.get("race_lap1"), "damaged": bool(c.get("damage")),
             "spun": any(x["type"] == "spin" for x in ep["comps"]), "broke": [_wheel(w) for w in c.get("damage_new") or []],
             "target": {k: c.get(k) for k in ("v_turnin_usual", "gear_turnin_usual", "v_turnin", "gear_turnin", "dv_entry") if c.get(k) is not None},
             "brake_late_m": round(c["me"]["brake_d"] - c["usual"]["brake_d"]) if (c.get("me") or {}).get("brake_d") is not None and (c.get("usual") or {}).get("brake_d") is not None else None,
             "trace": _trace(run, pool, c)}
        out.append(e)
    return out


def _title(kind, c, ep):
    where = c["corner"]
    if kind in ("contact", "crash") and any(x["type"] == "spin" for x in ep["comps"]):
        kind = kind + "_spin"
    at = "at" if not where.startswith(("the ", "after ")) and "m into" not in where else "at" if where.startswith("the ") else ""
    pre = {"spin": "Spin", "contact": "Contact", "crash": "Crash", "off": "Off", "moment": "Big slide (caught)",
           "incident": "Incident", "contact_spin": "Contact and spin", "crash_spin": "Spin and crash"}.get(kind, kind.title())
    sep = f" {at} " if at else " "
    return f"{pre}{sep}{where}".replace("  ", " ")


def _trace(run, pool, c):
    """The 6 s before to 3 s after, 20 points a second, plus what you normally do at the same distances."""
    R = run
    i = c["i_on"]
    step = max(1, R.tick // 20)
    a, b = max(0, i - R.tick * 6), min(R.n, i + R.tick * 3)
    idx = np.arange(a, b, step)
    out = {"t": [round(float(R.t[j] - R.t[i]), 2) for j in idx],
           "kmh": [round(float(R.kmh[j]), 1) for j in idx], "thr": [round(float(R.thr[j]), 2) for j in idx],
           "brk": [round(float(R.brk[j]), 2) for j in idx], "steer": [round(float(R.steer[j]), 1) for j in idx],
           "gear": [int(R.gear[j]) for j in idx], "slip": [round(float(R.beta[j]), 1) for j in idx],
           "off": [int(R.surf[j] == 0) for j in idx], "d": [round(float(R.dist[j])) for j in idx]}
    lap = R.lap_at(i)
    base = pool.baseline(R, lap["cond"] if lap else "dry")
    if base.n >= 2:
        # usual values at the same track distance (only before the event: after it the distances stop meaning much)
        u = {"kmh": [], "thr": [], "brk": [], "steer": []}
        d0 = float(R.dist[i])
        for j, dj in zip(idx, out["d"]):
            if j <= i and abs(dj - d0) < 1500:
                u["kmh"].append(round(base.at("kmh", dj), 1)); u["thr"].append(round(base.at("Throttle", dj), 2))
                u["brk"].append(round(base.at("Brake", dj), 2)); u["steer"].append(round(base.at("steer", dj), 1))
            else:
                for k in u:
                    u[k].append(None)
        out["usual"] = u
    out["map"] = _line_map(R, base, i, a, b)
    return out


def _line_map(R, base, i, a, b):
    """Where the car went (GPS) from 6 s before to 3 s after, against your usual line over the same stretch, in
    metres around the moment it started. None without GPS."""
    if R.glat is None:
        return None
    lat0, lon0 = float(R.glat[i]), float(R.glon[i])
    k = math.cos(math.radians(lat0)) * math.pi / 180 * 6371000.0
    kl = math.pi / 180 * 6371000.0
    step = max(1, R.tick // 10)
    idx = np.arange(a, b, step)
    me = {"x": [round(float((R.glon[j] - lon0) * k), 1) for j in idx], "y": [round(float((R.glat[j] - lat0) * kl), 1) for j in idx],
          "off": [int(R.surf[j] == 0) for j in idx], "t": [round(float(R.t[j] - R.t[i]), 2) for j in idx]}
    out = {"me": me}
    if base.n >= 2 and base.med is not None and "gLat" in base.med:
        d0 = float(R.dist[max(a, 0)])
        d1 = min(float(R.dist[i]) + 400, base.med["d"][-1])
        if d1 < d0:                                    # crossed the line inside the window
            d1 = base.med["d"][-1]
        ds = np.arange(d0, d1, 4.0)
        ul = np.interp(ds, base.med["d"], base.med["gLat"]); uo = np.interp(ds, base.med["d"], base.med["gLon"])
        out["usual"] = {"x": [round(float((x - lon0) * k), 1) for x in uo], "y": [round(float((y - lat0) * kl), 1) for y in ul]}
    return out


def session_summary(run, eps, pool):
    """Result, pace, stints, consistency, incidents."""
    R = run
    st = R.sess_type or "Session"
    out = {"type": st, "date": R.date, "track": R.s.track_display, "car": R.s.car, "car_path": R.s.car_path, "track_name": R.s.track_name,
           "file": os.path.basename(R.path), "laps": len([L for L in R.laps if L["n"] > 0])}
    # result
    racing = (R.state >= 4) & (R.cpos > 0)
    if racing.any():
        out["start_pos"] = int(R.cpos[np.flatnonzero(racing)[0]])
        out["finish_pos"] = int(R.cpos[np.flatnonzero(R.cpos > 0)[-1]])
        out["finished"] = bool((R.state >= 5).any())
        if not out["finished"]:
            out["retired_lap"] = int(R.lapn[-1])
    best = R.s.d.get("LapBestLapTime")
    if best is not None and best[-1] > 0:
        out["best"] = round(float(best[-1]), 3)
    clean = R.clean_laps()
    times = [L["posted"] or L["time"] for L in clean]
    if times:
        out["clean_laps"] = len(times)
        out["median"] = round(float(np.median(times)), 3)
        out.setdefault("best", round(min(times), 3))
        out["spread"] = round(float(np.std(times)), 2) if len(times) > 2 else None
        b = out["best"]
        out["within_1s"] = sum(1 for x in times if x <= b + 1.0)
    # stints
    stints, cur = [], []
    for L in R.laps:
        if L["n"] <= 0:
            continue
        cur.append(L)
        if L["pit"]:
            stints.append(cur); cur = []
    if cur:
        stints.append(cur)
    out["stints"] = []
    for s in stints:
        ts = [L["posted"] or L["time"] for L in s if L in clean]
        out["stints"].append({"laps": len(s), "from": s[0]["n"], "to": s[-1]["n"], "median": round(float(np.median(ts)), 3) if ts else None,
                              "best": round(min(ts), 3) if ts else None,
                              "fade": round(float(np.polyfit(np.arange(len(ts)), ts, 1)[0]), 2) if len(ts) >= 4 else None})
    out["wet"] = max(WETNESS.get(int(np.median(R.wet[R.v > 20])) if (R.v > 20).any() else 0, "?"), "")
    out["wet_max"] = WETNESS.get(int(R.wet.max()), "?")
    out["tyres"] = {0: "dry", 1: "wet"}.get(int(np.median(R.tyre)), None)
    out["incidents"] = int(R.inc.max() - R.inc.min()) if len(R.inc) else 0
    kinds = [e["kind"] for e in eps]
    out["counts"] = {k: kinds.count(k) for k in ("spin", "crash", "contact", "off", "moment", "incident")}
    out["time_lost"] = round(sum(e["loss"] for e in eps if e.get("loss") and e["loss"] > 0), 1)
    out["damage"] = [{"wheel": _wheel(w), "lap": int(R.lapn[i]), "corner": corner_name(R, float(R.dist[i]))} for i, w in R._damage]
    out["habits"] = habits(run, pool)
    out["corner_loss"] = corner_times(run, clean)
    out["corner_names"] = [c["name"] for c in run.s.find_corners() or []]
    return out


def corner_times(run, clean):
    """Time you usually lose in each corner on your clean laps: median against your best there."""
    if len(clean) < 3:
        return []
    trs = [run.light_trace(L["a"], L["b"]) for L in clean]
    trs = [t for t in trs if t is not None and len(t["d"]) > 0.9 * run.L]
    rows = []
    for c in run.s.find_corners() or []:
        a, b = max(0.0, c["start"] - 150), min(run.L - 2, c["end"] + 100)
        ts = [float(np.interp(b, t["d"], t["t"]) - np.interp(a, t["d"], t["t"])) for t in trs if t["d"][-1] > b]
        if len(ts) >= 3:
            rows.append({"name": c["name"], "lost": round(float(np.median(ts) - min(ts)), 2), "n": len(ts)})
    rows.sort(key=lambda r: -r["lost"])
    return [r for r in rows if r["lost"] >= 0.05][:6]


def habits(run, pool):
    """Small things on the clean running that add up: lock-ups and wheelspin moments per corner, slides you caught."""
    R, tk = run, run.tick
    res = {"lockups": {}, "wheelspin": {}, "slides": {}}
    live = (R.v > 15) & ~R.pit & (R.surf > 0) & (np.abs(R.beta) < 6)
    broken = set(w for _, w in R._damage)
    for axle, ws_ in (("front", ("LF", "RF")), ("rear", ("LR", "RR"))):
        ws = [R.wheels[w] for w in ws_ if w in R.wheels and w not in broken]
        if not ws:
            continue
        low = np.min(ws, axis=0)
        m = live & (R.brk > 0.1) & (low < R.v * 0.75)
        for a, b in _segments(m, int(tk * 0.3)):
            if b - a < tk * 0.1:
                continue
            k = corner_key(R, float(R.dist[a]))
            r = res["lockups"].setdefault(k, {"front": 0, "rear": 0})
            r[axle] += 1
    rr = [R.wheels[w] for w in ("LR", "RR") if w in R.wheels and w not in broken]
    if rr:
        rear = np.mean(rr, axis=0)
        for g in range(1, 8):
            n = _normal_slip(R, g)
            if n is None:
                continue
            m = live & (R.gear == g) & (R.thr > 0.3) & ((rear / np.maximum(R.v, 1) - 1) * 100 > n + 8)
            for a, b in _segments(m, int(tk * 0.4)):
                if b - a < tk * 0.15:
                    continue
                k = corner_key(R, float(R.dist[a]))
                res["wheelspin"][k] = res["wheelspin"].get(k, 0) + 1
    if R.has_slip:
        m = (R.v > 8) & ~R.pit & (np.abs(R.beta) > 8) & (np.abs(R.beta) < MOMENT_DEG + 5)
        for a, b in _segments(m, int(tk * 0.5)):
            k = corner_key(R, float(R.dist[a]))
            res["slides"][k] = res["slides"].get(k, 0) + 1
    # merge front+rear lock-ups counted once per wheel pair
    return res


# ======================================================================================== many sessions
def analyse(paths, landmarks=None, progress=None, log=print):
    """Analyse recordings together (they share baselines when they're the same car + track).
    -> {"version", "sessions": [{"summary", "episodes"}], "setup": [...]}"""
    if landmarks:
        from . import telemetry as _T
        _T._LM_CACHE = None                               # load the corner names from this file
        track_landmarks("", landmarks)
    runs = []
    for i, p in enumerate(paths):
        try:
            runs.append(Run(p))
        except Exception as e:
            log(f"[forensics] {os.path.basename(p)}: {e!r}")
        if progress:
            progress(i + 1, len(paths))
    pool = Pool(runs)
    out = {"version": VERSION, "made": time.strftime("%Y-%m-%d %H:%M"), "sessions": []}
    for r in sorted(runs, key=lambda r: r.date):
        eps = analyse_run(r, pool)
        sm = session_summary(r, eps, pool)
        out["sessions"].append({"id": _sid(r.path), "path": r.path, "summary": sm, "episodes": eps})
    out["setup"] = setup_advice(out["sessions"], runs[0].s if runs else None)
    return out


def _sid(path):
    """Same id as the Analysis tab uses for this recording."""
    try:
        from .telemetry import _sid as tsid
        return tsid(path)
    except OSError:
        return os.path.basename(path)


def setup_advice(sessions, sess=None):
    """Setup only when the same kind of mistake repeats (rulebook: technique first, 3+ times)."""
    from . import setup_bank as SB
    kind = "gtp" if (sess is not None and getattr(sess, "gtp", False)) else "gt3" if sess is not None and "gt3" in (sess.car_path + sess.car_class).lower() else "other"
    aids = None
    if sess is not None:                       # 2026-10-29 (car parity E7-E9): the car table's kind, no ABS/TC fixes it lacks
        from . import cars
        from .mechanic import car_kind
        kind = SB.table_kind(car_kind(sess)) if cars.lookup(sess.car_path, getattr(sess, "car_id", None)) else kind
        aids = cars.session_aids(sess)
    fam = {}
    for s in sessions:
        for e in s["episodes"]:
            cz = CAUSES.get(e["cause"], {})
            if cz.get("setup") and e["confidence"] != "unsure":
                fam.setdefault(cz["setup"], []).append(e)
    out = []
    bank = {p["id"]: p for p in SB.PROBLEMS}
    for pid, es in sorted(fam.items(), key=lambda kv: -len(kv[1])):
        p = bank.get(pid)
        if not p:
            continue
        wet = sum(1 for e in es if e["wet"] not in ("dry", "mostly dry", "unknown")) >= len(es) / 2
        fixes = SB.steps_for(p, kind, aids)
        where = ", ".join(dict.fromkeys(e["corner_key"] for e in es))
        if len(es) >= 3:
            out.append({"problem": p["label"], "times": len(es), "where": where, "repeat": True,
                        "first_fix": fixes[0]["t"] if fixes else None, "why": fixes[0]["why"] if fixes else "",
                        "wet_note": p.get("wet") if wet else None,
                        "line": f"{p['label']}: {len(es)} times ({where}). Technique first; if it still happens with clean inputs, the mechanic's first change is: {fixes[0]['t'] if fixes else '-'}."})
        else:
            out.append({"problem": p["label"], "times": len(es), "where": where, "repeat": False,
                        "line": f"{p['label']}: {len(es)} time{'s' if len(es) != 1 else ''} ({where}) - not enough to change the car, it's the driving."})
    return out


# ======================================================================================== plain text
def describe(e, short=False):
    """One episode as plain-English lines."""
    L = [f"{e['title']} - lap {e['lap']}" + (f", {e['pts']}x" if e["pts"] else "") + (f", about {e['loss']:.0f} s lost" if e.get("loss") and e["loss"] >= 1 else "")
         + (f", P{e['pos_before']} to P{e['pos_after']}" if e.get("pos_before") and e.get("pos_after") and e["pos_after"] != e["pos_before"] else "")]
    L.append(f"Why: {e['cause_title']}." + ("" if e["confidence"] != "unsure" else " (not certain)"))
    L += ["  " + w for w in e["why"]]
    if short:
        L.append(f"What to do: {e['what']}")
        return L
    if e["factors"]:
        L.append("Also: " + " ".join(e["factors"]))
    L.append(f"What to do: {e['what']}")
    L.append(f"Drill: {e['drill']}")
    L.append("Evidence: " + " ".join(e["evidence"]))
    return L


def points_meaning(pts):
    return {1: "1x = off track", 2: "2x = loss of control or a wall", 4: "4x = heavy contact with a car"}.get(pts, f"{pts}x")


def report_md(res):
    """The whole analysis as a Markdown report (plain English)."""
    from . import debrief as DB
    return DB.night_report_md(res)


# ======================================================================================== cache + background scan
FX_DIR = os.path.join(CACHE_DIR, "forensics")


def cache_path(paths):
    import hashlib
    key = []
    for p in sorted(paths):
        try:
            st = os.stat(p)
            key.append([os.path.basename(p), st.st_size, int(st.st_mtime)])
        except OSError:
            key.append([p, 0, 0])
    h = hashlib.md5(json.dumps([VERSION] + key).encode()).hexdigest()[:16]
    return os.path.join(FX_DIR, f"fx_{h}.json")


def analyse_cached(paths, landmarks=None, log=print):
    cp = cache_path(paths)
    try:
        with open(cp, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        pass
    res = json.loads(json.dumps(analyse(paths, landmarks, log=log), default=_num))     # plain types (the page bridge needs them)
    try:
        os.makedirs(FX_DIR, exist_ok=True)
        with open(cp + ".tmp", "w", encoding="utf-8") as f:
            json.dump(res, f, default=_num)
        os.replace(cp + ".tmp", cp)
    except OSError as e:
        log(f"[forensics] cache: {e!r}")
    return res


def _num(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def recent_sessions(hours=18.0, sessions=None, now=None):
    """The recordings of the last `hours` (tonight), grouped with the newest one's car + track. -> [paths]"""
    from .telemetry import list_sessions
    ss = sessions if sessions is not None else list_sessions()
    if not ss:
        return []
    now = now or max(s["mtime"] for s in ss)
    newest = max(ss, key=lambda s: s["mtime"])
    pick = [s for s in ss if now - s["mtime"] <= hours * 3600 and s["car"] == newest["car"] and s["track"] == newest["track"]]
    pick.sort(key=lambda s: s["mtime"])
    return [s["path"] for s in pick]


# ======================================================================================== CLI
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Diagnose every spin, crash and off in iRacing telemetry.")
    ap.add_argument("files", nargs="+", help=".ibt files (several = analysed together, sharing your clean laps)")
    ap.add_argument("--landmarks", help="trackLandmarksData.json (CrewChief) for corner names")
    ap.add_argument("--md", help="write the plain-English report here")
    ap.add_argument("--json", help="write the raw analysis here")
    a = ap.parse_args(argv)
    res = analyse(a.files, a.landmarks, log=lambda m: print(m, file=sys.stderr))
    text = report_md(res)
    if a.md:
        os.makedirs(os.path.dirname(os.path.abspath(a.md)), exist_ok=True)
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(text)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, default=_num, indent=1)
    sys.stdout.write(text if sys.stdout.encoding and "utf" in sys.stdout.encoding.lower() else text.encode("ascii", "replace").decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
