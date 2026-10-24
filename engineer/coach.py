"""The driving coach: your lap against a fast reference lap, corner by corner, ranked by time lost.

Reference lap sources (no Garage 61 token needed for the last three):
  * Garage 61 lap (API, see garage61.py)  * a CSV export of one lap (Garage 61 format or similar)
  * any iRacing .ibt file (its best lap, or a chosen lap)  * any reference the Analysis tab already offers

Every judgement comes from the fixed coaching bank (BANK below): a finding code maps to a plain-English
title, a "why" and a drill. Rules only fill in the numbers. Nothing is generated.

Light: runs on demand (Analysis tab > Coach), never per tick. Uses telemetry.corner_metrics for the basics.
Output is a plain JSON-safe dict (coach_session / coach_traces) and the last one is saved to
CACHE_DIR/coach_last.json for the team meeting room (last_summary()).
"""
import csv, io, json, math, os, re, time

import numpy as np

from .telemetry import CACHE_DIR, Session, corner_metrics, delta

VERSION = 1
LAST_FILE = os.path.join(CACHE_DIR, "coach_last.json")

# ---------------------------------------------------------------- the coaching bank (fixed)
# phase: entry / mid / exit / lap. consequence=True: usually a result of something else in the corner.
BANK = {
    "BRAKE_EARLY": dict(phase="entry", title="Braking too early",
        why="You are on the brakes before you need to be, so you spend extra time slow. The reference brakes later and still makes the corner.",
        drill="Move your brake marker about 5 m later each lap until you start missing the apex, then go back one step. Keep the same pedal pressure."),
    "BRAKE_LATE": dict(phase="entry", title="Braking too late (overshooting)",
        why="You brake later than the reference but arrive too fast, so you scrub speed in the middle of the corner and the exit suffers.",
        drill="Brake at the reference point and concentrate on rolling more speed to the apex instead of diving deep."),
    "BRAKE_PEAK_LOW": dict(phase="entry", title="Not enough brake pressure at the start",
        why="The car slows best at the start of the zone, while it is fast and the downforce is high. A soft first press wastes that.",
        drill="Press firmly in the first tenth of a second, close to the peak you need, then bleed off. On one corner: hard press, count 'one', start releasing."),
    "BRAKE_SLOW_BUILD": dict(phase="entry", title="Brake pressure builds too slowly",
        why="Reaching peak pressure late means the first part of the braking zone is wasted.",
        drill="Get to peak pressure in about 0.2 s. Think 'stamp, then squeeze off', not 'squeeze on'."),
    "BRAKE_RELEASE_ABRUPT": dict(phase="entry", title="Brake release too sudden",
        why="Dropping the brake all at once unloads the front tyres just when you need them to turn, so the car pushes wide and you have to wait for it.",
        drill="Release over about a second while you start turning: let the pedal come up as the steering goes in, like a dimmer, not a switch."),
    "BRAKE_NO_TRAIL": dict(phase="entry", title="No trail braking",
        why="You are off the brake before you turn in. A little brake while turning keeps weight on the front tyres and helps the car rotate.",
        drill="Keep 10 to 30% brake as you turn in and fade it to zero by the apex. Start on a slow corner."),
    "BRAKE_DRAG": dict(phase="entry", title="Brake held too long",
        why="You are still on the brake after the point where the reference is fully off, so you scrub speed you need at the apex.",
        drill="Pick a marker at the reference brake-off point and be completely off the pedal by it."),
    "ABS_HEAVY": dict(phase="entry", title="Leaning on ABS",
        why="Long ABS activation means the tyres are past their best grip: you stop less well and heat the tyres.",
        drill="Lower your peak pressure slightly so ABS only flickers at the start of the zone."),
    "EARLY_LIFT": dict(phase="entry", title="Lifting before the brake zone",
        why="You come off the throttle well before you brake and coast at high speed. That costs a lot of time for nothing.",
        drill="Stay flat until the brake point, then go straight from throttle to brake in one move."),
    "TURNIN_EARLY": dict(phase="entry", title="Turning in too early",
        why="An early turn-in points the car at the apex too soon, so you run out of road on exit and have to wait for the throttle.",
        drill="Wait for the reference turn-in point. Say 'wait' to yourself before you turn."),
    "TURNIN_LATE": dict(phase="entry", title="Turning in late",
        why="A late turn-in makes the corner tighter than it needs to be, so you must go slower in the middle.",
        drill="Start turning a few metres earlier, with a smoother, smaller first input."),
    "APEX_EARLY": dict(phase="mid", title="Apex too early",
        why="Your slowest point comes before the reference's, which usually means a compromised exit.",
        drill="Look further into the corner and be slowest a little later; get the car turned before you go to power."),
    "APEX_LATE": dict(phase="mid", title="Apex too late",
        why="You are slowest after the reference's apex, usually from braking too deep or rolling in too long.",
        drill="Come off the brake a little earlier so the car is rotated and slowest at the reference apex."),
    "MIN_SPEED_LOW": dict(phase="mid", title="Too slow in the middle",
        why="Your minimum speed is lower than the reference. The car has more grip here than you are using.",
        drill="Same brake point, a little less or a little shorter on the pedal: carry about 2 km/h more each lap until it starts to slide, then keep the last good one."),
    "COASTING": dict(phase="mid", title="Coasting between brake and throttle",
        why="Neither pedal is working: you are not braking on purpose and not accelerating. The reference links brake and throttle.",
        drill="Trail the brake a bit longer or pick up a light throttle sooner, so one pedal is always doing something."),
    "THROTTLE_LATE": dict(phase="exit", title="Throttle pickup late",
        why="You start accelerating later than the reference, and that loss carries all the way down the next straight.",
        drill="Get back to a light, steady throttle as soon as the car is rotated, and hold it."),
    "THROTTLE_RAMP_SLOW": dict(phase="exit", title="Too slow to full throttle",
        why="You reach full throttle later on exit. Every metre of part throttle on exit costs speed on the whole straight.",
        drill="Once you start opening, unwind the steering and keep squeezing: the less steering lock, the more throttle."),
    "THROTTLE_HESITATION": dict(phase="exit", title="Throttle hesitations on exit",
        why="You go back and forth on the throttle on exit. Each lift unsettles the car and costs drive.",
        drill="Open in one smooth squeeze. If you have to lift, you opened too early or with too much lock: open a touch later and don't stop."),
    "NEVER_FULL": dict(phase="exit", title="Never full throttle on exit",
        why="The reference gets to full throttle on this exit; you don't.",
        drill="Straighten the wheel earlier on exit so you can commit to full throttle."),
    "GEAR_DIFF": dict(phase="mid", title="Different gear in the corner",
        why="You use a different gear from the reference. The wrong gear puts the engine outside its strong rev range for the exit.",
        drill="Try the reference gear for three laps and compare the exit speed."),
    "SHIFT_EARLY": dict(phase="exit", title="Upshifting early",
        why="Shifting before the engine's best power means less push on the straight.",
        drill="Hold each gear until the shift lights (about the reference RPM shown)."),
    "SHIFT_LATE": dict(phase="exit", title="Upshifting late",
        why="Holding the gear past the shift point keeps you on the limiter, where the engine stops pulling.",
        drill="Shift on the first shift light, at about the reference RPM shown."),
    "STEER_CORRECTIONS": dict(phase="mid", title="Steering corrections",
        why="Lots of small corrections mean the car is moving around and you are scrubbing speed. Smooth hands keep the tyres working.",
        drill="One input in, hold, one input out. If the car needs catching, look at entry speed and brake release first."),
    "LINE_WIDE_APEX": dict(phase="mid", title="Missing the apex (wide)",
        why="You are further from the inside at the apex than the reference, so your corner is longer and tighter.",
        drill="Pick a point on the inside kerb and touch it; turn in a touch later if you can't reach it."),
    "LINE_TIGHT_APEX": dict(phase="mid", title="Pinching the apex",
        why="You are tighter at the apex than the reference, which closes the exit and delays the throttle.",
        drill="Turn in a touch later and use the width on exit; the apex is a point to pass, not to dive at."),
    "LINE_RADIUS_TIGHT": dict(phase="mid", title="Tighter line than the reference (estimated)",
        why="From your speed and cornering force, your path through the middle is tighter than the reference's. A tighter arc forces a lower speed.",
        drill="Use all the track width: wide on entry, kiss the apex, let it run wide on exit."),
    "EXIT_SLOW": dict(phase="exit", title="Slower on exit", consequence=True,
        why="Exit speed sets your speed for the whole next straight. This usually follows from the other items here.",
        drill="Fix the first item for this corner, then aim for an earlier, straighter exit."),
    "INCONSISTENT_BRAKE": dict(phase="lap", title="Brake point changes lap to lap",
        why="Your brake point moves around from lap to lap. It is hard to improve something that keeps changing.",
        drill="Pick one fixed marker (a board, a kerb, a shadow) and brake exactly there for five laps before moving it."),
    "INCONSISTENT_SPEED": dict(phase="lap", title="Corner speed changes lap to lap",
        why="Your minimum speed here varies a lot between laps, so the corner isn't settled yet.",
        drill="Do five laps aiming for the same brake point and the same release, then change one thing at a time."),
}
CONSEQUENCE_CODES = {"MIN_SPEED_LOW", "EXIT_SLOW", "APEX_LATE"}   # demoted when a cause is found in the same corner


