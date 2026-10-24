"""Off-track tests for the v62 calls (run: python -m engineer.tests.test_extras from the folder above engineer)."""
import os, sys, types, json

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
if "engineer" not in sys.modules:
    pkg = types.ModuleType("engineer"); pkg.__path__ = [PKG]; sys.modules["engineer"] = pkg
import tempfile
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="eng_test_")   # never touch the real marked-drivers file

from engineer.brain import Brain, Settings, F_GREEN
from engineer.voice import PRIO_URGENT
from engineer import lines_new

RENDERED = set(open(os.path.join(PKG, "tools", "sids_rendered.txt")).read().split()) if os.path.exists(
    os.path.join(PKG, "tools", "sids_rendered.txt")) else set()
NEW = lines_new.table()


class Clock:
    t = 1000.0
    def __call__(self):
        return self.t


class FakeIR:
    fake = True          # chat never types from tests

    def __init__(self):
        self.cmds, self.chats = [], []
    def pit_command(self, mode, var=0):
        try:
            import irsdk
            names = {v: k for k, v in vars(irsdk.PitCommandMode).items() if not k.startswith("_")}
            mode = names.get(mode, mode)
        except ImportError:
            pass
        self.cmds.append((mode, var))
    def chat_command(self, mode, *a):
        self.chats.append(mode)


class Src:
    def __init__(self):
        self.v = {}
        self.inf = {}
        self.ir = FakeIR()
    def __getitem__(self, k):
        return self.v.get(k)
    def info(self, sec):
        return self.inf.get(sec)


class FakeVoice:
    def __init__(self):
        self.said = []
        self.gtp = False
        self.fuel_metric = True
        self.last_said = None
        self.held = False
    def has(self, sid):
        return sid in RENDERED or sid in NEW or not RENDERED
    def say(self, sid, fills=None, prio=3, max_age=None):
        self.said.append((sid, dict(fills or {}), prio))
        if prio <= 3 and sid != "b2_repeat_last_message":
            self.last_said = (sid, fills)
    def hold(self, f):
        self.held = f
    def sids(self):
        return [s for s, _, _ in self.said]


class Corners:
    marks = []
    def at(self, *a, **k): return None
    def nearest_behind(self, *a): return None
    def next_after(self, *a): return None
    def set_track(self, *a): return 0


L = 5000.0


def setup(session="Race", n=6):
    clk, src, v = Clock(), Src(), FakeVoice()
    drivers = []
    for i in range(n):
        drivers.append(dict(CarIdx=i, CarNumber=str([28, 7, 91, 44, 25, 6][i] if i < 6 else 100 + i),
                            CarClassID=1 if i < 4 else 2, CarClassShortName="GT3" if i < 4 else "GTP",
                            CarPath="bmwm4gt3", CarClassEstLapTime=100.0 if i < 4 else 90.0,
                            IRating=[2000, 2500, 1500, 3000, 4000, 3500][i % 6], LicString=["A 3.41", "B 2.50", "D 1.20", "A 4.99", "A 4.0", "A 3.0"][i % 6],
                            UserID=1000 + i, UserName=f"Driver {i}", CurDriverIncidentCount=[0, 2, 9, 4, 0, 0][i % 6]))
    src.inf = {"DriverInfo": {"DriverCarIdx": 0, "Drivers": drivers, "DriverPitTrkPct": 0.10,
                              "DriverCarFuelMaxLtr": 100.0, "DriverCarMaxFuelPct": 1.0, "DriverCarSLShiftRPM": 7000,
                              "DriverCarGearNumForward": 6,
                              "DriverTires": [{"TireIndex": 0, "TireCompoundType": "Hard"}, {"TireIndex": 1, "TireCompoundType": "Wet"}]},
               "WeekendInfo": {"TrackName": "spa", "TrackLength": "5.00 km", "TrackPitSpeedLimit": "60.00 kph",
                               "WeekendOptions": {"IncidentLimit": "17"}},
               "SessionInfo": {"Sessions": [{"SessionNum": 0, "SessionType": session, "SessionLaps": "20",
                                             "SessionTrackRubberState": "low usage"}]}}
    src.v.update(SessionNum=0, SessionState=4, SessionFlags=F_GREEN, IsOnTrack=True, PlayerCarIdx=0, Speed=50.0,
                 OnPitRoad=False, DisplayUnits=1, TrackTempCrew=30.0, AirTemp=20.0, WindVel=2.0, LapDist=100.0, LapDistPct=0.5,
                 LapCompleted=5, LapLastLapTime=100.0, FuelLevel=50.0, SessionLapsRemainEx=15, SessionTimeRemain=-1,
                 PlayerCarMyIncidentCount=0, CarLeftRight=1, Brake=0.0, SteeringWheelAngle=0.0, EngineWarnings=0,
                 CarIdxClassPosition=[2, 1, 3, 4, 1, 2], CarIdxF2Time=[5.0, 0.0, 12.0, 40.0, 0.0, 3.0],
                 CarIdxLapDistPct=[0.5, 0.6, 0.45, 0.2, 0.9, 0.3], CarIdxTrackSurface=[3] * n, CarIdxOnPitRoad=[False] * n,
                 CarIdxLapCompleted=[5] * n, CarIdxLastLapTime=[100.0, 99.5, 101.0, 102.0, 90.0, 91.0],
                 CarIdxBestLapTime=[99.0, 98.7, 100.5, 101.5, 89.0, 89.5], SessionTime=5000.0, Throttle=1.0, ThrottleRaw=1.0,
                 WeatherDeclaredWet=False, PitRepairLeft=0.0, PitOptRepairLeft=0.0, PlayerCarInPitStall=False,
                 PlayerCarPitSvStatus=0, PitSvFlags=0, PitSvFuel=0.0, RPM=6500.0, PitSvLFP=170.0, PitSvRFP=170.0, PitSvLRP=165.0, PitSvRRP=165.0)
    s = Settings()
    b = Brain(src, v, Corners(), s, log=lambda *a: None, clock=clk)
    b.tick()
    b.green_seen = True
    b.sess_type = session
    b.lap_times = [100.0, 100.2, 99.8]
    b.fuel_laps = [3.0, 3.0, 3.0]
    v.said.clear()
    return b, src, v, clk


