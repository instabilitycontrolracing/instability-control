"""ic188 (#740): the radio calls approved on 2026-11-01 - replay-style checks on synthetic brain states.

Every call that is ON by default is checked to fire when it should and to stay quiet at the race start, in the pit lane,
on the tow and (where it matters) under a caution. The OFF ones are checked to stay quiet with the default settings.
"""
import importlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engineer import lines_new, radio_1101 as R1, settings as ST, voice as VO  # noqa: E402
from engineer.brain import F_GREEN, F_CAUTION  # noqa: E402
from engineer.tests import test_extras as TX  # noqa: E402


class Corners(TX.Corners):
    marks = [(0, 1, "dunlop")]

    def at(self, *a, **k):
        return "dunlop"

    def next_after(self, *a):
        return "dunlop"


def mk(session="Race", race_len="9600.0000 sec", hazard=False, **settings):
    """hazard=False: the test harness's cars stand still, so the stopped-car call (A5) would fire in every test - it is
    switched back to the old line there (rl() only looks at the new calls)."""
    b, src, v, clk = TX.setup(session)
    b.c = Corners()
    b.s.calls_hazard = hazard
    src.inf["SessionInfo"]["Sessions"][0]["SessionTime"] = race_len
    for k, val in settings.items():
        setattr(b.s, k, val)
    b.green_t = clk.t - 3600            # an hour into the race unless a test says otherwise
    src.v["PlayerCarTowTime"] = 0.0
    TX.step(b, clk, 0.5, 2)
    v.said.clear()
    return b, src, v, clk


def rl(v):
    return [s for s, _, _ in v.said if s.startswith("rl_")]


def step(b, clk, secs=0.5, n=1):
    TX.step(b, clk, secs, n)


def new_lap(b, src, clk):
    src.v["LapCompleted"] = (src.v.get("LapCompleted") or 0) + 1
    step(b, clk, 0.5, 2)


@pytest.fixture(autouse=True)
def _no_tow():
    VO.TOWING = False
    yield
    VO.TOWING = False


# ------------------------------------------------------------------ lines
def test_lines_on_render_list_and_stand_in(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(os.path.join(ROOT, "tools"))
    sys.modules.pop("vocab_spec", None)
    spec = importlib.import_module("vocab_spec")
    rendered = [(sid, t) for sid, _, t in spec.L]
    for sid, text in lines_new.APPROVED_1101:
        assert (sid, text) in rendered, sid
    table = lines_new.table()
    for sid, _ in lines_new.APPROVED_1101:
        assert sid in table
    # exact wording, a few from each sheet
    assert table["rl_hazard_stopped"] == ["Car stopped, [corner]. Careful.", "Stopped car, [corner]. Watch it."]
    assert table["rl_drink"] == ["Drink.", "Take a drink.", "Water, when you can."]
    assert table["tl_target_down"] == ["Sector [sector], [n] tenths down.", "[n] tenths off in sector [sector]."]
    assert table["s_leader_pitting"][0] == "P1 is in the box. Plan A."
    # never: damage lines, battery coaching
    txt = " ".join(t for _, t in lines_new.APPROVED_1101).lower()
    assert "damage" not in txt and "battery" not in txt and "build mode" not in txt
    # every fill is one the voice can say
    import re
    for sid, t in lines_new.APPROVED_1101:
        for f in re.findall(r"\[([^\]]+)\]", t):
            assert f in ("P", "n", "laps", "minutes", "corner", "class", "sector"), (sid, f)
    # every short version belongs to a call that exists
    assert set(R1.SHORT.values()) == {s for s, _ in lines_new.SHORT_1101}


def test_stand_in_says_and_rotates(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"lines": [], "blocks": {}}))
    v = VO.Voice(str(tmp_path), output=False, log=lambda *a: None)
    assert v.build("rl_hazard_slow", {"corner": "dunlop"})[1] == "Slow car ahead at Dunlop."
    said = [v.build("rl_drink")[1] for _ in range(30)]
    assert all(a != b for a, b in zip(said, said[1:]))            # never the same version twice in a row
    assert set(said) == {"Drink.", "Take a drink.", "Water, when you can."}


