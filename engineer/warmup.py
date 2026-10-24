"""How long your tyres take to come in, from your own telemetry.

iRacing's saved telemetry (.ibt) records hot tyre pressures and surface temperatures all the time.
Pressure tells us the tyres were cold at the pit exit. For every stint that
starts from the pit lane on cold tyres (pressures still low) we measure how far you drive until your
sector times are back to your settled pace, and how much time that first lap from cold costs.
Results are cached per session file.
"""
import json, os, statistics
import numpy as np

from .telemetry import CACHE_DIR, read_ibt, list_sessions

P = ["LFpressure", "RFpressure", "LRpressure", "RRpressure"]
T = ["LFtempM", "RFtempM", "LRtempM", "RRtempM"]
CH = P + T + ["Speed", "OnPitRoad", "LapDist", "SessionTime", "Lap", "LapLastLapTime", "TrackTempCrew", "IsOnTrack"]
VER = 3


def _cache(path):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, "warm_" + os.path.basename(path).replace(" ", "_") + ".json")


def stints(path, nsec=20):
    """-> list of {warm_m, lap_m, first_lap_loss, track_temp} for stints that start from the pit lane on cold tyres.
    warm_m = distance after the pit exit until your sector times are back within 1.5% of the settled ones
    (three sectors in a row); first_lap_loss = time lost over the first lap of running vs settled."""
    cp = _cache(path)
    try:
        c = json.load(open(cp, encoding="utf-8"))
        if c.get("v") == VER and c.get("mtime") == os.path.getmtime(path):
            return c["stints"]
    except (OSError, ValueError):
        pass
    out = []
    try:
        d, _, tick = read_ibt(path, CH)
        if not all(k in d for k in P + ["Speed", "OnPitRoad", "LapDist", "SessionTime"]):
            raise ValueError("no tyre data")
        tick = int(tick or 60)
        spd, onp, t, ld = d["Speed"], d["OnPitRoad"].astype(bool), d["SessionTime"], d["LapDist"]
        lap_m = float(np.nanmax(ld)) or 1.0
        dist = np.cumsum(spd * np.diff(t, prepend=t[0]).clip(0, 1))
        p = np.mean([d[k] for k in P], axis=0)
        sec = np.minimum((ld / lap_m * nsec).astype(int), nsec - 1)
        exits = np.flatnonzero(onp[:-1] & ~onp[1:] & (spd[1:] > 5)) + 1
        ends = list(np.flatnonzero(~onp[:-1] & onp[1:]) + 1) + [len(t) - 1]
        for a in exits:
            b = next((e for e in ends if e > a), len(t) - 1)
            if dist[b] - dist[a] < 3 * lap_m:                        # need settled laps to compare with
                continue
            later = (dist >= dist[a] + 1.5 * lap_m) & (np.arange(len(t)) <= b)
            if p[min(a + tick, b)] > np.median(p[later]) - 6:         # pressures already up: tyres weren't cold
                continue
            seq, cur, t_in = [], sec[a], t[a]                         # (distance from exit, sector, sector time)
            for j in range(a + 1, b):
                if sec[j] != cur:
                    if not onp[j] and (sec[j] - cur) % nsec == 1:
                        seq.append((dist[j] - dist[a], int(cur), float(t[j] - t_in)))
                    cur, t_in = sec[j], t[j]
            ref = {}
            for dd, sct, tt in seq:
                if dd > 2 * lap_m:
                    ref.setdefault(sct, []).append(tt)
            ref = {k: statistics.median(v) for k, v in ref.items() if len(v) >= 2}
            rat = [(dd, tt / ref[sct]) for dd, sct, tt in seq if sct in ref and dd < 2 * lap_m]
            warm = next((rat[n][0] for n in range(len(rat) - 2) if all(r <= 1.015 for _, r in rat[n:n + 3])), None)
            if warm is None:
                continue
            loss = sum(tt - ref[sct] for dd, sct, tt in seq if sct in ref and dd < lap_m)
            out.append({"warm_m": float(warm), "lap_m": lap_m, "first_lap_loss": round(float(loss), 2),
                        "track_temp": float(np.median(d["TrackTempCrew"][a:b])) if "TrackTempCrew" in d else None})
    except Exception:
        out = []
    try:
        json.dump({"v": VER, "mtime": os.path.getmtime(path), "stints": out}, open(cp, "w", encoding="utf-8"))
    except OSError:
        pass
    return out


def estimate(car, track, max_files=40):
    """Your typical warm-up at this car + track. -> {laps, metres, first_lap_loss, n} or None"""
    files = [x["path"] for x in list_sessions() if x.get("car") == car and x.get("track") == track]
    files = files[:max_files]                                       # newest first
    ss = [s for f in files for s in stints(f)]
    if len(ss) < 2:
        return None
    lap_m = ss[0]["lap_m"]
    warm = statistics.median(s["warm_m"] for s in ss)
    loss = statistics.median(s["first_lap_loss"] for s in ss)
    return {"laps": warm / lap_m, "metres": warm, "first_lap_loss": loss if loss > 0.3 else None, "n": len(ss)}


def phrase_laps(x):
    for lim, txt in ((0.2, "a few corners"), (0.4, "a third of a lap"), (0.65, "half a lap"), (0.9, "most of a lap"),
                     (1.3, "one lap"), (1.8, "a lap and a half"), (2.5, "two laps")):
        if x < lim:
            return txt
    return "three laps"


WARM_VALUES = ["a few corners", "a third of a lap", "half a lap", "most of a lap", "one lap", "a lap and a half", "two laps", "three laps"]


def phrase_secs(s):
    if s < 0.75:
        return "half a second"
    n = int(round(s))
    return "1 second" if n == 1 else f"{min(n, 8)} seconds"


SECS_VALUES = ["half a second", "1 second"] + [f"{n} seconds" for n in range(2, 9)]