def step(b, clk, secs=0.5, n=1):
    for _ in range(n):
        clk.t += secs
        b.tick()


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        check.fails += 1
check.fails = 0


def t_pitlane():
    b, src, v, clk = setup()
    # coming in without the limiter
    src.v["CarIdxTrackSurface"] = [2, 3, 3, 3, 3, 3]; src.v["Speed"] = 40.0
    step(b, clk)
    check("limiter warning on pit approach", "limiter_on" in v.sids())
    # into the pit lane with the limiter on: no 'limiter on' reminder
    v.said.clear()
    src.v.update(OnPitRoad=True, EngineWarnings=0x10, Speed=16.0, CarIdxTrackSurface=[3] * 6)
    src.v["LapDistPct"] = 0.10 - 80 / L
    step(b, clk)
    check("no pit_entry reminder when limiter already on", "pit_entry" not in v.sids())
    check("stall coming up", "stall_close" in v.sids())
    # stop: 30 s repairs
    v.said.clear()
    src.v.update(PlayerCarInPitStall=True, PitRepairLeft=30.0, PlayerCarPitSvStatus=1, Speed=0.0, PitSvFlags=0x0F)
    step(b, clk, 0.5, 4)
    check("long repair call", "repair_long" in v.sids())
    for r in (10.2, 9.8, 5.3, 4.9, 0.0):
        src.v["PitRepairLeft"] = r; step(b, clk)
    src.v["PlayerCarPitSvStatus"] = 2; step(b, clk)
    check("repair countdown 10 and 5", [f["n"] for s, f, _ in v.said if s == "repair_left"] == [10, 5])
    check("release go go go", "stop_go_go" in v.sids())
    # leave the box and the pit lane with the limiter still on
    src.v.update(PlayerCarInPitStall=False, Speed=16.0); step(b, clk)
    src.v.update(OnPitRoad=False, Speed=30.0); step(b, clk, 1.0, 6)
    check("limiter still on after exit", "limiter_off" in v.sids())
    step(b, clk, 1.0, 8)
    check("stop time reported", "b2_stop_time" in v.sids())


def t_predict_exit():
    b, src, v, clk = setup()
    # me P2 GT3 at f2 5.0; #91 (P3) 7 s behind, #44 (P4) 35 s behind -> 1 car passes in a ~30 s stop
    src.v["PitSvFlags"] = 0x10; src.v["PitSvFuel"] = 10.0      # fuel only: ~32 s stop
    r = b.x.predict_exit(say=True)
    check("exit prediction P3", r is not None and r[0] == 3)
    check("exit prediction spoken", any(s in ("pit_out_behind", "pit_out_ahead", "pit_rejoin_pos") for s in v.sids()))


