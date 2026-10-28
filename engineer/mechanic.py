"""The mechanic: finds handling problems by corner and phase, separates technique from setup,
and suggests ONE setup change at a time with the car's current value.

Rules come from iRacing's car manuals (see project doc mechanic-setup-rulebook.md).
Understeer/oversteer is measured with a steering index: steering needed per unit of rotation,
compared with this car's own median in this session (so it works without knowing the steering ratio).
"""
import numpy as np

from .telemetry import corner_metrics

MIN_REPEAT = 2   # a symptom must show on at least this many laps (and most laps) before we call it setup


# ---------------------------------------------------------------- setup lookups
def _walk(d, path=""):
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            yield from _walk(v, path + k + ".")
        else:
            yield path + k, v


def setup_value(sess, *names):
    for key, v in _walk(sess.setup):
        last = key.split(".")[-1].lower()
        if any(n.lower() == last for n in names):
            return str(v).strip()
    for key, v in _walk(sess.setup):
        if any(n.lower() in key.lower() for n in names):
            return str(v).strip()
    return None


def incar(tr, ch):
    if ch in tr:
        return int(round(float(np.median(tr[ch]))))
    return None


def car_kind(sess):
    if sess.gtp:
        return "gtp"
    t = (sess.car_path + " " + sess.car_class).lower()
    if "gt3" in t or "evo" in t:
        return "gt3"
    return "other"


# ---------------------------------------------------------------- measuring
def _raw_index(tr, sl=slice(None)):
    sw, yr, v, la = tr["SteeringWheelAngle"][sl], tr["YawRate"][sl], tr["Speed"][sl], tr["LatAccel"][sl]
    m = (v > 12) & (np.abs(yr) > 0.05) & (np.abs(la) > 3)
    return np.abs(sw[m]) * v[m] / np.abs(yr[m]), v[m], m


def _baseline(tr):
    """The car's normal steering-per-rotation at each speed (median per 6 m/s band) on this lap."""
    idx, v, _ = _raw_index(tr)
    if len(idx) < 80:
        return None
    edges = np.arange(10, 100, 6.0)
    cen, med = [], []
    for lo in edges:
        sel = (v >= lo) & (v < lo + 6)
        if sel.sum() >= 25:
            cen.append(lo + 3); med.append(np.median(idx[sel]))
    if len(cen) < 2:
        return (np.array([30.0, 60.0]), np.array([np.median(idx)] * 2))
    return (np.array(cen), np.array(med))


def _steer_index(tr, sl, base):
    idx, v, m = _raw_index(tr, sl)
    if len(idx) < 8:
        return None, 0.0
    expect = np.interp(v, base[0], base[1])
    rel = float(np.median(idx / expect))
    sw, yr = tr["SteeringWheelAngle"][sl], tr["YawRate"][sl]
    counter = float(((np.sign(sw) != np.sign(yr)) & (np.abs(yr) > 0.08) & (np.abs(sw) > 0.03)).mean())
    return rel, counter


def phase_slices(tr, m):
    d = tr["d"]
    at = lambda x: int(np.searchsorted(d, x))
    apex = m["apex_d"]
    entry_start = m.get("brake_d") or (apex - 120)
    full = m.get("full_throttle_d") or (apex + 150)
    return {"entry": slice(at(entry_start), at(apex - 15)),
            "mid": slice(at(apex - 25), at(apex + 25)),
            "exit": slice(at(apex + 20), at(max(apex + 60, full)))}


def corner_phase_read(tr, m, base):
    out = {}
    for ph, sl in phase_slices(tr, m).items():
        if sl.stop - sl.start < 6:
            continue
        idx, counter = _steer_index(tr, sl, base)
        if idx is None:
            continue
        sym = None
        if counter > 0.12 or idx < 0.8:
            sym = "oversteer"
        elif idx > 1.22:
            sym = "understeer"
        out[ph] = {"idx": round(idx, 2), "counter": round(counter, 2), "sym": sym}
    # technique tells
    d = tr["d"]
    ent = phase_slices(tr, m)["entry"]
    sw = np.abs(tr["SteeringWheelAngle"])
    if ent.stop > ent.start:
        turn = np.flatnonzero(sw[ent] > 0.08)
        out["brake_at_turnin"] = float(tr["Brake"][ent.start + int(turn[0])]) if len(turn) else 0.0
    ex = phase_slices(tr, m)["exit"]
    thr = tr["Throttle"][ex]
    if len(thr) > 5:
        a = np.flatnonzero(thr > 0.2); b = np.flatnonzero(thr > 0.9)
        if len(a) and len(b) and b[0] > a[0]:
            dist = (b[0] - a[0]) * (d[1] - d[0])
            out["throttle_ramp_s"] = float(dist / max(1.0, tr["Speed"][ex][a[0]]))
            out["steer_at_full"] = float(sw[ex][b[0]] / max(0.05, sw[ex].max()))
    # bottoming: lowest ride height in the corner window
    sl = slice(int(np.searchsorted(d, m["apex_d"] - 200)), int(np.searchsorted(d, m["apex_d"] + 150)))
    rh_f = [tr[k][sl].min() for k in ("LFrideHeight", "RFrideHeight") if k in tr]
    rh_r = [tr[k][sl].min() for k in ("LRrideHeight", "RRrideHeight") if k in tr]
    out["rh_front_min"] = float(min(rh_f)) if rh_f else None
    out["rh_rear_min"] = float(min(rh_r)) if rh_r else None
    return out


