"""Trackside crowd (2026-10-24). No iRacing, no speakers: synthetic sounds, offline mixing.

    python -m unittest tests.test_crowd -v
"""
import json, math, os, random, shutil, sys, tempfile, types, unittest

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from engineer import crowd as C      # noqa: E402
import crowd_synth as CS             # noqa: E402

LE_MANS = os.path.join(HERE, "fixtures", "le_mans.json")
_TMP = tempfile.mkdtemp(prefix="ic_crowd_")
SOUNDS = os.path.join(_TMP, "sounds")
CS.write_all(SOUNDS, C.SOUND_NAMES)
CLIPS = C.load_sounds(SOUNDS, os.path.join(_TMP, "levels.json"), log=lambda *a: None)


def S(**kw):
    s = types.SimpleNamespace(crowd_on=True, crowd_volume=0.3, crowd_max_db=-18.0, crowd_mute=False, crowd_pa=True,
                              crowd_heli=True, crowd_mute_pits=True, crowd_duck=True, crowd_others=True,
                              crowd_intensity=100, crowd_max_voices=6)
    s.__dict__.update(kw)
    return s


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def mixer(**kw):
    m = C.Mixer(log=lambda *a: None, **kw)
    m.clock = FakeClock()
    m.heartbeat()
    return m


def run(m, seconds, beat=True):
    """Render offline; returns the output."""
    out, buf = [], np.zeros((m.block, 2), np.float32)
    for _ in range(int(seconds * m.rate / m.block)):
        if beat:
            m.heartbeat()
        m.render(buf)
        out.append(buf.copy())
        m.clock.t += m.block / m.rate
    return np.concatenate(out) if out else np.zeros((0, 2), np.float32)


def director(m=None, settings=None, seed=3):
    m = m or mixer()
    d = C.Director(m, CLIPS, [os.path.dirname(LE_MANS)], settings or S(), rng=random.Random(seed), log=lambda *a: None)
    return d


def frame(pct, **kw):
    f = dict(running=True, on_track=True, in_pits=False, track_id="lemans full", track_name="Circuit des 24 Heures du Mans",
             session="Race", track_len=13626.0, pct=pct, speed_kmh=200.0, lap=1, cars=[])
    f.update(kw)
    return C.Frame(**f)


class TrackMatching(unittest.TestCase):
    def test_le_mans_found_by_id_or_name(self):
        folder = os.path.dirname(LE_MANS)
        m = C.find_track([folder], "lemans full", "")
        self.assertIsNotNone(m)
        self.assertEqual(len(m.stands), 12)
        self.assertIsNotNone(C.find_track([folder], "", "Circuit des 24 Heures du Mans"))
        self.assertIsNone(C.find_track([folder], "spa 2024 up", "Circuit de Spa-Francorchamps"))

    def test_user_file_wins_bom_and_case_insensitive_keys(self):
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        shutil.copy(LE_MANS, a)
        mine = {"track": "Le Mans (mine)", "match": ["lemans"], "stands": [{"name": "Mine", "from": 0.5, "to": 0.52, "side": "r"}]}
        with open(os.path.join(b, "lm.json"), "w", encoding="utf-8-sig") as f:
            json.dump(mine, f)
        open(os.path.join(b, "broken.json"), "w").write("{nope")
        m = C.find_track([a, b], "lemans full", "")
        self.assertEqual(m.track, "Le Mans (mine)")
        self.assertEqual(m.stands[0].side, "R")
        self.assertEqual(m.stands[0].sign, 1.0)

    def test_wrapping_stand(self):
        m = C.TrackMap(json.load(open(LE_MANS)))
        main = [s for s in m.stands if s.name == "Main grandstands"][0]
        self.assertAlmostEqual(main.length, 0.064, places=6)
        self.assertAlmostEqual(main.closest(0.0), 0.0)
        self.assertAlmostEqual(main.closest(0.5), main.to if abs(0.5 - main.to) < abs(0.5 - main.frm) else main.frm)
        self.assertEqual(len(main.emitters(13626)), 5)


