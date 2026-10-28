"""Race memory (2026-10-24): what happened every time you drove this car at this track.

One small JSON file (%LOCALAPPDATA%\\RaceEngineer\\race_memory.json), keyed by car + track. Each session you drive
leaves one short summary: date, session type, laps, best / typical lap, fuel per lap, tyre fade, stints, pit stops,
incidents, spins and offs (and where), the corners where you usually lose time, the weather, the setup name and the
notes you said on the radio.

    record_session(summary)        store one summary
    recall(car, track, cls=None)   -> {"sessions", "aggregates", "source", "from_cars"}

When this car has never been here, recall() borrows from the same track in a car of the same class (GT3 <-> GT3,
GTP <-> GTP) and says so: source = "similar car (rough guide)".

Recorder watches the session while you drive (a few cheap reads per tick, nothing heavy) and, when the session ends,
writes the summary from a separate thread so the engine loop never waits for it.
"""
import bisect, json, os, statistics, threading, time
from datetime import datetime

DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RaceEngineer")
PATH = os.path.join(DIR, "race_memory.json")
KEEP = 60                       # sessions kept per car + track
THIS_CAR, SIMILAR, NONE = "this car", "similar car (rough guide)", "none"
_LOCK = threading.Lock()


# ---------------------------------------------------------------- car classes (for the similar-car fallback)
def car_class(car_path="", class_name=""):
    """'GT3', 'GTP', 'LMP2', 'LMP3', 'GT4', 'TCR' or '' - from DriverInfo CarClassShortName, else the car path."""
    for s in (str(class_name or ""), str(car_path or "")):
        s = s.lower().replace(" ", "").replace("-", "")
        if not s:
            continue
        if "gtp" in s or "lmdh" in s or "lmh" in s or "963" in s or "499p" in s or "vseriesr" in s or "arx06" in s or "hybridv8" in s:
            return "GTP"
        if "lmp2" in s or "p217" in s:
            return "LMP2"
        if "lmp3" in s or "ligierjsp320" in s:
            return "LMP3"
        if "gt3" in s:
            return "GT3"
        if "gt4" in s:
            return "GT4"
        if "tcr" in s:
            return "TCR"
    return ""


# ---------------------------------------------------------------- store
def _key(car, track):
    return f"{car}|{track}"


def _load():
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("combos"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"v": 1, "combos": {}}


def _save(d):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, PATH)


def record_session(summary):
    """Store one session summary (needs at least car and track). -> the stored summary, or None."""
    car, track = summary.get("car"), summary.get("track")
    if not car or not track:
        return None
    s = dict(summary)
    s.setdefault("at", time.time())
    s.setdefault("date", datetime.fromtimestamp(s["at"]).strftime("%Y-%m-%d %H:%M"))
    s["cls"] = s.get("cls") or car_class(car)
    with _LOCK:
        d = _load()
        c = d["combos"].setdefault(_key(car, track), {"car": car, "track": track, "cls": s["cls"], "sessions": []})
        c["cls"] = c.get("cls") or s["cls"]
        for k in ("car_name", "track_name"):
            if s.get(k):
                c[k] = s[k]
        c["sessions"] = [x for x in c["sessions"] if abs((x.get("at") or 0) - s["at"]) > 1][-(KEEP - 1):] + [s]
        _save(d)
    return s


def car_name(car_path):
    """The car's screen name as stored with its sessions (falls back to the path)."""
    with _LOCK:
        d = _load()
    return next((c["car_name"] for c in d["combos"].values() if c.get("car") == car_path and c.get("car_name")), car_path)


def last_combo():
    """(car, track) of the most recently stored session, or (None, None)."""
    with _LOCK:
        d = _load()
    best = None
    for c in d["combos"].values():
        for s in c.get("sessions", []):
            if best is None or (s.get("at") or 0) > (best.get("at") or 0):
                best = s
    return (best["car"], best["track"]) if best else (None, None)


def recall(car, track, cls=None):
    """Everything remembered for this car at this track (newest first). Borrows from a same-class car at
    the same track when there's nothing for this one."""
    with _LOCK:
        d = _load()
    c = d["combos"].get(_key(car, track))
    sess, source, from_cars = (list(c.get("sessions", [])) if c else []), THIS_CAR, []
    names = {}
    if c:
        names = {"car_name": c.get("car_name"), "track_name": c.get("track_name")}
    if not sess:
        cls = cls or car_class(car)
        if cls:
            for o in d["combos"].values():
                if o.get("track") == track and o.get("car") != car and (o.get("cls") or car_class(o.get("car"))) == cls and o.get("sessions"):
                    sess += o["sessions"]
                    from_cars.append(o.get("car_name") or o.get("car"))
                    names.setdefault("track_name", o.get("track_name"))
        source = SIMILAR if sess else NONE
    sess.sort(key=lambda s: -(s.get("at") or 0))
    return {"car": car, "track": track, "source": source, "from_cars": from_cars, "sessions": sess,
            "aggregates": aggregates(sess), **{k: v for k, v in names.items() if v}}


