"""Driving coach tests on synthetic laps (python -m unittest discover -s tests).

No real iRacing or Garage 61 data is used: tests/synth.py drives a simple car model on a made-up track.
"""
import io, json, os, sys, tempfile, unittest, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np
import synth as S
from engineer import coach, garage61
from engineer.analysis import compare
from engineer.telemetry import Session

REF_SIM = S.simulate(S.reference_params())
REF = S.to_trace(REF_SIM)
CORNERS = S.corners_meta()
_SIMS = {}


def sim_of(name):
    if name not in _SIMS:
        _SIMS[name] = S.simulate(S.with_mistake(name))
    return _SIMS[name]


def run(name, position=True, ref=REF):
    return coach.coach_traces(S.to_trace(sim_of(name), position), ref, CORNERS)


class Findings(unittest.TestCase):
    def test_each_mistake_is_found_and_ranked_first(self):
        for name, (ci, _, expect) in S.MISTAKES.items():
            if name == "wide_apex":
                continue          # no time effect in the model; see the line test
            with self.subTest(name):
                out = run(name)
                top = out["corners"][0]
                self.assertEqual(top["name"], S.NAMES[ci], f"{name}: wrong corner ranked first")
                self.assertGreater(top["lost"], 0.03)
                self.assertEqual(top["findings"][0]["code"], expect, f"{name}: {[f['code'] for f in top['findings']]}")
                f = top["findings"][0]
                bank = coach.BANK[expect]
                self.assertEqual((f["title"], f["why"], f["drill"]), (bank["title"], bank["why"], bank["drill"]))
                self.assertTrue(f["detail"])

    def test_ranked_by_time_lost_and_adds_up(self):
        for name in ("brake_early", "throttle_late", "shift_early"):
            out = run(name)
            lost = [c["lost"] for c in out["corners"]]
            self.assertEqual(lost, sorted(lost, reverse=True))
            self.assertAlmostEqual(sum(lost), out["total"], delta=0.02)

    def test_two_mistakes_bigger_first(self):
        P = S.with_mistake("hesitation", S.with_mistake("brake_early"))
        out = coach.coach_traces(S.to_trace(S.simulate(P)), REF, CORNERS)
        names = [c["name"] for c in out["corners"]]
        self.assertLess(names.index("Hairpin"), names.index("Turn Four"))
        by = {c["name"]: c for c in out["corners"]}
        self.assertEqual(by["Hairpin"]["findings"][0]["code"], "BRAKE_EARLY")
        self.assertIn("THROTTLE_HESITATION", [f["code"] for f in by["Turn Four"]["findings"]])
        self.assertEqual(out["focus"][0]["corner"], "Hairpin")

    def test_same_lap_has_nothing_to_say(self):
        out = coach.coach_traces(REF, REF, CORNERS)
        self.assertAlmostEqual(out["total"], 0.0, places=6)
        self.assertEqual(out["focus"], [])
        self.assertTrue(all(not c["findings"] for c in out["corners"]))

    def test_consequences_come_after_causes(self):
        out = run("abrupt_release")
        codes = [f["code"] for f in out["corners"][0]["findings"]]
        self.assertLess(codes.index("BRAKE_RELEASE_ABRUPT"), codes.index("MIN_SPEED_LOW"))

    def test_line_from_position(self):
        out = run("wide_apex")
        c = next(c for c in out["corners"] if c["name"] == "Fast Left")
        self.assertIn("LINE_WIDE_APEX", [f["code"] for f in c["findings"]])
        self.assertAlmostEqual(c["line"]["apex"], -3.0, delta=0.6)
        self.assertTrue(out["position"])

    def test_no_position_no_line_claims(self):
        out = run("wide_apex", position=False)
        self.assertFalse(out["position"])
        self.assertTrue(any("estimated" in n for n in out["notes"]))
        for c in out["corners"]:
            self.assertIsNone(c["line"])
            self.assertFalse({"LINE_WIDE_APEX", "LINE_TIGHT_APEX"} & {f["code"] for f in c["findings"]})

    def test_every_finding_comes_from_the_bank(self):
        for name in S.MISTAKES:
            for c in run(name)["corners"]:
                for f in c["findings"]:
                    self.assertIn(f["code"], coach.BANK)
                    self.assertEqual(f["drill"], coach.BANK[f["code"]]["drill"])

    def test_json_safe_and_saved(self):
        out = run("coasting")
        txt = json.dumps(out)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "coach_last.json")
            coach.save_summary(out, p)
            self.assertEqual(coach.last_summary(p)["total"], json.loads(txt)["total"])
            self.assertTrue(coach.last_summary(p)["lines"])