class Geometry(unittest.TestCase):
    def setUp(self):
        self.d = director()
        self.d.update(frame(0.0), 0.07)

    def test_gain_side_and_distance(self):
        d = self.d
        g, pan, dist = d.gains_for(0.0, 45, -1, 950)       # alongside the main stand, on the left
        self.assertAlmostEqual(g, 1.0)
        self.assertLess(pan, -0.8)
        g2, pan2, _ = d.gains_for(0.0, 45, 1, 950)         # same place on the right
        self.assertGreater(pan2, 0.8)
        g3, pan3, dist3 = d.gains_for(300 / 13626, 45, -1, 950)   # 300 m ahead
        self.assertLess(g3, 0.1); self.assertGreater(g3, 0.0)
        self.assertGreater(pan3, -0.2)                     # far ahead: nearly centred
        self.assertEqual(d.gains_for(2000 / 13626, 45, -1, 950)[0], 0.0)   # past max distance: silent
        self.assertGreater(d.gains_for(100 / 13626, 45, -1, 950)[0], d.gains_for(200 / 13626, 45, -1, 950)[0])

    def test_beds_follow_the_nearest_stands(self):
        d = self.d
        beds = [st for st in d.stands if st.bed is not None]
        self.assertTrue(1 <= len(beds) <= d.BED_SLOTS)
        self.assertIn("Main grandstands", [st.s.name for st in beds])
        d.update(frame(0.40), 0.07)                         # the Mulsanne straight: no crowd anywhere near
        run(d.m, 1.0)
        d.update(frame(0.40), 0.07)
        self.assertEqual([st for st in d.stands if st.bed is not None], [])

    def test_distance_variants(self):
        d = self.d
        self.assertEqual(d.variant("roar_goal", 50), "roar_goal_near")
        self.assertEqual(d.variant("roar_goal", 250), "roar_goal_mid")
        self.assertEqual(d.variant("roar_goal", 900), "roar_goal_mid")   # no _far file: closest that exists


