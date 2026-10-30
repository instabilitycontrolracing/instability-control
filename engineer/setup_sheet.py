"""iPad SETUP sheet (2026-10-30, #602; merges #580 meeting setup talk, #581 always-on SETUP tab, #582 review page).

Angelo: "putting suggested setups from the race meeting into the iPad so I can easily reference it ... take the
screenshots I sent of the full setup options menu and use those as a reference".

  * Garage layout per car (garage_layouts/<car>.json): iRacing's own garage menu - the tabs, the sections in their
    order, every field with its name, its unit (imperial: lbs, in, psi, F, gal, mph) and whether it has < > arrows /
    a drop-down (adjustable) or is read-only. The BMW M Hybrid V8 is transcribed from his 9 screenshots. A car with no
    layout file falls back to a generic sheet grouped by iRacing's own CarSetup section names.
  * A suggestion = the rule-based changes (My style #491 or the team meeting's setup advice) + his real setup values
    at that moment (the CarSetup block iRacing writes into the session info). Saved with date, track, car, session
    and the reasons; the newest one is what the iPad shows; a short history is kept.
  * The sheet: every field with his current value; changed fields show current -> suggested, the click count /
    direction and the reason; a checklist that ticks itself when the live setup (session info) shows the change.

NEVER made-up numbers (#419): values come only from iRacing's CarSetup (unit-converted metric -> imperial, the same
conversion the garage does) and from the rulebook's own step sizes ("0.5%", "one click"). A suggested number is only
shown when the rule names an exact amount (0.5% bias) or a count of clicks on a field that moves one by one
(dampers, ARB blades, TC, migration); otherwise the sheet shows the direction only ("up a touch"). Unknown = "—".

TODO: BMW M4 GT3 layout (garage_layouts/bmw_m4_gt3.json) - no screenshots yet; until then the M4 uses the generic sheet.
"""
import json
import os
import re
import struct
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.join(HERE, "garage_layouts")
STORE_PATH = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "RaceEngineer", "setup_suggestions.json")
HISTORY = 8
DASH = "—"

_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_TOK = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(n/mm|km/h|kph|kpa|ft-lbs|lbs/in|lbs|mm|cm|in|nm|bar|psi|gal|mph|deg|turns|clicks|kg|n|l|c|f|%|\")?", re.I)

# metric -> imperial, the same factors iRacing's garage uses
_FACT = {("mm", "in"): 1 / 25.4, ("cm", "in"): 1 / 2.54, ("kpa", "psi"): 0.1450377, ("bar", "psi"): 14.503774,
         ("n/mm", "lbs/in"): 5.7101471, ("n", "lbs"): 0.22480894, ("kg", "lbs"): 2.2046226, ("l", "gal"): 0.26417205,
         ("km/h", "mph"): 0.62137119, ("kph", "mph"): 0.62137119, ("nm", "ft-lbs"): 0.73756215}