def test_settings_defaults():
    s = ST.Settings()
    for k, on in R1.DEFAULTS.items():
        assert getattr(s, k) is on, k
    for k in ("calls_track_coach", "calls_target_pace", "calls_brake_cues"):
        assert getattr(s, k) is False                               # F lines stay off


# ------------------------------------------------------------------ #702 short versions
def test_short_versions_only_once_rendered():
    b, src, v, clk = mk()
    b.say("lost_place", {"P": 4})
    assert v.said[-1][0] == "lost_place"                           # not recorded yet: the old line
    v.lines = {"s_lost_place": [{}]}
    b.say("lost_place", {"P": 4}, cooldown=0, key="x1")
    assert v.said[-1][0] == "s_lost_place" and v.said[-1][1] == {"P": 4}
    b.s.calls_short_lines = False
    b.say("lost_place", {"P": 4}, key="x2")
    assert v.said[-1][0] == "lost_place"


# ------------------------------------------------------------------ A5 hazard
def _stopped_car_ahead(src, me_pct=0.5):
    src.v["LapDistPct"] = me_pct
    pct = list(src.v["CarIdxLapDistPct"])
    pct[0] = me_pct
    pct[2] = me_pct + 200 / TX.L                                   # car 2 parked 200 m ahead
    src.v["CarIdxLapDistPct"] = pct


def test_hazard_stopped_car():
    b, src, v, clk = mk(hazard=True)
    _stopped_car_ahead(src)
    step(b, clk, 0.3, 30)
    said = [(s, f) for s, f, p in v.said if s.startswith("rl_hazard")]
    assert said and said[0][0] in ("rl_hazard_stopped", "rl_hazard_slow") and said[0][1] == {"corner": "dunlop"}
    assert [p for s, _, p in v.said if s.startswith("rl_hazard")][0] == VO.PRIO_URGENT
    n = len(said)
    step(b, clk, 0.3, 20)                                           # same car: not again within 25 s
    assert len([s for s in rl(v) if s.startswith("rl_hazard")]) == n


def test_hazard_quiet_in_pits_tow_caution():
    for case in ("pits", "tow", "caution"):
        b, src, v, clk = mk(hazard=True)
        if case == "pits":
            src.v["OnPitRoad"] = True
        elif case == "tow":
            src.v["PlayerCarTowTime"] = 20.0
        else:
            src.v["SessionFlags"] = F_CAUTION
            b.caution_on = True
        _stopped_car_ahead(src)
        step(b, clk, 0.3, 30)
        assert not [s for s in rl(v) if s.startswith("rl_hazard")], case


def test_hazard_at_the_start_and_off_switch():
    b, src, v, clk = mk(hazard=True)
    b.green_t = clk.t                                               # just after the green: a stopped car is still called
    _stopped_car_ahead(src)
    step(b, clk, 0.3, 30)
    assert {"rl_hazard_stopped", "rl_hazard_slow"} & set(rl(v))
    b, src, v, clk = mk(calls_hazard=False)
    _stopped_car_ahead(src)
    step(b, clk, 0.3, 30)
    assert not [s for s in rl(v) if s.startswith("rl_hazard")]
    assert {"stopped_ahead", "slow_ahead"} & set(v.sids())          # switch off: the old line as before


# ------------------------------------------------------------------ B1 / B2 grid and formation
def _pre_race(b, src, clk):
    b.green_seen = False
    src.v.update(SessionState=0, SessionFlags=0, Speed=0.0)
    step(b, clk)


def test_grid_and_formation():
    b, src, v, clk = mk()
    _pre_race(b, src, clk)
    src.v["SessionState"] = 1
    step(b, clk, 1.0, 30)
    g = [(s, f) for s, f, _ in v.said if s == "rl_grid_clean"]
    assert len(g) == 1 and g[0][1]["_variant"] in (1, 2, 3)
    step(b, clk, 1.0, 60)
    assert rl(v).count("rl_grid_clean") == 1
    src.v["SessionState"] = 3
    src.v["Speed"] = 25.0
    step(b, clk, 1.0, 50)
    assert rl(v).count("rl_form_warm") == 1
    step(b, clk, 1.0, 60)
    assert rl(v).count("rl_form_warm") == 1


