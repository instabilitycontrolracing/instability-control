"""Team meeting room (2026-10-27): the night review, the race debrief with incident forensics, practice plan,
trend across sessions, and questions answered from the data.

Everything here is fixed code working on forensics.analyse() output - no AI needed. With the team AI loaded the
same facts become its DATA block and it talks them through (it may not add numbers of its own); without it the
page shows these lines and the meeting still works.

    review = night_review(res, history=None)   # res = forensics.analyse(...)
    answer(question, review) -> {"lines", "refs", "intent"} or None (not a question the code can answer)
    night_report_md(res)                        # the same as a Markdown report
"""
import re

from .forensics import fmt_lap, CAUSES

FAMILY = {   # what a family of mistakes is called in the meeting, and the one thing to practise for it
    "overspeed": ("Arriving too fast at the corner", "Brake at your clean-lap marker and hit the turn-in speed you know works"),
    "entry_os": ("Braking and downshifting into the turn", "Finish the braking and the downshifts in a straight line, then bleed the brake off as you turn"),
    "exit_os": ("Throttle with the wheel still turned", "Unwind the steering first, then squeeze the throttle in over about a second"),
    "exit_us": ("Running wide on the exits", "Get the car turned before you open the throttle"),
    "mid_us": ("Understeer: too much steering", "A little slower at the turn-in, then don't keep adding lock"),
    "lock_front": ("Locking the fronts", "Hard at the start of the braking, then ease off as the speed drops"),
    "lock_rear": ("Locking the rears", "Less pedal at the end of the braking zone, straight-line braking"),
    "kerbs": ("Kerbs", "Take less of the kerb, with the steering straighter"),
    "contact": ("Contact with other cars", "Leave room in traffic: brake at your marker or earlier with a car close in front"),
    "cold": ("Cold tyres", "Gentle on the out-lap and the first lap"),
    "damage": ("Carrying on with a damaged car", "After a hit that damages the car, slow down, stay off the racing line and get it to the pits"),
    "unclear": ("Unclear moments", "Watch the replays of these"),
}
KIND_WORD = {"spin": "spin", "crash": "crash", "contact": "contact", "off": "off", "moment": "big slide", "incident": "incident"}
KIND_PLURAL = {"spin": "spins", "crash": "crashes", "contact": "contacts", "off": "offs", "moment": "big slides", "incident": "incidents"}


def kw(k, n):
    return KIND_WORD[k] if n == 1 else KIND_PLURAL[k]


def _plural(n, w):
    return f"{n} {w}{'' if n == 1 else 'es' if w.endswith(('sh', 'ch')) else 's'}"


# ======================================================================================== labels
def label_sessions(sessions):
    """'Race 1', 'Race 2', 'Practice 1' ... in time order, plus the clock time and wet/dry."""
    count = {}
    for s in sessions:
        sm = s["summary"]
        t = (sm.get("type") or "Session").replace("Lone Qualify", "Qualifying").replace("Open Qualify", "Qualifying")
        count[t] = count.get(t, 0) + 1
        s["label"] = f"{t} {count[t]}"
        hhmm = (sm.get("date") or "")[11:16]
        wet = sm.get("tyres") == "wet" or sm.get("wet") not in ("dry", "mostly dry", "unknown", "?", None)
        s["long_label"] = f"{s['label']} ({hhmm}{', wet' if wet else ''})"
    return sessions


def session_lines(s):
    """The debrief of one session as short plain sentences."""
    sm, L = s["summary"], []
    if sm.get("start_pos") and sm.get("finish_pos"):
        d = sm["start_pos"] - sm["finish_pos"]
        if sm.get("finished", True):
            L.append(f"Started P{sm['start_pos']}, finished P{sm['finish_pos']} in class"
                     + (f" ({'+' if d > 0 else ''}{d} place{'s' if abs(d) != 1 else ''})." if d else ", same as the start."))
        else:
            L.append(f"Started P{sm['start_pos']}; stopped on lap {sm.get('retired_lap')} running P{sm['finish_pos']} (didn't finish).")
    laps = f"{sm['laps']} lap{'s' if sm['laps'] != 1 else ''}" + ("" if sm.get("best") or sm.get("median") else " (no complete timed lap)")
    if sm.get("best"):
        laps += f", best {fmt_lap(sm['best'])}"
    if sm.get("median"):
        laps += f", typical {fmt_lap(sm['median'])}"
    if sm.get("spread") is not None:
        laps += f", spread {sm['spread']:.2f} s on {sm['clean_laps']} clean laps"
    L.append(laps + ".")
    if sm.get("tyres") == "wet" or sm.get("wet_max") not in ("dry", "mostly dry", "unknown", "?"):
        L.append(f"Track: {sm.get('wet_max')}" + (", wet tyres." if sm.get("tyres") == "wet" else "."))
    st = [x for x in sm.get("stints") or [] if x.get("median")]
    if len(st) > 1:
        L.append("Stints: " + "; ".join(f"laps {x['from']}-{x['to']} typical {fmt_lap(x['median'])}" + (f", {x['fade']:+.2f} s/lap" if x.get("fade") is not None else "") for x in st) + ".")
    c = sm.get("counts") or {}
    bits = [f"{c[k]} {kw(k, c[k])}" for k in ("spin", "crash", "contact", "off", "moment") if c.get(k)]
    L.append(f"{sm.get('incidents', 0)}x incident points" + (": " + ", ".join(bits) + "." if bits else ", no spins, crashes or offs."))
    if sm.get("time_lost"):
        L.append(f"About {sm['time_lost']:.0f} s lost in those moments.")
    for dmg in sm.get("damage") or []:
        L.append(f"The {dmg['wheel']} wheel was damaged on lap {dmg['lap']} ({dmg['corner']}) and the car wasn't right after that.")
    if sm.get("corner_loss"):
        L.append("Where the clean laps lose time (your usual against your best there): "
                 + ", ".join(f"{r['name']} {r['lost']:.2f} s" for r in sm["corner_loss"][:3]) + ".")
    return L