_TARGET = {"in": "in", "inch": "in", "in_of": "in", "in32": "in", "lbs/in": "lbs/in", "lbs": "lbs", "psi": "psi",
           "gal": "gal", "mph": "mph", "ft-lbs": "ft-lbs", "F3": "f"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# ------------------------------------------------------------------ layouts
def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def layouts():
    out = []
    try:
        names = sorted(os.listdir(LAYOUT_DIR))
    except OSError:
        names = []
    for n in names:
        if n.endswith(".json"):
            d = _load(os.path.join(LAYOUT_DIR, n))
            if d and d.get("tabs"):
                d["_file"] = n
                out.append(d)
    return out


def layout_for(car_path=None, car_name=None):
    """The garage layout for this car (matched on iRacing's CarPath, else the screen name), or None."""
    cp, cn = norm(car_path), norm(car_name)
    for d in layouts():
        for m in d.get("match") or []:
            if cp and norm(m) == cp:
                return d
        if cn and norm(d.get("car")) == cn:
            return d
    return None


def fields(layout):
    """Every field of a layout in garage order: (tab, section, field, path)."""
    for tab in layout.get("tabs") or []:
        for row in tab.get("rows") or []:
            for sec in row:
                for f in sec.get("fields") or []:
                    yield tab, sec, f, f"{tab.get('yaml')}.{sec.get('yaml')}.{f.get('yaml')}"


def _split_camel(k):
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", str(k))
    w = [x if (x.isupper() and len(x) > 1) else x.lower() for x in s.split()]
    s = " ".join(w)
    return s[:1].upper() + s[1:] if s else s


def generic_layout(carsetup, car=""):
    """No layout file for this car: iRacing's own CarSetup sections, in the order iRacing writes them."""
    tabs = []
    for tk, tv in (carsetup or {}).items():
        if not isinstance(tv, dict):
            continue
        rows, loose = [], []
        for sk, sv in tv.items():
            if isinstance(sv, dict):
                rows.append([{"name": _split_camel(sk).upper(), "yaml": sk,
                              "fields": [{"label": _split_camel(fk), "yaml": fk, "adj": "unknown", "unit": "auto"}
                                         for fk, fv in sv.items() if not isinstance(fv, dict)]}])
            else:
                loose.append({"label": _split_camel(sk), "yaml": sk, "adj": "unknown", "unit": "auto"})
        if loose:
            rows.insert(0, [{"name": _split_camel(tk).upper(), "yaml": None, "fields": loose}])
        tabs.append({"name": _split_camel(tk).upper(), "yaml": tk, "rows": rows})
    return {"car": car, "generic": True, "units": "imperial (converted from iRacing's values)", "tabs": tabs, "keys": {}}


# ------------------------------------------------------------------ values
def flatten(carsetup):
    """CarSetup dict -> {'Chassis.LeftFront.Camber': '-2.9 deg', ...} (only leaf values)."""
    out = {}

    def walk(d, path):
        for k, v in (d or {}).items():
            if isinstance(v, dict):
                walk(v, path + [str(k)])
            elif v is not None and k != "UpdateCount":
                out[".".join(path + [str(k)])] = str(v).strip()
    walk(carsetup if isinstance(carsetup, dict) else {}, [])
    return out


def lookup(flat, tab_yaml, sec_yaml, f_yaml):
    """A field's raw value: exact path first, then the same names compared loosely (spaces / case)."""
    p = ".".join(x for x in (tab_yaml, sec_yaml, f_yaml) if x)
    if p in flat:
        return p, flat[p]
    want = [norm(x) for x in (tab_yaml, sec_yaml, f_yaml) if x]
    for k, v in flat.items():
        parts = [norm(x) for x in k.split(".")]
        if parts == want:
            return k, v
    return p, None


def _fmt(x, dp):
    s = f"{x:.{dp}f}"
    return s.lstrip("-") if float(s) == 0 else s


def _conv(n, src, unit):
    """One number with its source unit -> the field's display unit; None when it can't be done honestly."""
    src = (src or "").lower()
    tgt = _TARGET.get(unit)
    if tgt is None:
        return n
    if src in ("", tgt, '"') or (tgt == "in" and src == '"'):
        return n
    if tgt == "f":
        return n * 9 / 5 + 32 if src == "c" else (n if src == "f" else None)
    f = _FACT.get((src, tgt))
    return n * f if f else None


def display(raw, field):
    """iRacing's raw value -> what the garage shows with Metric units off. Returns (text, number) - number is the
    first value in display units (for comparing), None for text fields. Unknown -> (DASH, None)."""
    if raw is None or str(raw).strip() == "":
        return DASH, None
    raw = str(raw).strip()
    unit = field.get("unit") or "raw"
    dp = int(field.get("dp", 3))
    if unit in ("text", "raw"):
        return raw, None
    if unit == "auto":
        return _auto(raw)
    toks = [(float(m.group(1)), m.group(2)) for m in _TOK.finditer(raw)]
    if not toks:
        return raw, None
    n0, s0 = toks[0]
    if unit in ("clicks", "int", "num", "pct", "deg"):
        return raw, n0                                         # same unit as the garage: shown exactly as iRacing wrote it
    if unit == "in_of":
        if len(toks) < 2:
            return raw, None
        a, b = _conv(toks[0][0], toks[0][1], unit), _conv(toks[1][0], toks[1][1], unit)
        if a is None or b is None:
            return raw, None
        return f"{_fmt(a, dp)} in of {_fmt(b, dp)} in", a
    if unit == "F3":
        vals = [_conv(n, s, unit) for n, s in toks]
        if any(v is None for v in vals):
            return raw, None
        return " ".join(f"{v:.0f}F" for v in vals), vals[0]
    if unit == "pct3":
        return " ".join(f"{n:.0f}%" for n, _ in toks), toks[0][0]
    v = _conv(n0, s0, unit)
    if v is None:
        return raw, None
    if unit == "in32":
        k = int(round(v * 32))
        return f"{k:+d}/32\"", v
    if unit == "inch":
        return f"{_fmt(v, dp)}\"", v
    return f"{_fmt(v, dp)} {unit}", v


_AUTO = {"mm": ("in", 3), "cm": ("in", 3), "kpa": ("psi", 1), "bar": ("psi", 1), "n/mm": ("lbs/in", 0), "n": ("lbs", 0),
         "kg": ("lbs", 0), "l": ("gal", 1), "km/h": ("mph", 1), "kph": ("mph", 1), "nm": ("ft-lbs", 0), "c": ("F", 0)}


def _auto(raw):
    """Generic sheet (no layout): every metric number converted to imperial in place, the rest left as iRacing wrote it."""
    first = []

    def rep(m):
        n, u = float(m.group(1)), (m.group(2) or "").lower()
        if u not in _AUTO:
            first.append(n)
            return m.group(0)
        tgt, dp = _AUTO[u]
        v = n * 9 / 5 + 32 if u == "c" else n * _FACT[(u, tgt)]
        first.append(v)
        return f"{_fmt(v, dp)}{tgt}" if tgt == "F" else f"{_fmt(v, dp)} {tgt}"
    txt = _TOK.sub(rep, raw)
    return txt, (first[0] if first else None)


def _with_number(text, new, dp):
    """'6 (TCLAT)' + 7 -> '7 (TCLAT)'; '48.50%' + 48.0 -> '48.00%' (keeps iRacing's own wording / decimals)."""
    m = _NUM.search(text or "")
    if not m:
        return None
    s = m.group(0)
    d = len(s.split(".")[1]) if "." in s else dp
    nv = f"{new:.{d}f}"
    if s.startswith("+") and not nv.startswith("-"):
        nv = "+" + nv
    return text[:m.start()] + nv + text[m.end():]


# ------------------------------------------------------------------ rulebook change -> garage fields
# rulebook steps without a key (dampers, toe, pads ...) found by their words; paths for the BMW GTP layout's names
TEXT_RULES = [
    (("rear low-speed rebound",), ["Chassis.LeftRear.LsRbdDamping", "Chassis.RightRear.LsRbdDamping"]),
    (("front low-speed rebound",), ["Chassis.LeftFront.LsRbdDamping", "Chassis.RightFront.LsRbdDamping"]),
    (("rear low-speed compression",), ["Chassis.LeftRear.LsCompDamping", "Chassis.RightRear.LsCompDamping"]),
    (("high-speed compression slope", "hs slope"), ["Chassis.LeftFront.HsCompDampSlope", "Chassis.RightFront.HsCompDampSlope",
                                                   "Chassis.LeftRear.HsCompDampSlope", "Chassis.RightRear.HsCompDampSlope"]),
    (("high-speed compression",), ["Chassis.LeftFront.HsCompDamping", "Chassis.RightFront.HsCompDamping",
                                   "Chassis.LeftRear.HsCompDamping", "Chassis.RightRear.HsCompDamping"]),
    (("high-speed rebound",), ["Chassis.LeftFront.HsRbdDamping", "Chassis.RightFront.HsRbdDamping",
                               "Chassis.LeftRear.HsRbdDamping", "Chassis.RightRear.HsRbdDamping"]),
    (("front toe",), ["Chassis.Front.ToeIn"]),
    (("rear toe",), ["Chassis.LeftRear.ToeIn", "Chassis.RightRear.ToeIn"]),
    (("pad",), ["BrakesDriveUnit.BrakeSpec.PadCompound"]),
    (("third spring",), ["Chassis.Rear.ThirdSpring"]),
    (("clutch plates", "friction plates"), ["BrakesDriveUnit.RearDiffSpec.ClutchFrictionPlates"]),
    (("ramp angle",), ["BrakesDriveUnit.RearDiffSpec.CoastDriveRampAngles"]),
]

_WORDS = {"one": 1, "a single": 1, "two": 2, "three": 3, "four": 4, "five": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}
_DIRWORDS = ["more negative", "less negative", "towards zero", "more positive", "softer", "stiffer", "forward", "rearward",
             "up", "down", "higher", "lower", "raise", "more", "less", "fewer", "reduce", "increase"]
_DIRSIGN = {"more negative": -1, "less negative": +1, "towards zero": +1, "more positive": +1, "softer": -1, "stiffer": +1,
            "forward": +1, "rearward": -1, "up": +1, "down": -1, "higher": +1, "lower": -1, "raise": +1, "more": +1,
            "less": -1, "fewer": -1, "reduce": -1, "increase": +1}


def targets_for(change, layout, flat):
    """Garage field paths a rulebook change acts on (the layout's key map, then the step's words). Generic sheets:
    the rulebook's own value names (setup_bank.K) looked up in this car's CarSetup."""
    key = change.get("key")
    t = (change.get("t") or "").lower()
    out = list((layout.get("keys") or {}).get(key) or []) if key else []
    if not out and not layout.get("generic"):
        for words, paths in TEXT_RULES:
            if any(w in t for w in words):
                out = list(paths)
                break
    if not out and not key:
        from .setup_guide import _key_for                  # older meeting results carry no key: from the words
        key = _key_for(change)
        out = list((layout.get("keys") or {}).get(key) or []) if key else []
    if not out and key:
        from .setup_bank import K
        for n in K.get(key, []):
            if n.startswith("@"):
                continue
            hit = next((p for p in flat if p.endswith("." + n) or p.split(".")[-1] == n), None)
            if hit:
                out = [hit]
                break
    # both sides of an axle when the rule names the axle (camber_f -> LF + RF is in the key map already)
    return [p for p in dict.fromkeys(out)]


def plan(change):
    """How much / which way, from the rule's own words. -> {"dir", "word", "clicks", "amount", "how"}"""
    t = " " + (change.get("t") or "").lower().replace("–", "-") + " "
    word = None
    for w in _DIRWORDS:
        if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t):
            word = w
            break
    if " towards zero" in t:
        word = "towards zero"
    d = _DIRSIGN.get(word, 0)
    clicks = None
    m = re.search(r"(?<![a-z0-9.])(one|a single|two|three|four|five|[1-5])\s+(click|step)s?\b", t)
    if m:
        clicks = _WORDS[m.group(1)]
    amount = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", t)
    if m and not re.search(r"\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*%", t):
        amount = float(m.group(1))
    rng = re.search(r"(\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*%)", t)
    pretty = {"raise": "higher", "reduce": "less", "increase": "more", "fewer": "fewer"}.get(word, word) or "change"
    if clicks:
        unit = "click" if "click" in t else "step"
        how = f"{clicks} {unit}{'s' if clicks != 1 else ''} {pretty}"
    elif amount is not None:
        how = f"{amount:g}% {pretty}"
    elif rng:
        how = f"{rng.group(1).replace(' ', '')} {pretty}"
    else:
        how = (f"{pretty} a touch" if "touch" in t else f"a little {pretty}" if "little" in t else pretty)
    return {"dir": d, "word": pretty, "clicks": clicks, "amount": amount, "how": how}


