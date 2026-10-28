"""Track research packs (2026-10-28): every bundled grandstand map loads, every iRacing id resolves, text stays text."""
import glob, json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engineer import crowd as C, rain as R, series as SE
from engineer.forensics import drill_text
from engineer.track_packs import PACK_ALIASES, PACK_TRACKS, PACK_WET

# (iRacing TrackName id, track display name) -> the short name the Series tab shows
SAMPLE = [("brandshatch grandprix", "Brands Hatch Circuit", "Brands Hatch"), ("spa 2024 up", "Circuit de Spa-Francorchamps", "Spa"),
          ("roadatlanta full", "Michelin Raceway Road Atlanta", "Road Atlanta"), ("daytona 2011 road", "Daytona International Speedway", "Daytona"),
          ("watkinsglen 2021 fullcourse", "Watkins Glen International", "Watkins Glen"), ("cota gp", "Circuit of the Americas", "COTA"),
          ("nurburgring nordschleife", "Nürburgring Nordschleife", "Nordschleife"), ("nurburgring combined", "Nürburgring Combined", None),
          ("nurburgring gp", "Nürburgring Grand-Prix-Strecke", None), ("bathurst", "Mount Panorama Circuit", None),
          ("lagunaseca 2026", "WeatherTech Raceway at Laguna Seca", None), ("imola gp", "Autodromo Internazionale Enzo e Dino Ferrari", None),
          ("spielberg gp", "Red Bull Ring", None), ("zandvoort 2023 gp", "Circuit Zandvoort", None), ("montreal", "Circuit Gilles Villeneuve", None),
          ("oulton international", "Oulton Park Circuit", None), ("virginia 2022 full", "VIRginia International Raceway", None),
          ("okayama full", "Okayama International Circuit", None), ("interlagos gp", "Autódromo José Carlos Pace", None)]
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = sorted(glob.glob(os.path.join(HERE, "engineer", "trackside_tracks", "*.json")))


class Aliases(unittest.TestCase):
    def test_sample_of_iracing_names_resolve(self):
        for tid, disp, short in SAMPLE:
            a, b = SE.track_info("", tid), SE.track_info(disp)
            self.assertIsNotNone(a, tid)
            self.assertIs(a, b, (tid, disp))
            if short:
                self.assertEqual(a["name"], short, tid)

    def test_every_alias_resolves_to_its_own_track(self):
        for a, k in PACK_ALIASES.items():
            self.assertIs(SE.track_info(a), SE.TRACKS[k], a)
        for k in PACK_TRACKS:
            self.assertIs(SE.track_info(k), SE.TRACKS[k], k)

    def test_hand_done_tracks_unchanged(self):
        self.assertEqual(SE.track_info("sebring club")["name"], "Sebring")
        self.assertEqual(SE.track_info("lemans full")["watch"][0], "Dunlop Chicane: lap-1 pile-ups. Brake early on lap 1.")
        for k in ("circuitdes24heuresdumans", "sebringinternationalraceway", "autodromonazionalemonza", "silverstonecircuit",
                  "suzukainternationalracingcourse", "autodromohermanosrodriguez"):
            self.assertNotIn(k, PACK_TRACKS)

    def test_watch_notes_short_and_drills_name_the_track(self):
        for k, v in PACK_TRACKS.items():
            for w in v.get("watch", []):
                self.assertLessEqual(len(w), 70, w)
        t = drill_text("contact_ahead", "brandshatch grandprix", "Brands Hatch Circuit")
        self.assertNotIn("Mulsanne", t)
        self.assertIn("Paddock Hill Bend", SE.drill_spots("brandshatch grandprix")["lap1"])


class Wet(unittest.TestCase):
    def test_wet_notes_reach_the_series_tab_but_never_the_radio(self):
        spoken = {t for k in R.TIPS for t in R.TIPS[k]} | {t for v in R.TRACK_WET.values() for t in v}
        for k, notes in PACK_WET.items():
            got = R.track_notes(k)
            for n in notes:
                self.assertIn(n, got, k)
                self.assertNotIn(n, spoken)
        # round 2: Brands Hatch's two text notes became spoken tips (the card lists each once); Spa keeps its text note
        self.assertTrue(set(PACK_WET["circuitdespafrancorchamps"]) <= set(R.track_notes("Circuit de Spa-Francorchamps", "spa up")))
        self.assertFalse(set(PACK_WET["circuitdespafrancorchamps"]) & set(R.track_notes("Cadwell Park Circuit", "cadwell full")))
        self.assertEqual(R.track_notes("Brands Hatch Circuit", "brandshatch indy"), R.TRACK_WET["brandshatchcircuit"])


class Grandstands(unittest.TestCase):
    def test_every_bundled_map_loads_and_is_found_by_its_own_id(self):
        self.assertGreaterEqual(len(BUNDLED), 60)
        for p in BUNDLED:
            with open(p, encoding="utf-8-sig") as fh:
                d = json.load(fh)
            m = C.TrackMap(d, p)
            self.assertTrue(m.match and m.stands and m.length_m > 0, p)
            for s in m.stands:
                self.assertTrue(0 <= s.frm < 1 and 0 <= s.to < 1 and 0 < s.length < 0.2, (p, s.name))
            for tid in m.match:
                self.assertEqual(C.find_track([C.BUNDLED_TRACKS], tid, "").source, p, tid)

    def test_users_own_map_still_wins(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "mine.json"), "w") as fh:
                json.dump({"Track": "mine", "Match": ["brandshatch grandprix"], "Stands": []}, fh)
            self.assertEqual(C.find_track([C.BUNDLED_TRACKS, td], "brandshatch grandprix", "").track, "mine")


if __name__ == "__main__":
    unittest.main()
