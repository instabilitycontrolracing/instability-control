"""Lap analysis: compare a lap to a reference, find where time goes, and say what to do about it."""
import json, os, time
import numpy as np

from .telemetry import Session, corner_metrics, delta, list_sessions, lap_dist, recording_meta, CACHE_DIR

_SESSIONS = {}


def open_session(path):
    s = _SESSIONS.get(path)
    if s is None:
        s = Session(path)
        _SESSIONS.clear()   # keep memory small: one session (plus reference) at a time
        _SESSIONS[path] = s
    return s


# ---------------------------------------------------------------- advice
def _fmt_m(x):
    return f"{abs(x):.0f} m"


def corner_advice(m, r, dt):
    """m = this lap, r = reference lap metrics, dt = time lost here (s, + = slower). -> list of (weight, text)."""
    tips = []
    if m is None or r is None:
        return tips
    # braking point (positive = braked earlier than the reference)
    if m.get("brake_d") is not None and r.get("brake_d") is not None:
        early = r["brake_d"] - m["brake_d"]
        if early > 6:
            tips.append((early * 0.6, f"Brake {_fmt_m(early)} later ({m['brake_d']:.0f} vs {r['brake_d']:.0f} m)."))
        elif early < -8 and m["min_kmh"] < r["min_kmh"] - 2:
            tips.append((-early * 0.5, f"Too deep: braked {_fmt_m(early)} later but slower at apex ({m['min_kmh']:.0f} vs {r['min_kmh']:.0f}). Brake earlier, roll more speed."))
    if m.get("peak_brake") and r.get("peak_brake") and m["peak_brake"] < r["peak_brake"] - 8:
        tips.append((4, f"Harder initial brake ({m['peak_brake']:.0f}% vs {r['peak_brake']:.0f}%)."))
    if m.get("abs_pct", 0) > max(25, r.get("abs_pct", 0) + 15):
        tips.append((3, f"ABS on {m['abs_pct']:.0f}% of braking: ease the peak."))
    # apex speed
    dv = r["min_kmh"] - m["min_kmh"]
    if dv > 2:
        tips.append((dv * 2.2, f"+{dv:.0f} km/h at apex ({m['min_kmh']:.0f} vs {r['min_kmh']:.0f}): release the brake slower."))
    # coasting
    dc = m.get("coast_m", 0) - r.get("coast_m", 0)
    if dc > 10:
        tips.append((dc * 0.3, f"Coasting {m['coast_m']:.0f} m (+{dc:.0f}): trail brake longer or throttle earlier."))
    # throttle
    if m.get("throttle_on_d") and r.get("throttle_on_d"):
        late = m["throttle_on_d"] - r["throttle_on_d"]
        if late > 6:
            tips.append((late * 0.5, f"Throttle {_fmt_m(late)} sooner."))
    if m.get("full_throttle_d") and r.get("full_throttle_d"):
        late = m["full_throttle_d"] - r["full_throttle_d"]
        if late > 10:
            tips.append((late * 0.35, f"Full throttle {_fmt_m(late)} sooner: open the wheel earlier."))
    elif m.get("full_throttle_d") is None and r.get("full_throttle_d"):
        tips.append((8, "Never full throttle on exit."))
    dex = r["exit_kmh"] - m["exit_kmh"]
    if dex > 3:
        tips.append((dex * 1.5, f"Exit {dex:.0f} km/h slower ({m['exit_kmh']:.0f} vs {r['exit_kmh']:.0f})."))
    if m["steer_reversals"] > r["steer_reversals"] + 3:
        tips.append((4, f"Smoother hands: {m['steer_reversals']} corrections vs {r['steer_reversals']}."))
    if m.get("gear_apex") and r.get("gear_apex") and m["gear_apex"] != r["gear_apex"]:
        tips.append((3, f"Apex gear {m['gear_apex']} vs {r['gear_apex']}."))
    if m.get("kerb_m", 0) > r.get("kerb_m", 0) + 15:
        tips.append((2, f"More kerb ({m['kerb_m']:.0f} vs {r.get('kerb_m', 0):.0f} m)."))
    tips.sort(key=lambda t: -t[0])
    if dt > 0.05 and not tips:
        tips.append((1, "Small loss, no single cause."))
    return tips


