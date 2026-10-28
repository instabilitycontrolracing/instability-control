"""Notes the driver says on the radio, tagged with where and when they were said."""
import json, os, time
from datetime import datetime

DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RaceEngineer")
PATH = os.path.join(DIR, "driver_notes.jsonl")


def add(text, track="", car="", session="", lap=None, lap_dist=None, corner=None):
    os.makedirs(DIR, exist_ok=True)
    row = {"time": time.time(), "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "text": text, "track": track,
           "car": car, "session": session, "lap": lap, "dist": lap_dist, "corner": corner}
    with open(PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def for_session(track, start_ts, end_ts):
    """Notes said on this track between the telemetry file's start and end."""
    out = []
    try:
        for line in open(PATH, encoding="utf-8"):
            r = json.loads(line)
            if r.get("track") == track and start_ts - 120 <= r["time"] <= end_ts + 120:
                out.append(r)
    except OSError:
        pass
    return out
