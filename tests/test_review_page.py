"""#582 iPad REVIEW page: summary, laps (sectors / gap to best / flags), traces vs the best lap, the debrief and the
setup suggestion - from Angelo's real dev recordings. Never a made-up number (#419): what isn't in the data is None."""
import json
import os
import socket
import urllib.error
import urllib.request

import pytest
import yaml

from engineer import review_page as RP, setup_sheet as SS
from engineer.telemetry import _list_one

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IBT = "/mnt/user-data/uploads/Engineer Voice - Engine Test/_dev/ibt/"
LEMANS, NAVARRA = IBT + "gtp_lemans.ibt", IBT + "m2_navarra.ibt"
need = pytest.mark.skipif(not (os.path.isfile(LEMANS) and os.path.isfile(NAVARRA)), reason="dev recordings not here")
LIST = lambda: _list_one(IBT)


@pytest.fixture(autouse=True)
def _fresh():
    RP.reset()
    yield
    RP.reset()


def _lemans():
    return RP.session_data(LEMANS)


# ------------------------------------------------------------------ one session
@need
def test_lemans_summary_is_the_recording():
    d = _lemans()
    assert d["track"] == "Circuit des 24 Heures du Mans" and d["car_path"] == "bmwlmdh"
    assert d["type"] == "Qualifying"                      # SessionNum 1 = Lone Qualify in this file, not "Practice / ... / Race"
    assert d["laps_n"] == 2 and d["clean_n"] == 2
    assert d["best_n"] == 2 and d["best"] == pytest.approx(214.526) and d["best_clean"]
    assert d["avg"] == pytest.approx((218.934 + 214.526) / 2, abs=1e-3) and d["avg_n"] == 2
    assert d["incidents"] == 0
    assert d["units"] == "mph"


@need
def test_lemans_laps_sectors_deltas_flags():
    laps = {L["n"]: L for L in _lemans()["laps"]}
    assert laps[0]["time"] is None and laps[0]["flags"] == ["partial"] and laps[0]["sec"] == [None, None, None]
    assert laps[0]["delta"] is None                     # a part lap has no time and no gap: never invented
    for n in (1, 2):
        L = laps[n]
        assert all(s is not None for s in L["sec"])
        assert sum(L["sec"]) == pytest.approx(L["time"], abs=0.003)
    assert laps[1]["delta"] == pytest.approx(4.408, abs=1e-3) and laps[2]["delta"] == 0 and laps[2]["best"]
    assert laps[1]["flags"] == [] and laps[1]["clean"]
    assert _lemans()["best_sec"] == laps[2]["sec"]       # lap 2 was quicker in every third


@need
def test_navarra_pit_incident_and_no_clean_lap():
    d = RP.session_data(NAVARRA)
    laps = {L["n"]: L for L in d["laps"]}
    assert laps[6]["flags"] == ["pit", "incident"] and laps[6]["incidents"] == 2
    assert laps[7]["flags"] == ["incident"] and laps[7]["best"]
    assert d["best_n"] == 7 and not d["best_clean"]
    assert d["avg"] is None and d["avg_n"] == 0 and d["spread"] is None       # no clean lap: "—", not an average of dirty laps
    assert d["best_sec"] == [None, None, None]
    assert d["incidents"] == 4 and d["type"] == "Practice"


@need
def test_trace_against_best_downsampled():
    d = _lemans()
    t = RP.trace(d, 1)
    assert t["ref"] == 2 and t["lap"] == 1
    n = len(t["d"])
    assert 400 <= n <= 900 and len(t["me"]["v"]) == n and len(t["best"]["thr"]) <= n
    assert all(b > a for a, b in zip(t["d"], t["d"][1:]))
    assert 150 < max(t["me"]["v"]) < 230                 # mph down the Mulsanne in the GTP
    assert all(0 <= x <= 1.0001 for x in t["me"]["thr"] + t["me"]["brk"])
    assert t["gap"][-1] == pytest.approx(4.408, abs=0.3)  # gap at the end of the lap ~ the lap time difference
    best = RP.trace(d, 2)
    assert best["ref"] is None and best["best"] is None and best["gap"] is None
    assert "error" in RP.trace(d, 0)                     # the part lap: no trace, said in words


@need
def test_cached_per_file(monkeypatch):
    d = _lemans()

    def boom(*a, **k):
        raise AssertionError("recording read again")
    monkeypatch.setattr(RP, "_build", boom)
    assert RP.session_data(LEMANS) is d                  # memory
    RP._MEM.clear()
    again = RP.session_data(LEMANS)                       # disk cache
    assert again["laps"] == json.loads(json.dumps(d["laps"]))
    assert os.path.isfile(RP._cache_file(d["sid"]))


# ------------------------------------------------------------------ the page's data
@need
def test_view_lists_sessions_newest_first_and_picks():
    v = RP.view(list_fn=LIST)
    assert [s["track"] for s in v["sessions"]] == ["Circuit des 24 Heures du Mans", "Circuito de Navarra"]
    assert v["sid"] == v["sessions"][0]["id"] and v["session"]["file"] == "gtp_lemans.ibt"
    assert "traces" not in v["session"] and "setup_flat" not in v["session"] and "trace" not in v
    v2 = RP.view(sid=v["sessions"][1]["id"], lap=6, list_fn=LIST)
    assert v2["session"]["file"] == "m2_navarra.ibt" and v2["trace"]["lap"] == 6 and v2["trace"]["ref"] == 7
    v3 = RP.view(sid="nope", list_fn=LIST)               # an old id: the newest session instead
    assert v3["sid"] == v["sid"]
    assert len(json.dumps(v)) < 20000                    # the poll stays light (traces only when a lap is tapped)


