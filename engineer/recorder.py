"""The engineer's own telemetry recorder (2026-10-26).

Requested: "Analysis is not showing anything - can it take the data from the replay race?" and "we won't be using Garage 61
anymore, we will have to make our own way to do that based off our times only". iRacing's .ibt files were being deleted
by the Garage 61 agent, and iRacing writes none while you watch a replay. So the engineer records for itself:

  * reads iRacing's live data at the sim's own 60 Hz (its own SDK connection, a thread of its own - never the engine's)
  * records while you drive, and while a replay plays at normal speed (your car's channels, checked against the car's
    position so a camera on someone else never gets written as yours)
  * a replay has no GPS position: the track position comes from the app's cached track map, so the Analysis map works
  * one file per stint, saved next to the kept .ibt copies: <car>_<track> <date time>.renpz - the same channels and
    session information as an .ibt, so Analysis, the Series tab and the strategy memory read it exactly like one
  * when iRacing itself wrote an .ibt for the same drive, ours is dropped (no doubles)
"""
import json, math, os, threading, time
from array import array
import numpy as np

from .telemetry import CHANNELS, CACHE_DIR, TELEMETRY_DIR, archive_dir, fallback_dir

EXT = ".renpz"
MIN_SECONDS = 75            # shorter than this can't hold a lap: not kept


def recordings_dir():
    return archive_dir()    # same folder as the kept .ibt copies (E:\RaceEngineer\telemetry on the developer's PC)


