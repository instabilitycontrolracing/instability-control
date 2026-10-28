"""Race memory, pre-race meeting, debrief and what-if (2026-10-24). No iRacing needed.

    python -m unittest tests.test_memory -v
"""
import os, sys, tempfile, time, types, unittest

_TMP = tempfile.mkdtemp(prefix="ic_mem_")
os.environ["LOCALAPPDATA"] = _TMP                 # every store goes to a scratch folder (paths are set at import)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engineer import memory as M, briefing as BR, strategy as S   # noqa: E402

GT3, GT3B, GTP = "bmwm4gt3", "mercedesamgevogt3", "bmwlmdh"
SPA = "spa 2024 up"


def summary(car=GT3, track=SPA, at=None, **kw):
    s = {"car": car, "track": track, "car_name": "BMW M4 GT3", "track_name": "Spa", "session": "Practice",
         "at": at or time.time(), "laps": 12, "clean_laps": 10, "best": 138.2, "median": 139.0, "fuel_lap": 3.1,
         "tyre_deg": 0.04, "stints": [12], "stops": [], "pit_loss": 27.0, "incidents": 4, "spins": 1, "spin_at": ["Eau Rouge"],
         "offs": 2, "off_at": ["Bus Stop", "Bus Stop"], "corners": [{"name": "Pouhon", "lost": 0.41, "n": 9}, {"name": "Bus Stop", "lost": 0.2, "n": 9}],
         "weather": {"track_temp": 31.0}, "setup": "spa_race_v2", "tank": 100.0,
         "notes": [{"lap": 5, "corner": "Pouhon", "text": "rear loose on entry"}]}
    s.update(kw)
    return s


def reset_store():
    for p in (M.PATH, S.DB_PATH):
        try:
            os.remove(p)
        except OSError:
            pass