def test_grid_two_hours_forty_only_when_true():
    for _ in range(10):
        b, src, v, clk = mk(race_len="2700.0000 sec")
        _pre_race(b, src, clk)
        src.v["SessionState"] = 1
        step(b, clk, 1.0, 30)
        f = [f for s, f, _ in v.said if s == "rl_grid_clean"][0]
        assert f["_variant"] in (2, 3)


def test_grid_quiet_in_pits_tow_practice_and_late_join():
    for case in ("pits", "tow", "practice", "late"):
        b, src, v, clk = mk(session="Practice" if case == "practice" else "Race")
        _pre_race(b, src, clk)
        if case == "pits":
            src.v["OnPitRoad"] = True
        if case == "tow":
            src.v["PlayerCarTowTime"] = 20.0
        if case == "late":                                      # app started with the grid already open
            b.r1101.state_prev = None
            b.r1101.sess = b.sess_num
            src.v["SessionState"] = 1
            b.r1101.state_prev = 1
        src.v["SessionState"] = 1
        step(b, clk, 1.0, 40)
        src.v["SessionState"] = 3
        step(b, clk, 1.0, 50)
        if case == "late":
            assert "rl_grid_clean" not in rl(v)
        else:
            assert not {"rl_grid_clean", "rl_form_warm"} & set(rl(v)), case


# ------------------------------------------------------------------ A6 / D5 night
def test_night_calls():
    b, src, v, clk = mk(calls_drink=False)
    src.v.update(SolarAltitude=0.10, TrackTempCrew=30.0)
    step(b, clk)
    src.v["SolarAltitude"] = -0.01
    step(b, clk)
    assert rl(v) == ["rl_lights_on"]
    step(b, clk, 1.0, 60)
    src.v["SolarAltitude"] = -0.12
    new_lap(b, src, clk)
    assert rl(v) == ["rl_lights_on", "rl_night_brake"]
    src.v["TrackTempCrew"] = 27.0                                   # only 3 degrees: not yet
    step(b, clk, 1.0, 60); new_lap(b, src, clk)
    assert "rl_track_cooling" not in rl(v)
    src.v["TrackTempCrew"] = 25.5
    step(b, clk, 1.0, 60); new_lap(b, src, clk)
    assert rl(v) == ["rl_lights_on", "rl_night_brake", "rl_track_cooling"]
    for _ in range(4):
        step(b, clk, 1.0, 60); new_lap(b, src, clk)
    assert len(rl(v)) == 3                                          # each once a race


def test_night_waits_for_pits_tow_and_lap1_and_never_for_a_night_start():
    b, src, v, clk = mk(calls_drink=False)
    src.v.update(SolarAltitude=0.10, OnPitRoad=True)
    step(b, clk)
    src.v["SolarAltitude"] = -0.01
    step(b, clk, 1.0, 10)
    assert not rl(v)                                                # in the pit lane: waits
    src.v["PlayerCarTowTime"] = 10.0
    src.v["OnPitRoad"] = False
    step(b, clk, 1.0, 5)
    assert not rl(v)                                                # on the tow: waits
    src.v["PlayerCarTowTime"] = 0.0
    step(b, clk, 1.0, 2)
    assert rl(v) == ["rl_lights_on"]
    # lap 1 at night-fall: quiet
    b, src, v, clk = mk(calls_drink=False)
    b.green_t = clk.t
    src.v.update(SolarAltitude=0.10, LapCompleted=0, LapDistPct=0.1)
    step(b, clk)
    src.v["SolarAltitude"] = -0.01
    step(b, clk, 0.5, 4)
    assert not rl(v)
    # a race that starts in the dark: never "it's getting dark"
    b, src, v, clk = mk(calls_drink=False)
    src.v["SolarAltitude"] = -0.3
    for _ in range(5):
        step(b, clk, 1.0, 60); new_lap(b, src, clk)
    assert not rl(v)


