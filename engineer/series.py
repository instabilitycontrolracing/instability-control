"""Series prep: pick the live series you're practising for -> format, what to watch for, and your own numbers there.

Static facts are kept short on purpose. Schedule weeks are only listed where confirmed (2026 Season 4 started
15 Sep 2026); the rest says "check iRacing". Your numbers come from your own telemetry.
"""
import datetime as _dt
import json, math, os
import numpy as np

from .telemetry import CACHE_DIR, Session
from .track_theme import norm

SEASON_START = _dt.date(2026, 9, 15)       # 2026 Season 4, week 1
SCHEDULE_PDF = "https://us.v-cdn.net/6034148/uploads/597LPPDHT83M/2026s4.pdf"

MULTICLASS_GTP = ["GT3s brake much earlier: don't dive late.", "Pass on straights, not in fast corners.",
                  "Lapping traffic: be patient, one corner at a time.", "Mirrors when leaving the pits."]
MULTICLASS_GT3 = ["Hold your line when prototypes come by.", "Don't move in braking zones.",
                  "Fight your class, not the GTPs."]

SERIES = [
    {"id": "imsa_open", "rid": 447, "pdf": "IMSA iRacing Series by GO Fast", "name": "IMSA iRacing Series", "tag": "Open setup", "license": "Sports Car A",
     "classes": ["GTP", "LMP2", "GT3"], "minutes": 45, "setup": "Open",
     "weeks": {1: "Indianapolis Motor Speedway", 2: "Michelin Raceway Road Atlanta", 3: "Fuji International Speedway",
               5: "Long Beach Street Circuit"},
     "notes": ["Open setups: bring your own (Setup tab)."]},
    {"id": "imsa_fixed", "rid": 539, "pdf": "IMSA iRacing Series - Fixed", "name": "IMSA iRacing Series", "tag": "Fixed setup", "license": "Sports Car A",
     "classes": ["GTP", "LMP2", "GT3"], "minutes": 35, "setup": "Fixed",
     "weeks": {1: "Indianapolis Motor Speedway", 2: "Michelin Raceway Road Atlanta", 3: "Fuji International Speedway",
               5: "Long Beach Street Circuit"},
     "notes": ["Fixed setup: only in-car adjustments."]},
    {"id": "imsa_endurance", "rid": 419, "pdf": "IMSA Endurance Series", "name": "IMSA Endurance Series", "tag": "160 min", "license": "",
     "classes": ["GTP", "LMP2", "GT3"], "minutes": 160, "setup": "Open",
     "weeks": {}, "notes": ["Every 2 weeks, 4 race times.", "Long race: fuel and tyre plan matter."]},
    {"id": "practice", "name": "Just practice", "tag": "", "license": "", "classes": [], "minutes": 45, "setup": "",
     "weeks": {}, "notes": []},
]

