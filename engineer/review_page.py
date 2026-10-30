"""#582 (2026-10-30): the iPad REVIEW page - what the iPad shows when he isn't in a session.

The latest session (or any of the last ten) from the recordings: a summary (track, car, session type, date, laps,
best lap, average of the clean laps, incidents), every lap with its sectors, its gap to the best lap and its flags
(pit / incident / off / invalid / partial), the throttle / brake / speed traces of a lap against the best lap, the
problem corners and the practice plan from the debrief (forensics), and the current setup suggestion next to the
setup he drove in that session.

Real data only (#419): every number comes from the recording, the forensics result or the setup store. Anything
that isn't there is None (the page shows "—" or a friendly empty state) - nothing is estimated or filled in.

Light on the PC (the iPad polls): one session is read once per recording file and kept in memory and on disk
(CACHE_DIR/review/, keyed by the recording's id, which changes when the file changes); the list of recordings is
looked at every 20 s at most; the forensics debrief is only read from what is already worked out, or worked out in
the background for one recording when iRacing is closed (never while he drives).

    view(sid=None, lap=None, ...)  -> the page's data (GET /api/review)
    session_data(path)             -> one recording's summary + laps + traces (cached)
"""
import json, os, threading, time

import numpy as np

V = 1                         # cache version: bump when the cached shape changes
N_SESSIONS = 10
LIST_TTL = 20.0               # seconds the list of recordings is kept before looking at the folders again
FRESH_S = 60                  # a recording written in the last minute may still be open in iRacing: not listed
POOL_FRAC = 1.03              # the clean-lap average ignores laps over 3 % off the best (same as Analysis' Simple view)
SECS = (1 / 3, 2 / 3)         # sector lines at a third and two thirds of the lap (same as the iPad's live laps)
KEEP_FILES = 40               # cached sessions kept on disk
GAP_MAX_FRAC = 0.30           # a time gap bigger than 30 % of a lap is a broken recording (analysis.DELTA_MAX_FRAC)

_lock = threading.Lock()
_MEM = {}                     # sid -> session data (newest few)
_HEAD = {}                    # sid -> list entry (track / car / type read from the file's header)
_LIST = {"t": 0.0, "rows": None}
_DB = {}                      # (sid, source key) -> debrief block
_JOBS = set()                 # sids whose forensics run in the background now


def _cache_dir():
    from .telemetry import CACHE_DIR
    return os.path.join(CACHE_DIR, "review")


def _fnum(x, dp=3):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, dp) if np.isfinite(x) else None


def _type_word(t):
    t = str(t or "").strip()
    return {"Lone Qualify": "Qualifying", "Open Qualify": "Qualifying", "Offline Testing": "Testing"}.get(t, t)


def _date_of(path):
    from .forensics import _date_of as fx_date        # the same date the debrief shows
    try:
        return fx_date(path, {})
    except OSError:
        return None


# ======================================================================================== the list of recordings
def _head(s):
    """List entry for one recording: track / car / session type from its header (cheap, cached per file id)."""
    h = _HEAD.get(s["id"])
    if h is not None:
        return h
    from .telemetry import car_name
    track, car, typ = None, None, None
    try:
        if not s["path"].lower().endswith(".renpz"):
            from .setup_sheet import ibt_setup, session_label
            _cs, info = ibt_setup(s["path"])
            wk = info.get("WeekendInfo") or {}
            di = info.get("DriverInfo") or {}
            me = next((x for x in di.get("Drivers") or [] if x.get("CarIdx") == di.get("DriverCarIdx")), {})
            track = wk.get("TrackDisplayName") or wk.get("TrackName")
            car = me.get("CarScreenName") or (car_name(me["CarPath"]) if me.get("CarPath") else None)
            ss = (info.get("SessionInfo") or {}).get("Sessions") or []
            if len(ss) == 1:                      # more than one: which one he drove needs the telemetry (session_data)
                typ = _type_word(session_label(info))
    except Exception:
        pass
    if not track and s.get("track") and s["track"] != "?":
        track = str(s["track"]).replace("_", " ").title()
    if not car and s.get("car") and s["car"] != "?":
        car = car_name(s["car"])
    h = {"id": s["id"], "track": track, "car": car, "type": typ, "date": _date_of(s["path"]), "mtime": s.get("mtime", 0)}
    _HEAD[s["id"]] = h
    return h


