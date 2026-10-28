"""Your in-car settings during a replay (2026-10-28, #490, Angelo: "on the dash for the iPad it doesn't actually show
the data from the car, it just shows zeros all the time").

While you drive, iRacing sends the car's in-car settings (brake bias, TC, ABS, roll bars ... the dc* values). A replay
doesn't play them back: they read 0. But iRacing saved them in that race's telemetry file (.ibt) while you drove. So when
the replay is of a session you drove, this finds the matching .ibt (same SubSessionID, your car) and plays the settings
back in step with the replay clock (SessionNum + SessionTime). No matching file, or a moment you weren't in the car ->
None (the iPad shows a dash, never a made-up 0).

The search and the file reading run once per replay on a background thread; a lookup is a binary search.
"""
import os
import re
import struct
import threading

import numpy as np

from . import telemetry

DC = ["dcBrakeBias", "dcAntiRollFront", "dcAntiRollRear", "dcTractionControl", "dcTractionControl2", "dcABS",
      "dcBrakeMisc", "dcThrottleShape"]
_SI_CACHE = {}          # path -> (size, mtime, SubSessionID, DriverUserID)


def _ids(path):
    """(SubSessionID, DriverUserID) from a recording's session info, reading only the header (cached)."""
    try:
        st = os.stat(path)
    except OSError:
        return None, None
    hit = _SI_CACHE.get(path)
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime:
        return hit[2], hit[3]
    sid = uid = None
    try:
        with open(path, "rb") as f:
            head = f.read(144)
            si_len, si_off = struct.unpack_from("<2i", head, 16)
            if 0 < si_len < 20_000_000:
                f.seek(si_off)
                si = f.read(si_len).decode("cp1252", "replace")
                m = re.search(r"SubSessionID:\s*(\d+)", si)
                sid = int(m.group(1)) if m else None
                m = re.search(r"DriverUserID:\s*(\d+)", si)
                uid = int(m.group(1)) if m else None
    except (OSError, struct.error):
        pass
    _SI_CACHE[path] = (st.st_size, st.st_mtime, sid, uid)
    return sid, uid


class ReplayDC:
    def __init__(self, log=print, sessions=None):
        self.log = log
        self._sessions = sessions or telemetry.list_sessions
        self._key = None
        self._data = None       # {"num": array, "t": array, ch: array} merged over the matching files, sorted by (num, t)
        self._busy = False

    def _load(self, key):
        sid, uid = key
        try:
            files = [s["path"] for s in self._sessions() if s["path"].lower().endswith(".ibt")]
            hits = [p for p in files if _ids(p) == (sid, uid)]
            parts = []
            for p in hits:
                d, _, _ = telemetry.read_ibt(p, channels=["SessionNum", "SessionTime", "IsOnTrack"] + DC)
                if "SessionTime" not in d or "SessionNum" not in d:
                    continue
                keep = d["IsOnTrack"].astype(bool) if "IsOnTrack" in d else np.ones(len(d["SessionTime"]), bool)
                step = np.zeros(len(keep), bool); step[::6] = True          # 10 a second is plenty
                keep &= step
                parts.append({k: v[keep] for k, v in d.items()})
            if parts:
                m = {k: np.concatenate([p[k] for p in parts if k in p]) for k in parts[0]}
                order = np.lexsort((m["SessionTime"], m["SessionNum"]))
                data = {k: v[order] for k, v in m.items()}
                if self._key == key:
                    self._data = data
                self.log(f"[replay dc] {len(hits)} recording(s) for subsession {sid}: settings play back with the replay")
            else:
                self.log(f"[replay dc] no recording of subsession {sid} with your car - the dash shows '-'")
        except Exception as e:
            self.log(f"[replay dc] {e!r}")
        finally:
            self._busy = False

    def values(self, b, g):
        """-> {dc name: value} for this moment of the replay, or None."""
        try:
            wi = b.info("WeekendInfo", {}) or {}
            di = b.info("DriverInfo", {}) or {}
            sid = int(wi.get("SubSessionID") or 0)
            uid = int(di.get("DriverUserID") or 0) or None
            if uid is None:
                me = di.get("DriverCarIdx")
                for d in di.get("Drivers", []) or []:
                    if d.get("CarIdx") == me:
                        uid = int(d.get("UserID") or 0) or None
            if not sid or not uid:
                return None
        except (TypeError, ValueError, AttributeError):
            return None
        key = (sid, uid)
        if key != self._key:
            self._key, self._data = key, None
            if not self._busy:
                self._busy = True
                threading.Thread(target=self._load, args=(key,), daemon=True).start()
            return None
        d = self._data
        if d is None:
            return None
        num, t = g("SessionNum"), g("SessionTime")
        if num is None or t is None:
            return None
        lo = np.searchsorted(d["SessionNum"], num, "left"); hi = np.searchsorted(d["SessionNum"], num, "right")
        if hi <= lo:
            return None
        ts = d["SessionTime"][lo:hi]
        i = int(np.searchsorted(ts, t))
        best = min((j for j in (i - 1, i) if 0 <= j < len(ts)), key=lambda j: abs(ts[j] - t), default=None)
        if best is None or abs(ts[best] - t) > 2.0:          # you weren't in the car then
            return None
        return {k: float(d[k][lo + best]) for k in DC if k in d}