# ======================================================================================== tonight as a whole
def all_episodes(review_or_sessions):
    ss = review_or_sessions["sessions"] if isinstance(review_or_sessions, dict) else review_or_sessions
    return [(s, e) for s in ss for e in s["episodes"]]


def _spots(sessions):
    """2026-10-28: corner names for the drills at tonight's track (these were Le Mans' corners everywhere)."""
    from .series import drill_spots
    sm = ((sessions or [{}])[0].get("summary") or {}) if sessions else {}
    return drill_spots(sm.get("track_name"), sm.get("track"))


def top3(sessions):
    """The three things that cost the most tonight, each with why and a drill."""
    eps = all_episodes(sessions)
    fam = {}
    for s, e in eps:
        f = e["family"]
        if e["kind"] == "moment" and not e["pts"]:
            w = 1.0
        else:
            w = 2.0 + (e["pts"] or 0) + (e.get("loss") or 0) / 10
        fam.setdefault(f, {"score": 0.0, "eps": []})
        fam[f]["score"] += w
        fam[f]["eps"].append((s, e))
    out = []
    lap1 = [(s, e) for s, e in eps if e.get("race_lap1") and e["kind"] != "moment"]
    if len(lap1) >= 3:
        out.append({"title": "Lap 1", "score": 99,
                    "why": f"{len(lap1)} of tonight's {len([x for x in eps if x[1]['kind'] != 'moment'])} incidents were on the first lap of a race "
                           f"({', '.join(dict.fromkeys(s['label'] for s, _ in lap1))}).",
                    "drill": "Lap 1 is for surviving: brake 10-20 m earlier than your marker with cars around, leave a car's width, and don't attack until the pack spreads out ("
                             + _spots(sessions)["settle"] + ").",
                    "refs": [(s["id"], e["n"]) for s, e in lap1]})
    dmg = fam.get("damage")
    dmg_item = None
    if dmg and len(dmg["eps"]) >= 2:
        dmg_item = {"title": FAMILY["damage"][0], "score": 90,
                    "why": f"{len(dmg['eps'])} more incidents happened after the car was already damaged.",
                    "drill": FAMILY["damage"][1] + ".", "refs": [(s["id"], e["n"]) for s, e in dmg["eps"]]}
    if out:                                  # lap 1 is its own lesson: don't count those incidents again below
        lap1_ids = {id(e) for _, e in lap1}
        for f in list(fam):
            v = fam[f]
            v["eps"] = [(s, e) for s, e in v["eps"] if id(e) not in lap1_ids]
            v["score"] = sum((1.0 if e["kind"] == "moment" and not e["pts"] else 2.0 + (e["pts"] or 0) + (e.get("loss") or 0) / 10) for _, e in v["eps"])
            if not v["eps"]:
                del fam[f]
    driving = []
    for f, v in sorted(fam.items(), key=lambda kv: -kv[1]["score"]):
        if f in ("damage", "unclear"):
            continue
        es = v["eps"]
        corners = list(dict.fromkeys(e["corner_key"] for _, e in es))
        cause = max(set(e["cause"] for _, e in es), key=lambda c: sum(1 for _, e in es if e["cause"] == c))
        title, short = FAMILY.get(f, (CAUSES[cause]["title"], CAUSES[cause]["what"]))
        n = len(es)
        driving.append({"title": title, "score": v["score"],
                        "why": f"{n} time{'s' if n != 1 else ''} tonight ({', '.join(corners[:4])}). {short}.",
                        "drill": CAUSES[cause]["drill"], "refs": [(s["id"], e["n"]) for s, e in es]})
    out += driving[:1]
    if dmg_item:
        out.append(dmg_item)
    out += driving[1:]
    return out[:3]


