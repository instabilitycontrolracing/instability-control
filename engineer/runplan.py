"""Practice run plan: the strategist proposes the runs that fill the gaps in what we know for the next race.

Opt-in like the race brief: she does a radio check when you first leave the pits in practice and only
plans if you key up. Then, run by run:
  - in the pits: she says the run and fuels the car for it (pit menu fuel set by the pit crew)
  - on track: quiet, counts your laps; at the target "That's the race sim done. Box this lap."
  - back in the pits: a short summary (pace vs your best, vs your last race sim, fuel per lap), then the next run.
Radio: "skip this run" / "next run", "one more lap", "what's the plan".
No AI involved: plain rules on the stored strategy model.
"""
import time

ORD = ["Run one", "Run two", "Run three", "Run four"]
NRUNS = {1: "one run", 2: "two runs", 3: "three runs", 4: "four runs"}
NAME = {"settle": "settle-in run", "sim": "race sim", "save": "fuel saving run", "long": "long run",
        "wet": "wet run", "quali": "qualifying sim"}


def make_plan(m, base, time_left, wet_now, wet_laps, save_pct):
    """-> list of runs {kind, laps, save} that fit in the time left (seconds), most useful first."""
    if not base:
        return []
    L = lambda secs, lo, hi: int(max(lo, min(hi, round(secs / base))))
    want = [("settle", L(600, 2, 5), 0)]
    if wet_now >= 3 and wet_laps < 6:
        want.append(("wet", L(900, 3, 8), 0))
    sims, learned = m.get("race_sims", 0), m.get("learned", [])
    want.append(("sim", L(1500, 5, 15), 0))
    if save_pct:
        want.append(("save", L(900, 3, 6), save_pct))
    if "tyre wear" not in learned:
        want.append(("long", L(2400, 8, 20), 0))
    want.append(("quali", 2 if base > 120 else 3, 0))
    out, t = [], 0.0
    budget = (time_left or 3600) - 180
    for kind, laps, save in want:
        need = (laps + 2) * base + 90                        # + out lap, in lap, stop
        if kind != "settle" and t + need > budget:
            continue
        out.append({"kind": kind, "laps": laps, "save": save})
        t += need
        if len(out) == 4:
            break
    return out


