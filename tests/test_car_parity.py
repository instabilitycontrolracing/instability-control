"""Car parity phase 2 (2026-10-29): every Sports Car / Prototype works like the BMWs, from the sourced car table."""
import types, unittest

from engineer import cars, classes, setup_bank, mechanic, pit, audio_tool, series, timing, memory
from engineer.car_data import CARS
from engineer.telemetry import CAR_NAMES, car_name


class FakeBrain:
    """Just enough of brain.Brain for the car checks."""
    def __init__(self, driver, src=None):
        self._d, self.src = driver, src or {}
        self.fuel_laps, self.electric = [], False

    def drivers(self):
        return {0: self._d}

    def me(self):
        return 0

    def g(self, k, d=None):
        v = self.src.get(k)
        return d if v is None else v

    def info(self, k, d=None):
        return {"DriverInfo": {"DriverCarFuelMaxLtr": 100, "DriverCarMaxFuelPct": 1}}.get(k, d)


def brain_of(driver, **src):
    from engineer.brain import Brain
    b = Brain.__new__(Brain)
    b.drivers = lambda: {0: driver}
    b.me = lambda: 0
    return b


class CarTable(unittest.TestCase):
    def test_table(self):
        self.assertEqual(len(CARS), 91)
        self.assertEqual(len({c["id"] for c in CARS}), 91)
        self.assertTrue(all(c["src"] for c in CARS))
        # only verified CarPaths: the from-memory candidates are not in the table
        for p in ("nissangtpzxt", "audir8gt3", "bmwz4gt3", "porsche911rgt3", "mercedesamggt3"):
            self.assertNotIn(p, cars.BY_PATH)
        self.assertEqual(sum(1 for c in CARS if c["path"]), 59)
        # aids only where a source says so
        self.assertIs(cars.lookup("bmwlmdh")["abs"], False)
        self.assertIs(cars.lookup("bmwm4gt3")["abs"], True)
        self.assertIsNone(cars.lookup("porsche963gtp")["abs"])
        self.assertIsNone(cars.lookup("dallarap217")["hybrid"])          # "no (not stated)" stays unknown

    def test_lookup_by_id(self):
        self.assertEqual(cars.lookup(None, 77)["name"], "Nissan GTP ZX-T")
        self.assertEqual(cars.lookup("whatever", 158)["kind"], "electric")
        self.assertIsNone(cars.lookup("nosuchcar", None))

    def test_names(self):                                                     # E1
        self.assertNotIn("bmwm4evogt3", CAR_NAMES)
        self.assertEqual(car_name("bmwm4evogt4"), "BMW M4 G82 GT4 Evo")
        for p, n in {"bmwlmdh": "BMW M Hybrid V8", "bmwm4gt3": "BMW M4 GT3", "bmwm2g87": "BMW M2", "bmwm4gt4": "BMW M4 GT4"}.items():
            self.assertEqual(car_name(p), n)
        self.assertEqual(car_name("ferrari499p"), "Ferrari 499P")
        self.assertEqual(car_name("unknowncar"), "unknowncar")
        self.assertGreaterEqual(len(CAR_NAMES), 59)

    def test_notes(self):                                                     # E2
        self.assertEqual(series.CAR_NOTES["bmwlmdh"], ["No ABS: front lock = pink lights.", "Brake migration and bias from the wheel."])
        self.assertEqual(series.CAR_NOTES["bmwm4gt3"], ["ABS and TC: use the dials, don't fight them."])
        self.assertIn("FWD.", series.CAR_NOTES["hondacivictyper"])
        self.assertIn("No hybrid: no deploy, regen or battery calls.", series.CAR_NOTES["amvalkyriegtp"])
        self.assertNotIn("lamborghinievogt3", series.CAR_NOTES)               # trivia only: no note
        for n in sum(series.CAR_NOTES.values(), []):
            self.assertTrue(0 < len(n) <= 120, n)