class Recorder:
    def __init__(self, log=print):
        self.log = log
        self.alive = True
        self.status = "idle"
        self._map = {}
        threading.Thread(target=self._run, daemon=True, name="recorder").start()

    # ------------------------------------------------------------ track position for replays (no GPS there)
    def _track_xy(self, track):
        if track in self._map:
            return self._map[track]
        m = None
        try:
            with open(os.path.join(CACHE_DIR, "maps", f"{track}.json".replace(" ", "_")), encoding="utf-8") as f:
                m = json.load(f)
            m = (np.asarray(m["d"], float), np.asarray(m["x"], float), np.asarray(m["y"], float))
        except Exception:
            m = None
        self._map[track] = m
        return m

    # ------------------------------------------------------------ main loop
    def _run(self):
        try:
            import irsdk
        except Exception as e:
            self.log(f"[recorder] no iRacing SDK: {e!r}")
            return
        self._recover()
        ir = irsdk.IRSDK()
        cur = None                       # the stint being recorded
        idle_since = None
        while self.alive:
            try:
                if not (ir.is_initialized and ir.is_connected):
                    if cur:
                        self._save(cur); cur = None
                    ir.shutdown()
                    if not ir.startup():
                        time.sleep(2.0); continue
                ir.freeze_var_buffer_latest()
                tick = ir["SessionTick"]
                if cur is not None and tick == cur["last_tick"]:
                    ir.unfreeze_var_buffer_latest(); time.sleep(0.004); continue
                want, src = self._want(ir)
                if want:
                    st = ir["SessionTime"] or 0.0
                    if cur is not None and (src != cur["src"] or st < cur["last_t"] - 0.05 or st - cur["last_t"] > 3.0
                                            or ir["SessionNum"] != cur["sess"]):
                        self._save(cur); cur = None          # rewound, jumped, switched source or session
                    if cur is None:
                        cur = self._begin(ir, src)
                    self._sample(ir, cur)
                    cur["last_tick"], cur["last_t"] = tick, st
                    if cur["n"] - cur.get("saved_n", 0) >= 120 * 60:     # every 2 min: saved so far (a restart loses little)
                        cur["saved_n"] = cur["n"]
                        self._checkpoint(cur)
                    idle_since = None
                else:
                    if cur is not None:
                        idle_since = idle_since or time.time()
                        if time.time() - idle_since > 3.0:
                            self._save(cur); cur = None; idle_since = None
                ir.unfreeze_var_buffer_latest()
                # 2026-10-29 (efficiency): nothing to record (the usual case while you drive - iRacing writes its own file -
                # and in menus): look 10 times a second instead of at every one of the sim's 60 updates
                time.sleep(0.008 if cur is not None else 0.1)
            except Exception as e:
                self.log(f"[recorder] {e!r}")
                try:
                    ir.unfreeze_var_buffer_latest()
                except Exception:
                    pass
                time.sleep(1.0)
        if cur:
            self._save(cur)

    @staticmethod
    def _want(ir):
        """Live: you're in the car on track. Replay: playing at normal speed and the player's channels are the player's."""
        if ir["IsReplayPlaying"]:
            if ir["ReplayPlaySpeed"] != 1 or ir["ReplayPlaySlowMotion"]:
                return False, "replay"
            me = ir["PlayerCarIdx"]
            pct, arr = ir["LapDistPct"], ir["CarIdxLapDistPct"]
            if me is None or pct is None or not arr or me >= len(arr) or arr[me] is None or arr[me] < 0:
                return False, "replay"
            gap = abs(pct - arr[me]); gap = min(gap, 1 - gap)
            return gap < 0.003 and (ir["Speed"] or 0) > 1.0, "replay"
        # 2026-10-27 (#451, request: radio + crowd chopping in the race - "do whatever it takes"): while you drive and iRacing
        # writes its own telemetry file (always kept by the vault), no second copy - it was thrown away at the end anyway,
        # and its 2-minute checkpoints copied the whole growing recording. Replays are still recorded (iRacing writes none).
        try:
            if ir["IsDiskLoggingEnabled"]:
                return False, "live"
        except Exception:
            pass
        return bool(ir["IsOnTrack"]), "live"

    def _begin(self, ir, src):
        wk = ir["WeekendInfo"] or {}
        di = ir["DriverInfo"] or {}
        me = next((d for d in (di.get("Drivers") or []) if d.get("CarIdx") == di.get("DriverCarIdx")), {})
        si = ""
        try:
            raw = ir._shared_mem[ir._header.session_info_offset: ir._header.session_info_offset + ir._header.session_info_len]
            si = bytes(raw).rstrip(b"\x00").decode("cp1252", "replace")
        except Exception:
            si = ""
        if "WeekendInfo" not in si:
            try:
                import yaml
                si = yaml.safe_dump({k: ir[k] for k in ("WeekendInfo", "SessionInfo", "DriverInfo", "SplitTimeInfo", "CarSetup") if ir[k]},
                                    allow_unicode=False, sort_keys=False)
            except Exception as e:
                self.log(f"[recorder] session info: {e!r}")
        self.status = f"recording ({src})"
        self.log(f"[recorder] recording your {'replay' if src == 'replay' else 'drive'} at {wk.get('TrackDisplayName', '?')}")
        car = (me.get("CarPath") or "car").replace("_", "-")
        path = os.path.join(recordings_dir(), f"{car}_{wk.get('TrackName', '') or ''} {time.strftime('%Y-%m-%d %H-%M-%S')}{EXT}")
        return {"src": src, "sess": ir["SessionNum"], "t0": time.time(), "si": si, "track": wk.get("TrackName", "") or "", "path": path, "done": [False],
                "car": (me.get("CarPath") or "car").replace("_", "-"),
                "cols": {c: array("d" if c in ("SessionTime", "Lat", "Lon", "SessionTimeRemain") else "f") for c in CHANNELS},
                "last_tick": None, "last_t": -1.0, "n": 0, "wall0": time.localtime()}

    def _sample(self, ir, cur):
        cols = cur["cols"]
        for c in CHANNELS:
            try:
                v = ir[c]
            except Exception:
                v = None
            cols[c].append(float("nan") if v is None or isinstance(v, (list, tuple, dict, str)) else float(v))
        cur["n"] += 1

    # ------------------------------------------------------------ checkpoints (#537)
    # 2026-10-29 (#537, Angelo 10-27: "we have long races ... need it optimized for not causing performance issues"):
    # every 2 minutes only the NEW part is written (a small uncompressed piece, <recording>.ck000, .ck001 ...) instead of
    # compressing the whole growing recording again. The finished recording is written once at the end and the pieces
    # are removed; after a crash the pieces are joined into a recording the next time the engineer starts.
    def _checkpoint(self, cur):
        i0, n = cur.get("ck_n", 0), cur["n"]
        if n - i0 < 60 or not cur.get("path"):
            return
        k = cur.get("ck_k", 0)
        cur["ck_k"], cur["ck_n"] = k + 1, n
        part = {}
        for c, v in cur["cols"].items():
            a = np.frombuffer(v, dtype=np.float64 if v.typecode == "d" else np.float32)[i0:n].copy()
            part[c] = a
        meta = {"_src": np.array(cur["src"]), "_track": np.array(cur["track"]), "_car": np.array(cur["car"]),
                "_t0": np.array(cur["t0"]), "_wall0": np.array(time.mktime(cur["wall0"]))}
        if k == 0:
            meta["_si"] = np.array(cur["si"])
        path = cur["path"] + f".ck{k:03d}"

        def write():
            try:
                if cur.get("done", [False])[0]:
                    return                                          # the finished recording is already written
                with open(path + ".tmp", "wb") as f:
                    np.savez(f, **part, **meta)
                os.replace(path + ".tmp", path)
            except Exception as e:
                self.log(f"[recorder] checkpoint: {e!r}")
        threading.Thread(target=write, daemon=True, name="recorder-ck").start()

    @staticmethod
    def _drop_pieces(path):
        import glob
        for f in glob.glob(glob.escape(path) + ".ck*"):
            try:
                os.remove(f)
            except OSError:
                pass

    def _recover(self):
        """Pieces left by a crash -> one recording (only when no finished recording exists for them)."""
        import glob
        for d in {recordings_dir(), fallback_dir()}:
            try:
                firsts = glob.glob(os.path.join(glob.escape(d), "*" + EXT + ".ck000"))
            except Exception:
                continue
            for f0 in firsts:
                base = f0[:-len(".ck000")]
                try:
                    if os.path.exists(base):
                        self._drop_pieces(base); continue
                    pieces = sorted(glob.glob(glob.escape(base) + ".ck[0-9][0-9][0-9]"))
                    zs = [np.load(p, allow_pickle=False) for p in pieces]
                    z0 = zs[0]
                    cols = {}
                    for c in [k for k in z0.files if not k.startswith("_")]:
                        a = np.concatenate([z[c] for z in zs if c in z.files])
                        cols[c] = array("d" if a.dtype == np.float64 else "f", a.tobytes())
                    n = len(next(iter(cols.values()))) if cols else 0
                    cur = {"src": str(z0["_src"]), "track": str(z0["_track"]), "car": str(z0["_car"]), "si": str(z0["_si"]) if "_si" in z0.files else "",
                           "t0": float(z0["_t0"]), "wall0": time.localtime(float(z0["_wall0"])), "path": base, "cols": cols, "n": n, "done": [False]}
                    self.log(f"[recorder] joining {len(pieces)} pieces left by a crash: {os.path.basename(base)}")
                    self._save(cur)
                    self._drop_pieces(base)
                except Exception as e:
                    self.log(f"[recorder] recover {os.path.basename(base)}: {e!r}")

    # ------------------------------------------------------------ saving
    def _save(self, cur, final=True):
        if final:
            self.status = "idle"
            cur.setdefault("done", [False])[0] = True              # a checkpoint still writing must not overwrite this
        orig = cur.get("path")
        n = cur["n"]
        if n < MIN_SECONDS * 60:
            if final and cur.get("path"):
                self._drop_pieces(cur["path"])
            return
        try:
            out = {}
            for c, vals in cur["cols"].items():
                a = np.frombuffer(vals, dtype=np.float64 if vals.typecode == "d" else np.float32).astype(np.float64)
                if np.all(np.isnan(a)):
                    continue
                out[c] = a
            if cur["src"] == "replay":
                out["IsOnTrack"] = np.ones(n)                       # iRacing says "not on track" while you watch
                m = self._track_xy(cur["track"])
                if m is not None and "LapDist" in out and ("Lat" not in out or np.all(np.isnan(out.get("Lat")))):
                    d, x, y = m
                    ld = np.nan_to_num(out["LapDist"]) % max(1.0, float(d[-1]))
                    xx, yy = np.interp(ld, d, x), np.interp(ld, d, y)
                    R = 6371000.0
                    out["Lat"] = yy / R * 180 / math.pi
                    out["Lon"] = xx / R * 180 / math.pi
            # iRacing wrote its own file for this drive? keep that one (it's copied by the archive), drop ours
            if cur["src"] == "live" and final:
                key = f"{cur['car'].replace('-', '_')}_{cur['track']}".lower()
                for f in os.listdir(TELEMETRY_DIR) if os.path.isdir(TELEMETRY_DIR) else []:
                    p = os.path.join(TELEMETRY_DIR, f)
                    if f.lower().startswith(key) and f.endswith(".ibt") and os.path.getmtime(p) > cur["t0"] - 60:
                        self.log("[recorder] iRacing recorded this drive itself - using its file")
                        if cur.get("path") and os.path.exists(cur["path"]):
                            os.remove(cur["path"])                   # our checkpoint of the same drive
                        if cur.get("path"):
                            self._drop_pieces(cur["path"])
                        return
            ints = {"SessionNum", "Lap", "Gear", "PlayerTrackSurface", "PlayerCarMyIncidentCount", "PitSvFlags"}
            bools = {"BrakeABSactive", "OnPitRoad", "IsOnTrack"}
            arrs = {}
            for c, a in out.items():
                a = np.nan_to_num(a)
                arrs[c] = a.astype(np.int32) if c in ints else a.astype(bool) if c in bools else a.astype(np.float32 if c not in ("SessionTime", "Lat", "Lon") else np.float64)
            arrs["_si"] = np.array(cur["si"])
            arrs["_tick"] = np.array(60)
            arrs["_src"] = np.array(cur["src"])                 # "live" / "replay" (telemetry.recording_meta reads these)
            # 2026-10-27 (#344): where Lat/Lon came from - "gps" (iRacing's own) or "map" (made from the cached track
            # map: metres around (0, 0), replays have no GPS). Analysis must never treat "map" positions as a real line.
            arrs["_pos"] = np.array("map" if cur["src"] == "replay" else "gps")
            d = recordings_dir()
            stamp = time.strftime("%Y-%m-%d %H-%M-%S", cur["wall0"])
            path = cur.get("path") or os.path.join(d, f"{cur['car']}_{cur['track']} {stamp}{EXT}")
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                part = path + (".part" if final else ".ck")
                with open(part, "wb") as f:
                    np.savez_compressed(f, **arrs)
            except OSError as e:
                # 2026-10-27 (#359): the archive drive (external E:) went away mid-session - never lose the drive:
                # write to the system drive instead; the vault moves it across when E: is back
                fb = fallback_dir()
                self.log(f"[recorder] archive folder not writable ({e.__class__.__name__}) - saving to {fb}")
                os.makedirs(fb, exist_ok=True)
                path = os.path.join(fb, os.path.basename(path))
                part = path + (".part" if final else ".ck")
                with open(part, "wb") as f:
                    np.savez_compressed(f, **arrs)
            cur["path"] = path
            if not final and cur.get("done", [False])[0]:
                os.remove(part); return
            os.replace(part, path)
            if final:
                for q in {orig, path} - {None}:
                    self._drop_pieces(q)
                self.log(f"[recorder] saved {n / 60 / 60:.1f} min of your {'replay' if cur['src'] == 'replay' else 'drive'}: {os.path.basename(path)}")
        except Exception as e:
            self.log(f"[recorder] save: {e!r}")


def read_renpz(path):
    """-> (data dict, session-info yaml text, tick) - the same shape telemetry.read_ibt returns."""
    z = np.load(path, allow_pickle=False)
    data = {}
    for k in z.files:
        if k.startswith("_"):
            continue
        a = z[k]
        data[k] = a.astype(np.float64) if a.dtype.kind == "f" else a.astype(np.int64) if a.dtype.kind in "iu" else a.astype(bool)
    return data, str(z["_si"]), int(z["_tick"])
