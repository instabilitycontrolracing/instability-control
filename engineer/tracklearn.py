"""ic186 (#729): track learning - the practice coach's rules, worked out from his own laps only.

Plan: claude/track-learning-research-and-plan.md (T1-T13). Everything here comes from the laps the PC records for the
iPad (lap_store.py: lap %, speed, throttle, brake, steering, gear, lap clock at 10 Hz) and the track length; nothing is
estimated or filled in. When the data isn't there the advice is left out (None / a "why" text).

    stage_for(n_clean, race_prep)       T1/T13  Learn / Refine / Push / Race pace + what to do in it (+ endurance drills)
    banker_lap(run_laps, best, flags)   T2      the first clean lap of a run within 10 % of his best (coach quiet before)
    analyse(laps, L, met, ...)          T3/T6/T7 at most 3 focus items that repeat over his best + next fastest laps,
                                        ordered by time lost (corners onto long straights first), root cause first
                                        T5      coasting, lifts on straights, square braking, min speed vs best per corner
                                        T4      braking-board steps per corner;  T9 target pace;  T10 reference sheet
    Live                                the live hooks (run / banker tracking, off-track + incident marks per lap, the
                                        proposed calls - sids that have no recorded lines yet are skipped by brain.say)
"""
import json, math, os, threading, time

import numpy as np

BANKER_FRAC = 1.10        # T2: a banker lap is within 10 % of his best
GROUP_N = 5               # T6: his best lap + the next 4 fastest clean laps
REPEAT_FRAC = 0.6         # T6: a finding must show on 60 % of the compared laps (and at least 2) - no one-offs
MAX_FOCUS = 3             # T3: at most three things to work on in a run
MIN_LOST = 0.05           # s: a corner losing less than this isn't a focus item
STRAIGHT_W = 1000.0       # T7: weight = time lost x (1 + straight after the corner / 1000 m), capped at 1500 m
COAST_PEDAL = 0.05        # T5: neither pedal above 5 %...
COAST_S = 0.3             # ...for more than 0.3 s = coasting
LIFT_THR = 0.8            # T5: throttle under 80 % on a straight he drives flat on his best lap...
LIFT_S = 0.2              # ...for at least 0.2 s = a lift
STRAIGHT_MIN = 150.0      # m of full throttle (> 90 %) on the best lap = a straight
BRAKE_ON = 0.2            # T4: braking point = brake first over 20 % on the approach
STEP_MARGIN = 5.0         # T4: never suggest braking more than 5 m later than his best lap did
TARGET_ADD = 0.2          # T9: target lap = median of his best 5 green laps + 0.2 s
STAGES = (                # T1: (key, name, clean laps below which this stage applies)
    ("learn", "Learn", 15), ("refine", "Refine", 50), ("push", "Push", 150), ("race", "Race pace", None))
STAGE_TEXT = {
    "learn": ["Steady laps at about 90 % - no lap-time chasing yet.",
              "Find one braking marker and one turn-in point for every corner and use the same ones every lap.",
              "The coach stays quiet until your banker lap (the first clean lap within 10 % of your best)."],
    "refine": ["One corner at a time from the focus list - never more than three things in a run.",
               "Move one brake marker in small steps (the braking-board column) and keep the laps clean.",
               "Check the reference sheet after each run and note what changed."],
    "push": ["Qualifying-style runs: low fuel, fresh tyres, 3-4 push laps, then back in.",
             "Work the top focus items; compare each run with your best lap, not with the last one.",
             "Stop moving a brake marker the moment you lock up or run wide there - go back one step."],
    "race": ["Long runs on race fuel at your target lap - consistency over one-lap speed.",
             "Practise laps in traffic and keep the target pace sector by sector.",
             "Note how the pace drops over a stint (tyres, fuel) for the race plan."],
}
ENDURANCE_DRILLS = [
    {"t": "Night stint after a day stint", "d": "Do a run in daylight, then one at night (or with the time of day moved on) and compare the brake markers you can still see."},
    {"t": "Traffic laps", "d": "Follow and pass slower cars for a few laps: where do you lose the most, and where is it safe to pass?"},
    {"t": "A practice pit stop", "d": "Come in for fuel and tyres at race fuel: pit entry, the limiter, the stop and the exit."},
    {"t": "A start", "d": "Practise the start the race uses (rolling or standing) and the first lap's braking points with full fuel."},
]
ENDURANCE_S = 7200        # a race of 2 hours or more = an endurance event (drills shown)


# ======================================================================================== laps -> traces
def _at(d, x):
    return int(min(len(d) - 1, max(0, np.searchsorted(d, x))))