def recordings(list_fn=None, now=None):
    """The newest recordings, newest first (iRacing's folder, the archive, the fallback folder). Cached LIST_TTL s."""
    t = time.time()
    with _lock:
        if _LIST["rows"] is not None and t - _LIST["t"] < LIST_TTL and list_fn is None:
            return _LIST["rows"]
    cache = list_fn is None
    if cache:
        from .telemetry import list_sessions as list_fn
    now = now or t
    rows = [s for s in list_fn() if now - s.get("mtime", 0) > FRESH_S]
    rows.sort(key=lambda s: s.get("mtime", 0), reverse=True)
    rows = rows[:N_SESSIONS]
    if cache:
        with _lock:
            _LIST.update(t=t, rows=rows)
    return rows


def _entry(s):
    h = _head(s)
    d = _MEM.get(s["id"])
    if d:                                          # read already: the exact type and best lap
        h = dict(h, type=d.get("type") or h.get("type"), track=d.get("track") or h.get("track"), car=d.get("car") or h.get("car"))
        h["best"] = d.get("best")
        h["laps"] = d.get("laps_n")
    return {k: v for k, v in h.items() if k != "mtime"}


# ======================================================================================== one session
def _grid_points(L):
    return int(min(900, max(400, (L or 0) / 10)))


def _light(d, a, b, L, pedal):
    """Samples a..b on distance (metres from the line, monotonic) -> dist, time from the line, speed, pedals."""
    from .telemetry import lap_dist
    dist = lap_dist(d, a, b, L)
    keep = np.concatenate([[True], np.diff(dist) > 1e-4])
    dist = dist[keep]
    t = d["SessionTime"][a:b][keep]
    t = t - float(np.interp(0.0, dist, t))
    g = lambda ch: d[ch][a:b][keep].astype(np.float64) if ch in d else None
    return dist, t, g("Speed"), g(pedal), g("Brake")