# ------------------------------------------------------------------ building a suggestion
def _reason(c):
    """The reason in one plain sentence: what was measured, else the rulebook's why."""
    for k in ("why", "rule"):
        s = (c.get(k) or "").strip()
        if s:
            s = re.split(r"(?<=[.!?])\s", s)[0]
            return s if s.endswith((".", "!", "?")) else s + "."
    return ""


def make_suggestion(changes, carsetup, car_path="", car="", track="", session="", source="My style", date=None,
                    notes=None, sessions=None):
    """Freeze a rule-based change list against his real setup at this moment. -> the suggestion dict (JSON-safe)."""
    flat = flatten(carsetup)
    lay = layout_for(car_path, car) or generic_layout(carsetup, car)
    out = []
    for c in changes or []:
        tg = targets_for(c, lay, flat)
        p = plan(c)
        fl = {}
        for path in tg:
            meta = _field_meta(lay, path)
            raw = flat.get(path)
            if raw is None and meta is not None:
                raw = lookup(flat, *path.split(".", 2))[1]
            txt, num = display(raw, meta or {"unit": "raw"})
            sug_txt, sug_num = None, None
            if num is not None and p["dir"]:
                step = (meta or {}).get("step")
                if p["clicks"] and step and (meta or {}).get("unit") in ("clicks", "int"):
                    sug_num = num + p["dir"] * p["clicks"] * step
                elif p["amount"] is not None and (meta or {}).get("unit") == "pct":
                    sug_num = round(num + p["dir"] * p["amount"], 4)
                if sug_num is not None:
                    sug_txt = _with_number(txt, sug_num, int((meta or {}).get("dp", 0)))
                    if sug_txt is None:
                        sug_num = None
            fl[path] = {"before": raw, "before_txt": txt, "before_num": num, "sug_txt": sug_txt, "sug_num": sug_num}
        how = p["how"]
        if fl and all(v["before_num"] is None for v in fl.values()):
            how = c.get("t") or how                            # a drop-down (pads, ramp angles): the rule's own words
        note = ((lay.get("key_notes") or {}).get(c.get("key")) or "") if c.get("key") else ""
        out.append({"t": c.get("t", ""), "key": c.get("key"), "where": c.get("where"), "how": how, "dir": p["dir"],
                    "reason": _reason(c), "rule": (c.get("rule") or "").strip(), "style": c.get("style"), "for": c.get("for"),
                    "note": note, "fields": fl})
    made = time.time()
    return {"id": time.strftime("%Y%m%d-%H%M%S", time.localtime(made)) + f"-{int(made * 1000) % 1000:03d}",
            "made": made, "date": date or time.strftime("%Y-%m-%d %H:%M", time.localtime(made)), "car": car, "car_path": car_path,
            "track": track, "session": session, "source": source, "layout": lay.get("_file") or ("generic" if lay.get("generic") else ""),
            "changes": out, "values": flat, "notes": list(notes or []), "sessions": list(sessions or [])}


