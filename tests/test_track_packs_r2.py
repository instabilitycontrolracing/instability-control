"""Track packs round 2 (2026-10-28): every Sports Car research track and layout, Le Mans parity for voice lines,
crowd maps and bridge echoes. Runs from the repo only (no research files needed)."""
import glob, importlib, json, os, re, sys, time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TOOLS = os.path.join(ROOT, "tools")

from engineer import crowd as C, lines_new as LN, rain as R, series as SE, strat_lines as SL  # noqa: E402
from engineer.track_packs import PACK_ALIASES, PACK_BRIDGES, PACK_TRACKS, PACK_WET, PACK_WET_ALIAS  # noqa: E402
from engineer.track_theme import norm  # noqa: E402

NEW = {"atlantamotorspeedway", "autoclubspeedway", "circuitdeneversmagnycours", "homesteadmiamispeedway", "lankebanen",
       "lasvegasmotorspeedwayroadcourses", "milwaukeemile", "newhampshiremotorspeedway", "newjerseymotorsportspark",
       "poconoraceway", "portlandinternationalraceway", "thruxtoncircuit", "willowspringsinternationalraceway",
       "worldwidetechnologyraceway"}
BUNDLED = sorted(glob.glob(os.path.join(ROOT, "engineer", "trackside_tracks", "*.json")))


def _spell():
    os.environ.setdefault("USERPROFILE", "/tmp")
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    sys.modules.pop("vocab_jobs", None); sys.modules.pop("vocab_spec", None)
    return importlib.import_module("vocab_jobs")


def test_new_tracks_and_every_id_resolve_to_their_own_entry():
    assert NEW <= set(PACK_TRACKS)
    assert PACK_TRACKS["thruxtoncircuit"]["name"] == "Thruxton" and len(PACK_TRACKS["thruxtoncircuit"]["watch"]) == 6
    assert "Lucas Oil" not in {v["name"] for v in PACK_TRACKS.values()}          # off-road: left out
    for a, k in PACK_ALIASES.items():
        assert SE.track_info(a) is (SE.TRACKS[SE.TRACKS[k]["alias"]] if "alias" in SE.TRACKS[k] else SE.TRACKS[k]), a
    for tid, short in (("thruxton", "Thruxton"), ("portland full", "Portland"), ("magnycours gp", "Magny-Cours"),
                       ("zandvoort 2023 oostelijk", "Zandvoort"), ("nurburgring gpshort", "Nürburgring GP"),
                       ("nurburgring combinedlong", "Nürburgring"), ("nurburgring nordschleife", "Nordschleife"),
                       ("suzuka westchicane", "Suzuka"), ("monza combinedchicanes", "Monza"), ("roadatlanta club", "Road Atlanta"),
                       ("lemans nochicane", "Le Mans"), ("sonoma 2025 sportscar", "Sonoma"), ("willow international", "Willow Springs")):
        assert SE.track_info("", tid)["name"] == short, tid
    for k, v in PACK_TRACKS.items():
        for w in v.get("watch", []):
            assert len(w) <= 70, w
    assert SE.drill_spots("spa up")["lap1"] == "La Source, Eau Rouge and Raidillon"     # round 1 listed La Source twice
    assert SE.drill_spots("thruxton")["lap1"] == "Allard, Campbell and Cobb"


def test_hand_done_tracks_keep_their_notes():
    assert SE.track_info("lemans full")["watch"][0] == "Dunlop Chicane: lap-1 pile-ups. Brake early on lap 1."
    assert SE.track_info("", "monza combinedchicanes") is SE.TRACKS["autodromonazionalemonza"]
    assert SE.TRACKS["autodromonazionalemonza"]["watch"][0] == "Turn 1 chicane on lap 1: chaos."


def test_lap_one_lines_resolve_from_display_name_and_iracing_id():
    new = {k for k in SL.TRACK_LAP1 if k in PACK_TRACKS}
    assert len(new) >= 50
    keys = {k for k, _ in SL.units()}
    for k in SL.TRACK_LAP1:
        assert SL.track_lap1(k) == k
        assert f"{k}~0~0" in keys
        for t in SL.TRACK_LAP1[k]:
            assert not re.search(r"\d", t), t                       # numbers written out (render rules)
            assert len(t) <= 90, t
    for a, k in PACK_ALIASES.items():
        if k in SL.TRACK_LAP1:
            assert SL.track_lap1(a) == k, a
    assert SL.track_lap1("brandshatch grandprix") == "brandshatchcircuit"
    assert SL.track_lap1("Thruxton Circuit") == "thruxtoncircuit"
    assert SL.track_lap1("lucas oil speedway") is None


