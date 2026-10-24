"""Race strategy that remembers.

Everything you drive is kept in a small database (%LOCALAPPDATA%\\RaceEngineer\\strategy.db), per car and
track: every lap (time, fuel used, fuel on board, tyre age, track/air temperature, wetness), every stint and
every pit stop. It is filled from your saved iRacing telemetry and, live, lap by lap while you drive - so a
2-minute practice or a session that ends early still counts, and nothing is forgotten next time.

From that it builds a model of your car at that track:
    lap time = base + fuel effect x fuel on board + tyre wear x tyre age + temperature effect
    pit stop = pit lane loss + max(fuel time, tyre time)
and simulates the race (timed race: laps until the clock runs out, then one more) for every sensible
strategy: number of stops, where they go, tyres or not, and a little fuel saving. The best three are
Plan A, B and C. During the race the same simulation runs every lap from where you really are (fuel,
tyre age, your current pace, time left) and from where the cars ahead are (when they last pitted, their
pace, the gap), so the plan changes if you lose time and it looks for the plan that beats them.
No safety cars are assumed - in IMSA on iRacing they basically don't happen.
"""
import json, math, os, sqlite3, threading, time
import numpy as np

from .telemetry import CACHE_DIR

DB_PATH = os.path.join(os.path.dirname(CACHE_DIR), "strategy.db")
_LOCK = threading.Lock()

DEFAULTS = {"fuel_effect": 0.025, "tyre_deg": 0.03, "temp_effect": 0.02, "lane_loss": 28.0, "fuel_rate": 2.4,
            "tyre_time": 22.0, "save_cost": 0.07}     # s/L, s/lap, s/°C, s, L/s, s, s per % fuel saved per lap


