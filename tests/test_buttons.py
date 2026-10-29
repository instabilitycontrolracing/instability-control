"""Wheel / button box bindings (#322, 2026-10-27). No controllers needed.

    python -m unittest tests.test_buttons -v

Covered: exact device match, "X" vs "X #2" when only one such device is plugged in, both identical boxes plugged in
(exact name only), wrong button, no binding, connected(), and settings that keep the binding through a BOM, a
restart and an unreadable file.
"""
import json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from engineer import buttons as B          # noqa: E402
from engineer import settings as ST        # noqa: E402

TM = "Thrustmaster Advanced Mode Racer"


class Matches(unittest.TestCase):
    def test_exact(self):
        b = {"device": TM, "button": 4}
        self.assertTrue(B.matches(b, TM, 4))
        self.assertTrue(B.matches(b, TM, 4, [TM, "AJAZZ box"]))
        self.assertFalse(B.matches(b, TM, 3, [TM]))

    def test_none(self):
        self.assertFalse(B.matches(None, TM, 4, [TM]))
        self.assertFalse(B.matches({}, TM, 4, [TM]))

    def test_number_gained_or_lost_single_device(self):
        self.assertTrue(B.matches({"device": TM, "button": 4}, TM + " #2", 4, [TM + " #2", "AJAZZ box"]))
        self.assertTrue(B.matches({"device": TM + " #2", "button": 4}, TM, 4, [TM]))

    def test_no_names_means_exact_only(self):
        self.assertFalse(B.matches({"device": TM, "button": 4}, TM + " #2", 4))

    def test_two_identical_devices_exact_only(self):
        names = [TM, TM + " #2"]
        b = {"device": TM, "button": 4}
        self.assertTrue(B.matches(b, TM, 4, names))
        self.assertFalse(B.matches(b, TM + " #2", 4, names))
        self.assertTrue(B.matches({"device": TM + " #2", "button": 4}, TM + " #2", 4, names))

    def test_other_device(self):
        self.assertFalse(B.matches({"device": TM, "button": 4}, "AJAZZ box", 4, [TM, "AJAZZ box"]))
        self.assertFalse(B.matches({"device": TM + " Pro", "button": 4}, TM, 4, [TM]))

    def test_base_name(self):
        self.assertEqual(B.base_name(TM + " #12"), TM)
        self.assertEqual(B.base_name(TM), TM)
        self.assertEqual(B.base_name(None), "")

    def test_connected(self):
        self.assertTrue(B.connected(None, []))
        self.assertTrue(B.connected({"device": TM, "button": 1}, [TM]))
        self.assertTrue(B.connected({"device": TM + " #2", "button": 1}, [TM]))
        self.assertFalse(B.connected({"device": TM, "button": 1}, ["AJAZZ box"]))
        self.assertFalse(B.connected({"device": TM, "button": 1}, []))


class SettingsKeepBinding(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ic_btn_")
        self.old = ST.PATH
        ST.PATH = os.path.join(self.d, "engineer_settings.json")

    def tearDown(self):
        ST.PATH = self.old

    def test_round_trip(self):
        s = ST.Settings(); s.radio_button = {"device": TM, "button": 4}; s.save()
        self.assertEqual(ST.Settings.load().radio_button, {"device": TM, "button": 4})
        self.assertFalse(os.path.exists(ST.PATH + ".tmp"))
        raw = open(ST.PATH, "rb").read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))

    def test_bom_file_loads(self):
        with open(ST.PATH, "w", encoding="utf-8-sig") as f:
            json.dump({"radio_button": {"device": TM, "button": 4}, "driver_name": "Angelo"}, f)
        self.assertEqual(ST.Settings.load().radio_button, {"device": TM, "button": 4})

    def test_unreadable_file_kept_aside(self):
        with open(ST.PATH, "w", encoding="utf-8") as f:
            f.write('{"radio_button": {"device": "X", "butt')
        s = ST.Settings.load()
        self.assertIsNone(s.radio_button)
        kept = [n for n in os.listdir(self.d) if ".unreadable_" in n]
        self.assertEqual(len(kept), 1)


if __name__ == "__main__":
    unittest.main()


class WindowsScan(unittest.TestCase):
    """2026-10-29 (efficiency): the device name is asked for once per plugged-in device, not on every 3 s rescan;
    presses, the "#2" numbering and a device unplugged / plugged back in work as before."""

    def test_names_cached_presses_kept(self):
        import ctypes, types, unittest.mock as um

        class Stop(Exception):
            pass

        clock = {"t": 1000.0, "n": 0}
        plugged = {0: TM, 3: TM}                     # two identical wheels
        btn = {0: 0, 3: 0}
        caps_calls = []

        class WinMM:
            def joyGetNumDevs(self):
                return 16

            def joyGetPosEx(self, i, ref):
                if i not in plugged:
                    return 167
                ref._obj.dwButtons = btn[i]
                return 0

            def joyGetDevCapsW(self, i, ref, size):
                caps_calls.append(i)
                ref._obj.szPname = plugged[i]
                return 0

        def sleep(s):
            clock["t"] += 0.5
            clock["n"] += 1
            if clock["n"] == 3:
                btn[0] = 1                           # press button 1 on the first wheel
            if clock["n"] == 20:
                del plugged[3]                       # unplug the second one ...
            if clock["n"] == 30:
                plugged[3] = TM                      # ... and plug it back in
            if clock["n"] > 45:
                raise Stop

        presses = []
        b = B.Buttons.__new__(B.Buttons)
        b.on_press, b.log, b.capture, b.ok, b.names = (lambda n, k, d: presses.append((n, k, d))), (lambda *a: None), None, False, []
        b.on_devices, b._logged_names = None, None
        fake_time = types.SimpleNamespace(time=lambda: clock["t"], sleep=sleep)
        with um.patch.object(ctypes, "WinDLL", lambda name: WinMM(), create=True), um.patch.object(B, "time", fake_time), \
                um.patch.object(B, "_oem_name", lambda vid, pid: None):
            with self.assertRaises(Stop):
                b._loop_windows()
        self.assertIn((TM, 0, True), presses)
        self.assertEqual(caps_calls.count(0), 1)     # asked once, though rescanned ~7 times
        self.assertEqual(caps_calls.count(3), 2)     # once, and again after being plugged back in
        self.assertEqual(b.names, [TM, TM + " #2"])