def _med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return float(statistics.median(xs)) if xs else None


def aggregates(sessions):
    """What the sessions say together: best, typical pace, fuel, tyres, pit loss, trouble corners, notes."""
    S = sessions
    if not S:
        return {"sessions": 0}
    corners = {}
    for s in S:
        for c in s.get("corners") or []:
            corners.setdefault(c["name"], []).append(c["lost"])
    trouble = sorted(({"name": k, "lost": round(sum(v) / len(v), 2), "sessions": len(v)} for k, v in corners.items()),
                     key=lambda r: (-r["lost"] * min(r["sessions"], 3)))
    spots = {}
    for s in S:
        for k in (s.get("spin_at") or []) + (s.get("off_at") or []):
            if k:
                spots[k] = spots.get(k, 0) + 1
    stints = [n for s in S for n in (s.get("stints") or []) if n and n >= 3]
    races = [s for s in S if "race" in str(s.get("session", "")).lower()]
    notes = [dict(n, date=s.get("date")) for s in S for n in (s.get("notes") or [])][:8]
    n = len(S)
    return {
        "sessions": n, "races": len(races), "laps": sum(s.get("laps") or 0 for s in S),
        "best": min([s["best"] for s in S if s.get("best")] or [None], key=lambda x: x or 1e9),
        "typical": _med([s.get("median") for s in S]),
        "fuel_lap": _med([s.get("fuel_lap") for s in S]),
        "tyre_deg": _med([s.get("tyre_deg") for s in S]),
        "pit_loss": _med([s.get("pit_loss") for s in S]),
        "stint": _med(stints),
        "tank": next((s["tank"] for s in S if s.get("tank")), None),
        "spins": round(sum(s.get("spins") or 0 for s in S) / n, 1),
        "offs": round(sum(s.get("offs") or 0 for s in S) / n, 1),
        "incidents": round(sum(s.get("incidents") or 0 for s in S) / n, 1),
        "trouble": trouble[:5],
        "hotspots": [k for k, _ in sorted(spots.items(), key=lambda kv: -kv[1])][:3],
        "setup": next((s["setup"] for s in S if s.get("setup")), None),
        "finishes": [s["race"]["pos"] for s in races if (s.get("race") or {}).get("pos")][:5],
        "track_temp": _med([(s.get("weather") or {}).get("track_temp") for s in S]),
        "notes": notes,
        "last": S[0].get("date"),
    }


def similar_model(car, track, cls=None):
    """Strategy model (strategy.py) of the same-class car with the most laps at this track. -> (model, car) or (None, None)"""
    from . import strategy as ST
    cls = cls or car_class(car)
    if not cls:
        return None, None
    try:
        with ST._LOCK:
            c = ST.db()
            rows = c.execute("SELECT car, COUNT(*) FROM laps WHERE track=? AND car<>? AND clean=1 GROUP BY car ORDER BY 2 DESC",
                             (track, car)).fetchall()
            c.close()
    except Exception:
        return None, None
    for other, _ in rows:
        if car_class(other) == cls:
            m = ST.model(other, track)
            if m.get("fuel_lap"):
                return m, other
    return None, None


# ---------------------------------------------------------------- live recorder
def pretty_corner(key):
    return key.replace("_", " ").title().replace("Nascar", "NASCAR") if key else None


