"""Builds fine-tuning examples for the team model from the developer's own telemetry.

Each example = the same fact sheet the app gives the model + a driver question + the answer the team
should give (composed from those facts, in the engineer's / mechanic's voice). The model learns the
format, the voices, to stick to the facts, to put technique before setup, and to keep it short.
"""
import json, os, random, re, sys

from .analysis import open_session, compare, section, lap_index
from .mechanic import car_summary, corner_advice
from .team import SYSTEM, build_context, fmt_lap

R = random.Random(7)

Q_DEBRIEF = ["Debrief this lap", "How was that lap?", "Talk me through that lap", "Debrief", "What happened on that lap?",
             "Give me the debrief", "How did I do?", "Lap review please"]
Q_BIGGEST = ["Where am I losing the most time?", "Where's the time?", "What's my biggest loss?", "Where do I lose most?",
             "Which corners cost me the most?"]
Q_CORNER = ["How do I get faster at {c}?", "What am I doing wrong in {c}?", "Help me with {c}", "How's my {c}?",
            "{c}, what should I do there?", "Why am I slow in {c}?"]
Q_SETUP = ["What should we change on the car?", "Any setup changes?", "Is it the car or me?", "What would you change on the setup?",
           "Mechanic, what do you think of the car?", "How's the balance?"]
Q_NEXT = ["Give me 3 things for my next run", "What should I focus on next run?", "Top three things to work on?",
          "What do I do on the next stint?"]
Q_SECTION = ["How do I get faster in the selected section?", "What about this section?", "Break down this part for me",
             "What's going on here?"]
Q_UNKNOWN = ["What was my top speed on the straight?", "What were my tyre temperatures?", "How much fuel did I use per lap?",
             "What lap time did the leader do?", "What's the weather going to do?"]

OPEN = ["Okay.", "Alright.", "Okay, so.", "Good.", "Right.", ""]
CLOSE = ["Same again next run, but fix this.", "Work on this and we find the time.", "One thing at a time.", "We go again.",
         "Focus on this.", ""]


def soften(tip):
    """Advice sentence -> engineer phrasing."""
    t = tip[0].lower() + tip[1:] if tip[:2] not in ("ABS",) else tip
    t = re.sub(r"^You braked at (\d+) m, the reference at (\d+) m\.", r"", t)
    return t.strip()


def pick(seq):
    return R.choice(seq)


def corner_line(c, n_tips=2):
    tips = [soften(t) for t in c["tips"][:n_tips]]
    if not tips:
        return f"{c['name']}, {c['lost']:+.2f}: nothing big, just tidy it up."
    tips[0] = tips[0][0].upper() + tips[0][1:]
    return f"{c['name']}, {abs(c['lost']):.2f} " + ("lost" if c["lost"] > 0 else "gained") + ". " + " ".join(tips)


def ans_debrief(lap_n, lap_t, cmp, ref_label, mech):
    big = [c for c in sorted(cmp["corners"], key=lambda r: -r["lost"]) if c["lost"] > 0.05][:3]
    head = f"ENGINEER: {pick(OPEN)} Lap {lap_n}, {fmt_lap(lap_t)}. That's {abs(cmp['total']):.2f} " + \
           ("slower than" if cmp["total"] > 0 else "faster than") + f" {ref_label}."
    if not big:
        body = " Very close everywhere. No single corner is costing you, keep this rhythm."
    else:
        body = " Most of it is " + ", ".join(f"{c['name']} ({c['lost']:.2f})" for c in big) + "."
        body += " " + " ".join(corner_line(c, 1) for c in big[:2])
    out = (head + body + " " + pick(CLOSE)).strip()
    if mech:
        out += f"\n\nMECHANIC: On the car side: {mech[0]} Before we touch the setup, fix the driving first, then we see if it's still there."
    return out


def ans_biggest(cmp):
    big = [c for c in sorted(cmp["corners"], key=lambda r: -r["lost"]) if c["lost"] > 0.03][:3]
    if not big:
        return "ENGINEER: Nowhere big. You're within a few hundredths of the reference in every corner. Good lap."
    lines = [f"ENGINEER: {pick(['The biggest is', 'Number one is', 'Most of the time is in'])} {big[0]['name']}, {big[0]['lost']:.2f}. " +
             " ".join(t[0].upper() + t[1:] for t in (soften(x) for x in big[0]["tips"][:2]))]
    if len(big) > 1:
        lines.append("Then " + " and ".join(f"{c['name']} ({c['lost']:.2f})" for c in big[1:]) + ".")
    return " ".join(lines)