# ---------------------------------------------------------------- reference laps
class RefLap:
    """A reference lap trace on the 1 m grid. Works as a reference 'session' for analysis.compare(): .trace(n)."""
    def __init__(self, tr, label, source, meta=None):
        self._tr, self.label, self.source, self.meta = tr, label, source, dict(meta or {})
        self.time = float(tr["t"][-1])
        self.path = None
        self.track_len = float(tr["d"][-1])

    def trace(self, n=None, step=1.0):
        return self._tr

    @property
    def has_position(self):
        return _has_pos(self._tr)

    def info(self):
        return _clean({"label": self.label, "source": self.source, "time": round(self.time, 3), "position": self.has_position,
                       **{k: v for k, v in self.meta.items() if isinstance(v, (str, int, float, bool, np.generic)) or v is None}})


def _has_pos(tr):
    return bool("Lat" in tr and "Lon" in tr and np.nanmax(np.abs(tr["Lat"])) > 1e-6 and np.nanstd(tr["Lat"]) > 1e-7)


_G61_NAME = re.compile(r"^Garage 61 - (?P<driver>.+?) - (?P<car>.+?) - (?P<track>.+?) - (?P<t>\d+[.:]\d\d[.:]\d{3})(?: - .*)?$")


def csv_name_meta(file_name):
    """'Garage 61 - Driver - Car - Track - 01.55.992 - id.csv' -> {driver, car, track, lap_time}."""
    base = os.path.splitext(os.path.basename(file_name or ""))[0]
    m = _G61_NAME.match(base)
    if not m:
        return {}
    mm, ss, ms = re.split(r"[.:]", m.group("t"))
    return {"driver": m.group("driver"), "car": m.group("car"), "track": m.group("track"),
            "lap_time": int(mm) * 60 + int(ss) + int(ms) / 1000.0, "garage61": True}


