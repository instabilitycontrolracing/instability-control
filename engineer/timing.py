"""Timing screen and session screen data (2026-10-25, request: "a timing screen and session screen like F1 has.
Just the format of data, don't actually copy them. Viewable as a section on the iPad, a window in the engineer app on
the PC, and as a pop-out for the screen above the triples").

Everything here comes from the iRacing telemetry the engineer already reads - no outside service.

  tick(b)   ~15 times a second from the iPad server's feed, whether a page is open or not, so the sectors, stops and
            race control log are already filled in when you open the screen mid-race.
  build(b)  ~2 times a second: one row per car (class order) plus the session panel. Sent as the "timing" event.

Sectors are thirds of the lap - the same S1/S2/S3 the engineer's own sector calls and the lap analysis use, so
"fastest sector in class" on the radio is the purple box you see here. Colours: purple = best in class this
session, green = that driver's own best, yellow = slower than his best.

What the engineer works out himself (stops, laps on tyres, sector bests, where each car started, the race control
log) is saved to engineer_timing_state.json every 10 s and read back after a restart in the same session, like
race_state.py does for the engineer's memory.
"""
import json, math, os, time

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engineer_timing_state.json")

F_CHECKERED, F_WHITE, F_GREEN, F_YELLOW, F_RED, F_BLUE = 0x1, 0x2, 0x4, 0x8, 0x10, 0x20
F_YELLOW_W, F_CAUTION, F_CAUTION_W = 0x100, 0x4000, 0x8000
F_BLACK, F_DQ, F_REPAIR, F_FURLED = 0x10000, 0x20000, 0x100000, 0x80000
TS_NOT_IN_WORLD, TS_OFF = -1, 0
SECS = 3