def ans_corner(c, mech_notes):
    if c["lost"] <= 0.03 and not c["tips"]:
        out = f"ENGINEER: {c['name']} is good. You're {abs(c['lost']):.2f} " + ("up" if c["lost"] < 0 else "down") + " on the reference there. Keep doing the same."
    else:
        tips = [soften(t) for t in c["tips"][:3]]
        tips = [t[0].upper() + t[1:] for t in tips]
        out = f"ENGINEER: In {c['name']} we lose {c['lost']:.2f}. " + " ".join(tips)
    setup_notes = [n for n in mech_notes if "Try:" in n or "bottoming" in n or "close to the ground" in n]
    tech_notes = [n for n in mech_notes if "technique" in n]
    if tech_notes:
        out += f"\n\nMECHANIC: {tech_notes[0]}"
    elif setup_notes:
        out += f"\n\nMECHANIC: {setup_notes[0]}"
    return out


def ans_setup(mech_summary, corner_mech, cmp):
    if not mech_summary and not corner_mech:
        big = max(cmp["corners"], key=lambda r: r["lost"]) if cmp["corners"] else None
        out = "MECHANIC: Honestly, the car looks consistent in the data. I don't see the same handling problem lap after lap, so I wouldn't change the setup yet."
        if big and big["lost"] > 0.05:
            out += f"\n\nENGINEER: The time is in the driving. Start with {big['name']}: " + (soften(big["tips"][0]) if big["tips"] else "same line as the reference.")
        return out
    name, note = corner_mech[0] if corner_mech else (None, None)
    out = "MECHANIC: "
    if mech_summary:
        out += mech_summary[0] + " "
    if note:
        out += f"In {name}: {note}"
    out += "\n\nENGINEER: And change only one thing per run, so we know what worked."
    return out.strip()


def ans_next(cmp):
    tips = []
    for c in sorted(cmp["corners"], key=lambda r: -r["lost"]):
        if c["tips"] and c["lost"] > 0.03:
            tips.append(f"{c['name']}: {soften(c['tips'][0])}")
        if len(tips) == 3:
            break
    if not tips:
        return "ENGINEER: Keep this rhythm. Consistency now: same braking points every lap."
    return "ENGINEER: Three things. " + " ".join(f"{i + 1}, {t}" for i, t in enumerate(tips)) + f" {pick(CLOSE)}"


def ans_section(sec):
    names = " to ".join(c["name"] for c in sec["corners"]) or "this part"
    out = f"ENGINEER: Through {names} we " + (f"lose {sec['lost']:.2f}." if sec["lost"] > 0 else f"gain {abs(sec['lost']):.2f}.")
    for n in sec["notes"][:1]:
        out += " " + n
    for c in sec["corners"][:2]:
        if c["tips"]:
            out += f" {c['name']}: " + " ".join(soften(t) for t in c["tips"][:2])
    mech = [m for c in sec["corners"] for m in c.get("mech", []) if "Try:" in m or "technique" in m]
    if mech:
        out += f"\n\nMECHANIC: {mech[0]}"
    return out


def ans_unknown(q):
    what = {"top speed": "top speed", "tyre": "tyre temperatures", "fuel": "fuel use", "leader": "the leader's lap times",
            "weather": "the weather forecast"}
    k = next((v for kk, v in what.items() if kk in q.lower()), "that")
    return f"ENGINEER: I don't have {k} in front of me from this data. I can tell you where you lose time corner by corner, and the mechanic can talk about the setup."


