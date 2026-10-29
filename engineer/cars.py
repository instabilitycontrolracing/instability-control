"""One car table for the whole engineer (car parity phase 2, 2026-10-29): every Sports Car / Prototype on iRacing,
found by its CarPath (where that is verified) or its iRacing CarID. Data: car_data.py (generated, sourced).

What the table does NOT know stays None, and the live telemetry decides instead (dcABS / dcTractionControl exist only
on cars that have them). The two BMWs keep exactly what the app did for them before.
"""
import re

from .car_data import CARS

BY_PATH = {c["path"].lower(): c for c in CARS if c["path"]}
BY_ID = {int(c["id"]): c for c in CARS if c.get("id") is not None}

# kinds -> the setup bank / mechanic table they use (the bank has GTP and GT3 tables from the BMW manuals; every other
# kind gets the generic "other" advice)
TABLE = {"gtp": "gtp", "gt3": "gt3"}
KIND_LABEL = {"gtp": "GTP", "gt3": "GT3", "gt4": "GT4", "gte": "GTE", "gt1": "GT1", "lmp1": "LMP1", "lmp2": "LMP2",
              "lmp3": "LMP3", "dp": "DP", "proto": "Prototype", "tcr": "TCR", "cup": "Cup", "touring": "Touring",
              "club": "Club", "classic": "Classic", "electric": "Electric", "other": "Other"}

# the BMWs' names as the app showed them before (kept), plus the GT4 Evo that was missing
_BMW_NAMES = {"bmwlmdh": "BMW M Hybrid V8", "bmwm4gt3": "BMW M4 GT3", "bmwm2g87": "BMW M2", "bmwm4gt4": "BMW M4 GT4"}


def lookup(path=None, car_id=None):
    """-> the car's entry or None. CarPath first (verified ones only), then the iRacing CarID."""
    c = BY_PATH.get(str(path or "").strip().lower())
    if c is not None:
        return c
    try:
        return BY_ID.get(int(car_id)) if car_id not in (None, "") else None
    except (TypeError, ValueError):
        return None


def of_driver(d):
    """A DriverInfo driver entry -> the car's entry or None."""
    d = d or {}
    return lookup(d.get("CarPath"), d.get("CarID"))


def name(path, car_id=None):
    """Display name for a CarPath (the raw path when the car is unknown)."""
    if path in _BMW_NAMES:
        return _BMW_NAMES[path]
    c = lookup(path, car_id)
    return c["name"] if c else path


def names():
    """{CarPath: display name} for every car with a verified CarPath."""
    out = {p: c["name"] for p, c in BY_PATH.items()}
    out.update(_BMW_NAMES)
    return out


def notes(path, car_id=None):
    c = lookup(path, car_id)
    return list(c["notes"]) if c else []


def kind(path=None, car_id=None, default=None):
    c = lookup(path, car_id)
    return c["kind"] if c else default


def table_kind(k):
    """Setup-bank table for a kind: gtp, gt3 or other."""
    return TABLE.get(k or "", "other")


def is_gtp(path=None, car_id=None, words=""):
    """Modern GTP class (LMDh / LMH). Known cars from the table; unknown ones by the old word match."""
    c = lookup(path, car_id)
    if c is not None:
        return c["kind"] == "gtp"
    t = f"{words} {path or ''}".lower()
    return any(k in t for k in ("gtp", "lmdh", "hybrid v8", "mhybrid"))


def is_hybrid(path=None, car_id=None, words=""):
    """Hybrid lines (deploy, regen, battery) only for a GTP that is a hybrid: the Valkyrie (no hybrid on iRacing's page)
    and the 1980s Nissan GTP are not."""
    c = lookup(path, car_id)
    if c is not None:
        return c["kind"] == "gtp" and c["hybrid"] is not False
    return is_gtp(path, car_id, words)


def is_electric(path=None, car_id=None):
    c = lookup(path, car_id)
    return bool(c and c["electric"])


def aid(path, car_id, which, live=None):
    """ABS / TC: True / False / None (unknown). live = what the telemetry says (True: the dc variable is there,
    False: it is not there on a live car / iRacing's own recording, None: can't tell) - it always wins."""
    if live is not None:
        return bool(live)
    c = lookup(path, car_id)
    return c.get(which) if c else None


def channel_state(data, name, source="ibt"):
    """Does a recording have this channel? True / False / None (can't tell: a replay recording keeps no dc values)."""
    if data is None:
        return None
    a = data.get(name) if hasattr(data, "get") else None
    if a is not None:
        try:
            import numpy as np
            if np.isfinite(np.asarray(a, dtype=float)).any():
                return True
        except Exception:
            return True
    return False if source in ("ibt", "live") else None


def session_aids(sess):
    """{'abs': bool|None, 'tc': bool|None} for a recorded session (telemetry.Session)."""
    if sess is None:
        return {"abs": None, "tc": None}
    d, src = getattr(sess, "d", None), getattr(sess, "source", "ibt")
    path, cid = getattr(sess, "car_path", ""), getattr(sess, "car_id", None)
    tc_live = channel_state(d, "dcTractionControl", src)
    tc2 = channel_state(d, "dcTractionControl2", src)
    if tc_live is not True and tc2 is True:
        tc_live = True
    return {"abs": aid(path, cid, "abs", channel_state(d, "dcABS", src)), "tc": aid(path, cid, "tc", tc_live)}


def spoken_class(path=None, car_id=None):
    """The class label the voice has recordings for, or None."""
    c = lookup(path, car_id)
    return c["cls"] if c else None


def class_text(path=None, car_id=None):
    """The class as text for the screen (TCR, Cup (Porsche), Supercars ...), or None."""
    c = lookup(path, car_id)
    return c["cls_text"] if c else None


# ---------------------------------------------------------------- sound-mix voice (E4)
def voice_band(path):
    """A draft sound-mix voice from the car's sourced engine (cylinders) and Lovely's shift-light rpm, the same way the
    M Hybrid V8 voice was worked out: a four-stroke fires cylinders/2 times per turn, so the firing note is
    rpm x cylinders / 120; the band runs from a slow exit (55 % of the shift rpm, as 4,500 of 8,200 on the BMW) to the
    shift light, and the voice lifts its middle. None when either fact is missing. Levels still need tuning by ear."""
    c = lookup(path)
    if not c or not c.get("cyl") or not c.get("shift_rpm") or c["electric"]:
        return None
    top = c["shift_rpm"] * c["cyl"] / 120.0
    lo = top * 4500 / 8200
    return {"cyl": c["cyl"], "rpm": c["shift_rpm"], "lo": lo, "hi": top, "note": int(round((lo + top) / 2 / 10.0) * 10)}


_CYL_WORD = {4: "four", 5: "five", 6: "six", 8: "V8", 10: "V10", 12: "V12"}


def engine_label(path):
    c = lookup(path)
    if not c or not c.get("cyl"):
        return None
    e = (c.get("engine") or "").lower()
    if c["cyl"] == 6 and "flat" in e:
        return "flat six"
    if c["cyl"] == 6 and re.search(r"\bv6\b", e):
        return "V6"
    return _CYL_WORD.get(c["cyl"], f"{c['cyl']}-cylinder")