class GtpHybrid(unittest.TestCase):                                            # E11
    def test_table_rules(self):
        self.assertTrue(cars.is_gtp("bmwlmdh") and cars.is_hybrid("bmwlmdh"))
        self.assertTrue(cars.is_gtp("porsche963gtp") and cars.is_hybrid("porsche963gtp"))
        self.assertTrue(cars.is_gtp("amvalkyriegtp"))
        self.assertFalse(cars.is_hybrid("amvalkyriegtp"))
        self.assertFalse(cars.is_gtp("nissangtpzxt", 77, "gtp nissan gtp zx-t"))
        self.assertFalse(cars.is_hybrid("nissangtpzxt", 77, "gtp"))
        self.assertFalse(cars.is_gtp("porsche919"))
        self.assertTrue(cars.is_gtp("somefuturelmdh", None, ""))             # unknown cars: the old word match
        self.assertFalse(cars.is_gtp("bmwm4gt3"))

    def test_brain(self):
        nissan = {"CarPath": "nissangtpzxt", "CarID": 77, "CarClassShortName": "GTP", "CarScreenName": "Nissan GTP ZX-T"}
        valk = {"CarPath": "amvalkyriegtp", "CarID": 212, "CarClassShortName": "GTP", "CarScreenName": "Aston Martin Valkyrie AMR-LMH"}
        bmw = {"CarPath": "bmwlmdh", "CarID": 159, "CarClassShortName": "GTP", "CarScreenName": "BMW M Hybrid V8"}
        m4 = {"CarPath": "bmwm4gt3", "CarID": 132, "CarClassShortName": "GT3", "CarScreenName": "BMW M4 GT3 EVO"}
        self.assertFalse(brain_of(nissan).is_gtp())
        self.assertTrue(brain_of(valk).is_gtp()); self.assertFalse(brain_of(valk).is_hybrid())
        self.assertTrue(brain_of(bmw).is_gtp()); self.assertTrue(brain_of(bmw).is_hybrid())
        self.assertFalse(brain_of(m4).is_gtp()); self.assertFalse(brain_of(m4).is_hybrid())
        self.assertTrue(brain_of({"CarPath": "x", "CarID": 158}).is_electric())


class ClassLabels(unittest.TestCase):                                          # E12
    def test_name_fallback(self):
        cup = {"CarPath": "porsche992cup", "CarID": 143, "CarScreenName": "Porsche 911 GT3 Cup (992.1)"}
        self.assertIsNone(classes.label(cup))                                 # was "GT3" from the name
        self.assertEqual(classes.text(cup), "Cup (Porsche)")
        self.assertIsNone(classes.label({"CarID": 118, "CarScreenName": "Supercars Ford Mustang GT"}))
        self.assertIsNone(classes.label({"CarID": 77, "CarScreenName": "Nissan GTP ZX-T"}))
        self.assertEqual(classes.label({"CarPath": "ligierjsp320", "CarScreenName": "Ligier JS P320"}), "LMP3")
        # iRacing's own class data still comes first
        self.assertEqual(classes.label({"CarPath": "bmwm4gt3", "CarClassShortName": "GTD"}), "GTD")
        self.assertEqual(classes.label({"CarPath": "x", "CarClassID": 4029}), "GTP")
        self.assertEqual(classes.label({"CarScreenName": "Some GT3 car", "CarPath": "newgt3"}), "GT3")

    def test_timing_and_memory(self):
        self.assertEqual(timing.class_name([{"CarPath": "hondacivictyper", "CarScreenName": "Honda Civic Type R"}]), "TCR")
        self.assertEqual(timing.class_name([{"CarPath": "porsche992cup"}]), "Cup (Porsche)")
        self.assertEqual(timing.class_name([{"CarClassShortName": "GT3 Class", "CarPath": "porsche992cup"}]), "GT3 Class")
        self.assertEqual(memory.car_class("porsche992cup"), "")
        self.assertEqual(memory.car_class("bmwm4gt3"), "GT3")
        self.assertEqual(memory.car_class("bmwlmdh"), "GTP")
        self.assertEqual(memory.car_class("hondacivictyper"), "TCR")
        self.assertEqual(memory.car_class("porsche992cup", "GT3 Cup"), "GT3")   # a class name from iRacing still wins