# ------------------------------------------------------------------ E1 drink
def test_drink_every_15_min_on_the_line_and_at_stops():
    b, src, v, clk = mk()
    b.green_t = clk.t - 100
    new_lap(b, src, clk)
    assert "rl_drink" not in rl(v)                                  # not in the first 15 minutes
    clk.t += 15 * 60
    new_lap(b, src, clk)
    assert rl(v).count("rl_drink") == 1
    new_lap(b, src, clk)
    assert rl(v).count("rl_drink") == 1                             # not again for 15 min
    # a pit stop: once, in the box
    clk.t += 400
    src.v.update(OnPitRoad=True, PlayerCarInPitStall=True, Speed=0.0)
    step(b, clk, 1.0, 6)
    assert rl(v).count("rl_drink") == 2
    step(b, clk, 1.0, 20)
    assert rl(v).count("rl_drink") == 2


def test_drink_quiet_on_tow_and_in_practice_and_caution_ok():
    b, src, v, clk = mk()
    src.v["PlayerCarTowTime"] = 30.0
    clk.t += 16 * 60
    new_lap(b, src, clk)
    src.v.update(OnPitRoad=True, PlayerCarInPitStall=True, Speed=0.0)
    step(b, clk, 1.0, 6)
    assert "rl_drink" not in rl(v)
    b, src, v, clk = mk(session="Practice")
    clk.t += 16 * 60
    new_lap(b, src, clk)
    assert "rl_drink" not in rl(v)
    b, src, v, clk = mk()                                           # behind the safety car: a good time to drink
    src.v["SessionFlags"] = F_CAUTION
    b.caution_on = True
    clk.t += 16 * 60
    new_lap(b, src, clk)
    assert "rl_drink" in rl(v)


# ------------------------------------------------------------------ E2 last 30 minutes
def _timed(src, left):
    src.v.update(SessionLapsRemainEx=32767, SessionTimeRemain=left)


def test_last_30():
    b, src, v, clk = mk()
    _timed(src, 1820.0); step(b, clk)
    _timed(src, 1795.0); step(b, clk, 1.0, 10)
    assert "rl_last_30" not in rl(v)                                # waits ~20 s after the minutes call
    step(b, clk, 1.0, 15)
    f = [f for s, f, _ in v.said if s == "rl_last_30"]
    assert len(f) == 1 and f[0]["_variant"] in (1, 2)
    step(b, clk, 1.0, 100)
    assert rl(v).count("rl_last_30") == 1


def test_last_30_variants_and_quiet_cases():
    b, src, v, clk = mk()
    b.prev["fuel_state"] = "short"
    _timed(src, 1795.0); step(b, clk, 1.0, 30)
    assert [f["_variant"] for s, f, _ in v.said if s == "rl_last_30"] == [2]      # a stop to come: not "last stint"
    b, src, v, clk = mk()
    b.prev["fuel_state"] = "ok"
    _timed(src, 1795.0); step(b, clk, 1.0, 30)
    assert [f["_variant"] for s, f, _ in v.said if s == "rl_last_30"] == [1]
    b, src, v, clk = mk(race_len="2700.0000 sec")                  # a 45-minute race: no
    _timed(src, 1795.0); step(b, clk, 1.0, 30)
    assert "rl_last_30" not in rl(v)
    b, src, v, clk = mk()                                           # in the pit lane: waits until out (max 5 min)
    src.v["OnPitRoad"] = True
    _timed(src, 1795.0); step(b, clk, 1.0, 40)
    assert "rl_last_30" not in rl(v)
    src.v["OnPitRoad"] = False
    step(b, clk, 1.0, 3)
    assert "rl_last_30" in rl(v)
    b, src, v, clk = mk()                                           # tow
    src.v["PlayerCarTowTime"] = 40.0
    _timed(src, 1795.0); step(b, clk, 1.0, 30)
    assert "rl_last_30" not in rl(v)
    b, src, v, clk = mk()                                           # joined with 20 minutes left: nothing
    _timed(src, 1200.0); step(b, clk, 1.0, 40)
    assert "rl_last_30" not in rl(v)


