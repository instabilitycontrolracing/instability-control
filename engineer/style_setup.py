"""Style setup (2026-10-28, #491, Angelo: "a setup thing ... where it analyzes my driving style and gives me a custom
setup to accommodate my driving style weaknesses").

No AI. It reads your own telemetry for one car across your recent sessions (any track), measures HOW you drive with
the mechanic's corner reads (mechanic.py) plus your brake and throttle traces, and turns the patterns that keep coming
back into a short, ordered setup sheet from the setup rulebook (setup_bank.py, iRacing's car manuals):

  1. Style traits - how deep you trail-brake, how fast you hit the brake and the throttle, how often you correct.
  2. Weaknesses   - what the car does to you most often (entry / mid / exit, under- or oversteer, slow or fast
                    corners), counted over every corner of every full lap, and only kept if it shows at more than one
                    session (one bad day is not your style).
  3. The sheet    - one change per weakness (the rulebook's first fix for this car that doesn't fight a change already
                    on the sheet), with your current value from your latest session and the reason in your own numbers.

Every number on the sheet is measured from your files; nothing is invented. Changes are one step / one click at a time.
"""
import numpy as np

from . import mechanic, setup_bank, telemetry

MIN_SESSIONS = 2          # a weakness must show in at least this many sessions
WEAK_RATE = 0.15          # ... and in at least this share of the corners measured
MAX_CHANGES = 4
MIN_READS = 3            # ... and at least this many corner reads (a pattern, not a one-off)

PH_WORD = {"entry": "on entry", "mid": "mid-corner", "exit": "on exit"}

# changes that contradict each other (same knob, opposite directions)
_OPPOSITE = [("bias", "forward", "rearward"), ("mig", "more negative", "towards zero"), ("mig", "more negative", "less negative"),
             ("preload", "more", "less"), ("farb", "softer", "stiffer"), ("rarb", "softer", "stiffer"),
             ("abs", "more", "less"), ("wing", "more", "less")]


def _direction(step):
    t = step["t"].lower()
    for key, a, b in _OPPOSITE:
        if (step.get("key") or "") == key or key in t:
            if a in t:
                return key, a
            if b in t:
                return key, b
    return (step.get("key") or step["t"]), None


def _brake_style(sess, laps):
    """Brake attack: seconds from first touch to 90 % of the peak, and the typical peak (0..1), per braking zone."""
    rise, peak = [], []
    for L in laps:
        try:
            tr = sess.trace(L["n"])
        except Exception:
            continue
        b, v = tr.get("Brake"), tr.get("Speed")
        if b is None or v is None or len(b) < 50:
            continue
        on = b > 0.05
        starts = np.flatnonzero(on[1:] & ~on[:-1]) + 1
        ends = np.flatnonzero(~on[1:] & on[:-1]) + 1
        for s in starts:
            e = ends[ends > s]
            e = int(e[0]) if len(e) else len(b)
            if e - s < 6 or v[s] < 25:                   # a real braking zone from speed, not a tap in the pits
                continue
            seg = b[s:e]; pk = float(seg.max())
            if pk < 0.3:
                continue
            k = int(np.argmax(seg >= 0.9 * pk))
            dist = (tr["d"][s + k] - tr["d"][s]) if "d" in tr else None
            if dist is not None and v[s] > 0:
                rise.append(float(dist / v[s])); peak.append(pk)
    return rise, peak


def _counter_rate(sess, laps):
    """Share of cornering time spent with opposite lock (corrections)."""
    n = c = 0
    for L in laps:
        try:
            tr = sess.trace(L["n"])
        except Exception:
            continue
        sw, yr, v = tr.get("SteeringWheelAngle"), tr.get("YawRate"), tr.get("Speed")
        if sw is None or yr is None or v is None:
            continue
        m = (v > 12) & (np.abs(yr) > 0.08)
        n += int(m.sum())
        c += int((m & (np.sign(sw) != np.sign(yr)) & (np.abs(sw) > 0.03)).sum())
    return (c / n) if n else None


