"""Pre-race meeting, post-race debrief and "what if" answers (2026-10-24).

Fixed code does all the judgement here: strategy maths from strategy.py (your own laps and stops), memory from
memory.py, mechanic notes from mechanic.py. The result is a FACTS PACK: short sections of plain sentences.
- With the team AI loaded, the pack is the DATA the model talks through (it may not add numbers of its own).
- Without it, the Team tab shows the same pack as plain text.
"""
import math, re

from . import strategy as S
from . import memory as M

MEETING_RULES = {
    "prerace": ("This is the PRE-RACE MEETING. Talk the driver through the race plan and how to be fastest here, using only the "
                "facts below: first the strategy (stops, fuel, pit loss, tyres), then where he usually loses time and what to "
                "focus on, then one setup point only if it is under MECHANIC RECOMMENDATIONS. Strategy numbers come from the "
                "strategy code: repeat them, never recalculate or invent them. For a 'what if' question use the WHAT-IF ANSWER "
                "block when there is one; if there isn't, say the strategy code didn't work that one out."),
    "debrief": ("This is the POST-RACE DEBRIEF. Go through what happened using only the facts below: result, stints and stops, "
                "incidents, spins and offs, where the time went, fuel and tyres, and what he said on the radio. Finish with the "
                "one or two things to work on next time. Setup changes only from MECHANIC RECOMMENDATIONS."),
}


def fmt_lap(t):
    return f"{int(t // 60)}:{t % 60:06.3f}" if t else "-"


def _vol(l, metric=True):
    return f"{l:.1f} L" if metric else f"{l / 3.785:.2f} gal"


# ---------------------------------------------------------------- the strategy maths
def strategy_model(car, track, cls=None, mem=None):
    """Your model here; else a same-class car's model here (rough guide); else one built from memory. -> (m, source, from_car)"""
    m = S.model(car, track) if car and track else dict(S.DEFAULTS, n=0, learned=[])
    if m.get("fuel_lap") and m.get("base"):
        return m, M.THIS_CAR, None
    sm, other = M.similar_model(car, track, cls)
    if sm:
        return sm, M.SIMILAR, other
    ag = (mem or {}).get("aggregates") or {}
    if ag.get("fuel_lap") and (ag.get("typical") or ag.get("best")):
        m = dict(S.DEFAULTS, n=0, learned=[], car=car, track=track)
        if ag.get("tyre_deg") is not None:
            m["tyre_deg"] = ag["tyre_deg"]
        if ag.get("pit_loss"):
            m["lane_loss"] = ag["pit_loss"]
        m["fuel_lap"] = ag["fuel_lap"]
        typ = ag.get("typical") or ag["best"] * 1.015
        tank = ag.get("tank") or 100
        m["base"] = typ - m["fuel_effect"] * tank / 2 - m["tyre_deg"] * 5
        m["best"] = ag.get("best")
        return m, (mem or {}).get("source", M.THIS_CAR), None
    return None, M.NONE, None