# ---------------------------------------------------------------- compare
DELTA_MAX_FRAC = 0.30      # a gap bigger than 30 % of a lap is a broken recording, not driving


def delta_check(trA, trR, track_len=None):
    """None when the time-vs-distance comparison of two laps is believable, else a short reason (2026-10-27:
    a replay recording once showed "-212.40 s vs ref" and every corner 10-24 s faster)."""
    try:
        tA, tR = float(trA["t"][-1]), float(trR["t"][-1])
        dA, dR = float(trA["d"][-1]), float(trR["d"][-1])
    except (KeyError, IndexError, TypeError):
        return "no lap data"
    L = float(track_len or max(dA, dR) or 1.0)
    if tA <= 1.0 or tR <= 1.0 or min(dA, dR) < 0.9 * L:
        return "one of the laps wasn't recorded properly"
    n = min(len(trA["t"]), len(trR["t"]))
    dt = np.asarray(trA["t"][:n]) - np.asarray(trR["t"][:n])
    if not np.isfinite(dt).all():
        return "one of the laps wasn't recorded properly"
    if float(np.max(np.abs(dt))) > DELTA_MAX_FRAC * min(tA, tR):
        return "the laps are too far apart to compare"
    return None


def compare(sess, lap_n, ref_sess, ref_n, points=1400):
    trA, trR = sess.trace(lap_n), ref_sess.trace(ref_n)
    d, dt = delta(trA, trR)
    bad = delta_check(trA, trR, sess.track_len)
    if bad:
        dt = np.zeros_like(dt)                      # never show impossible deltas: "-" in the UI instead
    corners = sess.find_corners()
    rows = []
    for c in corners:
        m = corner_metrics(trA, c["start"], c["end"])
        r = corner_metrics(trR, c["start"], c["end"])
        if not m or not r:
            continue
        a, b = m["span"]
        ia, ib = int(np.searchsorted(d, a)), min(len(d) - 1, int(np.searchsorted(d, b)))
        lost = float(dt[ib] - dt[ia])
        rows.append({"name": c["name"], "key": c["key"], "start": c["start"], "end": c["end"], "span": [a, b],
                     "lost": None if bad else round(lost, 3), "me": _round(m), "ref": _round(r),
                     "tips": [t for _, t in corner_advice(m, r, lost if not bad else 0.0)][:4]})
    idx = np.linspace(0, len(d) - 1, points).astype(int)
    ch = lambda tr, k: [round(float(x), 3) for x in tr[k][idx]] if k in tr else []
    # time lost per metre, smoothed, for colouring the map
    rate = np.gradient(dt) if len(dt) > 3 else np.zeros_like(dt)
    k = 40
    rate = np.convolve(rate, np.ones(k) / k, mode="same")
    total = float(dt[-1]) if len(dt) else 0.0
    return {
        "d": [round(float(x), 1) for x in d[idx]],
        "delta": [round(float(x), 3) for x in dt[idx]],
        "rate": [round(float(x) * 1000, 2) for x in rate[idx]],   # ms lost per metre
        "me": {"kmh": ch(trA, "kmh"), "thr": ch(trA, "Throttle"), "brk": ch(trA, "Brake"), "steer": ch(trA, "SteeringWheelAngle"), "gear": ch(trA, "Gear")},
        "ref": {"kmh": ch(trR, "kmh"), "thr": ch(trR, "Throttle"), "brk": ch(trR, "Brake"), "steer": ch(trR, "SteeringWheelAngle"), "gear": ch(trR, "Gear")},
        "corners": rows,
        "total": None if bad else round(total, 3),
        "delta_ok": not bad,
        "delta_note": f"Time gap not shown: {bad}." if bad else None,
        "biggest": [] if bad else sorted([r for r in rows if r["lost"] > 0.02], key=lambda r: -r["lost"])[:3],
    }


