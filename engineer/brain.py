"""Race engineer brain: watches iRacing data and decides what to say and when.

src must offer src[var] for telemetry and src.info(section) for session info (pyirsdk-style).
"""
from . import classes
import os, random, time
from .voice import PRIO_SPOTTER, PRIO_URGENT, PRIO_RACE, PRIO_INFO, PRIO_CHAT

# iRacing SessionFlags bits
F_CHECKERED, F_WHITE, F_GREEN, F_YELLOW, F_RED, F_BLUE = 0x1, 0x2, 0x4, 0x8, 0x10, 0x20
F_YELLOW_WAVING, F_ONE_TO_GREEN, F_CAUTION, F_CAUTION_WAVING = 0x100, 0x200, 0x4000, 0x8000
F_BLACK, F_DQ, F_REPAIR = 0x10000, 0x20000, 0x100000
# CarLeftRight
LR_CLEAR, LR_LEFT, LR_RIGHT, LR_BOTH, LR_2LEFT, LR_2RIGHT = 1, 2, 3, 4, 5, 6
# track surface
TS_OFF, TS_STALL, TS_APPROACH, TS_ON = 0, 1, 2, 3


class Settings:
    spotter = True
    gaps = True
    gaps_every = 2          # laps between routine gap calls
    hold_in_corners = True  # keep non-urgent talk for the straights