def race_maths(m, race_s, tank, fuel_now=None, temp=None, max_stops=None):
    """Everything the meeting needs from the strategy code. -> dict (ok False + why when it can't)."""
    if not m or not m.get("fuel_lap"):
        return {"ok": False, "why": "no fuel figure for this car here yet - do a few clean laps first"}
    if not tank:
        return {"ok": False, "why": "tank size unknown until you're in the car"}
    fl = m["fuel_lap"]
    fuel_now = fuel_now or tank
    plans = S.best_plans(m, race_s, tank, fuel_now, 0, 0.0, temp, 0, max_stops=max_stops)
    if not plans:
        return {"ok": False, "why": "no plan reaches the flag with this tank"}
    a = plans[0]["res"]
    laps = a["laps"]
    per_tank = tank / fl
    stops = a["stops"]
    stop_cost = [s["time"] for s in stops]
    out = {"ok": True, "fuel_lap": fl, "per_tank": per_tank, "laps": laps, "race_s": race_s, "tank": tank,
           "fuel_now": fuel_now, "plans": plans, "stops": len(stops), "stop_laps": [s["lap"] for s in stops],
           "lane_loss": m["lane_loss"], "stop_cost": stop_cost, "tyre_time": m["tyre_time"], "fuel_rate": m["fuel_rate"],
           "tyre_deg": m["tyre_deg"], "learned": list(m.get("learned") or []), "base": m.get("base"),
           "fuel_total": laps * fl}
    # fuel window for the first stop: earliest = the rest still fits in the remaining tanks, latest = this tank runs dry
    if stops:
        n = len(stops)
        earliest = max(1, math.ceil(laps - n * per_tank))
        latest = max(1, int(fuel_now / fl - 0.3))
        out["window"] = (min(earliest, latest), latest)
    # tyre fade over the longest stint, and the undercut
    stint = max([b - a_ for a_, b in zip([0] + out["stop_laps"], out["stop_laps"] + [laps])] or [laps])
    out["stint_max"] = stint
    out["fade_stint"] = m["tyre_deg"] * stint
    warm = 1.0
    try:
        from . import warmup as W
        w = W.estimate(m.get("car"), m.get("track")) if m.get("car") else None
        if w and w.get("first_lap_loss"):
            warm = float(w["first_lap_loss"])
    except Exception:
        pass
    out["warm_loss"] = warm
    if stops and any(s["tyres"] for s in stops) and m["tyre_deg"] > 0:
        age = out["stop_laps"][0]                       # the planned first stint
        gain = m["tyre_deg"] * age - warm               # fresh tyres vs a rival's worn ones, on your out-lap
        out["undercut"] = {"gain": gain, "age": age, "works": gain > 0.2}
    else:
        out["undercut"] = None
    return out


def strategy_lines(sm, metric=True):
    if not sm.get("ok"):
        return [f"Strategy: {sm.get('why')}."]
    L = []
    L.append(f"Race: {sm['race_s'] / 60:.0f} minutes, about {sm['laps']} laps. Fuel per lap {_vol(sm['fuel_lap'], metric)}, "
             f"a full tank ({_vol(sm['tank'], metric)}) lasts {sm['per_tank']:.1f} laps; the race needs about {_vol(sm['fuel_total'], metric)}.")
    for i, o in enumerate(sm["plans"]):
        d = S.describe(o, metric, "ABC"[i])
        extra = f" ({d['vs_a']:+.0f} s vs plan A)" if i and d["vs_a"] < 900 else ""
        L.append(f"Plan {d['name']}: {d['text']}{extra}.")
    if sm["stops"]:
        lane = sm["lane_loss"]
        L.append(f"Pit loss: {lane:.0f} s in the lane plus the stop itself; each stop in plan A costs "
                 + ", ".join(f"{c:.0f} s" for c in sm["stop_cost"]) + " in total.")
        if sm.get("window"):
            e, l = sm["window"]
            L.append(f"Fuel window for the first stop: lap {e} to lap {l}.")
    else:
        L.append("No stop needed: a tank covers the race.")
    if sm["tyre_deg"]:
        L.append(f"Tyre fade: about {sm['tyre_deg']:.2f} s a lap slower for every lap on a set; over a {sm['stint_max']}-lap stint "
                 f"that's about {sm['fade_stint']:.1f} s a lap by the end.")
    u = sm.get("undercut")
    if u:
        if u["works"]:
            L.append(f"Undercut: fresh tyres are worth about {u['gain']:.1f} s on the out-lap against a car on {u['age']}-lap-old tyres, "
                     f"so stopping a lap before the car ahead can work.")
        else:
            L.append("Undercut: the tyres don't fade enough here for an early stop to gain time; stopping a lap early only costs fuel laps.")
    if sm["learned"]:
        L.append("Learned from your own laps: " + ", ".join(sm["learned"]) + ". The rest uses standard values.")
    else:
        L.append("These numbers use standard values for pit loss and tyre wear (not learned from your laps yet).")
    return L


# ---------------------------------------------------------------- "what if"
_N = {"no": 0, "zero": 0, "one": 1, "single": 1, "two": 2, "double": 2, "three": 3, "four": 4, "five": 5}
CAUTION_FUEL = 0.5          # a caution lap uses about half the fuel of a racing lap
CAUTION_LAPS = 3            # typical length of a caution
CAUTION_PIT_SAVE = 0.6      # the field is slow, so a stop under caution costs ~60 % less time


