"""#602 iPad SETUP sheet: the garage layout (from Angelo's screenshots), values from a real BMW GTP recording, the diff
(current -> suggested, clicks, reasons) and the self-ticking checklist. Never a made-up number (#419)."""
import copy
import os

import pytest
import yaml

from engineer import setup_sheet as S

HERE = os.path.dirname(os.path.abspath(__file__))
CS = yaml.safe_load(open(os.path.join(HERE, "fixtures", "bmw_gtp_lemans_carsetup.yaml"), encoding="utf-8"))["CarSetup"]

# My style's real output for this recording (style_setup.build on gtp_lemans.ibt, 2026-10-30)
CHANGES = [
    {"t": "A little more rake: rear pushrod up a touch", "key": "rh_r",
     "why": "Understeer mid-corner in fast corners: 4 of 6 corner reads (67%) over 1 session(s).",
     "rule": "Rear higher = aero balance forward = more front grip at speed."},
    {"t": "TC2 (slip) one step up (in the car)", "key": "tc2",
     "why": "Oversteer on exit in slow corners: 9 of 16 corner reads (56%) over 1 session(s).", "rule": "Steps in sooner."},
]


def _lay():
    return S.layout_for("bmwlmdh")


# ------------------------------------------------------------------ layout parsing
def test_layout_matches_the_garage_screenshots():
    lay = _lay()
    assert lay and lay["car"] == "BMW M Hybrid V8"
    assert [t["name"] for t in lay["tabs"]] == ["TIRES/AERO", "CHASSIS", "BRAKES/DRIVE UNIT", "NOTES"]
    secs = {t["name"]: [s["name"] for row in t["rows"] for s in row] for t in lay["tabs"]}
    assert secs["CHASSIS"] == ["FRONT", "LEFT FRONT", "RIGHT FRONT", "LEFT REAR", "RIGHT REAR", "REAR"]
    assert secs["TIRES/AERO"] == ["TIRE TYPE", "LEFT FRONT", "RIGHT FRONT", "LEFT REAR TIRE", "RIGHT REAR TIRE", "AERO SETTINGS", "AERO CALCULATOR"]
    assert secs["BRAKES/DRIVE UNIT"] == ["LIGHTING", "BRAKE SPEC", "HYBRID CONFIG", "FUEL", "TRACTION CONTROL", "GEAR RATIOS", "REAR DIFF SPEC"]
    front = next(s for row in lay["tabs"][1]["rows"] for s in row if s["name"] == "FRONT")
    assert [f["label"] for f in front["fields"]] == ["Heave spring", "Heave perch offset", "Heave spring defl", "Heave slider defl",
                                                     "ARB size", "ARB blades", "Toe-in", "Pushrod length offset"]
    lr = next(s for row in lay["tabs"][1]["rows"] for s in row if s["name"] == "LEFT REAR")
    assert [f["label"] for f in lr["fields"]][:6] == ["Corner weight", "Ride height", "Shock defl", "Spring defl", "Spring perch offset", "Spring rate"]
    assert lr["fields"][-1]["label"] == "Toe-in"
    for tab, sec, f, path in S.fields(lay):
        assert f["adj"] in ("arrows", "list", "read"), path
    adj = {f["label"]: f["adj"] for t, s, f, _p in S.fields(lay) if s["name"] == "LEFT FRONT" and t["name"] == "CHASSIS"}
    assert adj["Ride height"] == "read" and adj["Camber"] == "arrows" and adj["Torsion bar O.D."] == "list"


def test_layout_keys_point_at_real_fields():
    lay = _lay()
    paths = {p for *_, p in S.fields(lay)}
    for key, ps in lay["keys"].items():
        for p in ps:
            assert p in paths, (key, p)
    for _, ps in S.TEXT_RULES:
        for p in ps:
            assert p in paths, p


