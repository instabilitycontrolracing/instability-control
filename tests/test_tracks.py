"""Per-track content for the rest of 2026 S4 (2026-10-28): schedule weeks, watch notes, drills, wet notes, grandstand maps."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engineer import crowd as C, rain as R, schedule as SC, series as SE
from engineer.forensics import CAUSES, drill_text

TRACKS = [("Autódromo Hermanos Rodríguez", "mexicocity gp"), ("Suzuka International Racing Course", "suzuka grandprix"),
          ("Silverstone Circuit", "silverstone 2019 gp"), ("Sebring International Raceway", "sebring international"),
          ("Autodromo Nazionale Monza", "monza full")]


class Schedule(unittest.TestCase):
    def test_weeks_match_the_account_order(self):
        w = SE.series_by_id("imsa_open")["weeks"]
        self.assertEqual(sorted(w), list(range(1, 13)))
        self.assertEqual(w[8], "Autódromo Hermanos Rodríguez")
        self.assertEqual(w[11], "Sebring International Raceway")
        self.assertEqual(w[12], "Autodromo Nazionale Monza")
        self.assertEqual(SE.series_by_id("imsa_fixed")["weeks"], w)
        e = SE.series_by_id("imsa_endurance")
        self.assertEqual(e["weeks"][9], "Suzuka International Racing Course")
        self.assertEqual(e["dates"][9], "2026-11-14")

    def test_week_line_without_space_after_date(self):
        m = SC.WEEK_RE.match("Week 10 (2026-11-17)Silverstone Circuit - Grand Prix")
        self.assertEqual((m.group(1), m.group(3)), ("10", "Silverstone Circuit - Grand Prix"))
        self.assertTrue(SC.WEEK_RE.match("Week 8 (2026-11-03) Autódromo Hermanos Rodríguez - Grand Prix"))


class Notes(unittest.TestCase):
    def test_every_track_has_watch_notes_by_name_or_id(self):
        for disp, tid in TRACKS:
            for n in (disp, tid):
                ti = SE.track_info(n)
                self.assertTrue(ti and len(ti["watch"]) >= 4, n)

    def test_le_mans_drills_unchanged(self):
        for code in ("contact_ahead", "contact_side"):
            self.assertEqual(drill_text(code, "lemans full", "Circuit des 24 Heures du Mans"), CAUSES[code]["drill"])

    def test_other_tracks_never_get_le_mans_corners(self):
        for disp, tid in TRACKS + [("Okayama International Circuit", "okayama full")]:
            for code in ("contact_ahead", "contact_side"):
                t = drill_text(code, tid, disp)
                self.assertNotIn("Dunlop", t)
                self.assertNotIn("Mulsanne", t)

    def test_wet_notes_are_text_only(self):
        spoken = {t for k in R.TIPS for t in R.TIPS[k]} | {t for v in R.TRACK_WET.values() for t in v}
        for disp, tid in TRACKS:
            notes = R.track_notes(disp, tid)
            self.assertTrue(notes, disp)
            for seed in range(20):                       # the radio never says a text-only note
                for t in R.tips(3, seed=seed, track_key=disp):
                    self.assertIn(t, spoken)


class Grandstands(unittest.TestCase):
    def test_bundled_maps_load_and_match_only_their_layout(self):
        for disp, tid in TRACKS:
            m = C.find_track([C.BUNDLED_TRACKS], tid, "")
            self.assertIsNotNone(m, tid)
            self.assertGreaterEqual(len(m.stands), 4)
            for s in m.stands:
                self.assertTrue(0 <= s.frm < 1 and 0 <= s.to < 1 and 0 < s.length < 0.15, (tid, s.name))
        self.assertIsNone(C.find_track([C.BUNDLED_TRACKS], "mexicocity oval", ""))
        self.assertIsNone(C.find_track([C.BUNDLED_TRACKS], "lemans full", ""))


if __name__ == "__main__":
    unittest.main()