def t_requests():
    b, src, v, clk = setup()
    ir = src.ir
    def req(text):
        ir.cmds.clear(); v.said.clear()
        ok = b.x.command(text)
        return ok, list(ir.cmds), v.sids()
    ok, c, s = req("left side tyres only")
    check("left side tyres", ok and ("lf", 0) in c and ("lr", 0) in c and ("rf", 0) not in c and "req_tyres" in s)
    ok, c, s = req("change the fronts")
    check("front tyres", ok and ("lf", 0) in c and ("rf", 0) in c and ("lr", 0) not in c)
    ok, c, s = req("no tyres this stop")
    check("no tyres", ok and c == [("clear_tires", 0)])
    ok, c, s = req("add twenty litres of fuel")
    check("add 20 litres", ok and ("fuel", 20) in c)
    src.v["FuelLevel"] = 20.0
    ok, c, s = req("fuel to the end")
    check("fuel to the end", ok and any(m == "fuel" for m, _ in c) and "req_fuel_end" in s)
    ok, c, s = req("no fuel")
    check("no fuel", ok and ("clear_fuel", 0) in c)
    ok, c, s = req("fast repair please")
    check("fast repair", ok and ("fr", 0) in c)
    ok, c, s = req("tear off")
    check("tear off", ok and ("ws", 0) in c)
    ok, c, s = req("front pressures up one psi")
    check("front pressures +1 psi", ok and ("lf", 177) in c and ("rf", 177) in c and not any(m == "lr" for m, _ in c))
    ok, c, s = req("pressures down point five")
    check("all pressures -0.5 psi", ok and ("lr", 162) in c)
    ok, c, s = req("box for wets")
    check("wet tyres", ok and ("tc", 1) in c)
    ok, c, s = req("clear the pit menu")
    check("clear menu", ok and ("clear", 0) in c)
    ok, c, s = req("what's the weather like")
    check("not a pit request", not ok)
    # audit 2026-10-24: questions never touch the pit menu; polite orders still work; numbers
    for q in ("do we have enough fuel to finish", "do we need new tyres", "should we do four tyres",
              "is the fuel ok for 5 more laps"):
        ok, c, s = req(q)
        check(f"question not an order: {q}", not c)
    ok, c, s = req("can you give us four tyres")
    check("polite order works", ok and ("rr", 0) in c)
    ok, c, s = req("add one hundred and five litres")
    check("one hundred and five litres", ok and ("fuel", 105) in c)


def t_drivers():
    b, src, v, clk = setup()
    b.x.answer("sof")
    check("sof answer", v.said and v.said[-1][0] == "sof" and 1900 < v.said[-1][1]["n"] < 2600)
    b.x.answer("irating")
    check("irating answer", v.said[-1][0] in ("irating_gain", "irating_even"))
    b.x.answer("irating_target")
    check("irating target", v.said[-1][0] == "irating_target")
    b.x.answer("who_ahead")
    check("who ahead -> drv_info #7", v.said[-1][0] == "drv_info" and v.said[-1][1]["car"] == "7" and v.said[-1][1]["lic"] == "B")
    # mark the car behind (#91), then it gets close on track
    b.x.command("mark the car behind")
    check("mark car behind", v.said[-1][0] == "mark_ok" and v.said[-1][1]["car"] == "91")
    v.said.clear()
    src.v["CarIdxLapDistPct"] = [0.5, 0.6, 0.495, 0.2, 0.9, 0.3]
    step(b, clk, 0.5, 2)
    check("marked car nearby", "marked_near" in v.sids())
    b.x.command("unmark car 91")
    check("unmark", v.said[-1][0] == "unmark_ok")
    # low SR: #91 is D 1.20, right behind
    v.said.clear(); b.x.near_said.clear()
    step(b, clk, 0.5, 2)
    check("low safety rating warning", "low_sr_near" in v.sids())
    # keep me updated on car 7
    b.x.command("keep me updated on car seven")
    check("watch ok", v.said[-1][0] == "watch_ok")
    src.v["CarIdxLapCompleted"] = [5, 6, 5, 5, 5, 5]; step(b, clk, 0.5, 2)
    check("watch report", "watch_report" in v.sids())
    b.x.command("stop the updates")
    check("watch off", v.said[-1][0] == "watch_off")
    b.x.command("what was car forty four's last lap time")
    check("lap time of car 44", v.said[-1][0] == "car_lap" and v.said[-1][1]["car"] == "44")
    b.x.command("how many incidents does car 91 have")
    check("incidents of car 91", v.said[-1][0] == "car_inc" and v.said[-1][1]["n"] == 9)
    b.x.command("what's the iRating of the car ahead")
    check("iRating of car ahead", v.said[-1][0] == "drv_info")