def test_every_field_reads_from_the_real_recording_in_garage_units():
    flat = S.flatten(CS)
    sh = S.sheet(S.make_suggestion([], CS, "bmwlmdh", "BMW M Hybrid V8"))
    vals = {}
    for t in sh["tabs"]:
        for row in t["rows"]:
            for s in row:
                for f in s["fields"]:
                    assert f["value"] != S.DASH, (t["name"], s["name"], f["label"])
                    vals[(t["name"], s["name"], f["label"])] = f["value"]
    assert flat["Chassis.Front.HeavePerchOffset"] == "-21.5 mm"
    # the same numbers his screenshots show for this setup
    assert vals[("CHASSIS", "FRONT", "Heave perch offset")] == '-0.846"'
    assert vals[("CHASSIS", "FRONT", "Pushrod length offset")] == '-1.201"'
    assert vals[("CHASSIS", "FRONT", "Toe-in")] == '-2/32"'
    assert vals[("CHASSIS", "LEFT REAR", "Toe-in")] == '+0/32"'
    assert vals[("CHASSIS", "FRONT", "Heave slider defl")] == "1.291 in of 7.874 in"
    assert vals[("CHASSIS", "LEFT FRONT", "Corner weight")] == "606 lbs"
    assert vals[("CHASSIS", "LEFT FRONT", "Shock defl")] == "0.465 in of 3.937 in"
    assert vals[("CHASSIS", "LEFT REAR", "Spring perch offset")] == '1.594"'
    assert vals[("CHASSIS", "REAR", "Third perch offset")] == '1.752"'
    assert vals[("BRAKES/DRIVE UNIT", "BRAKE SPEC", "Front master cyl.")] == "0.752 in"
    assert vals[("BRAKES/DRIVE UNIT", "BRAKE SPEC", "Rear master cyl.")] == "0.811 in"
    assert vals[("BRAKES/DRIVE UNIT", "REAR DIFF SPEC", "Preload")] == "59 ft-lbs"
    assert vals[("TIRES/AERO", "AERO CALCULATOR", "Front RH at speed")] == '0.591"'
    assert vals[("TIRES/AERO", "AERO CALCULATOR", "Rear RH at speed")] == '1.575"'
    assert vals[("TIRES/AERO", "LEFT FRONT", "Starting pressure")] == "22.0 psi"
    assert vals[("TIRES/AERO", "RIGHT FRONT", "Last temps I M O")] == "95F 95F 95F"
    assert vals[("BRAKES/DRIVE UNIT", "GEAR RATIOS", "Speed in seventh")] == "210.7 mph"
    assert vals[("BRAKES/DRIVE UNIT", "FUEL", "Fuel level")] == "11.8 gal"
    assert vals[("BRAKES/DRIVE UNIT", "TRACTION CONTROL", "Traction control gain")] == "4 (TCLAT)"


def test_unknown_values_show_dash_never_a_number():
    sh = S.sheet(S.make_suggestion(CHANGES, {}, "bmwlmdh", "BMW M Hybrid V8"))
    for t in sh["tabs"]:
        for row in t["rows"]:
            for s in row:
                for f in s["fields"]:
                    assert f["value"] == S.DASH
                    assert not f.get("sug")
    assert all(f["sug"] is None and f["before"] == S.DASH for it in sh["items"] for f in it["fields"])


def test_other_cars_fall_back_to_iracing_sections_and_m4_is_todo():
    assert S.layout_for("bmwm4gt3", "BMW M4 GT3") is None           # TODO: no screenshots of the M4 garage yet
    cs = {"Tires": {"LeftFront": {"StartingPressure": "200 kPa", "LastTempsOMI": "77C, 77C, 77C"}},
          "Chassis": {"Front": {"ArbSetting": "3", "ToeIn": "-1.4 mm"}}}
    sug = S.make_suggestion([{"t": "Front ARB one step softer", "key": "farb", "why": "Mid-corner understeer."}], cs, "bmwm4gt3", "BMW M4 GT3")
    sh = S.sheet(sug)
    assert sh["layout"]["generic"] is True
    assert [t["name"] for t in sh["tabs"]] == ["TIRES", "CHASSIS"]
    f = {x["label"]: x for row in sh["tabs"][0]["rows"] for s in row for x in s["fields"]}
    assert f["Starting pressure"]["value"] == "29.0 psi"
    assert f["Last temps OMI"]["value"] == "171F, 171F, 171F"
    arb = {x["label"]: x for row in sh["tabs"][1]["rows"] for s in row for x in s["fields"]}["Arb setting"]
    assert arb.get("changed") and arb["how"] == "1 step softer"