def what_if(question, ctx):
    """Answer a 'what if' with the strategy maths. ctx = the meeting's {"m", "sm", "metric", "car", "track"}.
    -> {"kind", "lines"} or None when the question isn't one the code can work out."""
    q = " " + re.sub(r"[^a-z0-9 ]+", " ", (question or "").lower()) + " "
    m, sm, metric = ctx.get("m"), ctx.get("sm") or {}, ctx.get("metric", True)
    if not m or not sm.get("ok"):
        if any(w in q for w in (" rain", " wet", " stop", " caution", " safety car", " yellow", " tyre", " tire", " hot", " cold")):
            return {"kind": "none", "lines": [f"I can't work that out yet: {sm.get('why') or 'no strategy data for this car here'}."]}
        return None
    race_s, tank, fuel_now = sm["race_s"], sm["tank"], sm["fuel_now"]
    # rain
    if any(w in q for w in (" rain", " wet ", " wets", " storm", " shower")):
        from . import rain as R
        try:
            mine, _ = R.wet_pace(m.get("car"), m.get("track"))
        except Exception:
            mine = {}
        lines = R.rain_plan(m, sm["plans"][0]["res"], race_s, 100, mine) or []
        return {"kind": "rain", "lines": ["If it rains: " + (lines[0] if lines else "take wets once the track is lightly wet.")] + lines[1:]}
    # caution / safety car / full course yellow
    if any(w in q for w in (" caution", " safety car", " yellow", " fcy", " full course", " pace car")):
        lane = m["lane_loss"]
        save = lane * CAUTION_PIT_SAVE
        fuel_gain = CAUTION_LAPS * sm["fuel_lap"] * (1 - CAUTION_FUEL)
        L = [f"Under a caution a stop costs about {lane - save:.0f} s instead of {lane:.0f} s, because the field is slow.",
             f"A {CAUTION_LAPS}-lap caution saves about {_vol(fuel_gain, metric)} of fuel, roughly {fuel_gain / sm['fuel_lap']:.1f} laps."]
        if sm.get("window"):
            e, l = sm["window"]
            L.append(f"If it comes between lap {e} and lap {l} (the fuel window), box under it: you save about {save:.0f} s on plan A.")
            if e > 1:
                L.append(f"Before lap {e} a stop under caution would need an extra stop later (you can't reach the end from there), so stay out unless it's within 2 laps of the window.")
        else:
            L.append("Plan A has no stop, so a caution only saves fuel; stay out.")
        L.append("Note: the plan assumes no cautions - in IMSA on iRacing they are rare.")
        return {"kind": "caution", "lines": L}
    # number of stops
    mm = re.search(r" (no|zero|one|single|two|double|three|four|five|\d) (stop|stops|pit|pits|pit stop|pit stops) ", q)
    once = re.search(r" (stop|pit|box) (once|twice) ", q)
    if mm or once or " no stop" in q or " don t stop" in q:
        if mm:
            n = _N[mm.group(1)] if mm.group(1) in _N else int(mm.group(1))
        else:
            n = {"once": 1, "twice": 2}[once.group(2)] if once else 0
        return {"kind": "stops", "lines": _forced_stops(m, sm, n, metric)}
    # tyres or no tyres
    if any(w in q for w in (" tyre", " tire", " tyres", " tires", " double stint", " fuel only")):
        no = any(w in q for w in (" no tyre", " no tire", " no new", " keep the tyre", " keep the tire", " fuel only", " double stint", " without tyre", " without tire"))
        return {"kind": "tyres", "lines": _tyre_choice(m, sm, not no, metric)}
    # hotter / cooler
    mt = re.search(r" (\d{1,2}) ?(degrees|deg|c) ", q)
    if any(w in q for w in (" hot", " hotter", " warmer", " cold", " colder", " cooler", " temperature", " temp ")):
        d = float(mt.group(1)) if mt else 10.0
        if any(w in q for w in (" cold", " colder", " cooler")):
            d = -d
        return {"kind": "temp", "lines": _temp_change(m, sm, d, metric)}
    # longer / shorter race
    mr = re.search(r" (\d{2,3}) ?(minute|minutes|min|mins) ", q)
    if mr and any(w in q for w in (" race", " long", " short", " minute", " min")):
        mins = int(mr.group(1))
        sm2 = race_maths(m, mins * 60, tank, fuel_now)
        return {"kind": "length", "lines": [f"A {mins}-minute race:"] + strategy_lines(sm2, metric)[:3]}
    return None