def _build(path):
    """Read one recording -> its review data (plain JSON types)."""
    from .telemetry import Session, CHANNELS, _sid
    from . import setup_sheet as SS
    se = Session(path, channels=list(CHANNELS) + ["ThrottleRaw", "DisplayUnits"])
    d, L = se.d, float(se.track_len or 0)
    info = se.info or {}
    # session type: the session(s) he drove in this file (SessionNum in the telemetry), never a guess
    sn = d.get("SessionNum")
    nums = sorted(set(int(x) for x in np.unique(sn))) if sn is not None and len(sn) else None
    typ = _type_word(SS.session_label(info, nums)) if nums is not None else None
    if typ:
        typ = " / ".join(dict.fromkeys(_type_word(x.strip()) for x in typ.split("/")))
    du = d.get("DisplayUnits")
    met = bool(du is not None and len(du) and int(np.median(du)) == 1)
    k = 3.6 if met else 2.23694
    pedal = "ThrottleRaw" if "ThrottleRaw" in d else "Throttle"   # the driver's own pedal (no downshift blips)
    inc = d.get("PlayerCarMyIncidentCount")
    incidents = int(inc.max() - inc.min()) if inc is not None and len(inc) else None

    best = se.best
    best_t = best["time"] if best else None
    P = _grid_points(L)
    grid = np.linspace(0.0, L, P) if L > 0 else None
    laps, traces = [], {}
    for Lp in se.laps:
        row = {"n": int(Lp["n"]), "time": None, "sec": [None, None, None], "delta": None, "flags": [],
               "incidents": int(Lp.get("incidents") or 0), "clean": bool(Lp.get("valid")), "best": False}
        if not Lp["complete"]:
            row["flags"].append("partial")             # started or ended part-way round: no lap time
        else:
            row["time"] = _fnum(Lp["time"])
        if Lp.get("pit"):
            row["flags"].append("pit")
        if row["incidents"]:
            row["flags"].append("incident")
        if Lp.get("off"):
            row["flags"].append("off")
        if Lp["complete"] and not Lp.get("valid") and not ({"pit", "incident", "off"} & set(row["flags"])):
            row["flags"].append("invalid")
        if Lp["complete"] and grid is not None:
            try:
                dist, t, v, thr, brk = _light(d, Lp["a"], Lp["b"], L, pedal)
                if len(dist) > 20 and dist[-1] > 0.9 * L:
                    for j, f in enumerate(SECS):
                        x = f * L
                        if dist[0] <= x <= dist[-1]:
                            row["sec"][j] = float(np.interp(x, dist, t))
                    s1, s2 = row["sec"][0], row["sec"][1]
                    if s1 is not None and s2 is not None and row["time"] and row["time"] > s2 > s1 > 0:
                        row["sec"] = [_fnum(s1), _fnum(s2 - s1), _fnum(row["time"] - s2)]
                    else:
                        row["sec"] = [None, None, None]
                    end = float(dist[-1])
                    gg = grid[grid <= end]
                    tr = {"t": [round(float(x), 3) for x in np.interp(gg, dist, t)]}
                    tr["v"] = [round(float(x) * k, 1) for x in np.interp(gg, dist, v)] if v is not None else None
                    tr["thr"] = [round(float(x), 3) for x in np.interp(gg, dist, thr)] if thr is not None else None
                    tr["brk"] = [round(float(x), 3) for x in np.interp(gg, dist, brk)] if brk is not None else None
                    traces[str(row["n"])] = tr
            except Exception:
                row["sec"] = [None, None, None]
        if best and Lp["n"] == best["n"]:
            row["best"] = True
        if best_t and row["time"] is not None:
            row["delta"] = _fnum(row["time"] - best_t)
        laps.append(row)

    # clean-lap average: Analysis' Simple view (clean laps within 3 % of the best)
    clean = [r for r in laps if r["clean"] and r["time"] is not None]
    pool = [r["time"] for r in clean if best_t and r["time"] < best_t * POOL_FRAC]
    avg = _fnum(sum(pool) / len(pool)) if pool else None
    spread = _fnum(float(np.std(pool, ddof=1)), 2) if len(pool) > 1 else None
    best_sec = [None, None, None]
    for r in clean:
        for j, x in enumerate(r["sec"]):
            if x is not None and (best_sec[j] is None or x < best_sec[j]):
                best_sec[j] = x
    flat = {}
    try:
        flat = SS.flatten(se.setup) if se.setup else {}
    except Exception:
        flat = {}
    try:
        corners = [{"name": c["name"], "start": _fnum(c["start"], 1), "end": _fnum(c["end"], 1)} for c in se.find_corners() or []]
    except Exception:
        corners = []
    st = os.stat(path)
    return {"v": V, "sid": _sid(path), "file": os.path.basename(path), "path": path, "stamp": [st.st_size, int(st.st_mtime)],
            "src": se.source, "track": se.track_display or se.track_name or None, "track_name": se.track_name or None,
            "car": se.car or None, "car_path": se.car_path or None, "type": typ or None, "date": _date_of(path),
            "units": "kmh" if met else "mph", "track_len": _fnum(L, 1),
            "laps": laps, "laps_n": sum(1 for r in laps if r["time"] is not None), "clean_n": len(clean),
            "best_n": best["n"] if best else None, "best": _fnum(best_t) if best_t else None,
            "best_clean": bool(best and best.get("valid")), "avg": avg, "avg_n": len(pool), "spread": spread,
            "best_sec": best_sec, "incidents": incidents, "corners": corners, "setup_flat": flat,
            "grid": [round(float(x), 1) for x in grid] if grid is not None else [], "traces": traces}


def _cache_file(sid):
    return os.path.join(_cache_dir(), f"rv_{sid}.json")