def sess_of(path, car_id=None, d=None, source="ibt", gtp=False):
    return types.SimpleNamespace(car_path=path, car_id=car_id, car_class="", gtp=gtp, d=d or {}, source=source)


class Kinds(unittest.TestCase):                                                # E7 / E8
    def test_car_kind(self):
        self.assertEqual(mechanic.car_kind(sess_of("bmwlmdh", gtp=True)), "gtp")
        self.assertEqual(mechanic.car_kind(sess_of("bmwm4gt3")), "gt3")
        self.assertEqual(mechanic.car_kind(sess_of("bmwm4evogt4")), "gt4")     # "evo" no longer makes it a GT3
        self.assertEqual(mechanic.car_kind(sess_of("dallarap217")), "lmp2")
        self.assertEqual(mechanic.car_kind(sess_of("audirs3lms")), "tcr")
        self.assertEqual(mechanic.car_kind(sess_of("porsche992cup")), "cup")
        self.assertEqual(mechanic.car_kind(sess_of("x", 77)), "classic")
        self.assertEqual(mechanic.car_kind(sess_of("newcargt3")), "gt3")       # unknown: as before
        self.assertEqual(mechanic.car_kind(sess_of("newcar")), "other")

    def test_bank_tables(self):
        self.assertEqual(setup_bank.table_kind("gt4"), "other")
        self.assertEqual(setup_bank.bank_for("tcr"), setup_bank.bank_for("other"))
        # the BMWs' banks are unchanged by known aids
        self.assertEqual(setup_bank.bank_for("gt3"), setup_bank.bank_for("gt3", {"abs": True, "tc": True}))
        self.assertEqual(setup_bank.bank_for("gtp"), setup_bank.bank_for("gtp", {"abs": False, "tc": True}))

    def test_no_abs_no_tc(self):                                              # E9 in the bank
        b = setup_bank.bank_for("gt3", {"abs": False, "tc": False})
        keys = {s.get("key") for p in b["problems"] for s in p["steps"]}
        self.assertFalse(keys & {"abs", "tc", "tc1", "tc2"})
        self.assertTrue(all(p["steps"] for p in b["problems"]))
        b = setup_bank.bank_for("other", {"abs": False, "tc": None})
        keys = {s.get("key") for p in b["problems"] for s in p["steps"]}
        self.assertNotIn("abs", keys)
        self.assertIn("tc", keys)                                            # unknown keeps the step

    def test_session_aids(self):
        import numpy as np
        nan = np.full(5, np.nan)
        self.assertEqual(cars.session_aids(sess_of("newcar", d={"dcABS": np.ones(5)})), {"abs": True, "tc": False})
        self.assertEqual(cars.session_aids(sess_of("newcar", d={"dcABS": nan}, source="live")), {"abs": False, "tc": False})
        self.assertEqual(cars.session_aids(sess_of("newcar", d={}, source="replay")), {"abs": None, "tc": None})
        self.assertEqual(cars.session_aids(sess_of("bmwlmdh", d={}, source="replay")), {"abs": False, "tc": True})
        self.assertEqual(cars.session_aids(sess_of("newcar", d={"dcTractionControl2": np.ones(5)})), {"abs": False, "tc": True})

    def test_mechanic_fix_words(self):
        S = lambda *n: None
        tr = {}
        main, alt = mechanic._fix("other", "understeer", "entry", False, S, tr, {"abs": False})
        self.assertNotIn("ABS", main + alt)
        main, alt = mechanic._fix("other", "oversteer", "exit", False, S, tr, {"tc": False})
        self.assertNotIn("raction", main + alt)
        main, alt = mechanic._fix("gtp", "oversteer", "exit", False, S, tr, {"tc": False})
        self.assertNotIn("TC", main + alt)
        # unchanged when the car has them / unknown
        self.assertEqual(mechanic._fix("gt3", "understeer", "entry", False, S, tr), mechanic._fix("gt3", "understeer", "entry", False, S, tr, {"abs": True}))


