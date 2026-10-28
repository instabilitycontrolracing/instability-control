"""Class of a car from iRacing's own class data (2026-10-26, #49 - same rules as Grandstand's ClassDetection).

Order: CarClassShortName ("GT3 Class", "GTP", "LMP2"...), then CarClassID (replays can leave the short name empty - the
numbers marked verified came from Grandstand's log of a real session), then the car's name as a last resort.
Labels: GTP, LMP2, LMP3, GT3, GTD, GTD_Pro, GT4, GTE (the class names the voice has recordings for), else None.
"""
import re

SHORT = {"GTP": "GTP", "LMDH": "GTP", "LMH": "GTP", "HYPERCAR": "GTP", "LMP2": "LMP2", "P2": "LMP2", "LMP3": "LMP3",
         "P3": "LMP3", "GT3": "GT3", "GTD": "GTD", "GTDPRO": "GTD_Pro", "GTDP": "GTD_Pro", "GT4": "GT4", "GTE": "GTE",
         "GTEPRO": "GTE", "GTEAM": "GTE", "GTLM": "GTE"}
IDS = {4029: "GTP",      # verified 2026-10-26 (Le Mans replay)
       4011: "GT3",      # verified 2026-10-26 (Le Mans replay)
       2523: "LMP2", 2708: "GT3", 4084: "GT4"}


def _norm(s):
    k = re.sub(r"[^A-Z0-9]", "", str(s or "").upper())
    return k[:-5] if len(k) > 5 and k.endswith("CLASS") else k


def from_car_name(s):
    s = str(s or "").lower()
    if any(k in s for k in ("gtp", "lmdh", "hybrid v8", "499p", "963", "arx-06", "v-series")): return "GTP"
    if "lmp2" in s or "p217" in s: return "LMP2"
    if "lmp3" in s: return "LMP3"
    if "gt3" in s: return "GT3"
    if "gt4" in s: return "GT4"
    if "gte" in s: return "GTE"
    return None


def label(d):
    """d = a DriverInfo driver entry -> class label or None."""
    d = d or {}
    k = _norm(d.get("CarClassShortName"))
    if k:
        if k in SHORT: return SHORT[k]
        if k.startswith("GT3"): return "GT3"
        if k.startswith("GT4"): return "GT4"
    try:
        cid = int(d.get("CarClassID") or 0)
    except (TypeError, ValueError):
        cid = 0
    if cid in IDS:
        return IDS[cid]
    return from_car_name(f"{d.get('CarScreenName') or ''} {d.get('CarPath') or ''}")


def spoken(d):
    """What to call the class out loud / on screen: our label, else iRacing's own short name."""
    return label(d) or (d or {}).get("CarClassShortName") or None