class Recorder:
    """Collects one session while you drive; writes its summary (in a thread) when the session ends.

    tick(brain, strat) is called from the engine loop. Per tick it only reads a handful of values and does one
    bisect into the corner map; everything else happens once per lap or once per session."""

    def __init__(self, on_done=None, log=print):
        self.on_done = on_done or (lambda summary, debrief: None)
        self.log = log
        self.key = None
        self.cur = None
        self.last = None              # the last summary written (for the debrief)

    # -------- helpers
    @staticmethod
    def _g(b, k, d=None):
        try:
            return b.g(k, d)
        except Exception:
            return d

    def _start(self, b):
        di = b.info("DriverInfo", {}) or {}
        wk = b.info("WeekendInfo", {}) or {}
        me = next((d for d in di.get("Drivers") or [] if d.get("CarIdx") == di.get("DriverCarIdx")), {}) or {}
        try:
            tank = float(di.get("DriverCarFuelMaxLtr")) * float(di.get("DriverCarMaxFuelPct") or 1)
        except (TypeError, ValueError):
            tank = None
        marks = list(getattr(b.c, "marks", None) or []) if getattr(b, "c", None) else []
        self.cur = {
            "car": me.get("CarPath"), "car_name": me.get("CarScreenName") or me.get("CarScreenNameShort"),
            "cls": car_class(me.get("CarPath"), me.get("CarClassShortName")),
            "track": wk.get("TrackName"), "track_name": wk.get("TrackDisplayName") or wk.get("TrackName"),
            "session": b.sess_type or "", "at": time.time(), "tank": tank,
            "setup": di.get("DriverSetupName") or None, "skies": wk.get("TrackSkies") or "",
            "laps": [], "stops": [], "corner_times": {}, "lap_corners": {},
            "incidents": 0, "inc0": None, "spins": 0, "spin_at": [], "offs": 0, "off_at": [],
            "temps": [], "air": [], "wet": [], "race": None,
            "_marks": marks, "_starts": [m[0] for m in marks], "_seg": None, "_seg_t": None,
            "_lc": None, "_fuel": None, "_inc_lap": None, "_pit": None, "_pitted_lap": False, "_stint": 0,
            "_spin_said": getattr(b, "_spin_said", None), "_tl": getattr(b, "tl_count", 0), "_last_spin_t": -99.0,
        }

    def _seg_at(self, dist):
        c = self.cur
        i = bisect.bisect_right(c["_starts"], dist + 20) - 1
        if i >= 0:
            a, e, k = c["_marks"][i]
            if a - 20 <= dist <= e + 20:
                return k
        return None

    def _corner_name(self, b):
        try:
            k = b.c.nearest_behind(self._g(b, "LapDist", 0) or 0) if b.c else None
            return pretty_corner(k)
        except Exception:
            return None

    # -------- every tick
    def tick(self, b, strat=None):
        if b is None:
            if self.cur:
                self.finish("disconnected")
            self.key = None
            return
        key = (id(b), b.sess_num)
        if key != self.key:
            if self.cur:
                self.finish("session changed")
            self.key = key
            self._start(b)
        c = self.cur
        if c is None:
            return
        g = lambda k, d=None: self._g(b, k, d)
        now = (getattr(b, "clock", None) or time.time)()
        on_track = bool(g("IsOnTrack", False))
        onp = bool(g("OnPitRoad", False))
        spd = g("Speed", 0) or 0
        # ---- corner timing (one bisect)
        if c["_marks"] and on_track and not onp:
            st, dist = g("SessionTime"), g("LapDist", -1)
            if st is not None and dist is not None and dist >= 0:
                seg = self._seg_at(dist)
                if seg != c["_seg"]:
                    if c["_seg"] is not None and c["_seg_t"] is not None and 0 < st - c["_seg_t"] < 60:
                        c["lap_corners"][c["_seg"]] = st - c["_seg_t"]
                    c["_seg"], c["_seg_t"] = seg, st
        # ---- incidents, spins, offs
        inc = g("PlayerCarMyIncidentCount")
        if inc is not None and not g("IsReplayPlaying", False):
            if c["inc0"] is None:
                c["inc0"] = inc
            else:
                d = inc - c["inc0"] - c["incidents"]
                if d > 0:
                    c["incidents"] += d
                    if d == 2 and now - c["_last_spin_t"] > 5:      # loss of control without a spin call
                        c["spins"] += 1; c["spin_at"].append(self._corner_name(b)); c["_last_spin_t"] = now
        ss = getattr(b, "_spin_said", None)
        if ss is not None and ss != c["_spin_said"]:
            c["_spin_said"] = ss
            if now - c["_last_spin_t"] > 5:
                c["spins"] += 1; c["spin_at"].append(self._corner_name(b)); c["_last_spin_t"] = now
        tl = getattr(b, "tl_count", 0) or 0
        if tl > c["_tl"]:
            c["offs"] += tl - c["_tl"]; c["off_at"].append(self._corner_name(b))
        c["_tl"] = tl
        # ---- pit stops
        if onp and c["_pit"] is None:
            c["_pit"] = {"t": now, "still": 0.0, "fuel0": g("FuelLevel", 0) or 0, "lap": (g("LapCompleted", 0) or 0) + 1}
            c["_pitted_lap"] = True
        elif onp:
            if spd < 0.5:
                c["_pit"]["still"] += now - c["_pit"]["t"]
            c["_pit"]["t"] = now
        elif c["_pit"] is not None:
            p, c["_pit"] = c["_pit"], None
            if p["still"] > 1.5:
                c["stops"].append({"lap": p["lap"], "still": round(p["still"], 1),
                                   "fuel": round(max(0.0, (g("FuelLevel", 0) or 0) - p["fuel0"]), 1)})
                c["_stint"] += 1
        # ---- laps
        lc = g("LapCompleted", -1)
        if lc is not None and lc >= 0:
            if c["_lc"] is None:
                c["_lc"], c["_fuel"], c["_inc_lap"] = lc, g("FuelLevel"), c["incidents"]
            elif lc > c["_lc"]:
                c["_lc"] = lc
                self._lap(b, lc)
        # ---- race over and the car has stopped: write it now (the debrief opens from this)
        if b.is_race() and getattr(b, "finished", False) and c["race"] is None and (spd < 0.5 or not on_track):
            c["race"] = self._race_numbers(b, strat)
            self.finish("race finished", debrief=True)

    def _lap(self, b, lc):
        c = self.cur
        g = lambda k, d=None: self._g(b, k, d)
        t = g("LapLastLapTime", -1) or -1
        fuel = g("FuelLevel")
        used = (c["_fuel"] - fuel) if (c["_fuel"] is not None and fuel is not None) else None
        clean = t > 0 and not c["_pitted_lap"] and c["incidents"] == c["_inc_lap"] and not getattr(b, "caution_on", False)
        c["laps"].append({"n": lc, "t": round(t, 3) if t > 0 else None, "clean": bool(clean), "stint": c["_stint"],
                          "fuel": round(used, 3) if used and 0.05 < used < 40 else None})
        if clean:
            for k, v in c["lap_corners"].items():
                c["corner_times"].setdefault(k, []).append(v)
        c["lap_corners"] = {}
        c["_fuel"], c["_inc_lap"], c["_pitted_lap"] = fuel, c["incidents"], bool(g("OnPitRoad", False))
        for k, arr in (("TrackTempCrew", "temps"), ("AirTemp", "air"), ("TrackWetness", "wet")):
            v = g(k)
            if isinstance(v, (int, float)):
                c[arr].append(float(v))

    def _race_numbers(self, b, strat):
        """The strategist's post-race numbers (strat_live.debrief_numbers) - the same ones she says on the radio."""
        try:
            if strat is not None and getattr(strat, "b", None) is b:
                return strat.debrief_numbers(b)
        except Exception as e:
            self.log(f"[memory] race numbers: {e!r}")
        try:
            return {"pos": b.class_pos(b.me()) or None, "start_pos": getattr(b, "start_pos", None)}
        except Exception:
            return {}

    # -------- session end
    def finish(self, reason, debrief=False):
        c, self.cur = self.cur, None
        if not c or not c.get("car") or not c.get("track"):
            return
        if not c["laps"] and not c["race"]:
            return                                    # sat in the garage: nothing to remember
        snap = {k: v for k, v in c.items() if not k.startswith("_")}
        snap["reason"] = reason
        threading.Thread(target=self._write, args=(snap, debrief), daemon=True).start()

    def _write(self, snap, debrief):
        try:
            s = summarise(snap)
            record_session(s)
            self.last = s
            self.log(f"[memory] stored {s['session'] or 'session'} at {s.get('track_name')}: {s['laps']} laps")
            self.on_done(s, debrief)
        except Exception as e:
            self.log(f"[memory] couldn't store the session: {e!r}")


