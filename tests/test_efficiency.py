"""Efficiency pass (2026-10-29): the cheaper code paths must give exactly the same answers as the old ones.

    python -m pytest -q tests/test_efficiency.py
"""
import json, os, queue, sys, tempfile, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from irsdk_fake import FakeIRFile, SyntheticRace, ir_from_file   # noqa: E402


def _src(path):
    from engineer import engine as E

    class Src(E.IRacing):
        def __init__(self, ir):
            self.ir, self.ok, self.log = ir, True, (lambda m: None)
    return Src(ir_from_file(path))


class TelemetryMemo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ic_eff_")
        self.fake = FakeIRFile(os.path.join(self.tmp, "ir.bin"))
        self.race = SyntheticRace(self.fake, race_s=300)
        for _ in range(40 * 15):
            self.race.advance(1 / 15)

    def tearDown(self):
        self.fake.close()

    def test_same_values_as_pyirsdk(self):
        src = _src(self.fake.path)
        raw = ir_from_file(self.fake.path)
        for _ in range(30):
            self.race.advance(1 / 15)
            src.freeze(); raw.freeze_var_buffer_latest()
            for name in self.fake.vars:
                self.assertEqual(src[name], raw[name], name)
                self.assertEqual(src[name], raw[name], name + " (from the memo)")
            self.assertEqual(src.info("DriverInfo"), raw["DriverInfo"])
            self.assertIsNone(src["NoSuchVariable"])

    def test_new_tick_new_values(self):
        src = _src(self.fake.path)
        src.freeze()
        t0 = src["SessionTime"]
        self.race.advance(1 / 15)
        self.assertEqual(src["SessionTime"], t0)                 # same frozen snapshot until the next freeze
        src.freeze()
        self.assertGreater(src["SessionTime"], t0)

    def test_memo_is_replaced_not_cleared(self):
        """A reader on another thread that started before freeze() can only write into the old tick's memo."""
        src = _src(self.fake.path)
        src.freeze()
        old = src._memo
        src["Speed"]
        src.freeze()
        self.assertIsNot(src._memo, old)
        self.assertNotIn("Speed", src._memo)

    def test_replay_test_override(self):
        src = _src(self.fake.path)
        self.fake.values["IsReplayPlaying"] = True
        self.fake.values["IsOnTrack"] = False
        self.fake.commit()
        src.freeze()
        self.assertFalse(src["IsOnTrack"])
        src.replay_test = True
        self.assertTrue(src["IsOnTrack"])


class DriversCache(unittest.TestCase):
    def _brain(self, di):
        from engineer.brain import Brain
        b = Brain.__new__(Brain)
        b.src = types.SimpleNamespace(info=lambda sec: di[0] if sec == "DriverInfo" else None)
        return b

    def test_same_table_and_private_copies(self):
        di = [{"Drivers": [{"CarIdx": 0, "CarIsPaceCar": 1}, {"CarIdx": 1, "UserName": "A"}, {"CarIdx": 2, "IsSpectator": 1},
                           {"CarIdx": 3, "UserName": "B"}]}]
        b = self._brain(di)
        d1 = b.drivers()
        self.assertEqual(sorted(d1), [1, 3])
        d1.pop(1)                                           # a caller changing its copy
        self.assertEqual(sorted(b.drivers()), [1, 3])
        di[0] = {"Drivers": [{"CarIdx": 5}]}                # new session info -> new table
        self.assertEqual(sorted(b.drivers()), [5])
        di[0] = None
        self.assertEqual(b.drivers(), {})


class LapStoreSave(unittest.TestCase):
    def test_bytes_identical_to_json_dump(self):
        from engineer import lap_store as LS
        tmp = tempfile.mkdtemp(prefix="ic_eff_ls_")
        old = (LS.PATH, LS.DIR)
        LS.PATH, LS.DIR = os.path.join(tmp, "state.json"), os.path.join(tmp, "laps")
        try:
            st = LS.LapStore(log=lambda *a: None)
            st.key = "4242:0:synthring"
            lap = LS._new(3); lap.update(p=[0.1, 0.25, 0.5], s=[100.5, 120.25, 99.0], t=[1.0, 2.5, float("nan")], time=101.234)
            st.laps, st.cur, st.lap_no, st.best_no, st.parts = [lap], LS._new(4), 4, 3, [{"no": 2, "sec": [30.1, None, None]}]
            st._dirty = True
            st.save(force=True)
            now = json.load(open(LS.PATH))["saved"]
            want = {"key": st.key, "laps": st.laps, "cur": st.cur, "lap_no": st.lap_no, "best_no": st.best_no,
                    "parts": st.parts, "saved": now}
            import io
            b = io.StringIO(); json.dump(want, b, separators=(",", ":"))
            self.assertEqual(open(LS.PATH, encoding="utf-8").read(), b.getvalue())
            mine = os.path.join(LS.DIR, st._fname(st.key))
            want2 = {"key": st.key, "laps": st.laps, "best_no": st.best_no, "parts": st.parts, "saved": now}
            b = io.StringIO(); json.dump(want2, b, separators=(",", ":"))
            self.assertEqual(open(mine, encoding="utf-8").read(), b.getvalue())
            # a new lap in front, an old one dropped: the per-lap text cache still writes exactly json.dump's text
            lap5 = LS._new(5); lap5.update(p=[0.2], t=[3.0], time=99.5)
            st.laps = [lap5] + st.laps[:1] + [LS._new(1)]
            st._dirty = True
            st.save(force=True)
            st.laps = st.laps[:2]
            st._dirty = True
            st.save(force=True)
            now = json.load(open(LS.PATH))["saved"]
            want = {"key": st.key, "laps": st.laps, "cur": st.cur, "lap_no": st.lap_no, "best_no": st.best_no,
                    "parts": st.parts, "saved": now}
            b = io.StringIO(); json.dump(want, b, separators=(",", ":"))
            self.assertEqual(open(LS.PATH, encoding="utf-8").read(), b.getvalue())
        finally:
            LS.PATH, LS.DIR = old