_COLS = {  # our channel <- accepted CSV headers (lower case)
    "Speed": ("speed", "speed (m/s)", "speed_ms"), "kmh_in": ("speed (km/h)", "speed_kmh", "kmh"),
    "LapDistPct": ("lapdistpct",), "LapDist": ("lapdist", "distance", "lapdist (m)"),
    "Throttle": ("throttle",), "Brake": ("brake",), "Gear": ("gear",), "RPM": ("rpm",),
    "SteeringWheelAngle": ("steeringwheelangle", "steering", "steer"), "LatAccel": ("lataccel",), "LongAccel": ("longaccel",),
    "YawRate": ("yawrate",), "Lat": ("lat",), "Lon": ("lon",), "BrakeABSactive": ("absactive", "brakeabsactive"),
    "Time": ("time", "sessiontime", "lapcurrentlaptime", "time (s)"),
}


def _num(s):
    s = (s or "").strip()
    if not s:
        return np.nan
    low = s.lower()
    if low in ("true", "false"):
        return 1.0 if low == "true" else 0.0
    try:
        return float(s)
    except ValueError:
        return np.nan


def parse_csv(text, track_len=None, lap_time=None, hz=60.0):
    """One lap of telemetry as CSV -> trace on a 1 m grid (same keys as Session.trace). Raises ValueError."""
    text = text.lstrip("﻿")
    rd = csv.reader(io.StringIO(text))
    try:
        head = [h.strip().lower() for h in next(rd)]
    except StopIteration:
        raise ValueError("The CSV file is empty.")
    idx = {}
    for ch, names in _COLS.items():
        for n in names:
            if n in head:
                idx[ch] = head.index(n); break
    has_speed = "Speed" in idx or "kmh_in" in idx
    if not has_speed or "Throttle" not in idx or "Brake" not in idx or not ("LapDistPct" in idx or "LapDist" in idx):
        raise ValueError("This CSV doesn't look like lap telemetry: it needs Speed, Throttle, Brake and LapDistPct (or LapDist) columns.")
    rows = [r for r in rd if r]
    cols = {ch: np.array([_num(r[i]) if i < len(r) else np.nan for r in rows]) for ch, i in idx.items()}
    n = len(rows)
    if n < 300:
        raise ValueError("The CSV is too short to be a full lap.")
    # keep the longest run between start/finish wraps (exports often carry a sample of the next lap)
    key = cols.get("LapDistPct") if "LapDistPct" in cols else cols["LapDist"]
    k = np.nan_to_num(key, nan=-1)
    wraps = np.flatnonzero(np.diff(k) < -0.5 * np.nanmax(k)) + 1
    b = [0] + list(wraps) + [n]
    a0, a1 = max(zip(b[:-1], b[1:]), key=lambda ab: ab[1] - ab[0])
    cols = {c: v[a0:a1] for c, v in cols.items()}
    n = a1 - a0
    # forward-fill channels written at a lower rate (empty cells)
    for c, v in cols.items():
        if np.isnan(v).any():
            ok = ~np.isnan(v)
            if not ok.any():
                continue
            fi = np.maximum.accumulate(np.where(ok, np.arange(len(v)), 0))
            v = v[fi]
            first = int(np.argmax(ok))
            v[:first] = v[first]
            cols[c] = v
    spd = cols["Speed"] if "Speed" in cols else cols["kmh_in"] / 3.6
    if "Speed" in cols and np.nanmax(spd) > 110:     # someone exported km/h under "Speed"
        spd = spd / 3.6
    spd = np.clip(spd, 0.5, None)
    for c in ("Throttle", "Brake"):
        if np.nanmax(cols[c]) > 1.5:
            cols[c] = cols[c] / 100.0
        cols[c] = np.clip(cols[c], 0, 1)
    # time
    if "Time" in cols and np.all(np.diff(cols["Time"]) >= 0) and cols["Time"][-1] - cols["Time"][0] > 10:
        t = cols["Time"] - cols["Time"][0]
    else:
        rate = (n - 1) / lap_time if lap_time else hz
        t = np.arange(n) / rate
    # distance
    if "LapDist" in cols and np.nanmax(cols["LapDist"]) > 100:
        dist = cols["LapDist"]
        L = track_len or float(np.nanmax(dist))
    else:
        pct = cols["LapDistPct"]
        if track_len:
            L = float(track_len)
        else:                                            # no track length: integrate speed
            L = float(np.sum(spd[:-1] * np.diff(t)))
        dist = pct * L
    dist = np.maximum.accumulate(np.clip(np.nan_to_num(dist), 0, None))
    keep = np.concatenate([[True], np.diff(dist) > 1e-4])
    dist, t = dist[keep], t[keep]
    grid = np.arange(0, min(L, dist[-1]), 1.0)
    tr = {"d": grid, "t": np.interp(grid, dist, t - t[0])}
    tr["Speed"] = np.interp(grid, dist, spd[keep])
    for c in ("Throttle", "Brake", "Gear", "RPM", "SteeringWheelAngle", "LatAccel", "LongAccel", "YawRate", "Lat", "Lon", "BrakeABSactive"):
        if c in cols:
            v = np.nan_to_num(cols[c][keep])
            tr[c] = np.interp(grid, dist, v)
    if "Gear" not in tr:
        tr["Gear"] = np.zeros_like(grid)
    if "SteeringWheelAngle" not in tr:
        tr["SteeringWheelAngle"] = np.zeros_like(grid)
    tr["kmh"] = tr["Speed"] * 3.6
    return tr