def _forced_stops(m, sm, n, metric):
    fl, tank, laps = sm["fuel_lap"], sm["tank"], sm["laps"]
    need_save = (1 - (sm["fuel_now"] + n * tank) / (laps * fl + 0.5 * fl)) * 100
    plans = S.best_plans(m, sm["race_s"], tank, sm["fuel_now"], 0, 0.0, None, 0, max_stops=n)
    hit = [o for o in plans if len(o["res"]["stops"]) == n]
    # best_plans only tries up to 8 % fuel saving; say how much it would take when that isn't enough
    if not hit:
        if need_save > 0:
            return [f"{n} stop{'s' if n != 1 else ''} isn't possible: a tank lasts {sm['per_tank']:.1f} laps and the race is about {laps} laps.",
                    f"You'd have to save about {need_save:.0f} percent fuel every lap, and the code only plans up to 8 percent.",
                    f"Plan A stays {sm['stops']} stop{'s' if sm['stops'] != 1 else ''}."]
        return [f"The strategy code found no {n}-stop plan that reaches the flag."]
    o = hit[0]
    d = S.describe(o, metric, "X")
    lead = sm["plans"][0]["res"]
    diff = o["res"]["time"] - lead["time"] if o["res"]["laps"] == lead["laps"] else None
    L = [d["text"][:1].upper() + d["text"][1:] + "."]
    if diff is not None and abs(diff) >= 0.5:
        L.append(f"That's {abs(diff):.0f} s {'slower' if diff > 0 else 'faster'} than plan A over the race.")
    elif diff is not None:
        L.append("About the same total time as plan A.")
    else:
        L.append(f"It finishes {lead['laps'] - o['res']['laps']} lap(s) down on plan A.")
    if o["plan"]["save"]:
        L.append(f"It needs {o['plan']['save']:.0f} percent fuel saving a lap, which costs about {o['plan']['save'] * m['save_cost']:.1f} s a lap.")
    return L


def _tyre_choice(m, sm, tyres, metric):
    if not sm["stops"]:
        return ["Plan A has no stop, so there is no tyre choice to make."]
    a = sm["plans"][0]
    plan = dict(a["plan"]); plan["tyres"] = [tyres] * len(plan["stops"])
    r = S.simulate(m, plan, sm["race_s"], sm["tank"], sm["fuel_now"], 0, 0.0, None, 0)
    if not r["ok"]:
        return ["That doesn't reach the flag."]
    diff = r["time"] - a["res"]["time"] if r["laps"] == a["res"]["laps"] else None
    per_stop = max(0.0, m["tyre_time"] - max(s["fuel"] for s in r["stops"]) / max(0.3, m["fuel_rate"]))
    what = "new tyres at every stop" if tyres else "fuel only (keep the tyres)"
    fuel_t = max(s["fuel"] for s in r["stops"]) / max(0.3, m["fuel_rate"])
    if per_stop < 0.5:
        L = [f"Tyres are free at these stops: refuelling takes about {fuel_t:.0f} s, longer than the tyre change ({m['tyre_time']:.0f} s), so new tyres cost nothing."]
    else:
        L = [f"With {what}: each stop changes by about {per_stop:.0f} s (tyres take {m['tyre_time']:.0f} s, fuel runs at the same time)."]
    if diff is not None:
        L.append(f"Over the race that's {abs(diff):.0f} s {'slower' if diff > 0 else 'faster'} than plan A as it is." if abs(diff) >= 0.5
                 else "Over the race it's about the same as plan A.")
    if not tyres:
        L.append(f"Old tyres: about {m['tyre_deg'] * sm['stint_max'] * 2:.1f} s a lap slower by the end of a double stint.")
    return L