def hot_corners(sessions):
    """Corners where tonight's incidents and lock-ups pile up."""
    rows = {}
    for s in sessions:
        for e in s["episodes"]:
            r = rows.setdefault(e["corner_key"], {"name": e["corner_key"], "incidents": 0, "slides": 0, "lockups": 0, "pts": 0, "sessions": set()})
            if e["kind"] == "moment":
                r["slides"] += 1
            else:
                r["incidents"] += 1
            r["pts"] += e["pts"] or 0
            r["sessions"].add(s["label"])
        for k, v in ((s["summary"].get("habits") or {}).get("lockups") or {}).items():
            r = rows.setdefault(k, {"name": k, "incidents": 0, "slides": 0, "lockups": 0, "pts": 0, "sessions": set()})
            r["lockups"] += v["front"] + v["rear"]
    out = []
    for r in rows.values():
        r["sessions"] = sorted(r["sessions"])
        r["score"] = r["incidents"] * 3 + r["slides"] + r["lockups"] * 0.3 + r["pts"] * 0.5
        out.append(r)
    out.sort(key=lambda r: -r["score"])
    return [r for r in out if r["incidents"] or r["slides"] or r["lockups"] >= 3][:6]


def trend(sessions, history=None):
    """Is he improving? Tonight's sessions in order (+ the memory's history for this car + track when given)."""
    L = []
    races = [s for s in sessions]
    if len(races) >= 2:
        parts = []
        for s in races:
            sm = s["summary"]
            laps = max(1, sm.get("laps") or 1)
            parts.append(f"{s['label']}: {sm.get('incidents', 0)}x in {laps} laps" + (f", typical {fmt_lap(sm['median'])}" if sm.get("median") else ""))
        L.append("; ".join(parts) + ".")
        dry = [s for s in races if s["summary"].get("median") and s["summary"].get("tyres") != "wet"]
        if len(dry) >= 2:
            a, b = dry[0]["summary"]["median"], dry[-1]["summary"]["median"]
            L.append(f"Dry pace: typical lap {fmt_lap(a)} in {dry[0]['label']} to {fmt_lap(b)} in {dry[-1]['label']} ({b - a:+.2f} s).")
        elif len(dry) == 1:
            L.append(f"Only {dry[0]['label']} had enough clean dry laps to judge pace ({fmt_lap(dry[0]['summary']['median'])} typical).")
        first, last = races[0]["summary"], races[-1]["summary"]
        r0 = first.get("incidents", 0) / max(1, first.get("laps") or 1)
        r1 = last.get("incidents", 0) / max(1, last.get("laps") or 1)
        if r1 < r0 * 0.7:
            L.append("Incident rate per lap went down from the first to the last session.")
        elif r1 > r0 * 1.3:
            L.append("Incident rate per lap went up from the first to the last session.")
        lap1 = [s["label"] for s in races if any(e.get("race_lap1") and e["kind"] != "moment" for e in s["episodes"])]
        if lap1:
            L.append(f"Lap-1 incidents in: {', '.join(lap1)}.")
    ag = (history or {}).get("aggregates") or {}
    if ag.get("sessions"):
        bits = [f"{ag['sessions']} sessions remembered here"]
        if ag.get("best"):
            bits.append(f"best ever {fmt_lap(ag['best'])}")
        if ag.get("typical"):
            bits.append(f"usual typical lap {fmt_lap(ag['typical'])}")
        if ag.get("spins") is not None:
            bits.append(f"{ag['spins']} spins and {ag['offs']} offs a session on average")
        L.append("History: " + ", ".join(bits) + ".")
        best_tonight = min([s["summary"]["best"] for s in sessions if s["summary"].get("best") and s["summary"].get("tyres") != "wet"] or [0]) or None
        if best_tonight and ag.get("best"):
            d = best_tonight - ag["best"]
            L.append("Tonight's best dry lap is your best ever here." if d <= 0.0005 else f"Tonight's best dry lap was {d:.2f} s off your best ever here.")
    return L