def ref_from_csv(path=None, text=None, track_len=None, label=None, meta=None):
    meta = dict(meta or {})
    if path:
        meta.update(csv_name_meta(path))
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    tr = parse_csv(text, track_len=track_len, lap_time=meta.get("lap_time"))
    who = meta.get("driver")
    lbl = label or ("Garage 61 · " + who if meta.get("garage61") and who else
                    os.path.splitext(os.path.basename(path))[0] if path else "CSV lap")
    ref = RefLap(tr, lbl, "csv", meta)
    if meta.get("lap_time"):
        ref.time = float(meta["lap_time"])
    return ref


def ref_from_ibt(path, lap_n=None, landmarks=None):
    """-> (RefLap, Session). Uses the file's best lap unless lap_n is given."""
    s = Session(path, landmarks=landmarks)
    n = lap_n or (s.best and s.best["n"])
    if not n:
        raise ValueError("That .ibt file has no complete lap.")
    L = s.lap(n)
    tr = s.trace(n)
    who = ""
    try:
        di = s.info.get("DriverInfo", {}) or {}
        me = next((x for x in di.get("Drivers", []) or [] if x.get("CarIdx") == di.get("DriverCarIdx")), {})
        who = me.get("UserName") or ""
    except Exception:
        pass
    ref = RefLap(tr, f".ibt · {os.path.splitext(os.path.basename(path))[0][:40]} · lap {n}", "ibt",
                 {"track": s.track_name, "car": s.car, "car_path": s.car_path, "driver": who, "lap": n, "lap_time": L["time"]})
    ref.time = float(L["time"])
    return ref, s


# ---------------------------------------------------------------- measuring
def _at(d, x):
    return int(min(len(d) - 1, max(0, np.searchsorted(d, x))))


def _smooth(x, k):
    if k < 2 or len(x) < k:
        return x
    return np.convolve(x, np.ones(k) / k, mode="same")


def extra_metrics(tr, m, c0, c1):
    """What corner_metrics doesn't measure: brake shape, turn-in, trail, lift, throttle shape, shifts, steering noise."""
    d, t = tr["d"], tr["t"]
    brk, thr, st, v = tr["Brake"], tr["Throttle"], tr["SteeringWheelAngle"], tr["Speed"]
    apex = _at(d, m["apex_d"])
    x = {}
    # steering: turn-in = first time the wheel passes 25% of this corner's peak lock on the way in
    w0, w1 = _at(d, c0 - 60), _at(d, c1 + 60)
    sabs = np.abs(st - np.median(st))
    smax = float(sabs[w0:w1].max()) if w1 > w0 else 0.0
    s0 = _at(d, (m.get("brake_d") or c0 - 150) - 20)
    ti = None
    if smax > 0.02:
        hit = np.flatnonzero(sabs[s0:apex + 1] > 0.25 * smax)
        ti = s0 + int(hit[0]) if len(hit) else None
    x["turnin_d"] = float(d[ti]) if ti is not None else None
    # brake shape
    if m.get("brake_d") is not None:
        b0 = _at(d, m["brake_d"])
        hi = _at(d, m["apex_d"] + 60)
        seg = brk[b0:hi + 1]
        pk = int(np.argmax(seg)); peak = float(seg[pk])
        reach = np.flatnonzero(seg[:pk + 1] >= 0.9 * peak)
        x["t_to_peak"] = float(t[b0 + int(reach[0])] - t[b0]) if len(reach) else 0.0
        after = seg[pk:]
        held = np.flatnonzero(after >= 0.8 * peak)
        ri = pk + (int(held[-1]) if len(held) else 0)
        off = np.flatnonzero(seg[ri:] < 0.05)
        bo = ri + (int(off[0]) if len(off) else len(seg[ri:]) - 1)
        x["release_s"] = float(t[b0 + bo] - t[b0 + ri])
        x["brake_off_d"] = float(d[b0 + bo])
        x["brake_at_turnin"] = float(brk[ti]) if ti is not None else None
        if ti is not None and smax > 0.02:
            sl = slice(ti, max(ti + 1, apex))
            x["trail_m"] = float(((brk[sl] > 0.05) & (sabs[sl] > 0.25 * smax)).sum() * (d[1] - d[0]))
        else:
            x["trail_m"] = 0.0
        # lift before the brake zone: from the last full throttle to the brake point
        j0 = _at(d, m["brake_d"] - 400)
        ft = np.flatnonzero(thr[j0:b0] > 0.9)
        x["lift_m"] = float(d[b0] - d[j0 + int(ft[-1])]) if len(ft) else None
        x["min_gear"] = int(round(float(tr["Gear"][b0:apex + 30].min())))
    # throttle shape on exit
    if m.get("throttle_on_d") is not None:
        a = _at(d, m["throttle_on_d"])
        z = _at(d, m["full_throttle_d"]) if m.get("full_throttle_d") else _at(d, c1 + 150)
        x["ramp_s"] = float(t[z] - t[a])
        seg = thr[a:z + 1]
        dips, low = 0, False
        run = np.maximum.accumulate(seg) if len(seg) else seg
        for i in range(len(seg)):
            drop = run[i] - seg[i]
            if not low and drop > 0.12:
                dips += 1; low = True
            elif low and drop < 0.04:
                low = False
        x["thr_dips"] = dips
    # upshifts on exit
    if "RPM" in tr:
        e0, e1 = apex, _at(d, c1 + 260)
        g = np.round(tr["Gear"][e0:e1 + 1])
        ups = np.flatnonzero(np.diff(g) > 0.5)
        if len(ups):
            rpm = tr["RPM"][e0:e1 + 1]
            x["shift_rpm"] = float(np.mean([rpm[max(0, i - 2):i + 1].max() for i in ups]))
            x["shift_n"] = int(len(ups))
    # steering noise: what's left after smoothing, through the corner
    if ti is not None:
        sl = slice(ti, _at(d, c1 + 40))
        if sl.stop - sl.start > 30:
            s = st[sl]
            x["steer_noise"] = float(np.std(s - _smooth(s, 21)) / max(0.05, smax))
    # estimated arc radius at the apex from speed and lateral g
    if "LatAccel" in tr:
        sl = slice(_at(d, m["apex_d"] - 10), _at(d, m["apex_d"] + 10) + 1)
        la = float(np.median(np.abs(tr["LatAccel"][sl])))
        if la > 3:
            x["radius_m"] = float(np.median(v[sl]) ** 2 / la)
    return x