def fill_strategy_db(car=GT3, track=SPA, laps=40, fuel=3.0, base=138.0):
    """Synthetic stored laps + stops so strategy.model() learns this car here."""
    tank = 100.0
    f = tank
    for i in range(laps):
        age = i % 20 + 1
        t = base + 0.025 * f + 0.04 * age
        S.record_lap(car, track, i + 1, t, f, fuel, True, age, i // 20, 30.0, 20.0, 1.0, "practice")
        f = f - fuel if f - fuel > 10 else tank
    S.record_stop(car, track, 20, 26.0, 30.0, 60.0, False)
    S.record_stop(car, track, 40, 27.0, 32.0, 62.0, True)


class TestStore(unittest.TestCase):
    def setUp(self):
        reset_store()

    def test_car_class(self):
        self.assertEqual(M.car_class("bmwm4gt3"), "GT3")
        self.assertEqual(M.car_class("bmwlmdh"), "GTP")
        self.assertEqual(M.car_class("porsche963gtp"), "GTP")
        self.assertEqual(M.car_class("dallarap217"), "LMP2")
        self.assertEqual(M.car_class("whatever", "GT3 Class"), "GT3")
        self.assertEqual(M.car_class("mx5 mx52016"), "")

    def test_record_and_recall(self):
        M.record_session(summary(at=1000.0))
        M.record_session(summary(at=2000.0, best=137.9, session="Race", race={"pos": 4, "start_pos": 7}))
        r = M.recall(GT3, SPA)
        self.assertEqual(r["source"], M.THIS_CAR)
        self.assertEqual(len(r["sessions"]), 2)
        self.assertEqual(r["sessions"][0]["at"], 2000.0)              # newest first
        ag = r["aggregates"]
        self.assertEqual(ag["sessions"], 2)
        self.assertEqual(ag["races"], 1)
        self.assertAlmostEqual(ag["best"], 137.9)
        self.assertAlmostEqual(ag["fuel_lap"], 3.1)
        self.assertEqual(ag["trouble"][0]["name"], "Pouhon")
        self.assertEqual(ag["hotspots"][0], "Bus Stop")
        self.assertEqual(ag["finishes"], [4])
        self.assertEqual(ag["notes"][0]["text"], "rear loose on entry")
        self.assertEqual(M.last_combo(), (GT3, SPA))

    def test_same_session_not_doubled(self):
        M.record_session(summary(at=1000.0))
        M.record_session(summary(at=1000.0, laps=13))
        self.assertEqual(len(M.recall(GT3, SPA)["sessions"]), 1)

    def test_similar_car_fallback(self):
        M.record_session(summary(car=GT3B, car_name="Mercedes AMG GT3"))
        M.record_session(summary(car=GTP, car_name="BMW M Hybrid V8", best=125.0))
        r = M.recall(GT3, SPA)                                          # never drove the BMW GT3 here
        self.assertEqual(r["source"], M.SIMILAR)
        self.assertEqual(r["from_cars"], ["Mercedes AMG GT3"])          # same class only: no GTP
        self.assertAlmostEqual(r["aggregates"]["best"], 138.2)
        self.assertEqual(M.recall(GT3, "monza full")["source"], M.NONE)  # other track: nothing


class FakeCorners:
    def __init__(self, marks):
        self.marks = marks

    def nearest_behind(self, d, within=400):
        best = None
        for a, b, k in self.marks:
            if a - 20 <= d and d - b <= within:
                best = k
        return best


class FakeBrain:
    """Just enough of Brain for the recorder and the strategist's debrief numbers."""
    def __init__(self, sess_type="Race"):
        self.src = {"IsOnTrack": True, "OnPitRoad": False, "Speed": 50.0, "LapCompleted": 0, "LapDist": 0.0,
                    "SessionTime": 0.0, "FuelLevel": 100.0, "PlayerCarMyIncidentCount": 0, "LapLastLapTime": -1,
                    "TrackTempCrew": 30.0, "AirTemp": 20.0, "TrackWetness": 1, "CarIdxBestLapTime": [138.5, 139.0, 139.5]}
        self.sess_num, self.sess_type = 2, sess_type
        self.c = FakeCorners([(100, 200, "turn_1"), (500, 650, "pouhon")])
        self.finished, self.start_pos, self.tl_count, self.caution_on = False, 6, 0, False
        self.t = 1000.0
        self.clock = lambda: self.t
        self.x = types.SimpleNamespace(irating_now=lambda pos: 24)

    def g(self, k, d=None):
        v = self.src.get(k)
        return d if v is None else v

    def info(self, sec, d=None):
        return {"DriverInfo": {"DriverCarIdx": 1, "DriverCarFuelMaxLtr": 100.0, "DriverCarMaxFuelPct": 1.0, "DriverSetupName": "race_v2",
                               "Drivers": [{"CarIdx": 1, "CarPath": GT3, "CarScreenName": "BMW M4 GT3", "CarClassShortName": "GT3"}]},
                "WeekendInfo": {"TrackName": SPA, "TrackDisplayName": "Spa", "TrackSkies": "Clear"}}.get(sec, d)

    def me(self): return 1
    def is_race(self): return "race" in self.sess_type.lower()
    def class_pos(self, i): return 3
    def my_class(self): return 0, "GT3"
    def class_cars(self, cid): return [0, 1, 2]
    def car_num(self, i): return "77"
    def metric(self): return True


def drive(rec, b, laps=6, slow_laps=(2, 3), spin_lap=4, pit_lap=5, strat=None):
    """Lap distances 0..1000 m, 0.1 s a step; Pouhon 0.5 s slower on two laps; a spin, an off, a pit stop."""
    for n in range(1, laps + 1):
        t0 = b.src["SessionTime"]
        for d in range(0, 1000, 10):
            b.src["LapDist"] = float(d)
            dt = 0.1
            if n in slow_laps and 500 <= d <= 650:
                dt += 0.5 / 16
            b.src["SessionTime"] += dt
            b.t += dt
            if n == spin_lap and d == 120:
                b._spin_said = b.t
            if n == spin_lap and d == 560:
                b.tl_count += 1
                b.src["PlayerCarMyIncidentCount"] += 1
            rec.tick(b, strat)
        if n == pit_lap:                                  # in the pits for 3 s, 20 L added
            b.src["OnPitRoad"] = True
            for _ in range(30):
                b.src["Speed"] = 0.0; b.t += 0.1; rec.tick(b, strat)
            b.src["FuelLevel"] += 20
            b.src["OnPitRoad"] = False; b.src["Speed"] = 50.0
            rec.tick(b, strat)
        b.src["FuelLevel"] -= 3.0
        b.src["LapCompleted"] = n
        b.src["LapLastLapTime"] = b.src["SessionTime"] - t0
        rec.tick(b, strat)


class TestRecorder(unittest.TestCase):
    def setUp(self):
        reset_store()

    def _run(self, finish_race=True):
        done = []
        rec = M.Recorder(on_done=lambda s, d: done.append((s, d)), log=lambda *a: None)
        b = FakeBrain()
        rec.tick(b)
        drive(rec, b)
        if finish_race:
            b.finished = True
            b.src["Speed"] = 0.0
            rec.tick(b)
        else:
            rec.tick(None)                                 # iRacing closed
        for _ in range(100):
            if done:
                break
            time.sleep(0.05)
        return done

    def test_race_summary_and_debrief_flag(self):
        done = self._run()
        self.assertEqual(len(done), 1)
        s, debrief = done[0]
        self.assertTrue(debrief)
        self.assertEqual(s["car"], GT3); self.assertEqual(s["cls"], "GT3"); self.assertEqual(s["laps"], 6)
        self.assertEqual(s["spins"], 1); self.assertEqual(s["spin_at"], ["Turn 1"])
        self.assertEqual(s["offs"], 1); self.assertEqual(s["off_at"], ["Pouhon"])
        self.assertEqual(s["incidents"], 1)
        self.assertEqual(len(s["stops"]), 1); self.assertEqual(s["stops"][0]["lap"], 5)
        self.assertAlmostEqual(s["stops"][0]["fuel"], 20.0, places=0)
        self.assertEqual(s["stints"], [5, 1])                 # stop on lap 5 (the in-lap ends stint 1)
        self.assertEqual(s["corners"][0]["name"], "Pouhon")         # the slow lap shows up as time lost there
        self.assertAlmostEqual(s["corners"][0]["lost"], 0.25, delta=0.05)   # clean laps 1,2,3,6: median - best
        self.assertEqual(len(s["corners"]), 1)                       # Turn 1 is the same every lap: nothing lost
        self.assertEqual(s["setup"], "race_v2")
        self.assertEqual(s["race"]["pos"], 3); self.assertEqual(s["race"]["start_pos"], 6)
        self.assertEqual(M.recall(GT3, SPA)["sessions"][0]["laps"], 6)  # stored
        line = M.review_line(s)
        self.assertIn("1 spin (Turn 1)", line); self.assertIn("Pouhon", line)

    def test_disconnect_stores_without_debrief(self):
        done = self._run(finish_race=False)
        self.assertEqual(len(done), 1)
        self.assertFalse(done[0][1])

    def test_garage_only_is_not_stored(self):
        done = []
        rec = M.Recorder(on_done=lambda s, d: done.append(s), log=lambda *a: None)
        b = FakeBrain("Practice")
        rec.tick(b); rec.tick(None)
        time.sleep(0.1)
        self.assertEqual(done, [])

    def test_tick_is_light(self):
        rec = M.Recorder(log=lambda *a: None)
        b = FakeBrain("Practice")
        rec.tick(b)
        t0 = time.perf_counter()
        for i in range(6000):
            b.src["LapDist"] = float(i % 1000); b.src["SessionTime"] += 0.016
            rec.tick(b)
        per = (time.perf_counter() - t0) / 6000
        self.assertLess(per, 0.0005, f"{per * 1e6:.0f} us a tick")

    def test_strategist_debrief_numbers(self):
        from engineer.strat_live import Strategist
        st = Strategist(lambda *a: None, log=lambda *a: None)
        b = FakeBrain()
        st.b = b
        st.stint = 1
        b.src["PlayerCarMyIncidentCount"] = 2
        n = st.debrief_numbers(b)
        self.assertEqual((n["pos"], n["start_pos"], n["best_rank"], n["stops"], n["incidents"], n["ir"]), (3, 6, 2, 1, 2, 24))
        self.assertFalse(n["fastest_me"]); self.assertEqual(n["fastest_car"], 77)


class TestBriefing(unittest.TestCase):
    def setUp(self):
        reset_store()

    def _pack(self, car=GT3, race_s=2 * 60 * 60):
        return BR.prerace_pack(car, SPA, "BMW M4 GT3", "Spa", None, race_s, "test", 100.0, None, 30.0, True,
                               ["Pouhon: Try: one click softer rear bar."], ["Understeer mid-corner in fast corners: Pouhon, Blanchimont."])

    def test_prerace_pack(self):
        fill_strategy_db()
        M.record_session(summary())
        p = self._pack()
        heads = [s["h"] for s in p["sections"]]
        self.assertEqual(heads[:2], ["Strategy", "Your history here"])
        self.assertIn("How to be fastest here", heads)
        txt = BR.pack_text(p)
        sm = p["ctx"]["sm"]
        self.assertTrue(sm["ok"])
        self.assertAlmostEqual(sm["fuel_lap"], 3.0, places=2)
        self.assertGreaterEqual(sm["stops"], 1)                        # 2 h x 3 L/lap > one 100 L tank
        self.assertIn("Plan A:", txt); self.assertIn("Pit loss:", txt); self.assertIn("Fuel window", txt)
        self.assertIn("Tyre fade", txt); self.assertIn("Undercut", txt)
        self.assertIn("Pouhon", txt)                                   # where he loses time
        self.assertIn("rear loose on entry", txt)                      # his radio note
        self.assertIn("MECHANIC RECOMMENDATIONS", txt); self.assertIn("softer rear bar", txt)
        self.assertNotIn("ROUGH GUIDE", txt)
        ctx = BR.model_context(p)
        self.assertTrue(ctx.startswith("This is the PRE-RACE MEETING"))
        e, l = sm["window"]
        self.assertLessEqual(e, l)

    def test_prerace_similar_car(self):
        fill_strategy_db(car=GT3B)
        M.record_session(summary(car=GT3B, car_name="Mercedes AMG GT3"))
        p = self._pack(car=GT3)
        txt = BR.pack_text(p)
        self.assertEqual(p["source"], M.SIMILAR); self.assertEqual(p["strategy_source"], M.SIMILAR)
        self.assertIn("ROUGH GUIDE", txt); self.assertIn("Mercedes AMG GT3", txt)

    def test_prerace_no_data(self):
        p = self._pack(car="nobody_gt3")
        self.assertFalse(p["ctx"]["sm"]["ok"])
        self.assertIn("No sessions remembered", BR.pack_text(p))
        self.assertEqual(BR.what_if("what if it rains", p["ctx"])["kind"], "none")

    def test_lap_race(self):
        fill_strategy_db()
        p = BR.prerace_pack(GT3, SPA, race_s=None, tank=100.0, race_laps=20)
        self.assertEqual(p["ctx"]["sm"]["laps"], 20)

    def test_what_if(self):
        fill_strategy_db()
        p = self._pack()
        ctx = p["ctx"]; sm = ctx["sm"]
        rain = BR.what_if("What if it rains?", ctx)
        self.assertEqual(rain["kind"], "rain"); self.assertTrue(rain["lines"][0].startswith("If it rains"))
        cau = BR.what_if("what if there's a caution", ctx)
        self.assertEqual(cau["kind"], "caution")
        lane = ctx["m"]["lane_loss"]
        self.assertIn(f"{lane - lane * BR.CAUTION_PIT_SAVE:.0f} s instead of {lane:.0f} s", cau["lines"][0])
        one = BR.what_if("what if we do one stop", ctx)
        self.assertEqual(one["kind"], "stops")
        # ~51 laps x 3 L = ~150 L: one stop is possible, no stop is not
        self.assertTrue(one["lines"][0].startswith("1 stop:"), one["lines"])
        zero = BR.what_if("what if we don't stop at all, no stop", ctx)
        self.assertIn("isn't possible", zero["lines"][0])
        need = (1 - 100.0 / (sm["laps"] * 3.0 + 1.5)) * 100
        self.assertIn(f"{need:.0f} percent", zero["lines"][1])
        self.assertEqual(BR.what_if("what if we stop twice", ctx)["kind"], "stops")
        ty = BR.what_if("what if we take no tyres, fuel only", ctx)
        self.assertEqual(ty["kind"], "tyres")
        hot = BR.what_if("what if it's 10 degrees hotter", ctx)
        self.assertEqual(hot["kind"], "temp"); self.assertIn("10 degrees hotter", hot["lines"][0])
        ln = BR.what_if("what if the race is 90 minutes", ctx)
        self.assertEqual(ln["kind"], "length")
        self.assertIsNone(BR.what_if("what's your favourite colour", ctx))
        mc = BR.model_context(p, cau)
        self.assertIn("WHAT-IF ANSWER", mc); self.assertIn(cau["lines"][0], mc)

    def test_debrief_pack(self):
        s = summary(session="Race", race={"pos": 3, "start_pos": 6, "best_rank": 2, "fastest_me": False, "ir": 24, "fuel_left": 4.0},
                    stops=[{"lap": 13, "still": 31.0, "fuel": 60.0}], stints=[13, 12])
        M.record_session(s)
        p = BR.debrief_pack(s, True, [])
        heads = [x["h"] for x in p["sections"]]
        for h in ("Result", "Laps and pace", "Stints and stops", "Incidents", "Where the time went", "Fuel and tyres", "What you said on the radio", "Car"):
            self.assertIn(h, heads)
        txt = BR.pack_text(p)
        self.assertIn("Finished P3 in class, started P6 (+3 places)", txt)
        self.assertIn("2nd fastest in class", txt)
        self.assertIn("lap 13 (31 s stopped, 60.0 L in)", txt)
        self.assertIn("1 spin: Eau Rouge", txt); self.assertIn("Bus Stop", txt)
        self.assertIn("Pouhon: +0.41 s", txt)
        self.assertIn("rear loose on entry", txt)
        self.assertIn("none - the car is consistent", txt)            # no recommendation: no setup change allowed
        self.assertTrue(BR.model_context(p).startswith("This is the POST-RACE DEBRIEF"))
        self.assertEqual(BR.debrief_pack(None)["sections"][0]["lines"][0][:10], "No session")


class TestAppApi(unittest.TestCase):
    """The page's calls (mem_state, team_meeting, team_whatif, team_ask in a meeting) without a window or iRacing."""
    def setUp(self):
        reset_store()
        import queue
        from engineer import app as A
        from engineer.settings import Settings
        api = object.__new__(A.Api)
        api._s, api._q, api._engine = Settings(), queue.Queue(), None
        api._log = lambda *a: None
        self.api = api

    def _events(self):
        out = []
        while not self.api._q.empty():
            out.append(self.api._q.get())
        return out

    def test_meeting_without_ai(self):
        fill_strategy_db()
        M.record_session(summary())
        st = self.api.mem_state()
        self.assertEqual((st["source"], st["ag"]["sessions"], st["car"]), (M.THIS_CAR, 1, "BMW M4 GT3"))
        r = self.api.team_meeting("prerace")
        self.assertEqual(r["team"], "missing")                    # no llama-server here: the page shows the facts
        self.assertIn("Strategy", [x["h"] for x in r["pack"]["sections"]])
        self.assertNotIn("ctx", r["pack"])
        w = self.api.team_whatif("what if there's a caution")
        self.assertEqual(w["kind"], "caution")
        self.assertIsNone(self.api.team_whatif("tell me a joke")["lines"])
        self.api.team_ask("what if it rains")                     # in a meeting: no 'open a lap in Analysis' error
        time.sleep(0.2)
        ev = self._events()
        self.assertTrue(any(e.get("t") == "team_done" and e.get("err") for e in ev))   # the model isn't ready: refused, not crashed
        self.assertFalse(any("Open a lap" in str(e.get("err")) for e in ev))
        d = self.api.team_meeting("debrief")
        self.assertEqual(d["pack"]["kind"], "debrief")
        self.api.team_reset()
        self.assertIsNone(self.api._meet)

    def test_session_end_opens_the_debrief(self):
        s = M.record_session(summary(session="Race", race={"pos": 2}))
        self.api._mem_done(s, True)
        ev = self._events()
        kinds = [e["t"] for e in ev]
        self.assertIn("mem_review", kinds); self.assertIn("mem", kinds)
        self.assertIn({"t": "team_meeting", "kind": "debrief"}, ev)
        self.api._s.team_debrief_auto = False
        self.api._mem_done(s, True)
        self.assertNotIn({"t": "team_meeting", "kind": "debrief"}, self._events())


class FakeIR(dict):
    is_initialized = is_connected = True
    def startup(self): return True
    def freeze_var_buffer_latest(self): pass


class TestDrivingGuard(unittest.TestCase):
    """The team AI must stay unloaded while the car is on track and moving, and in any race while in the car."""
    def setUp(self):
        from engineer import team as T
        self.T = T
        self.ir = FakeIR()
        sys.modules["irsdk"] = types.SimpleNamespace(IRSDK=lambda: self.ir)
        self.settings = types.SimpleNamespace(team_enabled=True, team_in_pitbox=True, driver_name="Alex", team_gpu="")
        self.team = T.Team(self.settings, log=lambda *a: None)

    def set(self, on_track, kind, in_box=False, speed=40.0):
        self.ir.update({"IsOnTrackCar": on_track, "IsOnTrack": on_track, "SessionNum": 0, "PlayerCarInPitStall": in_box,
                        "Speed": speed, "SessionInfo": {"Sessions": [{"SessionNum": 0, "SessionType": kind}]}})

    def test_blocks_on_track(self):
        self.set(True, "Practice")
        self.assertTrue(self.team._driving_now())
        self.set(True, "Race", in_box=True, speed=0.0)
        self.assertTrue(self.team._driving_now())                 # never in a race while in the car, even parked
        self.set(True, "Practice", in_box=True, speed=0.0)
        self.assertFalse(self.team._driving_now())                # parked in the box in practice, allowed in settings
        self.set(False, "Race")
        self.assertFalse(self.team._driving_now())                # out of the car

    def test_meeting_cannot_reach_the_model_while_driving(self):
        self.set(True, "Race")
        self.team.driving = True
        self.team.start()                                          # what team_meeting() does
        self.assertEqual(self.team.state, "blocked")
        self.assertIsNone(self.team.proc)
        got = []
        self.team.ask("Run the pre-race meeting.", "DATA", [], lambda d: got.append(d), lambda err, full="": got.append(("done", err)))
        self.assertEqual(got, [("done", "Not while driving")])

    def test_guard_thread_unloads(self):
        self.set(True, "Practice")
        killed = []
        self.team.proc = types.SimpleNamespace(terminate=lambda: killed.append(1), wait=lambda t: None, poll=lambda: None)
        self.team.state = "ready"
        for _ in range(30):
            if self.team.state == "blocked":
                break
            time.sleep(0.1)
        self.assertEqual(self.team.state, "blocked")
        self.assertEqual(killed, [1])
        self.assertIsNone(self.team.proc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