# ------------------------------------------------------------------ E4 after the race
def test_rest_after_long_race_only():
    b, src, v, clk = mk()
    b.finished = True
    step(b, clk, 1.0, 50)
    assert "rl_rest_after" not in rl(v)
    step(b, clk, 1.0, 15)
    assert rl(v).count("rl_rest_after") == 1
    step(b, clk, 1.0, 120)
    assert rl(v).count("rl_rest_after") == 1
    b, src, v, clk = mk(race_len="1200.0000 sec")
    b.green_t = clk.t - 1300
    b.finished = True
    step(b, clk, 1.0, 90)
    assert "rl_rest_after" not in rl(v)


# ------------------------------------------------------------------ the OFF ones stay off by default
def test_off_by_default():
    b, src, v, clk = mk()
    s = ST.Settings()
    for k in ("calls_dunlop", "calls_class_traffic", "calls_let_go", "calls_caution_plan", "calls_rain_plan", "calls_readback"):
        setattr(b.s, k, getattr(s, k))
    b.say("bf_box", prio=VO.PRIO_URGENT)
    pct = list(src.v["CarIdxLapDistPct"]); pct[0] = 0.5; pct[4] = 0.5 - 15 / TX.L      # a GTP 15 m behind
    pct[2] = 0.6
    src.v["CarIdxLapDistPct"] = pct
    for _ in range(6):
        step(b, clk, 1.0, 30); new_lap(b, src, clk)
    for sid in ("rl_confirm_box", "rl_let_him_go", "rl_traffic_into", "rl_yellow_box", "rl_yellow_stay",
                "rl_wets_now", "rl_dunlop"):
        assert sid not in rl(v), sid


# ------------------------------------------------------------------ D6 read-back (off by default; checked with it on)
def test_readback():
    b, src, v, clk = mk(calls_readback=True)
    b.say("bf_box", prio=VO.PRIO_URGENT)
    step(b, clk, 1.0, 5)
    assert "rl_confirm_box" not in rl(v)
    step(b, clk, 1.0, 5)
    assert rl(v) == ["rl_confirm_box"]
    step(b, clk, 1.0, 40)
    assert rl(v) == ["rl_confirm_box"]                               # asked once, never nags
    # copy in time: no reminder, "Copy." / "Thanks."
    b, src, v, clk = mk(calls_readback=True)
    b.say("bf_box", prio=VO.PRIO_URGENT)
    step(b, clk, 1.0, 3)
    assert b.answer("copy") is True
    step(b, clk, 1.0, 15)
    assert rl(v) == ["rl_copy"]
    # he dives into the pit lane: he heard it
    b, src, v, clk = mk(calls_readback=True)
    b.say("bf_box", prio=VO.PRIO_URGENT)
    src.v["OnPitRoad"] = True
    step(b, clk, 1.0, 15)
    assert not rl(v)
    # a copy press with nothing to answer: nothing said, never "didn't catch"
    b, src, v, clk = mk(calls_readback=True)
    assert b.answer("copy") is True and not v.said


def test_copy_is_a_wheel_binding_and_ipad_route():
    from engineer import app
    assert app.BIND_ACTIONS["copy"] == ("intent", "copy")
    src = open(os.path.join(ROOT, "engineer", "remote.py"), encoding="utf-8").read()
    assert '"/api/copy"' in src
    html = open(os.path.join(ROOT, "engineer", "ui", "ipad", "index.html"), encoding="utf-8-sig").read()
    assert 'id="copyBtn"' in html


# ------------------------------------------------------------------ the rule-of-three gap between chat calls
def test_chat_calls_are_spaced():
    b, src, v, clk = mk()
    b.prev["fuel_state"] = "ok"
    src.v.update(SolarAltitude=0.10)
    step(b, clk)
    clk.t += 16 * 60
    _timed(src, 1795.0)
    src.v["SolarAltitude"] = -0.01
    step(b, clk)
    new_lap(b, src, clk)
    step(b, clk, 1.0, 25)
    said = rl(v)
    assert said and len(said) == 1                                  # lights first; the drink / last-30 wait their turn
    step(b, clk, 1.0, 50)
    assert len(rl(v)) == 2