def _xy(tr, lat0, lon0):
    R = 6371000.0
    x = (tr["Lon"] - lon0) * math.cos(math.radians(lat0)) * math.pi / 180 * R
    y = (tr["Lat"] - lat0) * math.pi / 180 * R
    return x, y


def line_offsets(trM, trR, m_ref, c0, c1):
    """Signed distance of your path from the reference's at turn-in, apex and exit (+ = towards the inside), metres."""
    if not (_has_pos(trM) and _has_pos(trR)):
        return None
    lat0, lon0 = float(np.mean(trR["Lat"])), float(np.mean(trR["Lon"]))
    xr, yr = _xy(trR, lat0, lon0)
    xm, ym = _xy(trM, lat0, lon0)
    d = trR["d"]
    out = {}
    ia = _at(d, m_ref["apex_d"])
    # which way the corner turns (from the reference path's curvature at the apex)
    j0, j1 = max(1, ia - 15), min(len(d) - 2, ia + 15)
    h0 = math.atan2(yr[j0 + 1] - yr[j0 - 1], xr[j0 + 1] - xr[j0 - 1])
    h1 = math.atan2(yr[j1 + 1] - yr[j1 - 1], xr[j1 + 1] - xr[j1 - 1])
    turn = math.copysign(1, (h1 - h0 + math.pi) % (2 * math.pi) - math.pi)
    for name, at in (("entry", m_ref.get("brake_d") or c0), ("apex", m_ref["apex_d"]), ("exit", c1 + 40)):
        i = _at(d, at)
        if i < 1 or i >= len(d) - 1:
            continue
        hx, hy = xr[i + 1] - xr[i - 1], yr[i + 1] - yr[i - 1]
        hn = math.hypot(hx, hy) or 1
        lo, hi = max(0, i - 40), min(len(xm), i + 40)
        k = lo + int(np.argmin((xm[lo:hi] - xr[i]) ** 2 + (ym[lo:hi] - yr[i]) ** 2))
        left = (hx * (ym[k] - yr[i]) - hy * (xm[k] - xr[i])) / hn       # + = left of the reference
        out[name] = round(float(left * turn), 2)                          # + = inside of the corner
    return out


# ---------------------------------------------------------------- the rules
def _f(code, sev, detail, **kw):
    b = BANK[code]
    return dict(code=code, sev=float(sev), detail=detail, title=b["title"], why=b["why"], drill=b["drill"],
                phase=b["phase"], consequence=bool(b.get("consequence") or code in CONSEQUENCE_CODES), **kw)


