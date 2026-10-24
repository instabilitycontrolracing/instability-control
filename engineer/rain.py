"""Rain: how to drive it, when to change tyres, and a race plan for "what if it rains".

iRacing's rain (Tempest) is physically simulated: water sits in the low parts of the asphalt first, the
rubbered racing line gets slippery sooner than the rest of the track, puddles can aquaplane the car.
Telemetry gives: TrackWetness (1 dry, 2 mostly dry, 3 very lightly wet, 4 lightly wet, 5 moderately wet,
6 very wet, 7 extremely wet), Precipitation (0..1), WeatherDeclaredWet (wets allowed), PlayerTireCompound,
and DriverInfo.DriverTires (which compound index is "Wet").
"""
import numpy as np

from . import strategy as S

WET_NAME = {1: "dry", 2: "mostly dry", 3: "very lightly wet", 4: "lightly wet", 5: "moderately wet", 6: "very wet", 7: "extremely wet"}

# lap time vs a dry lap, by track wetness, until we have your own wet laps (fractions)
SLICK_PEN = {1: 0.0, 2: 0.01, 3: 0.04, 4: 0.11, 5: 0.22, 6: 0.32, 7: 0.40}
WET_PEN = {1: 0.07, 2: 0.06, 3: 0.05, 4: 0.065, 5: 0.09, 6: 0.12, 7: 0.16}

TIPS = {
    "braking": ["Brake earlier and a bit softer: grip is about two thirds of the dry.",
                "Brake in a straight line, release slowly. Most rain crashes start with braking while turning.",
                "Brake off the rubbered line: the dry racing line is the slipperiest part when wet."],
    "line": ["Drive off the usual line: cross the old rubber, find the grip on the cleaner tarmac.",
             "Avoid painted kerbs, white lines and pit lane paint. They are ice when wet.",
             "Watch for standing water in dips and at the bottom of hills: straighten the car before you hit it."],
    "throttle": ["Short shift and use a gear higher in slow corners: less torque, less wheelspin.",
                 "Squeeze the throttle. Wait until the car is straight before full power.",
                 "Smooth hands: every quick input breaks traction in the wet."],
    "car": ["Traction control up one or two clicks.",
            "Brake bias half a percent to one percent rearward if the fronts lock.",
            "Wipers on before you need them, and give more room: spray hides the car ahead."],
    "racing": ["Don't follow in the spray: pick the other side to see and to find grip.",
               "Gaps grow in the rain: one clean lap gains more than one risky pass.",
               "Lap one in the wet: brake extra early, everyone around you is guessing too."],
}
TRACK_WET = {
    "circuitdes24heuresdumans": ["Mulsanne straight: water sits in the dips, keep it straight at 300.",
                                 "Indianapolis and Arnage: braking from very high speed, brake early and off-line.",
                                 "Porsche Curves: fast and narrow, lift earlier than you think."],
    "michelinracewayroadatlanta": ["Turn 1 downhill exit holds water.", "Esses: smooth, no kerbs."],
    "circuitdespafrancorchamps": ["Eau Rouge in the wet: lift. Raidillon's exit holds water.", "Bus Stop kerbs are lethal."],
    "sebringinternationalraceway": ["Concrete patches lose grip first in the wet.", "Turn 17 bumps plus water: stay off the kerb."],
}


def tips(n=3, seed=0, track_key=None):
    """A few short tips, mixed across topics (different each time with seed)."""
    pool = []
    for k in ("braking", "line", "throttle", "car", "racing"):
        pool += TIPS[k]
    rng = np.random.default_rng(seed)
    out = [str(x) for x in rng.choice(pool, size=min(n, len(pool)), replace=False)]
    if track_key:
        from .track_theme import norm
        t = norm(track_key)
        t = {"lemans": "circuitdes24heuresdumans", "roadatlanta": "michelinracewayroadatlanta", "spa": "circuitdespafrancorchamps",
             "sebring": "sebringinternationalraceway"}.get(next((a for a in ("lemans", "roadatlanta", "spa", "sebring") if t.startswith(a)), ""), t)
        for k, v in TRACK_WET.items():
            if k in t or t in k:
                out = [v[seed % len(v)]] + out[:-1]
    return out


def wet_pace(car, track):
    """Your own wet laps here: seconds slower than your dry pace, by wetness. -> {level: delta}"""
    with S._LOCK:
        c = S.db()
        rows = c.execute("SELECT time, wet FROM laps WHERE car=? AND track=? AND clean=1 AND time>0", (car, track)).fetchall()
        c.close()
    dry = [t for t, w in rows if (w or 0) <= 2]
    if not dry:
        return {}, 0
    base = float(np.percentile(dry, 25))
    out, n = {}, 0
    for lvl in range(3, 8):
        xs = [t for t, w in rows if w is not None and round(w) == lvl]
        if len(xs) >= 2:
            out[lvl] = float(np.median(xs)) - base
            n += len(xs)
    return out, n


def lap_on(base, level, wet_tyres, mine=None):
    level = int(max(1, min(7, round(level or 1))))
    if wet_tyres and mine and level in mine:
        return base + mine[level]
    return base * (1 + (WET_PEN if wet_tyres else SLICK_PEN)[level])


def crossover(base, level, laps_left, stop_cost, mine=None, on_wets=False):
    """Should you change tyres now? -> (change, seconds gained per lap, total gain)"""
    slick, wet = lap_on(base, level, False), lap_on(base, level, True, mine)
    gain_lap = (slick - wet) if not on_wets else (wet - slick)
    total = gain_lap * laps_left - stop_cost
    return total > 0, gain_lap, total


def rain_plan(m, plan_res, race_s, rain_chance, mine=None):
    """What to do if it rains, around the dry plan. -> list of short sentences."""
    if not m or not m.get("base"):
        return []
    base = m["base"]
    stops = plan_res.get("stops", []) if plan_res else []
    tyre_cost = max(m["tyre_time"], 4.0)
    extra_stop = m["lane_loss"] + tyre_cost
    out = []
    if stops:
        s0 = stops[0]
        out.append(f"Rain before lap {s0['lap']}: hold on, then take wets at your planned stop (lap {s0['lap']}) — no extra stop.")
    # with an extra stop, how many wet laps make wets worth it?
    for lvl in (4, 5):
        g = lap_on(base, lvl, False) - lap_on(base, lvl, True, mine)
        if g > 0:
            out.append(f"Track {WET_NAME[lvl]}: wets are about {g:.0f} s a lap faster. An extra stop costs ~{extra_stop:.0f} s, so box if more than {extra_stop / g:.0f} laps are left.")
    out.append("Very lightly wet only: stay on slicks, they're still faster. Brake early.")
    out.append("Drying: back to slicks once the track is mostly dry and a dry line shows. Wets overheat and wear on a drying track.")
    wet_laps = int(race_s / lap_on(base, 5, True, mine)) + 1
    dry_laps = int(race_s / base) + 1
    if wet_laps < dry_laps:
        out.append(f"A wet race is about {dry_laps - wet_laps} lap{'s' if dry_laps - wet_laps > 1 else ''} shorter: you'll need less fuel, and fuel saving won't be needed.")
    return out