class RunPlan:
    def __init__(self, st):
        self.st = st                    # the Strategist (speak, g, model, b, pit, tank)
        self.reset()

    def reset(self):
        self.rc = None                  # None -> "wait" -> "ok" / "missed"
        self.rc_t = 0.0
        self.plan, self.cur = [], 0
        self.active = False             # a run is on track
        self.laps, self.times, self.fuels = 0, [], []
        self.done_called = False
        self.extra = 0
        self.onp_prev = True
        self.last_sim_pace = None

    # --------------------------------------------------------- helpers
    def L(self):
        from .strat_lines import Lines
        return Lines(seed=int(time.time() * 1000) % 100000)

    def say(self, lid, **f):
        import re
        t = self.L().say(lid, **f)["text"]
        for s in re.split(r"(?<=[.!?])\s+", t):
            if s.strip():
                self.st.speak("STRATEGIST", s.strip())

    def state(self):
        return {"plan": [{"name": NAME[r["kind"]], "laps": r["laps"], "done": i < self.cur or (i == self.cur and self.done_called)}
                         for i, r in enumerate(self.plan)], "cur": self.cur, "laps": self.laps, "active": self.active}

    def _emit(self):
        self.st.emit({"t": "strat", "s": self.st.state()})

    # --------------------------------------------------------- every tick (practice only)
    def tick(self):
        st = self.st
        onp = bool(st.g("OnPitRoad", False))
        on_track = bool(st.g("IsOnTrack", False))
        if not getattr(getattr(st, "s", None), "formation_brief", True):
            return
        # radio check the first time he leaves the pits
        if self.rc is None and on_track and self.onp_prev and not onp:
            from .strat_lines import Lines
            self.rc, self.rc_t = "wait", time.time()
            st.speak("STRATEGIST", Lines(seed=int(time.time())).say("rc")["text"])
        if self.rc == "wait" and time.time() - self.rc_t > 90:
            self.rc = "missed"                              # no answer: quiet for this session
        if self.rc == "ok" and self.plan:
            if self.onp_prev and not onp and self.cur < len(self.plan):          # out on a run
                self.active, self.laps, self.times, self.fuels, self.done_called, self.extra = True, 0, [], [], False, 0
                self.out_lap = True
                self._emit()
            if not self.onp_prev and onp and self.active:                        # back in
                self.active = False
                self._summary()
                self.cur += 1 if self.done_called or self.laps >= max(1, self.plan[self.cur]["laps"] - 1) else 0
                self._next()
        self.onp_prev = onp

    def radio_ack(self):
        if self.rc != "wait":
            return False
        self.rc = "ok"
        st = self.st
        m = st.model(force=True) or {}
        base = m.get("base")
        try:
            from .rain import wet_pace
            _, nwet = wet_pace(st.car, st.track)
        except Exception:
            nwet = 0
        save = 0
        try:
            from . import strategy as S
            ev = S.last_race(st.car, st.track)
            nx = st._forecast() or {}
            race_s = (nx.get("min") or 0) * 60 or (ev or {}).get("race_s") or 45 * 60
            tank = st.tank()
            if m.get("fuel_lap") and tank:
                pl = S.best_plans(m, race_s, tank, tank, 0, 0.0, st.g("TrackTempCrew"), 0)
                save = pl[0]["plan"].get("save", 0) if pl else 0
        except Exception as e:
            st.log(f"[runplan] {e!r}")
        self.plan = make_plan(m, base, st.g("SessionTimeRemain"), int(round(st.g("TrackWetness", 0) or 0)), nwet, save)
        self.cur = 0
        if not self.plan:
            return True
        self.active = not bool(st.g("OnPitRoad", False))   # he's already out: this outing is run one
        self.out_lap = True
        self.laps, self.times, self.fuels, self.done_called, self.extra = 0, [], [], False, 0
        from .strat_lines import Lines
        self.say("rp_ok")
        self.say("rp_intro", nruns=NRUNS[len(self.plan)])
        for i, r in enumerate(self.plan):
            self._say_run(i, r)
        self.say("rp_now", run=ORD[0])
        self._emit()
        return True

    def _say_run(self, i, r):
        from .strat_lines import f_laps, f_pct
        k = {"settle": "rp_settle", "sim": "rp_sim", "save": "rp_save", "long": "rp_long", "wet": "rp_wet", "quali": "rp_quali"}[r["kind"]]
        f = {"run": ORD[i], "laps": f_laps(r["laps"])}
        if r["kind"] == "save":
            f["pct"] = f_pct(r["save"])
        if r["kind"] == "wet":
            f.pop("laps")
        self.say(k, **f)

    def _next(self):
        st = self.st
        if self.cur >= len(self.plan):
            self.say("rp_all_done"); self._emit(); return
        r = self.plan[self.cur]
        self.say("rp_next", run=ORD[self.cur], runname=NAME[r["kind"]])
        self._fuel_for(r)
        self._emit()

    def _fuel_for(self, r):
        """Pit menu fuel so he has fuel for this run (+ out and in lap)."""
        from .strat_lines import f_laps, f_litres, f_gallons
        st = self.st
        m = st.model() or {}
        fl = m.get("fuel_lap")
        tank = st.tank()
        if not fl or not tank:
            return
        laps = r["laps"] + 2 if r["kind"] != "quali" else r["laps"] + 1
        need = min(tank, laps * fl * (1 - r.get("save", 0) / 100))
        now = st.g("FuelLevel") or 0
        add = max(0.0, need - now)
        if getattr(st, "pit", None) and add > 0.5:
            try:
                st.pit._cmd("fuel", min(999, round(add)))
            except Exception as e:
                st.log(f"[runplan] fuel: {e!r}")
        amt = f_litres if st.b.metric() else f_gallons
        self.say("rp_fuel", laps=f_laps(r["laps"]), fuel=amt(max(need, now)))

    # --------------------------------------------------------- each lap (from the Strategist)
    def lap(self, t, clean, used):
        if not (self.rc == "ok" and self.active and self.cur < len(self.plan)):
            return
        r = self.plan[self.cur]
        if getattr(self, "out_lap", False):                  # the lap he left the pits on doesn't count
            self.out_lap = False
            return
        self.laps += 1
        if clean and t > 0:
            self.times.append(t)
        if used and used > 0:
            self.fuels.append(used)
        if not self.done_called and self.laps >= r["laps"] + self.extra:
            self.done_called = True
            self.say("rp_done", runname=NAME[r["kind"]])
        self._emit()

    def _summary(self):
        from .warmup import phrase_secs
        from .strat_lines import f_litres, f_gallons
        st = self.st
        if len(self.times) < 2 or (self.cur < len(self.plan) and self.plan[self.cur]["kind"] in ("settle", "quali")):
            return                                          # settle-in / quali runs aren't about average pace
        m = st.model(force=True) or {}
        best = m.get("best") or min(self.times)
        avg = sorted(self.times)[len(self.times) // 2]
        d = avg - best
        if d < 0.25:
            self.say("rp_pace_close")
        else:
            self.say("rp_pace", secs=phrase_secs(d))
        r = self.plan[self.cur] if self.cur < len(self.plan) else {}
        if r.get("kind") == "sim" and m.get("sim_pace"):
            dd = avg - m["sim_pace"]
            if abs(dd) >= 0.4:
                self.say("rp_vs_sim_slower" if dd > 0 else "rp_vs_sim_faster", secs=phrase_secs(abs(dd)))
        if self.fuels:
            fu = sorted(self.fuels)[len(self.fuels) // 2]
            self.say("rp_fuel_used", fuel=(f_litres if st.b.metric() else f_gallons)(fu))

    # --------------------------------------------------------- radio
    def command(self, text):
        """'skip this run' / 'next run' / 'one more lap' / 'what's the plan'. -> True if handled."""
        t = text.lower()
        if self.rc != "ok" or not self.plan:
            return False
        if "skip" in t or "next run" in t:
            if self.cur < len(self.plan):
                self.say("rp_skip")
                if self.active:
                    self.done_called = True
                else:
                    self.cur += 1; self._next()
            return True
        if "one more lap" in t or "another lap" in t:
            self.extra += 1; self.done_called = False
            self.say("rp_more"); return True
        if "plan" in t and ("what" in t or "run" in t):
            for i in range(self.cur, len(self.plan)):
                self._say_run(i, self.plan[i])
            return True
        return False