def examples_for(sess, lap_n, ref_sess, ref_n, ref_label):
    cmp = compare(sess, lap_n, ref_sess, ref_n, points=60)
    if not cmp.get("delta_ok", True):
        return []                       # 2026-10-27 (#344): a broken comparison (no time gap) teaches nothing
    lap_t = sess.lap(lap_n)["time"]
    ms = car_summary(sess)
    corner_mech = []
    for c in sess.find_corners():
        notes = corner_advice(sess, c["key"])
        if any("Try:" in n for n in notes):
            corner_mech.append((c["name"], next(n for n in notes if "Try:" in n)))
    ctx = build_context(sess, cmp, lap_n, ref_label, None, ms)
    ex = []
    add = lambda q, a, context=ctx: ex.append({"messages": [{"role": "system", "content": SYSTEM + "\n\nDATA:\n" + context},
                                                            {"role": "user", "content": q}, {"role": "assistant", "content": a}]})
    add(pick(Q_DEBRIEF), ans_debrief(lap_n, lap_t, cmp, ref_label, ms))
    add(pick(Q_BIGGEST), ans_biggest(cmp))
    add(pick(Q_NEXT), ans_next(cmp))
    add(pick(Q_SETUP), ans_setup(ms, corner_mech, cmp))
    qu = pick(Q_UNKNOWN)
    add(qu, ans_unknown(qu))
    for c in R.sample(cmp["corners"], min(3, len(cmp["corners"]))):
        key = next((x["key"] for x in sess.find_corners() if x["name"] == c["name"]), None)
        notes = corner_advice(sess, key) if key else []
        add(pick(Q_CORNER).format(c=c["name"]), ans_corner(c, notes))
    # a selected section
    if len(cmp["corners"]) >= 3:
        i = R.randrange(0, len(cmp["corners"]) - 1)
        a, b = cmp["corners"][i]["span"][0], cmp["corners"][i + 1]["span"][1]
        sec = section(sess, lap_n, ref_sess, ref_n, a, b)
        from .mechanic import advise_section
        advise_section(sess, lap_n, sec)
        ctx2 = build_context(sess, cmp, lap_n, ref_label, sec, ms)
        add(pick(Q_SECTION), ans_section(sec), ctx2)
    return ex


def general_examples(sess, cmp, lap_n, ref_label, ms):
    from .team_general import GENERAL
    from .mechanic import car_kind
    kind = car_kind(sess)
    ctx = build_context(sess, cmp, lap_n, ref_label, None, ms)
    out = []
    for q, k, a in GENERAL:
        if k != "any" and k != kind:
            continue
        out.append({"messages": [{"role": "system", "content": SYSTEM + "\n\nDATA:\n" + ctx},
                                 {"role": "user", "content": q}, {"role": "assistant", "content": a}]})
    return out


def build(out_path, max_pairs_per_session=12, log=print):
    idx = lap_index()
    rows = []
    for sid, v in idx.items():
        if not v.get("best"):
            continue
        try:
            sess = open_session(v["path"])
        except Exception as e:
            log(f"skip {v['path']}: {e!r}"); continue
        full = [L for L in sess.laps if L["complete"] and not L["pit"]]
        if len(full) < 2:
            continue
        best = sess.best["n"]
        others = [L for L in full if L["n"] != best]
        R.shuffle(others)
        for L in others[:max_pairs_per_session]:
            try:
                rows += examples_for(sess, L["n"], sess, best, f"your best lap this session ({fmt_lap(sess.best['time'])})")
            except Exception as e:
                log(f"  lap {L['n']}: {e!r}")
        # the best lap vs the all-time best from another session
        try:
            from .analysis import all_time_best
            from .telemetry import Session
            ab = all_time_best(idx, sess.car_path, sess.track_name)
            if ab and ab[0] != sid and ab[1]["best"]["time"] < sess.best["time"] - 0.05:
                rsess = Session(ab[1]["path"])
                rows += examples_for(sess, best, rsess, ab[1]["best"]["n"], f"your all-time best ({fmt_lap(ab[1]['best']['time'])})")
        except Exception as e:
            log(f"  all-time: {e!r}")
        # general questions, answered with this session's data attached (taught twice per car/track)
        if R.random() < 0.35:
            try:
                cmp = compare(sess, others[0]["n"] if others else best, sess, best, points=60)
                if cmp.get("delta_ok", True):
                    rows += general_examples(sess, cmp, others[0]["n"] if others else best, "your best lap this session", car_summary(sess))
            except Exception as e:
                log(f"  general: {e!r}")
        log(f"{os.path.basename(v['path'])}: {len(rows)} examples so far")
    R.shuffle(rows)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


if __name__ == "__main__":
    n = build(sys.argv[1] if len(sys.argv) > 1 else "team_train.jsonl")
    print("examples:", n)