def corner_findings(m, r, xm, xr, line=None):
    """m/r = corner_metrics (you / reference), xm/xr = extra_metrics. -> list of findings (unsorted)."""
    F = []
    # --- braking point
    if m.get("brake_d") is not None and r.get("brake_d") is not None:
        early = r["brake_d"] - m["brake_d"]
        if early > 6:
            F.append(_f("BRAKE_EARLY", early / 8, f"You brake {early:.0f} m earlier ({m['brake_d']:.0f} m vs {r['brake_d']:.0f} m)."))
        elif early < -6 and m["min_kmh"] < r["min_kmh"] - 2:
            F.append(_f("BRAKE_LATE", -early / 8, f"You brake {-early:.0f} m later but are {r['min_kmh'] - m['min_kmh']:.0f} km/h slower at the apex."))
        # pressure
        if r.get("peak_brake", 0) > 20 and m.get("peak_brake", 0) < r["peak_brake"] - 8:
            F.append(_f("BRAKE_PEAK_LOW", (r["peak_brake"] - m["peak_brake"]) / 10, f"Peak brake {m['peak_brake']:.0f}% vs {r['peak_brake']:.0f}%."))
        if xm.get("t_to_peak") is not None and xr.get("t_to_peak") is not None and xm["t_to_peak"] > xr["t_to_peak"] + 0.15:
            F.append(_f("BRAKE_SLOW_BUILD", (xm["t_to_peak"] - xr["t_to_peak"]) / 0.15, f"{xm['t_to_peak']:.2f} s to peak pressure vs {xr['t_to_peak']:.2f} s."))
        # release
        rs_m, rs_r = xm.get("release_s"), xr.get("release_s")
        if rs_m is not None and rs_r is not None and rs_r > 0.4 and rs_m < 0.5 * rs_r and rs_m < 0.45:
            F.append(_f("BRAKE_RELEASE_ABRUPT", 1.2 + (rs_r - rs_m) / 0.4, f"You release in {rs_m:.2f} s; the reference takes {rs_r:.2f} s."))
        trail_r, trail_m = xr.get("trail_m") or 0, xm.get("trail_m") or 0
        if trail_r > 12 and trail_m < 0.3 * trail_r and not any(f["code"] == "BRAKE_RELEASE_ABRUPT" for f in F):
            F.append(_f("BRAKE_NO_TRAIL", trail_r / 20, f"Brake while turning: {trail_m:.0f} m vs the reference's {trail_r:.0f} m."))
        if xm.get("brake_off_d") is not None and xr.get("brake_off_d") is not None:
            late_off = xm["brake_off_d"] - xr["brake_off_d"]
            if late_off > 12 and m["min_kmh"] < r["min_kmh"] - 1.5:
                F.append(_f("BRAKE_DRAG", late_off / 12, f"Fully off the brake at {xm['brake_off_d']:.0f} m vs {xr['brake_off_d']:.0f} m."))
        if m.get("abs_pct", 0) > max(25, r.get("abs_pct", 0) + 15):
            F.append(_f("ABS_HEAVY", (m["abs_pct"] - r.get("abs_pct", 0)) / 20, f"ABS on for {m['abs_pct']:.0f}% of the braking (reference {r.get('abs_pct', 0):.0f}%)."))
        lm, lr = xm.get("lift_m"), xr.get("lift_m")
        if lm is not None and lr is not None and lm - lr > 15:
            F.append(_f("EARLY_LIFT", (lm - lr) / 12, f"Off the throttle {lm:.0f} m before braking (reference {lr:.0f} m)."))
    elif m.get("brake_d") is None and r.get("brake_d") is not None:
        pass   # you didn't brake where the reference did: the speed rules below cover it
    # --- turn-in and apex
    if xm.get("turnin_d") is not None and xr.get("turnin_d") is not None:
        dti = xm["turnin_d"] - xr["turnin_d"]
        if dti < -10:
            F.append(_f("TURNIN_EARLY", -dti / 15, f"You turn in {-dti:.0f} m earlier ({xm['turnin_d']:.0f} m vs {xr['turnin_d']:.0f} m)."))
        elif dti > 10:
            F.append(_f("TURNIN_LATE", dti / 15, f"You turn in {dti:.0f} m later ({xm['turnin_d']:.0f} m vs {xr['turnin_d']:.0f} m)."))
    da = m["apex_d"] - r["apex_d"]
    if da < -12:
        F.append(_f("APEX_EARLY", -da / 18, f"Slowest point {-da:.0f} m before the reference's."))
    elif da > 12:
        F.append(_f("APEX_LATE", da / 18, f"Slowest point {da:.0f} m after the reference's."))
    dv = r["min_kmh"] - m["min_kmh"]
    if dv > 2.5:
        F.append(_f("MIN_SPEED_LOW", dv / 2.5, f"Minimum {m['min_kmh']:.0f} km/h vs {r['min_kmh']:.0f} km/h."))
    # --- coasting
    dc = m.get("coast_m", 0) - r.get("coast_m", 0)
    thr_late = (m["throttle_on_d"] - r["throttle_on_d"]) if m.get("throttle_on_d") and r.get("throttle_on_d") else 0
    rest = dc - max(0.0, thr_late)                      # coasting not already explained by a late throttle
    if dc > 10 and rest > 10:
        F.append(_f("COASTING", 0.6 + rest / 10, f"{m['coast_m']:.0f} m with neither pedal (reference {r.get('coast_m', 0):.0f} m)."))
    # --- throttle
    if m.get("throttle_on_d") is not None and r.get("throttle_on_d") is not None:
        late = m["throttle_on_d"] - r["throttle_on_d"]
        if late > 8:
            F.append(_f("THROTTLE_LATE", late / 10, f"Throttle {late:.0f} m later ({m['throttle_on_d']:.0f} m vs {r['throttle_on_d']:.0f} m)."))
    if m.get("full_throttle_d") and r.get("full_throttle_d"):
        late = m["full_throttle_d"] - r["full_throttle_d"]
        on_late = (m.get("throttle_on_d") or 0) - (r.get("throttle_on_d") or 0)
        if late > 15 and late - max(0, on_late) > 10:
            F.append(_f("THROTTLE_RAMP_SLOW", (late - max(0, on_late)) / 15 * (0.5 if xm.get("thr_dips", 0) > xr.get("thr_dips", 0) else 1), f"Full throttle {late:.0f} m later ({m['full_throttle_d']:.0f} m vs {r['full_throttle_d']:.0f} m)."))
    elif not m.get("full_throttle_d") and r.get("full_throttle_d"):
        F.append(_f("NEVER_FULL", 2.0, "No full throttle before the next corner; the reference gets there."))
    if xm.get("thr_dips", 0) > xr.get("thr_dips", 0):
        F.append(_f("THROTTLE_HESITATION", 1.0 + 0.8 * (xm["thr_dips"] - xr.get("thr_dips", 0)),
                    f"{xm['thr_dips']} lift{'s' if xm['thr_dips'] != 1 else ''} while opening the throttle (reference {xr.get('thr_dips', 0)})."))
    # --- gears and shifts
    gm, gr = m.get("gear_apex"), r.get("gear_apex")
    if gm and gr and gm != gr and abs(dv) < 4:          # same speed, different gear = a choice (not just slower)
        F.append(_f("GEAR_DIFF", 1.5, f"Gear {gm} at the apex; the reference uses {gr}."))
    if xm.get("shift_rpm") and xr.get("shift_rpm"):
        k = xm["shift_rpm"] / xr["shift_rpm"]
        if k < 0.95:
            F.append(_f("SHIFT_EARLY", (1 - k) / 0.04, f"Upshift at about {xm['shift_rpm']:.0f} rpm vs {xr['shift_rpm']:.0f} rpm."))
        elif k > 1.03:
            F.append(_f("SHIFT_LATE", (k - 1) / 0.03, f"Upshift at about {xm['shift_rpm']:.0f} rpm vs {xr['shift_rpm']:.0f} rpm."))
    # --- steering
    nm, nr = xm.get("steer_noise"), xr.get("steer_noise")
    if m["steer_reversals"] > r["steer_reversals"] + 3 or (nm is not None and nr is not None and nm > 2.5 * max(nr, 0.004) and nm > 0.015):
        F.append(_f("STEER_CORRECTIONS", 1.0 + 0.15 * max(0, m["steer_reversals"] - r["steer_reversals"]),
                    f"{m['steer_reversals']} steering corrections vs {r['steer_reversals']}."))
    # --- line
    if line and "apex" in line:
        off = line["apex"]
        if off < -1.5:
            F.append(_f("LINE_WIDE_APEX", -off / 1.5, f"About {-off:.1f} m wider than the reference at the apex."))
        elif off > 1.5:
            F.append(_f("LINE_TIGHT_APEX", off / 2.0, f"About {off:.1f} m tighter than the reference at the apex."))
    elif not line and xm.get("radius_m") and xr.get("radius_m") and dv > 2:
        if xm["radius_m"] < 0.85 * xr["radius_m"]:
            F.append(_f("LINE_RADIUS_TIGHT", (1 - xm["radius_m"] / xr["radius_m"]) / 0.15,
                        f"Arc at the apex about {xm['radius_m']:.0f} m vs {xr['radius_m']:.0f} m (estimated from speed and lateral g)."))
    # --- exit
    dex = r["exit_kmh"] - m["exit_kmh"]
    if dex > 3:
        F.append(_f("EXIT_SLOW", dex / 4, f"Exit {m['exit_kmh']:.0f} km/h vs {r['exit_kmh']:.0f} km/h."))
    return F