class IbtAndCsv(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        P = S.reference_params()
        jitter = []
        for k in (-24, 0, -20, -4):          # a few laps with a wandering brake point in the Esses
            Q = [dict(p) for p in P]
            for key in ("brake_d", "rel_start", "rel_end"):
                Q[1][key] += k if key == "brake_d" else 0
            jitter.append(S.simulate(Q))
        cls.laps = [REF_SIM, sim_of("brake_early")] + jitter
        cls.ibt = S.write_ibt(os.path.join(cls.tmp.name, "bmwm4gt3_synth ring 2026-10-24 10-00-00.ibt"), cls.laps)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ibt_through_telemetry_session(self):
        s = Session(self.ibt, landmarks=[])
        full = [L for L in s.laps if L["complete"]]
        self.assertEqual(len(full), len(self.laps))
        self.assertEqual(s.best["n"], 1)                       # the reference lap is the fastest
        cs = s.find_corners()                                   # detected from braking zones (no track map)
        self.assertEqual(len(cs), 5)
        out = coach.coach_session(s, 2, s, s.best["n"], save=False)
        top = out["corners"][0]
        self.assertTrue(top["start"] <= 450 <= top["end"] + 80, top)
        self.assertEqual(top["findings"][0]["code"], "BRAKE_EARLY")
        # consistency over the other laps (brake point in the Esses wanders over 24 m)
        esses = next(c for c in out["corners"] if c["start"] <= 1000 <= c["end"] + 80)
        self.assertIsNotNone(esses["consistency"])
        self.assertGreater(esses["consistency"]["brake_sd_m"], 8)
        self.assertIn("INCONSISTENT_BRAKE", [f["code"] for f in esses["findings"]])

    def test_ibt_as_reference(self):
        ref, rs = coach.ref_from_ibt(self.ibt, landmarks=[])
        self.assertEqual(ref.source, "ibt")
        self.assertAlmostEqual(ref.time, REF_SIM["t"][-1], delta=0.1)
        out = coach.coach_traces(S.to_trace(sim_of("throttle_late")), ref.trace(), CORNERS)
        self.assertEqual(out["corners"][0]["findings"][0]["code"], "THROTTLE_LATE")

    def test_garage61_style_csv(self):
        name = "Garage 61 - Alien Driver - BMW M4 GT3 - Synth Ring - 00.59.420 - abc123.csv"
        p = S.write_g61_csv(os.path.join(self.tmp.name, name), REF_SIM)
        ref = coach.ref_from_csv(p, track_len=S.L)
        self.assertEqual(ref.meta["driver"], "Alien Driver")
        self.assertAlmostEqual(ref.meta["lap_time"], 59.42, places=2)
        self.assertIn("Alien Driver", ref.label)
        self.assertTrue(ref.has_position)
        self.assertAlmostEqual(ref.time, 59.42, places=3)                     # lap time from the file name
        self.assertAlmostEqual(float(ref.trace()["t"][-1]), REF_SIM["t"][-1], delta=0.15)
        json.dumps(ref.info())
        for name_, (ci, _, expect) in S.MISTAKES.items():
            if name_ in ("wide_apex", "corrections", "wrong_gear"):
                continue                         # tiny losses: 60 Hz CSV resampling noise can reorder those
            with self.subTest(name_):
                out = coach.coach_traces(S.to_trace(sim_of(name_)), ref.trace(), CORNERS)
                self.assertEqual(out["corners"][0]["name"], S.NAMES[ci])
                self.assertEqual(out["corners"][0]["findings"][0]["code"], expect)

    def test_csv_without_track_length_or_lap_time(self):
        p = S.write_g61_csv(os.path.join(self.tmp.name, "lap.csv"), REF_SIM)
        ref = coach.ref_from_csv(p)                             # distance from integrating speed
        self.assertAlmostEqual(ref.track_len, S.L, delta=0.02 * S.L)

    def test_csv_rejects_non_telemetry(self):
        with self.assertRaises(ValueError):
            coach.parse_csv("Name,Value\nfoo,1\n")

    def test_reference_works_in_existing_analysis(self):
        s = Session(self.ibt, landmarks=[])
        ref = coach.RefLap(REF, "test", "csv")
        out = compare(s, 2, ref, 0, points=200)
        self.assertGreater(out["total"], 0.5)
        self.assertEqual(len(out["corners"]), 5)


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(status=200, body=b"{}", seen=None):
    def f(req, timeout=None):
        if seen is not None:
            seen.append(req)
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, io.BytesIO(json.dumps({"message": "nope", "trace": "t1"}).encode()))
        return FakeResp(body)
    return f


