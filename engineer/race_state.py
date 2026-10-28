"""The engineer's memory of the race in progress, kept across an app restart (2026-10-25, request: "for every piece of
data we should keep like that, like how it manages to keep the session time remaining after a restart").

iRacing only sends what is true right now. What the engineer has worked out himself - your lap times and fuel per lap,
where you started, which minute / lap calls he has already made, the last-lap state, what pit stops are costing in this
race - lives in memory, so a restart used to wipe it. It's written to engineer_race_state.json every few seconds during a
session and read back when the app comes up in the same session. A replay rewound to before the save is ignored.
"""
import json, os, time

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engineer_race_state.json")
PREV_KEYS = ("last_lap_said", "last_lap_lc", "white_lc", "expired_leader_lc", "race_total_laps")
_last_save = 0.0


def _key(b):
    wi = b.info("WeekendInfo", {}) or {}
    return f"{wi.get('SubSessionID', 0)}:{b.sess_num}:{wi.get('TrackName', '')}"


def _my_lc(b):
    try:
        return int(b.g("LapCompleted", 0) or 0)
    except Exception:
        return 0


def snapshot(b):
    pw = getattr(b, "pitwatch", None)
    return {
        "key": _key(b), "saved": time.time(), "lc": _my_lc(b),
        "start_pos": b.start_pos, "green_seen": b.green_seen, "since_green": (b.clock() - b.green_t) if b.green_seen else None,
        "finished": b.finished, "lap_times": list(b.lap_times)[-30:], "fuel_laps": list(b.fuel_laps)[-30:], "best": b.best,
        "tl_count": b.tl_count, "minutes_announced": sorted(b.minutes_announced), "laps_announced": sorted(b.laps_announced),
        "half_said": b.half_said, "finish_p_line": getattr(b, "finish_p_line", 0),
        "prev": {k: b.prev[k] for k in PREV_KEYS if k in b.prev},
        "pit_losses": list(pw.losses) if pw else [], "cycle_said": sorted(pw.cycle_said) if pw else [],
    }


def maybe_save(b, every=5.0):
    """Called every tick: writes the state every few seconds once a session is known."""
    global _last_save
    now = time.time()
    if b.sess_num is None or now - _last_save < every:
        return
    if not (b.info("WeekendInfo", {}) or {}).get("TrackName"):      # not connected to a session: keep what's saved
        return
    _last_save = now
    try:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot(b), f)
        os.replace(tmp, PATH)
    except Exception as e:
        if b.once_log("race_state_save", e):
            b.log(f"[race state] save failed: {e!r}")


def restore(b):
    """Called once when a session starts: pick the race back up if the saved state is for this session."""
    try:
        if not os.path.exists(PATH):
            return False
        s = json.load(open(PATH, encoding="utf-8"))
        if s.get("key") != _key(b):
            return False
        if _my_lc(b) < int(s.get("lc", 0)) - 1:          # a replay rewound to before the save
            b.log("[race state] saved state is from later in this replay - starting fresh")
            return False
        b.start_pos = s.get("start_pos")
        if s.get("green_seen"):
            b.green_seen = True
            b.green_t = b.clock() - float(s.get("since_green") or 0)
        b.finished = bool(s.get("finished"))
        b.lap_times = list(s.get("lap_times") or [])
        b.fuel_laps = list(s.get("fuel_laps") or [])
        b.best = s.get("best")
        b.tl_count = int(s.get("tl_count") or 0)
        b.minutes_announced = set(s.get("minutes_announced") or [])
        b.laps_announced = set(s.get("laps_announced") or [])
        b.half_said = bool(s.get("half_said"))
        b.finish_p_line = s.get("finish_p_line", 0)
        for k, v in (s.get("prev") or {}).items():
            b.prev[k] = v
        pw = getattr(b, "pitwatch", None)
        if pw:
            pw.losses = list(s.get("pit_losses") or [])
            pw.cycle_said = set(s.get("cycle_said") or [])
        b.log(f"[race state] picked up this session where it left off: {len(b.lap_times)} laps timed, "
              f"best {b.best}, calls made {sorted(b.minutes_announced)}")
        return True
    except Exception as e:
        b.log(f"[race state] couldn't read the saved state: {e!r}")
        return False