def lap_trace(lap, L, met=True):
    """A lap from lap_store (p, s, th, br, t, st, gr) -> a 1 m grid trace with the keys telemetry.corner_metrics and
    coach.extra_metrics use (d, t, kmh, Speed, Throttle, Brake, SteeringWheelAngle, Gear). None if it isn't a usable lap."""
    P = lap.get("p") or []
    if not L or L <= 0 or len(P) < 50:
        return None
    n = len(P)

    def arr(k, dflt=0.0):
        v = lap.get(k)
        if not v or len(v) != n:
            return np.full(n, dflt, dtype=np.float64)
        return np.array([dflt if x is None else x for x in v], dtype=np.float64)
    d = np.asarray(P, dtype=np.float64) * float(L)
    keep = np.concatenate([[True], np.diff(d) > 1e-6])
    d = d[keep]
    if d[-1] - d[0] < 0.9 * L:
        return None
    grid = np.arange(math.ceil(d[0]), min(float(L), d[-1]), 1.0)
    if len(grid) < 100:
        return None
    m = lap.get("met", met)
    k = 1.0 if m else 1.609344                     # the store keeps speed in the units iRacing showed
    tr = {"d": grid, "t": np.interp(grid, d, arr("t")[keep])}
    tr["kmh"] = np.interp(grid, d, arr("s")[keep]) * k
    tr["Speed"] = tr["kmh"] / 3.6
    tr["Throttle"] = np.interp(grid, d, np.clip(arr("th")[keep], 0, 1))
    tr["Brake"] = np.interp(grid, d, np.clip(arr("br")[keep], 0, 1))
    tr["SteeringWheelAngle"] = np.interp(grid, d, arr("st")[keep])
    tr["Gear"] = np.round(np.interp(grid, d, arr("gr")[keep]))
    return tr