class RemoteWants(unittest.TestCase):
    def test_wanted(self):
        from engineer.remote import Remote
        r = Remote.__new__(Remote)
        import threading
        r.lock, r.clients, r._only = threading.Lock(), [], {}
        self.assertFalse(r._wanted("t"))
        dash, tim = queue.Queue(), queue.Queue()
        r.clients.append(dash); r._only[id(dash)] = None
        self.assertTrue(r._wanted("t")); self.assertFalse(r._wanted("timing"))
        r.clients.append(tim); r._only[id(tim)] = {"timing", "off", "hb"}
        self.assertTrue(r._wanted("timing"))
        r.clients.remove(dash)
        self.assertFalse(r._wanted("t")); self.assertTrue(r._wanted("off"))


class BackfillWaits(unittest.TestCase):
    def test_waits_while_driving(self):
        from engineer import strategy as ST
        calls = {"n": 0}
        def busy():
            calls["n"] += 1
            return calls["n"] < 3
        import unittest.mock as um
        with um.patch("time.sleep") as sl:
            ST._wait_idle(busy)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(sl.call_count, 2)
        ST._wait_idle(None)                                 # no busy test: never waits
        ST._wait_idle(lambda: 1 / 0)                         # a broken test never hangs the backfill


class Procs(unittest.TestCase):
    def test_tasklist_fallback_same_names(self):
        from engineer import procs
        import unittest.mock as um
        out = '"System Idle Process","0","Services","0","8 K"\n"iRacingSim64DX11.exe","4242","Console","1","2,100,000 K"\n'
        with um.patch.object(procs.os, "name", "posix"), \
                um.patch.object(procs.subprocess, "run", return_value=types.SimpleNamespace(stdout=out)):
            self.assertEqual(procs.running_exes(), {"system idle process", "iracingsim64dx11.exe"})
            self.assertTrue(procs.is_running("iRacingSim64DX11.exe"))
        with um.patch.object(procs.os, "name", "posix"), um.patch.object(procs.subprocess, "run", side_effect=OSError):
            self.assertEqual(procs.running_exes(), set())

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_toolhelp_sees_this_python(self):
        from engineer import procs
        self.assertIn(os.path.basename(sys.executable).lower(), procs._toolhelp())


class TeamGuardSessionType(unittest.TestCase):
    def test_engine_session_type_used(self):
        from engineer.team import Team
        reads = []

        class IR(dict):
            is_initialized = is_connected = True

            def freeze_var_buffer_latest(self):
                pass

            def __getitem__(self, k):
                if k == "SessionInfo":
                    reads.append(k)
                return dict.get(self, k)
        ir = IR(IsOnTrackCar=True, IsOnTrack=True, SessionNum=2,
                SessionInfo={"Sessions": [{"SessionNum": 0, "SessionType": "Practice"}, {"SessionNum": 2, "SessionType": "Race"}]},
                PlayerCarInPitStall=True, Speed=0.0)
        t = Team.__new__(Team)
        t._ir, t.s = ir, types.SimpleNamespace(team_in_pitbox=True)
        eng = {"n": 2, "type": "Race"}
        t.sess_type_fn = lambda n: eng["type"] if n == eng["n"] else ""
        for _ in range(5):
            self.assertTrue(t._driving_now())                 # in the car in a race: always "driving"
        self.assertEqual(reads, [])                           # the engine's answer - no YAML parse here
        dict.__setitem__(ir, "SessionNum", 0)                  # the engine hasn't caught up yet: parsed here
        self.assertFalse(t._driving_now())                    # practice, parked in the box -> allowed
        self.assertEqual(len(reads), 1)


class HuePictureRate(unittest.TestCase):
    def test_lower_rate_only_while_driving(self):
        from engineer.hue_rig import HueRig
        h = HueRig.__new__(HueRig)
        h.s = types.SimpleNamespace(hue_picture_fps=4)
        self.assertEqual(h._picture_fps(), 4)                 # not told yet: full rate
        h._driving = True
        self.assertEqual(h._picture_fps(), 2)
        h._driving = False
        self.assertEqual(h._picture_fps(), 4)
        h.s.hue_picture_fps, h._driving = 1, True
        self.assertEqual(h._picture_fps(), 1)                 # never faster than the chosen rate
        h.s.hue_picture_fps_driving = 4
        h.s.hue_picture_fps = 0
        self.assertEqual(h._picture_fps(), 1)


class SoundPageState(unittest.TestCase):
    def test_setup_checks_every_5s(self):
        from engineer.audio_tool import AudioMix
        import unittest.mock as um
        a = AudioMix(log=lambda *x: None)
        n = {"reg": 0}
        def reg():
            n["reg"] += 1
            return True
        clock = {"t": 100.0}
        with um.patch.object(AudioMix, "cable_has_apo", staticmethod(reg)), um.patch.object(a, "_vm", lambda: None), \
                um.patch("time.monotonic", lambda: clock["t"]):
            for _ in range(12):                                # 6 s of a twice-a-second poll
                st = a.state(); clock["t"] += 0.5
            self.assertTrue(st["tv_apo"])
            self.assertEqual(n["reg"], 2)                     # asked at 0 s and after 5 s, not 12 times


if __name__ == "__main__":
    unittest.main()