# ------------------------------------------------------------------ diff building
def test_plan_words():
    assert S.plan({"t": "TC2 (slip) one step up (in the car)"})["how"] == "1 step up"
    assert S.plan({"t": "FARB one step softer (in the car)"})["how"] == "1 step softer"
    assert S.plan({"t": "Brake bias 0.5% rearward"})["how"] == "0.5% rearward"
    p = S.plan({"t": "Brake bias 0.5–1% rearward"})
    assert p["amount"] is None and p["how"] == "0.5-1% rearward" and p["dir"] == -1
    assert S.plan({"t": "A little more rake: rear pushrod up a touch"})["how"] == "up a touch"
    assert S.plan({"t": "Brake migration one click more negative"})["dir"] == -1
    assert S.plan({"t": "Brake migration one click more positive (towards zero)"})["dir"] == +1
    assert S.plan({"t": "Two clicks stiffer HS comp"})["clicks"] == 2


def test_suggestion_from_my_style():
    sug = S.make_suggestion(CHANGES + [{"t": "Brake bias 0.5% rearward", "key": "bias", "why": "Front locks."},
                                       {"t": "Brake bias 0.5–1% rearward", "key": "bias", "why": "Front locks."},
                                       {"t": "More rear low-speed rebound", "key": None, "why": "Rear rises."},
                                       {"t": "Lower-friction brake pads", "key": None, "why": "Hard to modulate."},
                                       {"t": "Something the garage has no field for", "key": None}],
                            CS, "bmwlmdh", "BMW M Hybrid V8", "Le Mans", "Practice", "My style")
    c = sug["changes"]
    rake = c[0]["fields"]["Chassis.Rear.PushrodLengthOffset"]
    assert rake["before_txt"] == '-0.256"' and rake["sug_txt"] is None              # no exact step: direction only
    assert c[0]["how"] == "up a touch" and c[0]["reason"].startswith("Understeer mid-corner")
    tc = c[1]["fields"]["BrakesDriveUnit.TractionControl.TractionControlSlip"]
    assert (tc["before_txt"], tc["sug_txt"]) == ("5 (TCLON)", "6 (TCLON)")
    bias = c[2]["fields"]["BrakesDriveUnit.BrakeSpec.BrakePressureBias"]
    assert (bias["before_txt"], bias["sug_txt"]) == ("47.50%", "47.00%")
    assert c[3]["fields"]["BrakesDriveUnit.BrakeSpec.BrakePressureBias"]["sug_txt"] is None   # a range: no number
    assert set(c[4]["fields"]) == {"Chassis.LeftRear.LsRbdDamping", "Chassis.RightRear.LsRbdDamping"}
    assert c[5]["how"] == "Lower-friction brake pads"
    assert c[6]["fields"] == {}
    sh = S.sheet(sug)
    assert sh["items"][6]["state"] == "manual" and sh["unplaced"] == [6]
    ch = [f for t in sh["tabs"] for row in t["rows"] for s in row for f in s["fields"] if f.get("changed")]
    assert {f["label"] for f in ch} >= {"Pushrod length offset", "Traction control slip", "Brake pressure bias", "LS rbd damping", "Pad compound"}
    assert sh["total"] == 7 and sh["done"] == 0


# ------------------------------------------------------------------ auto-tick
def test_auto_tick_from_live_setup():
    sug = S.make_suggestion(CHANGES + [{"t": "Brake bias 0.5% rearward", "key": "bias", "why": "x"}], CS, "bmwlmdh", "BMW M Hybrid V8")
    live = copy.deepcopy(CS)
    assert [i["state"] for i in S.sheet(sug, live, "bmwlmdh")["items"]] == ["todo", "todo", "todo"]
    live["BrakesDriveUnit"]["TractionControl"]["TractionControlSlip"] = "6 (TCLON)"   # clicked up one
    live["Chassis"]["Rear"]["PushrodLengthOffset"] = "-7.5 mm"                          # moved DOWN: the wrong way
    live["BrakesDriveUnit"]["BrakeSpec"]["BrakePressureBias"] = "47.25%"                # not there yet
    sh = S.sheet(sug, live, "bmwlmdh")
    assert [i["state"] for i in sh["items"]] == ["check", "done", "todo"]
    assert sh["live_values"] is True
    live["Chassis"]["Rear"]["PushrodLengthOffset"] = "-5.0 mm"
    live["BrakesDriveUnit"]["BrakeSpec"]["BrakePressureBias"] = "47.00%"
    assert [i["state"] for i in S.sheet(sug, live, "bmwlmdh")["items"]] == ["done", "done", "done"]
    # the in-car BB knob counts too
    live["BrakesDriveUnit"]["BrakeSpec"]["BrakePressureBias"] = "47.50%"
    assert S.sheet(sug, live, "bmwlmdh", live_bias=47.0)["items"][2]["state"] == "done"
    # another car's live session is ignored
    assert S.sheet(sug, live, "porsche963gtp")["live_values"] is False