def t_health():
    b, src, v, clk = setup()
    src.v["EngineWarnings"] = 0x01; step(b, clk)
    check("water temp", "engine_hot" in v.sids())
    src.v["EngineWarnings"] = 0x00; step(b, clk)
    check("engine ok again", "engine_ok" in v.sids())
    src.v["EngineWarnings"] = 0x04; step(b, clk)
    check("oil pressure", "oil_low" in v.sids())
    src.v["EngineWarnings"] = 0x06; step(b, clk)
    check("fuel pressure", "fuel_pressure" in v.sids())
    src.v["EngineWarnings"] = 0; src.v["Speed"] = 1.0; step(b, clk)
    src.v["EngineWarnings"] = 0x08; step(b, clk)
    check("stall", "stalled" in v.sids())
    src.v.update(EngineWarnings=0, Speed=50.0)
    src.v["PitRepairLeft"] = 12.0; step(b, clk)
    check("damage report after a hit", "damage_report" in v.sids())
    b.x.answer("damage")
    check("damage answer", v.said[-1][0] == "damage_report" and v.said[-1][1]["n"] == 12)
    src.v["PitRepairLeft"] = 0.0; step(b, clk)
    b.x.answer("damage")
    check("no damage answer", v.said[-1][0] == "car_fine")
    # pedal: brake + full throttle for >3 s
    src.v.update(Brake=0.5, BrakeRaw=0.5, ThrottleRaw=1.0); v.said.clear()
    b.s.hold_in_corners = False
    step(b, clk, 0.5, 9)
    check("pedal overlap", "pedal_stuck" in v.sids())


def t_fuel():
    b, src, v, clk = setup()
    # 15 laps to go at 3 L/lap = 45 L (+margin); 40 L in the tank, tank 100 -> window open, a stop needed
    src.v["FuelLevel"] = 40.0
    src.v["LapCompleted"] = 6; step(b, clk)
    check("fuel window open", "b2_pit_window_opens" in v.sids())
    # just short: 43 L for 15 laps -> target
    b2, src2, v2, clk2 = setup()
    src2.v["FuelLevel"] = 43.5
    b2.fuel_at_line = 46.5
    src2.v["LapCompleted"] = 6; step(b2, clk2)
    check("fuel target when just short", "fuel_target" in v2.sids())
    b2.x.answer("fuel_target")
    check("fuel target answer", v2.said[-1][0] == "fuel_target" and 2.5 < v2.said[-1][1]["dec"] < 3.0)


def t_practice():
    b, src, v, clk = setup(session="Practice")
    b.x.lap_kind = "out"
    src.v["CarIdxLapDistPct"] = [0.5, 0.6, 0.48, 0.2, 0.9, 0.3]
    step(b, clk)
    src.v["CarIdxLapDistPct"] = [0.5, 0.6, 0.4835, 0.2, 0.9, 0.3]   # #91 closing fast behind
    step(b, clk)
    check("push-lap car behind on my out lap", "b2_car_on_push_lap_behind_you" in v.sids())
    b.x.lap_kind = "push"; v.said.clear(); b.cool.clear()
    src.v["CarIdxLapDistPct"] = [0.5, 0.53, 0.3, 0.2, 0.9, 0.1]
    step(b, clk)
    src.v["CarIdxLapDistPct"] = [0.5, 0.526, 0.3, 0.2, 0.9, 0.1]     # I close on #7 ahead
    step(b, clk)
    check("traffic ahead on push lap", "b2_push_lap_traffic_ahead" in v.sids())
    src.inf["SessionInfo"]["Sessions"][0]["SessionTrackRubberState"] = "moderate usage"
    step(b, clk)
    check("track rubbering in", "b2_track_getting_faster_rubber" in v.sids())