def session_data(path, sid=None):
    """One recording's review data, read once per file (memory, then disk, then the recording itself)."""
    from .telemetry import _sid
    sid = sid or _sid(path)
    d = _MEM.get(sid)
    if d is not None:
        return d
    cf = _cache_file(sid)
    try:
        with open(cf, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("v") != V or d.get("sid") != sid:
            d = None
    except (OSError, ValueError):
        d = None
    if d is None:
        d = _build(path)
        try:
            os.makedirs(_cache_dir(), exist_ok=True)
            with open(cf + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f, separators=(",", ":"))
            os.replace(cf + ".tmp", cf)
            _trim_cache()
        except OSError:
            pass
    with _lock:
        _MEM[sid] = d
        while len(_MEM) > 4:                          # a few sessions in memory (each one holds its laps' traces)
            _MEM.pop(next(iter(_MEM)))
    return d


def _trim_cache():
    try:
        fs = sorted((os.path.join(_cache_dir(), f) for f in os.listdir(_cache_dir()) if f.startswith("rv_") and f.endswith(".json")),
                    key=os.path.getmtime, reverse=True)
        for f in fs[KEEP_FILES:]:
            os.remove(f)
    except OSError:
        pass


def public(d):
    """The session for the page: without the traces (one lap at a time, when tapped) and the raw setup."""
    if not d:
        return None
    return {k: v for k, v in d.items() if k not in ("traces", "setup_flat", "grid", "path", "stamp", "v")}


def trace(d, n):
    """Lap n and the best lap on the same distance grid (down-sampled), with the time gap along the lap."""
    tr = (d.get("traces") or {}).get(str(n))
    if tr is None:
        return {"lap": n, "error": "No trace for this lap (it wasn't a full lap in the recording)."}
    grid = d.get("grid") or []
    out = {"lap": int(n), "ref": None, "units": d.get("units"), "d": grid[:len(tr["t"])], "me": tr, "best": None, "gap": None,
           "corners": d.get("corners") or [], "track_len": d.get("track_len")}
    bn = d.get("best_n")
    if bn is not None and int(bn) != int(n):
        rb = (d.get("traces") or {}).get(str(bn))
        if rb is not None:
            out["ref"], out["best"] = int(bn), rb
            m = min(len(tr["t"]), len(rb["t"]))
            gap = [round(a - b, 3) for a, b in zip(tr["t"][:m], rb["t"][:m])]
            lap_t = min(tr["t"][m - 1], rb["t"][m - 1]) if m else 0
            if gap and lap_t > 1 and max(abs(x) for x in gap) <= GAP_MAX_FRAC * lap_t:
                out["gap"] = gap                     # never an impossible gap: no line instead
    return out


# ======================================================================================== the debrief (forensics)
def _plain(rv_session, plan_from=None):
    """One forensics session (+ the night review's plan when it includes this session) -> the page's debrief block."""
    from . import debrief as DB
    s = rv_session
    ss = DB.label_sessions([dict(s)]) if "label" not in s else [s]
    hot = DB.hot_corners(ss)
    corners = []
    for r in hot:
        bits = [x for x in (f"{r['incidents']} incident{'s' if r['incidents'] != 1 else ''}" if r["incidents"] else "",
                            f"{r['slides']} big slide{'s' if r['slides'] != 1 else ''}" if r["slides"] else "",
                            f"{r['lockups']} lock-up{'s' if r['lockups'] != 1 else ''}" if r["lockups"] else "") if x]
        corners.append({"name": r["name"], "text": ", ".join(bits)})
    plan = plan_from if plan_from is not None else DB.practice_plan(ss)
    top = [{"title": t["title"], "why": t["why"], "drill": t["drill"]} for t in DB.top3(ss)]
    sm = s.get("summary") or {}
    return {"state": "ready", "corners": corners, "plan": [{"title": p["title"], "text": p["text"]} for p in plan or []],
            "top": top, "time_corners": [{"name": r["name"], "lost": r["lost"]} for r in sm.get("corner_loss") or []],
            "episodes": [{"lap": e.get("lap"), "kind": e.get("kind"), "title": e.get("title"), "cause": e.get("cause_title"),
                          "corner": e.get("corner_key"), "pts": e.get("pts")} for e in s.get("episodes") or []],
            "incidents": sm.get("incidents")}


def debrief_for(sid, path, fx_review=None, can_analyse=None, run_fx=None, log=print):
    """The debrief for one session: from the night review when it covers this session, else from the forensics already
    worked out for this recording; else worked out in the background when allowed (can_analyse(): iRacing closed)."""
    if fx_review:
        for s in fx_review.get("sessions") or []:
            if str(s.get("id")) == str(sid):
                key = (sid, "night", id(fx_review))
                b = _DB.get(key)
                if b is None:
                    b = dict(_plain(s, fx_review.get("plan")), source="night review")
                    _DB[key] = b
                return b
    key = (sid, "file")
    b = _DB.get(key)
    if b is not None:
        return b
    from . import forensics as F
    cp = F.cache_path([path])
    if os.path.isfile(cp):
        try:
            res = F.analyse_cached([path], log=log)
            s = next((x for x in res.get("sessions") or [] if str(x.get("id")) == str(sid)), None)
            b = dict(_plain(s), source="this session") if s else {"state": "none", "why": "The debrief found nothing to read in this recording."}
        except Exception as e:
            log(f"[review] debrief: {e!r}")
            b = {"state": "none", "why": "Couldn't read the debrief for this session."}
        _DB[key] = b
        return b
    if can_analyse is not None and can_analyse():
        if sid not in _JOBS:
            _JOBS.add(sid)

            def job():
                try:
                    (run_fx or (lambda ps: F.analyse_cached(ps, log=log)))([path])
                except Exception as e:
                    log(f"[review] debrief: {e!r}")
                    _DB[key] = {"state": "none", "why": "Couldn't work out the debrief for this session."}
                finally:
                    _JOBS.discard(sid)
            threading.Thread(target=job, daemon=True).start()
        return {"state": "pending", "why": "Working out the debrief for this session…"}
    return {"state": "none", "why": "The debrief is worked out once iRacing is closed."}


# ======================================================================================== the setup suggestion
def setup_block(store, d=None):
    """The current suggestion (setup_sheet's store) with, for each change, the value he drove with in this session
    (same car only) - read-only: nothing is ticked from here."""
    from . import setup_sheet as SS
    if store is None:
        return {"has": False}
    try:
        sug, ticks = store.get(None)
    except Exception:
        sug, ticks = None, {}
    if not sug:
        return {"has": False}
    sh = SS.sheet(sug, None, None, ticks)
    same = bool(d and d.get("car_path") and sug.get("car_path") and SS.norm(d["car_path"]) == SS.norm(sug["car_path"]))
    flat = (d or {}).get("setup_flat") or {} if same else {}
    lay = SS.layout_for(sug.get("car_path"), sug.get("car")) or SS.generic_layout(SS._unflatten(sug.get("values") or {}), sug.get("car", ""))
    items = []
    for it in sh.get("items") or []:
        fl = []
        for f in it.get("fields") or []:
            here = None
            if flat:
                raw = flat.get(f["path"])
                if raw is not None:
                    here = SS.display(raw, SS._field_meta(lay, f["path"]) or {"unit": "raw"})[0]
            fl.append({"label": f["label"], "before": f["before"], "sug": f["sug"], "here": here})
        items.append({"t": it["t"], "how": it["how"], "reason": it["reason"], "state": it["state"], "fields": fl})
    return {"has": True, "id": sug.get("id"), "date": sug.get("date"), "source": sug.get("source"), "car": sug.get("car"),
            "track": sug.get("track"), "session": sug.get("session"), "same_car": same, "items": items,
            "done": sh.get("done"), "total": sh.get("total")}


# ======================================================================================== the page
def view(sid=None, lap=None, store=None, fx_review=None, can_analyse=None, run_fx=None, on_track=False, session_live=False,
         list_fn=None, log=print):
    """GET /api/review: the last recordings (pick one), the chosen one's summary and laps, its debrief, the setup
    suggestion; with lap=N also that lap's traces against the best lap."""
    out = {"ok": True, "on_track": bool(on_track), "session_live": bool(session_live), "sessions": [], "sid": None,
           "session": None, "debrief": None, "setup": setup_block(store)}
    try:
        rows = recordings(list_fn)
    except Exception as e:
        log(f"[review] list: {e!r}")
        rows = []
    if not rows:
        out["why"] = "No recordings yet. Drive a session and it shows up here."
        return out
    pick = next((s for s in rows if s["id"] == sid), None) if sid else None
    if pick is None:
        pick = rows[0]
    out["sid"] = pick["id"]
    try:
        d = session_data(pick["path"], pick["id"])
    except Exception as e:
        log(f"[review] {os.path.basename(pick['path'])}: {e!r}")
        d = None
        out["why"] = "Couldn't read this recording."
    out["sessions"] = [_entry(s) for s in rows]
    if d is None:
        return out
    out["session"] = public(d)
    out["setup"] = setup_block(store, d)
    try:
        out["debrief"] = debrief_for(pick["id"], pick["path"], fx_review, can_analyse, run_fx, log)
    except Exception as e:
        log(f"[review] debrief: {e!r}")
        out["debrief"] = {"state": "none", "why": "Couldn't read the debrief for this session."}
    eps = (out["debrief"] or {}).get("episodes") or []
    if eps:                                            # the debrief's incidents on their laps
        for r in out["session"]["laps"]:
            r["fx"] = [e["title"] for e in eps if e.get("lap") == r["n"] and e.get("title")]
    if lap is not None:
        try:
            out["trace"] = trace(d, int(lap))
        except (TypeError, ValueError):
            out["trace"] = {"lap": lap, "error": "No trace for this lap."}
    return out


def reset():
    """Forget everything kept in memory (tests)."""
    with _lock:
        _MEM.clear(); _HEAD.clear(); _DB.clear(); _JOBS.clear()
        _LIST.update(t=0.0, rows=None)