class Events(unittest.TestCase):
    def test_pass_cheers_once_no_stacking(self):
        m = mixer(); d = director(m)
        me, other = C.CarState(0, True, 5, 5, 1.000, False), C.CarState(1, False, 4, 4, 1.002, False)
        d.update(frame(0.0, cars=[me, other]), 0.07)
        n0 = m.count()
        me2, other2 = C.CarState(0, True, 4, 4, 1.004, False), C.CarState(1, False, 5, 5, 1.003, False)
        d.update(frame(0.004, cars=[me2, other2]), 0.07)
        self.assertEqual(d.passes_seen, 1)
        self.assertGreater(m.count(), n0)
        fams = [v.family for v in list(m.voices) + list(m._new)]
        self.assertEqual(len(fams), len(set(fams)))         # never two of the same family
        before = m.count()
        # swap back and forth immediately: pair cooldown + stand cooldown -> no new sounds
        d.update(frame(0.0045, cars=[C.CarState(0, True, 5, 5, 1.0042, False), C.CarState(1, False, 4, 4, 1.0045, False)]), 0.07)
        d.update(frame(0.005, cars=[C.CarState(0, True, 4, 4, 1.005, False), C.CarState(1, False, 5, 5, 1.0048, False)]), 0.07)
        self.assertLessEqual(m.count(), before)
        self.assertLessEqual(m.count(), m.max_voices)

    def test_same_family_refused_by_mixer(self):
        m = mixer(); c = CLIPS["roar_goal_near"]
        self.assertIsNotNone(m.play(c, family="x"))
        self.assertIsNone(m.play(c, family="x"))
        for i in range(10):
            m.play(c, family=f"f{i}")
        self.assertEqual(m.count(), m.max_voices)

    def test_green_once_only_when_we_were_there_for_it(self):
        m = mixer(); d = director(m)
        d.update(frame(0.99, before_green=True, speed_kmh=80), 0.07)
        self.assertTrue(d.build_started)                    # pre-green build-up on the run to the line
        d.update(frame(0.995, before_green=True, green=True), 0.07)
        self.assertTrue(any(v.family == "green_roar" for v in list(m.voices) + list(m._new)))
        n = sum(v.family == "green_roar" for v in list(m.voices) + list(m._new))
        for _ in range(5):
            d.update(frame(0.996, before_green=True, green=True), 0.07)
        self.assertEqual(sum(v.family == "green_roar" for v in list(m.voices) + list(m._new)), n)
        # joined mid-race: no roar
        m2 = mixer(); d2 = director(m2)
        d2.update(frame(0.0, before_green=False, green=True), 0.07)
        self.assertFalse(any(v.family == "green_roar" for v in list(m2.voices) + list(m2._new)))

    def test_spin_groans(self):
        m = mixer(); d = director(m)
        d.update(frame(0.0), 0.07)
        d.update(frame(0.0, spin=True), 0.07)
        self.assertTrue(any(v.family == "groan" for v in list(m.voices) + list(m._new)))
        self.assertEqual(d.crashes_seen, 1)

    def test_other_car_crash_groans_once(self):
        m = mixer(); d = director(m)
        at = 0.67 + 0.005                                   # Indianapolis
        me = lambda: C.CarState(0, True, 3, 3, 1.66, False)
        p = 1 + at - 40 * 60 * 0.07 / 13626                 # arrives at Indianapolis on tick 40
        for i in range(60):                                 # 60 m/s, then stopped dead
            p = p + (60 * 0.07 / 13626 if i < 40 else 0)
            d.update(frame(0.66, cars=[me(), C.CarState(9, False, 9, 9, min(p, 1 + at), False)]), 0.07)
        self.assertEqual(d.crashes_seen, 1)
        self.assertEqual(sum(v.family == "groan" for v in list(m.voices) + list(m._new)), 1)

    def test_mute_in_pits_and_when_not_running(self):
        m = mixer(); d = director(m)
        d.update(frame(0.0), 0.07)
        self.assertGreater(m.count(), 0)
        d.update(frame(0.0, in_pits=True), 0.07)
        self.assertTrue(m.muted)
        out = run(m, 3.0)
        self.assertEqual(m.count(), 0)
        self.assertLess(np.abs(out[-4800:]).max(), 1e-6)
        d.update(frame(0.0), 0.07)
        self.assertFalse(m.muted)
        d.update(frame(0.0, running=False), 0.07)
        self.assertTrue(m.muted)
        m2 = mixer(); d2 = director(m2, S(crowd_mute_pits=False))
        d2.update(frame(0.0, in_pits=True), 0.07)
        self.assertFalse(m2.muted)

    def test_no_cars_running_no_crowd(self):
        """#220: nobody out on the circuit -> the stands go quiet (after 3 s); cars back -> the crowd returns."""
        m = mixer(); d = director(m)
        d.update(frame(0.0, cars_running=5), 0.07)
        self.assertTrue(any(st.bed is not None for st in d.stands))
        for _ in range(50):                                  # 3.5 s with an empty circuit
            d.update(frame(0.0, cars_running=0), 0.07)
        self.assertEqual([st for st in d.stands if st.bed is not None], [])
        run(m, 2.0)
        for _ in range(3):
            d.update(frame(0.0, cars_running=0), 0.07)
        fams = {v.family for v in list(m.voices) + list(m._new) if not v.done}
        self.assertTrue(fams <= {"_wait_bed", "pa"}, fams)    # #227: only the waiting crowd (and the PA), no cheers
        self.assertIn("_wait_bed", fams)
        d.update(frame(0.0, cars_running=1), 0.07)
        self.assertTrue(any(st.bed is not None for st in d.stands))
        d2 = director(mixer())                              # unknown (no data) never silences
        d2.update(frame(0.0), 0.07)
        self.assertTrue(any(st.bed is not None for st in d2.stands))

    def test_formation_lap_buzz_then_green_takes_over(self):
        """#227: formation lap -> an excited bed + whistles; green -> it hands over to the eruption."""
        m = mixer(max_voices=12); d = director(m)
        for _ in range(200):                                 # 14 s of formation lap
            d.update(frame(0.3, cars_running=20, sstate=3, before_green=True), 0.07)
            run(m, 0.07)
        fams = {v.family for v in list(m.voices) + list(m._new) if not v.done}
        self.assertIn("_form_bed", fams)
        d.update(frame(0.3, cars_running=20, sstate=4, before_green=True, green=True), 0.07)
        d.update(frame(0.3, cars_running=20, sstate=4, before_green=True, green=True), 0.07)
        self.assertIsNone(d._form_bed)

    def test_helmet_only_while_driving(self):
        """#230: driving -> the crowd is muffled and quieter; an onboard replay is open."""
        def level(driving):
            m = mixer(); d = director(m)
            for _ in range(40):
                d.update(frame(0.0, cars_running=10, driving=driving), 0.07)
                out = run(m, 0.07)
            out = run(m, 2.0)
            return float(np.sqrt((out ** 2).mean())), m.helmet
        open_, h0 = level(False); helm, h1 = level(True)
        self.assertEqual(h0, 0.0)
        self.assertGreater(h1, 0.9)
        self.assertLess(helm, open_ * 0.8)

    def test_session_sizes(self):
        """#231: practice stands are sparse, qualifying half, race packed."""
        sizes = {}
        for sess in ("Practice", "Qualify", "Race"):
            d = director(); d.update(frame(0.0, session=sess, cars_running=10), 0.07)
            sizes[sess] = d.sess_scale
        self.assertLess(sizes["Practice"], sizes["Qualify"])
        self.assertLess(sizes["Qualify"], sizes["Race"])

    def test_cooldown_applause_after_the_flag(self):
        """#233: after the chequered flag the crowd applauds through the cooldown lap."""
        m = mixer(max_voices=12); d = director(m)
        d.update(frame(0.0, cars_running=10, before_green=True, green=True), 0.07)
        d.update(frame(0.0, cars_running=10, chequered=True), 0.07)
        self.assertGreater(d.cool_until, d.now)
        for _ in range(300):                                 # the finish roar has the floor first; the applause follows
            d.update(frame(0.0, cars_running=10, chequered=True), 0.07)
            run(m, 0.07)
        self.assertIsNotNone(d._cool_bed)

    def test_extras_from_own_recordings(self):
        """W5 pit-lane camera turns the crowd down; W7 thunder in the rain; C7 the podium 2 minutes after the flag -
        each only when its recording exists."""
        m = mixer(max_voices=12); d = director(m)
        if d.amb is None:
            self.skipTest("no ambience")
        fake = lambda n: C.Clip(n, (np.ones((4800, 2)) * 1000).astype(np.int16), 1.0)
        for n in ("fx_thunder_1", "crowd_podium", "fx_champagne", "amb_garage"):
            d.clips[n] = fake(n)
        d.update(frame(0.0, cars_running=10, tv=True, cam="Pit Lane"), 0.07)
        self.assertEqual(d.cam_scale, 0.5)
        d.update(frame(0.0, cars_running=10, tv=True, cam="TV1"), 0.07)
        self.assertEqual(d.cam_scale, 1.0)
        d.update(frame(0.0, cars_running=10, rain=0.8), 0.07)
        fams = {v.family for v in list(m.voices) + list(m._new)}
        self.assertIn("thunder", fams)
        d.update(frame(0.0, cars_running=10, before_green=True, green=True), 0.07)
        d.update(frame(0.0, cars_running=10, chequered=True), 0.07)
        d.now += 121
        d.update(frame(0.0, cars_running=10, chequered=True), 0.07)
        self.assertTrue(d.amb._podium_done)

    def test_pa_and_heli_switches(self):
        for on in (True, False):
            m = mixer(); d = director(m, S(crowd_pa=on, crowd_heli=on))
            asked = []
            real = m.play
            m.play = lambda c, *a, **k: (asked.append(k.get("family")), real(c, *a, **k))[1]
            for i in range(3000):                           # ~200 s of ticks, slowly round the lap
                d.update(frame((i * 0.0003) % 1), 0.07)
                if i % 50 == 0:
                    m.stop_all(); run(m, 0.1)
            self.assertEqual("pa" in asked, on)
            self.assertEqual("heli" in asked, on)