def _field_meta(lay, path):
    for tab, sec, f, p in fields(lay):
        if p == path:
            return f
    return None


# ------------------------------------------------------------------ live status (auto-tick, #514)
def _state(fv, live_num, d):
    """One field of a change against the live value: 'done' / 'check' / 'todo'."""
    if live_num is None:
        return "todo"
    if fv.get("sug_num") is not None:
        tol = 1e-6 + 0.5 * 10 ** -4
        if abs(live_num - fv["sug_num"]) <= max(tol, abs(fv["sug_num"]) * 1e-4):
            return "done"
        b = fv.get("before_num")
        if b is not None and d and (live_num - b) * d < 0:
            return "check"
        return "todo"
    b = fv.get("before_num")
    if b is None or abs(live_num - b) < 1e-9:
        return "todo"
    if not d or (live_num - b) * d > 0:
        return "done"
    return "check"


def _state_text(fv, live_txt, live_raw):
    """Text fields (pads, ramp angles): done when the value changed from the one at suggestion time."""
    if live_raw is None or fv.get("before") is None:
        return "todo"
    return "done" if str(live_raw).strip() != str(fv["before"]).strip() else "todo"


def sheet(sug, live_setup=None, live_car_path=None, ticks=None, live_bias=None):
    """The page's data: the garage layout filled with values, the changes on their fields, and the checklist states.
    live_setup = the CarSetup of the session running now (None outside a session); only used when it is the same car."""
    ticks = ticks or {}
    cp = (sug or {}).get("car_path") or live_car_path or ""
    stored = (sug or {}).get("values") or {}
    live_flat = flatten(live_setup) if live_setup else {}
    same_car = bool(live_flat) and (not sug or not live_car_path or not sug.get("car_path") or norm(live_car_path) == norm(sug.get("car_path")))
    if not same_car:
        live_flat = {}
    lay = layout_for(cp, (sug or {}).get("car")) or generic_layout(_unflatten(live_flat or stored), (sug or {}).get("car", ""))
    cur = dict(stored)
    cur.update(live_flat)
    changed = {}
    for i, c in enumerate((sug or {}).get("changes") or []):
        for p in c["fields"]:
            changed.setdefault(p, []).append(i)

    # checklist states
    items = []
    for i, c in enumerate((sug or {}).get("changes") or []):
        states = []
        for p, fv in c["fields"].items():
            meta = _field_meta(lay, p) or {"unit": "raw"}
            raw = live_flat.get(p)
            if p.endswith("BrakePressureBias") and live_bias is not None:
                raw = f"{live_bias:.2f}%"                    # the in-car BB knob (dcBrakeBias) is the live bias
            if raw is None:
                states.append("todo")
                continue
            txt, num = display(raw, meta)
            states.append(_state(fv, num, c["dir"]) if num is not None or fv.get("before_num") is not None
                          else _state_text(fv, txt, raw))
        hand = ticks.get(str(i))
        auto = bool(states) and all(s == "done" for s in states)
        if hand is True:
            st = "done"
        elif hand is False:
            st = "todo"
        elif auto or hand == "auto":
            st = "done"
        elif "check" in states:
            st = "check"
        elif not c["fields"]:
            st = "manual"
        else:
            st = "todo"
        items.append({"i": i, "t": c["t"], "how": c["how"], "reason": c["reason"], "rule": c.get("rule"), "note": c.get("note"),
                      "where": c.get("where"), "state": st, "auto": auto, "hand": hand,
                      "fields": [{"path": p, "label": _label(lay, p), "before": fv["before_txt"], "sug": fv["sug_txt"]}
                                 for p, fv in c["fields"].items()]})

    tabs = []
    for tab in lay.get("tabs") or []:
        rows = []
        for row in tab.get("rows") or []:
            secs = []
            for sec in row:
                fl = []
                for f in sec.get("fields") or []:
                    p, raw = lookup(cur, tab.get("yaml"), sec.get("yaml"), f.get("yaml"))
                    txt, _ = display(raw, f)
                    ch = changed.get(p) or []
                    e = {"label": f["label"], "adj": f.get("adj", "unknown"), "value": txt, "path": p,
                         "live": p in live_flat}
                    if ch:
                        i = ch[0]
                        c = sug["changes"][i]
                        fv = c["fields"][p]
                        e.update({"changed": True, "i": i, "was": fv["before_txt"], "sug": fv["sug_txt"], "how": c["how"],
                                  "reason": c["reason"], "state": items[i]["state"]})
                    fl.append(e)
                # values iRacing reports in this section that the layout doesn't list (HYBRID CONFIG is empty in
                # the garage screenshots): shown read-only under the section so nothing he sees is hidden
                if not lay.get("generic") and sec.get("yaml"):
                    pre = f"{tab.get('yaml')}.{sec.get('yaml')}."
                    known = {norm(f.get("yaml")) for f in sec.get("fields") or []}
                    for k, v in cur.items():
                        if k.startswith(pre) and "." not in k[len(pre):] and norm(k[len(pre):]) not in known:
                            fl.append({"label": _split_camel(k[len(pre):]), "adj": "unknown", "value": v, "path": k,
                                       "live": k in live_flat, "extra": True})
                secs.append({"name": sec["name"], "fields": fl})
            rows.append(secs)
        tabs.append({"name": tab["name"], "rows": rows, "empty": not rows})
    unplaced = [it for it in items if not it["fields"]]
    return {"has": bool(sug), "id": (sug or {}).get("id"), "car": (sug or {}).get("car"), "track": (sug or {}).get("track"),
            "session": (sug or {}).get("session"), "date": (sug or {}).get("date"), "source": (sug or {}).get("source"),
            "notes": (sug or {}).get("notes") or [], "sessions": (sug or {}).get("sessions") or [],
            "layout": {"car": lay.get("car"), "generic": bool(lay.get("generic")), "units": lay.get("units")},
            "live_values": bool(live_flat), "tabs": tabs, "items": items, "unplaced": [u["i"] for u in unplaced],
            "done": sum(1 for it in items if it["state"] == "done"), "total": len(items)}