def section(sess, lap_n, ref_sess, ref_n, d0, d1):
    """A highlighted stretch of track: time lost there and what to do about it."""
    d0, d1 = min(d0, d1), max(d0, d1)
    trA, trR = sess.trace(lap_n), ref_sess.trace(ref_n)
    d, dt = delta(trA, trR)
    bad = delta_check(trA, trR, sess.track_len)
    if bad:
        dt = np.zeros_like(dt)
    i0, i1 = int(np.searchsorted(d, d0)), min(len(d) - 1, int(np.searchsorted(d, d1)))
    lost = float(dt[i1] - dt[i0])
    out = {"from": d0, "to": d1, "lost": None if bad else round(lost, 3), "delta_ok": not bad, "corners": [], "notes": []}
    if bad:
        out["notes"].append(f"Time gap not shown: {bad}.")
    for c in sess.find_corners():
        if c["end"] < d0 - 20 or c["start"] > d1 + 20:
            continue
        m, r = corner_metrics(trA, c["start"], c["end"]), corner_metrics(trR, c["start"], c["end"])
        if not m or not r:
            continue
        a, b = m["span"]
        ia, ib = int(np.searchsorted(d, a)), min(len(d) - 1, int(np.searchsorted(d, b)))
        cl = float(dt[ib] - dt[ia])
        out["corners"].append({"name": c["name"], "lost": round(cl, 3), "me": _round(m), "ref": _round(r),
                               "tips": [t for _, t in corner_advice(m, r, cl)][:5]})
    # straights inside the selection
    vA, vR = trA["kmh"][i0:i1 + 1], trR["kmh"][i0:i1 + 1]
    if len(vA) > 10:
        top_a, top_r = float(vA.max()), float(vR.max())
        if top_r - top_a > 3 and not out["corners"]:
            out["notes"].append(f"Top speed {top_r - top_a:.0f} km/h lower ({top_a:.0f} vs {top_r:.0f}): exit of the corner before.")
        thrA, thrR = trA["Throttle"][i0:i1 + 1], trR["Throttle"][i0:i1 + 1]
        lift = float(((thrA < 0.9) & (thrR > 0.97)).sum() * (d[1] - d[0]))
        if lift > 15:
            out["notes"].append(f"Lifted ~{lift:.0f} m where the ref was flat.")
    if bad:
        for c in out["corners"]:
            c["lost"] = None
        return out
    if not out["corners"] and not out["notes"]:
        out["notes"].append("Within a few hundredths." if abs(lost) < 0.05 else "Loss spread out, no single cause.")
    if lost < -0.02:
        out["notes"].insert(0, f"{abs(lost):.2f} s faster here.")
    return out


def _round(m):
    return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in m.items() if k != "span"}


# ---------------------------------------------------------------- all-time best per car+track
def _index_path():
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, "laps_index.json")


def lap_index(progress=None):
    """Best valid lap of every session, cached. -> {session_id: {...}}"""
    p = _index_path()
    try:
        idx = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        idx = {}
    sessions = list_sessions()
    # 2026-10-27 (#391): replay recordings indexed before the replay lap fix are read again once ("v" 2)
    todo = [s for s in sessions if s["id"] not in idx or idx[s["id"]].get("error")
            or (s["path"].lower().endswith(".renpz") and idx[s["id"]].get("v", 1) < 2)]
    for i, s in enumerate(todo):
        try:
            se = Session(s["path"])
            laps = [{"n": L["n"], "time": L["time"], "valid": L["valid"], "complete": L["complete"], "pit": L["pit"]} for L in se.laps]
            idx[s["id"]] = {"path": s["path"], "src": se.source, "car": se.car, "car_path": se.car_path, "track": se.track_name,
                            "track_display": se.track_display, "date": s["date"], "laps": laps,
                            "best": se.best and {"n": se.best["n"], "time": se.best["time"]}, "v": 2}
        except Exception as e:
            idx[s["id"]] = {"path": s["path"], "error": repr(e), "laps": [], "best": None}
        if progress:
            progress(i + 1, len(todo))
        if i % 10 == 9:
            json.dump(idx, open(p, "w", encoding="utf-8"))
    for s in sessions:                 # 2026-10-27: entries indexed before "src" existed (cheap: no channels read)
        v = idx.get(s["id"])
        if v is not None and "src" not in v:
            v["src"] = recording_meta(s["path"])["src"]
    live = {s["id"] for s in sessions}
    idx = {k: v for k, v in idx.items() if k in live}
    json.dump(idx, open(p, "w", encoding="utf-8"))
    return idx