class Safety(unittest.TestCase):
    def test_limiter_never_exceeds_ceiling(self):
        for db in (-18.0, -30.0, -6.0, +20.0):              # +20 is clamped to -6
            m = mixer(); m.set_volume(1.0); m.set_ceiling_db(db)
            ceil = C.db2lin(max(-48, min(-6, db)))
            loud = C.Clip("loud", (np.random.default_rng(0).uniform(-1, 1, (48000 * 2, 2)) * 32767).astype(np.int16))
            for i in range(6):
                v = m.play(loud, level=2.0, loop=True, family=f"l{i}")
                v.target = 50.0                             # a bug elsewhere asking for +34 dB
            out = run(m, 3.0)
            self.assertLessEqual(float(np.abs(out).max()), ceil + 1e-7, db)
            self.assertGreater(float(np.abs(out).max()), ceil * 0.5)

    def test_finish_with_absurd_input(self):
        m = mixer(); m.set_volume(1.0); m.master = 1.0
        out = np.zeros((m.block, 2), np.float32)
        mix = (np.random.default_rng(1).standard_normal((m.block, 2)) * 1e6).astype(np.float32)
        m._finish(mix, out)
        self.assertLessEqual(float(np.abs(out).max()), m.ceiling + 1e-7)
        mix[5, 0] = np.inf; mix[9, 1] = np.nan
        m._finish(mix, out)
        self.assertEqual(float(np.abs(out).max()), 0.0)      # broken numbers: silence, not noise

    def test_volume_and_ceiling_inputs_sanitised(self):
        m = mixer()
        for bad in ("x", None, float("nan"), float("inf")):
            m.set_volume(bad); self.assertTrue(0 <= m.volume <= 1)
            m.set_ceiling_db(bad); self.assertLessEqual(m.ceiling, C.db2lin(-6) + 1e-9)
        m.set_volume(7); self.assertEqual(m.volume, 1.0)

    def test_errors_go_silent(self):
        m = mixer(); m.set_volume(1.0)
        bad = C.Clip("bad", CLIPS["roar_goal_near"].data); bad.data = None   # a voice that blows up mid-mix
        m.play(CLIPS["roar_goal_near"], family="ok")
        m.play(bad, family="bad")
        out = np.ones((m.block, 2), np.float32)
        m.render(out)                                        # must not raise
        self.assertEqual(float(np.abs(out).max()), 0.0)
        self.assertGreaterEqual(m.errors, 1)

    def test_bad_files_skipped(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "garbage.wav"), "wb").write(b"RIFF....WAVEjunkjunk" * 10)
        x = np.zeros((4800, 2), np.float32); x[100, 0] = np.nan
        sf.write(os.path.join(d, "nan.wav"), x, 48000, subtype="FLOAT")
        sf.write(os.path.join(d, "fine.wav"), np.full((4800, 2), 0.1, np.float32), 48000)
        sf.write(os.path.join(d, "silent.wav"), np.zeros((4800, 2), np.float32), 48000)
        clips = C.load_sounds(d, None, log=lambda *a: None)
        self.assertEqual(sorted(clips), ["fine", "silent"])
        self.assertEqual(int(np.abs(clips["silent"].data).max()), 0)

    def test_watchdog_fades_out(self):
        m = mixer(); m.set_volume(1.0); m.set_ceiling_db(-6)
        m.play(CLIPS["bed_stadium_crowd_near"], loop=True, family="bed")
        on = run(m, 1.0)
        self.assertGreater(np.abs(on[-4800:]).max(), 1e-3)
        off = run(m, 4.0, beat=False)                        # the engineer stops sending updates
        self.assertLess(np.abs(off[-4800:]).max(), 1e-6)
        self.assertEqual(m.count(), 0)

    def test_fade_in_no_click(self):
        m = mixer(); m.set_volume(1.0); m.set_ceiling_db(-6); m.master = 1.0
        m.play(CLIPS["bed_stadium_crowd_near"], loop=True, family="bed")
        out = run(m, 0.5)
        first = np.abs(out[:256]).max()
        self.assertLess(first, 0.02)                          # starts from silence

    def test_ducking(self):
        talk = {"on": False}
        m = mixer(); m.set_volume(1.0); m.set_ceiling_db(-6); m.duck_fn = lambda: talk["on"]
        m.play(CLIPS["bed_stadium_crowd_near"], loop=True, family="bed")
        a = run(m, 2.0)[-24000:]
        talk["on"] = True
        b = run(m, 1.0)[-12000:]
        ra, rb = np.sqrt(np.mean(a ** 2)), np.sqrt(np.mean(b ** 2))
        self.assertAlmostEqual(C.lin2db(rb / ra), -9, delta=1.5)