def _temp_change(m, sm, d, metric):
    te = m.get("temp_effect", S.DEFAULTS["temp_effect"])
    per = te * d
    laps = sm["laps"]
    L = [f"Track {abs(d):.0f} degrees {'hotter' if d > 0 else 'cooler'}: about {abs(per):.2f} s a lap {'slower' if per > 0 else 'faster'}"
         + (" (learned from your laps)." if "temperature" in (sm.get("learned") or []) else " (standard value).")]
    if d > 0:
        L.append(f"Over {laps} laps that's about {abs(per) * laps:.0f} s; the tyres fade sooner in the heat, so look after the rears in the last laps of a stint.")
    else:
        L.append("Cold tyres take longer to come in: careful on the out-lap and the first lap.")
    L.append("Fuel per lap barely changes with temperature, so the stop plan stays the same.")
    return L


# ---------------------------------------------------------------- facts packs
def _mem_lines(mem, metric=True):
    ag = mem.get("aggregates") or {}
    if not ag.get("sessions"):
        return ["No sessions remembered for this car at this track yet."]
    src = mem.get("source")
    L = []
    if src == M.SIMILAR:
        L.append(f"ROUGH GUIDE: nothing stored for this car here, so these are from a similar car ({', '.join(mem.get('from_cars') or [])}).")
    L.append(f"{ag['sessions']} session{'s' if ag['sessions'] != 1 else ''} here ({ag.get('races', 0)} race{'s' if ag.get('races') != 1 else ''}), "
             f"{ag.get('laps', 0)} laps, last on {ag.get('last')}.")
    if ag.get("best"):
        L.append(f"Best lap {fmt_lap(ag['best'])}" + (f", typical {fmt_lap(ag['typical'])}." if ag.get("typical") else "."))
    if ag.get("trouble"):
        L.append("Where you usually lose time (your usual vs your best there): "
                 + "; ".join(f"{t['name']} {t['lost']:+.2f} s" for t in ag["trouble"][:3]) + ".")
    if ag.get("spins") or ag.get("offs"):
        L.append(f"On average {ag['spins']} spins and {ag['offs']} offs a session"
                 + (f", most at {', '.join(ag['hotspots'])}." if ag.get("hotspots") else "."))
    if ag.get("finishes"):
        L.append("Recent finishes here: " + ", ".join(f"P{p}" for p in ag["finishes"]) + ".")
    if ag.get("setup"):
        L.append(f"Last setup used: {ag['setup']}.")
    if ag.get("track_temp"):
        L.append(f"Your laps here were mostly at about {ag['track_temp']:.0f} degrees track temperature.")
    return L


def _notes_lines(notes):
    out = []
    for n in notes[:8]:
        where = " ".join(x for x in (f"lap {n['lap']}" if n.get("lap") else "", f"at {n['corner']}" if n.get("corner") else "") if x)
        out.append(f"{(n.get('date') or '')[:10]} {where}: \"{n.get('text')}\"".strip())
    return out


def mech_lines(recs):
    return ["MECHANIC RECOMMENDATIONS (the only setup changes allowed):" + ("" if recs else " none - the car is consistent, the time is in the driving.")] \
        + [f"- {r}" for r in recs[:6]]


