"""Live strategist: stores every lap and stop as you drive, and in races re-plans every lap
(Plan A / B / C) from where you really are and where the cars ahead are."""
from . import classes
import math, time

from . import strategy as S


class Strategist:
    def __init__(self, speak, log=print, emit=None):
        self.speak, self.log = speak, log
        self.emit = emit or (lambda e: None)
        self.b = None
        self._reset()

    def _reset(self):
        self.key = None
        self.car = self.track = None
        self.m = None
        self._m_at = -99
        self.tyre_age, self.stint = 0, 0
        self.lap_fuel, self.last_lc, self.lap_inc = None, None, None
        self.pit = None                 # current stop being measured
        self.pending_stop = None        # stop waiting for its out-lap (to measure the pit lane loss)
        self.recent = []                # recent clean lap times (this session)
        self.rival_stop = {}            # car idx -> lap of their last stop
        self.rival_onp = {}
        self.plans, self.rec, self.outlook = [], 0, []
        self.last_sig, self.briefed, self.pred = None, False, None
        self._pending_sig, self._lost = None, 0
        self.raining, self.wet_lvl, self._lvl_since, self._lvl_cand = False, None, 0.0, None
        self.tyre_call, self._call_lap, self._tip_lap = None, -9, -9
        self.mine_wet = None
        from .rain_brain import RainBrain          # #591: drying / wetter, the slicks-vs-wets crossover, its calls
        self.rb = RainBrain(say_clip=self._rb_clip, show=self._rb_show, quiet=self._rb_quiet, log=self.log)
        self._rb_cls = (-1e9, [], 1)               # (when, my class's car indices, my wet compound) - refreshed
        self._rb_fc = None                          # (when read, this week's rain chance)
        self.cond = None
        self.rundown, self._rd_next, self._grid_since, self._rd_st = [], 0.0, None, 0
        self.db_at, self.db_done = None, False   # post-race debrief
        self.rc = None                  # radio check: None -> "call" -> "wait" -> "ok" (no answer = no brief)
        from .runplan import RunPlan
        self.rp = RunPlan(self)         # practice run plan (same opt-in radio check)

    def g(self, k, d=None):
        if k == "SessionTimeRemain":            # #405: time left from the green (brain works it out)
            return self.b.g(k, d)
        try:
            x = self.b.src[k]
            return d if x is None else x
        except Exception:
            return d

    # ------------------------------------------------------------ every tick
    def tick(self, b):
        if b is not self.b:
            self.b = b
            self._reset()
        if b is None:
            return
        key = (id(b), b.sess_num)
        if key != self.key:
            self._reset(); self.b = b; self.key = key
            d = b.drivers().get(b.me(), {})
            self.car = d.get("CarPath"); self.track = (b.info("WeekendInfo", {}) or {}).get("TrackName")
            try:                    # this event's format and conditions, kept for next time
                info = {"WeekendInfo": b.info("WeekendInfo", {}), "SessionInfo": b.info("SessionInfo", {})}
                wk = info["WeekendInfo"] or {}
                S.record_event(S.event_from_info(info, self.car, self.track, f"live-{wk.get('SessionID')}-{wk.get('SubSessionID')}", time.time()))
            except Exception as e:
                self.log(f"[strategy] event: {e!r}")
        onp = bool(self.g("OnPitRoad", False))
        spd = self.g("Speed", 0) or 0
        # ---- my stops
        if onp and self.pit is None:
            self.pit = {"t0": time.time(), "still": 0.0, "fuel0": self.g("FuelLevel", 0), "tyres": False, "lap": (self.g("LapCompleted", 0) or 0) + 1, "_t": time.time()}
        if onp and self.pit is not None:
            now = time.time()
            if spd < 0.5:
                self.pit["still"] += now - self.pit["_t"]
                if int(self.g("PitSvFlags", 0) or 0) & 0x0F:
                    self.pit["tyres_req"] = True
            self.pit["_t"] = now
        if not onp and self.pit is not None:
            p, self.pit = self.pit, None
            if p["still"] > 1.5:
                added = max(0.0, (self.g("FuelLevel", 0) or 0) - (p["fuel0"] or 0))
                tyres = bool(p.get("tyres_req")) and p["still"] > 8
                if tyres:
                    self.tyre_age = 0
                self.stint += 1
                self.pending_stop = {"lap": p["lap"], "still": p["still"], "added": added, "tyres": tyres}
        # ---- rivals' stops
        onps = self.g("CarIdxOnPitRoad") or []
        lcs = self.g("CarIdxLapCompleted") or []
        for i, o in enumerate(onps):
            was = self.rival_onp.get(i)
            if was and not o and i < len(lcs):
                self.rival_stop[i] = lcs[i]
            self.rival_onp[i] = o
        self._rain_tick()
        try:
            self._rb_tick()
        except Exception as e:
            self.log(f"[rain] brain: {e!r}")
        self._formation(b)
        self._debrief(b)
        if "practice" in (b.sess_type or "").lower():
            self.rp.tick()
        # ---- laps
        lc = self.g("LapCompleted", -1)
        if lc is None or lc < 0:
            return
        if self.last_lc is None:
            self.last_lc, self.lap_fuel, self.lap_inc = lc, self.g("FuelLevel"), self.g("PlayerCarMyIncidentCount", 0)
            return
        if lc > self.last_lc:
            self.last_lc = lc
            self._lap(lc, onp)

    def _lap(self, lc, onp):
        b = self.b
        t = self.g("LapLastLapTime", -1) or -1
        fuel = self.g("FuelLevel")
        inc = self.g("PlayerCarMyIncidentCount", 0) or 0
        used = (self.lap_fuel - fuel) if (self.lap_fuel is not None and fuel is not None) else None
        clean = t > 0 and not onp and inc == self.lap_inc and not getattr(b, "caution_on", False) and self.pending_stop is None \
            and (self.lap_fuel or 0) > 0
        self.tyre_age += 1
        if self.car and self.track and t > 0:
            try:
                S.record_lap(self.car, self.track, lc, t, self.lap_fuel, used if used and used > 0.05 else None, clean, self.tyre_age,
                             self.stint, self.g("TrackTempCrew"), self.g("AirTemp"), self.g("TrackWetness"), b.sess_type.lower())
            except Exception as e:
                self.log(f"[strategy] save lap: {e!r}")
        try:
            self.rp.lap(t, clean, used)
        except Exception as e:
            self.log(f"[runplan] lap: {e!r}")
        if clean:
            self.recent = (self.recent + [t])[-6:]
        elif t > 0 and len(self.recent) >= 2 and not onp and self.pending_stop is None:
            self._lost = getattr(self, "_lost", 0) + max(0.0, t - sorted(self.recent)[len(self.recent) // 2])   # spin, off, traffic
        ps = self.pending_stop
        if ps and lc >= ps["lap"] + 1:              # the out-lap is done: measure the stop
            self.pending_stop = None
            lane = None
            if len(self.recent) >= 2 and t > 0:
                med = sorted(self.recent)[len(self.recent) // 2]
                inl = getattr(self, "_inlap_t", None)
                if inl:
                    lane = inl + t - 2 * med - ps["still"]
                    lane = lane if 5 < lane < 90 else None
            try:
                S.record_stop(self.car, self.track, ps["lap"], lane, ps["still"], ps["added"], ps["tyres"])
            except Exception:
                pass
        self._inlap_t = t
        self.lap_fuel, self.lap_inc = fuel, inc
        try:
            self._rain_lap(lc)
        except Exception as e:
            self.log(f"[rain] {e!r}")
        try:                                        # #591: the switch-point calls - not once "box for slicks / wets" is out
            self.rb.lap(self.rain_ctx(), box_called=self.tyre_call is not None)
        except Exception as e:
            self.log(f"[rain] brain lap: {e!r}")
        if b.is_race():
            self.replan(lc)
        elif len(self.recent) == 3 and not self.briefed and self.rp.rc is None:     # (the run plan replaces this)
            self.briefed = True
            self.brief(pre_race=False)

    # ------------------------------------------------------------ model + plans
    def model(self, force=False):
        if self.car and self.track and (force or self.m is None or (self.last_lc or 0) - self._m_at >= 5):
            try:
                self.m = S.model(self.car, self.track)
                if self.m and getattr(self.b, "electric", False):
                    self.m = dict(self.m, fuel_lap=None)   # electric car (car parity E15): no fuel figure, no fuel plans
                self._m_at = self.last_lc or 0
            except Exception as e:
                self.log(f"[strategy] model: {e!r}")
        return self.m

    def tank(self):
        di = self.b.info("DriverInfo", {}) or {}
        if getattr(self.b, "electric", False):
            return None                             # electric car (car parity E15): no fuel tank
        try:
            return float(di.get("DriverCarFuelMaxLtr")) * float(di.get("DriverCarMaxFuelPct") or 1)
        except (TypeError, ValueError):
            return None

    def race_seconds(self):
        s = str(self.b.session().get("SessionTime", ""))
        try:
            return float(s.split()[0])
        except (ValueError, IndexError):
            return None

    def live_model(self):
        m = self.model()
        if not m or not m.get("fuel_lap"):
            return None
        m = dict(m)
        # your pace right now moves the whole model
        if len(self.recent) >= 2:
            pred = S.lap_time(m, self.g("FuelLevel", 0) or 0, self.tyre_age, self.g("TrackTempCrew"))
            m["base"] += sorted(self.recent[-3:])[len(self.recent[-3:]) // 2] - pred
        return m

    def rivals(self):
        b = self.b
        me = b.me(); cid, _ = b.my_class(); mp = b.class_pos(me)
        f2 = self.g("CarIdxF2Time") or []
        last = self.g("CarIdxLastLapTime") or []
        lcs = self.g("CarIdxLapCompleted") or []
        out = []
        if not mp:
            return out
        for i in b.class_cars(cid):
            p = b.class_pos(i)
            if not p or p >= mp or p < mp - 3 or i >= len(f2):
                continue
            gap = (f2[me] - f2[i]) if me < len(f2) else None
            if gap is None or gap <= 0 or gap > 90:
                continue
            since = (lcs[i] - self.rival_stop[i]) if i in self.rival_stop and i < len(lcs) else (lcs[i] if i < len(lcs) else 0)
            out.append({"idx": i, "num": b.car_num(i), "pos": p, "gap": gap, "laps_since_stop": since,
                        "pace": last[i] if i < len(last) and last[i] and last[i] > 0 else None})
        return sorted(out, key=lambda r: r["pos"])

    def replan(self, lc):
        m = self.live_model()
        tank = self.tank()
        left = self.g("SessionTimeRemain", -1)
        if not m or not tank or left is None or left <= 0 or left > 86400:
            return
        fuel = self.g("FuelLevel", 0) or 0
        temp = self.g("TrackTempCrew")
        # ic176: plans may only ask for the saving he's actually doing (+1 %), rounded up to the planner's 2 % steps
        try:
            fl_recent = [x for x in list(getattr(self.b, "fuel_laps", []) or [])[-3:] if x and x > 0]
            base = float(m.get("fuel_lap") or 0)
            achieved = max(0.0, (1 - (sum(fl_recent) / len(fl_recent)) / base) * 100) if fl_recent and base > 0 else 0.0
        except Exception:
            achieved = 0.0
        import math as _m
        max_save = min(8.0, 2.0 * _m.floor((achieved + 1.0) / 2.0))
        plans = S.best_plans(m, left, tank, fuel, self.tyre_age, 0.0, temp, lc, max_save=max_save)
        if not plans:
            return
        per_tank = tank / m["fuel_lap"]
        laps_left = plans[0]["res"]["laps"] - lc
        rv = self.rivals()
        beats = []
        for o in plans:
            ol = S.rival_outlook(m, o["res"], o["res"]["laps"] - lc, rv, per_tank) if rv else []
            o["outlook"] = ol
            beats.append(sum(1 for x in ol if x["beat"]))
        rec = max(range(len(plans)), key=lambda i: (beats[i], -i))
        # ic174 (#678, 2026-10-31, Angelo: "the radio keeps telling me each stint inaccurate ... the logic for fuel needs
        # refinement"): in the 10-31 race the pick swapped between plans that needed 6-8 % fuel saved a lap and plans that
        # didn't (3 stops, 2, 3, 1, 2, 1 within an hour) - he wasn't saving that much, so the "1 stop" plans were never
        # possible and he needed extra splashes. A saving plan is only recommended while his last laps actually save it.
        try:
            fl_recent = [x for x in list(getattr(self.b, "fuel_laps", []) or [])[-3:] if x and x > 0]
            base = float(m.get("fuel_lap") or 0)
            achieved = max(0.0, (1 - (sum(fl_recent) / len(fl_recent)) / base) * 100) if fl_recent and base > 0 else 0.0
            ok = [i for i, o in enumerate(plans) if float(o["plan"].get("save", 0) or 0) <= achieved + 1.0]
            if ok:
                rec = max(ok, key=lambda i: (beats[i], -i))
        except Exception:
            pass
        # ic176 (#697, research - Porsche / Mercedes / Heilmeier: plan before, pick during; a single forecast flips with
        # noise): COMMIT to the announced plan. Switch only when (a) it no longer makes the finish, (b) a real event
        # (a caution, new damage, fuel use more than 3 % off what the plan was made on), or (c) the new plan is clearly
        # better - at least 10 s of race time or a lap. Otherwise keep the committed plan (B / C are tracked silently).
        forced, event = False, self._event(m)
        if self.last_sig is not None:
            cur = next((i for i, o in enumerate(plans) if len(o["res"]["stops"]) == self.last_sig[0]
                        and float(o["plan"].get("save", 0) or 0) == float(self.last_sig[2] or 0)), None)
            if cur is None:
                forced = True                                   # the committed plan doesn't make it any more
            elif cur != rec and not event:
                a_, b_ = plans[cur]["res"], plans[rec]["res"]
                gain = (a_["time"] - b_["time"]) if a_["laps"] == b_["laps"] else (b_["laps"] - a_["laps"]) * 200.0
                if gain < 10.0:
                    rec = cur
        self.plans, self.rec = plans, rec
        self.outlook = plans[rec].get("outlook", [])
        r = plans[rec]["res"]
        first = r["stops"][0] if r["stops"] else None
        sig = (len(r["stops"]), first["lap"] if first else None, plans[rec]["plan"]["save"])
        if self.last_sig is None:
            self.last_sig = sig
            self._commit_fl = float(m.get("fuel_lap") or 0)
            self.say_plan(rec, intro="Race plan")
        elif sig[0] != self.last_sig[0] or (sig[1] and self.last_sig[1] and abs(sig[1] - self.last_sig[1]) >= 2) or sig[2] != self.last_sig[2]:
            # only when the new plan holds for two laps in a row (no flip-flopping on the radio) - unless forced / an event
            if self._pending_sig == sig or forced or event:
                why = event or ("the old plan doesn't make the finish" if forced else "") or self._why()
                self.last_sig, self._pending_sig = sig, None
                self._commit_fl = float(m.get("fuel_lap") or 0)
                self.say_plan(rec, intro=f"Strategy update{(', ' + why) if why else ''}")
            else:
                self._pending_sig = sig
        else:
            self._pending_sig = None
            if getattr(self, "_lost", 0) > 6:
                lost, self._lost = self._lost, 0
                ahead = [x for x in self.outlook if x["beat"]]
                self.speak("ENGINEER", f"You lost {lost:.0f} seconds. Plan {'ABC'[rec]} is still the best one"
                           + (f", you still get the {ahead[0]['num']}." if ahead else "."))
        self.emit({"t": "strat", "s": self.state()})

    def _event(self, m):
        """ic176: a real reason to change the plan: a caution, new damage, or fuel use > 3 % off the plan's. '' = none."""
        try:
            fl_ = int(self.g("SessionFlags", 0) or 0)
            caution = bool(fl_ & 0x0000C000)
            if caution and not getattr(self, "_ev_caution", False):
                self._ev_caution = True
                return "caution"
            if not caution:
                self._ev_caution = False
            rep = float(self.g("PitRepairLeft", 0) or 0)
            if rep > 0 and not getattr(self, "_ev_damage", False):
                self._ev_damage = True
                return "we have damage"
            if rep <= 0:
                self._ev_damage = False
            c0, c1 = float(getattr(self, "_commit_fl", 0) or 0), float(m.get("fuel_lap") or 0)
            if c0 > 0 and c1 > 0 and abs(c1 - c0) / c0 > 0.03:
                self._commit_fl = c1
                return "fuel use has changed"
        except Exception:
            pass
        return ""

    def _why(self):
        lost = getattr(self, "_lost", 0)
        self._lost = 0
        return f"you lost {lost:.0f} seconds" if lost > 4 else ""

    def say_plan(self, i, intro="Plan"):
        o = self.plans[i]
        d = S.describe(o, self.b.metric(), "ABC"[i])
        r = o["res"]
        if r["stops"]:
            s0 = r["stops"][0]
            u = f"{s0['fuel']:.0f} litres" if self.b.metric() else f"{s0['fuel'] / 3.785:.1f} gallons"
            msg = f"{intro}: plan {d['name']}. {d['stops']} stop{'s' if d['stops'] != 1 else ''}, first on lap {s0['lap']}, {u}{', tyres' if s0['tyres'] else ', no tyres'}."
        else:
            msg = f"{intro}: plan {d['name']}. No stop, you make it to the end."
        if o["plan"]["save"]:
            msg += f" Save {o['plan']['save']:.0f} percent fuel a lap."
        beat = [x for x in o.get("outlook", []) if x["beat"]]
        if beat:
            msg += " That gets you ahead of the " + " and the ".join(str(x["num"]) for x in beat[:2]) + "."
        else:
            # nobody beaten on strategy alone: how much pace would it take for the next car?
            laps_left = max(1, r["laps"] - (self.last_lc or 0))
            near = [x for x in o.get("outlook", []) if 0 < x["final_gap"] < laps_left * 1.0]
            if near:
                x = min(near, key=lambda x: x["final_gap"])
                msg += f" To get the {x['num']} you need {x['final_gap'] / laps_left:.1f} a lap more."
        self.speak("ENGINEER", msg)

    # ------------------------------------------------------------ formation lap rundown (strategist)
    def _formation(self, b):
        """Race only: once on the formation lap (or 30 s on the grid), the strategist runs through the race.
        One line every few seconds, held while you brake or turn; stops the moment the race starts."""
        st = self.g("SessionState", 0) or 0
        if not b.is_race():
            return
        if st >= 4:                                   # racing: anything not said yet is dropped
            self.rundown = []
            if self.rc in ("call", "wait"):
                self.rc = "missed"                    # no answer before the start: no brief this race
            return
        if st == 3 and self._rd_st != 3:              # the engineer says "formation lap" + track temp first
            self._rd_next = max(self._rd_next, time.time() + 32)
        self._rd_st = st
        if not getattr(getattr(self, "s", None), "formation_brief", True):
            self.rundown = []
            return
        if not self.briefed and self.g("IsOnTrack", False):
            if st in (1, 2):
                self._grid_since = self._grid_since or time.time()
            if st == 3 or (self._grid_since and time.time() - self._grid_since > 30):
                self.briefed = True
                self.rc = "call"                          # first a radio check; the brief only if he answers
                self._rd_next = max(self._rd_next, time.time() + 2)
        if self.rc == "call" and time.time() >= self._rd_next and (getattr(self, "idle", None) is None or self.idle()):
            if ((self.g("Speed", 0) or 0) <= 3 or ((self.g("Brake", 0) or 0) <= 0.15 and abs(self.g("SteeringWheelAngle", 0) or 0) <= 0.6)) and (self.g("CarLeftRight", 0) or 0) <= 1:
                from .strat_lines import Lines
                self.rc = "wait"
                self.speak("STRATEGIST", Lines(seed=int(time.time())).say("rc")["text"])
                self.log("[strategy] radio check: waiting for the driver to key up")
        idle = getattr(self, "idle", None)                # wait until the last line has actually been said
        if self.rundown and time.time() >= self._rd_next and (idle is None or idle()):
            moving = (self.g("Speed", 0) or 0) > 3            # 2026-10-26: sitting on the grid holding the brake is not "busy"
            busy = moving and ((self.g("Brake", 0) or 0) > 0.15 or abs(self.g("SteeringWheelAngle", 0) or 0) > 0.6) \
                or (self.g("CarLeftRight", 0) or 0) > 1          # a car alongside: the spotter has the radio
            self._rd_busy0 = (getattr(self, "_rd_busy0", None) or time.time()) if busy else None
            if busy and time.time() - self._rd_busy0 < 12:      # never held back more than 12 s (request: "nobody is responding")
                return
            self._rd_busy0 = None
            line = self.rundown.pop(0)
            import re as _re
            for sent in _re.split(r"(?<=[.!?])\s+", line):     # one message, said sentence by sentence
                if sent.strip():                                # (if the spotter cuts in, only that sentence is repeated)
                    self.speak("STRATEGIST", sent.strip())
            self._rd_next = time.time() + 3.5 + len(line) / 16     # roughly the time to say it, plus a breath

    def _debrief(self, b):
        """Race only: about 10 s after the chequered flag the strategist gives the facts of the race
        (2026-10-24). Each line only when it applies; said sentence by sentence like the rundown."""
        if self.db_done or not b.is_race() or not getattr(b, "green_seen", False):
            return
        if getattr(getattr(self, "s", None), "debrief", True) is False:
            return
        st = self.g("SessionState", 0) or 0
        # 2026-10-24 (driver request): SessionState 5 means the LEADER has the chequered flag - she was debriefing while
        # you were still on your last lap. Now: after YOU cross the line (the engineer's finish), or once the
        # session is in cool-down (6+) if you never cross it (retired, towed).
        if not (getattr(b, "finished", False) or st >= 6):
            return
        now = time.time()
        if self.db_at is None:
            self.db_at = now + 10
            return
        if now < self.db_at or (getattr(self, "idle", None) and not self.idle()):
            return
        self.db_done = True
        from .strat_lines import Lines, f_pos, f_places, f_nth, f_stops, f_car, f_incs, f_ir, f_litres
        L = Lines(seed=int(now))
        out = []
        n_ = self.debrief_numbers(b)         # memory (2026-10-24): the numbers live in one place, the Team-tab debrief reuses them
        pos = n_["pos"]
        if pos:
            out.append(L.say("db_pos", pos=f_pos(pos))["text"])
            sp = n_["start_pos"]
            if sp:
                d = sp - pos
                out.append(L.say("db_up", places=f_places(d))["text"] if d > 0 else
                           L.say("db_down", places=f_places(-d))["text"] if d < 0 else L.say("db_same")["text"])
        if n_["best_rank"]:
            out.append(L.say("db_best", nth=f_nth(n_["best_rank"]))["text"])
        if n_["fastest_me"]:
            out.append(L.say("db_fl_me")["text"])
        elif n_["fastest_car"] is not None:
            out.append(L.say("db_fl", car=f_car(n_["fastest_car"]))["text"])
        n = n_["stops"]
        out.append(L.say("db_stops0")["text"] if n == 0 else L.say("db_stops1")["text"] if n == 1 else
                   L.say("db_stops", nstops=f_stops(n))["text"])
        inc = n_["incidents"]
        if inc is not None:
            out.append(L.say("db_clean")["text"] if inc == 0 else L.say("db_inc", incs=f_incs(int(inc)))["text"])
        ir = n_["ir"]
        if ir is not None and abs(ir) >= 3:
            out.append(L.say("db_ir_up" if ir > 0 else "db_ir_down", ir=f_ir(ir))["text"])
        fuel = n_["fuel_left"]
        if fuel and fuel >= 1:
            out.append(L.say("db_fuel", fuel=f_litres(fuel))["text"])
        out.append(L.say("db_end")["text"])
        import re as _re
        for line in out:
            for sent in _re.split(r"(?<=[.!?])\s+", line):
                if sent.strip():
                    self.speak("STRATEGIST", sent.strip())
        self.log("[strategy] post-race debrief: " + " ".join(out))

    def debrief_numbers(self, b):
        """The facts of the race for the debrief (memory, 2026-10-24: said by _debrief, stored by memory.py).
        -> {pos, start_pos, best_rank, best, fastest_me, fastest_car, stops, incidents, ir, fuel_left}"""
        me = b.me()
        pos = b.class_pos(me) or None
        out = {"pos": pos, "start_pos": getattr(b, "start_pos", None), "best_rank": None, "best": None,
               "fastest_me": False, "fastest_car": None, "stops": self.stint, "incidents": None, "ir": None, "fuel_left": None}
        try:
            best = self.g("CarIdxBestLapTime") or []
            cid, _ = b.my_class()
            cls = [i for i in b.class_cars(cid) if i < len(best) and best[i] and best[i] > 0]
            if me in cls:
                out["best_rank"] = 1 + sum(1 for i in cls if best[i] < best[me])
                out["best"] = float(best[me])
            allb = [(best[i], i) for i in range(len(best)) if best[i] and best[i] > 0]
            if allb:
                _, fi = min(allb)
                if fi == me:
                    out["fastest_me"] = True
                else:
                    num = b.car_num(fi)
                    if num is not None and str(num).isdigit():
                        out["fastest_car"] = int(num)
        except Exception as e:
            self.log(f"[strategy] debrief laps: {e!r}")
        inc = self.g("PlayerCarMyIncidentCount")
        out["incidents"] = int(inc) if inc is not None else None
        try:
            out["ir"] = b.x.irating_now(pos) if pos else None
        except Exception:
            pass
        fuel = self.g("FuelLevel")
        out["fuel_left"] = float(fuel) if fuel else None
        return out

    def answer(self, intent):
        """Strategy questions on the radio button, answered by the strategist (2026-10-23). -> True if she answered."""
        b = self.b
        if b is None:
            return False
        from .strat_lines import Lines, f_litres, f_laps, f_lap, f_pct, PERCENT
        L = Lines(seed=int(time.time()))
        out = []
        if intent == "fuel_per_lap":
            fl = b.fuel_lap_est()
            if not fl:
                return False
            out.append(L.say("sa_fuel_lap" if b.fuel_laps else "sa_fuel_hist", fuel=f_litres(fl))["text"])
        elif intent in ("fuel", "next_stop"):
            # 2026-10-24 fix (request: "the logic is bad"): judge the fuel against the NEXT STOP when one is
            # planned (not the flag), never ask for an impossible save, and stay quiet when the fuel isn't known
            # (replays report an empty tank).
            fl, ltg = b.fuel_lap_est(), b.laps_to_go()
            fuel = self.g("FuelLevel", 0) or 0
            done = self.g("LapCompleted", 0) or self.last_lc or 0
            nxt = None
            if self.plans and b.is_race():
                o = self.plans[self.rec if isinstance(self.rec, int) else 0]
                ahead = [s_ for s_ in o["res"]["stops"] if s_["lap"] > done]
                nxt = int(ahead[0]["lap"]) if ahead else None
                if intent == "next_stop":
                    out.append(L.say("sa_box", lap=f_lap(nxt))["text"] if nxt else L.say("sa_nostop")["text"])
            if not out:
                if not fl or not ltg or fuel <= 0.05:
                    return False                          # fuel unknown: let the engineer say so
                have = fuel / fl
                target = (nxt - done) if nxt else ltg       # laps until the stop, or to the end
                if intent == "next_stop":                 # no plan: work it out from the fuel
                    if have >= ltg + 0.5 or (1 - have / (ltg + 0.15)) * 100 <= 8:   # makes it, or makes it with a small save
                        out.append(L.say("sa_nostop")["text"])
                    else:
                        out.append(L.say("sa_box", lap=f_lap(max(done + 1, min(60, done + int(have)))))["text"])
                else:
                    # ic170 (Angelo: "We're short. You've got 8 laps, we need 8"): what we have rounded DOWN, what we need
                    # rounded UP; good with a quarter lap spare, and "short" only when the numbers really are short
                    import math as _m
                    hl, nl = max(1, min(60, int(have))), max(1, min(60, int(_m.ceil(target - 1e-6))))
                    if have >= target + 0.25 or hl >= nl:
                        out.append(L.say("sa_fuel_ok", flaps=f_laps(hl), laps=f_laps(nl))["text"])
                    else:
                        need = (1 - have / (target + 0.15)) * 100
                        sents = L.say("sa_fuel_short", flaps=f_laps(hl), laps=f_laps(nl), pct=f_pct(min(PERCENT, key=lambda x: abs(x - max(1.0, need)))))["text"]
                        if need <= 8:                     # saving can fix it
                            out.append(sents)
                        else:                             # it can't: say we're short, then when we box
                            import re as _r
                            out.append(" ".join(_r.split(r"(?<=[.!?])\s+", sents)[:2]))
                            out.append(L.say("sa_box", lap=f_lap(max(done + 1, min(60, done + int(have)))))["text"])
        elif intent == "tyres":
            # "strategist, how are the tyres?" (#453, 2026-10-28): laps on this set (counted live since the last tyre
            # change) and whether the plan changes them. Nothing known (no race plan / no lap on them yet) = the
            # engineer answers.
            laps = int(self.tyre_age or 0)
            if not (self.plans and b.is_race()) or not 1 <= laps <= 60:
                return False
            done = self.g("LapCompleted", 0) or self.last_lc or 0
            o = self.plans[self.rec if isinstance(self.rec, int) else 0]
            ahead = [s_ for s_ in o["res"]["stops"] if s_["lap"] > done]
            change = bool(ahead and ahead[0].get("tyres"))
            out.append(L.say("sa_tyres", variant=1 if change else 0, laps=f_laps(laps))["text"])
        else:
            return False
        import re as _re
        for line in out:
            for sent in _re.split(r"(?<=[.!?])\s+", line):
                if sent.strip():
                    self.speak("STRATEGIST", sent.strip())
        return True

    def dry_no_rain(self):
        """"Strategist, do we need wets?" -> True when the track is dry, it isn't raining and no rain is forecast
        (live data; an unknown forecast counts as none, like the briefing). Then she says "No rain expected"."""
        if self.b is None:
            return False
        lvl = self.wet_lvl or int(round(self.g("TrackWetness", 0) or 0))
        if lvl > 1 or self.raining or (self.g("Precipitation", 0) or 0) > 0.005 or self.g("WeatherDeclaredWet"):
            return False
        try:
            fc = self._forecast() or {}
            rain = fc.get("rain") if isinstance(fc, dict) else None
        except Exception:
            rain = None
        return not (rain and rain >= 15)          # the briefing mentions rain from 15 %

    def radio_ack(self):
        """The driver keyed up after her radio check -> she answers and gives the brief. -> True if it was for her."""
        if self.rp.radio_ack():                     # practice: answering her run-plan radio check
            return True
        if self.rc not in ("call", "wait"):
            return False
        from .strat_lines import Lines
        self.rc = "ok"
        try:
            lines = self.formation_lines()
        except Exception as e:
            self.log(f"[strategy] rundown: {e!r}")
            lines = []
        self.rundown = [Lines(seed=int(time.time())).say("rc_ok")["text"]] + lines
        self._rd_next = time.time() + 0.8
        self.log("[strategy] radio check answered: brief follows")
        return True

    def _forecast(self):
        """This week's scheduled race here (length, rain chance, forecast temperature), if known."""
        try:
            from . import schedule as SC
            wk = self.b.info("WeekendInfo", {}) or {}
            sc = SC.series(rid=wk.get("SeriesID")) if wk.get("SeriesID") else None
            return SC.next_at(sc, wk.get("TrackDisplayName", "")) if sc else None
        except Exception as e:
            self.log(f"[strategy] schedule: {e!r}")
            return None

    def formation_lines(self):
        """The rundown, said like a real strategist: laps of fuel first, then the amount. -> list of sentences."""
        from . import rain as R
        from .strat_lines import Lines, track_lap1, f_mins, f_laps, f_lap, f_pos, f_litres, f_gallons, f_pct, f_stops
        L = Lines(seed=int(time.time()))
        out = [[]]                                       # one radio message per topic
        say = lambda lid, **f: out[-1].append(L.say(lid, **f)["text"])
        nxt = lambda: out.append([]) if out[-1] else None
        m = self.model(force=True) or {}
        race_s, tank = self.race_seconds(), self.tank()
        nx = self._forecast() or {}
        rain = nx.get("rain")
        mins = round(race_s / 60) if race_s else nx.get("min")
        base, fl = m.get("base"), m.get("fuel_lap")
        met = self.b.metric()
        amt = f_litres if met else f_gallons
        laps = int(race_s / base) + 1 if race_s and base else None
        if mins and laps:
            say("intro", mins=f_mins(mins), laps=f_laps(laps))
        elif mins:
            say("intro_nolaps", mins=f_mins(mins))
        pos = self.g("PlayerCarClassPosition", 0) or 0
        if pos > 0:
            say("start_pos", pos=f_pos(pos))
        plans = []
        fuel_now = None
        if fl and tank and race_s:
            fuel_now = self.g("FuelLevel") or 0
            if fuel_now <= 0.5:
                # 2026-10-24 (driver request): replays/spectating report an empty tank and no fuel limit, and she used to
                # assume a full tank ("12 laps, no stop"). Use what you normally start this race with instead.
                usual = S.usual_start_fuel(self.car, self.track)
                if usual:
                    fuel_now, tank = usual, min(tank, usual + 1.0)
                    self.log(f"[strategy] no live fuel reading: using your usual start fuel {usual:.1f} L")
                else:
                    fuel_now = None
                    self.log("[strategy] no live fuel reading and no history: skipping the fuel plan")
        if fl and tank and race_s and fuel_now:
            nxt()
            say("fuel_start", flaps=f_laps(int(fuel_now / fl)), fuel=amt(fuel_now))
            plans = S.best_plans(m, race_s, tank, fuel_now, 0, 0.0, self.g("TrackTempCrew"), 0)
        if plans:
            self.plans, self.rec = plans, 0
            self.emit({"t": "strat", "s": self.state()})
            nxt()
            a, sa = plans[0]["res"]["stops"], plans[0]["plan"].get("save", 0)
            if not a:
                say("a_nostop")
            else:
                say("a_one", lap=f_lap(a[0]["lap"])) if len(a) == 1 else say("a_multi", nstops=f_stops(len(a)), lap=f_lap(a[0]["lap"]))
                say("stop_fuel", flaps=f_laps(max(1, round(a[0]["fuel"] / fl))), fuel=amt(a[0]["fuel"]))
                say("tyres_yes" if a[0]["tyres"] else "tyres_no")
            if sa:
                say("save", pct=f_pct(sa))
            if len(plans) > 1:
                nxt()
                b, sb = plans[1]["res"]["stops"], plans[1]["plan"].get("save", 0)
                if not b:
                    say("b_nostop")
                elif len(b) == len(a):
                    say("b_same", lap=f_lap(b[0]["lap"]))
                    if sa and not sb:
                        say("b_nosave")
                else:
                    say("b_other", nstops=f_stops(len(b)), lap=f_lap(b[0]["lap"]))
        nxt()
        wet_now = int(round(self.g("TrackWetness", 0) or 0))
        if wet_now >= 3:
            say(f"wet_now_{min(7, wet_now)}")
        elif rain and rain >= 15 and base:
            say("rain", pct=f_pct(rain, rain=True))
            if plans and plans[0]["res"]["stops"]:
                say("rain_stop")
            mine = self.mine_wet or R.wet_pace(self.car, self.track)[0]
            g = R.lap_on(base, 4, False) - R.lap_on(base, 4, True, mine)
            if g > 0:
                say("rain_box", laps=f_laps(max(1, round((m["lane_loss"] + max(m["tyre_time"], 4)) / g))))
        tk = track_lap1((self.b.info("WeekendInfo", {}) or {}).get("TrackDisplayName", "") or self.track)
        nxt()
        if tk:
            say(tk)
        nxt()
        oc = self._other_classes()                        # "GT3 class cars", "LMP2 and GT3 class cars" ...
        for kind in ("faster", "slower"):
            ns = [n.replace(" class cars", "") for k, n in oc if k == kind]
            if ns:
                say("multi_slower" if kind == "slower" else "multi_faster", cls=" and ".join(ns) + " class cars")
        nxt()
        try:                                              # how long cold tyres take, from his own telemetry
            from . import warmup as W
            w = W.estimate(self.car, self.track)
            if w:
                say("warm", warm=W.phrase_laps(w["laps"]))
                if w.get("first_lap_loss") and w["first_lap_loss"] >= 0.5:
                    say("warm_loss", secs=W.phrase_secs(w["first_lap_loss"]))
        except Exception as e:
            self.log(f"[strategy] warm-up: {e!r}")
        say("close")
        return [" ".join(x) for x in out if x]

    def _other_classes(self):
        """Other classes in this race vs mine -> [("slower"|"faster", "GT3 class cars"), ...] (at most 2)."""
        di = self.b.info("DriverInfo", {}) or {}
        drv = [d for d in (di.get("Drivers") or []) if not d.get("CarIsPaceCar") and d.get("CarClassID") is not None]
        me = next((d for d in drv if d.get("CarIdx") == di.get("DriverCarIdx")), None)
        def name(d):   # #49: iRacing's class name / class number first, the car's name only as a last resort
            c = classes.label(d)
            return f"{c} class cars" if c in ("GTP", "LMP2", "GT3") else None
        if not me:
            return []
        out, seen = [], {name(me)}
        for d in sorted(drv, key=lambda d: float(d.get("CarClassEstLapTime") or 0)):
            n = name(d)
            if n and n not in seen and d.get("CarClassID") != me.get("CarClassID"):
                seen.add(n)
                faster = float(d.get("CarClassEstLapTime") or 0) < float(me.get("CarClassEstLapTime") or 0)
                out.append(("faster" if faster else "slower", n))
        return out[:2]

    def brief(self, pre_race=False):
        """Your pace now vs your race sims, the conditions, and plans A/B/C."""
        m = self.model(force=True)
        if not m or not m.get("fuel_lap"):
            return
        tank, race_s = self.tank(), self.race_seconds() if self.b.is_race() else None
        if not tank:
            return
        sched_temp, rain = None, None
        if not race_s:                     # practice: this series' scheduled race here, else your last race here, else 45 min
            try:
                from . import schedule as SC
                wk = self.b.info("WeekendInfo", {}) or {}
                sc = SC.series(rid=wk.get("SeriesID")) if wk.get("SeriesID") else None
                nx = SC.next_at(sc, wk.get("TrackDisplayName", "")) if sc else None
                if nx and nx.get("min"):
                    race_s = nx["min"] * 60
                    sched_temp = max(nx["temp"]) + 6 if nx.get("temp") else None
                    rain = nx.get("rain")
                    self.speak("ENGINEER", f"This week's race: {nx['min']} minutes" + (f", {rain:.0f} percent chance of rain." if rain and rain >= 10 else "."))
            except Exception as e:
                self.log(f"[strategy] schedule: {e!r}")
            if not race_s:
                ev = S.last_race(self.car, self.track)
                race_s = (ev or {}).get("race_s") or 45 * 60
        now_pace = sorted(self.recent)[len(self.recent) // 2] if self.recent else None
        self.cond = S.conditions(m, self.g("TrackTempCrew"), self.g("TrackWetness"), now_pace)
        plans = S.best_plans(m, race_s, tank, tank, 0, 0.0, sched_temp or self.g("TrackTempCrew"), 0)
        if not plans:
            return
        self.plans, self.rec = plans, 0
        c = self.cond
        if c["pace_diff"] is not None:
            self.speak("ENGINEER", f"Your laps are {abs(c['pace_diff']):.1f} {'faster' if c['pace_diff'] < 0 else 'slower'} than your race sims.")
        if m.get("race_sims"):
            t = f", {abs(c['temp_diff']):.0f} degrees {'hotter' if c['temp_diff'] > 0 else 'cooler'} track" if c["temp_diff"] is not None and abs(c["temp_diff"]) >= 3 else ""
            self.speak("ENGINEER", f"Your race sims were in {c['label']}{t}.")
        if rain and rain >= 15:
            from . import rain as R
            mine, _ = R.wet_pace(self.car, self.track)
            rp = R.rain_plan(m, plans[0]["res"], race_s, rain, mine)
            if rp:
                self.speak("ENGINEER", f"If it rains: {rp[0]}")
        for i in range(len(plans)):
            d = S.describe(plans[i], self.b.metric(), "ABC"[i])
            extra = f", {d['vs_a']:.0f} seconds slower" if i and d["vs_a"] < 900 else ""
            self.speak("ENGINEER", f"Plan {d['name']}: {d['text']}{extra}.")
        self.emit({"t": "strat", "s": self.state()})

    def state(self):
        rp = self.rp.state() if getattr(self, "rp", None) and self.rp.plan else None
        if not self.b or not self.plans:
            return {"plans": [], "rec": 0, "runplan": rp}
        met = self.b.metric()
        out = []
        for i, o in enumerate(self.plans):
            d = S.describe(o, met, "ABC"[i])
            d["outlook"] = o.get("outlook", [])
            out.append(d)
        m = self.m or {}
        return {"plans": out, "rec": self.rec, "cond": self.cond, "learned": m.get("learned", []), "n": m.get("n", 0),
                "sims": m.get("race_sims", 0), "runplan": rp}

    # ------------------------------------------------------------ rain
    def wet_index(self):
        for t in (self.b.info("DriverInfo", {}) or {}).get("DriverTires", []) or []:
            if str(t.get("TireCompoundType", "")).lower().startswith("wet"):
                return int(t.get("TireIndex", 1))
        return 1

    def dry_index(self):
        for t in (self.b.info("DriverInfo", {}) or {}).get("DriverTires", []) or []:
            if not str(t.get("TireCompoundType", "")).lower().startswith("wet"):
                return int(t.get("TireIndex", 0))
        return 0

    def _rain_tick(self):
        from .rain import WET_NAME, tips
        prec = self.g("Precipitation", 0) or 0
        lvl = int(round(self.g("TrackWetness", 0) or 0))
        now = time.time()
        if prec > 0.03 and not self.raining:
            self.raining = True
            self.speak("ENGINEER", "Rain starting.")
            self.speak("ENGINEER", tips(1, seed=int(now), track_key=self.track)[0])   # own line: a track tip has a clip
        elif prec < 0.005 and self.raining:
            self.raining = False
            self.speak("ENGINEER", "Rain has stopped. The track will dry from the racing line.")
        if lvl < 1:
            return
        # wetness changes are announced once they've held for 20 s
        if lvl != self._lvl_cand:
            self._lvl_cand, self._lvl_since = lvl, now
        elif lvl != self.wet_lvl and now - self._lvl_since > 20:
            first = self.wet_lvl is None
            old, self.wet_lvl = self.wet_lvl, lvl
            if not first and (lvl >= 3 or (old or 0) >= 3):
                self.speak("ENGINEER", f"Track now {WET_NAME.get(lvl, 'wet')}.")

    def _rain_lap(self, lc):
        """Each lap: wets or slicks? and one wet-weather tip while it's wet."""
        from . import rain as R
        lvl = self.wet_lvl or int(round(self.g("TrackWetness", 0) or 0))
        if lvl < 2 and self.tyre_call is None:
            return
        if self._rb_quiet():                        # #591: no tyre calls while towed or after the flag (ic155 / ic156)
            return
        m = self.model()
        if not m or not m.get("base"):
            return
        if self.mine_wet is None:
            self.mine_wet, _ = R.wet_pace(self.car, self.track)
        comp = self.g("PlayerTireCompound", 0) or 0
        on_wets = comp == self.wet_index()
        ltg = self.b.laps_to_go() or 10
        ns = self.next_stop()
        stop_cost = m["tyre_time"] if (ns and abs(ns["lap"] - lc) <= 1) else m["lane_loss"] + m["tyre_time"]
        # #591: when the other cars' / your own lap times on each compound measure the gap, that beats the table
        gain, worth = None, None
        try:
            _, x = self.rb.estimate(self.rain_ctx())
            if x["source"] in ("field", "fit", "own") and x["conf"] in ("medium", "high") and x["gain"] is not None:
                gain, worth = x["gain"], x["worth"]
        except Exception as e:
            self.log(f"[rain] estimate: {e!r}")
        change, g, total = R.crossover(m["base"], lvl, ltg, stop_cost, self.mine_wet, on_wets, gain=gain)
        if worth is not None and gain is not None:
            change = bool(worth and gain > 0)       # measured: the gain follows the trend lap by lap (same as the answer)
        declared = self.g("WeatherDeclaredWet")
        if change and lc - self._call_lap >= 2:
            self._call_lap = lc
            if not on_wets:
                if declared is False:
                    self.speak("ENGINEER", f"Wets would be {g:.0f} seconds a lap faster, but they're not allowed yet. Stay out, brake early.")
                else:
                    self.tyre_call = "wet"
                    self.speak("ENGINEER", f"Box this lap for wets. They're about {g:.0f} seconds a lap faster on this track now.")
            else:
                self.tyre_call = "dry"
                self.speak("ENGINEER", f"Track's drying. Slicks are {g:.0f} seconds a lap faster now. Box this lap for slicks.")
        elif not change and self.tyre_call and lc - self._call_lap >= 2:
            self.tyre_call = None
        if lvl >= 3 and lc - self._tip_lap >= 2 and self._call_lap != lc:
            self._tip_lap = lc
            self.speak("ENGINEER", R.tips(1, seed=lc, track_key=self.track)[0])

    # ------------------------------------------------------------ rain brain (#591)
    def _rb_clip(self, sid, fills=None, answer=False):
        """Play an engineer clip if his library has it (a pending rain line isn't there until it's rendered)."""
        b = self.b
        if b is None or not hasattr(b, "say"):
            return False
        from .voice import PRIO_URGENT, PRIO_INFO
        try:
            return bool(b.say(sid, fills or {}, prio=PRIO_URGENT if answer else PRIO_INFO))
        except Exception as e:
            self.log(f"[rain] clip {sid}: {e!r}")
            return False

    def _rb_show(self, role, text):
        """A rain answer / call with no clip yet: shown on the radio card, the overlay caption and the iPad."""
        show = getattr(self, "show", None)
        (show or (lambda r, t: self.log(f"{r}: {t}")))(role, text)

    def _rb_quiet(self):
        """No proactive rain calls: being towed (ic155), after the flag (ic156), not driving, or watching a replay."""
        from . import voice as _v
        b = self.b
        if b is None or _v.TOWING:
            return True
        if getattr(b, "finished", False):
            return True
        return not self.g("IsOnTrack", False) or bool(self.g("IsReplayPlaying", False))

    def _rb_tick(self):
        b = self.b
        t = self.g("SessionTime")
        if t is None:
            return
        when, cls, wi = self._rb_cls
        if abs(t - when) > 30:                       # my class and wet compound: every 30 s is plenty
            try:
                cls = b.class_cars(b.my_class()[0])
            except Exception:
                cls = []
            wi = self.wet_index()
            self._rb_cls = (t, cls, wi)
        self.rb.tick(self.g, b.me(), cls, wi, t=t)

    def rain_ctx(self):
        """What the rain brain needs from the strategist: tyres on, pace, laps left, the stop plan, the forecast."""
        b = self.b
        m = self.model() or {}
        comp = self.g("PlayerTireCompound", None)
        on_wets = comp is not None and int(comp) == self.wet_index()
        lc = self.g("LapCompleted", 0) or self.last_lc or 0
        ns = self.next_stop()
        stint = int(ns["lap"] - lc) if ns and ns.get("lap") and ns["lap"] > lc else None
        lap_s = sorted(self.recent)[len(self.recent) // 2] if self.recent else None
        if not lap_s:
            t = self.g("LapLastLapTime", -1) or -1
            lap_s = t if t > 0 else None
        best = {}
        try:
            arr = self.g("CarIdxBestLapTime") or []
            for i in self._rb_cls[1]:
                if i < len(arr) and arr[i] and arr[i] > 0:
                    best[i] = float(arr[i])
        except Exception:
            pass
        now = time.time()
        fc = getattr(self, "_rb_fc", None)
        if fc is None or now - fc[0] > 600:          # this week's rain chance: read once in ten minutes, not every lap
            pct = None
            try:
                pct = (self._forecast() or {}).get("rain")
            except Exception:
                pass
            fc = self._rb_fc = (now, pct)
        fc_pct = fc[1]
        from .rain_brain import forecast_from_info
        stop_cost = (m["lane_loss"] + max(m.get("tyre_time") or 0, 4.0)) if m.get("lane_loss") else None
        return {"on_wets": on_wets, "base": m.get("base"), "lap_s": lap_s, "laps_left": b.laps_to_go() if b else None,
                "stint_laps": stint, "stop_cost": stop_cost, "stop_soon": bool(stint is not None and stint <= 1),
                "mine": self.mine_wet, "t": self.g("SessionTime"), "best": best, "forecast_pct": fc_pct,
                "forecast": forecast_from_info(b.info("WeekendInfo", {}) if b else {})}

    def rain_answer(self, kind, concepts=()):
        """A radio rain question -> the answer the rain brain gives, or {"route": "tyres"} ("should we change tyres?"
        on a dry track is a tyre-wear question), or None (nothing to say: the old path answers)."""
        if self.b is None:
            return None
        ctx = self.rain_ctx()
        st = self.rb.trend.state()
        dry = (st.get("level") or int(round(self.g("TrackWetness", 0) or 0)) or 1) <= 1 and not st.get("raining") \
            and not self.g("WeatherDeclaredWet", False)
        named = bool(set(concepts or ()) & {"DRYCOMP", "WETCOMP", "RAIN", "RAINW", "CROSS"})
        if kind == "switch" and dry and not ctx["on_wets"] and not named:
            return {"route": "tyres"}
        return self.rb.answer(kind, ctx)

    def next_stop(self):
        """The recommended plan's next stop (for the pit plan)."""
        if not self.plans:
            return None
        r = self.plans[self.rec]["res"]
        return r["stops"][0] if r["stops"] else None