class Brain:
    def __init__(self, src, voice, corners, settings=None, log=print, clock=time.time):
        self.src, self.v, self.c = src, voice, corners
        self.s = settings or Settings()
        self.log, self.clock = log, clock
        self._spin_t = None
        self.crowd_ev = []                            # crowd (2026-10-24): our spins / contact, drained by crowd.py
        self.reset_session()
        self.cool = {}
        self.track_loaded = None
        self.said_radio_check = False
        from .extras import Extras
        self.x = Extras(self)
        from .extras import RaceControl
        self.rc = RaceControl(self)
        from .racecraft import Racecraft              # DRE parity round 2 (2026-10-24)
        self.rcft = Racecraft(self)
        from .askmore import AskMore                  # Batch E: the rest of DRE's voice questions (2026-10-24)
        self.ask = AskMore(self)
        from .incar import InCar                      # in-car adjustments by voice + in-car coaching (2026-10-24)
        self.incar = InCar(self)
        self.strat = None                             # set by the app: the strategist (forecast answers)

    # ---------- helpers ----------
    # Replays (2026-10-24): iRacing leaves some of the driver's own values at zero in a replay, but records the
    # same thing per car. While a replay plays, these read the per-car version for our car instead.
    _RMAP = {"LapLastLapTime": "CarIdxLastLapTime", "LapBestLapTime": "CarIdxBestLapTime",
             "OnPitRoad": "CarIdxOnPitRoad", "Gear": "CarIdxGear", "PlayerCarClassPosition": "CarIdxClassPosition"}

    # 2026-10-27 (#404 / #405, request: the strategist said "5 laps in the car, we need 5" with 8 laps left; the
    # timer ran out 2-3 laps before the flag): in a timed race iRacing's live SessionTimeRemain counts from the start
    # of the race SESSION (grid + formation included), but the race clock only starts at the green. Last night's
    # Le Mans race: session 2700 s, green at 261 s, chequered at 3010 s - our timer and every "laps to go" were
    # ~4.4 min (1-2 laps) short. Once we've seen the green, the time left is worked out from the green instead.
    def _time_left(self, raw):
        gst = getattr(self, "_green_st", None)
        if gst is None:
            gst = self._green_st_load()
        if gst is None or not self.is_race() or (self.src["SessionState"] or 0) != 4:
            return raw
        try:
            total = self.src["SessionTimeTotal"]
            now = self.src["SessionTime"]
        except Exception:
            return raw
        if not total or total <= 0 or total > 86400 or now is None:
            return raw
        return max(0.0, float(total) - (float(now) - float(gst)))

    def _green_key(self):
        try:
            return f"{(self.info('WeekendInfo', {}) or {}).get('SubSessionID')}:{self.src['SessionNum']}"
        except Exception:
            return None

    def _green_st_save(self, st):
        self._green_st = st
        try:
            import json as _j
            from .telemetry import CACHE_DIR
            p = os.path.join(CACHE_DIR, "green_times.json")
            try:
                d = _j.load(open(p, encoding="utf-8"))
            except Exception:
                d = {}
            d[self._green_key()] = st
            d = dict(list(d.items())[-50:])
            _j.dump(d, open(p, "w", encoding="utf-8"))
        except Exception:
            pass

    def _green_st_load(self):
        """After an app restart mid-race: the green time we saved for this race (None if we never saw it)."""
        key = self._green_key()
        if getattr(self, "_green_loaded", None) == key:
            return None
        self._green_loaded = key
        try:
            import json as _j
            from .telemetry import CACHE_DIR
            v = _j.load(open(os.path.join(CACHE_DIR, "green_times.json"), encoding="utf-8")).get(key)
            if v is not None:
                self._green_st = float(v)
                return self._green_st
        except Exception:
            pass
        return None

    def g(self, k, d=None):
        if k == "SessionTimeRemain":
            try:
                raw = self.src[k]
            except Exception:
                return d
            if raw is None:
                return d
            return self._time_left(raw)
        try:
            if getattr(self, "_rp", False) and k in self._RMAP:
                arr = self.src[self._RMAP[k]]
                me = self.src["PlayerCarIdx"]
                x = arr[me] if arr is not None and me is not None and 0 <= me < len(arr) else None
            else:
                x = self.src[k]
            return d if x is None else x
        except Exception:
            return d

    def say(self, sid, fills=None, prio=PRIO_INFO, cooldown=0, key=None, max_age=None):
        key = key or sid
        now = self.clock()
        if cooldown and now - self.cool.get(key, -1e9) < cooldown:
            return False
        if not self.v.has(sid):
            return False
        from .voice import TOWING, tow_ok
        if TOWING and not tow_ok(sid):
            return False                     # 2026-10-29: no flags / passes / gaps while you're being towed back
        self.cool[key] = now
        self.v.say(sid, fills, prio, max_age=max_age)
        return True

    def once_log(self, key, e):
        """True the first time this kind of error shows up (keeps the log readable at 60 Hz)."""
        seen = self.__dict__.setdefault("_errs", set())
        k = (key, type(e).__name__, str(e)[:80])
        if k in seen:
            return False
        seen.add(k)
        return True

    def later(self, delay, fn):
        self.timers.append((self.clock() + delay, fn))

    def reset_session(self):
        self.sess_num = None
        self.sess_type = ""
        self.prev = {}
        self.timers = []
        self.lr_prev, self.lr_since, self.lr_still_said = LR_CLEAR, 0, False
        self.start_pos = None
        self.green_seen = False
        self.green_t = 0
        self._green_st = None; self._green_loaded = None   # #405: race clock start (SessionTime at the green)
        self.finished = False; self._fin_seen = None; self.finish_p_line = 0
        self.last_lap_done = -1
        self.lap_times = []
        self.fuel_at_line = None
        self.fuel_laps = []
        self.best = None
        self.inc = None
        self.tl_count = 0
        self.pos_pending = None
        self.pos_stable = None
        self.last_pit_time = -1e9
        self.gap_hist = []
        self.mc_seen = {}
        self.laps_announced = set()
        self.minutes_announced = set()
        self.half_said = False
        self.wet = None
        self.yellow_on = False
        self.caution_on = False
        self.ahead_pit_prev = {}
        from .pit_watch import PitWatch
        self.pitwatch = PitWatch(self)
        if getattr(self, "x", None):
            self.x.reset()

    # ---------- session facts ----------
    def info(self, sec, d=None):
        try:
            x = self.src.info(sec)
            return d if x is None else x
        except Exception:
            return d

    def me(self):
        return self.g("PlayerCarIdx", self.info("DriverInfo", {}).get("DriverCarIdx", 0))

    def drivers(self):
        # Efficiency (2026-10-29): called ~20 times a tick (class order, neighbours, timing, racecraft...). pyirsdk hands
        # back the same DriverInfo object until the session info really changes, so the table is built once per
        # DriverInfo and each caller gets its own shallow copy (callers may add to / pop from theirs).
        di = self.info("DriverInfo", {})
        c = getattr(self, "_drv_cache", None)
        if c is not None and c[0] is di:
            return dict(c[1])
        out = {}
        for d in di.get("Drivers", []) or []:
            if d.get("IsSpectator") or d.get("CarIsPaceCar"):
                continue
            out[d["CarIdx"]] = d
        if di:                                          # never cache the {} stand-in (a new one each call anyway)
            self._drv_cache = (di, out)
        return dict(out)

    def _tick_memo(self):
        """A dict that lives for one frozen iRacing snapshot (engine.IRacing's memo), or None when the source has none
        (tests, replays of recordings): answers worked out only from the snapshot are kept in it for the rest of the
        tick. 2026-10-29 (efficiency): neighbours() alone was asked ~1.5 times a tick, each a walk over the field."""
        m = getattr(self.src, "_memo", None)
        if not isinstance(m, dict):
            return None
        c = getattr(self, "_tm", None)
        if c is None or c[0] is not m:
            c = self._tm = (m, {})
        return c[1]

    def my_class(self):
        tm = self._tick_memo()
        if tm is not None:
            r = tm.get("my_class")
            if r is None:
                r = tm["my_class"] = self._my_class()
            return r
        return self._my_class()

    def _my_class(self):
        d = self.drivers().get(self.me(), {})
        return d.get("CarClassID"), d.get("CarClassShortName") or d.get("CarScreenNameShort", "")

    def is_gtp(self):
        """Modern GTP class (2026-10-29, car parity E11: known cars from the car table - the 1980s Nissan GTP ZX-T is
        not one; unknown cars by the old word match)."""
        from . import cars
        d = self.drivers().get(self.me(), {})
        t = f"{d.get('CarClassShortName', '')} {d.get('CarPath', '')} {d.get('CarScreenName', '')}".lower()
        return cars.is_gtp(d.get("CarPath"), d.get("CarID"), t)

    def is_hybrid(self):
        """GTP with a hybrid: deploy / regen / battery lines. The Valkyrie has no hybrid (iRacing's page)."""
        from . import cars
        d = self.drivers().get(self.me(), {})
        t = f"{d.get('CarClassShortName', '')} {d.get('CarPath', '')} {d.get('CarScreenName', '')}".lower()
        return cars.is_hybrid(d.get("CarPath"), d.get("CarID"), t)

    def is_electric(self):
        """The Porsche Mission R (car parity E15): no fuel, so no fuel calls."""
        from . import cars
        d = self.drivers().get(self.me(), {})
        return cars.is_electric(d.get("CarPath"), d.get("CarID"))

    def session(self):
        ss = self.info("SessionInfo", {}).get("Sessions", []) or []
        n = self.g("SessionNum", 0)
        for s in ss:
            if s.get("SessionNum") == n:
                return s
        return {}

    def track_len_m(self):
        t = str(self.info("WeekendInfo", {}).get("TrackLength", "5 km"))
        try:
            v = float(t.split()[0])
            return v * 1609.34 if "mi" in t else v * 1000
        except ValueError:
            return 5000

    def metric(self):
        return self.g("DisplayUnits", 0) == 1

    def is_race(self):
        return "race" in self.sess_type.lower()

    def is_quali(self):
        return "qual" in self.sess_type.lower()

    def alone(self):
        """Lone (solo) qualifying: the other cars on the timing screen aren't physically on track with
        you, so no traffic warnings and no spotter (2026-10-24, heard "watch for traffic" in lone qualy)."""
        return "lone" in self.sess_type.lower()

    def class_cars(self, class_id):
        return [i for i, d in self.drivers().items() if d.get("CarClassID") == class_id]

    def class_pos(self, idx):
        a = self.g("CarIdxClassPosition") or []
        return a[idx] if idx < len(a) else 0

    def f2(self, idx):
        a = self.g("CarIdxF2Time") or []
        return a[idx] if idx < len(a) else None

    def neighbours(self):
        """(car ahead idx, gap s, car behind idx, gap s) in my class, race order."""
        tm = self._tick_memo()
        if tm is not None:
            r = tm.get("neighbours")
            if r is None:
                r = tm["neighbours"] = self._neighbours()
            return r
        return self._neighbours()

    def _neighbours(self):
        me = self.me(); cid, _ = self.my_class(); mp = self.class_pos(me)
        if not mp:
            return None, None, None, None
        ahead = behind = None
        for i in self.class_cars(cid):
            p = self.class_pos(i)
            if p == mp - 1: ahead = i
            if p == mp + 1: behind = i
        mf = self.f2(me)
        ga = (mf - self.f2(ahead)) if ahead is not None and mf is not None and self.f2(ahead) is not None else None
        gb = (self.f2(behind) - mf) if behind is not None and mf is not None and self.f2(behind) is not None else None
        if ga is not None and ga <= 0: ga = None
        if gb is not None and gb <= 0: gb = None
        return ahead, ga, behind, gb

    def car_num(self, idx):
        return self.drivers().get(idx, {}).get("CarNumber")

    def corner_here(self):
        return self.c.at(self.g("LapDist", 0)) if self.c else None

    def laps_to_go(self):
        r = self.g("SessionLapsRemainEx", 32767)
        if r is not None and 0 <= r < 32000:
            return r
        t = self.g("SessionTimeRemain", -1)
        avg = self.pace_est()
        if t is not None and t > 0 and avg:
            return int(t / avg) + 1
        return None

    # ---------- what we know from earlier sessions (request 2026-10-23: "take my earlier performances into account") ----------
    def hist(self):
        """This car at this track from every stored session (strategy database), worked out once per session."""
        if getattr(self, "_hist_key", None) != self.sess_num:
            self._hist_key, self._hist = self.sess_num, {}
            try:
                from . import strategy as S
                d = self.drivers().get(self.me(), {}) or {}
                car, track = d.get("CarPath"), (self.info("WeekendInfo", {}) or {}).get("TrackName")
                if car and track:
                    self._hist = S.model(car, track) or {}
                    if self._hist.get("n"):
                        self.log(f"[brain] history: {self._hist.get('n')} clean laps here before")
            except Exception as e:
                self.log(f"[brain] history: {e!r}")
        return self._hist or {}

    def fuel_lap_est(self):
        """Fuel per lap: this session's laps, or your usual here from earlier sessions until there are some."""
        if getattr(self, "electric", False):
            return None                            # electric car: no fuel figure, so no fuel calls or fuel plans
        if self.fuel_laps:
            xs = self.fuel_laps[-4:]
            return sum(xs) / len(xs)
        return self.hist().get("fuel_lap")

    def pace_est(self):
        """Typical lap time: this session's laps, or your race pace here from earlier sessions."""
        if self.lap_times:
            xs = self.lap_times[-3:]
            return sum(xs) / len(xs)
        h = self.hist()
        if h.get("sim_pace"):
            return h["sim_pace"]
        return h["best"] * 1.02 if h.get("best") else None

    # ---------- main loop ----------
    def tick(self):
        try:
            self._rp = bool(self.src["IsReplayPlaying"])     # replay stand-ins in g()
        except Exception:
            self._rp = False
        try:                                                 # 2026-10-27 (#454): loading screens -> sound waits
            from . import simload
            simload.update(self.src["SessionTick"], log=self.log)
        except Exception:
            pass
        try:                                                 # 2026-10-29: being towed back -> the radio goes quiet
            tow = float(self.src["PlayerCarTowTime"] or 0) > 0
            from . import voice as _voice
            if tow != _voice.TOWING:
                _voice.TOWING = tow
                self.log("[radio] towed to the pits - only pit / damage / your own questions until you're back"
                         if tow else "[radio] tow over - normal radio")
        except Exception:
            pass
        if not self.g("IsOnTrack", False) and not self.g("IsOnTrackCar", False):
            # still watch flags/session even when in garage
            pass
        n = self.g("SessionNum", 0)
        if n != self.sess_num:
            self.reset_session()
            self.sess_num = n
            self.sess_type = self.session().get("SessionType", "")
            self.v.gtp = self.is_hybrid()          # the voice's {GTP:...} parts are hybrid / deploy lines
            self.electric = self.is_electric()
            self.v.fuel_metric = self.metric()
            tn = self.info("WeekendInfo", {}).get("TrackName")
            if tn and tn != self.track_loaded and self.c:
                cnt = self.c.set_track(tn); self.track_loaded = tn
                self.log(f"[brain] track {tn}: {cnt} corners known")
            self.log(f"[brain] session {n}: {self.sess_type}  GTP={self.v.gtp}")
            self.session_greeting = False
            # 2026-10-25: an app restart mid-session picks the race back up (laps, calls made, last-lap state...)
            from . import race_state
            race_state.restore(self)

        # race control first (driver request 2026-10-23): the director's call plays the instant the session
        # switches (qualifying, practice, grid, formation, green) - before the radio check or anything else
        try:
            self.rc.tick()
        except Exception as e:
            self.log(f"[race control] {e!r}")

        now = self.clock()
        # later() is also called from the radio / button threads: take due timers out in place (no rebinding)
        due = [t for t in list(self.timers) if t[0] <= now]
        for t in due:
            try:
                self.timers.remove(t)
            except ValueError:
                pass
        for _, fn in due:
            try:
                fn()
            except Exception as e:      # one bad delayed call must not cost the rest of this tick (spotter etc.)
                self.log(f"[brain] later: {e!r}")

        try:
            from . import race_state
            race_state.maybe_save(self)
        except Exception:
            pass

        on_track = self.g("IsOnTrack", False)
        if on_track and not self.said_radio_check:
            self.said_radio_check = True
            self.say("radio_check", prio=PRIO_INFO)
        if on_track and not self.session_greeting:
            self.session_greeting = True
            if "practice" in self.sess_type.lower():
                self.later(4, lambda: self.say("practice_start"))
            elif self.is_quali():
                self.later(4, lambda: self.say("quali_start"))

        if getattr(self.s, "hold_in_corners", True) and on_track and not self.g("OnPitRoad", False):
            busy = (self.g("Brake", 0) or 0) > 0.25 or abs(self.g("SteeringWheelAngle", 0) or 0) > 0.35
            self.v.hold(bool(busy) or self.chat_busy())
        else:
            self.v.hold(self.chat_busy())

        self.spotter()
        self.flags()
        self.incidents()
        self.spin_watch()
        self.pit()
        self.laps()
        self.positions()
        self.multiclass()
        self.weather()
        self.end_watch()
        self.x.tick()
        self.rcft.tick()
        try:
            self.incar.tick()
        except Exception as e:
            if self.once_log("incar", e):
                self.log(f"[incar] {e!r}")
        try:
            self.ask.tick()
        except Exception as e:
            if self.once_log("ask", e):
                self.log(f"[ask] {e!r}")

    # ---------- spotter ----------
    def spotter(self):
        min_ms = max(0.0, float(getattr(self.s, "spot_min_kmh", 30) or 0)) / 3.6
        if not self.s.spotter or self.alone() or self.g("Speed", 0) < max(8.0, min_ms) or self.g("OnPitRoad", False):
            self.lr_prev = LR_CLEAR
            self.lr_pend = None
            return
        raw = self.g("CarLeftRight", LR_CLEAR) or LR_CLEAR
        now = self.clock()
        # 2026-10-26 (DRE parity, spotter tuning): a change only counts once it has held for the call / clear delay -
        # a car flickering at the edge of the mirror no longer makes "car left, clear, car left" chatter
        pend = getattr(self, "lr_pend", None)
        if raw == self.lr_prev:
            self.lr_pend = None
            c = raw
        else:
            if pend is None or pend[0] != raw:
                self.lr_pend = pend = (raw, now)
            hold = (getattr(self.s, "spot_clear_ms", 350) if raw == LR_CLEAR else getattr(self.s, "spot_call_ms", 120)) / 1000.0
            c = raw if now - pend[1] >= hold else self.lr_prev
            if c == raw:
                self.lr_pend = None
        p = self.lr_prev
        if c != p:
            L = lambda x: x in (LR_LEFT, LR_2LEFT)
            R = lambda x: x in (LR_RIGHT, LR_2RIGHT)
            if c == LR_BOTH and p != LR_BOTH:
                self.say("three_wide", prio=PRIO_SPOTTER)
            elif L(c) and not (L(p) or p == LR_BOTH):
                self.say("car_left", prio=PRIO_SPOTTER)
            elif R(c) and not (R(p) or p == LR_BOTH):
                self.say("car_right", prio=PRIO_SPOTTER)
            elif p == LR_BOTH and R(c):
                self.say("clear_left", prio=PRIO_SPOTTER)
            elif p == LR_BOTH and L(c):
                self.say("clear_right", prio=PRIO_SPOTTER)
            elif c == LR_CLEAR and p != LR_CLEAR:
                self.say("clear", prio=PRIO_SPOTTER)
            self.lr_since, self.lr_still_said = now, False
        elif c not in (LR_CLEAR, 0) and not self.lr_still_said and now - self.lr_since > float(getattr(self.s, "spot_still_s", 5.0) or 5.0):
            self.lr_still_said = True
            self.say("still_there", prio=PRIO_SPOTTER)
        self.lr_prev = c

    # ---------- flags ----------
    def flags(self):
        f = self.g("SessionFlags", 0) or 0
        pf = self.prev.get("flags", f)
        self.prev["flags"] = f
        rise = lambda b: (f & b) and not (pf & b)
        fall = lambda b: (pf & b) and not (f & b)
        state = self.g("SessionState", 0)
        ps = self.prev.get("state", 0); self.prev["state"] = state

        if self.is_race():
            if state == 3 and ps != 3:
                self.say("formation", prio=PRIO_RACE)
                tt = self.g("TrackTempCrew")
                if tt is not None:
                    deg = tt if self.metric() else tt * 9 / 5 + 32
                    self.later(25, lambda: self.say("track_temp", {"n": round(deg)}))
            if state == 4 and ps in (2, 3) or (rise(F_GREEN) and not self.green_seen and state == 4):
                if not self.green_seen:
                    self.green_seen = True
                    self.green_t = self.clock()
                    try:
                        self._green_st_save(float(self.src["SessionTime"]))   # #405: the race clock starts here
                    except Exception:
                        pass
                    self.start_pos = self.class_pos(self.me()) or None
                    self.say("green_start", prio=PRIO_URGENT)
                    self.later(14, self.judge_start)
            if rise(F_CAUTION) or rise(F_CAUTION_WAVING):
                if not self.caution_on:
                    self.caution_on = True
                    self.say("sc_deployed", prio=PRIO_URGENT)
            if self.caution_on and rise(F_ONE_TO_GREEN):
                self.say("sc_in", prio=PRIO_RACE)
            if self.caution_on and not (f & (F_CAUTION | F_CAUTION_WAVING)) and (f & F_GREEN):
                self.caution_on = False
                self.say("restart", prio=PRIO_URGENT)
            if rise(F_WHITE) and not self.finished and not self.prev.get("last_lap_said"):
                self.prev["last_lap_said"] = True
                self.prev["last_lap_lc"] = self.g("LapCompleted", 0) or 0
                self.log(f"[end] last lap: WHITE FLAG seen  lc={self.prev['last_lap_lc']} time_left={self.g('SessionTimeRemain', -1):.0f}s "
                         f"replay={bool(self.g('IsReplayPlaying', False))} state={self.g('SessionState', 0)}")
                p = self.class_pos(self.me())
                self.say("last_lap_leading" if p == 1 else "last_lap", prio=PRIO_RACE)
            if rise(F_CHECKERED) or (state == 5 and ps == 4):
                pass  # wait for us to cross the line (handled in laps())
        if rise(F_RED):
            self.say("red_flag", prio=PRIO_URGENT)
        if rise(F_BLACK):
            self.say("black_flag", prio=PRIO_URGENT)
        if rise(F_DQ):
            self.say("car_black_flag", prio=PRIO_URGENT)
        if rise(F_REPAIR):
            self.say("heavy_damage", prio=PRIO_URGENT)
        # ic168 (2026-10-31, Angelo: sitting in the pit box after a tow it kept saying "car ahead blue flag, careful on pass"):
        # no blue-flag call while we are in the pit lane or crawling - the cars going by on track are not ours to let past
        if (f & F_BLUE) and not self.is_quali():
            # ic168b: only when we are really out driving - not in the pit lane / stall, not being repaired, not on the tow
            g = self.g
            parked = (g("OnPitRoad", False) or g("PlayerCarInPitStall", False) or not g("IsOnTrack", True)
                      or (g("PitRepairLeft", 0) or 0) > 0 or (g("PitOptRepairLeft", 0) or 0) > 0
                      or (g("Speed", 0) or 0) < 15)
            try:
                from .voice import TOWING
                parked = parked or bool(TOWING)
            except Exception:
                pass
            if not parked:
                self.say("blue_flag", prio=PRIO_RACE, cooldown=25)
        yel = bool(f & (F_YELLOW | F_YELLOW_WAVING)) and not self.caution_on
        if yel and not self.yellow_on:
            self.yellow_on = True
            k = self.trouble_ahead()
            if k:
                self.say("yellow_corner", {"corner": k}, prio=PRIO_URGENT, cooldown=8)
            else:
                self.say("yellow_sector", {"sector": self.sector()}, prio=PRIO_URGENT, cooldown=8)
        elif not yel and self.yellow_on:
            self.yellow_on = False
            self.say("yellow_clear", prio=PRIO_RACE, cooldown=20)

    def sector(self):
        return min(3, int((self.g("LapDistPct", 0) or 0) * 3) + 1)

    def trouble_ahead(self, look_m=1500):
        """Corner of the nearest car off track / stopped ahead of us."""
        pct = self.g("CarIdxLapDistPct") or []
        surf = self.g("CarIdxTrackSurface") or []
        me = self.me(); L = self.track_len_m()
        mp = pct[me] if me < len(pct) else None
        if mp is None or mp < 0:
            return None
        best = None
        for i, s in enumerate(surf):
            if i == me or i >= len(pct) or pct[i] < 0:
                continue
            if s == TS_OFF:
                d = ((pct[i] - mp) % 1) * L
                if 0 < d < look_m and (best is None or d < best[0]):
                    best = (d, pct[i] * L)
        return self.c.at(best[1], slack=150) if best and self.c else None

    def judge_start(self):
        p = self.class_pos(self.me())
        if not p or not self.start_pos:
            return
        d = self.start_pos - p
        if d >= 2:
            self.say("great_start", prio=PRIO_RACE)
        elif d >= 0:
            self.say("good_start", prio=PRIO_INFO)
        elif d <= -2:
            self.say("bad_start", prio=PRIO_INFO)
        self.pos_stable = p

    # ---------- incidents: track limits, spins, contact ----------
    def spin_watch(self):
        """Spins from the car's motion (2026-10-24): replays carry no live incident count, and a
        spin is worth a call the moment it happens anyway. Big yaw rate while the car slides
        sideways, held for a moment."""
        if not self.g("IsOnTrack", False) or self.g("OnPitRoad", False):
            self._spin_t = None
            return
        yaw = abs(self.g("YawRate", 0) or 0)
        vx, vy = (self.g("VelocityX", 0) or 0), (self.g("VelocityY", 0) or 0)
        v = (vx * vx + vy * vy) ** 0.5
        sliding = v > 4 and (abs(vy) > 0.55 * v or vx < -1.0)
        now = self.clock()
        if yaw > 1.4 and sliding:
            if self._spin_t is None:
                self._spin_t = now
            elif now - self._spin_t > 0.3 and now - getattr(self, "_spin_said", -1e9) > 20:
                self._spin_said = now
                self.crowd_ev.append("spin")          # crowd (2026-10-24)
                self.say("spin", prio=PRIO_URGENT, cooldown=6)
                self.later(2.5, self.rejoin_advice)
        else:
            self._spin_t = None

    def incidents(self):
        if self.g("IsReplayPlaying", False):
            return self.replay_offtrack()
        n = self.g("PlayerCarMyIncidentCount")
        if n is None:
            return
        if self.inc is None:
            self.inc = n; return
        d = n - self.inc
        if d <= 0:
            return
        self.inc = n
        corner = self.c.nearest_behind(self.g("LapDist", 0)) if self.c else None
        if d == 1:
            self.tl_count += 1
            if corner:
                self.say("track_limits_again" if self.tl_count >= 3 and self.tl_count % 3 == 0 else "track_limits",
                         {"corner": corner}, prio=PRIO_URGENT, cooldown=4)
        elif d == 2:
            self.crowd_ev.append("spin")              # crowd (2026-10-24)
            self.say("spin", prio=PRIO_URGENT, cooldown=6)
            self.later(2.5, self.rejoin_advice)
        else:
            self.crowd_ev.append("contact")           # crowd (2026-10-24)
            self.say("contact", prio=PRIO_URGENT, cooldown=6)
        lim = self.incident_limit()
        if lim and n >= lim - 4 and "inc_close" not in self.prev:
            self.prev["inc_close"] = True
            self.later(6, lambda: self.say("incident_close", {"n": n}, prio=PRIO_RACE))

    def replay_offtrack(self):
        """Replays (2026-10-24): iRacing replays the FINAL incident count the whole time, so the counter never
        moves. Use the car's track surface instead - four wheels off for a moment = a track-limits call, at the
        corner it happened. Live driving keeps using the real incident counter (exact)."""
        surf = self.g("PlayerTrackSurface", 3)
        now = self.clock()
        off = surf == 0                                   # irsdk TrkLoc: 0 = off track, 3 = on track
        st = getattr(self, "_rp_off", None)
        if off and st is None:
            self._rp_off = now
        elif off and st is not None and st > 0 and now - st >= 0.3 and (self.g("Speed", 0) or 0) > 10:
            self._rp_off = -1.0                           # counted this excursion
            self.tl_count += 1
            corner = self.c.nearest_behind(self.g("LapDist", 0)) if self.c else None
            if corner and not (now - (getattr(self, "_spin_said", None) or -99) < 3):   # a spin call covers it
                self.say("track_limits_again" if self.tl_count >= 3 and self.tl_count % 3 == 0 else "track_limits",
                         {"corner": corner}, prio=PRIO_URGENT, cooldown=4)
        elif not off:
            self._rp_off = None

    def incident_limit(self):
        v = str(self.info("WeekendInfo", {}).get("WeekendOptions", {}).get("IncidentLimit", ""))
        return int(v) if v.isdigit() else None

    def rejoin_advice(self):
        """After a spin: is someone coming?"""
        pct = self.g("CarIdxLapDistPct") or []
        me = self.me(); L = self.track_len_m()
        if me >= len(pct) or pct[me] < 0:
            return
        coming = False
        for i, p in enumerate(pct if not self.alone() else []):
            if i == me or p < 0:
                continue
            d = ((pct[me] - p) % 1) * L
            if 0 < d < 350:
                coming = True
        self.say("rejoin_car_coming" if coming else "rejoin_clear", prio=PRIO_URGENT)

    # ---------- pits ----------
    def pit(self):
        on = bool(self.g("OnPitRoad", False))
        was = self.prev.get("pit", on); self.prev["pit"] = on
        # 2026-10-29 (Angelo: after the race, pitting shouldn't sound like a race stop - "context aware of that being the
        # not in race pitting"): after the flag the pit lane gets the cool-down lines (post_pit_*, only once they're
        # approved and recorded - until then nothing), never the limiter reminder / where-we-come-out calls.
        if self.is_race() and self.finished:
            if on and not was and self.g("IsOnTrack", False):
                self.say("post_pit_in", prio=PRIO_INFO, cooldown=600)
            return
        if on and not was and self.g("IsOnTrack", False):
            self.last_pit_time = self.clock()
            if not (int(self.g("EngineWarnings", 0) or 0) & 0x10):   # limiter already on: nothing to remind
                self.say("pit_entry", prio=PRIO_RACE)
        if was and not on and self.g("IsOnTrack", False):
            self.last_pit_time = self.clock()
            self.say("pit_exit", prio=PRIO_RACE)
            self.later(3, self.pit_exit_traffic)
        if on:
            lim = self.pit_limit_ms()
            if lim and self.g("Speed", 0) > lim + 0.6:
                self.say("pit_too_fast", prio=PRIO_URGENT, cooldown=20)
        # a car ahead in class pits: can we jump them / catch them? (2026-10-25) - instead of the plain call for that car
        try:
            for idx in self.pitwatch.tick():
                self.cool[f"car_ahead_pitting{idx}"] = self.cool[f"leader_pitting{idx}"] = self.clock()
        except Exception as e:
            if self.once_log("pitwatch", e):
                self.log(f"[pitwatch] {e!r}")
        # other cars pitting, same class, right next to us in the order
        if self.is_race() and self.green_seen:
            ahead, _, behind, _ = self.neighbours()
            onp = self.g("CarIdxOnPitRoad") or []
            cid, _ = self.my_class()
            leader = next((i for i in self.class_cars(cid) if self.class_pos(i) == 1), None)
            for idx, sid in ((ahead, "car_ahead_pitting"), (behind, "car_behind_pitting"), (leader, "leader_pitting")):
                if idx is None or idx == self.me() or idx >= len(onp):
                    continue
                prev = self.ahead_pit_prev.get((sid, idx), onp[idx])
                if onp[idx] and not prev:
                    said = "car_ahead_pitting" if sid == "leader_pitting" and idx == ahead else sid
                    # 2026-10-24: a call was repeated 11 s later; one call per kind per 40 s, per car per 3 min
                    now = self.clock()
                    if now - self.cool.get(f"{said}{idx}", -1e9) >= 180:
                        # 2026-10-25 (driver request): name the position, not "car ahead" - "P3 is pitting" - once that line is
                        # recorded (voice queue); until then the existing call (never the stand-in voice)
                        pos = self.class_pos(idx)
                        if said != "leader_pitting" and pos and "pos_pitting" in getattr(self.v, "lines", {}):
                            ok = self.say("pos_pitting", {"P": pos}, prio=PRIO_RACE, cooldown=40, key=said)
                        else:
                            ok = self.say(said, prio=PRIO_RACE, cooldown=40, key=said)
                        if ok:
                            self.cool[f"{said}{idx}"] = now
                            if said != sid:   # leader = car ahead: don't announce it twice
                                self.cool["car_ahead_pitting"] = now
                self.ahead_pit_prev[(sid, idx)] = onp[idx]

    def pit_limit_ms(self):
        t = str(self.info("WeekendInfo", {}).get("TrackPitSpeedLimit", ""))
        try:
            v = float(t.split()[0])
            return v / 3.6 if "kph" in t else v * 0.44704
        except (ValueError, IndexError):
            return None

    def pit_exit_traffic(self):
        if self.alone():
            return
        pct = self.g("CarIdxLapDistPct") or []
        me = self.me(); L = self.track_len_m()
        if me >= len(pct) or pct[me] < 0:
            return
        onp = self.g("CarIdxOnPitRoad") or []
        for i, p in enumerate(pct):
            if i == me or p < 0 or (i < len(onp) and onp[i]):
                continue
            d = ((pct[me] - p) % 1) * L
            if 0 < d < 250:
                self.say("pit_exit_traffic", prio=PRIO_URGENT)
                return

    # ---------- every lap ----------
    def laps(self):
        lc = self.g("LapCompleted", -1)
        if lc is None or lc < 0:
            return
        if self.last_lap_done < 0:
            self.last_lap_done = lc
            self.fuel_at_line = self.g("FuelLevel")
            return
        if lc <= self.last_lap_done:
            return
        self.last_lap_done = lc
        fuel = self.g("FuelLevel")
        t = self.g("LapLastLapTime", -1) or -1
        pitted = self.clock() - self.last_pit_time < 90
        clean = t > 0 and not pitted and not self.caution_on
        if clean:
            self.lap_times.append(t)
        if self.fuel_at_line is not None and fuel is not None and clean and not getattr(self, "electric", False):
            used = self.fuel_at_line - fuel
            if used > 0.05:
                self.fuel_laps.append(used)
        self.fuel_at_line = fuel

        flags = self.g("SessionFlags", 0) or 0
        # 2026-10-24 (request: "congratulatory radio at the white flag, a lap early"): when the clock has run out iRacing
        # can already say "checkered" as you take the WHITE. Once the last lap has been called, the finish is the
        # NEXT time you cross the line, not the crossing the last-lap call was made on.
        ll = self.prev.get("last_lap_lc")
        early = ll is not None and lc <= ll
        wl = self.prev.get("white_lc")           # the leader has taken the white (end_watch, earlier tick)...
        if ll is None and wl is not None:        # ...and this crossing is OUR white - laps() runs before end_watch
            early = True
        if self.is_race() and (flags & F_CHECKERED or self.g("SessionState", 0) >= 5):
            self.log(f"[end] line crossed with checkered/state>=5  lc={lc} last_lap_lc={ll} white_lc={wl} "
                     f"early={early} finished={self.finished} flags={flags:#x} state={self.g('SessionState', 0)}")
        if self.is_race() and (flags & F_CHECKERED or self.g("SessionState", 0) >= 5) and not self.finished and not early:
            self.finished = True
            self.finish_p_line = self.line_pos(lc)
            self.later(3.5, self.finish_call)
            self.later(25, lambda: self.say("cooldown", prio=PRIO_INFO))
            return

        # lap time news
        prev_best = self.best
        if t > 0 and not pitted:
            if self.best is None or t < self.best:
                self.best = t
            if prev_best and t < prev_best - 0.05:
                if self.class_fastest(t):
                    self.say("fastest_lap", prio=PRIO_INFO, cooldown=60)
                else:
                    self.say("personal_best", {"time": t}, prio=PRIO_INFO, cooldown=45)

        if self.is_quali() and t > 0:
            # 2026-10-25: the position is worked out 2 s after the line from everyone's best laps (iRacing's
            # own position lags behind - a P2 lap was once called "P4"), and "one more lap" is only said
            # when there is time left for one
            improved = bool(prev_best and t < prev_best) or prev_best is None
            self.later(2, lambda: self.quali_call(improved))
            return
        if not self.is_race() or not self.green_seen:
            return

        ltg = self.laps_to_go()
        self.fuel_call(lc, ltg)
        self.race_progress(ltg)
        self.gap_call(lc)

    def chat_busy(self):
        """Someone is talking on iRacing voice chat (or you are): hold non-urgent lines (2026-10-24, DRE 'busy detection')."""
        if not getattr(self.s, "hold_for_chat", True):
            return False
        r = self.g("RadioTransmitCarIdx", -1)
        return r is not None and r >= 0

    def end_watch(self):
        """End-of-race calls, checked every tick (2026-10-24, request: "he never says last lap / 5 minutes / 2 minutes").
        - Minutes left in timed races: said the moment the clock passes 30, 20, 15, 10, 5 and 2 minutes (it used
          to be checked only at the line, so a 3.5-minute Le Mans lap could skip a call completely).
        - Last lap without the white flag (replays don't record flags, and it backs up the flag live): the leader
          takes the white when the clock has run out (timed) or with one lap to go (lap races); our last lap
          starts when we next cross the line."""
        if self.is_race() and not self.green_seen and (self.g("SessionState", 0) or 0) == 4 and (self.g("LapCompleted", 0) or 0) >= 1:
            # joined a race already under way (app restarted mid-race, or a replay jump): carry on quietly
            self.green_seen = True
            self.green_t = self.clock()
            self.log("[brain] joined a race in progress - race calls on")
        if not self.is_race() or not self.green_seen or self.finished:
            return
        p = self.class_pos(self.me())
        tr = self.g("SessionTimeRemain", -1)
        lap_based = 0 <= (self.g("SessionLapsRemainEx", 32767) or 32767) < 32000
        if not lap_based and tr is not None and tr >= 0:
            mins = tr / 60
            prev = self.prev.get("mins_prev")
            self.prev["mins_prev"] = mins
            if prev is not None:
                for m in (30, 20, 15, 10, 5, 2):
                    if prev > m >= mins and m not in self.minutes_announced and prev - mins < 1:   # crossed just now
                        self.minutes_announced.add(m)
                        # 2026-10-24 (driver request): every minute call asks for a tyre phase + brake shape update;
                        # the answer ("tyres are good", "brakes are fading"...) is handled in racecraft.feedback()
                        self.say("minutes_ask", {"minutes": m}, prio=PRIO_RACE)
                        self.feedback_asked = self.clock()
                        break
        # ---- last lap, flag-free ----
        if self.prev.get("last_lap_said"):
            return
        lcs = self.g("CarIdxLapCompleted") or []
        me = self.me()
        if me is None or me >= len(lcs):
            return
        leader_lc = max([x for x in lcs if x is not None] or [-1])
        my_lc = lcs[me]
        white = self.prev.get("white_lc")
        if white is None:
            if lap_based:
                total = (self.g("SessionLapsRemainEx", 32767) or 0) + (self.g("LapCompleted", 0) or 0)
                total = self.prev.setdefault("race_total_laps", total)
                if total > 1 and leader_lc >= total - 1:
                    white = self.prev["white_lc"] = my_lc
            elif tr is not None and tr <= 0.5:
                if "expired_leader_lc" not in self.prev:
                    self.log(f"[end] clock ran out  leader_lc={leader_lc} my_lc={my_lc} "
                             f"green {self.clock() - self.green_t:.0f}s ago  state={self.g('SessionState', 0)}")
                exp = self.prev.setdefault("expired_leader_lc", leader_lc)
                if leader_lc > exp:                       # the leader crossed after time ran out: white flag
                    white = self.prev["white_lc"] = my_lc
            if white is not None and my_lc >= leader_lc:  # we ARE the leader: our last lap starts now
                white = -1
        if white is not None and (white == -1 or my_lc > white):
            self.prev["last_lap_said"] = True
            self.prev["last_lap_lc"] = my_lc
            self.log(f"[end] last lap: from {'lap count' if lap_based else 'clock'}  white_lc={white} my_lc={my_lc} "
                     f"leader_lc={leader_lc} time_left={tr:.0f}s lap_based={lap_based} "
                     f"total={self.prev.get('race_total_laps')} remainEx={self.g('SessionLapsRemainEx', -1)}")
            self.say("last_lap_leading" if p == 1 else "last_lap", prio=PRIO_RACE)

    def quali_pos(self):
        """Class position by best lap (counts only cars that have set a time); falls back to iRacing's."""
        me = self.me()
        bests = self.g("CarIdxBestLapTime") or []
        mine = bests[me] if me is not None and me < len(bests) else -1
        if not mine or mine <= 0:
            return self.class_pos(me)
        cid, _ = self.my_class()
        return 1 + sum(1 for i in self.class_cars(cid) if i != me and i < len(bests) and 0 < bests[i] < mine)

    def quali_call(self, improved):
        p = self.quali_pos()
        if not p:
            return
        if p == 1 and improved:
            self.say("pole", prio=PRIO_INFO, cooldown=60)
            return
        left = self.g("SessionTimeRemain", -1)
        lap = self.best or 0
        over = bool((self.g("SessionFlags", 0) or 0) & F_CHECKERED) or (left is not None and 0 <= left < lap * 1.02)
        if over:
            self.say("quali_result", {"P": p}, prio=PRIO_INFO, cooldown=60)
        else:
            self.say("quali_provisional", {"P": p}, cooldown=60)

    def class_fastest(self, t):
        cid, _ = self.my_class()
        bests = self.g("CarIdxBestLapTime") or []
        for i in self.class_cars(cid):
            if i != self.me() and i < len(bests) and 0 < bests[i] < t:
                return False
        return True

    def fuel_call(self, lc, ltg):
        if len(self.fuel_laps) < 2 or ltg is None or getattr(self, "electric", False):
            return
        per = sum(self.fuel_laps[-4:]) / len(self.fuel_laps[-4:])
        fuel = self.g("FuelLevel", 0) or 0
        have = fuel / per if per > 0 else 99
        # ic170 (2026-10-31, Angelo: told "fuel for 2 laps, 2 to go, we need lift and coast" with 2.6 laps in the car -
        # he pitted for nothing): good = a quarter of a lap spare (per-lap burn is known to a few tenths of a litre);
        # the laps said are what we HAVE rounded down and what we NEED rounded up, so the numbers always match the call
        st = ("ok" if have >= ltg + 0.25 else "thin" if have >= ltg else
              "short" if have >= ltg - 1.5 else ("critical" if have < 1.6 else "pit"))
        changed = st != self.prev.get("fuel_state")
        self.prev["fuel_state"] = st
        if st == "thin":
            return                      # makes it, with under a quarter lap spare: no call either way (ask the strategist)
        import math as _m
        laps = [int(have), int(ltg)] if st == "ok" else [int(have), int(_m.ceil(ltg))]
        if st == "critical":
            self.say("fuel_critical", prio=PRIO_URGENT, cooldown=60)
        elif st == "ok" and (changed or lc % 8 == 3):
            self.say("fuel_ok", {"laps": laps}, cooldown=400)
        elif st == "short" and (changed or lc % 4 == 0):
            self.say("fuel_short", {"laps": laps}, prio=PRIO_RACE, cooldown=90)
        elif st == "pit" and changed:
            need = max(0.0, (ltg - have) * per + per * 0.3)
            # ic170 (Angelo: "We need 62 gallons to finish for a car that holds 23 gallons doesn't make sense"): more
            # than a tank to go = a multi-stop race - the strategist's stop plan says it; this line is for a top-up
            di = self.info("DriverInfo", {}) or {}
            try:
                tank = float(di.get("DriverCarFuelMaxLtr") or 0) * float(di.get("DriverCarMaxFuelPct") or 1)
            except (TypeError, ValueError):
                tank = 0.0
            if tank > 0 and need > tank * 0.9:
                return
            if not self.metric():
                need = need / 3.785
            n_ = max(1, round(need))       # ic174: "fuel unit" is the singular/plural count (the card showed "62 62")
            self.say("fuel_to_add", {"n": n_, "fuel unit": 1 if n_ == 1 else 2}, cooldown=200)

    def race_progress(self, ltg):
        lap_based = 0 <= (self.g("SessionLapsRemainEx", 32767) or 32767) < 32000
        p = self.class_pos(self.me())
        if lap_based and ltg is not None:
            total = (ltg or 0) + self.last_lap_done
            if ltg == 5 and total >= 10 and 5 not in self.laps_announced:
                self.laps_announced.add(5); self.say("five_laps", prio=PRIO_RACE)
            elif ltg == 2 and 2 not in self.laps_announced:
                self.laps_announced.add(2); self.say("two_laps", prio=PRIO_RACE)
            elif ltg in (10, 15, 20) and ltg not in self.laps_announced:
                self.laps_announced.add(ltg); self.say("laps_left", {"laps": ltg})
        # timed races: the minute calls run every tick in end_watch() (2026-10-24)
        total = self.prev.setdefault("total_laps", (ltg or 0) + self.last_lap_done)
        if not self.half_said and ltg is not None and total > 8 and ltg <= total / 2:
            self.half_said = True
            st = self.prev.get("fuel_state")
            self.say("half_fuel_short" if st in ("short", "pit") else "half_fuel_ok", cooldown=600)

    def gap_call(self, lc):
        if not self.s.gaps or self.caution_on:
            return
        ahead, ga, behind, gb = self.neighbours()
        self.gap_hist.append((ga, gb))
        p = self.class_pos(self.me())
        if p == 1 and gb is not None:
            if lc % 3 == 0:
                self.say("leading_gap", {"gap": gb})
            return
        prev = self.gap_hist[-2] if len(self.gap_hist) > 1 else (None, None)
        if gb is not None and gb < 1.0 and corner_ok(self):
            self.say("car_behind_close", {"gap": gb, "corner": self.c.next_after(self.g("LapDist", 0))},
                     prio=PRIO_RACE, cooldown=100)
        elif ga is not None and prev[0] is not None and prev[0] - ga > 0.25 and ga < 6:
            self.say("reeling_in" if ga < 2 else "gap_ahead_shrinking", {"gap": ga}, cooldown=250, key="gapA")
        elif gb is not None and prev[1] is not None and prev[1] - gb > 0.25 and gb < 4:
            self.say("behind_reeling", {"gap": gb}, cooldown=250, key="gapB")
        elif lc % self.s.gaps_every == 0 and ga is not None and gb is not None:
            self.say("gaps_each_lap", {"gap": [ga, gb]}, cooldown=50)

    def line_pos(self, my_lc):
        """2026-10-24 (request: P4 called "Podio!"): our class place the instant we take the flag - every car in our
        class that has already completed at least as many laps has finished ahead of us. iRacing's live class
        position can lag at the line; this can't. 0 if unknown."""
        try:
            me = self.me(); cid, _ = self.my_class()
            lcs = self.g("CarIdxLapCompleted") or []
            ahead = sum(1 for i in self.class_cars(cid)
                        if i != me and i < len(lcs) and lcs[i] is not None and lcs[i] >= my_lc)
            return ahead + 1
        except Exception:
            return 0

    def finish_pos(self):
        """Official class finishing position: the session results once iRacing has them, else the live class position."""
        me = self.me()
        try:
            sess = (self.info("SessionInfo", {}) or {}).get("Sessions", [])
            num = self.g("SessionNum", -1)
            for s_ in sess:
                if s_.get("SessionNum") == num:
                    for r in s_.get("ResultsPositions") or []:
                        if r.get("CarIdx") == me and r.get("ClassPosition") is not None:
                            return int(r["ClassPosition"]) + 1   # results are 0-based
        except Exception:
            pass
        return getattr(self, "finish_p_line", 0) or self.class_pos(me) or self.g("PlayerCarClassPosition", 0)

    def finish_call(self, tries=0):
        # 2026-10-24: positions settle a few seconds after the line (a P4 once got "Podio!");
        # only speak once two readings 2 s apart agree (up to 4 tries)
        p = self.finish_pos()
        self.log(f"[end] finish call try {tries}: P{p}  (line count P{getattr(self, 'finish_p_line', 0)}, live P{self.class_pos(self.me())})")
        if not p:
            return
        if tries < 4 and getattr(self, "_fin_seen", None) != p:
            self._fin_seen = p
            self.later(2.0, lambda: self.finish_call(tries + 1))
            return
        if p == 1:
            self.say("win", prio=PRIO_URGENT)
        elif p <= 3:
            self.say("podium", prio=PRIO_URGENT)
        elif self.start_pos and self.start_pos - p >= 3:
            self.say("finish_gained", {"P": p, "n": self.start_pos - p}, prio=PRIO_URGENT)
        elif self.start_pos and p > self.start_pos + 2:
            self.say("finish_bad", {"P": p}, prio=PRIO_URGENT)
        else:
            self.say("finish_good", {"P": p}, prio=PRIO_URGENT)

    # ---------- position changes ----------
    def positions(self):
        if not self.is_race() or not self.green_seen or self.finished or self.caution_on:
            return
        if self.clock() - self.green_t < 20:  # the start is judged as a whole by judge_start
            return
        p = self.class_pos(self.me())
        if not p:
            return
        now = self.clock()
        if self.pos_stable is None:
            self.pos_stable = p; return
        if p == self.pos_stable:
            self.pos_pending = None; return
        if not self.pos_pending or self.pos_pending[0] != p:
            self.pos_pending = (p, now); return
        if now - self.pos_pending[1] < 3:
            return
        old, self.pos_stable, self.pos_pending = self.pos_stable, p, None
        if now - self.last_pit_time < 60:
            return  # pit cycle, not a real pass
        # 2026-10-25 (request: "it's got to be an on track pass for him to be excited, not just a pit strategy call"):
        # who did we swap with? If every car we went past (or that went past us) has been in the pits lately, it was
        # the pit cycle - the pit watch says the strategy line when it pays off
        cid, _ = self.my_class()
        cars = [i for i in self.class_cars(cid) if i != self.me()]
        swapped = [i for i in cars if (self.class_pos(i) and ((self.class_pos(i) > p) != (self.class_pos(i) > old) or self.class_pos(i) == old))]
        swapped = [i for i in swapped if old <= self.class_pos(i) <= p or p <= self.class_pos(i) <= old]
        if swapped and all(self.pitwatch.pitted_recently(i) for i in swapped):
            self.log(f"[brain] P{old} -> P{p} through the pits (cars {[self.car_num(i) for i in swapped]}): no pass call")
            return
        if p < old:
            if p == 1:
                self.say("taking_lead", prio=PRIO_RACE)
            elif random.random() < 0.3:
                self.say("great_pass", prio=PRIO_RACE)
            else:
                self.say("gained_place", {"P": p}, prio=PRIO_RACE)
        else:
            self.say("lost_place", {"P": p}, prio=PRIO_RACE, cooldown=20)

    # ---------- multiclass traffic ----------
    def multiclass(self):
        # ic168c (2026-10-31, Angelo: sitting in the pit box it kept saying "car ahead blue flag, careful on pass"):
        # no traffic calls while we are in the pit lane / stall or crawling - the cars going by are not near us
        if self.g("OnPitRoad", False) or self.g("PlayerCarInPitStall", False) or (self.g("Speed", 0) or 0) < 15:
            return
        if not self.is_race() or self.finished:
            return
        now = self.clock()
        if now - self.prev.get("mc_t", 0) < 0.5:
            return
        self.prev["mc_t"] = now
        drv = self.drivers(); me = self.me()
        mine = drv.get(me, {})
        my_est = mine.get("CarClassEstLapTime") or 0
        pct = self.g("CarIdxLapDistPct") or []
        surf = self.g("CarIdxTrackSurface") or []
        if me >= len(pct) or pct[me] < 0:
            return
        L = self.track_len_m()
        faster_behind, slower_ahead = [], []
        for i, d in drv.items():
            if i == me or i >= len(pct) or pct[i] < 0 or d.get("CarClassID") == mine.get("CarClassID"):
                continue
            if i < len(surf) and surf[i] != TS_ON:
                continue
            est = d.get("CarClassEstLapTime") or 0
            if not (est and my_est):
                continue
            behind = ((pct[me] - pct[i]) % 1) * L
            ahead = ((pct[i] - pct[me]) % 1) * L
            if est < my_est * 0.97 and 20 < behind < 220:
                faster_behind.append((i, d))
            elif est > my_est * 1.03 and 20 < ahead < 250:
                slower_ahead.append((i, d))
        if faster_behind:
            cls = classes.spoken(faster_behind[0][1]) or ""   # #49: class from iRacing's class data (replays leave the name empty)
            new = [i for i, _ in faster_behind if now - self.mc_seen.get(i, -1e9) > 60]
            if new:
                for i, _ in faster_behind: self.mc_seen[i] = now
                if len(faster_behind) >= 2:
                    self.say("mc_faster_group", {"n": len(faster_behind), "class": cls}, prio=PRIO_RACE, max_age=6)
                elif self.class_pos(new[0]) == 1:
                    self.say("mc_class_leader", prio=PRIO_RACE, max_age=6)
                else:
                    self.say("mc_faster", {"class": cls}, prio=PRIO_RACE, max_age=6)
        if slower_ahead:
            new = [i for i, _ in slower_ahead if now - self.mc_seen.get(i, -1e9) > 60]
            if new:
                for i, _ in slower_ahead: self.mc_seen[i] = now
                self.say("mc_slower_group" if len(slower_ahead) >= 2 else "mc_slower_ahead",
                         prio=PRIO_INFO, max_age=6, cooldown=20, key="mc_slow")

    # ---------- weather ----------
    def weather(self):
        w = self.g("WeatherDeclaredWet")
        if w is None:
            return
        if self.wet is None:
            self.wet = w; return
        if w and not self.wet:
            self.say("rain_start", prio=PRIO_RACE)
        elif self.wet and not w:
            self.say("rain_stop", prio=PRIO_INFO)
        self.wet = w

    # ---------- answers for talk-back (voice recognition calls these) ----------
    def answer(self, intent):
        ahead, ga, behind, gb = self.neighbours()
        p = self.class_pos(self.me())
        A = lambda sid, f=None: self.say(sid, f, prio=PRIO_URGENT)
        if intent == "position":
            return A("ans_position", {"P": p}) if p else A("tb_no_data")
        if intent == "gap_ahead":
            if not ga:
                return A("tb_no_data")
            prev = self.gap_hist[-2][0] if len(self.gap_hist) > 1 else None
            return A("ans_gap_ahead", {"gap": ga, "_variant": 2 if prev is not None and ga > prev + 0.1 else 1})
        if intent == "gap_behind":
            return A("ans_gap_behind", {"gap": gb}) if gb else A("tb_no_data")
        if intent == "fuel":
            per = self.fuel_lap_est()               # earlier sessions here count until this one has a lap
            if not per or (self.g("FuelLevel", 0) or 0) <= 0.05:     # replays report an empty tank
                return A("tb_no_data")
            have = (self.g("FuelLevel", 0) or 0) / per
            ltg = self.laps_to_go() or 0
            return A("ans_fuel", {"laps": [int(have), int(ltg)], "_variant": 1 if have >= ltg + 0.5 else 2})
        if intent == "laps_left":
            ltg = self.laps_to_go()
            if not ltg:
                return A("tb_no_data")
            lap_based = 0 <= (self.g("SessionLapsRemainEx", 32767) or 32767) < 32000
            return A("ans_laps", {"laps": ltg, "minutes": int((self.g("SessionTimeRemain", 0) or 0) / 60),
                                  "_variant": 1 if lap_based else 2})
        if intent == "last_lap":
            t = self.g("LapLastLapTime", -1)
            return A("ans_time", {"time": t}) if t and t > 0 else A("tb_no_data")
        if intent == "best_lap":
            return A("ans_best", {"time": self.best}) if self.best else A("tb_no_data")
        if intent == "incidents":
            n = self.g("PlayerCarMyIncidentCount", 0)
            lim = self.incident_limit()
            return A("ans_incidents", {"n": [n, lim]}) if lim else A("incident_points", {"n": [n, 0]})
        if intent == "track_temp":
            tt = self.g("TrackTempCrew")
            if tt is None:
                return A("tb_no_data")
            return A("tb_track_temp", {"n": round(tt if self.metric() else tt * 9 / 5 + 32)})
        if intent == "spotter_off":
            self.s.spotter = False; return A("tb_spotter", {"_variant": 1})
        if intent == "spotter_on":
            self.s.spotter = True; return A("tb_spotter", {"_variant": 2})
        if intent == "quiet":
            self.s.gaps = False; return A("quiet")
        if intent == "talk":
            self.s.gaps = True; return A("talk")
        if intent == "radio_check":
            return A("radio_check")
        if self.x.answer(intent):
            return True
        return A("ans_didnt_catch")


def corner_ok(b):
    return b.c is not None and bool(b.c.marks)