def _is_replay(v):
    """A recording of a replay (the car you were watching - maybe not you): never in all-time numbers unless picked."""
    if v.get("src"):
        return v["src"] == "replay"
    p = v.get("path") or ""
    return p.lower().endswith(".renpz") and recording_meta(p)["src"] == "replay"


def all_time_best(idx, car_path, track, include_replays=False):
    best = None
    for sid, v in idx.items():
        if not include_replays and _is_replay(v):
            continue
        if v.get("car_path") == car_path and v.get("track") == track and v.get("best"):
            if best is None or v["best"]["time"] < best[1]["best"]["time"]:
                best = (sid, v)
    return best


# ---------------------------------------------------------------- theoretical best
# Your best time in every part of the track, stitched into one lap. Cuts are made in the middle of the
# straights (between corners), so each corner comes whole from one lap.

def theory_cuts(sess):
    L = sess.track_len
    cs = sorted(sess.find_corners(), key=lambda c: c["start"])
    groups = []
    for c in cs:
        if groups and c["start"] - groups[-1]["end"] < 40:          # chicanes / esses: one piece
            groups[-1]["end"] = max(groups[-1]["end"], c["end"]); groups[-1]["names"].append(c["name"])
        else:
            groups.append({"start": c["start"], "end": c["end"], "names": [c["name"]]})
    if len(groups) < 2:
        n = max(4, int(L // 400))
        cuts = list(np.linspace(0, L, n + 1))
        return cuts, [f"Part {i + 1}" for i in range(n)]
    cuts = [0.0] + [(groups[i]["end"] + groups[i + 1]["start"]) / 2 for i in range(len(groups) - 1)] + [L]
    names = [" / ".join(g["names"][:2]) + ("…" if len(g["names"]) > 2 else "") for g in groups]
    # merge pieces shorter than 60 m into the one before
    out, nm = [0.0], [names[0]]
    for x, n in zip(cuts[1:-1], names[1:]):
        if x - out[-1] > 60:
            out.append(x); nm.append(n)
        else:
            nm[-1] += " / " + n
    if len(out) > 1 and L - out[-1] < 60:
        out.pop(); last = nm.pop(); nm[-1] += " / " + last
    out.append(L)
    return out, nm


def _lap_t(sess, n):
    """Time along the lap on a 1 m grid (cheap: no other channels)."""
    tr = sess._traces.get((n, 1.0))
    if tr is not None:
        return tr["t"]
    L = sess.lap(n)
    d = sess.d
    a, b = L["a"], L["b"]
    dist = lap_dist(d, a, b, sess.track_len)            # same as Session.trace (2026-10-27: wrap at the line)
    keep = np.concatenate([[True], np.diff(dist) > 1e-4])
    dist = dist[keep]
    grid = np.arange(0, min(sess.track_len, dist[-1]), 1.0)
    t = d["SessionTime"][a:b][keep]
    return np.interp(grid, dist, t) - float(np.interp(0.0, dist, t))


def _candidate_laps(sess, strict=True):
    good = [L for L in sess.laps if L["valid"]]
    if not good and not strict:
        good = [L for L in sess.laps if L["complete"] and not L["pit"]]
    if not good:
        return []
    best = min(L["time"] for L in good)
    return [L for L in good if L["time"] < best * 1.07]


class Theory:
    """A stitched lap. Behaves like a reference session for compare()/section(): .trace(n) returns it."""
    def __init__(self, tr, time, segs, base_best):
        self._tr, self.time, self.segs = tr, time, segs
        self.gain = round(base_best - time, 3) if base_best else 0.0
        self.path = None

    def trace(self, n=None, step=1.0):
        return self._tr

    def summary(self):
        return {"time": round(self.time, 3), "gain": self.gain, "segs": self.segs}


def build_theory(base, sources=None, progress=None):
    """base = the session being analysed. sources = [(label_fn, path)] of other sessions (same car + track).
    -> Theory or None."""
    cuts, names = theory_cuts(base)
    base_best = base.best and base.best["time"]
    E = int(len(base.trace(base.best["n"])["t"]) if base.best else base.track_len) - 15
    ci = [min(int(round(x)), E) for x in cuts[:-1]] + [E]
    nseg = len(ci) - 1
    rows = []           # (segment times, origin, lap n)

    def scan(sess, origin):
        strict = origin is not None
        for L in _candidate_laps(sess, strict=strict):
            t = _lap_t(sess, L["n"])
            if len(t) <= E:
                continue
            st = [float(t[ci[j + 1]] - t[ci[j]]) for j in range(nseg - 1)]
            st.append(float(L["time"] - t[ci[-2]]))            # last piece runs to the line
            rows.append((st, origin, L["n"], L["time"]))

    scan(base, None)
    for i, (label, path) in enumerate(sources or []):
        try:
            s = Session(path, landmarks=base.landmarks)
            scan(s, (label, path))
            del s
        except Exception:
            pass
        if progress:
            progress(i + 1, len(sources))
    if len(rows) < 2:
        return None
    M = np.array([r[0] for r in rows])
    med = np.median(M, axis=0)
    M = np.where(M < med * 0.97, np.inf, M)                    # a glitch can't win a piece
    win = M.argmin(axis=0)
    # build the stitched trace from the winning laps
    opened = {}
    def tr_of(k):
        st, origin, n, _ = rows[k]
        if origin is None:
            return base.trace(n)
        path = origin[1]
        if path not in opened:
            opened[path] = Session(path, landmarks=base.landmarks)
        return opened[path].trace(n)
    traces = {k: tr_of(k) for k in set(win.tolist())}
    keys = set.intersection(*(set(t.keys()) for t in traces.values())) - {"d", "t"}
    out = {"d": np.arange(0, E + 1, 1.0)}
    tt = np.empty(E + 1)
    chans = {k: np.empty(E + 1) for k in keys}
    acc, segs = 0.0, []
    for j in range(nseg):
        a, b = ci[j], ci[j + 1]
        k = int(win[j]); tr = traces[k]
        hi = b + 1 if j == nseg - 1 else b
        tt[a:hi] = tr["t"][a:hi] - tr["t"][a] + acc
        for c in keys:
            chans[c][a:hi] = tr[c][a:hi]
        acc += float(M[k, j])
        st, origin, n, lapt = rows[k]
        yours = [r for r in rows if r[1] is None]
        bt = min(yours, key=lambda r: r[3])[0][j] if yours else None
        col = M[:, j][np.isfinite(M[:, j])]
        typical = float(np.median(col)) - float(M[k, j]) if len(col) else 0.0
        segs.append({"name": names[j], "from": float(cuts[j]), "to": float(cuts[j + 1]), "time": round(float(M[k, j]), 3),
                     "typical_loss": round(typical, 3),
                     "lap": n, "where": "this session" if origin is None else origin[0],
                     "vs_best": round(bt - float(M[k, j]), 3) if bt is not None else None})
    out["t"] = tt
    out.update(chans)
    return Theory(out, acc, segs, base_best)


def theory_sources(idx, base, sid):
    """Other sessions with the same car and track, as [(label, path)]."""
    out = []
    for k, v in (idx or {}).items():
        if k == sid or v.get("error") or v.get("car_path") != base.car_path or v.get("track") != base.track_name:
            continue
        if _is_replay(v):                       # 2026-10-27: someone else's laps can't be your theoretical best
            continue
        if any(L.get("valid") for L in v.get("laps", [])):
            out.append((v.get("date", "")[:10], v["path"]))
    return out


def theory_cache_key(base, sources):
    import hashlib
    h = hashlib.md5(json.dumps([base.path, os.path.getmtime(base.path)] + sorted(
        [p, os.path.getmtime(p)] for _, p in sources if os.path.exists(p))).encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"theory2_{h}")


def load_theory(key):
    try:
        z = np.load(key + ".npz")
        meta = json.load(open(key + ".json", encoding="utf-8"))
        th = Theory({k: z[k] for k in z.files}, meta["time"], meta["segs"], None)
        th.gain = meta["gain"]
        return th
    except Exception:
        return None


def save_theory(key, th):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        np.savez_compressed(key + ".npz", **{k: v.astype(np.float32) if k != "t" else v for k, v in th._tr.items()})
        json.dump({"time": th.time, "gain": th.gain, "segs": th.segs}, open(key + ".json", "w", encoding="utf-8"))
    except Exception:
        pass