class Normalisation(unittest.TestCase):
    def test_files_brought_to_target(self):
        for name in ("bed_stadium_crowd_near", "bed_crowd_buzz_mid", "cheer_A_short_mid", "whistles_1"):
            c = CLIPS[name]
            x = c.data.astype(np.float32) / 32768
            rms_db, peak_db = C.measure(x)
            self.assertLessEqual(peak_db, C.FILE_PEAK_DB + 0.1, name)
            if c.gain < C.db2lin(C.FILE_PEAK_DB) / 1e-3:     # not peak-limited: on target
                self.assertTrue(abs(rms_db - C.TARGET_RMS_DB) < 1.0 or peak_db > C.FILE_PEAK_DB - 0.5, (name, rms_db, peak_db))

    def test_quiet_and_loud_end_up_alike(self):
        d = tempfile.mkdtemp()
        rng = np.random.default_rng(5)
        n = rng.standard_normal((48000, 2)).astype(np.float32)
        sf.write(os.path.join(d, "quiet.wav"), np.clip(n * 0.003, -1, 1), 48000, subtype="FLOAT")
        sf.write(os.path.join(d, "loud.wav"), np.clip(n * 0.3, -1, 1), 48000, subtype="FLOAT")
        clips = C.load_sounds(d, os.path.join(d, "levels.json"), log=lambda *a: None)
        q = C.measure(clips["quiet"].data / 32768.0)[0]; l = C.measure(clips["loud"].data / 32768.0)[0]
        self.assertLess(abs(q - l), 1.0)

    def test_gain_cache(self):
        d = tempfile.mkdtemp()
        sf.write(os.path.join(d, "a.wav"), np.full((4800, 2), 0.05, np.float32), 48000)
        cache = os.path.join(d, "levels.json")
        C.load_sounds(d, cache, log=lambda *a: None)
        j = json.load(open(cache))
        self.assertIn("a.wav", j)
        j["a.wav"]["gain"] = 0.5                              # cached gain is used as-is (no re-measure)
        json.dump(j, open(cache, "w"))
        c = C.load_sounds(d, cache, log=lambda *a: None)["a"]
        self.assertAlmostEqual(c.gain, 0.5)