def summarise(c):
    """Raw recorder data -> the stored summary (runs in the writer thread)."""
    laps = c.get("laps") or []
    clean = [L["t"] for L in laps if L["clean"] and L["t"]]
    timed = [L["t"] for L in laps if L["t"]]
    fuel = [L["fuel"] for L in laps if L["clean"] and L["fuel"]]
    # stints: laps between stops
    stints, n = [], 0
    stop_laps = sorted(s["lap"] for s in c.get("stops") or [])
    first = laps[0]["n"] - 1 if laps else 0
    prev = first
    for sl in stop_laps:
        stints.append(max(0, sl - prev)); prev = sl
    if laps:
        stints.append(max(0, laps[-1]["n"] - prev))
    # tyre fade: slope of clean lap time vs lap in the longest stint (fuel burn taken out with the model's effect)
    fe, deg, model = 0.025, None, {}
    try:
        from . import strategy as ST
        model = ST.model(c["car"], c["track"]) or {}
        fe = model.get("fuel_effect", fe)
    except Exception:
        model = {}
    by_stint = {}
    for L in laps:
        if L["clean"] and L["t"]:
            by_stint.setdefault(L["stint"], []).append(L)
    if by_stint:
        run = max(by_stint.values(), key=len)
        if len(run) >= 5:
            import numpy as np
            x = np.arange(len(run), dtype=float)
            fpl = statistics.median(fuel) if fuel else 0
            y = np.array([L["t"] + fe * fpl * i for i, L in enumerate(run)])   # add back the fuel the car lost
            k = float(np.polyfit(x, y, 1)[0])
            deg = round(max(0.0, min(0.3, k)), 3)
    # per-corner time lost: your usual time in each corner vs your best in it (clean laps)
    names = []
    for k, ts in (c.get("corner_times") or {}).items():
        if len(ts) >= 3:
            lost = statistics.median(ts) - min(ts)
            if lost >= 0.02:
                names.append({"name": pretty_corner(k), "lost": round(lost, 2), "n": len(ts)})
    names.sort(key=lambda r: -r["lost"])
    # radio notes said during this session at this track (notes.py)
    nts = []
    try:
        from . import notes as N
        end = time.time()
        for r in N.for_session(c["track"], c["at"], end):
            if not r.get("car") or r.get("car") == c["car"]:
                nts.append({"lap": r.get("lap"), "corner": r.get("corner"), "text": r.get("text")})
    except Exception:
        pass
    w = lambda xs: round(statistics.median(xs), 1) if xs else None
    pit_loss = model.get("lane_loss") if "pit lane loss" in (model.get("learned") or []) else None
    return {
        "v": 1, "car": c["car"], "car_name": c.get("car_name"), "track": c["track"], "track_name": c.get("track_name"),
        "cls": c.get("cls") or car_class(c["car"]), "session": c.get("session") or "", "reason": c.get("reason"),
        "at": c["at"], "date": datetime.fromtimestamp(c["at"]).strftime("%Y-%m-%d %H:%M"),
        "laps": len(laps), "clean_laps": len(clean),
        "best": round(min(timed), 3) if timed else None,
        "median": round(statistics.median(clean), 3) if clean else None,
        "fuel_lap": round(statistics.median(fuel), 3) if fuel else None,
        "tyre_deg": deg, "stints": stints, "stops": c.get("stops") or [], "pit_loss": round(pit_loss, 1) if pit_loss else None,
        "incidents": c.get("incidents") or 0, "spins": c.get("spins") or 0, "spin_at": [x for x in c.get("spin_at") or [] if x],
        "offs": c.get("offs") or 0, "off_at": [x for x in c.get("off_at") or [] if x], "corners": names[:8],
        "weather": {"track_temp": w(c.get("temps")), "air": w(c.get("air")), "wet": max(c.get("wet") or [0]) or 0, "skies": c.get("skies") or ""},
        "setup": c.get("setup"), "tank": c.get("tank"), "notes": nts[-12:], "race": c.get("race"),
        "lap_times": [L["t"] for L in laps][-80:],
    }


