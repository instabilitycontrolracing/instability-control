"""Series prep: pick the live series you're practising for -> format, what to watch for, and your own numbers there.

Static facts are kept short on purpose. Schedule weeks are from iRacing's 2026 Season 4 PDF (season started
15 Sep 2026). Track notes are only things checked against track guides; your numbers come from your own telemetry.
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

# 2026-10-28: the whole 2026 S4 schedule, from iRacing's season PDF (SCHEDULE_PDF; checked line by line).
# Same 12 weeks for the open and the fixed IMSA iRacing Series. Week order checked against iRacing's own account
# schedule data (2026-10-28): week 11 Sebring (24 Nov), week 12 Monza (1 Dec). The live account data wins anyway.
IMSA_WEEKS = {1: "Indianapolis Motor Speedway", 2: "Michelin Raceway Road Atlanta", 3: "Fuji International Speedway",
              4: "Red Bull Ring", 5: "Long Beach Street Circuit", 6: "Circuit Gilles Villeneuve",
              7: "Circuit des 24 Heures du Mans", 8: "Autódromo Hermanos Rodríguez", 9: "Suzuka International Racing Course",
              10: "Silverstone Circuit", 11: "Sebring International Raceway", 12: "Autodromo Nazionale Monza"}
# IMSA Endurance runs one Saturday every two weeks; keyed by the SEASON week the race falls in (week_now()),
# the PDF calls them rounds 1-6. Race dates from the same PDF.
ENDURANCE_WEEKS = {1: "Michelin Raceway Road Atlanta", 3: "Fuji International Speedway", 5: "Long Beach Street Circuit",
                   7: "Circuit des 24 Heures du Mans", 9: "Suzuka International Racing Course", 11: "Sebring International Raceway"}
ENDURANCE_DATES = {1: "2026-09-19", 3: "2026-10-03", 5: "2026-10-17", 7: "2026-10-31", 9: "2026-11-14", 11: "2026-11-28"}

SERIES = [
    {"id": "imsa_open", "rid": 447, "pdf": "IMSA iRacing Series by GO Fast", "name": "IMSA iRacing Series", "tag": "Open setup", "license": "Sports Car A",
     "classes": ["GTP", "LMP2", "GT3"], "minutes": 45, "setup": "Open",
     "weeks": dict(IMSA_WEEKS),
     "notes": ["Open setups: bring your own (Setup tab)."]},
    {"id": "imsa_fixed", "rid": 539, "pdf": "IMSA iRacing Series - Fixed", "name": "IMSA iRacing Series", "tag": "Fixed setup", "license": "Sports Car A",
     "classes": ["GTP", "LMP2", "GT3"], "minutes": 35, "setup": "Fixed",
     "weeks": dict(IMSA_WEEKS),
     "notes": ["Fixed setup: only in-car adjustments."]},
    {"id": "imsa_endurance", "rid": 419, "pdf": "IMSA Endurance Series", "name": "IMSA Endurance Series", "tag": "160 min", "license": "",
     "classes": ["GTP", "LMP2", "GT3"], "minutes": 160, "setup": "Open",
     "weeks": dict(ENDURANCE_WEEKS), "dates": dict(ENDURANCE_DATES),
     "notes": ["Every 2 weeks, 4 race times.", "Long race: fuel and tyre plan matter."]},
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
        "Long lap: one mistake costs 10 s+."],
        # corners the debrief / incident drills name here (text only, never spoken)
        "drill": {"brake": "the Ford Chicanes, Dunlop and Mulsanne Corner", "side": "Dunlop and the Esses",
                  "lap1": "Dunlop, the Esses and the Ford Chicanes", "settle": "after the Mulsanne"}},
    "lemansfull": {"alias": "circuitdes24heuresdumans"},          # iRacing TrackName ids (WeekendInfo.TrackName)
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
        "Hairpin: slowest corner, easy place to get hit.",
        "Concrete patches change the grip.",
        "Old airfield: concrete joins are rough, the floor can spark.",
        "Tower Bend: tighter than it looks.",
        "Ulmann straight: watch for cars leaving the pits."],
        "drill": {"brake": "Turn 1, the Hairpin and Turn 17", "side": "Turn 1 and Turn 3",
                  "lap1": "Turn 1, Turn 3 and the Hairpin"}},
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
        "Rettifilo (Turn 1): the heaviest stop of the lap.",
        "Roggia: big stop, a main passing spot.",
        "Lesmos: exit speed.",
        "Ascari: exit speed onto the back straight.",
        "Parabolica: last chance to pass, exit = main straight speed.",
        "Slipstream everywhere."],
        "drill": {"brake": "the Rettifilo, the Roggia and the Parabolica", "side": "the Rettifilo and the Roggia",
                  "lap1": "the Rettifilo and the Roggia"}},
    "monzafull": {"alias": "autodromonazionalemonza"},
    "autodromohermanosrodriguez": {"name": "Mexico City", "watch": [
        "Turn 1: end of the 1.2 km straight, lap-1 pile-ups. Brake early.",
        "Turns 1-3 (Moisés Solana): the main passing spot.",
        "Turns 4-6: passes happen here too.",
        "Stadium (Foro Sol): slow and tight.",
        "Peraltada exit sets your main straight speed.",
        "2,238 m up: thin air, less downforce and drag."],
        "drill": {"brake": "Turn 1 and Turn 4", "side": "Turns 1 to 3",
                  "lap1": "Turns 1 to 3 and Turn 4"}},
    "mexicocitygp": {"alias": "autodromohermanosrodriguez"},
    "suzukainternationalracingcourse": {"name": "Suzuka", "watch": [
        "Turn 1: lap-1 pile-ups. Brake early on lap 1.",
        "S Curves: rhythm, no passing.",
        "Hairpin: the main passing spot.",
        "Spoon exit sets your back straight speed.",
        "Casio Triangle: last-lap lunges, a passing spot.",
        "Figure eight: the back straight crosses the track on a bridge."],
        "drill": {"brake": "Turn 1, the Hairpin and the Casio Triangle", "side": "Turns 1 and 2",
                  "lap1": "Turn 1, Turn 2 and the S Curves"}},
    "suzukagrandprix": {"alias": "suzukainternationalracingcourse"},
    "silverstonecircuit": {"name": "Silverstone", "watch": [
        "Abbey on lap 1: fast and busy, leave room.",
        "Exit of Luffield: run down the pit straight, a passing spot.",
        "Copse: fast, only brave passes here.",
        "Maggotts, Becketts, Chapel: rhythm, carry speed out of Chapel.",
        "Stowe: big stop after the Hangar straight, passes common.",
        "Vale: often side by side out of Stowe."],
        "drill": {"brake": "Stowe and Vale", "side": "Stowe and Vale",
                  "lap1": "Abbey, Farm and Village"}},
    "silverstone2019gp": {"alias": "silverstonecircuit"},
    # the other configs of the six tracks above (iRacing TrackName ids)
    "lemansnochicane": {"alias": "circuitdes24heuresdumans"}, "monzagpsecondchicane": {"alias": "autodromonazionalemonza"},
    "suzukaeast": {"alias": "suzukainternationalracingcourse"}, "silverstone2019international": {"alias": "silverstonecircuit"},
    "sebringclub": {"alias": "sebringinternationalraceway"},
}


def _merge_packs():
    """2026-10-28: 57 more tracks from the verified research packs (engineer/track_packs.py): watch notes, drill
    corners, iRacing TrackName aliases. A pack replaces an older hand-written entry's notes for the same track
    (Spa, Road Atlanta, Daytona, Watkins Glen, Long Beach, Fuji, Indianapolis); the six done above are not in it."""
    from .track_packs import PACK_TRACKS, PACK_ALIASES
    for k, v in PACK_TRACKS.items():
        TRACKS.setdefault(k, {"watch": []}).update(v)
    for a, k in PACK_ALIASES.items():
        TRACKS.setdefault(a, {"alias": k})


_merge_packs()
# debrief drills where we have no corner names for the track (was: always Le Mans' corners)
DRILL_GENERIC = {"brake": "the big braking zones", "side": "a few corners", "lap1": "Turn 1 and the first few corners",
                 "settle": "after the first few corners"}


def drill_spots(*names):
    """Corner names for the debrief / incident drills at this track (Le Mans' are the ones the drills were
    written with). Unknown tracks get neutral wording."""
    ti = None
    for n in names:
        if n:
            ti = track_info(n)
            if ti:
                break
    return dict(DRILL_GENERIC, **((ti or {}).get("drill") or {}))
CAR_NOTES = {
    "bmwlmdh": ["No ABS: front lock = pink lights.", "Brake migration and bias from the wheel."],
    "bmwm4gt3": ["ABS and TC: use the dials, don't fight them."],
}
# 2026-10-29 (car parity E2): every other car with a verified CarPath gets its short, sourced notes from the car table
from . import cars as _cars
for _p, _c in _cars.BY_PATH.items():
    if _c["notes"]:
        CAR_NOTES.setdefault(_p, list(_c["notes"]))


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