class CopyAndApp(unittest.TestCase):
    def test_copy_from_simhub_copies_never_moves(self):
        sim = tempfile.mkdtemp(); dest = tempfile.mkdtemp()
        os.makedirs(os.path.join(sim, "TracksideCrowd", "sounds")); os.makedirs(os.path.join(sim, "TracksideCrowd", "tracks"))
        os.makedirs(os.path.join(sim, "PluginsData", "TracksideCrowd", "tracks"))
        shutil.copy(os.path.join(SOUNDS, "roar_goal_near.wav"), os.path.join(sim, "TracksideCrowd", "sounds"))
        shutil.copy(LE_MANS, os.path.join(sim, "TracksideCrowd", "tracks"))
        open(os.path.join(sim, "PluginsData", "TracksideCrowd", "tracks", "mine.json"), "w").write("{}")
        open(os.path.join(sim, "TracksideCrowd", "credits.txt"), "w").write("credits")
        r = C.copy_from_simhub(dest, roots=[sim], log=lambda *a: None)
        self.assertEqual(r["copied"], 3)
        self.assertTrue(os.path.exists(os.path.join(sim, "TracksideCrowd", "sounds", "roar_goal_near.wav")))   # still there
        self.assertTrue(os.path.exists(os.path.join(dest, "sounds", "roar_goal_near.wav")))
        self.assertTrue(os.path.exists(os.path.join(dest, "tracks", "mine.json")))
        self.assertEqual(C.copy_from_simhub(dest, roots=[sim], log=lambda *a: None)["copied"], 0)
        self.assertFalse(C.copy_from_simhub(dest, roots=[tempfile.mkdtemp()], log=lambda *a: None)["ok"])

    def test_crowd_tick_from_a_fake_brain(self):
        root = tempfile.mkdtemp()
        shutil.copytree(SOUNDS, os.path.join(root, "sounds"))
        os.makedirs(os.path.join(root, "tracks")); shutil.copy(LE_MANS, os.path.join(root, "tracks"))
        cr = C.Crowd(S(), log=lambda *a: None, root=root)
        for _ in range(200):
            if cr.state != "loading":
                break
            __import__("time").sleep(0.05)
        self.assertEqual(cr.state, "ready")

        class B:
            sess_type = "Race"; green_seen = False; finished = False
            def __init__(s): s.prev = {}; s.crowd_ev = ["spin"]; s.v = {"SessionNum": 0, "SessionState": 3, "IsOnTrack": True,
                "OnPitRoad": False, "LapDistPct": 0.01, "Speed": 50, "Lap": 1, "CarIdxLapDistPct": [0.01, 0.02],
                "CarIdxLapCompleted": [0, 0], "CarIdxPosition": [2, 1], "CarIdxClassPosition": [2, 1], "CarIdxOnPitRoad": [False, False]}
            def g(s, k, d=None): return s.v.get(k, d)
            def info(s, k, d=None): return {"TrackName": "lemans full", "TrackDisplayName": "Circuit des 24 Heures du Mans"} if k == "WeekendInfo" else d
            def drivers(s): return {0: {}, 1: {}}
            def me(s): return 0
            def track_len_m(s): return 13626.0
        b = B()
        cr.tick(b); cr.tick(b)
        self.assertEqual(b.crowd_ev, [])                       # drained
        self.assertIn("24 Heures", cr.director.status)
        self.assertGreaterEqual(cr.director.crashes_seen, 1)
        cr.tick(None)
        self.assertTrue(cr.mixer.muted)
        info = cr.info()
        self.assertEqual(info["state"], "ready")
        r = cr.test()                                         # no PortAudio here: reports the device, stays silent
        self.assertIn("msg", r)
        cr.close()


