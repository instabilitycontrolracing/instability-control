"""ic186 (#729) track learning tests on synthetic laps (tests/synth.py) - no real iRacing data."""
import json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np
import synth as S
from engineer import tracklearn as T

CORNERS = S.corners_meta()


def to_store(sim, no, clean=True, hz=10.0):
    """A synthetic lap in lap_store's format (10 Hz samples: lap %, km/h, pedals, lap clock, steering, gear)."""
    t = sim["t"] - sim["t"][0]
    ts = np.arange(0.0, t[-1], 1.0 / hz)
    g = lambda k: np.interp(ts, t, sim[k])
    p = g("d") / S.L
    lap = {"no": no, "p": [round(float(x), 5) for x in p], "s": [round(float(x) * 3.6, 1) for x in g("Speed")],
           "th": [round(float(x), 3) for x in g("Throttle")], "br": [round(float(x), 3) for x in g("Brake")],
           "t": [round(float(x), 3) for x in ts], "st": [round(float(x), 3) for x in g("SteeringWheelAngle")],
           "gr": [int(round(x)) for x in g("Gear")], "clean": clean, "time": round(float(t[-1]), 3)}
    third = [float(np.interp(f * S.L, sim["d"], t)) for f in (1 / 3, 2 / 3)]
    lap["sec"] = [round(third[0], 3), round(third[1], 3), round(lap["time"] - third[1], 3)]
    return lap


_LAPS = None


def laps():
    """Lap 1 = the reference; laps 2-5 brake early into the Hairpin by different amounts (a repeating mistake)."""
    global _LAPS
    if _LAPS is None:
        out = [to_store(S.simulate(S.reference_params()), 1)]
        for no, sc in zip((2, 3, 4, 5), (1.0, 0.8, 1.2, 0.9)):
            out.append(to_store(S.simulate(S.with_mistake("brake_early", scale=sc)), no))
        _LAPS = out
    return [dict(l) for l in _LAPS]


class Basics(unittest.TestCase):
    def test_stage_thresholds(self):
        self.assertEqual(T.stage_for(0)["key"], "learn")
        self.assertEqual(T.stage_for(14)["key"], "learn")
        self.assertEqual(T.stage_for(15)["key"], "refine")
        self.assertEqual(T.stage_for(49)["key"], "refine")
        self.assertEqual(T.stage_for(50)["key"], "push")
        self.assertEqual(T.stage_for(150)["key"], "race")
        self.assertEqual(T.stage_for(3, race_prep=True)["key"], "race")
        self.assertEqual(T.stage_for(10)["to_next"], 5)

    def test_banker_lap(self):
        run = [{"no": 3, "time": 130.0, "clean": True}, {"no": 4, "time": 101.0, "clean": False},
               {"no": 5, "time": 102.0, "clean": True}, {"no": 6, "time": 101.5, "clean": True}]
        self.assertEqual(T.banker_lap(run, 100.0)["no"], 5)               # 130 s is over 10 % off; lap 4 isn't clean
        self.assertEqual(T.banker_lap(run, 100.0, {5: {"off": [0.4]}})["no"], 6)   # an off on lap 5
        self.assertIsNone(T.banker_lap(run, None))

    def test_track_len_and_race(self):
        self.assertAlmostEqual(T.track_len_m("5.79 km"), 5790.0)
        self.assertAlmostEqual(T.track_len_m("2.00 mi"), 3218.688)
        self.assertIsNone(T.track_len_m(None))
        info = {"Sessions": [{"SessionType": "Practice", "SessionTime": "3600.0000 sec"},
                             {"SessionType": "Race", "SessionTime": "21600.0000 sec"}]}
        self.assertEqual(T.race_secs(info), 21600.0)
        self.assertIsNone(T.race_secs({"Sessions": [{"SessionType": "Race", "SessionTime": "unlimited"}]}))

    def test_target_pace(self):
        L = [{"no": i, "time": 100 + i * 0.1, "clean": True, "sec": [33.0, 66.0, 34.0 + i * 0.1]} for i in range(1, 7)]
        t = T.target_pace(L)
        self.assertTrue(t["ok"])
        self.assertAlmostEqual(t["target"], 100.3 + 0.2, places=3)       # median of laps 1-5 (100.3) + 0.2
        self.assertAlmostEqual(sum(t["sectors"]), t["target"], places=2)
        self.assertEqual(t["last"]["no"], 6)
        self.assertFalse(T.target_pace(L[:4])["ok"])

    def test_clean_count(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "idx.json")
            ok = {"valid": True, "complete": True, "pit": False}
            json.dump({"a": {"car_path": "bmwm4gt3", "track": "spa up", "laps": [ok, ok, dict(ok, valid=False)]},
                       "b": {"car_path": "bmwm4gt3", "track": "spa up", "src": "replay", "laps": [ok]},
                       "c": {"car_path": "other", "track": "spa up", "laps": [ok]}}, open(p, "w"))
            self.assertEqual(T.clean_count("bmwm4gt3", "spa up", index_path=p), 2)
            self.assertIsNone(T.clean_count("bmwm4gt3", "spa up", index_path=os.path.join(d, "none.json")))