# ---------------------------------------------------------------- diagnosis over the session
def diagnose(sess, max_laps=8):
    """{corner_key: {"phase": {...counts}, "laps": n, "speed": kmh, ...}} across this session's full laps."""
    if getattr(sess, "_diag", None) is not None:
        return sess._diag
    laps = [L for L in sess.laps if L["complete"] and not L["pit"]][-max_laps:]
    res = {}
    for L in laps:
        tr = sess.trace(L["n"])
        base = _baseline(tr)
        if base is None:
            continue
        for c in sess.find_corners():
            m = corner_metrics(tr, c["start"], c["end"])
            if not m:
                continue
            r = corner_phase_read(tr, m, base)
            e = res.setdefault(c["key"], {"name": c["name"], "laps": 0, "speed": [], "ph": {}, "brake_turnin": [],
                                          "ramp": [], "rh_f": [], "rh_r": []})
            e["laps"] += 1
            e["speed"].append(m["min_kmh"])
            for ph in ("entry", "mid", "exit"):
                if ph in r and r[ph]["sym"]:
                    e["ph"].setdefault(ph, {}).setdefault(r[ph]["sym"], 0)
                    e["ph"][ph][r[ph]["sym"]] += 1
            if r.get("brake_at_turnin") is not None:
                e["brake_turnin"].append(r["brake_at_turnin"])
            if r.get("throttle_ramp_s") is not None:
                e["ramp"].append((r["throttle_ramp_s"], r.get("steer_at_full", 0)))
            if r.get("rh_front_min") is not None:
                e["rh_f"].append(r["rh_front_min"])
            if r.get("rh_rear_min") is not None:
                e["rh_r"].append(r["rh_rear_min"])
    sess._diag = res
    sess._diag_tr = sess.trace(laps[-1]["n"]) if laps else None
    return res


# ---------------------------------------------------------------- advice
def _fix(kind, sym, phase, fast, S, tr):
    """-> (main suggestion, alternative) as text with current values."""
    cur = lambda label, v: f" (now {v})" if v not in (None, "", "None") else ""
    if kind == "gtp":
        farb, rarb = incar(tr, "dcAntiRollFront"), incar(tr, "dcAntiRollRear")
        bias = S("BrakePressureBias"); mig = S("BrakeBiasMigration"); wing = S("RearWingAngle")
        pre = S("Preload"); ramps = S("CoastDriveRampAngles"); tc2 = S("TractionControlSlip")
        table = {
            ("understeer", "entry"): (f"Brake migration one click more negative{cur('', mig)}, so the rear does more of the braking as you trail off.",
                                      f"Or front roll bar (FARB on the dash) one step softer{cur('', farb)}."),
            ("oversteer", "entry"): (f"Brake bias half a percent forward{cur('', bias)}.",
                                     f"Or migration one click towards zero{cur('', mig)}, or a little more diff preload{cur('', pre)}."),
            ("understeer", "mid", False): (f"Front roll bar (FARB) one step softer from the cockpit{cur('', farb)}.",
                                           f"Or rear roll bar (RARB) one step stiffer{cur('', rarb)}."),
            ("understeer", "mid", True): ("A little more rake: rear pushrod up a touch. That moves the aero balance forward for the fast corners.",
                                          f"Or one click less rear wing{cur('', wing)}."),
            ("oversteer", "mid", False): (f"Rear roll bar (RARB) one step softer from the cockpit{cur('', rarb)}.",
                                          f"Or front roll bar one step stiffer{cur('', farb)}."),
            ("oversteer", "mid", True): (f"One click more rear wing{cur('', wing)}.",
                                         "Or a little less rake: rear pushrod down a touch."),
            ("understeer", "exit"): (f"Higher drive ramp angle for less diff locking on power{cur('', ramps)}.",
                                     f"Or front roll bar one step softer{cur('', farb)}."),
            ("oversteer", "exit"): (f"Traction control slip (TC2) one step up so it catches the rear earlier{cur('', tc2)}.",
                                    f"Or a little less diff preload{cur('', pre)}, or rear roll bar one step softer{cur('', rarb)}."),
        }
    else:
        bias = S("BrakePressureBias", "BrakeBias"); wing = S("RearWingAngle", "RearWingPosition", "WingSetting")
        farb = S("FrontArb", "ArbBlades", "ArbSetting"); pre = S("Preload", "DiffPreload")
        abs_ = incar(tr, "dcABS"); tc = incar(tr, "dcTractionControl")
        table = {
            ("understeer", "entry"): (f"Brake bias half a percent rearward{cur('', bias)}.",
                                      f"If ABS is working a lot here, one step less ABS{cur('', abs_)}; or a softer front anti-roll bar."),
            ("oversteer", "entry"): (f"Brake bias half a percent forward{cur('', bias)}.",
                                     f"Or a little more diff preload{cur('', pre)}."),
            ("understeer", "mid", False): ("Front anti-roll bar one step softer.", "Or rear anti-roll bar one step stiffer."),
            ("understeer", "mid", True): ("Raise the rear ride height a little for more rake (aero balance forward).",
                                          f"Or one click less rear wing{cur('', wing)}."),
            ("oversteer", "mid", False): ("Rear anti-roll bar one step softer.", "Or front anti-roll bar one step stiffer."),
            ("oversteer", "mid", True): (f"One click more rear wing{cur('', wing)}.", "Or lower the rear ride height a little."),
            ("understeer", "exit"): ("Front anti-roll bar one step softer.", f"Or a little less diff preload{cur('', pre)}."),
            ("oversteer", "exit"): (f"Traction control one step more intervention{cur('', tc)}.",
                                    f"Or a little less diff preload{cur('', pre)}, or a softer rear anti-roll bar."),
        }
    key = (sym, phase, fast) if phase == "mid" else (sym, phase)
    return table.get(key, (None, None))


