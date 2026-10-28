"""The iPad's lap analysis memory, kept on the PC (2026-10-25, request: "the iPad app has no way of grabbing car
telemetry if the app restarts, like the old telemetry from before the restart").

The iPad page used to record laps only while it was open, in the browser - reload the page, restart the engineer
or open it mid-race and the earlier laps were gone. Now the PC records every lap itself (the same samples the iPad
draws: distance, speed, throttle, brake, lap time; ten a second, whether a page is open or not), keeps the last
twelve complete laps plus the lap in progress, writes them to engineer_laps_state.json every 15 s and on every new
lap, and reads them back after a restart in the same session. When the iPad connects it gets them all at once
("laps" event) and carries on from there.
"""
import json, math, os, time

# 2026-10-27 (telemetry vault, request: "make sure that never happens again"): after a session the laps are also rebuilt
# from the recording itself (iRacing's .ibt or the engineer's own .renpz) and merged in - so laps the live store missed
# (app restarted mid-lap, app closed, iPad not open) are there for the iPad, the analysis and the meeting anyway.

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engineer_laps_state.json")
# 2026-10-25 (request: "keep a cache of the laps"): one file per session (subsession + session + track), so going to
# another session and back - or watching a replay of it later - picks its laps up again; the newest 40 sessions kept
DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engineer_laps")
KEEP_SESSIONS = 40
SECS = (1 / 3, 2 / 3)
MAX_PTS = 8000
KEEP = 80                 # 2026-10-27: was 30 - a whole race's laps (Le Mans ~50) stay; a lap is ~2-3k points