def prerace_pack(car, track, car_name=None, track_name=None, cls=None, race_s=None, race_label=None, tank=None, fuel_now=None,
                 temp=None, metric=True, mech=None, mech_summary=None, race_laps=None):
    """Everything for the pre-race meeting. -> {"kind", "title", "source", "sections": [{"h", "lines"}], "ctx"}"""
    mem = M.recall(car, track, cls)
    ag = mem.get("aggregates") or {}
    m, msrc, mcar = strategy_model(car, track, cls, mem)
    tank = tank or ag.get("tank")
    label = race_label or ""
    if not race_s and race_laps and m and m.get("base"):
        # a lap race: the simulation runs on time, so give it the time those laps take at your pace (a hair under)
        race_s = race_laps * S.lap_time(m, (tank or 100) / 2, 5, temp) - 1
        label = f"this event ({race_laps} laps)"
    if not race_s:
        ev = S.last_race(car, track) if car and track else None
        race_s = (ev or {}).get("race_s")
        label = "your last race here" if race_s else "assumed 45 minutes (race length unknown)"
        race_s = race_s or 45 * 60
    sm = race_maths(m, race_s, tank, fuel_now, temp) if m else {"ok": False, "why": "no laps stored for this car here yet"}
    strat = strategy_lines(sm, metric)
    if label:
        strat.insert(0, f"Race length from {label}.")
    if msrc == M.SIMILAR and m:
        strat.insert(0, f"ROUGH GUIDE: no laps of this car here, so the strategy uses your laps in the {M.car_name(mcar)} (same class).")
    sections = [{"h": "Strategy", "lines": strat},
                {"h": "Your history here", "lines": _mem_lines(mem, metric)}]
    focus = []
    if ag.get("trouble"):
        t = ag["trouble"][0]
        focus.append(f"Biggest gain: {t['name']}, {t['lost']:.2f} s between your usual and your best there.")
    if ag.get("hotspots"):
        focus.append(f"Keep it on the track at {ag['hotspots'][0]}: that's where most of your spins and offs happen.")
    if ag.get("best") and ag.get("typical"):
        focus.append(f"Consistency: your typical lap is {ag['typical'] - ag['best']:.2f} s off your best here.")
    if focus:
        sections.append({"h": "How to be fastest here", "lines": focus})
    mech_part = []
    if mech_summary:
        mech_part.append("Mechanic's read of the car: " + " ".join(mech_summary))
    mech_part += mech_lines(mech or [])
    sections.append({"h": "Car", "lines": mech_part})
    nl = _notes_lines(ag.get("notes") or [])
    if nl:
        sections.append({"h": "Your radio notes here", "lines": nl})
    return {"kind": "prerace", "title": "Pre-race meeting", "car": car_name or car, "track": track_name or mem.get("track_name") or track,
            "source": mem.get("source"), "strategy_source": msrc, "sections": sections,
            "ctx": {"m": m, "sm": sm, "metric": metric, "car": car, "track": track}}