def _f(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _abbr(name):
    """'Jane Driver' -> 'J. DRIVER'; keeps a single word as is."""
    p = [w for w in str(name or "").replace("_", " ").split() if w and w.strip(".").lower() not in ("jr", "sr", "ii", "iii", "iv")]
    if not p:
        return ""
    if len(p) == 1:
        return p[0].upper()
    last = p[-1] if not p[-1][:1].isdigit() else p[-2]
    return f"{p[0][0]}. {last}".upper()


def _hex(c):
    try:
        c = int(c, 16) if isinstance(c, str) else int(c or 0)
    except ValueError:
        c = 0
    return f"#{c:06X}" if c else "#C5A572"


def class_name(drivers):
    """iRacing sometimes sends no short class name (seen in a Le Mans replay). Name the class from its cars."""
    for d in drivers:
        n = (d.get("CarClassShortName") or "").strip()
        if n:
            return n
    from . import cars                     # 2026-10-29 (car parity E12): known cars name their class from the car table
    for d in drivers:
        c = cars.of_driver(d)
        if c is not None:
            return c["cls"] or c["cls_text"]
    t = " ".join(f"{d.get('CarPath', '')} {d.get('CarScreenName', '')}" for d in drivers).lower()
    for keys, name in ((("gtp", "lmdh", "hybrid v8", "mhybrid", "lmh", "963", "v-series.r", "arx-06"), "GTP"),
                       (("lmp2", "dallara p217", "oreca"), "LMP2"), (("lmp3",), "LMP3"),
                       (("gt3", "gtd"), "GT3"), (("gt4",), "GT4"), (("tcr",), "TCR")):
        if any(k in t for k in keys):
            return name
    return (drivers[0].get("CarScreenNameShort") or drivers[0].get("CarScreenName") or "Class") if drivers else "Class"


def flag_text(fl, sess_type="", state=None):
    """2026-10-25 (request: the iPad 'says pre-race and it has 4:22 left'): iRacing only keeps the green bit up for a
    moment, so a race with no flag out read as PRE-RACE. The session state decides: 4 = racing, 3 = formation."""
    fl = int(fl or 0)
    if fl & F_CHECKERED: return "CHECKERED", "chk"
    if fl & F_RED: return "RED FLAG", "red"
    if fl & (F_CAUTION | F_CAUTION_W): return "FULL COURSE YELLOW", "yel"
    if fl & F_WHITE: return "FINAL LAP", "wht"
    if fl & (F_YELLOW | F_YELLOW_W): return "LOCAL YELLOW", "yel"
    if fl & F_GREEN: return "GREEN", "grn"
    st = int(state) if isinstance(state, (int, float)) else None
    if st == 4: return "GREEN", "grn"
    if st == 5 or st == 6: return "CHECKERED", "chk"
    if st == 3 and "race" in (sess_type or "").lower(): return "FORMATION", ""
    if "race" in (sess_type or "").lower() and st in (None, 0, 1, 2): return "PRE-RACE", ""
    return "TRACK CLEAR", "grn"
    return "TRACK CLEAR", "grn"


class Timing:
    def __init__(self, log=print):
        self.log = log
        self.key = None
        self.reset()
        self._save_t = 0.0

    def reset(self):
        self.cars = {}       # idx -> per-car memory (see _car)
        self.cbest = {}      # class id -> [s1, s2, s3] best in class
        self.cfast = {}      # class id -> (lap time, idx, lap no) fastest lap
        self.rc = []         # race control log, newest last
        self.flags = None
        self.leader = {}     # class id -> idx
        self.off_t = {}

    # ------------------------------------------------------------------ memory
    def _car(self, i):
        c = self.cars.get(i)
        if c is None:
            c = self.cars[i] = {"p": None, "t": None, "sec": None, "t0": None, "dirty": True,
                                "cur": [None] * SECS, "prev": [None] * SECS, "pb": [None] * SECS,
                                "stops": 0, "stop_lc": None, "onp": None, "start": None, "best_lap": None,
                                "out_t": None, "pit_t0": None, "pit_last": None}
        return c

    def _key_of(self, b):
        wi = b.info("WeekendInfo", {}) or {}
        return f"{wi.get('SubSessionID', 0)}:{b.g('SessionNum', 0)}:{wi.get('TrackName', '')}"

    def _say(self, st, kind, text, cls=None):
        self.rc.append({"t": round(st or 0, 1), "k": kind, "x": text, "c": cls})
        self.rc = self.rc[-60:]

    def save(self, b, force=False):
        now = time.time()
        if not force and now - self._save_t < 10:
            return
        self._save_t = now
        keep = ("cur", "prev", "pb", "stops", "stop_lc", "start", "best_lap")
        data = {"key": self.key, "st": b.g("SessionTime", 0), "saved": now,
                "cars": {str(i): {k: c[k] for k in keep} for i, c in self.cars.items()},
                "cbest": {str(k): v for k, v in self.cbest.items()},
                "cfast": {str(k): list(v) for k, v in self.cfast.items()}, "rc": self.rc}
        try:
            tmp = PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps(data))      # 2026-10-29: C encoder (json.dump is pure Python: ~20 ms a save), same text
            os.replace(tmp, PATH)
        except OSError:
            pass

    def restore(self, b):
        try:
            d = json.load(open(PATH, encoding="utf-8"))
        except (OSError, ValueError):
            return
        if d.get("key") != self.key:
            return
        st = b.g("SessionTime", 0) or 0
        if st + 5 < (d.get("st") or 0):          # a replay rewound to before the save: start clean
            return
        for k, v in (d.get("cars") or {}).items():
            c = self._car(int(k))
            c.update(v)
        self.cbest = {int(k): v for k, v in (d.get("cbest") or {}).items()}
        self.cfast = {int(k): tuple(v) for k, v in (d.get("cfast") or {}).items()}
        self.rc = d.get("rc") or []
        self.log(f"[timing] restored {len(self.cars)} cars from the saved state")

    # ------------------------------------------------------------------ 15 Hz
    def tick(self, b):
        try:
            self._tick(b)
        except Exception as e:                  # never take the iPad feed down
            self.log(f"[timing] {e!r}")

    def _tick(self, b):
        key = self._key_of(b)
        if key != self.key:
            if self.key is not None:
                self.save(b, force=True)
            self.key = key
            self.reset()
            self.restore(b)
        st = _f(b.g("SessionTime"))
        if st is None:
            return
        drv = b.drivers()
        pct = b.g("CarIdxLapDistPct") or []
        lc = b.g("CarIdxLapCompleted") or []
        onp = b.g("CarIdxOnPitRoad") or []
        surf = b.g("CarIdxTrackSurface") or []
        cflags = b.g("CarIdxSessionFlags") or []
        last = b.g("CarIdxLastLapTime") or []
        cpos = b.g("CarIdxClassPosition") or []
        race = "race" in (b.sess_type or "").lower()
        my_cls = drv.get(b.me(), {}).get("CarClassID")

        fl = int(b.g("SessionFlags", 0) or 0)
        ft, _ = flag_text(fl, b.sess_type, b.g("SessionState"))
        if self.flags is not None and ft != self.flags and ft not in ("PRE-RACE",):
            self._say(st, "flag", ft)
        self.flags = ft

        for i, d in drv.items():
            if d.get("CarIsPaceCar") or d.get("IsSpectator"):
                continue
            p = _f(pct[i]) if i < len(pct) else None
            c = self._car(i)
            num = d.get("CarNumber", "")
            cid = d.get("CarClassID")
            sname = d.get("CarClassShortName") or ""
            on = bool(onp[i]) if i < len(onp) else False
            l = lc[i] if i < len(lc) else -1
            if p is None or p < 0:
                c["p"] = None
                continue
            # --- pit road
            if c["onp"] is not None and on != c["onp"]:
                if on:
                    c["pit_t0"] = st
                    if l is not None and l >= 1:
                        c["stops"] += 1
                    if cid == my_cls and l is not None and l >= 1:
                        self._say(st, "pit", f"#{num} {_abbr(d.get('UserName'))} pits", sname)
                else:
                    c["stop_lc"] = l
                    if c["pit_t0"] is not None:
                        c["pit_last"] = round(st - c["pit_t0"], 1)
                    if cid == my_cls and l is not None and l >= 1 and c["pit_last"]:
                        self._say(st, "pit", f"#{num} {_abbr(d.get('UserName'))} out of the pits ({c['pit_last']:.0f}s in the lane)", sname)
            c["onp"] = on
            if c["start"] is None and race and i < len(cpos) and cpos[i] and (fl & F_GREEN):
                c["start"] = int(cpos[i])
            # --- black flag / meatball
            cf = int(cflags[i]) if i < len(cflags) and cflags[i] is not None else 0
            if cf & (F_BLACK | F_REPAIR | F_DQ):
                kk = "dq" if cf & F_DQ else "black" if cf & F_BLACK else "repair"
                if c.get("pen") != kk:
                    txt = {"dq": "disqualified", "black": "black flag", "repair": "meatball flag (repairs)"}[kk]
                    self._say(st, "pen", f"#{num} {_abbr(d.get('UserName'))} {txt}", sname)
                c["pen"] = kk
            else:
                c["pen"] = None
            # --- off track (my class only, once per 20 s)
            s_ = surf[i] if i < len(surf) else None
            if s_ == TS_OFF and cid == my_cls and not on and st - self.off_t.get(i, -99) > 20:
                self.off_t[i] = st
                self._say(st, "off", f"#{num} {_abbr(d.get('UserName'))} off track", sname)
            # --- sectors
            s = min(SECS, int(p * SECS) + 1)
            if c["t"] is not None and st == c["t"]:      # same telemetry frame again (paused, or called twice)
                continue
            if c["p"] is None or c["t"] is None or st < c["t"]:
                c["p"], c["t"], c["sec"], c["t0"], c["dirty"] = p, st, s, None, True
                continue
            dp = (p - c["p"]) % 1.0
            if dp > 0.25 or s_ == TS_NOT_IN_WORLD:      # tow, reset, teleport
                c["p"], c["t"], c["sec"], c["t0"], c["dirty"] = p, st, s, None, True
                continue
            if s != c["sec"]:
                # interpolate the moment it crossed the line between the two samples
                edge = ((c["sec"]) % SECS) / SECS            # start of the next sector (0 = the line)
                part = ((edge - c["p"]) % 1.0) / dp if dp > 0 else 1.0
                tx = c["t"] + (st - c["t"]) * min(1.0, max(0.0, part))
                done = c["sec"]
                ok = s == done % SECS + 1 and c["t0"] is not None and not c["dirty"]
                if ok:
                    t = tx - c["t0"]
                    if 1.0 < t < 600:
                        self._sector(i, d, done, t, st)
                if done == SECS:                        # crossed the line: the lap just finished
                    c["prev"] = c["cur"]
                    c["cur"] = [None] * SECS
                    self._lap(i, d, b, st, last, l)
                c["sec"], c["t0"], c["dirty"] = s, tx, on
            elif on:
                c["dirty"] = True
            c["p"], c["t"] = p, st
        self.save(b)

    def _sector(self, i, d, k, t, st):
        c = self.cars[i]
        c["cur"][k - 1] = round(t, 3)
        if c["pb"][k - 1] is None or t < c["pb"][k - 1]:
            c["pb"][k - 1] = round(t, 3)
        cid = d.get("CarClassID")
        cb = self.cbest.setdefault(cid, [None] * SECS)
        if cb[k - 1] is None or t < cb[k - 1]:
            cb[k - 1] = round(t, 3)

    def _lap(self, i, d, b, st, last, l):
        t = _f(last[i]) if i < len(last) else None
        if not t or t <= 0:
            return
        cid = d.get("CarClassID")
        f = self.cfast.get(cid)
        if f is None or t < f[0] - 1e-4:
            self.cfast[cid] = (round(t, 3), i, int(l) if l is not None else 0)
            if f is not None:
                self._say(st, "fast", f"Fastest lap #{d.get('CarNumber', '')} {_abbr(d.get('UserName'))} {fmt_lap(t)}",
                          d.get("CarClassShortName"))

    # ------------------------------------------------------------------ 2 Hz
    def build(self, b):
        drv = b.drivers()
        g = b.g
        me = b.me()
        my = drv.get(me, {})
        race = "race" in (b.sess_type or "").lower()
        pct = g("CarIdxLapDistPct") or []
        lc = g("CarIdxLapCompleted") or []
        lap = g("CarIdxLap") or []
        cpos = g("CarIdxClassPosition") or []
        opos = g("CarIdxPosition") or []
        f2 = g("CarIdxF2Time") or []
        last = g("CarIdxLastLapTime") or []
        best = g("CarIdxBestLapTime") or []
        bestn = g("CarIdxBestLapNum") or []
        onp = g("CarIdxOnPitRoad") or []
        surf = g("CarIdxTrackSurface") or []
        tyre = g("CarIdxTireCompound") or []
        st = _f(g("SessionTime")) or 0

        def at(a, i, d=None):
            return a[i] if i < len(a) and a[i] is not None else d

        rows_by_cls = {}
        for i, d in drv.items():
            if d.get("CarIsPaceCar") or d.get("IsSpectator"):
                continue
            c = self.cars.get(i) or self._car(i)
            p = _f(at(pct, i))
            l = at(lc, i, -1)
            prog = (l if l is not None and l >= 0 else 0) + (p if p is not None and p >= 0 else 0)
            row = {"i": i, "num": d.get("CarNumber", ""), "name": _abbr(d.get("UserName")), "full": d.get("UserName", ""),
                   "team": d.get("TeamName", "") if d.get("TeamName") != d.get("UserName") else "",
                   "car": d.get("CarScreenNameShort") or d.get("CarScreenName", ""),
                   "cls": d.get("CarClassShortName") or "", "cid": d.get("CarClassID"), "col": _hex(d.get("CarClassColor")),
                   "ir": d.get("IRating"), "lic": d.get("LicString", ""),
                   "cpos": int(at(cpos, i, 0) or 0), "pos": int(at(opos, i, 0) or 0),
                   "lap": int(at(lap, i, 0) or 0), "lc": int(l) if l is not None else -1, "prog": prog,
                   "pct": round(p, 4) if p is not None and p >= 0 else None,
                   "last": _f(at(last, i)), "best": _f(at(best, i)), "best_lap": int(at(bestn, i, 0) or 0),
                   "f2": _f(at(f2, i)), "pit": bool(at(onp, i, False)), "out": at(surf, i, 0) == TS_NOT_IN_WORLD,
                   "off": at(surf, i, 3) == TS_OFF,
                   "stops": c["stops"], "pit_last": c.get("pit_last"),
                   "tyre": max(0, (int(l) if l is not None else 0) - (c["stop_lc"] if c["stop_lc"] is not None else 0)),
                   "cmp": at(tyre, i, None), "sec": c["sec"] if c["p"] is not None else None,
                   "cur": c["cur"], "prev": c["prev"], "pb": c["pb"], "start": c["start"], "pen": c.get("pen"),
                   "me": i == me}
            if row["last"] is not None and row["last"] <= 0: row["last"] = None
            if row["best"] is not None and row["best"] <= 0: row["best"] = None
            rows_by_cls.setdefault(row["cid"], []).append(row)

        classes = []
        my_cid = my.get("CarClassID")
        for cid, rows in rows_by_cls.items():
            cname = class_name([drv.get(r["i"], {}) for r in rows])
            for r in rows:
                r["cls"] = cname
            if race and any(r["cpos"] > 0 for r in rows):
                rows.sort(key=lambda r: (r["cpos"] <= 0, r["cpos"] if r["cpos"] > 0 else -r["prog"]))
            elif race:
                rows.sort(key=lambda r: -r["prog"])
            else:
                rows.sort(key=lambda r: (r["cpos"] <= 0 and r["best"] is None, r["cpos"] if r["cpos"] > 0 else 999,
                                         r["best"] or 9e9))
            cb = self.cbest.get(cid, [None] * SECS)
            best_lap = min((r["best"] for r in rows if r["best"]), default=None)
            lead = rows[0] if rows else None
            for n, r in enumerate(rows):
                r["cp"] = n + 1
                ahead = rows[n - 1] if n else None
                if race:
                    r["gap"] = self._gap(r, lead)
                    r["int"] = self._gap(r, ahead) if ahead else None
                else:
                    r["gap"] = (r["best"] - best_lap) if (r["best"] and best_lap and n) else None
                    r["int"] = (r["best"] - ahead["best"]) if (ahead and r["best"] and ahead["best"]) else None
                r["sc"] = [self._col(r["cur"][k], r["pb"][k], cb[k]) for k in range(SECS)]
                r["psc"] = [self._col(r["prev"][k], r["pb"][k], cb[k]) for k in range(SECS)]
                r["lcol"] = ("p" if (r["last"] and best_lap and abs(r["last"] - best_lap) < 1e-3) else
                             "g" if (r["last"] and r["best"] and abs(r["last"] - r["best"]) < 1e-3) else "")
                r["fast"] = bool(r["best"] and best_lap and abs(r["best"] - best_lap) < 1e-3)
                r["gain"] = (r["start"] - r["cp"]) if (race and r["start"]) else None
            for r in rows:
                for k in ("prog", "f2", "full"):
                    r.pop(k, None)
            # class lead change
            if race and lead and rows and lead["lc"] >= 1:
                prev = self.leader.get(cid)
                if prev is not None and prev != lead["i"]:
                    self._say(st, "lead", f"#{lead['num']} {lead['name']} takes the {lead['cls']} lead", lead["cls"])
                self.leader[cid] = lead["i"]
            fd = None
            if best_lap:                      # iRacing's own best laps are the truth; our log only feeds race control
                rr = next(r for r in rows if r["best"] == best_lap)
                fd = {"t": best_lap, "num": rr["num"], "name": rr["name"], "lap": rr["best_lap"], "i": rr["i"]}
            classes.append({"cid": cid, "name": rows[0]["cls"] if rows else "", "col": rows[0]["col"] if rows else "#C5A572",
                            "mine": cid == my_cid, "n": len(rows), "best_sec": cb, "fast": fd, "rows": rows,
                            "est": _f(drv.get(rows[0]["i"], {}).get("CarClassEstLapTime")) if rows else None})
        # my class first, then the fastest class
        classes.sort(key=lambda c: (not c["mine"], c["est"] or 999))
        return {"session": self._session(b, st), "classes": classes, "rc": self.rc[-40:], "me": me,
                "sectors": SECS, "race": race, "t": round(time.time(), 2)}

    @staticmethod
    def _gap(r, other):
        if other is None or other is r:
            return None
        dl = other.get("prog", 0) - r.get("prog", 0)
        if dl >= 1.0:
            return f"+{int(dl)} LAP" + ("S" if int(dl) > 1 else "")
        a, b = r.get("f2"), other.get("f2")
        if a is not None and b is not None and a > 0 and a >= b:
            return round(a - b, 3)
        return None

    @staticmethod
    def _col(t, pb, cb):
        if t is None:
            return ""
        if cb is not None and t <= cb + 1e-4:
            return "p"
        if pb is not None and t <= pb + 1e-4:
            return "g"
        return "y"

    def _session(self, b, st):
        g = b.g
        wi = b.info("WeekendInfo", {}) or {}
        s = b.session() or {}
        fl = int(g("SessionFlags", 0) or 0)
        ft, fc = flag_text(fl, b.sess_type, b.g("SessionState"))
        tl = _f(g("SessionTimeRemain"))
        if tl is not None and (tl < 0 or tl > 1e6):
            tl = None
        lr = g("SessionLapsRemainEx")
        try:
            lr = int(lr) if lr is not None and 0 <= int(lr) < 30000 else None
        except (TypeError, ValueError):
            lr = None
        laps_total = s.get("SessionLaps")
        try:
            laps_total = int(laps_total)
        except (TypeError, ValueError):
            laps_total = None
        ld = g("CarIdxLap") or []
        cp = g("CarIdxClassPosition") or []
        my_cls = b.drivers().get(b.me(), {}).get("CarClassID")
        lead_lap = None
        for i, d in b.drivers().items():
            if d.get("CarClassID") == my_cls and i < len(cp) and cp[i] == 1 and i < len(ld):
                lead_lap = ld[i]
        wind = _f(g("WindVel"))
        wdir = _f(g("WindDir"))
        tod = _f(g("SessionTimeOfDay"))
        sky = {0: "Clear", 1: "Partly cloudy", 2: "Mostly cloudy", 3: "Overcast"}.get(g("Skies"), "")
        return {"type": b.sess_type or s.get("SessionType", ""), "name": s.get("SessionName", ""),
                "track": wi.get("TrackDisplayName", ""), "cfg": wi.get("TrackConfigName", ""), "city": wi.get("TrackCity", ""),
                "len": wi.get("TrackLength", ""), "series": wi.get("SeriesName", "") or "",
                "time_left": tl, "laps_left": lr, "laps_total": laps_total, "lead_lap": lead_lap,
                "flag": ft, "fcol": fc, "st": st,
                "air": _f(g("AirTemp")), "track_t": _f(g("TrackTempCrew") if g("TrackTempCrew") is not None else g("TrackTemp")),
                "wet": g("TrackWetness"), "rain": _f(g("Precipitation")), "hum": _f(g("RelativeHumidity")),
                "wind": wind, "wdir": round(math.degrees(wdir)) % 360 if wdir is not None else None, "sky": sky,
                "tod": tod, "fuel_metric": bool(b.metric()) if hasattr(b, "metric") else False,
                "inc": g("PlayerCarMyIncidentCount"), "inc_lim": b.incident_limit() if hasattr(b, "incident_limit") else None}


def fmt_lap(t):
    if not t:
        return "–"
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:06.3f}" if m else f"{s:.3f}"
