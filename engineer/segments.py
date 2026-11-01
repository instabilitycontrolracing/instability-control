"""ic187 (#734 / #733, 2026-11-01): the segment timer - custom sectors that iRacing doesn't have.

Angelo practises one piece of the lap over and over (pit box -> out of the PlayStation chicane on cold tyres, then
flying resets) and changes TC / brake bias / migration between tries. This times each piece and keeps every try with the
in-car settings it was driven on, so the iPad TRACK page can show which settings were quicker.

A segment is FROM -> TO in lap metres. FROM can also be "pitbox": the timer starts the moment the car leaves its pit
stall. Times are interpolated between the ~15 Hz reads (crossing time worked out from the two samples either side), so
they're good to a few hundredths. A reset (the car jumps more than 150 m in one read, or backwards) cancels the tries in
progress - a try only counts if it was driven through.

Defaults per track below; Angelo's own list (if any) is %LOCALAPPDATA%\\RaceEngineer\\custom_sectors.json:
    {"lemans full": [{"name": "Pit box -> PlayStation exit", "from": "pitbox", "to": 4300}, ...]}
Every finished try is kept in %LOCALAPPDATA%\\RaceEngineer\\segments\\<track>.json (last 300 per segment).
"""
import json, os, threading, time

BASE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RaceEngineer")
KEEP = 300
JUMP_M = 150.0            # one read moving further than this (or backwards by more than 5 m) = a reset / tow
MAX_SEG_S = 600.0         # anything longer isn't a try (parked, left the car)

# Le Mans corner windows come from his 10-31 race telemetry (speed minimum +/- the braking zone and 350 m of exit).
DEFAULTS = {
    "lemans full": [
        {"name": "Pit box -> PlayStation exit", "from": "pitbox", "to": 4300},
        {"name": "Pit box -> Dunlop exit", "from": "pitbox", "to": 1250},
        {"name": "Dunlop chicane", "from": 800, "to": 1250},
        {"name": "Tertre Rouge -> PlayStation exit", "from": 1250, "to": 4300},
        {"name": "PlayStation chicane", "from": 3300, "to": 4300},
        {"name": "Michelin chicane", "from": 5900, "to": 6350},
        {"name": "Mulsanne corner", "from": 7500, "to": 8050},
        {"name": "Arnage", "from": 9950, "to": 10450},
        {"name": "Ford chicanes", "from": 13150, "to": 13540},
    ],
}


def _safe(s):
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in (s or "track")).strip() or "track"


def load_defs(track):
    try:
        with open(os.path.join(BASE, "custom_sectors.json"), encoding="utf-8") as f:
            own = json.load(f)
        if isinstance(own, dict) and isinstance(own.get(track), list) and own[track]:
            return [d for d in own[track] if isinstance(d, dict) and "name" in d and "from" in d and "to" in d]
    except Exception:
        pass
    return [dict(d) for d in DEFAULTS.get(track, [])]