def detect_corners(tr):
    """No named corners for this track: corners = clear speed minima on the lap (same rule as telemetry.Session)."""
    v, d = tr["kmh"], tr["d"]
    from numpy.lib.stride_tricks import sliding_window_view as sw
    w = 151
    if len(v) < w + 10:
        return []
    pad = np.pad(v, (w // 2, w // 2), mode="edge")
    cands = np.flatnonzero(v <= sw(pad, w).min(axis=1) + 1e-9)
    out, last = [], -1e9
    for i in cands:
        lo, hi = max(0, i - 400), min(len(v) - 1, i + 400)
        if v[lo:hi].max() - v[i] < 12 or d[i] - last < 120 or d[i] < 60 or d[i] > d[-1] - 60:
            continue
        last = d[i]
        out.append({"name": f"Turn {len(out) + 1}", "key": f"turn_{len(out) + 1}",
                    "start": float(max(0, d[i] - 120)), "end": float(min(d[-1], d[i] + 80))})
    return out


def corners_for(track_name, tr_best):
    try:
        from .telemetry import track_landmarks
        cs = [dict(c) for c in track_landmarks(track_name or "")]
    except Exception:
        cs = []
    if not cs and tr_best is not None:
        cs = detect_corners(tr_best)
    return sorted(cs, key=lambda c: c["start"])


def brake_point(tr, c0, apex_d, on=BRAKE_ON):
    """T4: lap distance (m) where the brake first goes over 20 % on the approach to this corner, or None (flat out)."""
    d, thr, brk = tr["d"], tr["Throttle"], tr["Brake"]
    j0, ia = _at(d, c0 - 350), _at(d, apex_d)
    if ia <= j0:
        return None
    ft = np.flatnonzero(thr[j0:ia] > 0.9)
    start = j0 + (int(ft[-1]) + 1 if len(ft) else 0)
    hit = np.flatnonzero(brk[start:ia + 1] > on)
    return float(d[start + int(hit[0])]) if len(hit) else None


def seg_time(tr, a, b):
    d = tr["d"]
    a, b = max(float(d[0]), a), min(float(d[-1]), b)
    if b <= a:
        return None
    return float(np.interp(b, d, tr["t"]) - np.interp(a, d, tr["t"]))


def straight_after(tr, apex_d):
    """T7: metres of full throttle (> 90 %) on this lap after the corner's apex (wrapping over the line), 0 if none."""
    d, thr = tr["d"], tr["Throttle"]
    i = _at(d, apex_d)
    on = np.flatnonzero(thr[i:] > 0.9)
    if not len(on):
        return 0.0
    i0 = i + int(on[0])
    off = np.flatnonzero(thr[i0:] <= 0.9)
    if len(off):
        return float(d[i0 + int(off[0])] - d[i0])
    run = float(d[-1] - d[i0])                     # flat over the line: add the start of the lap
    off0 = np.flatnonzero(thr <= 0.9)
    return run + (float(d[int(off0[0])] - d[0]) if len(off0) else 0.0)


def straights(tr):
    """[(d0, d1)] runs of full throttle (> 90 %) of at least STRAIGHT_MIN metres on this lap."""
    d, full = tr["d"], tr["Throttle"] > 0.9
    out, i, n = [], 0, len(d)
    while i < n:
        if full[i]:
            j = i
            while j < n and full[j]:
                j += 1
            if d[j - 1] - d[i] >= STRAIGHT_MIN:
                out.append((float(d[i]), float(d[j - 1])))
            i = j
        else:
            i += 1
    return out


def _runs(mask):
    """Index runs (i0, i1 exclusive) where mask is True."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _corner_at(corners, x, slack=150.0):
    best, bd = None, 1e9
    for c in corners:
        if c["start"] - slack <= x <= c["end"] + slack:
            dd = 0 if c["start"] <= x <= c["end"] else min(abs(x - c["start"]), abs(x - c["end"]))
            if dd < bd:
                best, bd = c["name"], dd
    return best


# ======================================================================================== T5: checks on one lap
def coasting(tr, corners=()):
    """Places where neither pedal is over 5 % for more than 0.3 s -> [{at, m, s, corner}]. The laps come from the lap
    store's clean laps, which are never on pit road (the pit lane is left out by that)."""
    m = (tr["Throttle"] < COAST_PEDAL) & (tr["Brake"] < COAST_PEDAL)
    d, t = tr["d"], tr["t"]
    out = []
    for i0, i1 in _runs(m):
        dur = float(t[i1 - 1] - t[i0])
        if dur > COAST_S:
            out.append({"at": round(float(d[i0]), 1), "m": round(float(d[i1 - 1] - d[i0]), 1), "s": round(dur, 2),
                        "corner": _corner_at(corners, float(d[i0]))})
    return out


def straight_lifts(tr, ref_straights):
    """Throttle under 80 % for at least 0.2 s inside a straight his best lap drives flat -> [{at, s, straight}]
    (the last 30 m before the straight's end are left out: that's the lift for the brake zone)."""
    d, t, thr = tr["d"], tr["t"], tr["Throttle"]
    out = []
    for k, (a, b) in enumerate(ref_straights):
        i0, i1 = _at(d, a + 20), _at(d, b - 30)
        if i1 <= i0 + 2:
            continue
        for r0, r1 in _runs(thr[i0:i1] < LIFT_THR):
            dur = float(t[i0 + r1 - 1] - t[i0 + r0])
            if dur >= LIFT_S:
                out.append({"at": round(float(d[i0 + r0]), 1), "s": round(dur, 2), "straight": k})
    return out


def square_braking(m, x):
    """True when the brake is fully off before the turn-in (no trail braking), None when it can't be judged."""
    if m.get("brake_d") is None or x.get("brake_off_d") is None or x.get("turnin_d") is None:
        return None
    return bool(x["brake_off_d"] <= x["turnin_d"])


def lap_checks(tr, corners, ref_tr=None):
    """T5 for one lap (the coach's output): coasting, lifts on the reference's straights, square braking and minimum
    corner speed against the reference lap per corner."""
    from .telemetry import corner_metrics
    from .coach import extra_metrics
    ref_tr = ref_tr if ref_tr is not None else tr
    out = {"coasting": coasting(tr, corners), "lifts": straight_lifts(tr, straights(ref_tr)), "corners": []}
    for c in corners:
        m = corner_metrics(tr, c["start"], c["end"])
        r = corner_metrics(ref_tr, c["start"], c["end"])
        if not m:
            continue
        x = extra_metrics(tr, m, c["start"], c["end"])
        out["corners"].append({"name": c["name"], "square": square_braking(m, x), "trail_m": x.get("trail_m"),
                               "min_kmh": round(m["min_kmh"], 1), "ref_min_kmh": round(r["min_kmh"], 1) if r else None,
                               "min_diff_kmh": round(m["min_kmh"] - r["min_kmh"], 1) if r else None})
    return out


# ======================================================================================== T1 / T13: practice stage
def stage_for(n_clean, race_prep=False):
    n = int(n_clean or 0)
    key = "race"
    if not race_prep:
        for k, _name, below in STAGES:
            if below is not None and n < below:
                key = k
                break
    i = [s[0] for s in STAGES].index(key)
    name = STAGES[i][1]
    nxt = STAGES[i + 1] if i + 1 < len(STAGES) else None
    to_next = (STAGES[i][2] - n) if (STAGES[i][2] is not None and not race_prep) else None
    return {"key": key, "name": name, "clean_laps": n, "race_prep": bool(race_prep), "todo": list(STAGE_TEXT[key]),
            "next": nxt[1] if nxt else None, "to_next": to_next}


def clean_count(car_path, track, index_path=None, newer_than=None):
    """Clean laps (complete, valid, not a pit lap) he has recorded with this car at this track, from the app's lap index
    (CACHE_DIR/laps_index.json - read only, never rebuilt here; replays left out). newer_than: leave out recordings
    written after this time (the live session's own laps are counted from the lap store instead)."""
    if not car_path or not track:
        return None
    if index_path is None:
        from .telemetry import CACHE_DIR
        index_path = os.path.join(CACHE_DIR, "laps_index.json")
    try:
        with open(index_path, encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, ValueError):
        return None
    norm = lambda s: str(s or "").lower().replace(" ", "").replace("_", "")
    n = 0
    for v in idx.values():
        if not isinstance(v, dict) or v.get("error") or v.get("src") == "replay":
            continue
        if norm(v.get("car_path")) != norm(car_path) or norm(v.get("track")) != norm(track):
            continue
        if newer_than is not None:
            try:
                if os.path.getmtime(v.get("path") or "") >= newer_than:
                    continue
            except OSError:
                pass
        n += sum(1 for L in v.get("laps") or [] if L.get("valid") and L.get("complete") and not L.get("pit"))
    return n


# ======================================================================================== T2: banker lap
def lap_ok(lap, flags=None):
    """A clean lap: a full lap with a time, clean in the lap store (no pit / not off the world / no gap) and no off-track
    or incident marked on it live."""
    if not lap.get("time") or not lap.get("clean", True):
        return False
    f = (flags or {}).get(lap.get("no")) or (flags or {}).get(str(lap.get("no"))) or {}
    return not (f.get("off") or f.get("inc"))


def banker_lap(run_laps, best, flags=None):
    """T2: the first clean lap of the run within 10 % of his best lap -> lap dict or None. run_laps oldest first."""
    if not best:
        return None
    for lap in sorted(run_laps, key=lambda l: l.get("no") or 0):
        if lap_ok(lap, flags) and lap["time"] <= best * BANKER_FRAC:
            return lap
    return None


# ======================================================================================== T3 / T6 / T7: the focus list
# T7: the chain a corner's time goes down - the first link that repeats is the one to fix (the rest follow from it)
CHAIN = (
    ("entry", ("EARLY_LIFT", "BRAKE_EARLY", "BRAKE_LATE", "BRAKE_PEAK_LOW", "BRAKE_SLOW_BUILD", "ABS_HEAVY",
               "BRAKE_RELEASE_ABRUPT", "BRAKE_NO_TRAIL", "BRAKE_DRAG", "TURNIN_EARLY", "TURNIN_LATE")),
    ("mid", ("MIN_SPEED_LOW", "APEX_EARLY", "APEX_LATE", "COASTING", "GEAR_DIFF", "STEER_CORRECTIONS",
             "LINE_RADIUS_TIGHT")),
    ("exit", ("THROTTLE_LATE", "THROTTLE_RAMP_SLOW", "THROTTLE_HESITATION", "NEVER_FULL", "SHIFT_EARLY", "SHIFT_LATE")),
    ("straight", ("EXIT_SLOW",)),
)
_LINK = {code: (i, ph) for i, (ph, codes) in enumerate(CHAIN) for code in codes}
LINK_WORD = {"entry": "braking / entry", "mid": "corner speed", "exit": "throttle / exit", "straight": "speed onto the straight"}


def _med(xs):
    xs = [x for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def _disp(kmh, met):
    return None if kmh is None else round(float(kmh) if met else float(kmh) / 1.609344, 1)


def _cuts(cs, L):
    """Each corner owns the track from 250 m before it (or the previous corner's end) to the same point of the next
    corner, so the straight after a corner counts for that corner."""
    cuts = [0.0]
    for k in range(1, len(cs)):
        cut = max(cs[k - 1]["end"], cs[k]["start"] - 250.0)
        cuts.append(max(cuts[-1] + 1.0, min(cut, cs[k]["start"])))
    cuts.append(float(L))
    return cuts


def _offs_at(c, flags, L):
    """Laps with an off-track or incident marked inside this corner (live marks: lap % where it happened)."""
    hit = []
    for no, f in (flags or {}).items():
        for p in list(f.get("off") or []) + list(f.get("inc") or []):
            try:
                x = float(p) * float(L)
            except (TypeError, ValueError):
                continue
            if c["start"] - 150 <= x <= c["end"] + 100:
                hit.append(int(no))
                break
    return sorted(set(hit))


def target_pace(laps, flags=None):
    """T9: target lap = median of his best 5 green (clean) laps + 0.2 s, split by sector in the proportion of those
    laps' median sectors; plus his last lap against it. None when there aren't 5 clean laps."""
    from .lap_store import splits
    ok = sorted((l for l in laps if lap_ok(l, flags)), key=lambda l: l["time"])
    if len(ok) < 5:
        return {"ok": False, "why": f"Needs 5 clean laps ({len(ok)} so far)."}
    b5 = ok[:5]
    target = round(float(np.median([l["time"] for l in b5])) + TARGET_ADD, 3)
    secs = [splits(l.get("sec")) for l in b5]
    med = [_med([s[k] for s in secs]) if sum(1 for s in secs if s[k]) >= 3 else None for k in range(3)]
    tsec = None
    if all(med):
        tot = sum(med)
        tsec = [round(v * target / tot, 3) for v in med]
    out = {"ok": True, "target": target, "sectors": tsec, "from": [l["no"] for l in b5], "add": TARGET_ADD}
    last = max((l for l in laps if l.get("time")), key=lambda l: l.get("no") or 0, default=None)
    if last:
        ls = splits(last.get("sec"))
        out["last"] = {"no": last["no"], "time": last["time"], "delta": round(last["time"] - target, 3),
                       "sec_delta": [round(ls[k] - tsec[k], 3) if tsec and ls[k] else None for k in range(3)]}
    return out


def analyse(laps, L, met=True, track_name="", flags=None, corners=None):
    """The track-learning view of a session's laps (lap_store format). -> plain JSON-safe dict."""
    from .telemetry import corner_metrics
    from .coach import corner_findings, extra_metrics
    out = {"ok": False, "why": None, "track_len": L, "units": "kmh" if met else "mph", "focus": [], "corners": [],
           "checks": None, "steps": [], "sheet": [], "target": target_pace(laps, flags), "best": None, "laps_used": []}
    if not L:
        out["why"] = "The track length isn't known yet (it comes from iRacing when you're in the session)."
        return out
    ok = [l for l in laps if lap_ok(l, flags)]
    if not ok:
        out["why"] = "No clean full lap yet."
        return out
    TR = {}

    def trace(l):
        if l["no"] not in TR:
            try:
                TR[l["no"]] = lap_trace(l, L, met)
            except Exception:
                TR[l["no"]] = None
        return TR[l["no"]]
    by_time = sorted(ok, key=lambda l: l["time"])
    G = [(l, trace(l)) for l in by_time[:GROUP_N]]
    G = [(l, t) for l, t in G if t is not None]
    if not G:
        out["why"] = "The clean laps don't have enough samples to read."
        return out
    best, trB = G[0]
    out["best"] = {"no": best["no"], "time": best["time"]}
    out["laps_used"] = [l["no"] for l, _ in G]
    cs = corners or corners_for(track_name, trB)
    if not cs:
        out["why"] = "No corners known for this track."
        return out
    recent = [l for l in sorted(ok, key=lambda l: -(l.get("no") or 0))[:3] if trace(l) is not None]
    cuts = _cuts(cs, L)
    need = lambda n: max(2, math.ceil(REPEAT_FRAC * n))
    cands, coast_rows, sq_rows, min_rows = [], {}, [], []
    for k, c in enumerate(cs):
        per = []
        for l, tr in G:
            m = corner_metrics(tr, c["start"], c["end"])
            if not m:
                continue
            x = extra_metrics(tr, m, c["start"], c["end"])
            per.append({"no": l["no"], "tr": tr, "m": m, "x": x, "seg": seg_time(tr, cuts[k], cuts[k + 1]),
                        "bp": brake_point(tr, c["start"], m["apex_d"])})
        pb = next((p for p in per if p["no"] == best["no"]), None)
        if pb is None:
            continue
        mB, xB = pb["m"], pb["x"]
        straight = straight_after(trB, mB["apex_d"])
        row = {"name": c["name"], "key": c.get("key"), "start": round(c["start"], 1), "end": round(c["end"], 1),
               "straight_m": round(straight), "lost": None, "ref_lap": None}
        # ---- T3/T6/T7: what repeats here, against his fastest lap through this corner
        segs = [p for p in per if p["seg"] is not None]
        if len(segs) >= 3:
            ref = min(segs, key=lambda p: p["seg"])
            others = [p for p in segs if p is not ref]
            lost = _med([p["seg"] - ref["seg"] for p in others])
            row.update(lost=round(lost, 3), ref_lap=ref["no"])
            counts, sev, det, on_best = {}, {}, {}, set()
            for p in others:
                seen = set()
                for f in corner_findings(p["m"], ref["m"], p["x"], ref["x"]):
                    cd = f["code"]
                    if cd in seen or cd not in _LINK:
                        continue
                    seen.add(cd)
                    counts[cd] = counts.get(cd, 0) + 1
                    sev.setdefault(cd, []).append(f["sev"])
                    if p["no"] == best["no"] or cd not in det:
                        det[cd] = (f, p["no"])
                    if p["no"] == best["no"]:
                        on_best.add(cd)
            best_is_ref = ref["no"] == best["no"]
            rep = [cd for cd, n in counts.items() if n >= need(len(others)) and (best_is_ref or cd in on_best)]
            if rep and lost is not None and lost >= MIN_LOST:
                chain = sorted(rep, key=lambda cd: (_LINK[cd][0], -counts[cd], -float(np.mean(sev[cd]))))
                f0, f_no = det[chain[0]]
                w = lost * (1.0 + min(straight, 1500.0) / STRAIGHT_W)
                cands.append({"corner": c["name"], "lost": round(lost, 3), "weight": round(w, 3), "straight_m": round(straight),
                              "code": chain[0], "title": f0["title"], "detail": f0["detail"], "drill": f0["drill"],
                              "link": LINK_WORD[_LINK[chain[0]][1]], "seen": f"{counts[chain[0]]} of {len(others)} laps",
                              "detail_lap": f_no, "ref_lap": ref["no"],
                              "chain": [{"code": cd, "title": det[cd][0]["title"], "link": LINK_WORD[_LINK[cd][1]]} for cd in chain]})
        # ---- T5: square braking + minimum speed against his best lap, per corner
        sq = [square_braking(p["m"], p["x"]) for p in per]
        judged = [s for s in sq if s is not None]
        if len(judged) >= 2 and sum(judged) >= need(len(judged)):
            sq_rows.append({"corner": c["name"], "laps": int(sum(judged)), "of": len(judged), "trail_m": round(xB.get("trail_m") or 0, 1)})
        others_min = [p["m"]["min_kmh"] for p in per if p["no"] != best["no"]]
        top = max(p["m"]["min_kmh"] for p in per)
        min_rows.append({"corner": c["name"], "best_lap": _disp(mB["min_kmh"], met), "session_top": _disp(top, met),
                         "others": _disp(_med(others_min), met),
                         "diff": _disp(_med(others_min) - mB["min_kmh"], met) if others_min else None})
        # ---- T10: reference sheet from his best lap
        bpB = pb["bp"]
        turn = xB.get("turnin_d")
        exit_d = mB.get("full_throttle_d") or mB.get("throttle_on_d")
        out["sheet"].append({"corner": c["name"], "brake_d": round(bpB) if bpB is not None else None,
                             "before": round(turn - bpB) if (bpB is not None and turn is not None and turn > bpB) else None,
                             "turnin_d": round(turn) if turn is not None else None, "apex_d": round(mB["apex_d"]),
                             "exit_d": round(exit_d) if exit_d is not None else None, "min": _disp(mB["min_kmh"], met),
                             "gear": int(mB["gear_apex"]) if mB.get("gear_apex") else None})
        # ---- T4: braking-board step
        if bpB is not None:
            rec = [brake_point(TR[l["no"]], c["start"], mB["apex_d"]) for l in recent]
            rec = [x for x in rec if x is not None]
            if rec:
                cur = _med(rec)
                ref_pt, ref_word = (turn, "turn-in") if (turn is not None and turn > cur) else (mB["apex_d"], "apex")
                zone = mB["apex_d"] - cur
                step = 10.0 if zone < 120 else 15.0 if zone < 220 else 20.0
                cap = bpB + STEP_MARGIN
                sd = float(np.std(rec)) if len(rec) >= 3 else None
                offs = _offs_at(c, flags, L)
                st = {"corner": c["name"], "now_d": round(cur), "now_before": round(ref_pt - cur), "ref": ref_word,
                      "best_d": round(bpB), "best_before": round(ref_pt - bpB), "laps": len(rec), "sd": round(sd, 1) if sd is not None else None,
                      "next_d": None, "next_before": None, "status": None, "text": None}
                if offs:
                    st.update(status="hold", text=f"Off track or an incident here (lap {', '.join(map(str, offs))}): no later marker - "
                                                  f"go back to your best lap's {round(ref_pt - bpB)} m.")
                elif sd is not None and sd > 8:
                    st.update(status="settle", text=f"Your brake point moves about ±{sd:.0f} m: pick one marker and use it for five laps first.")
                elif cur >= cap - 2:
                    st.update(status="at_best", text="You brake where your best lap did. Hold this until it's the same every lap.")
                else:
                    nxt = min(cur + step, cap)
                    st.update(status="step", next_d=round(nxt), next_before=round(ref_pt - nxt),
                              text=f"Try {round(ref_pt - nxt)} m before the {ref_word} ({round(nxt - cur)} m later than now).")
                out["steps"].append(st)
        out["corners"].append(row)
    # ---- T5: coasting and lifts on straights, over the compared laps
    strs = straights(trB)
    lift_rows = {}
    for l, tr in G:
        for e in coasting(tr, cs):
            key = e["corner"] or f"{e['at']:.0f} m"
            r = coast_rows.setdefault(key, {"corner": key, "laps": set(), "s": []})
            r["laps"].add(l["no"]); r["s"].append(e["s"])
        if l["no"] == best["no"]:
            continue
        for e in straight_lifts(tr, strs):
            a = strs[e["straight"]][0]
            before = [c for c in cs if c["start"] <= a]
            key = ("after " + before[-1]["name"]) if before else f"at {a:.0f} m"
            r = lift_rows.setdefault(key, {"straight": key, "laps": set(), "s": []})
            r["laps"].add(l["no"]); r["s"].append(e["s"])
    n_other = max(0, len(G) - 1)
    out["checks"] = {
        "laps": len(G),
        "coasting": sorted(({"corner": r["corner"], "laps": len(r["laps"]), "of": len(G), "s": round(_med(r["s"]), 2),
                             "repeat": len(r["laps"]) >= need(len(G))} for r in coast_rows.values()), key=lambda r: -r["laps"]),
        "lifts": sorted(({"straight": r["straight"], "laps": len(r["laps"]), "of": n_other, "s": round(_med(r["s"]), 2),
                          "repeat": n_other >= 2 and len(r["laps"]) >= need(n_other)} for r in lift_rows.values()), key=lambda r: -r["laps"]),
        "square": sq_rows, "min_speed": min_rows,
    }
    cands.sort(key=lambda f: -f["weight"])
    out["focus"] = cands[:MAX_FOCUS]
    out["ok"] = True
    if len(G) < 3:
        out["why"] = f"The focus list needs 3 clean laps to compare ({len(G)} so far)."
    return out


# ======================================================================================== live (practice)
# Proposed calls (ic186, NOT approved yet - no recorded lines, so brain.say() skips them quietly until Angelo approves
# them; see C:\SimRacing\Temp\ic186_proposed_lines.md). All of them are off by default in the settings.
FOCUS_SID = {"BRAKE_EARLY": "tl_focus_brake_early", "BRAKE_LATE": "tl_focus_brake_late", "BRAKE_NO_TRAIL": "tl_focus_trail",
             "COASTING": "tl_focus_coasting", "EARLY_LIFT": "tl_focus_entry"}
FOCUS_SID_LINK = {"entry": "tl_focus_entry", "mid": "tl_focus_min_speed", "exit": "tl_focus_throttle", "straight": "tl_focus_exit"}
META_FILE = None          # CACHE_DIR/tracklearn_meta.json (set on first use)


def focus_sid(code):
    return FOCUS_SID.get(code) or FOCUS_SID_LINK.get(_LINK.get(code, (0, "entry"))[1], "tl_focus_entry")


def track_len_m(text):
    """WeekendInfo TrackLength ('5.79 km' / '3.60 mi') -> metres, or None."""
    try:
        v, u = str(text).split()[:2]
        v = float(v)
        return v * (1609.344 if u.lower().startswith("mi") else 1000.0)
    except (ValueError, TypeError):
        return None


def race_secs(info):
    """The race session's length in this event's SessionInfo (seconds), or None (laps-only / unlimited / not listed)."""
    for s in ((info or {}).get("Sessions") or []):
        if "race" in str(s.get("SessionType", "")).lower():
            try:
                return float(str(s.get("SessionTime", "")).split()[0])
            except (ValueError, IndexError):
                return None
    return None


def _meta_path():
    global META_FILE
    if META_FILE is None:
        from .telemetry import CACHE_DIR
        META_FILE = os.path.join(CACHE_DIR, "tracklearn_meta.json")
    return META_FILE


def load_meta(key):
    try:
        with open(_meta_path(), encoding="utf-8") as f:
            return (json.load(f) or {}).get(str(key)) or {}
    except (OSError, ValueError, AttributeError):
        return {}


def save_meta(key, meta):
    p = _meta_path()
    try:
        with open(p, encoding="utf-8") as f:
            allm = json.load(f) or {}
    except (OSError, ValueError):
        allm = {}
    allm[str(key)] = dict(meta, saved=time.time())
    if len(allm) > 40:
        for k in sorted(allm, key=lambda k: allm[k].get("saved", 0))[:len(allm) - 40]:
            allm.pop(k, None)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(allm, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


class Live:
    """Fed by remote.feed() with the brain and the lap store (about 15 times a second). Light: a few reads per tick;
    the lap analysis runs on its own thread once per completed lap, and only when a live call is switched on."""

    def __init__(self, log=print):
        self.log = log
        self.reset(None)

    def reset(self, key):
        self.key, self.flags, self.meta = key, {}, (load_meta(key) if key else {})
        self.t0 = time.time()
        self.run, self.run_from, self.banker = 0, None, None
        self.onp_prev = self.inc_prev = None
        self.off_prev = False
        self.last_seen, self.result, self.target = None, None, None
        self.busy = False
        self.said, self.pending, self.cued = set(), [], set()
        self._meta_t = 0.0
        self._d_prev = None

    def state(self):
        return {"run": self.run, "run_from": self.run_from, "banker": self.banker,
                "flags": {str(k): v for k, v in self.flags.items()}}

    def _setting(self, b, k, d=False):
        return bool(getattr(getattr(b, "s", None), k, d))

    def tick(self, b, store):
        if store.key != self.key:
            self.reset(store.key)
        g = b.g
        lap = (g("LapCompleted", 0) or 0) + 1
        pct = g("LapDistPct")
        onp = bool(g("OnPitRoad", False))
        if self.onp_prev is None:
            self.onp_prev = onp
            if not onp:                          # picked up mid-run: this lap and the ones after are the run
                self.run, self.run_from = 1, lap
        elif self.onp_prev and not onp:          # out of the pits: a new run (the out lap doesn't count)
            self.run += 1
            self.run_from, self.banker = lap + 1, None
            self.said, self.cued = set(), set()
        self.onp_prev = onp
        # off-track and incident marks on this lap (where on the lap they happened)
        try:
            off = int(g("PlayerTrackSurface", 3)) == 0          # irsdk_TrkLoc: 0 = off track
        except (TypeError, ValueError):
            off = False
        if off and not self.off_prev and pct is not None:
            self.flags.setdefault(lap, {}).setdefault("off", []).append(round(float(pct), 4))
        self.off_prev = off
        inc = g("PlayerCarMyIncidentCount")
        if inc is not None:
            if self.inc_prev is not None and inc > self.inc_prev and pct is not None:
                self.flags.setdefault(lap, {}).setdefault("inc", []).append(round(float(pct), 4))
            self.inc_prev = inc
        now = time.time()
        if now - self._meta_t > 10:
            self._meta_t = now
            self._update_meta(b)
        newest = store.laps[0].get("no") if store.laps else None
        if newest != self.last_seen:
            self.last_seen = newest
            if newest is not None:
                self._on_lap(b, store)
        self._speak(b)
        self._cue(b, pct)

    def _update_meta(self, b):
        try:
            wk = b.info("WeekendInfo", {}) or {}
            me = b.drivers().get(b.me(), {}) or {}
            m = {"track": wk.get("TrackName"), "track_display": wk.get("TrackDisplayName"),
                 "track_len": track_len_m(wk.get("TrackLength")), "car_path": me.get("CarPath"), "car": me.get("CarScreenName"),
                 "race_s": race_secs(b.info("SessionInfo", {})), "session": getattr(b, "sess_type", "") or "",
                 "met": bool(b.metric()) if hasattr(b, "metric") else None}
        except Exception:
            return
        if m != {k: self.meta.get(k) for k in m}:
            self.meta.update(m)
            if self.key:
                save_meta(self.key, self.meta)

    def _practice(self, b):
        return "practice" in str(getattr(b, "sess_type", "") or "").lower()

    def _on_lap(self, b, store):
        if not self._practice(b) or self.run_from is None:
            return
        ok = [l for l in store.laps if lap_ok(l, self.flags)]
        best = min((l["time"] for l in ok), default=None)
        if self.banker is None:
            run_laps = [l for l in store.laps if (l.get("no") or 0) >= self.run_from]
            bk = banker_lap(run_laps, best, self.flags)
            if bk is not None:
                self.banker = bk["no"]
                self.log(f"[track] banker lap: lap {bk['no']} ({bk['time']:.3f})")
                if self._setting(b, "calls_track_coach"):
                    self.pending.append(("tl_banker", {}))
            return                                  # T2: no corner advice until the banker lap is in
        coach, tgt = self._setting(b, "calls_track_coach"), self._setting(b, "calls_target_pace")
        cues = self._setting(b, "calls_brake_cues")
        if not (coach or tgt or cues) or self.busy:
            return
        laps, flags, L = list(store.laps), {k: dict(v) for k, v in self.flags.items()}, self.meta.get("track_len")
        met, track = bool(store.met), self.meta.get("track") or ""
        race_prep = self._setting(b, "practice_race_prep")
        self.busy = True

        def job():
            try:
                res = analyse(laps, L, met, track, flags)
                self.result = res
                if coach and len(self.said) < MAX_FOCUS:
                    for f in res.get("focus") or []:
                        if f["corner"] not in self.said:
                            self.said.add(f["corner"])
                            self.pending.append((focus_sid(f["code"]), {"corner": f["corner"]}))
                            break
                if tgt:
                    n = (clean_count(self.meta.get("car_path"), track, newer_than=self.t0) or 0) + sum(1 for l in laps if lap_ok(l, flags))
                    if stage_for(n, race_prep)["key"] == "race":
                        t = res.get("target") or {}
                        last = t.get("last") or {}
                        sd = [x for x in (last.get("sec_delta") or []) if x is not None]
                        if t.get("ok") and last:
                            worst = max(range(3), key=lambda k: (last["sec_delta"][k] if last["sec_delta"][k] is not None else -9))
                            wv = last["sec_delta"][worst]
                            if last["delta"] <= 0:
                                self.pending.append(("tl_target_on", {}))
                            elif sd and wv is not None and wv >= 0.1:
                                self.pending.append(("tl_target_down", {"sector": worst + 1, "tenths": int(round(wv * 10))}))
            except Exception as e:
                self.log(f"[track] analyse: {e!r}")
            finally:
                self.busy = False
        threading.Thread(target=job, daemon=True, name="tracklearn").start()

    def _speak(self, b):
        while self.pending:
            sid, f = self.pending.pop(0)
            try:
                b.say(sid, f, max_age=20)           # an unapproved sid has no lines: brain.say returns False, nothing plays
            except Exception as e:
                self.log(f"[track] say {sid}: {e!r}")

    def _cue(self, b, pct):
        """T4/T8 (off by default): 'next step' brake marker reminder ~300 m before the braking zone, once per corner a lap."""
        L = self.meta.get("track_len")
        if pct is None or not L or self.banker is None or not self._setting(b, "calls_brake_cues") or not self.result:
            self._d_prev = None
            return
        d = float(pct) * L
        prev, self._d_prev = self._d_prev, d
        if prev is None or d < prev:
            self.cued = set() if prev is not None and d < prev - L / 2 else self.cued
            return
        for st in self.result.get("steps") or []:
            if st.get("status") != "step":
                continue
            x = st["now_d"] - 300.0
            if prev < x <= d and st["corner"] not in self.cued:
                self.cued.add(st["corner"])
                try:
                    b.say("tl_brake_cue", {"corner": st["corner"], "metres": st["next_before"]}, max_age=3)
                except Exception:
                    pass


# ======================================================================================== the iPad page
_VIEW = {"sig": None, "out": None}


def _stored_session():
    """No session in memory (the engineer just started): the newest session the lap store kept on disk."""
    from .lap_store import DIR
    try:
        fs = sorted((os.path.join(DIR, n) for n in os.listdir(DIR) if n.endswith(".json")), key=os.path.getmtime, reverse=True)
    except OSError:
        return None, []
    for p in fs[:3]:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("laps"):
                return d.get("key"), d["laps"]
        except (OSError, ValueError):
            continue
    return None, []


def view(store, live=None, settings=None, log=print):
    """GET /api/tracklearn: stage + plan + drills, the focus list, the T5 checks, braking steps, target pace, reference
    sheet and the best / last lap (for the visualisation timer). Cached until a lap or a mark changes."""
    key, laps, met = getattr(store, "key", None), list(getattr(store, "laps", None) or []), bool(getattr(store, "met", False))
    is_live = bool(laps)
    if not laps:
        key, laps = _stored_session()
    meta = dict(live.meta) if (live is not None and live.key == key and live.meta) else load_meta(key)
    if not is_live and meta.get("met") is not None:
        met = bool(meta["met"])
    flags = {k: dict(v) for k, v in (live.flags.items() if (live is not None and live.key == key) else [])}
    race_prep = bool(getattr(settings, "practice_race_prep", False))
    track = meta.get("track") or (str(key).split(":", 2)[2] if key and str(key).count(":") >= 2 else "")
    L = meta.get("track_len")
    sig = json.dumps([key, [(l.get("no"), l.get("time"), l.get("clean", True)) for l in laps], flags, L, met, race_prep,
                      live.state() if live is not None else None], default=str)
    if sig == _VIEW["sig"] and _VIEW["out"] is not None:
        return _VIEW["out"]
    try:
        res = analyse(laps, L, met, track, flags) if laps else {"ok": False, "why": "No laps recorded yet. Drive a few laps and they show up here."}
    except Exception as e:
        log(f"[track] view: {e!r}")
        res = {"ok": False, "why": "Couldn't read the laps."}
    n_live = sum(1 for l in laps if lap_ok(l, flags))
    hist = clean_count(meta.get("car_path"), track, newer_than=live.t0 if (is_live and live is not None) else None)
    stage = stage_for((hist or 0) + (n_live if is_live else 0), race_prep) if (hist is not None or n_live) else None
    if stage is not None:
        stage["counted"] = "your recordings with this car here + this session" if hist is not None else "this session only (car not known)"
    rs = meta.get("race_s")
    endurance = (rs >= ENDURANCE_S) if rs else None
    timed = [l for l in laps if l.get("time")]
    last = max(timed, key=lambda l: l.get("no") or 0, default=None)
    res.update({"key": key, "live": is_live, "track": meta.get("track_display") or track, "car": meta.get("car"),
                "stage": stage, "endurance": endurance, "race_s": rs, "drills": ENDURANCE_DRILLS if endurance is not False else [],
                "run": live.state() if (live is not None and live.key == key) else None,
                "last_lap": {"no": last["no"], "time": last["time"]} if last else None,
                "settings": {k: bool(getattr(settings, k, False)) for k in ("calls_track_coach", "calls_target_pace", "calls_brake_cues", "practice_race_prep")}})
    res = _clean(res)
    _VIEW.update(sig=sig, out=res)
    return res


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_clean(v) for v in x]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return round(float(x), 3) if math.isfinite(float(x)) else None
    return x