TRACKS = {
    "circuitdes24heuresdumans": {"name": "Le Mans", "watch": [
        "Dunlop Chicane: lap-1 pile-ups. Brake early on lap 1.",
        "Tertre Rouge exit sets your Mulsanne speed.",
        "Mulsanne chicanes: GT3s brake far earlier.",
        "Mulsanne Corner, Indianapolis, Arnage: big stops, easy lock-ups.",
        "Porsche Curves: walls close, no passing here.",
        "Ford Chicanes: kerbs launch the car.",
        "Long lap: one mistake costs 10 s+."]},
    "circuitdespafrancorchamps": {"name": "Spa", "watch": [
        "La Source on lap 1: chaos. Stay out of it.",
        "Eau Rouge / Raidillon: commit only with a clean exit from La Source.",
        "Kemmel: slipstream and late passes into Les Combes.",
        "Bus Stop: track limits, and the main overtaking spot.",
        "Weather can differ around the lap."]},
    "michelinracewayroadatlanta": {"name": "Road Atlanta", "watch": [
        "Turn 1: uphill braking, blind exit.",
        "Esses: rhythm, no passing.",
        "Turn 10a/b: last-corner lunges.",
        "Walls are close: small mistakes end races."]},
    "roadatlanta": {"alias": "michelinracewayroadatlanta"},
    "daytonainternationalspeedway": {"name": "Daytona", "watch": [
        "Bus Stop: braking from top speed, track limits.",
        "Banking: GTPs pass high, GT3s stay low.",
        "Turn 1: lap-1 and restart pile-ups.",
        "Draft on the banking matters."]},
    "sebringinternationalraceway": {"name": "Sebring", "watch": [
        "Bumps: brake in a straight line.",
        "Turn 17: long, bumpy, sets the front straight.",
        "Hairpin: easy place to get hit.",
        "Concrete patches change the grip."]},
    "watkinsgleninternational": {"name": "Watkins Glen", "watch": [
        "Turn 1: downhill braking, lap-1 chaos.",
        "Bus Stop / Inner Loop: kerbs and track limits.",
        "Armco everywhere: no room for errors.",
        "Back straight: slipstream."]},
    "longbeachstreetcircuit": {"name": "Long Beach", "watch": [
        "Walls: 99% is fast, 101% is the wall.",
        "Turn 1: lap-1 braking chaos.",
        "Hairpin (T11): slow, crowded, easy to get punted.",
        "Traffic: few places to pass."]},
    "fujiinternationalspeedway": {"name": "Fuji", "watch": [
        "Long straight: slipstream, then T1 braking.",
        "Turn 1: big stop, late divers.",
        "Final sector: tight and slow, exits matter."]},
    "indianapolismotorspeedway": {"name": "Indianapolis", "watch": [
        "Turn 1: lap-1 braking chaos.",
        "Infield: tight, exits matter.",
        "Track limits on the infield kerbs."]},
    "autodromonazionalemonza": {"name": "Monza", "watch": [
        "Turn 1 chicane on lap 1: chaos.",
        "Lesmos: exit speed.",
        "Slipstream everywhere."]},
}
CAR_NOTES = {
    "bmwlmdh": ["No ABS: front lock = pink lights.", "Brake migration and bias from the wheel."],
    "bmwm4gt3": ["ABS and TC: use the dials, don't fight them."],
}


def week_now(today=None):
    today = today or _dt.date.today()
    return max(1, (today - SEASON_START).days // 7 + 1)


def track_info(display, raw=""):
    for k in (norm(display), norm(raw)):
        for key, v in TRACKS.items():
            if key and (k == key or (len(k) > 4 and (k in key or key in k))):
                return TRACKS[v["alias"]] if "alias" in v else v
    return None


def series_list():
    return [{"id": s["id"], "label": s["name"] + (f"  ·  {s['tag']}" if s["tag"] else "")} for s in SERIES]


def series_by_id(sid):
    return next((s for s in SERIES if s["id"] == sid), SERIES[0])


# ---------------------------------------------------------------- your numbers at this track
def _cache_path(car_path, track):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"prep_{car_path}_{track}.json".replace(" ", "_"))