class Segments:
    def __init__(self, log=print):
        self.log = log
        self.lock = threading.Lock()
        self.track = None
        self.defs, self.hist, self.active = [], {}, {}
        self.prev = None                  # (session time, lap metres)
        self.in_stall_prev = None
        self.last_done = None
        self._dirty, self._save_t = False, 0.0

    # ------------------------------------------------------------------------------------------- storage
    def _path(self):
        return os.path.join(BASE, "segments", _safe(self.track) + ".json")

    def _load(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                h = json.load(f)
            return h if isinstance(h, dict) else {}
        except Exception:
            return {}

    def save(self, force=False):
        if not self._dirty or not self.track or (not force and time.time() - self._save_t < 10):
            return
        try:
            os.makedirs(os.path.dirname(self._path()), exist_ok=True)
            tmp = self._path() + ".tmp"
            with self.lock:
                data = json.dumps(self.hist)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, self._path())
            self._dirty, self._save_t = False, time.time()
        except Exception as e:
            self.log(f"[segments] save: {e!r}")

    # ------------------------------------------------------------------------------------------- live
    def _settings(self, g):
        def r(k, n=2):
            v = g(k)
            try:
                return round(float(v), n)
            except (TypeError, ValueError):
                return None
        # checked against the garage (10-30 file: TC gain 5 / slip 8 -> dcTractionControl 8, dcTractionControl2 5):
        # dcTractionControl = TC LON (slip), dcTractionControl2 = TC LAT (gain)
        return {"tc_lat": r("dcTractionControl2", 0), "tc_lon": r("dcTractionControl", 0), "bias": r("dcBrakeBias"),
                "mig": r("dcBrakeMisc", 0), "farb": r("dcAntiRollFront", 0), "rarb": r("dcAntiRollRear", 0),
                "fuel": r("FuelLevel", 1)}

    def _start(self, i, t, g):
        self.active[i] = {"t0": t, "min": None, "off": False, "set": self._settings(g)}

    def _finish(self, i, t, g, now_kmh):
        a = self.active.pop(i, None)
        if not a:
            return
        dt = t - a["t0"]
        if dt <= 0 or dt > MAX_SEG_S:
            return
        d = self.defs[i]
        rec = {"t": round(dt, 3), "at": time.strftime("%Y-%m-%d %H:%M:%S"), "lap": g("LapCompleted"),
               "min": None if a["min"] is None else round(a["min"], 1), "exit": round(now_kmh, 1), "off": a["off"],
               "set": a["set"], "lap_no": (g("LapCompleted", 0) or 0) + 1}
        with self.lock:
            lst = self.hist.setdefault(d["name"], [])
            lst.append(rec)
            del lst[:-KEEP]
        self._dirty = True
        self.last_done = {"name": d["name"], **rec}

    def tick(self, b):
        g = b.g
        wi = b.info("WeekendInfo", {}) or {}
        track = wi.get("TrackName") or None
        if track != self.track:
            self.save(force=True)
            self.track = track
            self.defs = load_defs(track) if track else []
            self.hist = self._load() if track else {}
            self.active, self.prev, self.in_stall_prev = {}, None, None
        if not self.defs or g("IsReplayPlaying", False):
            return
        t = g("SessionTime")
        dist = g("LapDist")
        if dist is None:
            pct = g("LapDistPct")
            dist = None if pct is None else float(pct) * b.track_len_m()
        if t is None or dist is None:
            return
        t, dist = float(t), float(dist)
        kmh = float(g("Speed", 0.0) or 0.0) * 3.6
        L = b.track_len_m()
        in_stall = bool(g("PlayerCarInPitStall", False))
        try:
            off = int(g("PlayerTrackSurface", 3)) == 0
        except (TypeError, ValueError):
            off = False
        for a in self.active.values():
            a["min"] = kmh if a["min"] is None else min(a["min"], kmh)
            a["off"] = a["off"] or off
        # leaving the pit stall starts every "pitbox" segment
        if self.in_stall_prev and not in_stall:
            for i, d in enumerate(self.defs):
                if d["from"] == "pitbox":
                    self._start(i, t, g)
        if in_stall:                       # back in the box (or reset to it): tries from the box start again
            for i, d in enumerate(self.defs):
                if d["from"] == "pitbox":
                    self.active.pop(i, None)
        self.in_stall_prev = in_stall
        if self.prev is not None:
            t0, d0 = self.prev
            step = dist - d0
            if step < -L / 2:              # crossed the start/finish line
                step += L
            if step > JUMP_M or step < -5 or t - t0 > 2.0:
                self.active = {}           # reset / tow / pause: tries in progress don't count
            elif step > 0:
                d1 = d0 + step             # unwrapped position this read
                for i, d in enumerate(self.defs):
                    for edge in ("from", "to"):
                        m = d[edge]
                        if m == "pitbox":
                            continue
                        m = float(m)
                        for mm in (m, m + L):  # the line may sit just past the wrap
                            if d0 < mm <= d1:
                                tc = t0 + (t - t0) * (mm - d0) / step
                                if edge == "from":
                                    self._start(i, tc, g)
                                elif i in self.active:
                                    self._finish(i, tc, g, kmh)
        self.prev = (t, dist)
        self.save()

    # ------------------------------------------------------------------------------------------- view
    def view(self):
        with self.lock:
            hist = {k: list(v) for k, v in self.hist.items()}
        out = []
        for d in self.defs:
            lst = hist.get(d["name"], [])
            clean = [x for x in lst if not x.get("off")]
            best = min(clean, key=lambda x: x["t"]) if clean else None
            last = lst[-1] if lst else None
            # which settings were quicker: best time per combination of TC / bias / migration (clean tries only)
            combos = {}
            for x in clean:
                s = x.get("set") or {}
                k = (s.get("tc_lat"), s.get("tc_lon"), s.get("bias"), s.get("mig"))
                c = combos.setdefault(k, {"tc_lat": k[0], "tc_lon": k[1], "bias": k[2], "mig": k[3], "n": 0, "best": None, "sum": 0.0})
                c["n"] += 1
                c["sum"] += x["t"]
                c["best"] = x["t"] if c["best"] is None else min(c["best"], x["t"])
            cl = sorted(({**c, "avg": round(c["sum"] / c["n"], 3)} for c in combos.values()), key=lambda c: c["best"])
            for c in cl:
                c.pop("sum", None)
            out.append({"name": d["name"], "from": d["from"], "to": d["to"], "n": len(lst), "best": best, "last": last,
                        "recent": lst[-12:][::-1], "by_settings": cl[:8],
                        "running": any(self.defs[i]["name"] == d["name"] for i in self.active)})
        return {"ok": bool(self.defs), "track": self.track,
                "why": None if self.defs else ("No segments for this track yet." if self.track else "Not in a session."),
                "segments": out, "last_done": self.last_done,
                "file": os.path.join(BASE, "custom_sectors.json")}