def practice_plan(sessions, setup=None):
    """A short practice session plan built from tonight's mistakes, with target numbers from the clean laps."""
    plan = []
    eps = all_episodes(sessions)
    # 1) corners where he arrived too fast: target turn-in speed and gear from the clean laps
    tgt = {}
    for s, e in eps:
        t = e.get("target") or {}
        if e["family"] in ("overspeed", "entry_os", "exit_us", "mid_us") and t.get("v_turnin_usual"):
            tgt.setdefault(e["corner_key"], []).append(t)
    if tgt:
        bits = []
        for k, ts in tgt.items():
            v = round(sum(t["v_turnin_usual"] for t in ts) / len(ts))
            g = ts[0].get("gear_turnin_usual")
            bits.append(f"{k} about {v} km/h" + (f" in {g}{_th(g)}" if g else ""))
        plan.append({"title": "Turn-in speed", "text": "10 laps hitting your clean-lap turn-in speed: " + "; ".join(bits) + ". Brake at your marker, gears done before you turn."})
    # 2) the drill for each of the top families
    for t in top3(sessions):
        if t["title"] == "Lap 1":
            plan.append({"title": "Race starts", "text": "Do 3 AI races of 2 laps with a full grid: practise lap 1 into " + _spots(sessions)["lap1"]
                         + " with cars around you. Goal: zero contact."})
        elif t["title"] != "Turn-in speed":
            plan.append({"title": t["title"], "text": t["drill"]})
    # 3) clean-lap time: the corner with most usual loss
    losses = {}
    for s in sessions:
        for r in s["summary"].get("corner_loss") or []:
            losses.setdefault(r["name"], []).append(r["lost"])
    if losses:
        k, v = max(losses.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        plan.append({"title": "Pace", "text": f"{k} costs you about {sum(v) / len(v):.2f} s a lap between your usual and your best there. Open the coach in Analysis on that corner."})
    for x in setup or []:
        if x.get("repeat"):
            plan.append({"title": "Car (only if it still happens)", "text": x["line"]})
    seen, out = set(), []
    for p in plan:
        if p["title"] not in seen:
            seen.add(p["title"]); out.append(p)
    return out[:6]


def _th(n):
    return {1: "st", 2: "nd", 3: "rd"}.get(n, "th")


def night_review(res, history=None):
    """forensics result -> the meeting pack (same section shape as briefing.py packs, plus the details)."""
    ss = label_sessions(list(res.get("sessions") or []))
    first = ss[0]["summary"] if ss else {}
    sections = []
    ov = []
    for s in ss:
        sm = s["summary"]
        res_txt = ""
        if sm.get("start_pos") and sm.get("finish_pos"):
            res_txt = f"P{sm['start_pos']} to P{sm['finish_pos']}" + ("" if sm.get("finished", True) else " (didn't finish)")
        c = sm.get("counts") or {}
        bits = []
        for k in ("spin", "crash", "contact", "off"):
            if c.get(k):
                sp = sum(1 for e in s["episodes"] if e.get("spun") and e["kind"] == k and k != "spin")
                bits.append(f"{c[k]} {kw(k, c[k])}" + (f" ({'it' if c[k] == 1 else sp} spun you round)" if sp else ""))
        ov.append(f"{s['long_label']}: {res_txt + ', ' if res_txt else ''}{sm['laps']} laps"
                  + (f", best {fmt_lap(sm['best'])}" if sm.get("best") else "")
                  + f", {sm.get('incidents', 0)}x" + (f" ({', '.join(bits)})" if bits else ", clean") + ".")
    sections.append({"h": "Tonight", "lines": ov or ["No sessions found."]})
    t3 = top3(ss)
    if t3:
        sections.append({"h": "Top 3 to work on", "lines": [f"{i + 1}. {t['title']}: {t['why']}" for i, t in enumerate(t3)]})
    tr = trend(ss, history)
    if tr:
        sections.append({"h": "Trend", "lines": tr})
    hc = hot_corners(ss)
    if hc:
        sections.append({"h": "Problem corners", "lines": [
            f"{r['name']}: " + ", ".join(x for x in (f"{r['incidents']} incident{'s' if r['incidents'] != 1 else ''}" if r["incidents"] else "",
                                                     f"{r['slides']} big slide{'s' if r['slides'] != 1 else ''}" if r["slides"] else "",
                                                     f"{r['lockups']} lock-up{'s' if r['lockups'] != 1 else ''}" if r["lockups"] else "") if x)
            + f" ({', '.join(r['sessions'])})." if r["sessions"] else "." for r in hc]})
    if res.get("setup"):
        sections.append({"h": "Car", "lines": [x["line"] for x in res["setup"]]})
    plan = practice_plan(ss, res.get("setup"))
    if plan:
        sections.append({"h": "Practice plan", "lines": [f"{p['title']}: {p['text']}" for p in plan]})
    for s in ss:
        sections.append({"h": s["long_label"], "lines": session_lines(s), "sid": s["id"]})
    return {"kind": "review", "title": "Night review", "car": first.get("car"), "track": first.get("track"),
            "date": (first.get("date") or "")[:10], "source": "this car", "sections": sections,
            "sessions": [{"id": s["id"], "label": s["label"], "long_label": s["long_label"], "summary": s["summary"],
                          "episodes": s["episodes"]} for s in ss],
            "top3": t3, "plan": plan, "hot": hc, "setup": res.get("setup") or []}


def prerace_lines(review):
    """For the pre-race meeting: where it went wrong last time here, with the target numbers."""
    L = []
    eps = [(s, e) for s, e in all_episodes(review) if e["kind"] != "moment" and not e.get("damaged")]
    lap1 = [e for _, e in eps if e.get("race_lap1")]
    if lap1:
        L.append(f"Lap 1: {len(lap1)} incident{'s' if len(lap1) != 1 else ''} on the first lap last time "
                 f"({', '.join(dict.fromkeys(e['corner_key'] for e in lap1))}). Survive it: brake early with cars around, leave room.")
    seen = set()
    for s, e in eps:
        if e["corner_key"] in seen or e.get("race_lap1"):
            continue
        seen.add(e["corner_key"])
        t = e.get("target") or {}
        tip = f" Target: about {t['v_turnin_usual']:.0f} km/h at the turn-in" + (f" in {t['gear_turnin_usual']}{_th(t['gear_turnin_usual'])}" if t.get("gear_turnin_usual") else "") + "." if t.get("v_turnin_usual") else ""
        L.append(f"{e['corner_key']}: {KIND_WORD[e['kind']]} in {s['label']} (lap {e['lap']}) - {e['cause_title'].lower()}.{tip}")
        if len(L) >= 5:
            break
    return L


def public(review, traces=False):
    """The review for the page: without the traces (fetched per incident when clicked)."""
    out = dict(review)
    out["sessions"] = []
    for s in review.get("sessions") or []:
        x = dict(s)
        x["episodes"] = [{k: v for k, v in e.items() if traces or k != "trace"} for e in s["episodes"]]
        out["sessions"].append(x)
    return out


def find_episode(review, sid, n):
    for s in review.get("sessions") or []:
        if str(s["id"]) == str(sid):
            for e in s["episodes"]:
                if int(e["n"]) == int(n):
                    return s, e
    return None, None


# ======================================================================================== questions
_ORD = {"first": 1, "one": 1, "1st": 1, "second": 2, "two": 2, "2nd": 2, "third": 3, "three": 3, "3rd": 3,
        "fourth": 4, "four": 4, "4th": 4, "fifth": 5, "five": 5}
_STOP = {"the", "chicane", "curve", "curves", "corner", "first", "second", "of", "de", "du"}
_ALIAS = {"indy": "indianapolis", "ps": "playstation", "play station": "playstation", "tertre": "tetre", "tetra": "tetre",
          "mulsane": "mulsanne", "michelin": "michelin", "porsches": "porsche", "s": "esses", "esses": "esses", "fords": "ford"}


def _norm(q):
    q = " " + re.sub(r"[^a-z0-9 ]+", " ", (q or "").lower()) + " "
    for a, b in _ALIAS.items():
        q = q.replace(f" {a} ", f" {b} ")
    return re.sub(r"\s+", " ", q)


def _pick_sessions(q, sessions):
    """Which session(s) the question is about: 'race 3', 'the third race', 'last race', 'the wet race'..."""
    m = re.search(r" (race|practice|session|qualifying) (\d|one|two|three|four|five|first|second|third|fourth|fifth) ", q) or \
        re.search(r" (first|second|third|fourth|fifth|1st|2nd|3rd|4th|last|final|latest) (race|practice|session) ", q)
    if m:
        a, b = m.group(1), m.group(2)
        kind, n = (a, b) if a in ("race", "practice", "session", "qualifying") else (b, a)
        pool = [s for s in sessions if kind == "session" or s["label"].lower().startswith(kind)] or sessions
        if n in ("last", "final", "latest"):
            return pool[-1:]
        k = int(n) if n.isdigit() else _ORD.get(n, 0)
        return pool[k - 1:k] if 0 < k <= len(pool) else []
    if " wet " in q or " rain" in q:
        w = [s for s in sessions if s["summary"].get("tyres") == "wet" or s["summary"].get("wet_max") not in ("dry", "mostly dry", "unknown")]
        if w:
            return w
    if " last " in q and (" race " in q or " session " in q):
        return sessions[-1:]
    return sessions


def _corner_match(q, names):
    best, score = [], 0
    for n in names:
        words = [w for w in re.sub(r"[^a-z ]+", " ", n.lower()).split() if w not in _STOP]
        if not words:
            continue
        hit = sum(1 for w in words if f" {w} " in q or (len(w) > 5 and w[:5] in q))
        if not hit:
            continue
        sc = hit * 10
        nl = n.lower()
        for w in ("chicane", "curve", "first", "second", "corner"):
            if w in nl and f" {w} " in q:
                sc += 3
            elif w in nl and w in ("first", "second") and f" {('second' if w == 'first' else 'first')} " in q:
                sc -= 5
        if sc > score:
            best, score = [n], sc
        elif sc == score:
            best.append(n)
    return best


def _kind_filter(q):
    """-> the kinds of incident the question is about, the main one first (or None)."""
    if re.search(r" (spin|spun|spins|spinning|lost the rear|swapped ends|loop|looped) ", q):
        return ["spin", "moment", "crash"]
    if re.search(r" (crash|crashed|crashes|wall|barrier|wreck|wrecked|crashing) ", q):
        return ["crash", "contact"]
    if re.search(r" (contact|contacts|hit|touch|touched|collision|collided|ran into|rear ended|bump|bumped) ", q):
        return ["contact"]
    if re.search(r" (off|offs|ran wide|gravel|grass|track limits|went wide|run wide) ", q):
        return ["off", "crash"]
    if re.search(r" (slide|slides|moment|snap|snapped|oversteer) ", q):
        return ["moment", "spin"]
    return None


def answer(question, review):
    """Answer a question about tonight from the forensics. -> {"intent", "lines", "refs"} or None."""
    if not review or not review.get("sessions"):
        return None
    q = _norm(question)
    ss = review["sessions"]
    pick = _pick_sessions(q, ss)
    if not pick:
        return {"intent": "none", "lines": [f"I only have {len(ss)} session{'s' if len(ss) != 1 else ''} tonight: " + ", ".join(s["long_label"] for s in ss) + "."], "refs": []}
    eps = [(s, e) for s in pick for e in s["episodes"]]
    names = sorted({e["corner_key"] for _, e in all_episodes(ss)} | {e["corner"] for _, e in all_episodes(ss)}
                   | {n for s in ss for n in s["summary"].get("corner_names") or []})
    corners = _corner_match(q, names)
    kinds = _kind_filter(q)
    lapm = re.search(r" lap (\d{1,2}) ", q)
    which = " in " + ", ".join(s["label"] for s in pick) if len(pick) < len(ss) else " tonight"

    def refs(es):
        return [{"sid": s["id"], "n": e["n"], "label": f"{s['label']} · {e['title']}"} for s, e in es]

    # ---- how many
    if re.search(r" how many ", q) and kinds and "spin" in kinds:
        sp = [(s, e) for s, e in eps if e.get("spun")]
        L = [f"{len(sp)} spin{'s' if len(sp) != 1 else ''}{which}" + (" (counting the ones after contact or before a crash)." if any(e["kind"] != "spin" for _, e in sp) else ".")]
        L += [f"{s['label']} lap {e['lap']}: {e['title']}." for s, e in sp]
        mo = [(s, e) for s, e in eps if e["kind"] == "moment"]
        if mo:
            L.append(f"Plus {len(mo)} big slide{'s' if len(mo) != 1 else ''} you caught.")
        return {"intent": "count", "lines": L, "refs": refs(sp + mo)}
    if re.search(r" how many ", q):
        c = {}
        for _, e in eps:
            c[e["kind"]] = c.get(e["kind"], 0) + 1
        sel = kinds[:1] if kinds else ["spin", "crash", "contact", "off", "moment"]
        L = [f"{c.get(k, 0)} {kw(k, c.get(k, 0))}" for k in sel]
        per = []
        for s in pick:
            cc = s["summary"].get("counts") or {}
            per.append(f"{s['label']}: " + ", ".join(f"{cc.get(k, 0)} {kw(k, cc.get(k, 0))}" for k in sel if cc.get(k)) or f"{s['label']}: none")
        return {"intent": "count", "lines": [", ".join(L) + which + "."] + (per if len(pick) > 1 else []), "refs": refs([x for x in eps if x[1]["kind"] in sel])}
    # ---- fault / blame / ruined someone's race
    if re.search(r" (fault|blame|my bad|ruin|ruined|responsib|whose|who caused|did i cause|caused) ", q):
        con = [(s, e) for s, e in eps if e["kind"] == "contact"]
        L = []
        for s, e in con:
            mine = {"contact_ahead": "you ran into him", "contact_behind": "he ran into you", "contact_side": "side by side"}.get(e["cause"], "")
            L.append(f"{s['label']}, lap {e['lap']}, {e['corner_key']}: {mine}. " + " ".join(e["why"][:2]))
        dmg = [(s, e) for s, e in eps if e.get("damaged")]
        if dmg:
            L.append(f"After the damage you stayed out: {len(dmg)} more incident{'s' if len(dmg) != 1 else ''} with a car that wasn't right"
                     + f" ({', '.join(dict.fromkeys(e['corner_key'] for _, e in dmg))}). A slow, damaged car in the pack is a danger to the others: next time slow right down off the racing line and get it to the pits.")
        if not L:
            L.append(f"No contact with other cars{which}.")
        return {"intent": "fault", "lines": L, "refs": refs(con + dmg)}
    # ---- practice / work on
    if re.search(r" (practi[cs]e|work on|improve|focus|drill|train|get better|next time|what should i do|tips|homework) ", q):
        plan = review.get("plan") or practice_plan(pick, review.get("setup"))
        t3 = review.get("top3") or top3(pick)
        L = [f"{i + 1}. {t['title']}: {t['why']} Drill: {t['drill']}" for i, t in enumerate(t3)]
        if plan:
            L.append("Practice plan: " + " | ".join(f"{p['title']}: {p['text']}" for p in plan[:4]))
        return {"intent": "practice", "lines": L, "refs": [{"sid": r[0], "n": r[1], "label": ""} for t in t3 for r in t.get("refs", [])][:8]}
    # ---- improving / trend
    if re.search(r" (improv|improving|progress|trend|getting better|getting worse|better or worse|compare|comparison) ", q):
        return {"intent": "trend", "lines": trend(ss) or ["Only one session tonight: nothing to compare yet."], "refs": []}
    # ---- setup
    if re.search(r" (setup|set up|car change|change on the car|mechanic|bias|roll bar|wing|diff) ", q):
        st = review.get("setup") or []
        L = [x["line"] for x in st] or ["Nothing repeats enough to change the car: it's the driving."]
        return {"intent": "setup", "lines": L, "refs": []}
    # ---- lock-ups / wheelspin
    if re.search(r" (lock|locking|locked|lockup|lockups|flat spot) ", q):
        L = []
        for s in pick:
            lk = (s["summary"].get("habits") or {}).get("lockups") or {}
            if lk:
                top = sorted(lk.items(), key=lambda kv: -(kv[1]["front"] + kv[1]["rear"]))[:4]
                L.append(f"{s['label']}: " + ", ".join(f"{k} {v['front']} front / {v['rear']} rear" for k, v in top) + ".")
        return {"intent": "lockups", "lines": L or ["No lock-ups found."], "refs": []}
    # ---- pace
    if re.search(r" (pace|lap time|laptime|fastest|best lap|consisten|slow|quick|time lost|losing time) ", q) and not kinds:
        L = []
        for s in pick:
            sm = s["summary"]
            L.append(f"{s['label']}: " + (f"best {fmt_lap(sm['best'])}" if sm.get("best") else "no timed lap")
                     + (f", typical {fmt_lap(sm['median'])}, spread {sm['spread']:.2f} s" if sm.get("median") and sm.get("spread") is not None else "")
                     + (". Clean laps lose most at " + ", ".join(f"{r['name']} {r['lost']:.2f} s" for r in sm["corner_loss"][:3]) if sm.get("corner_loss") else "") + ".")
        return {"intent": "pace", "lines": L, "refs": []}
    # ---- worst / problem corner
    if re.search(r" (worst|problem|dangerous|trouble|hardest) (corner|corners|place|part|bit) ", q) or " where do i " in q and not corners:
        hc = review.get("hot") or hot_corners(pick)
        return {"intent": "corners", "lines": [f"{r['name']}: {r['incidents']} incidents, {r['slides']} big slides, {r['lockups']} lock-ups." for r in hc[:4]] or ["No problem corners tonight."], "refs": []}
    # ---- why / what happened (the main one)
    sel = eps
    if corners:
        sel = [(s, e) for s, e in sel if e["corner_key"] in corners or e["corner"] in corners]
    if kinds:
        sel = [(s, e) for s, e in sel if e["kind"] in kinds or ("spin" in kinds and e.get("spun"))]
    if lapm:
        sel = [(s, e) for s, e in sel if e["lap"] == int(lapm.group(1))]
    asked = corners or kinds or lapm or re.search(r" (why|what happened|how did|explain|tell me about|what went wrong|debrief|summary|how did i do|result) ", q)
    if not asked:
        return None
    if re.search(r" (debrief|summary|how did i do|result|results|recap) ", q) and not (corners or kinds or lapm):
        L = []
        for s in pick:
            L.append(f"{s['long_label']}:")
            L += ["  " + x for x in session_lines(s)]
        return {"intent": "summary", "lines": L, "refs": refs([x for x in eps if x[1]["kind"] != "moment"])}
    if not sel:
        what = " ".join(x for x in (", ".join(sorted(kinds)) if kinds else "incident", f"at {corners[0]}" if corners else "", f"on lap {lapm.group(1)}" if lapm else "") if x)
        have = [f"{s['label']} lap {e['lap']}: {e['title']}" for s, e in eps if e["kind"] != "moment"][:8]
        return {"intent": "why", "lines": [f"I don't see a {what}{which}."] + (["What I do have: " + "; ".join(have) + "."] if have else []), "refs": refs(eps[:8])}
    L = []
    for s, e in sel[:4]:
        L.append(f"{s['label']}, lap {e['lap']}: {e['title']}" + (f" ({e['pts']}x)" if e["pts"] else "") + ".")
        L.append(f"Why: {e['cause_title']}." + (" (Not certain from the data.)" if e["confidence"] == "unsure" else ""))
        L += e["why"]
        if e["factors"]:
            L.append("Also: " + " ".join(e["factors"]))
        L.append(f"What to do: {e['what']}")
    if len(sel) > 4:
        L.append(f"And {len(sel) - 4} more like it: ask about one by race and lap.")
    return {"intent": "why", "lines": L, "refs": refs(sel)}


EXAMPLES = ["Why did I spin at the Dunlop Chicane in race 3?", "What happened at Tetre Rouge in race 2?", "Was the contact my fault?",
            "What should I practise?", "Am I improving?", "How many spins tonight?", "Where do I lock up?", "Do we need a setup change?"]


# ======================================================================================== model DATA + markdown
RULES = ("This is the NIGHT REVIEW: the debrief of tonight's sessions with the incident forensics. Use ONLY the facts below. "
         "Every spin, crash, contact and off has its cause worked out by the forensics code: repeat those causes and numbers, never "
         "invent another cause or number. If the forensics says 'not certain', say so. Driving first; a setup change only if it is "
         "under Car and marked as repeating. When the FORENSICS ANSWER block is there, base the answer on it.")


def review_text(review, max_eps=30):
    out = [f"{review.get('title')}: {review.get('car') or ''} at {review.get('track') or ''} ({review.get('date') or ''})"]
    for s in review.get("sections", []):
        out.append(f"\n{s['h'].upper()}")
        out += [f"- {x}" for x in s["lines"]]
    out.append("\nINCIDENTS (forensics)")
    k = 0
    for s in review.get("sessions") or []:
        for e in s["episodes"]:
            if k >= max_eps:
                break
            k += 1
            out.append(f"- {s['label']} lap {e['lap']}, {e['title']}" + (f", {e['pts']}x" if e["pts"] else "")
                       + f": cause {e['cause_title']} ({e['confidence']}). " + " ".join(e["why"]) + (" Also: " + " ".join(e["factors"]) if e["factors"] else "")
                       + f" Fix: {e['what']}")
    return "\n".join(out)


def model_context(review, ans=None):
    ctx = RULES + "\n\n" + review_text(review)
    if ans and ans.get("lines"):
        ctx += "\n\nFORENSICS ANSWER (worked out by the code for this question - use these facts):\n" + "\n".join(f"- {x}" for x in ans["lines"])
    return ctx


def night_report_md(res, history=None):
    rv = night_review(res, history)
    L = [f"# Night review - {rv.get('car') or ''} at {rv.get('track') or ''}", "",
         f"_{rv.get('date')}. Built by the Race Engineer's incident forensics from your iRacing telemetry. Every number below is measured;"
         " \"your clean laps\" means the median of your laps with no incident, pit stop or off, in the same conditions (wet or dry)._", ""]
    for sec in rv["sections"]:
        if sec.get("sid"):
            continue
        L.append(f"## {sec['h']}")
        L += [f"- {x}" for x in sec["lines"]]
        L.append("")
    for s in rv["sessions"]:
        L.append(f"## {s['long_label']}")
        L += [f"- {x}" for x in session_lines(s)]
        L.append("")
        if not s["episodes"]:
            L.append("No spins, crashes or offs.")
            L.append("")
        for e in s["episodes"]:
            head = f"### {e['n']}. {e['title']} - lap {e['lap']}" + (f" ({e['pts']}x)" if e["pts"] else "")
            L.append(head)
            meta = []
            if e.get("loss") and e["loss"] >= 1:
                meta.append(f"about {e['loss']:.0f} s lost")
            if e.get("pos_before") and e.get("pos_after") and e["pos_before"] != e["pos_after"]:
                meta.append(f"P{e['pos_before']} to P{e['pos_after']}")
            if meta:
                L.append(f"_{', '.join(meta)}_")
            L.append("")
            L.append(f"**Why: {e['cause_title']}**" + (" _(not certain from the data)_" if e["confidence"] == "unsure" else ""))
            L += [f"- {w}" for w in e["why"]]
            if e["factors"]:
                L.append(f"- Also: {' '.join(e['factors'])}")
            L.append("")
            L.append(f"**What to do differently:** {e['what']}")
            L.append("")
            L.append(f"**Drill:** {e['drill']}")
            L.append("")
            L.append(f"<sub>Evidence: {' '.join(e['evidence'])}</sub>")
            L.append("")
        hb = s["summary"].get("habits") or {}
        lk = hb.get("lockups") or {}
        if lk:
            top = sorted(lk.items(), key=lambda kv: -(kv[1]["front"] + kv[1]["rear"]))[:5]
            L.append("Lock-ups on the rest of the laps: " + ", ".join(f"{k} {v['front']} front / {v['rear']} rear" for k, v in top) + ".")
            L.append("")
    L.append("---")
    L.append("_What the telemetry file can't show: which car touched you (only the distance to the next car ahead and behind on track is "
             "recorded), cars side by side, the damage level, and live tyre temperatures._")
    return "\n".join(L) + "\n"