def _f(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _new(no):
    return {"no": no, "p": [], "s": [], "th": [], "br": [], "t": [], "st": [], "gr": [], "sec": [None, None, None], "clean": True, "start": None}


class LapStore:
    def __init__(self, log=print):
        self.log = log
        self.key = None
        self.laps, self.cur, self.lap_no = [], None, None
        self.best_no = None
        self.met = False
        self._t = 0.0
        self._last_wall = 0.0
        self._save_t = 0.0
        self._dirty = False
        self.live = None          # 2026-10-25: this lap as we measure it (lap, pct, cur) - right in replays too
        self._pending = []        # 2026-10-27: laps rebuilt from a recording, waiting for the next tick

    # ------------------------------------------------------------------ the live delta (2026-10-25)
    def delta(self):
        """Time against the best lap at the same point of the lap (seconds, + = slower), or None. Works in replays
        and whenever iRacing's own LapDeltaToBestLap isn't there (request: "the delta between the laps doesn't work")."""
        c = self.cur
        best = next((l for l in self.laps if l.get("no") == self.best_no and l.get("time")), None)
        if not c or not best or not c.get("p") or len(best.get("p") or []) < 10:
            return None
        pct, t = c["p"][-1], c["t"][-1]
        P, T = best["p"], best["t"]
        import bisect
        i = bisect.bisect_left(P, pct)
        if i <= 0 or i >= len(P):
            return None
        f = (pct - P[i - 1]) / ((P[i] - P[i - 1]) or 1)
        ref = T[i - 1] + (T[i] - T[i - 1]) * f
        d = t - ref
        return d if -60 < d < 60 else None

    # ------------------------------------------------------------------ recording (10 Hz)
    def tick(self, b):
        now = time.time()
        if now - self._t < 0.1:
            return
        self._t = now
        try:
            self._tick(b, now)
            if self._pending:
                self._apply_pending()
        except Exception as e:
            self.log(f"[laps] {e!r}")

    def _tick(self, b, now):
        g = b.g
        wi = b.info("WeekendInfo", {}) or {}
        key = f"{wi.get('SubSessionID', 0)}:{g('SessionNum', 0)}:{wi.get('TrackName', '')}"
        if key != self.key:
            if self.key is not None:
                self.save(force=True)
            self.key = key
            self.laps, self.cur, self.lap_no, self.best_no = [], None, None, None
            self.restore()
        self.met = bool(b.metric()) if hasattr(b, "metric") else False
        replay = bool(g("IsReplayPlaying", False))
        lap = (g("LapCompleted", 0) or 0) + 1
        pct, cur, last = _f(g("LapDistPct")), _f(g("LapCurrentLapTime")), _f(g("LapLastLapTime"))
        if replay:
            # replays: the player's own lap numbers / distance come from the per-car arrays; the lap clock is ours
            me = b.me()
            lc_a, pc_a = g("CarIdxLapCompleted") or [], g("CarIdxLapDistPct") or []
            if me is not None and me < len(lc_a) and lc_a[me] is not None and lc_a[me] >= 0:
                lap = int(lc_a[me]) + 1
            if me is not None and me < len(pc_a) and _f(pc_a[me]) is not None and pc_a[me] >= 0:
                pct = _f(pc_a[me])
            st = _f(g("SessionTime"))
            if st is not None:
                if self.lap_no != lap or getattr(self, "_lap_t0", None) is None:
                    self._lap_t0 = st - (cur if cur and cur > 0 else 0)
                if not cur or cur <= 0:
                    cur = st - self._lap_t0
        self.live = {"lap": lap, "pct": pct, "cur": cur, "replay": replay}
        spd = (_f(g("Speed")) or 0) * (3.6 if self.met else 2.23694)
        thr, brk = _f(g("Throttle")) or 0, _f(g("Brake")) or 0
        gapped = self._last_wall and now - self._last_wall > 2.5
        self._last_wall = now
        if self.lap_no != lap:
            d = self.cur
            if (d and last and last > 0 and d["clean"] and d["start"] is not None and d["start"] < 0.06
                    and len(d["p"]) > 50 and d["p"][-1] > 0.94):
                d["time"] = round(last, 3)
                if d["sec"][0] and d["sec"][1]:
                    d["sec"][2] = round(last - d["sec"][1], 3)
                d.pop("start", None)
                self.laps = [l for l in self.laps if l.get("no") != d["no"]]   # a replay rewound over it: the new one wins
                self.laps.insert(0, d)
                self.laps.sort(key=lambda l: -(l.get("no") or 0))
                del self.laps[KEEP:]
                best = min((l for l in self.laps if l.get("time")), key=lambda l: l["time"], default=None)
                self.best_no = best["no"] if best else None
                self._dirty = True
                self.save(force=True)
            self.cur, self.lap_no = _new(lap), lap
        c = self.cur
        if g("OnPitRoad", False) or (not replay and not g("IsOnTrack", False)) or gapped:
            c["clean"] = False
        try:                     # 2026-10-26: the formation / parade lap (a race before the green) is never a lap
            if "race" in str(getattr(b, "sess_type", "") or "").lower() and 0 < int(g("SessionState", 0) or 0) < 4:
                c["clean"] = False
        except (TypeError, ValueError):
            pass
        if pct is None or cur is None:
            return
        if c["start"] is None:
            c["start"] = pct
        lastp = c["p"][-1] if c["p"] else -1
        if pct < lastp - 0.5 or pct <= lastp or len(c["p"]) >= MAX_PTS:
            return
        for k in range(2):
            if not c["sec"][k] and 0 <= lastp < SECS[k] <= pct:
                tl = c["t"][-1]
                f = (SECS[k] - lastp) / ((pct - lastp) or 1)
                c["sec"][k] = round(tl + (cur - tl) * f, 3)       # cumulative, like the iPad
        c["p"].append(round(pct, 5)); c["s"].append(round(spd, 1)); c["th"].append(round(thr, 3))
        c["br"].append(round(brk, 3)); c["t"].append(round(cur, 3))
        c.setdefault("st", []).append(round(_f(g("SteeringWheelAngle")) or 0, 3))      # 2026-10-26: steering + gear for the
        c.setdefault("gr", []).append(int(g("Gear", 0) or 0))                          # iPad lap analysis
        self._dirty = True
        self.save()

    # ------------------------------------------------------------------ disk
    def save(self, force=False):
        now = time.time()
        if not self._dirty or (not force and now - self._save_t < 15) or not self.key:
            return
        self._save_t = now; self._dirty = False
        try:
            tmp = PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"key": self.key, "laps": self.laps, "cur": self.cur, "lap_no": self.lap_no, "best_no": self.best_no,
                           "saved": now}, f, separators=(",", ":"))
            os.replace(tmp, PATH)
            # the session's own file too (the cache), and trim the oldest
            os.makedirs(DIR, exist_ok=True)
            mine = os.path.join(DIR, self._fname(self.key))
            tmp2 = mine + ".tmp"
            with open(tmp2, "w", encoding="utf-8") as f:
                json.dump({"key": self.key, "laps": self.laps, "best_no": self.best_no, "saved": now}, f, separators=(",", ":"))
            os.replace(tmp2, mine)
            files = sorted((os.path.join(DIR, n) for n in os.listdir(DIR) if n.endswith(".json")), key=os.path.getmtime, reverse=True)
            for old in files[KEEP_SESSIONS:]:
                try:
                    os.remove(old)
                except OSError:
                    pass
        except OSError:
            pass

    @staticmethod
    def _fname(key):
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(key))[:120] + ".json"

    def restore(self):
        try:
            d = json.load(open(PATH, encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        if d.get("key") != self.key:
            # not the last session: this session's own cached file, if we've been here before
            try:
                d = json.load(open(os.path.join(DIR, self._fname(self.key)), encoding="utf-8"))
            except (OSError, ValueError):
                return
            if d.get("key") != self.key:
                return
            d["cur"], d["lap_no"] = None, None
        self.laps = d.get("laps") or []
        self.best_no = d.get("best_no")
        try:                     # 2026-10-27: laps rebuilt from a recording may sit in the session's cache file
            with open(os.path.join(DIR, self._fname(self.key)), encoding="utf-8") as f:
                c = json.load(f)
            if c.get("key") == self.key:
                have = {l.get("no") for l in self.laps}
                more = [l for l in c.get("laps") or [] if l.get("no") not in have]
                if more:
                    self.laps = sorted(self.laps + more, key=lambda l: -(l.get("no") or 0))[:KEEP]
                    best = min((l for l in self.laps if l.get("time") and l.get("clean", True)), key=lambda l: l["time"], default=None)
                    self.best_no = best["no"] if best else self.best_no
        except (OSError, ValueError, AttributeError):
            pass
        # the lap that was in progress can't be finished cleanly (we missed part of it): keep it as dirty
        self.cur, self.lap_no = d.get("cur"), d.get("lap_no")
        if self.cur:
            self.cur["clean"] = False
        self.log(f"[laps] picked up {len(self.laps)} laps from before the restart")

    # ------------------------------------------------------------------ laps rebuilt from a recording (2026-10-27)
    def merge(self, key, laps, ended=None):
        """Add laps rebuilt from a recording to session `key` (live laps already there win). -> laps added."""
        if not laps:
            return 0
        n = merge_file(key, laps, ended=ended, log=self.log)     # on disk now, even if no tick ever comes
        if key == self.key:
            self._pending.append((key, laps))     # applied by the engine's own tick (no two threads on self.laps)
        return n

    def _apply_pending(self):
        while self._pending:
            key, laps = self._pending.pop(0)
            if key != self.key:
                continue                          # already in that session's file
            have = {l.get("no") for l in self.laps}
            add = [l for l in laps if l.get("no") not in have]
            if add:
                self.laps = sorted(self.laps + add, key=lambda l: -(l.get("no") or 0))[:KEEP]
                best = min((l for l in self.laps if l.get("time") and l.get("clean", True)), key=lambda l: l["time"], default=None)
                self.best_no = best["no"] if best else None
                self._dirty = True
                self.save(force=True)
                self.log(f"[laps] {len(add)} laps added from the recording")

    # ------------------------------------------------------------------ for the iPad
    def payload(self):
        return {"key": self.key, "laps": self.laps, "best_no": self.best_no, "cur": self.cur, "lap_no": self.lap_no, "met": self.met}


# ---------------------------------------------------------------------- rebuilding laps from a recording (2026-10-27)
def laps_from_session(se, hz=10):
    """telemetry.Session -> {key: [laps in this store's format]} (one key per session in the file). Only complete laps
    off pit road; speed in the units iRacing showed (DisplayUnits), like the live store."""
    import numpy as np
    from .telemetry import read_ibt
    d = se.d
    wk = (se.info or {}).get("WeekendInfo", {}) or {}
    sub = wk.get("SubSessionID", 0)
    try:
        du = read_ibt(se.path, channels=["DisplayUnits"])[0].get("DisplayUnits") if not str(se.path).endswith(".renpz") else None
        met = bool(du is not None and len(du) and int(np.median(du)) == 1)
    except Exception:
        met = False
    k = 3.6 if met else 2.23694
    step = max(1, int(round((se.tick or 60) / hz)))
    sn = d.get("SessionNum")
    out = {}
    for L in se.laps:
        if not L["complete"] or L["pit"]:
            continue
        a, b = L["a"], L["b"]
        idx = np.arange(a, b, step)
        pct = d["LapDistPct"][idx]
        t = d["SessionTime"][idx] - d["SessionTime"][a]
        keep = np.concatenate([[True], np.diff(pct) > 0])            # strictly increasing, like the live store
        idx, pct, t = idx[keep], pct[keep], t[keep]
        if len(idx) < 50:
            continue
        g = lambda ch, dflt=0.0: d[ch][idx] if ch in d else np.full(len(idx), dflt)
        lap = {"no": int(L["n"]), "p": [round(float(x), 5) for x in pct], "s": [round(float(x) * k, 1) for x in g("Speed")],
               "th": [round(float(x), 3) for x in g("Throttle")], "br": [round(float(x), 3) for x in g("Brake")],
               "t": [round(float(x), 3) for x in t], "st": [round(float(x), 3) for x in g("SteeringWheelAngle")],
               "gr": [int(x) for x in g("Gear")], "sec": [None, None, None], "clean": bool(L["valid"]),
               "time": round(float(L["time"]), 3), "src": "recording", "met": met}
        for j, f in enumerate(SECS):
            lap["sec"][j] = round(float(np.interp(f, pct, t)), 3) if pct[0] <= f <= pct[-1] else None
        if lap["sec"][1]:
            lap["sec"][2] = round(lap["time"] - lap["sec"][1], 3)
        s_no = int(sn[a]) if sn is not None else 0
        out.setdefault(f"{sub}:{s_no}:{se.track_name}", []).append(lap)
    return out


def merge_file(key, laps, ended=None, log=print):
    """Merge rebuilt laps into session key's cache file. A test / offline session has subsession 0, so the same key
    comes back every time you drive there: a cache older than this recording by more than a few hours is replaced."""
    p = os.path.join(DIR, LapStore._fname(key))
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("key") != key:
            d = {}
    except (OSError, ValueError):
        d = {}
    if str(key).startswith("0:") and ended and d.get("saved") and d["saved"] < ended - 6 * 3600:
        d = {}
    have = {l.get("no") for l in d.get("laps") or []}
    add = [l for l in laps if l.get("no") not in have]
    if not add:
        return 0
    allp = sorted((d.get("laps") or []) + add, key=lambda l: -(l.get("no") or 0))[:KEEP]
    best = min((l for l in allp if l.get("time") and l.get("clean", True)), key=lambda l: l["time"], default=None)
    os.makedirs(DIR, exist_ok=True)
    tmp = f"{p}.{os.getpid()}.merge.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"key": key, "laps": allp, "best_no": best["no"] if best else None, "saved": time.time()}, f, separators=(",", ":"))
    os.replace(tmp, p)
    log(f"[laps] {len(add)} laps from the recording kept for {key}")
    return len(add)