def _label(lay, path):
    for tab, sec, f, p in fields(lay):
        if p == path:
            return f"{tab['name'].title()} › {sec['name'].title()} › {f['label']}"
    parts = path.split(".")
    return " › ".join(_split_camel(x) for x in parts)


def _unflatten(flat):
    out = {}
    for k, v in (flat or {}).items():
        d = out
        ps = k.split(".")
        for p in ps[:-1]:
            d = d.setdefault(p, {})
        d[ps[-1]] = v
    return out


# ------------------------------------------------------------------ the store ("Push to iPad")
class Store:
    """The iPad's current suggestion + a short history, with the checklist ticks. One JSON file."""

    def __init__(self, path=None):
        self.path = path or STORE_PATH
        self.lock = threading.Lock()

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("items"), list):
                d.setdefault("ticks", {})
                return d
        except (OSError, ValueError):
            pass
        return {"current": None, "items": [], "ticks": {}}

    def _write(self, d):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def push(self, sug):
        """Make this suggestion the iPad's current one (newest first, HISTORY kept)."""
        with self.lock:
            d = self._read()
            d["items"] = [sug] + [x for x in d["items"] if x.get("id") != sug["id"]]
            for old in d["items"][HISTORY:]:
                d["ticks"].pop(old.get("id"), None)
            d["items"] = d["items"][:HISTORY]
            d["current"] = sug["id"]
            self._write(d)
        return sug["id"]

    def get(self, sid=None):
        d = self._read()
        sid = sid or d.get("current")
        sug = next((x for x in d["items"] if x.get("id") == sid), None)
        return sug, dict(d["ticks"].get(sid or "", {}))

    def history(self):
        d = self._read()
        return [{"id": x["id"], "date": x.get("date"), "track": x.get("track"), "car": x.get("car"), "source": x.get("source"),
                 "n": len(x.get("changes") or []), "current": x["id"] == d.get("current")} for x in d["items"]]

    def tick(self, sid, i, on):
        """on: True / False by hand, 'auto' when the live setup showed it (kept so it stays ticked offline)."""
        with self.lock:
            d = self._read()
            t = d["ticks"].setdefault(sid, {})
            t[str(int(i))] = on
            self._write(d)
            return dict(t)