def test_store_push_history_ticks(tmp_path):
    st = S.Store(str(tmp_path / "s.json"))
    sug = S.make_suggestion(CHANGES, CS, "bmwlmdh", "BMW M Hybrid V8", "Le Mans")
    st.push(sug)
    live = copy.deepcopy(CS)
    live["BrakesDriveUnit"]["TractionControl"]["TractionControlSlip"] = "6 (TCLON)"
    v = S.view(st, None, live, "bmwlmdh")
    assert [i["state"] for i in v["items"]] == ["todo", "done"]
    v = S.view(st)                                                     # left the session: stays ticked
    assert [i["state"] for i in v["items"]] == ["todo", "done"] and v["live_values"] is False
    st.tick(sug["id"], 0, True)
    assert S.view(st)["done"] == 2
    st.tick(sug["id"], 1, False)                                       # untick by hand beats the auto tick
    assert S.view(st, None, live, "bmwlmdh")["items"][1]["state"] == "todo"
    for k in range(S.HISTORY + 3):
        s2 = S.make_suggestion(CHANGES[:1], CS, "bmwlmdh", "BMW M Hybrid V8")
        s2["id"] += f"-{k}"
        st.push(s2)
    h = st.history()
    assert len(h) == S.HISTORY and h[0]["current"] and h[0]["id"].endswith(f"-{S.HISTORY + 2}")
    assert S.same(S.make_suggestion(CHANGES, CS, "bmwlmdh"), S.make_suggestion(CHANGES, CS, "bmwlmdh"))
    assert not S.same(S.make_suggestion(CHANGES, CS, "bmwlmdh"), S.make_suggestion(CHANGES[:1], CS, "bmwlmdh"))


def test_meeting_text_and_advice():
    adv = [{"problem": "Oversteer / wheelspin on exit", "times": 4, "where": "Turn 1, Turn 9", "repeat": True,
            "first_fix": "TC2 (slip) one step up (in the car)", "why": "Steps in sooner.", "key": "tc2", "line": ""},
           {"problem": "Front wheels lock", "times": 1, "where": "Turn 5", "repeat": False, "line": ""}]
    ch = S.from_meeting(adv)
    assert len(ch) == 1 and ch[0]["key"] == "tc2" and ch[0]["why"].startswith("Oversteer / wheelspin on exit: 4 times")
    old = [dict(adv[0], key=None, first_fix="Brake bias 0.5% forward")]            # cached result without a key
    assert list(S.make_suggestion(S.from_meeting(old), CS, "bmwlmdh")["changes"][0]["fields"]) == ["BrakesDriveUnit.BrakeSpec.BrakePressureBias"]
    sug = S.make_suggestion(ch, CS, "bmwlmdh", "BMW M Hybrid V8", "Le Mans", source="Team meeting")
    L = S.meeting_lines(sug)
    assert L[0].startswith("1 setup change for the BMW M Hybrid V8 at Le Mans")
    assert "now 5 (TCLON), to 6 (TCLON)" in L[1]
    assert "on your iPad now" in L[-1]
    assert S.meeting_lines(None) == []


def test_ibt_header_reader(tmp_path):
    import struct
    si = ("---\nWeekendInfo:\n TrackDisplayName: Le Mans\nSessionInfo:\n Sessions:\n - SessionNum: 0\n   SessionType: Practice\n"
          " - SessionNum: 1\n   SessionType: Race\nCarSetup:\n Chassis:\n  Front:\n   ToeIn: -1.4 mm\n...\n").encode()
    head = struct.pack("<6i", 2, 1, 60, 0, len(si), 112) + b"\x00" * (112 - 24)
    p = tmp_path / "x.ibt"
    p.write_bytes(head + si)
    cs, info = S.ibt_setup(str(p))
    assert cs["Chassis"]["Front"]["ToeIn"] == "-1.4 mm"
    assert S.session_label(info) == "Practice / Race"
    assert S.session_label(info, [1]) == "Race"