if __name__ == "__main__":
    unittest.main()


class HeliAhead(unittest.TestCase):
    """2026-10-29 (efficiency): the green-flag helicopter is made in the background when the track loads - the same clip
    the green would have made itself."""
    def test_prepared_same_as_inline(self):
        import time as _t
        d1, d2 = director(), director()
        if d1.get("helicopter_low_hover") is None:
            self.skipTest("no helicopter sound in the synthetic set")
        inline = d1.heli_big()
        d2.heli_prepare()
        for _ in range(200):
            if getattr(d2, "_heli_pre", None):
                break
            _t.sleep(0.01)
        self.assertIs(d2._heli_pre[0], d2.get("helicopter_low_hover"))
        got = d2.heli_big()
        self.assertIs(got, d2._heli_pre[1])
        self.assertTrue(np.array_equal(np.asarray(got.data), np.asarray(inline.data)))
        self.assertIs(d2.heli_big(), got)                  # kept


class LoadingScreenLoop(unittest.TestCase):
    """2026-10-29: on a loading screen the crowd keeps playing as a loop of the last seconds (no gap, almost no work)."""

    def test_loop_plays_while_loading_then_live_returns(self):
        import time as _t
        m = mixer()
        m.volume = 0.3
        clip = next(iter(CLIPS.values()))
        m.play(clip, level=1.0, loop=True)
        live = run(m, 10)
        self.assertGreater(np.abs(live[-m.rate:]).max(), 1e-3)
        C.simload.BUSY = True
        try:
            run(m, 0.2)                        # starts the loop build (background thread)
            for _ in range(50):
                if m._hloop is not None:
                    break
                _t.sleep(0.05)
            self.assertIsNotNone(m._hloop)
            busy = run(m, 8)
            tail = busy[m.rate * 2:]           # after the crossfade: only the loop is playing
            self.assertGreater(np.abs(tail).max(), 1e-3)
            tail = tail[:len(tail) // m.block * m.block]
            blocks = tail.reshape(-1, m.block, 2)
            self.assertEqual(int((np.abs(blocks).max(axis=(1, 2)) < 1e-6).sum()), 0)   # no silent block
        finally:
            C.simload.BUSY = False
        m.play(clip, level=1.0, loop=True)      # the director starts the beds again after loading
        after = run(m, 4)
        self.assertGreater(np.abs(after[-m.rate:]).max(), 1e-3)
        self.assertEqual(m._hgain, 0.0)
        self.assertIsNone(m._hloop)             # next loading screen records fresh crowd