def rank_findings(F, phase_loss):
    """Score = severity, weighted by how much time the finding's phase loses; consequences go after causes."""
    pos = {k: max(0.0, v) for k, v in phase_loss.items()}
    tot = sum(pos.values()) or 1.0
    share = lambda ph: (pos.get("entry", 0) + pos.get("exit", 0)) / 2 / tot if ph in ("mid", "lap") else pos.get(ph, 0) / tot
    for f in F:
        f["score"] = f["sev"] * (0.5 + share(f["phase"]))
    causes = [f["score"] for f in F if not f["consequence"]]
    for f in F:
        if f["consequence"] and causes:                 # a result, not the cause: list it after the causes
            f["score"] = min(f["score"] * 0.35, min(causes) * 0.9)
        f["score"] = round(f["score"], 3)
    F.sort(key=lambda f: -f["score"])
    return F


def _consistency(laps_m):
    """laps_m = [corner_metrics] of your other clean laps at this corner."""
    if len(laps_m) < 3:
        return None, []
    b = [x["brake_d"] for x in laps_m if x.get("brake_d") is not None]
    v = [x["min_kmh"] for x in laps_m]
    t = [x["time"] for x in laps_m]
    c = {"laps": len(laps_m), "brake_sd_m": round(float(np.std(b)), 1) if len(b) >= 3 else None,
         "min_sd_kmh": round(float(np.std(v)), 1), "time_sd": round(float(np.std(t)), 3)}
    F = []
    if c["brake_sd_m"] is not None and c["brake_sd_m"] > 8:
        F.append(_f("INCONSISTENT_BRAKE", c["brake_sd_m"] / 10, f"Brake point varies by about ±{c['brake_sd_m']:.0f} m over {len(b)} laps."))
    if c["min_sd_kmh"] > 3:
        F.append(_f("INCONSISTENT_SPEED", c["min_sd_kmh"] / 4, f"Minimum speed varies by about ±{c['min_sd_kmh']:.0f} km/h over {len(v)} laps."))
    return c, F


# ---------------------------------------------------------------- the coach
def _r(x):
    return {k: v for k, v in _clean(x).items() if k != "span"}