# ---------------------------------------------------------------- database
def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, path TEXT, mtime REAL, car TEXT, track TEXT, kind TEXT,
        started REAL, ended REAL, source TEXT);
    CREATE TABLE IF NOT EXISTS laps (session TEXT, car TEXT, track TEXT, lap INTEGER, time REAL, fuel_start REAL, fuel_used REAL,
        clean INTEGER, valid INTEGER, tyre_age INTEGER, stint INTEGER, track_temp REAL, air_temp REAL, wet REAL, kind TEXT,
        at REAL, source TEXT);
    CREATE TABLE IF NOT EXISTS stops (session TEXT, car TEXT, track TEXT, lap INTEGER, lane_loss REAL, stationary REAL,
        fuel_added REAL, tyres INTEGER, at REAL, source TEXT);
    CREATE TABLE IF NOT EXISTS events (session TEXT PRIMARY KEY, car TEXT, track TEXT, series_id INTEGER, season_id INTEGER,
        race_week INTEGER, kind TEXT, official INTEGER, race_s REAL, race_laps INTEGER, fixed INTEGER, tod TEXT, weather TEXT,
        skies TEXT, air REAL, track_temp REAL, precip REAL, rubber TEXT, incident_limit TEXT, fast_repairs TEXT,
        standing_start INTEGER, starters INTEGER, at REAL);
    CREATE INDEX IF NOT EXISTS laps_ct ON laps(car, track);
    CREATE INDEX IF NOT EXISTS stops_ct ON stops(car, track);
    """)
    return c


# ---------------------------------------------------------------- from saved telemetry (.ibt)
def ingest_session(sess, sid, path, mtime):
    """Laps, stints and stops of one telemetry file."""
    d = sess.d
    n = len(d["Lap"])
    tick = sess.tick
    onp = d.get("OnPitRoad", np.zeros(n, bool))
    spd = d["Speed"]
    t = d["SessionTime"]
    fuel = d.get("FuelLevel")
    tt, air, wet = d.get("TrackTempCrew"), d.get("AirTemp"), d.get("TrackWetness")
    psv = d.get("PitSvFlags")
    import re as _re
    m = _re.search(r"(\d{4}-\d\d-\d\d \d\d-\d\d-\d\d)", os.path.basename(path))
    try:
        from datetime import datetime
        t0 = datetime.strptime(m.group(1), "%Y-%m-%d %H-%M-%S").timestamp() if m else mtime
    except ValueError:
        t0 = mtime
    kind = ""
    try:
        n_s = int(d["SessionNum"][len(d["SessionNum"]) // 2]) if "SessionNum" in d else 0
        for x in sess.info.get("SessionInfo", {}).get("Sessions", []) or []:
            if x.get("SessionNum") == n_s:
                kind = (x.get("SessionType") or "").lower()
    except Exception:
        pass
    # pit stops: each stretch on pit road
    stops, edges = [], np.flatnonzero(np.diff(onp.astype(np.int8)) != 0) + 1
    bounds = list(edges)
    if onp[0]:
        bounds = [0] + bounds
    if onp[-1]:
        bounds = bounds + [n]
    for a, b in zip(bounds[0::2], bounds[1::2]):
        if b - a < tick * 3:
            continue
        stopped = (spd[a:b] < 0.5)
        stationary = float(stopped.sum() / tick)
        if stationary < 1.5 or a == 0:              # drive-through or the garage exit
            continue
        added = float(fuel[min(n - 1, b)] - fuel[a]) if fuel is not None else 0.0
        tyres = bool(psv is not None and int(psv[a + int(np.argmax(stopped))]) & 0x0F)
        lap = int(d["Lap"][a])
        stops.append({"lap": lap, "stationary": stationary, "fuel_added": max(0.0, added), "tyres": tyres, "i": a})
    # laps
    stop_laps = {s["lap"] for s in stops}
    rows, stint, tyre_age = [], 0, 0
    clean_times = []
    for L in sess.laps:
        a, b = L["a"], L["b"]
        if L["n"] in stop_laps:                        # in-lap of a stop
            s = next(s for s in stops if s["lap"] == L["n"])
            if s["tyres"]:
                tyre_age = 0
            stint += 1
        tyre_age += 1
        if not L["complete"]:
            continue
        fs = float(fuel[a]) if fuel is not None else None
        fu = float(fuel[a] - fuel[b - 1]) if fuel is not None else None
        pit = bool(onp[a:b].any())
        clean = int(L["valid"] and not pit)
        if clean:
            clean_times.append(L["time"])
        mid = (a + b) // 2
        rows.append((sid, sess.car_path, sess.track_name, L["n"], L["time"], fs, fu if fu and fu > 0 else None, clean, int(L["valid"]),
                     tyre_age, stint, float(tt[mid]) if tt is not None else None, float(air[mid]) if air is not None else None,
                     float(wet[mid]) if wet is not None else None, kind, t0 + float(t[a] - t[0]), "ibt"))
    med = float(np.median(clean_times)) if clean_times else None
    srows = []
    for s in stops:
        lane = None
        if med:
            inl = next((L for L in sess.laps if L["n"] == s["lap"]), None)
            outl = next((L for L in sess.laps if L["n"] == s["lap"] + 1), None)
            if inl and outl and inl["time"] and outl["time"]:
                lane = inl["time"] + outl["time"] - 2 * med - s["stationary"]
                if not (5 < lane < 90):
                    lane = None
        srows.append((sid, sess.car_path, sess.track_name, s["lap"], lane, s["stationary"], s["fuel_added"], int(s["tyres"]),
                      t0 + float(t[s["i"]] - t[0]), "ibt"))
    with _LOCK:
        c = db()
        c.execute("DELETE FROM laps WHERE session=?", (sid,)); c.execute("DELETE FROM stops WHERE session=?", (sid,))
        c.executemany("INSERT INTO laps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        c.executemany("INSERT INTO stops VALUES (?,?,?,?,?,?,?,?,?,?)", srows)
        ended = t0 + float(t[-1] - t[0])
        c.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?)", (sid, path, mtime, sess.car_path, sess.track_name, kind, t0, ended, "ibt"))
        try:
            c.execute("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      event_from_info(sess.info, sess.car_path, sess.track_name, sid, t0))
        except Exception:
            pass
        # live laps already covered by this file are dropped (no double counting)
        c.execute("DELETE FROM laps WHERE source='live' AND car=? AND track=? AND at BETWEEN ? AND ?", (sess.car_path, sess.track_name, t0 - 60, ended + 60))
        c.execute("DELETE FROM stops WHERE source='live' AND car=? AND track=? AND at BETWEEN ? AND ?", (sess.car_path, sess.track_name, t0 - 60, ended + 60))
        c.commit(); c.close()
    return len(rows), len(srows)


def backfill(sessions, progress=None, log=print):
    """Read any telemetry files not in the database yet."""
    from .telemetry import Session
    with _LOCK:
        c = db()
        have = {r[0]: r[1] for r in c.execute("SELECT id, mtime FROM sessions")}
        c.close()
    todo = [s for s in sessions if have.get(s["id"]) != s["mtime"]]
    for i, s in enumerate(todo):
        try:
            se = Session(s["path"])
            ingest_session(se, s["id"], s["path"], s["mtime"])
            del se
        except Exception as e:
            log(f"[strategy] {os.path.basename(s['path'])}: {e!r}")
            with _LOCK:
                c = db(); c.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?)", (s["id"], s["path"], s["mtime"], "", "", "", 0, 0, "error")); c.commit(); c.close()
        if progress:
            progress(i + 1, len(todo))
    backfill_events(sessions)
    return len(todo)


def backfill_events(sessions):
    """Race format/conditions for files stored before events were kept (reads only the file's header)."""
    from .telemetry import read_ibt, parse_yaml
    with _LOCK:
        c = db()
        have = {r[0] for r in c.execute("SELECT session FROM events")}
        known = {r[0]: (r[1], r[2], r[3]) for r in c.execute("SELECT id, car, track, started FROM sessions WHERE source='ibt'")}
        c.close()
    for s in sessions:
        if s["id"] in have or s["id"] not in known:
            continue
        try:
            _, si, _ = read_ibt(s["path"], channels=["Lap"])
            info = parse_yaml(si)
            car, track, t0 = known[s["id"]]
            record_event(event_from_info(info, car, track, s["id"], t0))
        except Exception:
            pass


# ---------------------------------------------------------------- race format + conditions of each event
def _num(x):
    try:
        return float(str(x).split()[0])
    except (ValueError, IndexError, TypeError):
        return None


def event_from_info(info, car, track, sid, at):
    """What iRacing says about the event: race length, fixed/open, weather, time of day, limits."""
    wk = info.get("WeekendInfo", {}) or {}
    op = wk.get("WeekendOptions", {}) or {}
    race = next((s for s in (info.get("SessionInfo", {}) or {}).get("Sessions", []) or [] if "race" in str(s.get("SessionType", "")).lower()), None)
    laps = race.get("SessionLaps") if race else None
    return (sid, car, track, wk.get("SeriesID"), wk.get("SeasonID"), wk.get("RaceWeek"), str(wk.get("EventType", "")).lower(),
            int(wk.get("Official") or 0), _num(race.get("SessionTime")) if race else None, laps if isinstance(laps, int) else None,
            int(op.get("IsFixedSetup") or 0), str(op.get("TimeOfDay") or ""), str(op.get("WeatherType") or ""), str(op.get("Skies") or wk.get("TrackSkies") or ""),
            _num(wk.get("TrackAirTemp")), _num(wk.get("TrackSurfaceTemp")), _num(wk.get("TrackPrecipitation")),
            str(race.get("SessionTrackRubberState") or "") if race else "", str(op.get("IncidentLimit") or ""), str(op.get("FastRepairsLimit") or ""),
            int(op.get("StandingStart") or 0), int(op.get("NumStarters") or 0), at)


def record_event(row):
    with _LOCK:
        c = db()
        c.execute("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        c.commit(); c.close()


def last_race(car, track):
    """Your most recent official race here (its format and conditions), or None."""
    with _LOCK:
        c = db()
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM events WHERE car=? AND track=? AND race_s IS NOT NULL AND kind='race' ORDER BY at DESC LIMIT 1", (car, track)).fetchone()
        c.close()
    return dict(r) if r else None


# ---------------------------------------------------------------- live (lap by lap while you drive)
def record_lap(car, track, lap, t, fuel_start, fuel_used, clean, tyre_age, stint, track_temp, air_temp, wet, kind):
    with _LOCK:
        c = db()
        c.execute("INSERT INTO laps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("live", car, track, lap, t, fuel_start, fuel_used, int(clean), int(clean), tyre_age, stint, track_temp, air_temp, wet, kind, time.time(), "live"))
        c.commit(); c.close()


def record_stop(car, track, lap, lane_loss, stationary, fuel_added, tyres):
    with _LOCK:
        c = db()
        c.execute("INSERT INTO stops VALUES (?,?,?,?,?,?,?,?,?,?)", ("live", car, track, lap, lane_loss, stationary, fuel_added, int(tyres), time.time(), "live"))
        c.commit(); c.close()


# ---------------------------------------------------------------- the model
def model(car, track):
    """Fit the car at this track from everything stored. -> dict (with 'n' laps used and what was learned)."""
    with _LOCK:
        c = db()
        L = c.execute("SELECT time, fuel_start, fuel_used, clean, tyre_age, track_temp, wet, kind, stint, session, at FROM laps "
                      "WHERE car=? AND track=? AND time>0", (car, track)).fetchall()
        S = c.execute("SELECT lane_loss, stationary, fuel_added, tyres FROM stops WHERE car=? AND track=?", (car, track)).fetchall()
        c.close()
    m = dict(DEFAULTS)
    m.update({"n": 0, "learned": [], "car": car, "track": track})
    clean = [r for r in L if r[3] and (r[6] or 0) < 2]
    if not clean:
        return m
    best = min(r[0] for r in clean)
    use = [r for r in clean if r[0] < best * 1.05 and r[1] is not None]
    fu = [r[2] for r in clean if r[2] and r[0] < best * 1.05]
    m["fuel_lap"] = float(np.median(fu)) if fu else None
    m["best"] = best
    m["n"] = len(use)
    tts = [r[5] for r in use if r[5] is not None]
    m["temp_ref"] = float(np.median(tts)) if tts else None
    if len(use) >= 8:
        X = np.array([[1.0, r[1], min(r[4] or 1, 40), (r[5] - m["temp_ref"]) if (r[5] is not None and m["temp_ref"] is not None) else 0.0] for r in use])
        y = np.array([r[0] for r in use])
        try:
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            # one robust pass: drop the worst 10 %, fit again
            res = np.abs(X @ coef - y)
            keep = res <= np.quantile(res, 0.9)
            coef, *_ = np.linalg.lstsq(X[keep], y[keep], rcond=None)
            base, fe, td, te = coef
            if 0 <= fe <= 0.08 and np.ptp(X[:, 1]) > 8:
                m["fuel_effect"] = float(fe); m["learned"].append("fuel effect")
            if -0.1 <= te <= 0.1 and np.ptp(X[:, 3]) > 4:
                m["temp_effect"] = float(te); m["learned"].append("temperature")
        except np.linalg.LinAlgError:
            pass
    # tyre wear: inside each long run, how much slower per lap (after taking the fuel burn out); median of runs
    runs = {}
    for r in use:
        runs.setdefault((r[9], r[8]), []).append(r)
    slopes = []
    for v in runs.values():
        if len(v) >= 5:
            ages = np.array([min(r[4] or 1, 40) for r in v], float)
            if np.ptp(ages) < 4:
                continue
            adj = np.array([r[0] - m["fuel_effect"] * r[1] for r in v])
            k = np.polyfit(ages, adj, 1)[0]
            slopes.append(k)
    if slopes:
        m["tyre_deg"] = float(np.clip(np.median(slopes), 0.0, 0.15)); m["learned"].append("tyre wear")
    # base = typical fresh-tyre, light-fuel lap at the reference temperature
    resid = [r[0] - m["fuel_effect"] * r[1] - m["tyre_deg"] * min(r[4] or 1, 40) for r in use] or [best]
    m["base"] = float(np.percentile(resid, 25))
    lanes = [s[0] for s in S if s[0]]
    if lanes:
        m["lane_loss"] = float(np.median(lanes)); m["learned"].append("pit lane loss")
    rates = [s[2] / s[1] for s in S if s[2] and s[2] > 5 and s[1] and not s[3]]
    if rates:
        m["fuel_rate"] = float(np.median(rates)); m["learned"].append("refuel speed")
    tyre_stops = [s[1] for s in S if s[3] and s[1] and s[1] >= 12]
    if len(tyre_stops) >= 2:
        m["tyre_time"] = float(np.median(tyre_stops)); m["learned"].append("tyre change time")
    # long runs = your race simulations
    runs = {}
    for r in clean:
        runs.setdefault((r[9], r[8]), []).append(r)
    sims = [v for v in runs.values() if len(v) >= 6]
    m["race_sims"] = len(sims)
    if sims:
        lt = [r[0] for v in sims for r in v]
        m["sim_pace"] = float(np.median(lt))
        m["sim_temp"] = float(np.median([r[5] for v in sims for r in v if r[5] is not None])) if any(r[5] is not None for v in sims for r in v) else None
        m["sim_wet"] = float(np.median([r[6] or 0 for v in sims for r in v]))
    return m


def lap_time(m, fuel, tyre_age, temp=None, save=0.0):
    t = m["base"] + m["fuel_effect"] * fuel + m["tyre_deg"] * tyre_age
    if temp is not None and m.get("temp_ref") is not None:
        t += m["temp_effect"] * (temp - m["temp_ref"])
    return t + m["save_cost"] * save


def stop_time(m, fuel_add, tyres):
    fuel_t = max(0.0, fuel_add) / max(0.3, m["fuel_rate"])
    return m["lane_loss"] + max(fuel_t, m["tyre_time"] if tyres else 0.0, 4.0)


# ---------------------------------------------------------------- simulation
def simulate(m, plan, race_s, tank, fuel_now, tyre_age=0, elapsed=0.0, temp=None, laps_done=0):
    """plan = {"stops": [lap, ...], "tyres": [bool per stop], "save": % fuel saved per lap}
    -> {"laps", "time", "stops": [{lap, fuel, tyres, time}], "ok"}"""
    fl = m.get("fuel_lap") or 0
    save = plan.get("save", 0.0)
    flap = fl * (1 - save / 100)
    fuel, age, tt = fuel_now, tyre_age, elapsed
    lap = laps_done
    stops = list(plan["stops"]); tyres = list(plan.get("tyres") or [False] * len(stops))
    out = []
    # fuel needed after each stop: enough for the next stint (or to the end)
    while True:
        lap += 1
        lt = lap_time(m, fuel, age, temp, save)
        tt += lt
        fuel -= flap
        age += 1
        if fuel < -0.2:
            return {"ok": False, "laps": lap, "time": tt, "stops": out}
        if tt >= race_s:                      # the flag: this lap was the last one
            return {"ok": True, "laps": lap, "time": tt, "stops": out, "fuel_left": fuel}
        if stops and lap == stops[0]:
            stops.pop(0); ty = tyres.pop(0) if tyres else False
            # fuel to reach the next stop, or the end (+ half a lap margin), within the tank
            nxt = stops[0] if stops else None
            if nxt is not None:
                need = (nxt - lap + 0.5) * flap
            else:
                left_s = race_s - tt
                laps_left = math.floor(left_s / max(1, lap_time(m, fuel, 0 if ty else age, temp, save))) + 1
                need = (laps_left + 0.5) * flap
            add = max(0.0, min(tank - fuel, need - fuel))
            st = stop_time(m, add, ty)
            tt += st
            fuel += add
            if ty:
                age = 0
            out.append({"lap": lap, "fuel": round(add, 1), "tyres": ty, "time": round(st, 1)})


def best_plans(m, race_s, tank, fuel_now, tyre_age=0, elapsed=0.0, temp=None, laps_done=0, max_stops=None):
    """Try the sensible strategies, return the best 3 (most laps, then least time), each a different idea."""
    fl = m.get("fuel_lap")
    if not fl or not tank:
        return []
    per_tank = tank / fl
    est_lap = lap_time(m, tank / 2, 5, temp)
    total_laps = math.floor((race_s - elapsed) / est_lap) + 1 + laps_done
    # fewest stops possible with the most fuel saving we'd consider (6 %); the simulation checks each one
    min_stops = max(0, math.ceil(((total_laps - laps_done) * fl * 0.94 - fuel_now) / tank - 1e-6))
    hi = min(min_stops + 2, max_stops if max_stops is not None else 9)
    cands = []
    for ns in range(min_stops, hi + 1):
        for save in (0.0, 2.0, 4.0, 6.0, 8.0):
            for tyre_rule in ("none", "all", "alternate"):
                if ns == 0 and tyre_rule != "none":
                    continue
                window = (fuel_now / (fl * (1 - save / 100)))
                for shape in ("even", "late", "early"):
                    # stop laps: spread the remaining laps, first stop no later than the fuel allows
                    rem = total_laps - laps_done
                    if ns == 0:
                        stops = []
                    else:
                        seg = rem / (ns + 1)
                        stops = [laps_done + round(seg * (i + 1)) for i in range(ns)]
                        if shape == "late":
                            stops[0] = laps_done + max(1, min(int(window - 0.3), stops[0] + 2))
                        elif shape == "early":
                            stops[0] = laps_done + max(1, stops[0] - 2)
                        stops[0] = min(stops[0], laps_done + max(1, int(window - 0.3)))
                        stops = sorted(set(stops))
                    ty = [tyre_rule == "all" or (tyre_rule == "alternate" and i % 2 == 1) for i in range(len(stops))]
                    plan = {"stops": stops, "tyres": ty, "save": save}
                    r = simulate(m, plan, race_s, tank, fuel_now, tyre_age, elapsed, temp, laps_done)
                    if r["ok"]:
                        cands.append((plan, r))
    cands.sort(key=lambda pr: (-pr[1]["laps"], pr[1]["time"]))
    out, seen = [], set()
    for plan, r in cands:
        sig = (len(plan["stops"]), plan["save"] > 0, any(plan["tyres"]))
        if sig in seen:
            continue
        seen.add(sig)
        out.append({"plan": plan, "res": r})
        if len(out) == 3:
            break
    if out:
        lead = out[0]["res"]
        for o in out:
            o["vs_a"] = round((o["res"]["time"] - lead["time"]) if o["res"]["laps"] == lead["laps"] else (lead["laps"] - o["res"]["laps"]) * 999, 1)
    return out


def describe(o, metric=True, name="A"):
    p, r = o["plan"], o["res"]
    u = (lambda l: f"{l:.0f} litres") if metric else (lambda l: f"{l / 3.785:.1f} gallons")
    if not r["stops"]:
        stops = "no stop"
    else:
        stops = ", ".join(f"lap {s['lap']} ({u(s['fuel'])}{', tyres' if s['tyres'] else ''})" for s in r["stops"])
    save = f", save {p['save']:.0f}% fuel a lap" if p["save"] else ""
    return {"name": name, "stops": len(r["stops"]), "text": f"{len(r['stops'])} stop{'s' if len(r['stops']) != 1 else ''}: {stops}{save}",
            "laps": r["laps"], "time": r["time"], "save": p["save"], "detail": r["stops"], "vs_a": o.get("vs_a", 0)}


def conditions(m, now_temp, now_wet, now_pace):
    """How today compares with your stored race simulations."""
    out = {"temp_diff": None, "wet_now": now_wet, "label": "no race sim yet", "pace_diff": None}
    if not m.get("race_sims"):
        return out
    st, sw = m.get("sim_temp"), m.get("sim_wet") or 0
    dt = (now_temp - st) if (now_temp is not None and st is not None) else None
    wet_change = abs((now_wet or 0) - sw) >= 2
    out["temp_diff"] = dt
    if wet_change or (dt is not None and abs(dt) > 12):
        out["label"] = "very different conditions"
    elif dt is not None and abs(dt) > 5:
        out["label"] = "different conditions"
    else:
        out["label"] = "the same conditions"
    if now_pace and m.get("sim_pace"):
        out["pace_diff"] = now_pace - m["sim_pace"]
    return out


# ---------------------------------------------------------------- against the cars ahead
def rival_outlook(m, plan_res, my_time_left_laps, rivals, per_tank_laps):
    """rivals: [{num, gap (s ahead of you), laps_since_stop, pace}] -> who each plan beats.
    A rival is assumed to fill up like you; they need ceil((laps left - laps they have)/per tank) more stops."""
    my_stop_loss = sum(s["time"] for s in plan_res["stops"])
    my_pace = (plan_res["time"] - my_stop_loss) / max(1, my_time_left_laps)
    out = []
    for rv in rivals:
        have = max(0.0, per_tank_laps - rv.get("laps_since_stop", 0))
        need = max(0, math.ceil((my_time_left_laps - have) / per_tank_laps - 1e-6))
        fl = m.get("fuel_lap") or 0
        their_fuel = max(0.0, (my_time_left_laps - have) * fl)          # what they still have to put in
        their_loss = need * m["lane_loss"] + (their_fuel / max(0.3, m["fuel_rate"]) if need else 0.0)
        pace_gap = ((rv.get("pace") or my_pace) - my_pace) * my_time_left_laps
        final = rv["gap"] - (their_loss - my_stop_loss) - pace_gap     # >0: still ahead of you at the end
        out.append({"num": rv["num"], "stops_left": need, "final_gap": round(final, 1), "beat": final < 0})
    return out