def view(store, sid=None, live_setup=None, live_car_path=None, live_bias=None):
    """Sheet for the iPad; remembers auto-ticks so the list stays ticked after he leaves the session."""
    sug, ticks = store.get(sid)
    sh = sheet(sug, live_setup, live_car_path, ticks, live_bias)
    if sug:
        for it in sh["items"]:
            if it["auto"] and it["hand"] is None:
                store.tick(sug["id"], it["i"], "auto")
    sh["history"] = store.history()
    return sh


def same(a, b):
    """Two suggestions with the same changes on the same setup (the meeting re-opened): no new push."""
    if not a or not b:
        return False
    return (a.get("car_path") == b.get("car_path") and a.get("values") == b.get("values")
            and [c["t"] for c in a.get("changes") or []] == [c["t"] for c in b.get("changes") or []])


def from_meeting(setup_advice):
    """The meeting's setup advice (forensics.setup_advice) -> rulebook changes. Only the ones that repeat (3+ times,
    technique first) become changes; the others stay 'it's the driving'."""
    out = []
    for x in setup_advice or []:
        if x.get("repeat") and x.get("first_fix"):
            out.append({"t": x["first_fix"], "key": x.get("key"), "rule": x.get("why") or "",
                        "why": f"{x['problem']}: {x['times']} times tonight ({x.get('where') or 'several corners'}).",
                        "for": x["problem"]})
    return out