def review_line(s):
    """The automatic data review after each session, in one or two sentences."""
    from .team import fmt_lap
    bits = [f"{s.get('session') or 'Session'} at {s.get('track_name') or s.get('track')}: {s['laps']} laps"]
    if s.get("best"):
        bits.append(f"best {fmt_lap(s['best'])}")
    if s.get("median") and s.get("best"):
        bits.append(f"typical {fmt_lap(s['median'])}")
    out = ", ".join(bits) + "."
    trouble = []
    if s.get("spins"):
        where = ", ".join(dict.fromkeys(s.get("spin_at") or []))
        trouble.append(f"{s['spins']} spin{'s' if s['spins'] != 1 else ''}{' (' + where + ')' if where else ''}")
    if s.get("offs"):
        where = ", ".join(dict.fromkeys(s.get("off_at") or []))
        trouble.append(f"{s['offs']} off{'s' if s['offs'] != 1 else ''}{' (' + where + ')' if where else ''}")
    if trouble:
        t = " and ".join(trouble)
        out += " " + t[:1].upper() + t[1:] + "."
    elif s["laps"] >= 3:
        out += " No spins or offs."
    if s.get("corners"):
        c = s["corners"][:2]
        out += " Most time lost: " + ", ".join(f"{x['name']} {x['lost']:+.2f} s" for x in c) + " (your usual vs your best there)."
    return out