def sessions_for(car_path, limit=6, sessions=None):
    """Your recent recordings of this car (any track), newest first; real driving only (no replay recordings)."""
    out = []
    for s in (sessions or telemetry.list_sessions)():
        p = s["path"]
        if not p.lower().endswith(".ibt"):
            continue
        if car_path and s.get("car") and s["car"].lower() != car_path.lower():
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def build(car_path=None, limit=6, sessions=None, open_fn=None, log=print):
    """-> the style sheet dict (see module doc). car_path None = the car of your newest recording."""
    open_fn = open_fn or (lambda p: telemetry.Session(p))
    if car_path is None:
        for s in (sessions or telemetry.list_sessions)():
            if s["path"].lower().endswith(".ibt") and s.get("car") not in (None, "?"):
                car_path = s["car"]; break
    paths = sessions_for(car_path, limit, sessions)
    tally, measured = {}, {}           # (sym, ph, band) -> {"n": corner-laps, "sessions": set, "corners": set}; (ph, band) -> n
    turnin, ramps, rise, peak, counters = [], [], [], [], []
    used, latest, car_name, kind = [], None, car_path, None
    for p in paths:
        try:
            se = open_fn(p)
        except Exception as e:
            log(f"[style setup] {p}: {e!r}")
            continue
        laps = [L for L in se.laps if L.get("complete") and not L.get("pit")]
        if len(laps) < 2:
            continue
        try:
            diag = mechanic.diagnose(se)
        except Exception as e:
            log(f"[style setup] diagnose {p}: {e!r}")
            continue
        if not diag:
            continue
        if latest is None:
            latest, car_name, kind = se, se.car, mechanic.car_kind(se)
        used.append({"track": se.track_display, "laps": len(laps), "path": p})
        sid = len(used)
        for e in diag.values():
            band = "fast" if np.median(e["speed"]) > 165 else "slow"
            for ph in ("entry", "mid", "exit"):
                measured[(ph, band)] = measured.get((ph, band), 0) + e["laps"]
            for ph, counts in e["ph"].items():
                for sym, n in counts.items():
                    t = tally.setdefault((sym, ph, band), {"n": 0, "sessions": set(), "corners": set()})
                    t["n"] += n; t["sessions"].add(sid); t["corners"].add(f"{e['name']} ({se.track_display})")
            turnin += [x for x in e["brake_turnin"] if x is not None]
            ramps += e["ramp"]
        r, pk = _brake_style(se, laps[-6:])
        rise += r; peak += pk
        cr = _counter_rate(se, laps[-6:])
        if cr is not None:
            counters.append(cr)
    if not used:
        return {"ok": False, "car": car_name, "why": "No full laps of this car in your recordings yet. Drive a few clean laps and try again."}

    # ---- style traits (measured)
    traits = []
    if turnin:
        ti = float(np.median(turnin))
        lab = "Deep trail-braker" if ti > 0.30 else "Light trail-braker" if ti > 0.10 else "Off the brake before turn-in"
        traits.append({"k": "trail", "label": lab, "v": ti, "detail": f"About {ti * 100:.0f}% brake still on as you start turning (median over {len(turnin)} corners)."})
    if rise:
        rs = float(np.median(rise))
        lab = "Stabs the brake" if rs < 0.12 else "Squeezes the brake on" if rs > 0.30 else "Firm, quick brake application"
        traits.append({"k": "attack", "label": lab, "v": rs, "detail": f"{rs:.2f} s from first touch to full pressure, peak about {np.median(peak) * 100:.0f}% (median over {len(rise)} braking zones)."})
    if ramps:
        fast = [x for x in ramps if x[0] < 0.25 and x[1] > 0.6]
        fr = len(fast) / len(ramps)
        med = float(np.median([x[0] for x in ramps]))
        lab = "Early, aggressive throttle" if fr > 0.35 else "Patient on the throttle" if fr < 0.10 else "Balanced throttle"
        traits.append({"k": "throttle", "label": lab, "v": fr, "detail": f"Partial to full throttle in {med:.2f} s; {fr * 100:.0f}% of exits go full throttle with a lot of lock still on."})
    if counters:
        cr = float(np.median(counters))
        lab = "Lots of corrections" if cr > 0.10 else "Smooth hands" if cr < 0.04 else "Some corrections"
        traits.append({"k": "corr", "label": lab, "v": cr, "detail": f"Opposite lock {cr * 100:.0f}% of the time you're cornering."})

    # ---- weaknesses: repeated across sessions and a real share of the corners
    weak = []
    for (sym, ph, band), t in tally.items():
        tot = measured.get((ph, band), 0)
        rate = t["n"] / tot if tot else 0
        if rate >= WEAK_RATE and t["n"] >= MIN_READS and (len(t["sessions"]) >= MIN_SESSIONS or len(used) == 1):
            weak.append({"sym": sym, "ph": ph, "band": band, "rate": rate, "n": t["n"], "of": tot,
                         "sessions": len(t["sessions"]), "corners": sorted(t["corners"])[:4],
                         "label": f"{sym.capitalize()} {PH_WORD[ph]} in {band} corners"})
    weak.sort(key=lambda w: -w["rate"])

    # ---- the sheet: the rulebook's first fix per weakness that doesn't fight one already chosen
    kind = kind or "other"
    bank = {p["id"]: p for p in setup_bank.bank_for(kind)["problems"]}
    vals = setup_bank.current_values(latest) if latest is not None else {}
    tmap = {t["k"]: t for t in traits}
    chosen, knobs, changes = set(), {}, []
    for w in weak:
        pid = setup_bank.FROM_DETECTION.get((w["sym"], w["ph"], w["band"])) or setup_bank.FROM_DETECTION.get((w["sym"], w["ph"]))
        prob = bank.get(pid)
        if not prob or pid in chosen:
            continue
        for st in prob["steps"]:
            knob, way = _direction(st)
            if knob in knobs and knobs[knob] != way:
                continue                                   # would undo a change already on the sheet
            if knob in knobs:
                continue                                   # same change already there
            why = f"{w['label']}: {w['n']} of {w['of']} corner reads ({w['rate'] * 100:.0f}%) over {w['sessions']} session(s)."
            tech = None
            # the style note only where it explains the problem
            if w["ph"] == "entry" and "trail" in tmap and ((w["sym"] == "understeer" and tmap["trail"]["v"] > 0.30) or (w["sym"] == "oversteer" and tmap["trail"]["v"] > 0.20)):
                tech = tmap["trail"]["detail"]
            elif w["ph"] == "exit" and w["sym"] == "oversteer" and "throttle" in tmap and tmap["throttle"]["v"] > 0.20:
                tech = tmap["throttle"]["detail"]
            elif w["ph"] == "entry" and "attack" in tmap and tmap["attack"]["v"] < 0.12:
                tech = tmap["attack"]["detail"]
            changes.append({"t": st["t"], "where": st.get("where"), "now": vals.get(st.get("key")) if st.get("key") else None,
                            "why": why, "style": tech, "rule": st.get("why") or "", "for": w["label"]})
            knobs[knob] = way; chosen.add(pid)
            break
        if len(changes) >= MAX_CHANGES:
            break

    notes = []
    if "trail" in tmap and tmap["trail"]["v"] > 0.30 and any(w["sym"] == "understeer" and w["ph"] == "entry" for w in weak):
        notes.append("Some of the entry understeer is the deep trail braking itself: the setup can help, releasing a little earlier helps more.")
    if "throttle" in tmap and tmap["throttle"]["v"] > 0.35 and any(w["sym"] == "oversteer" and w["ph"] == "exit" for w in weak):
        notes.append("The exit oversteer comes with full throttle while there's still lock on: the setup makes it calmer, unwinding first is free time.")
    if not weak:
        notes.append("No weakness repeats across your sessions: the car suits how you drive. Keep the setup and work on consistency.")
    notes.append("Make one change, run 3 laps, compare in Analysis. Keep it only if the lap is faster or the car is easier.")
    return {"ok": True, "car": car_name, "kind": kind, "sessions": [{"track": u["track"], "laps": u["laps"]} for u in used],
            "traits": traits, "weak": [{k: w[k] for k in ("label", "rate", "n", "of", "sessions", "corners")} for w in weak[:5]],
            "changes": changes, "notes": notes}