class Garage61(unittest.TestCase):
    TOKEN = "g61pat_TEST_NOT_REAL_123"

    def test_token_never_in_settings(self):
        from engineer import settings as ST
        names = " ".join(getattr(ST.Settings, "__dataclass_fields__", {}).keys())
        self.assertNotIn("garage61", names.lower()); self.assertNotIn("g61", names.lower())

    def test_token_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "garage61_token.txt")
            self.assertIsNone(garage61.load_token(p))
            garage61.save_token("  " + self.TOKEN + "\n", p)
            self.assertEqual(garage61.load_token(p), self.TOKEN)
            garage61.save_token("", p)
            self.assertFalse(garage61.has_token(p))

    def test_me_ok_and_token_never_echoed(self):
        seen = []
        me = {"id": "u1", "firstName": "Alex", "lastName": "D", "subscriptionPlan": "free", "apiPermissions": ["driving_data"]}
        c = garage61.Client(self.TOKEN, opener=opener(body=json.dumps(me).encode(), seen=seen))
        r = garage61.test_token(c)
        self.assertTrue(r["ok"]); self.assertTrue(r["driving_data"]); self.assertEqual(r["plan"], "free")
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer " + self.TOKEN)
        self.assertEqual(seen[0].full_url, "https://garage61.net/api/v1/me")
        self.assertNotIn(self.TOKEN, json.dumps(r) + repr(c))

    def test_missing_permission_is_explained(self):
        me = {"id": "u1", "firstName": "A", "apiPermissions": []}
        r = garage61.test_token(garage61.Client(self.TOKEN, opener=opener(body=json.dumps(me).encode())))
        self.assertFalse(r["driving_data"])
        self.assertIn("driving data", r["status"])
        c = garage61.Client(self.TOKEN, opener=opener(403))
        with self.assertRaises(garage61.G61Error) as e:
            c.lap_csv("abc")
        self.assertEqual(e.exception.kind, "permission")
        self.assertIn("driving_data", e.exception.message)

    def test_errors(self):
        for code, kind in ((401, "bad_token"), (404, "not_found"), (429, "rate_limited"), (500, "server")):
            with self.subTest(code):
                with self.assertRaises(garage61.G61Error) as e:
                    garage61.Client(self.TOKEN, opener=opener(code)).me()
                self.assertEqual(e.exception.kind, kind)
                self.assertNotIn(self.TOKEN, e.exception.message)
        with self.assertRaises(garage61.G61Error) as e:
            garage61.Client("", opener=opener()).me()
        self.assertEqual(e.exception.kind, "no_token")

    def setUp(self):
        garage61._MEM.clear()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        garage61._MEM.clear()
        self.tmp.cleanup()

    def test_lap_search_query(self):
        seen = []
        body = {"items": [{"id": "L1", "lapTime": 100.5, "driver": {"id": "u1", "firstName": "Alex"}, "canViewTelemetry": True},
                          {"id": "L0", "lapTime": 99.9, "driver": {"id": "u1", "firstName": "Alex"}, "canViewTelemetry": True}], "total": 2}
        c = garage61.Client(self.TOKEN, opener=opener(body=json.dumps(body).encode(), seen=seen))
        res = garage61.fastest_laps(c, 132, 999, me_id="u1")
        self.assertIn("/laps?cars=132&tracks=999&group=driver", seen[0].full_url)
        self.assertEqual([x["id"] for x in res["laps"]], ["L0", "L1"])
        self.assertTrue(res["only_mine"])
        self.assertIn("CSV", res["note"])
        self.assertIn("team", res["note"])

    def test_lap_list_is_cached_no_extra_requests(self):
        seen = []
        body = {"items": [{"id": "L1", "lapTime": 100.5, "driver": {"id": "u2", "firstName": "Fast"}, "canViewTelemetry": True}]}
        c = garage61.Client(self.TOKEN, opener=opener(body=json.dumps(body).encode(), seen=seen))
        a = garage61.fastest_laps(c, 1, 2, me_id="u1", my_best=101.0)
        b = garage61.fastest_laps(c, 1, 2, me_id="u1", my_best=101.0)
        self.assertEqual(len(seen), 1)                       # the second click is served from the cache
        self.assertFalse(a["cached"]); self.assertTrue(b["cached"])
        self.assertEqual(a["faster"], 1); self.assertIsNone(a["note"])
        garage61.fastest_laps(c, 1, 2, me_id="u1", refresh=True)
        self.assertEqual(len(seen), 2)
        me = {"id": "u1"}
        c2 = garage61.Client(self.TOKEN, opener=opener(body=json.dumps(me).encode(), seen=seen))
        garage61.cached_me(c2); garage61.cached_me(c2)
        self.assertEqual(len(seen), 3)

    def test_no_faster_lap_reachable_is_explained(self):
        body = {"items": [{"id": "L1", "lapTime": 230.0, "driver": {"id": "u2", "firstName": "Mate"}, "canViewTelemetry": True},
                          {"id": "L2", "lapTime": 225.0, "driver": {"id": "u1", "firstName": "Alex"}, "canViewTelemetry": True}]}
        c = garage61.Client(self.TOKEN, opener=opener(body=json.dumps(body).encode()))
        res = garage61.fastest_laps(c, 1, 2, me_id="u1", my_best=224.0)
        self.assertEqual(res["faster"], 0)
        self.assertFalse(res["only_mine"])
        self.assertIn("teammates", res["note"])
        self.assertIn("join", res["note"])
        self.assertTrue(res["laps"][0]["mine"])
        self.assertNotIn("224", res["note"])                   # no made-up or echoed numbers in the explanation

    def test_lap_csv_cached(self):
        n = []

        def f(req, timeout=None):
            n.append(req.full_url)
            return FakeResp(b"Speed,LapDistPct\n1,0\n")
        c = garage61.Client(self.TOKEN, opener=f)
        a = garage61.lap_csv_cached(c, "L/../9", cache_dir=self.tmp.name)
        b = garage61.lap_csv_cached(c, "L/../9", cache_dir=self.tmp.name)
        self.assertEqual(a, b); self.assertEqual(len(n), 1)
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, "g61_laps")), ["L9.csv"])

    def test_token_file_location_and_clear_only_touches_it(self):
        self.assertEqual(os.path.basename(garage61.TOKEN_FILE), "garage61_token.txt")
        self.assertEqual(os.path.basename(os.path.dirname(garage61.TOKEN_FILE)), "RaceEngineer")
        ibt = os.path.join(self.tmp.name, "car_track.ibt")
        open(ibt, "wb").write(b"x")
        self.assertFalse(garage61.clear_token(ibt))            # refuses anything but its own token file
        self.assertTrue(os.path.exists(ibt))

    def test_module_never_touches_ibt_files(self):
        src = open(garage61.__file__, encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith(("#", "*")) and ".ibt" not in l)
        for bad in ("shutil", "os.rename", "os.replace", "unlink", "rmtree", "TELEMETRY_DIR", "subprocess"):
            self.assertNotIn(bad, code)
        self.assertEqual(src.count("os.remove("), 1)             # only clear_token's own file

    def test_garage61_lap_to_reference(self):
        with tempfile.TemporaryDirectory() as d:
            p = S.write_g61_csv(os.path.join(d, "x.csv"), REF_SIM)
            with open(p, encoding="utf-8") as f:
                csv_text = f.read()
        info = {"id": "L9", "lapTime": float(REF_SIM["t"][-1]), "canViewTelemetry": True, "driver": {"firstName": "Fast", "lastName": "Guy"}}

        def f(req, timeout=None):
            return FakeResp(csv_text.encode() if req.full_url.endswith("/csv") else json.dumps(info).encode())
        ref = coach.ref_from_garage61(garage61.Client(self.TOKEN, opener=f), "L9", S.L, cache_dir=self.tmp.name)
        self.assertEqual(ref.source, "garage61")
        self.assertIn("Fast Guy", ref.label)
        out = coach.coach_traces(S.to_trace(sim_of("early_lift")), ref.trace(), CORNERS)
        self.assertEqual(out["corners"][0]["findings"][0]["code"], "EARLY_LIFT")


@unittest.skipUnless(os.environ.get("G61_SAMPLE_CSV"), "set G61_SAMPLE_CSV to a real Garage 61 export to run")
class RealCsvSample(unittest.TestCase):
    def test_parses(self):
        ref = coach.ref_from_csv(os.environ["G61_SAMPLE_CSV"])
        self.assertGreater(ref.track_len, 1000)
        self.assertGreater(ref.time, 30)


if __name__ == "__main__":
    unittest.main()