class Analyse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = T.analyse(laps(), S.L, True, "", corners=CORNERS)

    def test_focus_names_the_repeating_root_cause(self):
        r = self.res
        self.assertTrue(r["ok"], r.get("why"))
        self.assertLessEqual(len(r["focus"]), 3)
        top = r["focus"][0]
        self.assertEqual(top["corner"], "Hairpin")
        self.assertEqual(top["code"], "BRAKE_EARLY")
        self.assertEqual(top["link"], "braking / entry")
        self.assertGreater(top["lost"], 0)

    def test_one_off_is_not_a_focus_item(self):
        L = laps()
        L[1] = to_store(S.simulate(S.with_mistake("throttle_late")), 2)    # only one lap is late on the throttle
        r = T.analyse(L, S.L, True, "", corners=CORNERS)
        self.assertFalse(any(f["code"] == "THROTTLE_LATE" for f in r["focus"]))

    def test_sheet_steps_and_checks(self):
        r = self.res
        names = [x["corner"] for x in r["sheet"]]
        self.assertIn("Hairpin", names)
        hp = next(x for x in r["sheet"] if x["corner"] == "Hairpin")
        self.assertIsNotNone(hp["brake_d"]); self.assertIsNotNone(hp["min"]); self.assertIsNotNone(hp["apex_d"])
        st = next(x for x in r["steps"] if x["corner"] == "Hairpin")
        # recent laps brake earlier than the best: the step is 10-20 m later and never past the best lap + margin
        self.assertEqual(st["status"], "step")
        self.assertGreater(st["next_d"], st["now_d"])
        self.assertLessEqual(st["next_d"] - st["now_d"], 20)
        self.assertLessEqual(st["next_d"], st["best_d"] + T.STEP_MARGIN + 1)
        self.assertIn("min_speed", r["checks"])
        self.assertTrue(r["target"]["ok"])

    def test_off_at_a_corner_stops_the_step(self):
        hp = next(c for c in CORNERS if c["name"] == "Hairpin")
        pct = (hp["start"] + 5) / S.L
        r = T.analyse(laps(), S.L, True, "", flags={5: {"off": [pct]}}, corners=CORNERS)
        st = next((x for x in r["steps"] if x["corner"] == "Hairpin"), None)
        self.assertTrue(st is None or st["status"] != "step")

    def test_no_track_length_no_advice(self):
        r = T.analyse(laps(), None, True, "", corners=CORNERS)
        self.assertFalse(r["ok"])
        self.assertEqual(r["focus"], [])


class Checks(unittest.TestCase):
    def test_coasting_found(self):
        tr = S.to_trace(S.simulate(S.with_mistake("coasting")))
        ev = T.coasting(tr, CORNERS)
        self.assertTrue(any(e["corner"] == "Hairpin" for e in ev), ev)

    def test_lift_on_a_straight(self):
        tr = S.to_trace(S.simulate(S.reference_params()))
        strs = T.straights(tr)
        self.assertTrue(strs)
        a, b = strs[0]
        lifted = dict(tr)
        lifted["Throttle"] = tr["Throttle"].copy()
        i = int(np.searchsorted(tr["d"], (a + b) / 2))
        lifted["Throttle"][i:i + 40] = 0.5                                 # 40 m at ~50 m/s = 0.8 s
        self.assertEqual(T.straight_lifts(tr, strs), [])
        self.assertTrue(T.straight_lifts(lifted, strs))

    def test_lap_checks_shape(self):
        tr = S.to_trace(S.simulate(S.reference_params()))
        out = T.lap_checks(tr, CORNERS)
        self.assertEqual(len(out["corners"]), len(CORNERS))
        self.assertTrue(all(c["min_diff_kmh"] == 0 for c in out["corners"]))


class LiveHooks(unittest.TestCase):
    def test_live_tracks_runs_banker_and_unknown_sid_is_quiet(self):
        class St:
            spotter = True
        class B:
            def __init__(self):
                self.v = {"OnPitRoad": True, "LapCompleted": 0, "LapDistPct": 0.1, "PlayerTrackSurface": 3, "PlayerCarMyIncidentCount": 0}
                self.sess_type = "Practice"; self.s = St(); self.said = []
            def g(self, k, d=None): return self.v.get(k, d)
            def info(self, k, d=None): return {"TrackName": "synth", "TrackLength": "3.00 km"} if k == "WeekendInfo" else (d or {})
            def drivers(self): return {0: {"CarPath": "bmwm4gt3"}}
            def me(self): return 0
            def metric(self): return True
            def say(self, sid, f=None, **kw): self.said.append(sid); return False
        class Store:
            key, met, laps = "0:0:synth", True, []
        b, st = B(), Store()
        T.META_FILE = os.path.join(tempfile.mkdtemp(), "tracklearn_meta.json")    # never the real cache
        lv = T.Live(log=lambda *a: None)
        lv.tick(b, st)                                   # in the pits
        b.v["OnPitRoad"] = False
        lv.tick(b, st)                                   # out: run 1, the out lap (1) doesn't count
        self.assertEqual((lv.run, lv.run_from), (1, 2))
        b.v.update(PlayerTrackSurface=0, LapDistPct=0.5)
        lv.tick(b, st)
        self.assertEqual(lv.flags[1]["off"], [0.5])
        st.laps = [{"no": 2, "time": 100.0, "clean": True}]
        lv.tick(b, st)
        self.assertEqual(lv.banker, 2)
        self.assertEqual(b.said, [])                     # coach call is off by default


if __name__ == "__main__":
    unittest.main()