def debrief_pack(s, metric=True, mech=None):
    """Everything for the post-race debrief, from one stored session summary (memory.summarise)."""
    if not s:
        return {"kind": "debrief", "title": "Debrief", "sections": [{"h": "Debrief", "lines": ["No session stored yet. Drive a session first."]}], "ctx": {}}
    mem = M.recall(s["car"], s["track"], s.get("cls"))
    ag = mem.get("aggregates") or {}
    rc = s.get("race") or {}
    sec = []
    res = []
    if rc.get("pos"):
        line = f"Finished P{rc['pos']} in class"
        if rc.get("start_pos"):
            d = rc["start_pos"] - rc["pos"]
            line += f", started P{rc['start_pos']} ({'+' if d > 0 else ''}{d} place{'s' if abs(d) != 1 else ''})" if d else f", same as the start"
        res.append(line + ".")
    if rc.get("best_rank"):
        res.append(f"Your best lap was {rc['best_rank']}{_th(rc['best_rank'])} fastest in class" + (" - fastest lap of the race." if rc.get("fastest_me") else "."))
    if rc.get("ir") is not None and abs(rc["ir"]) >= 3:
        res.append(f"iRating about {rc['ir']:+.0f}.")
    if res:
        sec.append({"h": "Result", "lines": res})
    pace = [f"{s['laps']} laps, {s['clean_laps']} clean."]
    if s.get("best"):
        pace.append(f"Best {fmt_lap(s['best'])}" + (f", typical {fmt_lap(s['median'])}" if s.get("median") else "") + ".")
    if ag.get("best") and s.get("best") and ag["sessions"] > 1:
        d = s["best"] - ag["best"]
        pace.append("That's your best ever here." if d <= 0.0005 else f"Your best ever here is {fmt_lap(ag['best'])} ({d:+.3f} s).")
    sec.append({"h": "Laps and pace", "lines": pace})
    st = []
    stops = s.get("stops") or []
    if stops:
        st.append(f"{len(stops)} stop{'s' if len(stops) != 1 else ''}: " + ", ".join(
            f"lap {p['lap']} ({p['still']:.0f} s stopped, {_vol(p['fuel'], metric)} in)" for p in stops) + ".")
    elif "race" in str(s.get("session", "")).lower():
        st.append("No stop.")
    if s.get("stints"):
        st.append("Stints: " + ", ".join(f"{n} laps" for n in s["stints"]) + ".")
    if s.get("pit_loss"):
        st.append(f"Pit lane loss here: {s['pit_loss']:.0f} s (from your stops).")
    if st:
        sec.append({"h": "Stints and stops", "lines": st})
    inc = [f"{s.get('incidents', 0)} incident point{'s' if s.get('incidents') != 1 else ''}."]
    if s.get("spins"):
        inc.append(f"{s['spins']} spin{'s' if s['spins'] != 1 else ''}" + (f": {', '.join(s['spin_at'])}." if s.get("spin_at") else "."))
    if s.get("offs"):
        inc.append(f"{s['offs']} off{'s' if s['offs'] != 1 else ''} (track limits)" + (f": {', '.join(dict.fromkeys(s['off_at']))}." if s.get("off_at") else "."))
    if not s.get("spins") and not s.get("offs") and not s.get("incidents"):
        inc = ["Clean: no incidents, spins or offs."]
    sec.append({"h": "Incidents", "lines": inc})
    if s.get("corners"):
        sec.append({"h": "Where the time went", "lines": ["Time lost per corner (your usual vs your best there, clean laps):"]
                    + [f"{c['name']}: {c['lost']:+.2f} s" for c in s["corners"][:5]]})
    ft = []
    if s.get("fuel_lap"):
        ft.append(f"Fuel per lap {_vol(s['fuel_lap'], metric)}" + (f" (usual here {_vol(ag['fuel_lap'], metric)})." if ag.get("fuel_lap") and ag["sessions"] > 1 else "."))
    if rc.get("fuel_left") and rc["fuel_left"] >= 1:
        ft.append(f"{_vol(rc['fuel_left'], metric)} left at the flag" + (f", about {rc['fuel_left'] / s['fuel_lap']:.1f} laps." if s.get("fuel_lap") else "."))
    if s.get("tyre_deg") is not None:
        ft.append(f"Tyre fade in your longest stint: {s['tyre_deg']:.2f} s a lap per lap.")
    w = s.get("weather") or {}
    if w.get("track_temp"):
        ft.append(f"Track {w['track_temp']:.0f} degrees" + (f", wet level up to {w['wet']:.0f}." if (w.get("wet") or 0) >= 3 else "."))
    if ft:
        sec.append({"h": "Fuel and tyres", "lines": ft})
    nl = _notes_lines([dict(n, date="") for n in s.get("notes") or []])
    if nl:
        sec.append({"h": "What you said on the radio", "lines": nl})
    sec.append({"h": "Car", "lines": ([f"Setup: {s['setup']}."] if s.get("setup") else []) + mech_lines(mech or [])})
    kind = "Race debrief" if "race" in str(s.get("session", "")).lower() else f"{s.get('session') or 'Session'} debrief"
    return {"kind": "debrief", "title": kind, "car": s.get("car_name") or s["car"], "track": s.get("track_name") or s["track"],
            "source": M.THIS_CAR, "date": s.get("date"), "sections": sec, "ctx": {}}


def _th(n):
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def pack_text(pack):
    """The pack as plain text: the model's DATA block, and the no-model view."""
    out = [f"{pack.get('title')}: {pack.get('car') or ''} at {pack.get('track') or ''}" + (f" ({pack['date']})" if pack.get("date") else "")]
    for s in pack.get("sections", []):
        out.append(f"\n{s['h'].upper()}")
        out += [f"- {x}" if not x.startswith("- ") and not x.startswith("MECHANIC") else x for x in s["lines"]]
    return "\n".join(out)


def model_context(pack, whatif=None):
    """DATA block for the team model: meeting rules + the facts (+ the what-if answer when there is one)."""
    ctx = MEETING_RULES.get(pack.get("kind"), "") + "\n\n" + pack_text(pack)
    if whatif and whatif.get("lines"):
        ctx += "\n\nWHAT-IF ANSWER (worked out by the strategy code - use these numbers only):\n" + "\n".join(f"- {x}" for x in whatif["lines"])
    return ctx


def public(pack):
    """The pack without the internal maths (for the page)."""
    return {k: v for k, v in pack.items() if k != "ctx"}