# ------------------------------------------------------------------ words for the meeting (text only, #580)
def meeting_lines(sug, max_items=4):
    """The setup summary in words for the team meeting / debrief. Text only - no new spoken lines (see
    docs/proposals/setup-ipad-lines-for-approval.md)."""
    if not sug or not sug.get("changes"):
        return []
    n = len(sug["changes"])
    where = " at ".join(x for x in (sug.get("car"), sug.get("track")) if x)
    L = [f"{n} setup change{'s' if n != 1 else ''}" + (f" for the {where}" if where else "") + f" ({sug.get('source') or 'rulebook'}):"]
    for k, c in enumerate(sug["changes"][:max_items], 1):
        now = ""
        for fv in c["fields"].values():
            if fv.get("before_txt") and fv["before_txt"] != DASH:
                now = f" (now {fv['before_txt']}" + (f", to {fv['sug_txt']}" if fv.get("sug_txt") else "") + ")"
                break
        L.append(f"{k}. {c['t']}: {c['how']}{now}. {c['reason']}".strip())
    L.append("It is on your iPad now: open SETUP. One change at a time, 3 laps, compare.")
    return L


# ------------------------------------------------------------------ reading a recording's setup
def ibt_setup(path):
    """CarSetup + a few facts from a recording's session info (header only - no telemetry read)."""
    from .telemetry import parse_yaml
    with open(path, "rb") as f:
        head = f.read(112)
        _ver, _st, _tick, _upd, slen, soff = struct.unpack_from("<6i", head, 0)
        f.seek(soff)
        si = f.read(slen).rstrip(b"\x00").decode("latin-1")
    info = parse_yaml(si)
    return info.get("CarSetup") or {}, info


def session_label(info, nums=None):
    """The session(s) a recording covers: 'Practice', 'Race' ... nums = the SessionNum values seen in its telemetry;
    without them every session of the event is named ('Practice / Qualify / Race') - never a guess."""
    try:
        ss = (info.get("SessionInfo") or {}).get("Sessions") or []
        if nums is not None:
            ss = [x for x in ss if x.get("SessionNum") in set(int(n) for n in nums)]
        return " / ".join(dict.fromkeys(str(x.get("SessionType") or "") for x in ss if x.get("SessionType")))
    except Exception:
        return ""
