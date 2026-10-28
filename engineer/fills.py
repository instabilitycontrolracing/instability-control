"""Turn live values into fill-in clips (building blocks rendered in the engineer's voice)."""
import re


def _b(blocks, kind, key):
    return blocks.get(kind, {}).get(key)


def num_clips(n, blocks):
    n = int(round(n))
    c = _b(blocks, "num", str(n))
    if c:
        return [c]
    # 161..99999 with "thousand" / "hundred" blocks: 2450 -> two, thousand, four, hundred, fifty
    th, hu = _b(blocks, "big", "thousand"), _b(blocks, "big", "hundred")
    if 0 < n < 100000 and th and hu:
        out, k, h, r = [], n // 1000, (n % 1000) // 100, n % 100
        if k:
            out += num_clips(k, blocks) + [th]
        if h:
            out += [_b(blocks, "num", str(h)), hu]
        if r:
            out.append(_b(blocks, "num", str(r)))
        if all(out):
            return out
    # bigger than our number set: say it digit by digit ("one, six, two")
    out = [_b(blocks, "num", d) for d in str(abs(n))]
    return out if all(out) else None


def gap_clips(sec, blocks):
    sec = abs(float(sec))
    if sec < 0.05:
        sec = 0.1
    if sec < 9.95:
        return [_b(blocks, "gap", f"{round(sec, 1):.1f}")]
    if sec <= 60.5:
        return [_b(blocks, "gap", str(int(round(sec))))]
    return [_b(blocks, "gap", "over_minute")]


def lap_parts(sec):
    """Lap time -> (seconds, three decimal digits): 215.391 -> (35, "391"). Minutes are dropped, the way an
    engineer says it on the radio (request 2026-10-24: ':35.391', not '3:35.391')."""
    ms = int(round(float(sec) * 1000))
    return (ms // 1000) % 60, f"{ms % 1000:03d}"


def lap_clips(sec, blocks):
    """'thirty-five point three nine one' (the 'point' block when it has been rendered, else
    'thirty-five, three nine one' - also how engineers say it)."""
    s, dec = lap_parts(sec)
    out = [_b(blocks, "secs", f"0{s}")] if 0 < s < 10 else num_clips(s, blocks) or [None]
    pt = _b(blocks, "word", "point")
    if pt:
        out.append(pt)
    out += [_b(blocks, "num", d) for d in dec]
    return out


def time_clips(sec, blocks):
    """Clock times (whole minutes since midnight, 845 -> "fourteen", "oh five") and, for floats, lap times."""
    if isinstance(sec, float):
        return lap_clips(sec, blocks)
    sec = float(sec)
    m, s = int(sec // 60), int(sec % 60)
    out = []
    if m:
        out += num_clips(m, blocks)
        out.append(_b(blocks, "secs", f"0{s}") if s < 10 else _b(blocks, "num", str(s)))
    else:
        out += num_clips(s, blocks)
    return out


CLASS_KEYS = [("gtd_pro", "GTD_Pro"), ("gtd pro", "GTD_Pro"), ("gtdpro", "GTD_Pro"), ("gtp", "GTP"), ("lmdh", "GTP"),
              ("lmp2", "LMP2"), ("gtd", "GTD"), ("gt3", "GT3")]


def class_key(name):
    n = (name or "").lower()
    for k, v in CLASS_KEYS:
        if k in n:
            return v
    return None


def fill_clips(name, value, blocks, voice):
    """Returns a list of clip paths, or None if this value can't be said."""
    if value is None and name != "fuel unit":
        return None
    try:
        if name == "P":
            c = _b(blocks, "P", f"P{int(value)}")
            return [c] if c else None
        if name == "gap":
            out = gap_clips(value, blocks)
        elif name in ("n", "laps", "minutes", "percent"):
            out = num_clips(value, blocks)
        elif name == "car":
            s = re.sub(r"\D", "", str(value))
            if not s:
                return None
            out = num_clips(int(s), blocks) if not (len(s) > 1 and s[0] == "0") else [_b(blocks, "num", d) for d in s]
        elif name == "time":
            out = time_clips(value, blocks)
        elif name == "sector":
            out = [_b(blocks, "sector", str(int(value)))]
        elif name == "corner":
            out = [_b(blocks, "corner", value)]
        elif name == "side":
            out = [_b(blocks, "side", value.replace(" ", "_"))]
        elif name == "tyre corner":
            out = [_b(blocks, "tyre_corner", value.replace(" ", "_").replace("_tire", "") + "_tire")]
        elif name == "fuel unit":
            unit = "liters" if voice.fuel_metric else "gallons"
            if value == 1:
                unit = unit[:-1]
            out = [_b(blocks, "fuel_unit", unit)]
        elif name == "class":
            out = [_b(blocks, "class", class_key(value) or "")]
        elif name == "dec":                         # 3.2 -> "three point two" (the gap blocks)
            v = abs(float(value))
            out = gap_clips(v, blocks) if v < 9.95 else num_clips(v, blocks)
        elif name == "lic":
            out = [_b(blocks, "lic", str(value)[:1].upper())]
        elif name == "speed unit":
            out = [_b(blocks, "speed_unit", "kph" if voice.fuel_metric else "mph")]
        elif name == "dir":
            out = [_b(blocks, "dir", str(value))]
        elif name == "skies":
            out = [_b(blocks, "skies", str(value))]
        elif name == "txt":                      # free text (names, car models): only the stand-in voice can say it
            return None
        else:
            return None
    except (TypeError, ValueError):
        return None
    if not out or any(o is None for o in out):
        return None
    if any(voice._load(o) is None for o in out):
        return None
    return out


def shown(name, value):
    """How a fill appears in the on-screen readout (it should match what he says)."""
    if name == "time" and isinstance(value, float):
        s, dec = lap_parts(value)
        return f":{s:02d}.{dec}"
    return None


# ---------- the same values as words, for the stand-in voice (lines not rendered yet) ----------
def fill_text(name, value, metric):
    if name == "fuel unit":
        u = "litres" if metric else "gallons"
        return u[:-1] if value == 1 else u
    if name == "speed unit":
        return "kilometers per hour" if metric else "miles per hour"
    if value is None:
        return None
    try:
        if name == "P":
            return f"P {int(value)}"
        if name in ("gap", "dec"):
            v = abs(float(value))
            return f"{v:.1f}" if v < 9.95 else str(int(round(v)))
        if name == "time":
            if isinstance(value, float):                      # lap time: ':35.391' -> "35 point 3 9 1"
                s, dec = lap_parts(value)
                return f"{s} point {' '.join(dec)}"
            v = float(value); m, s = int(v // 60), int(v % 60)
            return f"{m} {s:02d}" if m else str(s)
        if name == "lic":
            return {"P": "Pro", "R": "Rookie", "D": "Delta", "C": "Charlie", "B": "Bravo", "A": "Alpha"}.get(
                str(value)[:1].upper(), str(value)[:1].upper())
        if name == "corner":
            return str(value).replace("_", " ").title()
        if name in ("dir", "skies"):
            return str(value).replace("_", " ")
        if name == "txt":
            return str(value)
        if name in ("n", "laps", "minutes", "percent", "car", "sector"):
            return str(int(round(float(re.sub(r"[^0-9.]", "", str(value)) or 0))))
        return str(value).replace("_", " ")
    except (TypeError, ValueError):
        return None
