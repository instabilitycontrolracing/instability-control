"""Lines the owner approved on 2026-10-28: on the render lists, said by the stand-in voice until rendered."""
import importlib
import json
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")

from engineer import lines_new, rain as R, strat_lines as SL  # noqa: E402

NEW_ENG = {"ans_say_again", "ans_which_gap", "wet_mexico_1", "wet_mexico_2", "wet_suzuka_1", "wet_suzuka_2",
           "wet_silverstone_1", "wet_silverstone_2", "wet_monza_1", "wet_monza_2"}
NEW_STRAT = {"sa_say_again", "sa_go_ahead", "sa_handoff", "sa_tyres", "sa_rain_none"}
LAP1 = {"Autódromo Hermanos Rodríguez": "autodromohermanosrodriguez",
        "Suzuka International Racing Course": "suzukainternationalracingcourse",
        "Silverstone Circuit": "silverstonecircuit", "Autodromo Nazionale Monza": "autodromonazionalemonza"}


@pytest.fixture
def vj(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.syspath_prepend(TOOLS)
    for m in ("vocab_jobs", "vocab_spec"):
        sys.modules.pop(m, None)
    return importlib.import_module("vocab_jobs")


def test_engineer_lines_on_render_list_and_stand_in(vj):
    spec = importlib.import_module("vocab_spec")
    sids = {sid for sid, _, _ in spec.L}
    assert NEW_ENG <= sids
    assert NEW_ENG <= set(lines_new.table())             # stand-in voice until rendered
    texts = [t for sid, _, t in spec.L if sid == "ans_say_again"]
    assert texts == ["Say again?", "Didn't get that, say again."]


def test_spell_keeps_corner_letters(vj):
    assert vj.spell("S Curves in the wet.") == "S Curves in the wet."
    assert vj.spell("Spoon and one-thirty R are fast.") == "Spoon and one-thirty R are fast."
    assert vj.spell("Plan A is two stops.") == "Plan Alpha is two stops."     # unchanged elsewhere
    assert vj.corner_say("130R") == "One-thirty R." and vj.corner_say("Maggots") == "Maggotts."
    assert vj.corner_say("Senna S") == "Senna Ess." and vj.corner_say("Le Mans") == "Le Mans."


def test_corner_tracks(vj, tmp_path):
    lm = lambda *names: [{"landmarkNames": [n], "distanceRoundLapStart": i * 100, "distanceRoundLapEnd": i * 100 + 50}
                         for i, n in enumerate(names)]
    d = {"trackLandmarksData": [
        {"irTrackName": "suzuka grandprix", "trackLandmarks": lm("first_esses", "130R", "turn_3")},
        {"irTrackName": "silverstone 2019 gp", "trackLandmarks": lm("maggots", "abbey")},
        {"irTrackName": "sebring international", "trackLandmarks": lm("le_mans", "kristensen")},
        {"irTrackName": "brandshatch grandprix", "trackLandmarks": lm("paddock_hill")},     # a track pack
        {"irTrackName": "zandvoort grandprix", "trackLandmarks": lm("tarzanbocht")},        # pack, older layout id
        {"irTrackName": "charlotte 2018 2019 roval", "trackLandmarks": lm("the_first_chicane")},
        {"irTrackName": "spa up", "trackLandmarks": lm("la_source")},                       # as before
        {"irTrackName": "texas oval", "trackLandmarks": lm("the_tri_oval")},                # oval: never
        {"irTrackName": "nowhere raceway", "trackLandmarks": lm("church")},                 # no pack: no
        {"irTrackName": "chicagoland", "isOval": True, "trackLandmarks": lm("the_tri_oval")},   # oval, not Chicago
        {"irTrackName": "", "trackLandmarks": lm("no_ir_name")},
    ]}
    p = tmp_path / "lm.json"
    p.write_text(json.dumps(d))
    names = vj.corner_names([str(p)])
    for n in ("First Esses", "130R", "Maggots", "Abbey", "Le Mans", "Kristensen", "Paddock Hill", "Tarzanbocht",
              "The First Chicane", "La Source"):
        assert n in names, n
    for n in ("The Tri Oval", "Church", "No Ir Name"):
        assert n not in names, n
    assert "Turn 3" not in names
    # the clip keys are the ones the app looks up (corners.py slug of the same name)
    from engineer.corners import slug, _pretty
    assert {slug(_pretty(r)) for r in ("130R", "degner1", "le_mans", "maggots")} == {"130r", "degner_1", "le_mans", "maggots"}


def test_corner_clip_missing_falls_back_to_turn_number(tmp_path):
    from engineer.corners import Corners
    d = {"trackLandmarksData": [{"irTrackName": "suzuka grandprix", "trackLandmarks": [
        {"landmarkNames": ["130R", "turn_15"], "distanceRoundLapStart": 4000, "distanceRoundLapEnd": 4100}]}]}
    p = tmp_path / "lm.json"
    p.write_text(json.dumps(d))
    blocks = {"130r": "blocks/corner/130r.wav", "turn_15": "blocks/corner/turn_15.wav"}
    have = {"blocks/corner/turn_15.wav"}
    c = Corners(str(p), blocks, exists=lambda rel: rel in have)
    c.set_track("suzuka grandprix")
    assert c.at(4050) == "turn_15"                         # 130R listed but not rendered yet
    have.add("blocks/corner/130r.wav")
    c.set_track("suzuka grandprix")
    assert c.at(4050) == "130r"
    assert Corners(str(p), blocks).set_track("suzuka grandprix") == 1    # no check given: as before


def test_voice_stand_in_says_new_lines(tmp_path):
    from engineer.voice import Voice
    (tmp_path / "manifest.json").write_text(json.dumps({"lines": [], "blocks": {}}))
    v = Voice(str(tmp_path), output=False, log=lambda *a: None)
    assert v.build("ans_which_gap")[1] == "Ahead or behind?"
    assert v.build("ans_say_again", {"_variant": 2})[1] == "Didn't get that, say again."
    assert v.build("wet_suzuka_1")[1] == "S Curves in the wet. Smooth hands, no kerbs."


def test_strategist_units():
    keys = {k for k, _ in SL.units()}
    for lid in NEW_STRAT:
        assert f"{lid}~0~0" in keys
    assert {"sa_tyres~1~1", "sa_say_again~1~0"} <= keys
    for k in LAP1.values():
        assert {f"{k}~0~0", f"{k}~0~1"} <= keys
    for disp, k in LAP1.items():
        assert SL.track_lap1(disp) == k
    L = SL.Lines(seed=1)
    for _ in range(5):
        assert L.say("sa_tyres", variant=1, laps="13 laps")["text"] == "Tyres have done 13 laps. We change them at the stop."
    spec = SL.SPOKEN[SL.norm_text("Tyres have done 13 laps.")]
    assert spec[0] == "sa_tyres~1~0" and spec[2] == {"laps": "13 laps"}


def test_wet_tips_spoken_once_on_the_card():
    for name, key in (("suzuka grandprix", "suzukainternationalracingcourse"), ("silverstone 2019 gp", "silverstonecircuit"),
                      ("mexicocity gp", "autodromohermanosrodriguez"), ("monza full", "autodromonazionalemonza")):
        tips = {t for s in range(6) for t in R.tips(3, seed=s, track_key=name)}
        assert tips & set(R.TRACK_WET[key]), name
        for t in R.TRACK_WET[key]:
            assert R.wet_sid(t) and R.wet_sid(t).startswith("wet_")
    notes = R.track_notes("Suzuka International Racing Course", "suzuka grandprix")
    assert notes == R.TRACK_WET["suzukainternationalracingcourse"]           # spoken tips only, once
    assert R.wet_sid("Brake in a straight line, release slowly. Most rain crashes start with braking while turning.") is None


class _B:
    def __init__(self, src, race=True):
        self.src, self._race = src, race

    def is_race(self):
        return self._race

    def g(self, k, d=None):
        return self.src.get(k, d)

    def info(self, k, d=None):
        return d


def _strat(src, stops, tyre_age=7, race=True):
    from engineer.strat_live import Strategist
    said = []
    st = Strategist(lambda role, t: said.append((role, t)), log=lambda *a: None)
    st.b = _B(src, race)
    st.tyre_age = tyre_age
    st.plans = [{"res": {"stops": stops}}] if stops is not None else []
    st._forecast = lambda: None
    return st, said


def test_strategist_tyres_answer_live_data():
    st, said = _strat({"LapCompleted": 10}, [{"lap": 20, "tyres": True}])
    assert st.answer("tyres") and said == [("STRATEGIST", "Tyres have done 7 laps."), ("STRATEGIST", "We change them at the stop.")]
    st, said = _strat({"LapCompleted": 10}, [{"lap": 20, "tyres": False}], tyre_age=1)
    assert st.answer("tyres") and said == [("STRATEGIST", "Tyres have done 1 lap."), ("STRATEGIST", "They should go to the end.")]
    st, said = _strat({"LapCompleted": 25}, [{"lap": 20, "tyres": True}])        # stop done: to the end
    assert st.answer("tyres") and said[-1] == ("STRATEGIST", "They should go to the end.")
    for args in (dict(stops=None), dict(stops=[], tyre_age=0), dict(stops=[], race=False)):   # nothing known: engineer
        st, said = _strat({"LapCompleted": 3}, **args)
        assert not st.answer("tyres") and not said


def test_strategist_dry_no_rain():
    st, _ = _strat({"TrackWetness": 1, "Precipitation": 0.0, "WeatherDeclaredWet": False}, [])
    assert st.dry_no_rain()
    st, _ = _strat({"TrackWetness": 4}, [])
    assert not st.dry_no_rain()
    st, _ = _strat({"TrackWetness": 1, "Precipitation": 0.2}, [])
    assert not st.dry_no_rain()
    st, _ = _strat({"TrackWetness": 1}, [])
    st._forecast = lambda: {"rain": 40}
    assert not st.dry_no_rain()