def your_numbers(idx, car_path, track, landmarks=None, progress=None):
    """Heavy pass over every session in this car at this track (cached until a new session appears).
    -> dict with laps, fuel, trouble spots, focus."""
    rows = sorted([(k, v) for k, v in (idx or {}).items() if not v.get("error") and v.get("car_path") == car_path and v.get("track") == track],
                  key=lambda kv: kv[1].get("date", ""))
    sig = sorted([k for k, _ in rows])
    cp = _cache_path(car_path, track).replace("prep_", "prep4_")
    try:
        c = json.load(open(cp, encoding="utf-8"))
        if c.get("sig") == sig:
            return c
    except (OSError, ValueError):
        pass
    laps, fuel, offs, incs, tank, est = [], [], {}, {}, None, None
    last = {}
    tank_max = None
    corners = None
    for i, (k, v) in enumerate(rows):
        try:
            s = Session(v["path"], landmarks=landmarks)
            if corners is None:
                corners = s.find_corners()
            di = s.info.get("DriverInfo", {}) or {}
            if di.get("DriverCarFuelMaxLtr"):
                tank = float(di["DriverCarFuelMaxLtr"]) * float(di.get("DriverCarMaxFuelPct") or 1.0)
                tank_max = float(di["DriverCarFuelMaxLtr"])
            d = s.d
            sc = []
            for L in s.laps:
                if L["complete"] and not L["pit"]:
                    laps.append((L["time"], L["valid"]))
                    if L["valid"]:
                        sc.append(L["time"])
                    if L["valid"] and "FuelLevel" in d:
                        used = float(d["FuelLevel"][L["a"]] - d["FuelLevel"][L["b"] - 1])
                        if 0.2 < used < 40:
                            fuel.append(used)
            if len(sc) >= 2:            # your latest running: pace and conditions
                last = {"last_pace": float(np.median(sc)), "last_date": v.get("date", "")[:10],
                        "last_temp": float(np.median(d["TrackTempCrew"])) if "TrackTempCrew" in d else None,
                        "last_wet": float(np.median(d["TrackWetness"])) if "TrackWetness" in d else None}
            # where you leave the track / pick up incidents
            if "PlayerTrackSurface" in d:
                off = (d["PlayerTrackSurface"] == 0) & (d["Speed"] > 10)
                starts = np.flatnonzero(off[1:] & ~off[:-1]) + 1
                for j in starts[:200]:
                    nm = _corner_at(corners, float(d["LapDist"][j]))
                    offs[nm] = offs.get(nm, 0) + 1
            if "PlayerCarMyIncidentCount" in d:
                inc = d["PlayerCarMyIncidentCount"]
                ch = np.flatnonzero(np.diff(inc) > 0) + 1
                for j in ch[:200]:
                    nm = _corner_at(corners, float(d["LapDist"][j]))
                    incs[nm] = incs.get(nm, 0) + int(inc[j] - inc[j - 1])
            del s
        except Exception:
            pass
        if progress:
            progress(i + 1, len(rows))
    clean = sorted(t for t, ok in laps if ok)
    out = {"sig": sig, "sessions": len(rows), "laps": len(laps), "clean": len(clean),
           "best": clean[0] if clean else None,
           "typical": float(np.median([t for t in clean if t < clean[0] * 1.03])) if clean else None,
           "spread": float(np.std([t for t in clean if t < clean[0] * 1.03])) if len(clean) > 2 else None,
           "fuel_lap": float(np.median(fuel)) if fuel else None, "tank": tank, "tank_max": tank_max,
           "offs": sorted(offs.items(), key=lambda kv: -kv[1])[:4],
           "incidents": sorted(incs.items(), key=lambda kv: -kv[1])[:4], **last}
    try:
        json.dump(out, open(cp, "w", encoding="utf-8"))
    except OSError:
        pass
    return out


def _corner_at(corners, dist):
    if not corners:
        return f"{dist:.0f} m"
    for c in corners:
        if c["start"] - 60 <= dist <= c["end"] + 60:
            return c["name"]
    best = min(corners, key=lambda c: min(abs(dist - c["start"]), abs(dist - c["end"])))
    return f"before {best['name']}" if dist < best["start"] else f"after {best['name']}"


def race_plan(minutes, lap_s, fuel_lap, tank):
    """Timed race: laps run until the clock ends, then one more."""
    if not (minutes and lap_s):
        return None
    laps = int(math.floor(minutes * 60 / lap_s)) + 1
    out = {"laps": laps}
    if fuel_lap:
        need = laps * fuel_lap + 0.5 * fuel_lap
        out["fuel"] = round(need, 1)
        if tank:
            out["laps_per_tank"] = round(tank / fuel_lap, 1)
            out["stops"] = max(0, math.ceil(need / tank) - 1)
    return out