class InCarCalls(unittest.TestCase):                                           # E9 on the radio
    def test_rule(self):
        allv = lambda v: True
        no_abs = lambda v: v != "dcABS"
        none = lambda v: False
        self.assertEqual(pit.in_car_rule("gt3", "front_lock", None, allv), ("dcABS", "A B S one step up"))
        self.assertEqual(pit.in_car_rule("gt3", "front_lock", None, no_abs), ("dcBrakeBias", "brake bias half a percent rearward"))
        self.assertIsNone(pit.in_car_rule("gt3", "front_lock", None, none))
        self.assertEqual(pit.in_car_rule("gt3", "traction", None, lambda v: v not in ("dcTractionControl",)),
                         ("dcAntiRollRear", "rear bar one step softer"))
        # the BMWs: same calls as before when the car has the controls
        for kind in ("gtp", "gt3"):
            for (p, ph), v in pit.IN_CAR[kind].items():
                self.assertEqual(pit.in_car_rule(kind, p, ph, allv, loose=False), v)

    def test_crew_live_check(self):
        c = pit.PitCrew.__new__(pit.PitCrew)
        c.b = FakeBrain({"CarPath": "mx5 mx52016", "CarID": 67}, {"Speed": 30.0, "dcBrakeBias": 52.0})
        self.assertFalse(c.has_control("dcABS"))
        self.assertTrue(c.has_control("dcBrakeBias"))
        c.b = FakeBrain({"CarPath": "bmwlmdh", "CarID": 159}, {})            # not live: the table decides
        self.assertFalse(c.has_control("dcABS"))
        self.assertTrue(c.has_control("dcTractionControl2"))
        c.b = FakeBrain({"CarPath": "newcar"}, {})
        self.assertTrue(c.has_control("dcABS"))                               # unknown: as before


class Electric(unittest.TestCase):                                             # E15
    def test_no_fuel(self):
        from engineer.brain import Brain
        b = Brain.__new__(Brain)
        b.fuel_laps, b.electric = [2.0, 2.1], True
        self.assertIsNone(b.fuel_lap_est())
        b.electric = False
        self.assertAlmostEqual(b.fuel_lap_est(), 2.05)
        c = pit.PitCrew.__new__(pit.PitCrew)
        c.b = FakeBrain({"CarID": 158}); c.b.electric = True; c.stint = [(1, 90.0, True, 2.0)]
        self.assertIsNone(c.tank())
        self.assertIsNone(c.fuel_per_lap())


class SoundAndPit(unittest.TestCase):
    def test_voices(self):                                                    # E4
        self.assertEqual(audio_tool.voice_for("bmwlmdh"), ("bmwlmdh", audio_tool.CAR_VOICES["bmwlmdh"]))
        self.assertEqual(audio_tool.voice_for("bmwm4gt3"), ("", audio_tool.CAR_VOICES[""]))
        self.assertEqual(audio_tool.voice_for("unknowncar"), ("", audio_tool.CAR_VOICES[""]))
        self.assertEqual(audio_tool.voice_for("amvantagegt4")[0], "")          # engine not on iRacing's page: generic
        self.assertEqual(audio_tool.voice_for("bmwm2g87")[0], "")              # engine flagged unverified: generic
        k, v = audio_tool.voice_for("lamborghinievogt3")                      # V10, 8,000 rpm shift light
        self.assertEqual(k, "lamborghinievogt3")
        top = 8000 * 10 / 120
        self.assertEqual(v["filters"][1][2], int(round((top + top * 4500 / 8200) / 2 / 10) * 10))
        self.assertTrue(v.get("draft"))
        self.assertTrue(all(f[2] < 5000 for f in v["filters"]))

    def test_pit_clips(self):                                                 # E16
        from engineer.ambience import PIT_CLIPS
        self.assertEqual(PIT_CLIPS["lmp2"], "gtp")
        self.assertEqual(PIT_CLIPS["gt4"], "gt3")
        self.assertEqual(PIT_CLIPS["gtd"], "gt3")
        self.assertNotIn("tcr", PIT_CLIPS)


if __name__ == "__main__":
    unittest.main()