def t_sectors_weather():
    b, src, v, clk = setup()
    # 4 clean laps of 33.3 s sectors, then a slow sector 2
    pct, st = 0.01, 5000.0
    src.v["LapDistPct"] = pct; src.v["SessionTime"] = st; step(b, clk)
    def run_sector(dur, to):
        src.v["SessionTime"] = src.v["SessionTime"] + dur
        src.v["LapDistPct"] = to
        step(b, clk)
    for lap in range(5):
        run_sector(33.3, 0.34); run_sector(33.3, 0.67)
        src.v["LapCompleted"] = 6 + lap
        run_sector(33.3, 0.01)
    v.said.clear()
    run_sector(33.3, 0.34); run_sector(34.2, 0.67)
    check("sector two loss", any(s == "sector_off" and f["sector"] == 2 and f["n"] == 9 for s, f, _ in v.said))
    # weather (baseline after the first minute on track)
    step(b, clk, 10.0, 8)
    src.v["TrackTempCrew"] = 34.0; clk.t += 20; step(b, clk); step(b, clk, 5.0, 2)
    check("track temp rising", "b2_track_temperature_rising" in v.sids())
    src.v["WindVel"] = 9.0; clk.t += 20; step(b, clk)
    check("strong wind", "wind_strong" in v.sids())
    b.x.answer("weather")
    check("weather answer", "air_temp" in v.sids())


def t_tyres():
    b, src, v, clk = setup()
    b.x.set_start_lap = 0
    src.v.update(LFwearL=0.80, LFwearM=0.78, LFwearR=0.79, RFwearL=0.9, RFwearM=0.9, RFwearR=0.9,
                 LRwearL=0.9, LRwearM=0.9, LRwearR=0.9, RRwearL=0.9, RRwearM=0.9, RRwearR=0.9, LapCompleted=10)
    b.x.tyre_stall()
    step(b, clk, 1.0, 5)
    check("wear learned (2.2 %/lap)", b.x.wear_rate and abs(b.x.wear_rate - 2.2) < 0.01)
    check("all good report at the stop", "b2_wear_report_all_good" in v.sids())
    b.x.set_start_lap = 10
    src.v["LapCompleted"] = 42; step(b, clk)
    check("critical wear warning", "tyres_critical" in v.sids())
    b.x.answer("tyres")
    check("tyre answer", "tyres_left" in v.sids() and "b2_laps_on_these_tires" in v.sids())


def t_radio():
    b, src, v, clk = setup()
    b.x.command("set a timer for two minutes")
    check("timer set", v.said[-1][0] == "timer_set")
    step(b, clk, 30.0, 5)
    check("timer done", "timer_done" in v.sids())
    b.x.command("remind me in three laps")
    src.v["LapCompleted"] = 8; step(b, clk)
    check("lap reminder", v.sids().count("timer_done") == 2)
    v.say("ans_position", {"P": 2}, 1)
    b.x.answer("say_again")
    check("say again", v.said[-2][0] == "b2_repeat_last_message" and v.said[-1][0] == "ans_position")
    b.x.answer("time_now")
    check("time of day", v.said[-1][0] == "time_now")
    b.x.command("send good luck")
    check("chat never types outside iRacing", v.said[-1][0] == "tb_no_data")
    b.x.answer("fastest")
    check("fastest car", v.said[-1][0] == "b2_who_is_fastest_right_now" and v.said[-1][1]["car"] == "7")
    b.x.answer("leader_gap")
    check("gap to class leader", v.said[-1][0] == "b2_gap_to_the_class_leader" and abs(v.said[-1][1]["gap"] - 5.0) < 0.01)
    # brain.answer falls through to extras
    b.answer("sof")
    check("brain routes new intents", v.said[-1][0] == "sof")


def t_hold():
    b, src, v, clk = setup(session="Practice")
    src.v["Brake"] = 0.6; step(b, clk)
    check("engineer holds while braking in practice too", v.held)
    src.v["Brake"] = 0.0; step(b, clk)
    check("released on the straight", not v.held)


def t_no_false_alarms_parked():
    """Engine off in the garage: every warning light is on. No health calls until the car has been driven."""
    b, src, v, clk = setup()
    b.x.moving_t = -1e9
    src.v.update(Speed=0.0, RPM=0.0, EngineWarnings=0x0F)
    step(b, clk, 0.5, 6)
    check("no oil/fuel/stall calls with the engine off", not {"oil_low", "fuel_pressure", "stalled", "engine_hot"} & set(v.sids()))