# ------------------------------------------------------------------ the OFF ones, switched on (so they're ready to test)
def test_class_traffic_when_on():
    b, src, v, clk = mk(calls_class_traffic=True, calls_drink=False)
    src.v["PlayerCarIdx"] = 4                                       # me in the GTP (faster class)
    pct = list(src.v["CarIdxLapDistPct"])
    pct[4] = 0.40; pct[0] = 0.50; pct[2] = 0.46; pct[1] = 0.62; pct[3] = 0.2; pct[5] = 0.9
    src.v["CarIdxLapDistPct"] = pct
    src.v["LapDistPct"] = 0.40
    step(b, clk, 0.5, 4)
    f = [f for s, f, _ in v.said if s == "rl_traffic_into"]
    assert f == [{"n": 2, "corner": "dunlop", "_variant": 3}]
    step(b, clk, 0.5, 60)
    assert rl(v).count("rl_traffic_into") == 1                       # same cars: once
    src.v["OnPitRoad"] = True
    b.r1101.trf_seen.clear()
    step(b, clk, 0.5, 6)
    assert rl(v).count("rl_traffic_into") == 1                       # never from the pit lane


def test_let_go_when_on():
    b, src, v, clk = mk(calls_let_go=True, calls_drink=False)
    pct = list(src.v["CarIdxLapDistPct"])
    pct[0] = 0.5; pct[4] = 0.5 - 10 / TX.L; pct[5] = 0.1               # the GTP 10 m behind me
    src.v["CarIdxLapDistPct"] = pct
    step(b, clk, 1.0, 6)
    assert "rl_let_him_go" not in rl(v)
    step(b, clk, 1.0, 4)
    assert rl(v).count("rl_let_him_go") == 1
    step(b, clk, 1.0, 60)
    assert rl(v).count("rl_let_him_go") == 1


def test_caution_plan_when_on():
    b, src, v, clk = mk(calls_caution_plan=True, calls_drink=False)
    for _ in range(3):
        step(b, clk, 1.0, 50); new_lap(b, src, clk)
    assert rl(v) == ["rl_yellow_stay"]                               # 16 laps of fuel, 15 to go
    for _ in range(3):
        step(b, clk, 1.0, 50); new_lap(b, src, clk)
    assert rl(v) == ["rl_yellow_stay"]                               # once a stint
    b, src, v, clk = mk(calls_caution_plan=True, calls_drink=False)
    src.v["FuelLevel"] = 20.0
    for _ in range(3):
        step(b, clk, 1.0, 50); new_lap(b, src, clk)
    assert rl(v) == ["rl_yellow_box"]


def test_rain_when_on():
    b, src, v, clk = mk(calls_rain_plan=True, calls_drink=False)
    src.v.update(PlayerTireCompound=0, TrackWetness=5, WeatherDeclaredWet=True)
    step(b, clk, 1.0, 30)
    assert "rl_wets_now" not in rl(v)
    step(b, clk, 1.0, 35)
    assert rl(v) == ["rl_wets_now"]
    step(b, clk, 1.0, 120)
    assert rl(v) == ["rl_wets_now"]


def test_dunlop_when_on():
    b, src, v, clk = mk(calls_dunlop=True, calls_drink=False)
    src.inf["WeekendInfo"]["TrackName"] = "lemans full"
    b.green_seen = False
    src.v.update(SessionState=3, SessionFlags=0)
    step(b, clk)
    src.v.update(SessionState=4, SessionFlags=F_GREEN)
    step(b, clk, 0.5, 4)
    assert rl(v) == ["rl_dunlop"]
    assert [p for s, _, p in v.said if s == "rl_dunlop"] == [VO.PRIO_URGENT]


def test_everything_on_never_errors():
    logs = []
    b, src, v, clk = mk(**{k: True for k in R1.DEFAULTS})
    b.log = logs.append
    src.v.update(SolarAltitude=0.1, PlayerTireCompound=0, TrackWetness=5, WeatherDeclaredWet=True)
    for k in range(40):
        src.v["SolarAltitude"] = 0.1 - k * 0.01
        _timed(src, 1900 - k * 10)
        src.v["OnPitRoad"] = k % 9 == 0
        step(b, clk, 1.0, 10); new_lap(b, src, clk)
    b.finished = True
    step(b, clk, 1.0, 70)
    assert not [l for l in logs if "1101" in str(l)], logs
    assert "rl_rest_after" in rl(v)
