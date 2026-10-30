"""Rain brain (#591, 2026-10-30): trend, crossover maths, answers, proactive calls, quiet rules, no unapproved voice.

All telemetry here is synthetic: session time in seconds, TrackWetness 1..7, Precipitation 0..1.
"""
import os
import queue
import shutil
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engineer import rain as R  # noqa: E402
from engineer import rain_brain as RB  # noqa: E402
from engineer.rain_brain import (CompoundLaps, RainBrain, RainTrend, answer_more, answer_switch, answer_trend,  # noqa: E402
                                 crossover, forecast_from_info, table_delta)


# ------------------------------------------------------------------ synthetic weather
def feed(trend, minutes, wet_at, rain_at=lambda t: 0.0, t0=0.0, step=5.0):
    """wet_at(t) / rain_at(t) -> values, t in seconds from t0."""
    n = int(minutes * 60 / step)
    for k in range(n + 1):
        t = t0 + k * step
        trend.add(t, wet_at(t - t0), rain_at(t - t0))
    return trend


def drying(minutes=10, start=5, every_s=200):
    return feed(RainTrend(), minutes, lambda t: max(1, start - int(t // every_s)))


def wetting(minutes=10, start=2, every_s=200, rain=0.35):
    return feed(RainTrend(), minutes, lambda t: min(7, start + int(t // every_s)), lambda t: rain + t / 6000)


# ------------------------------------------------------------------ 1. trend
def test_drying_sequence():
    st = drying().state()
    assert st["dir"] == "drying" and st["conf"] == "high"
    assert st["rate"] < -0.1 and st["level"] == 2 and not st["raining"]


def test_wetting_sequence():
    st = wetting().state()
    assert st["dir"] == "wetter" and st["conf"] in ("medium", "high")
    assert st["rate"] > 0.1 and st["raining"]


def test_steady_sequence():
    st = feed(RainTrend(), 10, lambda t: 4, lambda t: 0.15).state()
    assert st["dir"] == "steady" and st["conf"] == "high" and st["rate"] == 0


def test_too_early_to_say():
    st = feed(RainTrend(), 1, lambda t: 4).state()
    assert st["dir"] == "unknown" and st["conf"] == "low"
    assert RainTrend().state()["conf"] == "none"


def test_flicking_between_levels_is_not_a_trend():
    st = feed(RainTrend(), 10, lambda t: 4 + int(t // 60) % 2, lambda t: 0.1).state()
    assert st["dir"] == "steady" and st["conf"] == "low"


def test_rain_building_before_the_track_catches_up():
    st = feed(RainTrend(), 6, lambda t: 3, lambda t: 0.1 + t / 1800).state()
    assert st["dir"] == "wetter" and st["precip_dir"] == "heavier" and st["conf"] == "medium"


def test_one_change_only_is_low_confidence():
    st = feed(RainTrend(), 5, lambda t: 5 if t < 150 else 4, lambda t: 0.2).state()
    assert st["dir"] == "drying" and st["conf"] == "low"     # still raining: one step down is not enough


def test_missing_and_unknown_values_are_ignored():
    tr = RainTrend()
    for t in range(0, 300, 5):
        tr.add(t, 0, None)          # 0 = iRacing's "unknown"
        tr.add(t + 1, None, None)
        tr.add("x", 3, 0)
    assert tr.state()["level"] is None and tr.state()["dir"] == "unknown"


def test_time_going_backwards_starts_over():
    tr = drying()
    tr.add(10.0, 6, 0.5)            # replay jump / new session
    st = tr.state()
    assert st["level"] == 6 and st["dir"] == "unknown"


def test_window_is_twenty_minutes():
    tr = feed(RainTrend(), 45, lambda t: 6 if t < 600 else 4)     # wetter long ago, steady for the last 35 minutes
    st = tr.state()
    assert st["dir"] == "steady" and st["span_min"] <= 20.01 and tr.rained is False


def test_slow_drying_stays_drying_between_level_changes():
    """One level every 15 minutes (a slow drying track) is still 'drying' in the quiet minutes between the changes."""
    tr = RainTrend()
    for k in range(0, 3600, 5):
        tr.add(k, max(2, 6 - k // 900), 0.0)
        if k >= 1500 and k % 60 == 0:
            assert tr.state()["dir"] == "drying", k


# ------------------------------------------------------------------ forecast in the session info
def test_forecast_fields_missing_or_present():
    assert forecast_from_info(None) == {"precip_pct": None, "weather_type": "", "static": False, "forecast": None}
    f = forecast_from_info({"TrackPrecipitation": "15 %", "TrackWeatherType": "Static"})
    assert f["precip_pct"] == 15 and f["static"] and f["forecast"] is None
    f = forecast_from_info({"TrackWeatherType": "Dynamic", "WeekendOptions": {"WeatherForecast": [{"t": 0, "rain": 40}]}})
    assert not f["static"] and f["forecast"] == [{"t": 0, "rain": 40}]


# ------------------------------------------------------------------ 2. lap times per compound
def _arrays(n=8):
    return {"lc": [0] * n, "last": [-1.0] * n, "comp": [0] * n, "pit": [False] * n}


def test_compound_laps_counts_clean_class_laps_only():
    cl = CompoundLaps()
    a = _arrays()
    a["comp"] = [1, 1, 1, 0, 0, 0, 1, 0]           # 1 = wet compound; car 6 / 7 are another class
    t = 0.0
    def lap(times, pit_cars=()):
        nonlocal t
        t += 100
        for i in range(8):
            a["pit"][i] = i in pit_cars
        cl.feed(t - 50, a["lc"], a["last"], a["comp"], a["pit"], 4, 0, [0, 1, 2, 3, 4, 5], 1)
        for i in range(8):
            a["lc"][i] += 1
            a["last"][i] = times[i]
        cl.feed(t, a["lc"], a["last"], a["comp"], a["pit"], 4, 0, [0, 1, 2, 3, 4, 5], 1)
        for i in range(8):
            a["pit"][i] = False
    lap([110] * 8)                                   # first crossing seen: counts
    lap([110, 110, 110, 108, 108, 108, 90, 90], pit_cars=(5,))
    n_before = len(cl.laps)
    lap([110, 110, 110, 108, 108, 130, 90, 90])     # car 5: first lap on the new set - not counted
    assert len(cl.laps) == n_before + 5
    assert all(x[1] not in (6, 7) for x in cl.laps)  # other class never counted
    assert not any(x[1] == 5 and x[3] == 130 for x in cl.laps)
    f = cl.field_now(t, 110)
    d, ns, nw, se = f
    assert ns == 3 and nw == 3 and d == pytest.approx(-2.0, abs=0.01)   # slicks 2 s faster
    assert any(x[5] for x in cl.laps) and all(x[1] == 0 for x in cl.laps if x[5])


def test_field_needs_two_cars_on_each_tyre():
    cl = CompoundLaps()
    cl.laps = [(100, 0, True, 110, 4, True), (100, 1, True, 111, 4, False), (100, 2, False, 108, 4, False)]
    assert cl.field_now(150) is None


def test_driver_speed_is_taken_out():
    """A fast driver on wets and a slow one on slicks: normalising by each car's best lap compares like with like."""
    cl = CompoundLaps()
    cl.laps = [(100, i, w, lt, 4, False) for i, w, lt in
               [(0, True, 100.0), (1, True, 101.0), (2, False, 104.0), (3, False, 105.0)]]
    best = {0: 90.0, 1: 91.0, 2: 94.0, 3: 95.0}       # cars 2 / 3 are 4 s a lap slower drivers
    raw = cl.field_now(150)[0]
    norm = cl.field_now(150, best=best)[0]
    assert raw == pytest.approx(4.0) and abs(norm) < 0.5


# ------------------------------------------------------------------ 3. crossover maths
BASE, LAP = 100.0, 110.0


def test_table_crossover_level():
    """Penalty table: slicks lose 4 %, wets 5 % at 'very lightly wet' (3); 11 % vs 6.5 % at 4 -> crossover just above 3."""
    assert table_delta(3, BASE) == pytest.approx(-1.0)
    assert table_delta(4, BASE) == pytest.approx(4.5)
    lx = RB._zero(lambda l: table_delta(l, BASE))
    assert lx == pytest.approx(3 + 1.0 / 5.5, abs=0.02)


def test_table_only_is_low_confidence_and_says_so():
    st = feed(RainTrend(), 10, lambda t: 5 if t < 300 else 4).state()       # 5 -> 4, still drying
    st = dict(st, conf="high", rate=-0.1, level=5, level_fit=5.0, dir="drying")
    x = crossover(st, True, base=BASE, lap_s=LAP, laps_left=40)
    lx = 3 + 1.0 / 5.5
    assert x["source"] == "table" and x["conf"] == "low"
    assert x["level_x"] == pytest.approx(lx, abs=0.02)
    assert x["call"] == "laps" and x["laps"] == round((5 - lx) / 0.1 * 60 / LAP)
    a = answer_switch(x, st, True)
    assert a["sid"] == "rb_slicks_in_rough" and "Low confidence" in a["text"] and "table" in a["text"]
    assert a["fills"] == {"laps": x["laps"]}
    assert "seconds" not in a["text"]                 # no seconds from the table: they'd be a guess


def test_field_data_says_now():
    st = dict(drying().state())
    x = crossover(st, True, base=BASE, lap_s=LAP, field=(-1.5, 4, 5, 0.2), laps_left=30, stop_cost=40)
    assert x["call"] == "now" and x["source"] == "field" and x["conf"] == "high" and x["gain"] == pytest.approx(1.5)
    assert x["worth"] is True                          # 1.5 s a lap (and growing) x 30 laps > 40 s
    a = answer_switch(x, st, True)
    assert a["sid"] == "rb_slicks_now_box" and "1.5 seconds a lap" in a["text"]


def test_now_with_a_stop_coming_takes_them_there():
    st = dict(drying().state())
    x = crossover(st, True, base=BASE, lap_s=LAP, field=(-1.5, 4, 5, 0.2), laps_left=30, stint_laps=1, stop_cost=40,
                  stop_soon=True)
    assert x["worth"] and answer_switch(x, st, True)["sid"] == "rb_slicks_now_stop"


def test_far_past_the_table_crossover_is_medium_confidence():
    st = {"dir": "wetter", "conf": "high", "rate": 0.1, "level": 6, "level_fit": 6.0, "raining": True}
    x = crossover(st, False, base=BASE, lap_s=LAP, laps_left=20, stop_cost=40)
    assert x["source"] == "table" and x["call"] == "now" and x["conf"] == "medium"
    a = answer_switch(x, st, False)
    assert a["sid"] == "box_wets" and "general wet-weather table" in a["text"] and "seconds" not in a["text"]


def test_now_but_not_worth_a_stop():
    st = dict(drying().state(), rate=0.0, dir="steady")
    x = crossover(st, True, base=BASE, lap_s=LAP, field=(-0.5, 4, 4, 0.1), laps_left=5, stop_cost=40)
    assert x["call"] == "now" and x["worth"] is False
    assert answer_switch(x, st, True)["sid"] == "rb_slicks_now_wait"


def test_field_offset_moves_the_crossover():
    """Measured: wets still 3 s faster at 4.0 (the table says 4.5) -> the crossover moves accordingly."""
    st = {"dir": "drying", "conf": "high", "rate": -0.1, "level": 4, "level_fit": 4.0, "raining": False}
    x = crossover(st, True, base=BASE, lap_s=LAP, field=(3.0, 4, 4, 0.2), laps_left=40)
    off = 3.0 - 4.5
    lx = RB._zero(lambda l: table_delta(l, BASE) + off)
    assert x["level_x"] == pytest.approx(lx, abs=1e-6) and x["source"] == "field"
    assert x["laps"] == round((4.0 - lx) / 0.1 * 60 / LAP)
    assert x["conf"] == "high"


def test_two_levels_measured_fit_a_line():
    st = {"dir": "drying", "conf": "high", "rate": -0.1, "level": 4, "level_fit": 4.0, "raining": False}
    levels = {5: (8.0, 4, 4), 4: (4.0, 4, 4)}          # slope 4 s a level -> zero at 3.0
    x = crossover(st, True, base=BASE, lap_s=LAP, levels=levels, laps_left=40)
    assert x["source"] == "fit" and x["level_x"] == pytest.approx(3.0, abs=0.06)
    assert x["laps"] == round(1.0 / 0.1 * 60 / LAP)


def test_not_this_stint():
    st = {"dir": "drying", "conf": "high", "rate": -0.02, "level": 6, "level_fit": 6.0, "raining": False}
    x = crossover(st, True, base=BASE, lap_s=LAP, field=(15.0, 4, 4, 0.5), laps_left=60, stint_laps=10)
    assert x["call"] == "not_this_stint" and x["laps"] > 10
    assert answer_switch(x, st, True)["sid"] == "rb_slicks_not_stint"


def test_not_while_steady():
    st = feed(RainTrend(), 10, lambda t: 5, lambda t: 0.3).state()
    x = crossover(st, True, base=BASE, lap_s=LAP, laps_left=30)
    assert x["call"] == "not_yet" and x["laps"] is None
    assert answer_switch(x, st, True)["sid"] == "rb_slicks_not_yet"


def test_wets_coming_on_slicks():
    st = wetting().state()                             # 2 -> 4 and raining harder
    x = crossover(st, False, base=BASE, lap_s=LAP, laps_left=30, stop_cost=40)
    assert x["to"] == "wets"
    assert x["call"] in ("now", "next", "laps")


def test_wets_now_uses_the_recorded_box_call():
    st = {"dir": "wetter", "conf": "high", "rate": 0.2, "level": 5, "level_fit": 5.0, "raining": True}
    x = crossover(st, False, base=BASE, lap_s=LAP, field=(9.0, 4, 4, 0.3), laps_left=30, stop_cost=40)
    assert x["call"] == "now" and x["worth"]
    assert answer_switch(x, st, False)["sid"] == "box_wets"


def test_no_numbers_without_data():
    st = drying().state()
    x = crossover(st, True)                            # no dry pace, no lap time, no lap times on either tyre
    assert x["call"] == "unknown" and x["conf"] == "none" and x["laps"] is None and x["gain"] is None
    a = answer_switch(x, st, True)
    assert a["sid"] == "rb_unsure" and a["fallback"] == "tb_no_data" and not any(c.isdigit() for c in a["text"].split("(")[0])


def test_low_confidence_now_uses_the_existing_crossover_line():
    st = dict(drying().state())
    x = crossover(st, True, base=BASE, lap_s=LAP)       # table only: slicks faster at 2.7
    assert x["call"] == "now" and x["conf"] == "low"
    a = answer_switch(x, st, True)
    assert a["sid"] == "ty_opt" and a["fills"] == {"_variant": 3} and "Low confidence" in a["text"]


def test_dry_track_on_slicks():
    st = feed(RainTrend(), 5, lambda t: 1).state()
    a = answer_switch(crossover(st, False, base=BASE), st, False)
    assert a["sid"] == "ty_opt" and a["fills"] == {"_variant": 1}


def test_rain_py_crossover_takes_a_measured_gain():
    change, g, _ = R.crossover(BASE, 4, 20, 40, on_wets=True)
    assert not change and g < 0                         # table: slicks 4.5 s slower at 4
    change, g, _ = R.crossover(BASE, 4, 20, 40, on_wets=True, gain=3.0)
    assert change and g == 3.0


# ------------------------------------------------------------------ 4. answers
def test_will_it_rain_any_more():
    raining_heavier = feed(RainTrend(), 6, lambda t: 4, lambda t: 0.2 + t / 3600).state()
    a = answer_more(raining_heavier)
    assert a["sid"] == "rb_more_heavier" and a["fallback"] == "rain_worse"
    easing = feed(RainTrend(), 6, lambda t: 4, lambda t: 0.4 - t / 3600).state()
    assert answer_more(easing)["sid"] == "rb_more_easing"
    steady = feed(RainTrend(), 6, lambda t: 4, lambda t: 0.3).state()
    assert answer_more(steady)["sid"] == "rb_more_steady"
    stopped = feed(RainTrend(), 6, lambda t: 4, lambda t: 0.3 if t < 60 else 0.0).state()
    assert answer_more(stopped)["sid"] == "rb_more_stopped"
    dry = feed(RainTrend(), 6, lambda t: 1).state()
    a = answer_more(dry, forecast_pct=32)
    assert a["sid"] == "rb_more_none_fc" and a["fills"] == {"percent": 30}
    assert answer_more(dry)["sid"] == "rb_more_none"
    assert answer_more(dry, static=True)["sid"] == "rb_more_static"
    assert answer_more(RainTrend().state())["fallback"] == "tb_no_data"


def test_is_it_drying():
    assert answer_trend(drying().state())["sid"] == "rb_trend_drying"
    a = answer_trend(wetting().state())
    assert a["sid"] == "rb_trend_wetter" and a["fallback"] == "rain_worse"
    assert answer_trend(feed(RainTrend(), 10, lambda t: 4).state())["sid"] == "rb_trend_steady"
    assert answer_trend(feed(RainTrend(), 1, lambda t: 4).state())["sid"] == "rb_trend_unsure"
    assert "high confidence" in answer_trend(drying().state())["text"]


# ------------------------------------------------------------------ 5. proactive calls + quiet rules
class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def brain_for(trend, quiet=False, have=()):
    clips, shown = [], []
    ck = Clock()
    rb = RainBrain(say_clip=lambda sid, fills=None, answer=False: (clips.append((sid, fills)) or True) if sid in have else False,
                   show=lambda role, text: shown.append((role, text)), quiet=lambda: quiet, log=lambda *a: None, clock=ck)
    rb.trend = trend
    return rb, clips, shown, ck


def test_heads_up_once_when_slicks_are_close():
    tr = feed(RainTrend(), 10, lambda t: 4 if t < 300 else 3, lambda t: 0.0)
    rb, clips, shown, ck = brain_for(tr)
    st = tr.state()
    ctx = {"on_wets": True, "base": BASE, "lap_s": LAP, "laps_left": 30, "t": 600}
    # make the field say wets are still 1 s faster -> crossover a lap or two away
    rb.laps.field_now = lambda *a, **k: (1.0, 4, 4, 0.2)
    made = rb.lap(ctx)
    assert made and made["sid"] in ("rb_call_slicks_soon", "rb_slicks_next") and st["dir"] == "drying"
    assert shown and shown[0][0] == "ENGINEER" and "get ready" in shown[0][1].lower()      # no clip yet: text
    ck.t += 200
    assert rb.lap(ctx) is None                          # same call is not repeated


def test_new_clip_plays_once_rendered():
    tr = feed(RainTrend(), 10, lambda t: 4 if t < 300 else 3)
    rb, clips, shown, ck = brain_for(tr, have={"rb_call_slicks_soon", "rb_slicks_next"})
    rb.laps.field_now = lambda *a, **k: (1.0, 4, 4, 0.2)
    rb.lap({"on_wets": True, "base": BASE, "lap_s": LAP, "laps_left": 30, "t": 600})
    assert clips and clips[0][0] in ("rb_call_slicks_soon", "rb_slicks_next") and not shown


def test_quiet_while_towed_or_after_the_flag():
    tr = feed(RainTrend(), 10, lambda t: 4 if t < 300 else 3)
    rb, clips, shown, ck = brain_for(tr, quiet=True)
    rb.laps.field_now = lambda *a, **k: (1.0, 4, 4, 0.2)
    assert rb.lap({"on_wets": True, "base": BASE, "lap_s": LAP, "laps_left": 30, "t": 600}) is None
    assert not clips and not shown


def test_crossover_call_and_throttle():
    tr = drying()
    rb, clips, shown, ck = brain_for(tr)
    rb.laps.field_now = lambda *a, **k: (-1.2, 4, 4, 0.2)
    ctx = {"on_wets": True, "base": BASE, "lap_s": LAP, "laps_left": 30, "t": 600, "stop_cost": 40}
    made = rb.lap(ctx)
    assert made["sid"] == "rb_call_slicks_now" and "1.2 seconds a lap" in made["text"]
    rb.called.clear()
    ck.t += 30
    assert rb.lap(ctx) is None                          # less than 90 s since the last call
    rb2, _, _, _ = brain_for(drying())
    rb2.laps.field_now = rb.laps.field_now
    assert rb2.lap(ctx, box_called=True) is None        # the strategist's own "box this lap for slicks" went out


def test_table_only_never_makes_the_crossover_call():
    rb, clips, shown, ck = brain_for(drying())
    assert rb.lap({"on_wets": True, "base": BASE, "lap_s": LAP, "laps_left": 30, "t": 600}) is None


def test_rain_getting_heavier_call_when_trend_flips():
    tr = feed(RainTrend(), 10, lambda t: 1, lambda t: 0.05)             # light rain, dry track, steady
    rb, clips, shown, ck = brain_for(tr, have={"rain_worse"})
    ctx = {"on_wets": False, "base": BASE, "lap_s": LAP, "laps_left": 30, "t": 600}
    assert rb.lap(ctx) is None and rb.prev_dir == "steady"
    feed(tr, 5, lambda t: 1, lambda t: 0.05 + t / 1500, t0=605)          # the rain builds, the track not wet yet
    ck.t += 400
    assert rb.lap(ctx) is None and rb.heavier_at is not None            # waits for water on the track
    feed(tr, 4, lambda t: 2, lambda t: 0.25 + t / 1500, t0=910)          # now it's mostly dry -> getting wet
    ck.t += 400
    made = rb.lap(ctx)
    assert made and made["sid"] == "rb_call_heavier"
    assert clips == [("rain_worse", {})] and "Think about wets" in shown[0][1]    # existing clip + the text
    ck.t += 100
    again = rb.lap(ctx)
    assert again is None or again["sid"] != "rb_call_heavier"


def test_heavier_call_not_on_wets_and_not_when_quiet():
    tr = feed(RainTrend(), 10, lambda t: 1, lambda t: 0.05)
    rb, clips, shown, ck = brain_for(tr)
    rb.lap({"on_wets": True, "base": BASE, "lap_s": LAP, "t": 600})
    feed(tr, 6, lambda t: 2, lambda t: 0.1 + t / 1000, t0=605)
    ck.t += 400
    assert rb.lap({"on_wets": True, "base": BASE, "lap_s": LAP, "t": 960}) is None


# ------------------------------------------------------------------ 6. strategist wiring + quiet rules (ic155 / ic156)
class FakeSrc(dict):
    def info(self, sec):
        return self.get("_info", {}).get(sec)


def strategist(**tel):
    from engineer.strat_live import Strategist
    said = []
    st = Strategist(lambda r, t: said.append((r, t)), log=lambda *a: None)
    src = FakeSrc({"SessionTime": 0.0, "TrackWetness": 4, "Precipitation": 0.0, "IsOnTrack": True,
                   "IsReplayPlaying": False, "PlayerTireCompound": 1, "LapCompleted": 3,
                   "_info": {"DriverInfo": {"DriverTires": [{"TireIndex": 0, "TireCompoundType": "Hard"},
                                                            {"TireIndex": 1, "TireCompoundType": "Wet"}]}}})
    src.update(tel)
    b = types.SimpleNamespace(src=src, finished=False, info=lambda sec, d=None: src.info(sec) or d,
                              laps_to_go=lambda: 20, me=lambda: 0, my_class=lambda: (1, "GT3"),
                              class_cars=lambda c: [0, 1, 2], is_race=lambda: True, said=[],
                              g=lambda k, d=None: src.get(k, d))
    b.say = lambda sid, fills=None, prio=None: b.said.append(sid) or sid in ("box_wets", "rain_worse", "ty_opt", "tb_no_data")
    st.b = b
    st.m = {"base": BASE, "lane_loss": 30.0, "tyre_time": 10.0}
    return st, b, said


def test_strategist_quiet_rules():
    from engineer import voice
    st, b, _ = strategist()
    assert not st._rb_quiet()
    voice.TOWING = True
    try:
        assert st._rb_quiet()                           # ic155: towed back to the pits
    finally:
        voice.TOWING = False
    b.finished = True
    assert st._rb_quiet()                               # ic156: after the flag
    b.finished = False
    b.src["IsReplayPlaying"] = True
    assert st._rb_quiet()
    b.src["IsReplayPlaying"] = False
    b.src["IsOnTrack"] = False
    assert st._rb_quiet()


def test_strategist_rain_lap_quiet_after_flag():
    st, b, said = strategist()
    b.finished = True
    st.wet_lvl = 5
    st._rain_lap(4)
    assert not said and st.tyre_call is None


def test_strategist_feeds_and_answers():
    st, b, said = strategist()
    for k in range(121):
        b.src["SessionTime"] = k * 5.0
        b.src["TrackWetness"] = 5 if k < 40 else 4 if k < 80 else 3
        st._rb_tick()
    ctx = st.rain_ctx()
    assert ctx["on_wets"] and ctx["stop_cost"] == 40.0 and ctx["laps_left"] == 20
    a = st.rain_answer("trend")
    assert a["sid"] == "rb_trend_drying"
    a = st.rain_answer("switch", {"DRYCOMP"})
    assert a["sid"] in ("ty_opt", "rb_slicks_now_box", "rb_slicks_now_wait", "rb_slicks_next", "rb_slicks_in_rough")
    assert st.rb.deliver(a, answer=True) in ("clip", "text")


def test_change_tyres_on_a_dry_track_is_a_tyre_wear_question():
    st, b, _ = strategist(TrackWetness=1, PlayerTireCompound=0)
    for k in range(30):
        b.src["SessionTime"] = k * 5.0
        st._rb_tick()
    assert st.rain_answer("switch", {"TYRE", "CHANGE_T"}) == {"route": "tyres"}
    assert st.rain_answer("switch", {"DRYCOMP", "SWITCH"})["sid"] == "ty_opt"


# ------------------------------------------------------------------ 7. the radio: routing in the app
app = pytest.importorskip("engineer.app")


def radio(strat):
    from test_radio_routing import Brain, Voice
    eng = types.SimpleNamespace(voice=Voice(), brain=Brain())
    me = types.SimpleNamespace(_engine=eng, _team=None, _q=queue.Queue(), _strat=strat, _pit=None, notes=[], log=[])
    me._log = me.log.append
    me._in_car = lambda: True
    me._save_note = me.notes.append
    me._crew_say = lambda role, text: me.log.append(f"{role}: {text}")
    for f in ("_strat_line", "_heard", "_gap_both_ways", "_rain_q"):
        setattr(me, f, types.MethodType(getattr(app.Api, f), me))
    return me, eng


def test_radio_rain_question_answers_as_text_until_the_clip_exists():
    st, b, _ = strategist()
    st.log = lambda m: None
    shown = []
    st.show = lambda role, text: shown.append((role, text))
    for k in range(121):
        b.src["SessionTime"] = k * 5.0
        b.src["TrackWetness"] = 5 if k < 40 else 4 if k < 80 else 3
        st._rb_tick()
    me, eng = radio(st)
    me._heard("Is it drying?", "radio")
    assert shown and shown[-1][0] == "ENGINEER" and shown[-1][1].startswith("The track is drying.")
    assert "rb_trend_drying" in b.said                  # it tried the new clip first (not rendered here)
    assert "ack" not in eng.voice.said and not me.notes and not eng.brain.answered


@pytest.mark.parametrize("text", ["Will it rain any more?", "Is it getting wetter?", "When do we go to slicks?",
                                  "Should we switch tyres?", "Strategist, is it time for dries?"])
def test_radio_rain_questions_never_just_copy(text):
    st, b, _ = strategist(Precipitation=0.2)
    shown = []
    st.show = lambda role, text: shown.append((role, text))
    for k in range(60):
        b.src["SessionTime"] = k * 5.0
        st._rb_tick()
    me, eng = radio(st)
    me._heard(text, "radio")
    assert shown or any(s in b.said for s in ("box_wets", "rain_worse", "ty_opt", "tb_no_data"))
    assert "ack" not in eng.voice.said and not me.notes


def test_radio_without_a_session_falls_back_to_the_old_rain_answer():
    from test_radio_routing import Strat
    me, eng = radio(Strat())
    me._strat.dry = False
    me._heard("Is it drying?", "radio")
    assert any(l.startswith("ENGINEER") for l in me.log)    # track + tips, as before


def test_radio_do_we_need_wets_on_a_wet_track_gets_the_crossover():
    st, b, _ = strategist(PlayerTireCompound=0, Precipitation=0.4)
    shown = []
    st.show = lambda role, text: shown.append((role, text))
    for k in range(121):
        b.src["SessionTime"] = k * 5.0
        b.src["TrackWetness"] = 3 + k // 40
        st._rb_tick()
    me, eng = radio(st)
    me._heard("Do we need wets?", "radio")
    assert "box_wets" in b.said or shown


# ------------------------------------------------------------------ 8. no new spoken lines without approval
def test_pending_lines_are_never_said_by_the_stand_in():
    from engineer import lines_new, strat_lines
    ids = RB.PENDING_IDS
    assert len(ids) == len(RB.PENDING)
    assert not ids & set(lines_new.table())             # the stand-in voice says every lines_new line
    assert not ids & set(strat_lines.LINES)             # the strategist's lines are spoken by the placeholder voice
    for sid, text in RB.PENDING:
        assert sid.startswith("rb_") and not any(c.isdigit() for c in text), sid    # numbers are fills, said as words
    import re
    src = open(os.path.join(ROOT, "engineer", "rain_brain.py"), encoding="utf-8").read()
    used_ids = set(re.findall(r'"(rb_[a-z_]+)"', src)) | {f"rb_{to}_{k}" for to in ("slicks", "wets")
                                                         for k in ("next", "in", "in_rough")} | \
        {f"rb_call_{to}_soon" for to in ("slicks", "wets")}
    assert used_ids & ids == ids, ids - used_ids                       # every proposed line is wired to something
    used = {"box_wets", "rain_worse", "ty_opt", "tb_no_data"}          # the existing lines the brain may play
    spec_ids = _render_ids(None)
    assert used <= spec_ids | set(lines_new.table())
    assert not ids & spec_ids                           # not rendered until approved


def _render_ids(approved, tmp=None):
    """The render list (tools/vocab_spec.py), optionally with a tools/rain_approved.txt in a copy of the repo."""
    import importlib.util
    root = ROOT
    if approved is not None:
        root = str(tmp)
        for d in ("tools", "engineer"):
            os.makedirs(os.path.join(root, d), exist_ok=True)
        for f in ("tools/vocab_spec.py", "engineer/lines_new.py", "engineer/rain_brain_lines.py"):
            shutil.copy(os.path.join(ROOT, f), os.path.join(root, f))
        open(os.path.join(root, "tools", "rain_approved.txt"), "w").write(approved)
    spec = importlib.util.spec_from_file_location("vocab_spec_rain", os.path.join(root, "tools", "vocab_spec.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return {sid for sid, _, _ in m.L}


def test_approved_lines_go_on_the_render_list(tmp_path):
    some = _render_ids("# approved 2026-10-31\nrb_trend_drying\nrb_slicks_in\n", tmp_path / "a")
    assert {"rb_trend_drying", "rb_slicks_in"} <= some and "rb_call_heavier" not in some
    every = _render_ids("all\n", tmp_path / "b")
    assert RB.PENDING_IDS <= every


# ------------------------------------------------------------------ 9. a whole stint through the strategist
def race(wet_at, rain_at, start_comp, switch_to, switch_from=2300, n=12, until=3600, finish_at=None, history=True):
    """A synthetic race: 12 cars in my class (car 0 = me, never pits), lap time = car pace x the penalty table for the
    tyre it's on; the others change tyres one by one from switch_from. -> (said, clips, logs)"""
    from engineer.strat_live import Strategist

    class Src(dict):
        def info(self, sec):
            return self["_info"].get(sec)
    info = {"DriverInfo": {"DriverCarIdx": 0, "DriverTires": [{"TireIndex": 0, "TireCompoundType": "Hard"},
                                                             {"TireIndex": 1, "TireCompoundType": "Wet"}],
                           "Drivers": [{"CarIdx": i, "CarClassID": 1, "CarPath": "bmwm4gt3"} for i in range(n)]},
            "WeekendInfo": {"TrackName": "lemans full", "TrackWeatherType": "Dynamic"}, "SessionInfo": {}}
    src = Src(_info=info)
    said, clips, logs = [], [], []
    b = types.SimpleNamespace(src=src, finished=False, sess_num=0, sess_type="Race", green_seen=False, electric=False,
                              info=lambda s, d=None: src.info(s) or d,
                              drivers=lambda: {d["CarIdx"]: d for d in info["DriverInfo"]["Drivers"]},
                              me=lambda: 0, my_class=lambda: (1, "GT3"), class_cars=lambda c: list(range(n)),
                              is_race=lambda: True, laps_to_go=lambda: max(0, 30 - (src.get("LapCompleted") or 0)),
                              metric=lambda: True, class_pos=lambda i: 3, fuel_lap_est=lambda: 3.0, car_num=lambda i: i,
                              session=lambda: {}, g=lambda k, d=None: src.get(k, d))

    def say(sid, fills=None, prio=None):
        clips.append((src["SessionTime"], sid))
        return sid in ("box_wets", "rain_worse", "ty_opt", "tb_no_data")
    b.say = say
    st = Strategist(lambda r, t: said.append((src.get("SessionTime"), r, t)),
                    log=lambda m: logs.append((src.get("SessionTime"), m)))
    st.replan = lambda lc: None
    model = {"base": 210.0, "lane_loss": 35.0, "tyre_time": 12.0, "fuel_lap": 3.0}
    st.model = lambda force=False: model if history else None     # history = your earlier laps here (strategy db)
    lc, last, comp = [0] * n, [-1.0] * n, [start_comp] * n
    pct, best = [i / n for i in range(n)], [200.0 + i * 0.5 for i in range(n)]
    t = 0.0
    while t < until:
        t += 1.0
        w = wet_at(t)
        if finish_at and t >= finish_at:
            b.finished = True
        onp = [False] * n
        for i in range(n):
            lt = best[i] * (1 + (R.WET_PEN if comp[i] == 1 else R.SLICK_PEN)[w])
            pct[i] += 1.0 / lt
            if i and comp[i] != switch_to and t >= switch_from + i * 100:
                onp[i], comp[i] = True, switch_to
            if pct[i] >= 1:
                pct[i] -= 1
                lc[i] += 1
                last[i] = lt
        src.update({"SessionTime": t, "TrackWetness": w, "Precipitation": rain_at(t), "IsOnTrack": True,
                    "IsReplayPlaying": False, "CarIdxLapCompleted": list(lc), "CarIdxLastLapTime": list(last),
                    "CarIdxTireCompound": list(comp), "CarIdxOnPitRoad": onp, "CarIdxBestLapTime": list(best),
                    "PlayerTireCompound": comp[0], "LapCompleted": lc[0], "LapLastLapTime": last[0], "OnPitRoad": False,
                    "Speed": 50, "FuelLevel": 90 - lc[0] * 3, "SessionState": 4, "PlayerCarMyIncidentCount": 0})
        st.tick(b)
    return said, clips, logs


def _errors(logs):
    return [m for _, m in logs if m.startswith(("[rain]", "[strategy]")) and ("Error" in m or "Exception" in m)]


def test_drying_race_calls_slicks_at_the_crossover_once():
    said, clips, logs = race(lambda t: max(2, 6 - int(t // 900)), lambda t: max(0.0, 0.4 - t / 1500), 1, 0)
    assert not _errors(logs), _errors(logs)
    box = [(t, x) for t, r, x in said if "Box this lap for slicks" in x]
    assert box, said
    # the field showed slicks faster around level three (the table crossover is at 3.2, from about 2950 s)
    assert 2700 <= box[0][0] <= 3300
    assert "Slicks are 2 seconds a lap faster" in box[0][1]            # measured from the other cars, not the table
    assert not [c for c in clips if c[1] == "rb_call_slicks_now"]      # the box call went out: no second crossover call


def test_drying_race_without_history_the_rain_brain_calls_it():
    """No dry pace stored for this car / track yet: the strategist's table call can't run, the rain brain's can
    (from the other cars' lap times)."""
    said, clips, logs = race(lambda t: max(2, 6 - int(t // 900)), lambda t: max(0.0, 0.4 - t / 1500), 1, 0, history=False)
    assert not _errors(logs), _errors(logs)
    calls = [c for c in clips if c[1] == "rb_call_slicks_now"]
    assert len(calls) == 1 and 2700 <= calls[0][0] <= 3300
    assert any("Crossover. Slicks are faster now, about 2.0 seconds a lap." in m for _, m in logs)


def test_wetting_race_heavier_call_then_wets():
    said, clips, logs = race(lambda t: 1 if t < 1200 else min(6, 1 + int((t - 1200) // 500)),
                             lambda t: 0.0 if t < 900 else min(0.8, 0.03 + (t - 900) / 3000), 0, 1)
    assert not _errors(logs), _errors(logs)
    heavier = [c for c in clips if c[1] == "rb_call_heavier"]
    assert len(heavier) == 1 and 1700 <= heavier[0][0] <= 2000          # once there's water on the track
    assert ("rain_worse" in [c[1] for c in clips])                     # the recorded "Rain is worse" played with it
    assert any("Box this lap for wets" in x for _, _, x in said)


def test_no_rain_calls_after_the_flag():
    said, clips, logs = race(lambda t: max(2, 6 - int(t // 900)), lambda t: max(0.0, 0.4 - t / 1500), 1, 0,
                             finish_at=2000)
    assert not [x for t, r, x in said if t > 2000 and "Box this lap" in x]
    assert not [c for c in clips if c[0] > 2000 and c[1].startswith("rb_")]