def t_lines_complete():
    """Every line the new code can say exists (recorded or in the new-lines list)."""
    import re as _re
    src_txt = open(os.path.join(PKG, "extras.py"), encoding="utf-8").read()
    used = set(_re.findall(r'say\("([a-z0-9_]+)"', src_txt)) | set(_re.findall(r'"(b2_[a-z0-9_]+)"', src_txt))
    used |= set(_re.findall(r'self\.say\(\s*"([a-z0-9_]+)"', src_txt))
    missing = sorted(s for s in used if s not in RENDERED and s not in NEW)
    check("every line exists " + (str(missing) if missing else ""), not missing)
    fills_ok = True
    for sid, texts in NEW.items():
        for t in texts:
            for f in _re.findall(r"\[([^\]]+)\]", t):
                if f not in ("P", "car", "n", "gap", "time", "dec", "lic", "fuel unit", "speed unit", "percent", "laps", "sector"):
                    fills_ok = False; print("  unknown fill", sid, f)
    check("all fills known", fills_ok)


def t_say_list():
    """Every phrase on Settings > Calls > What you can say gets a real answer (same route as the radio)."""
    import re as _re
    from engineer.intents import understand
    html = open(os.path.join(PKG, "ui", "index.html"), encoding="utf-8").read()
    block = html[html.index('class="say-list"'):html.index("</div>\n        </div>\n      </div>", html.index('class="say-list"'))]
    phrases = _re.findall(r'"([^"]+)"', block.replace('class="say-list"', ""))
    bad = []
    for ph in phrases:
        b, src, v, clk = setup()
        b.x.pit_exit_t = None
        if not b.x.command(ph):
            intent, _ = understand(ph)
            if intent in ("pit_plan", "rain", "strategy", "meeting"):
                continue                      # handled by the pit crew / strategist in the app
            if intent is None or not b.answer(intent) and not v.said:
                bad.append((ph, intent)); continue
        if not v.said or v.said[-1][0] == "ans_didnt_catch":
            bad.append((ph, v.sids()))
    check(f"all {len(phrases)} phrases answered " + (str(bad) if bad else ""), not bad)


def t_settings():
    b, src, v, clk = setup()
    b.s.chat_enabled = False
    check("chat off: nothing typed", not b.x.command("send good luck"))
    b.s.chat_enabled = True
    b.s.press_unit, b.s.press_step = "kpa", 3.0
    src.ir.cmds.clear(); b.x.command("front pressures up one")
    check("pressure step 3 kPa", ("lf", 173) in src.ir.cmds)
    src.ir.cmds.clear(); b.x.command("front pressures up one psi")
    check("explicit psi still psi", ("lf", 177) in src.ir.cmds)
    b.s.press_unit, b.s.press_step = "psi", 0.5
    src.ir.cmds.clear(); b.x.command("rear pressures down two")
    check("pressure step 0.5 psi x2", ("lr", 158) in src.ir.cmds)
    # low SR threshold: #91 is D 1.20 -> off when rookies off and threshold 1.0
    b.s.low_sr_rookies, b.s.low_sr_below = False, 1.0
    src.v["CarIdxLapDistPct"] = [0.5, 0.6, 0.495, 0.2, 0.9, 0.3]
    v.said.clear(); step(b, clk, 0.5, 2)
    check("low SR threshold respected", "low_sr_near" not in v.sids())
    b.s.low_sr_below = 1.5; b.x.near_said.clear(); v.said.clear(); step(b, clk, 0.5, 2)
    check("low SR threshold 1.5 warns for SR 1.2", "low_sr_near" in v.sids())
    # marks shared with the settings screen
    from engineer import extras as X
    b.x.command("mark car 44")
    check("mark visible to settings", any(m.get("car") == "44" for m in X.marks().values()))
    uid = next(k for k, m in X.marks().items() if m.get("car") == "44")
    X.marks().pop(uid); X.save_marks()
    check("removed from settings -> brain sees it", not b.x.is_marked(b.drivers()[3]))


if __name__ == "__main__":
    for t in (t_settings, t_no_false_alarms_parked, t_say_list, t_pitlane, t_predict_exit, t_requests, t_drivers, t_health, t_fuel, t_practice, t_sectors_weather, t_tyres,
              t_radio, t_hold, t_lines_complete):
        print(f"--- {t.__name__}")
        t()
    print(f"\n{check.fails} failed")
    sys.exit(1 if check.fails else 0)