def _clean(x):
    """numpy scalars -> plain Python, floats rounded: the result must survive json.dumps."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return round(float(x), 3) if math.isfinite(float(x)) else None
    return x


def coach_traces(trM, trR, corners, others=None, ref_info=None, lap_info=None, extra=None):
    """trM = your lap, trR = reference (1 m grid traces), corners = [{name,key,start,end}],
    others = traces of your other clean laps (for consistency). -> JSON-safe dict, corners ranked by time lost."""
    d, dt = delta(trM, trR)
    rows = []
    has_pos = _has_pos(trM) and _has_pos(trR)
    pairs = []
    for c in sorted(corners, key=lambda c: c["start"]):
        m = corner_metrics(trM, c["start"], c["end"])
        r = corner_metrics(trR, c["start"], c["end"])
        if m and r:
            pairs.append((c, m, r, extra_metrics(trM, m, c["start"], c["end"]), extra_metrics(trR, r, c["start"], c["end"])))

    # each corner owns the track from where either driver comes off the throttle for it to that point for the
    # next corner, so the straight after a corner counts for that corner (exit speed carries all the way down
    # it) and the corner losses add up to the lap time
    def cut(c, m, r, xm, xr):
        pts = []
        for mm, xx in ((m, xm), (r, xr)):
            if mm.get("brake_d") is not None:
                pts.append(mm["brake_d"] - (xx.get("lift_m") or 0))
        return max(0.0, (min(pts) if pts else min(m["apex_d"], r["apex_d"]) - 80) - 10)
    bounds = [0.0] + [cut(*p) for p in pairs[1:]] + [float(d[-1])]
    for k, (c, m, r, xm, xr) in enumerate(pairs):
        a, b = m["span"]
        ia, ib = _at(d, a), _at(d, b)
        sa, sb = _at(d, bounds[k]), _at(d, bounds[k + 1])
        iap = _at(d, r["apex_d"])                    # split entry / exit at the reference's apex
        lost = float(dt[sb] - dt[sa])
        phase = {"entry": round(float(dt[iap] - dt[sa]), 3), "exit": round(float(dt[sb] - dt[iap]), 3)}
        line = line_offsets(trM, trR, r, c["start"], c["end"]) if has_pos else None
        F = corner_findings(m, r, xm, xr, line)
        cons = None
        if others:
            om = [x for x in (corner_metrics(o, c["start"], c["end"]) for o in others) if x]
            cons, FC = _consistency(om)
            F += FC
        F = rank_findings(F, phase)
        rows.append({"name": c["name"], "key": c.get("key") or c["name"].lower().replace(" ", "_"),
                     "start": float(c["start"]), "end": float(c["end"]), "span": [round(a, 1), round(b, 1)],
                     "segment": [round(bounds[k], 1), round(bounds[k + 1], 1)],
                     "lost": round(lost, 3), "lost_corner": round(float(dt[ib] - dt[ia]), 3), "phase": phase,
                     "me": _r({**m, **xm}), "ref": _r({**r, **xr}), "line": line, "consistency": cons,
                     "findings": [{k2: (round(v, 2) if isinstance(v, float) else v) for k2, v in f.items()} for f in F[:5]]})
    rows.sort(key=lambda x: -x["lost"])
    total = float(dt[-1]) if len(dt) else 0.0
    focus = []
    for row in rows:
        if row["lost"] < 0.03 or not row["findings"]:
            continue
        f = row["findings"][0]
        focus.append({"corner": row["name"], "lost": row["lost"], "code": f["code"], "title": f["title"],
                      "detail": f["detail"], "drill": f["drill"]})
        if len(focus) == 3:
            break
    lines = [f"{x['corner']}: {x['lost']:.2f} s. {x['title']}. {x['detail']} Drill: {x['drill']}" for x in focus]
    notes = []
    if not has_pos:
        notes.append("No position data in one of the laps: the line is estimated from speed and lateral g.")
    out = {"version": VERSION, "made": time.strftime("%Y-%m-%d %H:%M:%S"), "lap": lap_info or {}, "ref": ref_info or {},
           "total": round(total, 3), "position": has_pos, "corners": rows, "focus": focus, "lines": lines, "notes": notes}
    out.update(extra or {})
    return _clean(out)


def coach_session(sess, lap_n, ref, ref_n=None, ref_info=None, max_others=8, save=True):
    """Your lap `lap_n` of Session `sess` against `ref` (a RefLap, a Session + ref_n, or a Theory)."""
    trM = sess.trace(lap_n)
    trR = ref.trace(ref_n)
    others = [sess.trace(L["n"]) for L in sess.laps if L.get("valid") and L["n"] != lap_n][-max_others:]
    L = sess.lap(lap_n) or {}
    info = ref_info or (ref.info() if isinstance(ref, RefLap) else {"label": f"Lap {ref_n}" if ref_n else "reference", "source": "session"})
    out = coach_traces(trM, trR, sess.find_corners(), others=others, ref_info=info,
                       lap_info={"n": lap_n, "time": L.get("time")},
                       extra={"car": getattr(sess, "car", ""), "track": getattr(sess, "track_display", "")})
    if save:
        save_summary(out)
    return out


def save_summary(out, path=None):
    """The last coaching result, for the team meeting room (plain JSON)."""
    p = path or LAST_FILE
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
    except OSError:
        pass


def last_summary(path=None):
    try:
        with open(path or LAST_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- Garage 61 -> RefLap
def ref_from_garage61(client, lap_id, track_len, meta=None):
    from . import garage61
    info = {}
    try:
        info = client.lap(lap_id) or {}
    except garage61.G61Error as e:
        if e.kind in ("no_token", "bad_token", "permission", "network"):
            raise
    if info and info.get("canViewTelemetry") is False:
        raise garage61.G61Error("permission", "Garage 61 doesn't let you see the telemetry of that lap.")
    text = client.lap_csv(lap_id)
    drv = (info.get("driver") or {})
    who = " ".join(x for x in (drv.get("firstName"), drv.get("lastName")) if x)
    m = {"garage61": True, "lap_id": str(lap_id), "driver": who or (meta or {}).get("driver"), "lap_time": info.get("lapTime"),
         "car": (info.get("car") or {}).get("name"), "track": (info.get("track") or {}).get("name")}
    tr = parse_csv(text, track_len=track_len, lap_time=m["lap_time"])
    ref = RefLap(tr, f"Garage 61 · {m['driver'] or 'lap'}", "garage61", m)
    if m["lap_time"]:
        ref.time = float(m["lap_time"])
    return ref