def test_view_without_recordings():
    v = RP.view(list_fn=lambda: [])
    assert v["ok"] and v["session"] is None and v["sessions"] == [] and v["why"]
    assert v["setup"] == {"has": False}


@need
def test_debrief_states(monkeypatch):
    from engineer import forensics as F
    v = RP.view(sid=None, list_fn=LIST, can_analyse=lambda: False)
    assert v["debrief"]["state"] == "none" and "iRacing is closed" in v["debrief"]["why"]
    nav = next(s for s in _list_one(IBT) if s["path"].endswith("m2_navarra.ibt"))
    F.analyse_cached([NAVARRA], log=lambda *a: None)      # what the PC works out once iRacing is closed
    v = RP.view(sid=nav["id"], list_fn=LIST)
    db = v["debrief"]
    assert db["state"] == "ready" and db["source"] == "this session"
    assert [c["name"] for c in db["corners"]] == ["Turn 1", "Turn 3", "Turn 6"]
    assert db["corners"][0]["text"] == "2 incidents"
    laps = {L["n"]: L for L in v["session"]["laps"]}
    assert laps[7]["fx"] == ["Incident at Turn 1", "Incident at Turn 6"]


@need
def test_debrief_from_the_night_review():
    from engineer import forensics as F, debrief as DB
    rv = DB.night_review(F.analyse([NAVARRA], log=lambda *a: None))
    nav = next(s for s in _list_one(IBT) if s["path"].endswith("m2_navarra.ibt"))
    db = RP.debrief_for(nav["id"], NAVARRA, fx_review=rv)
    assert db["state"] == "ready" and db["source"] == "night review" and db["corners"]


@need
def test_debrief_worked_out_in_background_only_when_allowed():
    calls = []
    lem = next(s for s in _list_one(IBT) if s["path"].endswith("gtp_lemans.ibt"))
    b = RP.debrief_for(lem["id"], LEMANS, can_analyse=lambda: True, run_fx=lambda ps: calls.append(ps))
    assert b["state"] == "pending"
    import time
    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    assert calls == [[LEMANS]]


@need
def test_setup_block_shows_this_sessions_values(tmp_path):
    cs = yaml.safe_load(open(os.path.join(HERE, "fixtures", "bmw_gtp_lemans_carsetup.yaml"), encoding="utf-8"))["CarSetup"]
    changes = [{"t": "TC2 (slip) one step up (in the car)", "key": "tc2", "why": "Oversteer on exit.", "rule": "Steps in sooner."}]
    st = SS.Store(str(tmp_path / "s.json"))
    st.push(SS.make_suggestion(changes, cs, "bmwlmdh", "BMW M Hybrid V8", source="My style"))
    v = RP.view(list_fn=LIST, store=st)
    s = v["setup"]
    assert s["has"] and s["same_car"] and s["total"] == 1
    f = s["items"][0]["fields"][0]
    assert f["before"] == "5 (TCLON)" and f["sug"] == "6 (TCLON)" and f["here"] == "5 (TCLON)"
    nav = next(x for x in v["sessions"] if x["track"] == "Circuito de Navarra")
    s2 = RP.view(sid=nav["id"], list_fn=LIST, store=st)["setup"]
    assert not s2["same_car"] and s2["items"][0]["fields"][0]["here"] is None   # another car: no value from the M2


# ------------------------------------------------------------------ server + pages
class _Api:
    def review_page(self, sid=None, lap=None):
        return RP.view(sid, lap, list_fn=LIST)

    def fx_review_data(self):
        return {"sections": [], "sessions": []}


def _port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


@need
def test_endpoint_needs_the_key():
    from engineer.remote import Remote
    port = _port()
    r = Remote(_Api(), port=port, token="tok", log=lambda *a: None)
    r.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/review")
        assert e.value.code == 403
        d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/review?k=tok&lap=1"))
        assert d["session"]["file"] == "gtp_lemans.ibt" and d["trace"]["ref"] == 2
        assert json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/debrief?k=tok")) == {"sections": [], "sessions": []}
    finally:
        r.srv.shutdown()


def test_pages_and_navigation():
    ui = os.path.join(ROOT, "engineer", "ui", "ipad")
    idx = open(os.path.join(ui, "index.html"), encoding="utf-8").read()
    assert "'review.html'+location.search\">REVIEW" in idx and "'debrief.html'+location.search\">DEBRIEF" in idx
    assert 'location.href = "review.html" + (location.search' in idx          # no session for 10 s -> REVIEW
    rv = open(os.path.join(ui, "review.js"), encoding="utf-8").read()
    assert "/api/review?k=" in rv and "AUTO && d.on_track" in rv               # back to the dashboard on track
    assert "/api/debrief" in open(os.path.join(ui, "debrief.html"), encoding="utf-8").read()
    assert 'id="review"' in open(os.path.join(ui, "setup.html"), encoding="utf-8").read()
    assert os.path.isfile(os.path.join(ui, "review.html"))