def corner_advice(sess, corner_key):
    """Mechanic notes for one corner (list of strings)."""
    diag = diagnose(sess)
    e = diag.get(corner_key)
    if not e or e["laps"] == 0:
        return []
    tr = sess._diag_tr
    S = lambda *n: setup_value(sess, *n)
    kind = car_kind(sess)
    fast = float(np.median(e["speed"])) > 165
    notes = []
    for ph in ("entry", "mid", "exit"):
        counts = e["ph"].get(ph, {})
        if not counts:
            continue
        sym, n = max(counts.items(), key=lambda kv: kv[1])
        need = max(MIN_REPEAT, int(np.ceil(e["laps"] * 0.5)))
        where = {"entry": "on entry", "mid": "mid-corner", "exit": "on the exit"}[ph]
        if n < need:
            if n >= 1 and e["laps"] >= 2:
                notes.append(f"Some {sym} {where} ({n}/{e['laps']} laps). Not consistent: no change.")
            continue
        # technique first
        if sym == "understeer" and ph == "entry" and e["brake_turnin"] and np.median(e["brake_turnin"]) > 0.35:
            notes.append(f"Understeer {where} ({n}/{e['laps']} laps) with ~{np.median(e['brake_turnin']) * 100:.0f}% brake at turn-in: technique. Release the brake earlier.")
            continue
        if sym == "oversteer" and ph == "exit" and e["ramp"]:
            fastramp = [r for r in e["ramp"] if r[0] < 0.25 and r[1] > 0.6]
            if len(fastramp) >= max(1, len(e["ramp"]) // 2):
                notes.append(f"Oversteer {where} ({n}/{e['laps']} laps): throttle too fast with lock on: technique. Unwind, then squeeze.")
                continue
        main, alt = _fix(kind, sym, ph, fast, S, tr)
        if main:
            notes.append(f"{sym.capitalize()} {where} ({n}/{e['laps']} laps, {'fast' if fast else 'slow'} corner). "
                         f"Try: {main} {alt or ''}".strip().replace("  ", " "))
    # bottoming
    if e["rh_f"] and np.median(e["rh_f"]) < 0.003:
        notes.append("Front close to the ground here. If it scrapes: "
                     + ("a stiffer front heave spring or a touch more front ride height." if kind == "gtp" else "a little more front ride height or stiffer front springs."))
    if e["rh_r"] and np.median(e["rh_r"]) < 0.0:
        notes.append("Rear bottoming here. " + ("A stiffer rear third spring or a touch more rear ride height." if kind == "gtp"
                                                         else "A little more rear ride height or stiffer rear springs."))
    return notes[:3]


def car_summary(sess):
    """Overall balance across the lap: what the car does most."""
    diag = diagnose(sess)
    tally = {}
    for e in diag.values():
        for ph, counts in e["ph"].items():
            for sym, n in counts.items():
                if n >= max(MIN_REPEAT, int(np.ceil(e["laps"] * 0.5))):
                    spd = "fast" if np.median(e["speed"]) > 165 else "slow"
                    tally.setdefault((sym, ph, spd), []).append(e["name"])
    out = []
    for (sym, ph, spd), names in sorted(tally.items(), key=lambda kv: -len(kv[1])):
        if len(names) >= 2:
            out.append(f"{sym.capitalize()} {'on entry' if ph == 'entry' else 'mid-corner' if ph == 'mid' else 'on exit'} in {spd} corners: {', '.join(names)}.")
    return out


def advise_section(sess, lap_n, sec):
    for c in sec.get("corners", []):
        key = next((x["key"] for x in sess.find_corners() if x["name"] == c["name"]), None)
        if key:
            c["mech"] = corner_advice(sess, key)
    return sec