def test_wet_tips_spoken_by_the_engineer_and_listed_once():
    vj = _spell()
    spec = importlib.import_module("vocab_spec")
    sids = {sid for sid, _, _ in spec.L}
    table = LN.table()
    seen = set()
    assert len(LN.WET_TRACK_LINES) >= 60
    for k, lines in LN.WET_TRACK_LINES.items():
        assert R.TRACK_WET[k] == [t for _, t in lines]
        for sid, t in lines:
            assert sid.startswith("wet_") and sid not in seen and sid in sids and sid in table, sid
            seen.add(sid)
            assert R.wet_sid(t) == sid
            assert vj.spell(t) == t, t                               # no digits, no lone letters for the voice
            assert len(t) <= 100, t
            assert t not in PACK_WET.get(k, [])                      # the text note it came from is gone
        notes = R.track_notes(k)
        assert notes[:len(lines)] == [t for _, t in lines] and len(set(notes)) == len(notes), k
    # every iRacing id of a track with spoken tips gets them on the radio
    for a, k in PACK_ALIASES.items():
        if k in LN.WET_TRACK_LINES:
            assert a in PACK_WET_ALIAS, a
            tips = {t for s in range(4) for t in R.tips(3, seed=s, track_key=a)}
            assert tips & set(R.TRACK_WET[k]), a
    assert set(R.track_notes("Brands Hatch Circuit")) == set(R.TRACK_WET["brandshatchcircuit"])


def test_crowd_maps_for_more_layouts():
    assert len(BUNDLED) >= 110
    for p in BUNDLED:
        with open(p, encoding="utf-8-sig") as fh:
            d = json.load(fh)
        m = C.TrackMap(d, p)
        assert m.match and m.stands and m.length_m > 0, p
        for s in m.stands:
            assert 0 <= s.frm < 1 and 0 <= s.to < 1 and 0 < s.length < 0.2, (p, s.name)
        for tid in m.match:
            assert C.find_track([C.BUNDLED_TRACKS], tid, "").source == p, tid    # incl. 'suzuka west' vs 'westchicane'
    for tid in ("thruxton", "suzuka westchicane", "monza historicsecondchicane", "lagunaseca", "lagunaseca 2026",
                "silverstone gp", "silverstone 2019 gp", "zandvoort grandprix"):
        assert tid in C.find_track([C.BUNDLED_TRACKS], tid, "").match, tid
    th = C.find_track([C.BUNDLED_TRACKS], "thruxton", "")
    assert [s.name for s in th.stands] == ["Noble spectator area (new)", "Woodham Hill Bank (added 2025)"]


def test_bridge_echo_spans():
    from engineer.ambience import Ambience
    assert {"roadatlantafull", "roadamericafull", "limerock2019gp", "midohiofull"} <= set(PACK_BRIDGES)
    for k, spans in PACK_BRIDGES.items():
        for a, b in spans:
            assert 0 < a < b < 1 and b - a < 0.01, k
    amb = Ambience(None, None, log=lambda *a: None)
    amb._places_t = time.time() + 3600                               # no Grandstand fetch in the test
    a, b = PACK_BRIDGES["roadatlantafull"][0]
    assert amb._under_bridge((a + b) / 2, "roadatlanta full")
    assert not amb._under_bridge(a - 0.01, "roadatlanta full")
    assert not amb._under_bridge((a + b) / 2, "roadatlanta club")      # another layout: no bridge there
    assert amb._under_bridge(0.0765, "lemans full")                   # Le Mans as before
    assert not amb._under_bridge(0.5, "lemans full")


def test_corner_clips_for_new_tracks(tmp_path):
    vj = _spell()
    lm = lambda *names: [{"landmarkNames": [n], "distanceRoundLapStart": i * 100, "distanceRoundLapEnd": i * 100 + 50}
                         for i, n in enumerate(names)]
    d = {"trackLandmarksData": [
        {"irTrackName": "thruxton", "trackLandmarks": lm("church", "village_en")},
        {"irTrackName": "magnycours gp", "trackLandmarks": lm("adelaide", "180", "lycee_pin")},
        {"irTrackName": "portland full", "trackLandmarks": lm("turn1")},
        {"irTrackName": "chicagoland", "isOval": True, "trackLandmarks": lm("the_tri_oval")},
        {"irTrackName": "charlotte 2025 roval2019", "isOval": True, "trackLandmarks": lm("the_first_chicane")},
    ]}
    p = tmp_path / "lm.json"
    p.write_text(json.dumps(d))
    names = vj.corner_names([str(p)])
    assert {"Church", "Village En", "Adelaide", "180", "Lycee Pin", "The First Chicane"} <= set(names)
    assert "The Tri Oval" not in names
    assert vj.corner_say("Village En") == "Village." and vj.corner_say("180") == "One-eighty."
