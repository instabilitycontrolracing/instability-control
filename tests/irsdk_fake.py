"""A fake iRacing shared-memory file, read by the REAL pyirsdk (IRSDK.startup(test_file=...)).

Efficiency work (2026-10-29): the engineer's per-tick cost is mostly Python overhead around pyirsdk reads and the
session-info YAML. To measure it honestly the benchmark (tools/bench_engine.py) and the tests drive the real pyirsdk code
paths: this module writes a file in iRacing's memory-map layout (header, variable headers, three rotating data buffers,
the session-info YAML text) and a SyntheticRace that animates a 40-car multiclass race into it.

Nothing here runs in the app.
"""
import math, mmap, os, random, struct

import yaml

# irsdk var types
T_CHAR, T_BOOL, T_INT, T_BITS, T_FLOAT, T_DOUBLE = 0, 1, 2, 3, 4, 5
_FMT = {T_CHAR: "c", T_BOOL: "?", T_INT: "i", T_BITS: "I", T_FLOAT: "f", T_DOUBLE: "d"}
_SZ = {T_CHAR: 1, T_BOOL: 1, T_INT: 4, T_BITS: 4, T_FLOAT: 4, T_DOUBLE: 8}
N_CARS = 64

# (name, type, count) - the variables the engineer reads, with iRacing's types
VARS = [
    ("SessionTime", T_DOUBLE, 1), ("SessionTick", T_INT, 1), ("SessionNum", T_INT, 1), ("SessionState", T_INT, 1),
    ("SessionFlags", T_BITS, 1), ("SessionTimeRemain", T_DOUBLE, 1), ("SessionTimeTotal", T_DOUBLE, 1),
    ("SessionLapsRemainEx", T_INT, 1), ("SessionTimeOfDay", T_FLOAT, 1), ("SessionInfoUpdate", T_INT, 1),
    ("PlayerCarIdx", T_INT, 1), ("PlayerCarClassPosition", T_INT, 1), ("PlayerCarMyIncidentCount", T_INT, 1),
    ("PlayerCarInPitStall", T_BOOL, 1), ("PlayerCarPitSvStatus", T_INT, 1), ("PlayerTrackSurface", T_INT, 1),
    ("PlayerTrackSurfaceMaterial", T_INT, 1), ("PlayerTireCompound", T_INT, 1), ("PlayerFastRepairsUsed", T_INT, 1),
    ("IsOnTrack", T_BOOL, 1), ("IsOnTrackCar", T_BOOL, 1), ("IsReplayPlaying", T_BOOL, 1), ("IsDiskLoggingEnabled", T_BOOL, 1),
    ("IsDiskLoggingActive", T_BOOL, 1), ("ReplayPlaySpeed", T_INT, 1), ("ReplayPlaySlowMotion", T_BOOL, 1),
    ("OnPitRoad", T_BOOL, 1), ("Speed", T_FLOAT, 1), ("RPM", T_FLOAT, 1), ("Gear", T_INT, 1), ("Throttle", T_FLOAT, 1),
    ("ThrottleRaw", T_FLOAT, 1), ("Brake", T_FLOAT, 1), ("BrakeRaw", T_FLOAT, 1), ("Clutch", T_FLOAT, 1),
    ("BrakeABSactive", T_BOOL, 1), ("SteeringWheelAngle", T_FLOAT, 1), ("Lap", T_INT, 1), ("LapCompleted", T_INT, 1),
    ("LapDist", T_FLOAT, 1), ("LapDistPct", T_FLOAT, 1), ("LapCurrentLapTime", T_FLOAT, 1), ("LapLastLapTime", T_FLOAT, 1),
    ("LapBestLapTime", T_FLOAT, 1), ("LapDeltaToBestLap", T_FLOAT, 1), ("LapDeltaToBestLap_OK", T_BOOL, 1),
    ("Lat", T_DOUBLE, 1), ("Lon", T_DOUBLE, 1), ("Alt", T_FLOAT, 1), ("LatAccel", T_FLOAT, 1), ("LongAccel", T_FLOAT, 1),
    ("VertAccel", T_FLOAT, 1), ("YawRate", T_FLOAT, 1), ("VelocityX", T_FLOAT, 1), ("VelocityY", T_FLOAT, 1),
    ("FuelLevel", T_FLOAT, 1), ("WaterTemp", T_FLOAT, 1), ("OilTemp", T_FLOAT, 1), ("OilPress", T_FLOAT, 1),
    ("OilLevel", T_FLOAT, 1), ("WaterLevel", T_FLOAT, 1), ("Voltage", T_FLOAT, 1), ("EngineWarnings", T_BITS, 1),
    ("EnergyERSBatteryPct", T_FLOAT, 1), ("CarLeftRight", T_INT, 1), ("CarDistAhead", T_FLOAT, 1), ("CarDistBehind", T_FLOAT, 1),
    ("DisplayUnits", T_INT, 1), ("TrackTemp", T_FLOAT, 1), ("TrackTempCrew", T_FLOAT, 1), ("AirTemp", T_FLOAT, 1),
    ("TrackWetness", T_INT, 1), ("WeatherDeclaredWet", T_BOOL, 1), ("Precipitation", T_FLOAT, 1), ("Skies", T_INT, 1),
    ("WindVel", T_FLOAT, 1), ("WindDir", T_FLOAT, 1), ("RelativeHumidity", T_FLOAT, 1), ("AirPressure", T_FLOAT, 1),
    ("SolarAltitude", T_FLOAT, 1), ("CamCarIdx", T_INT, 1), ("CamGroupNumber", T_INT, 1), ("CamCameraNumber", T_INT, 1),
    ("RadioTransmitCarIdx", T_INT, 1), ("ChanLatency", T_FLOAT, 1), ("ChanQuality", T_FLOAT, 1),
    ("PitSvFlags", T_BITS, 1), ("PitSvFuel", T_FLOAT, 1), ("PitSvTireCompound", T_INT, 1), ("PitRepairLeft", T_FLOAT, 1),
    ("PitOptRepairLeft", T_FLOAT, 1), ("FastRepairUsed", T_INT, 1),
    ("dcBrakeBias", T_FLOAT, 1), ("dcABS", T_FLOAT, 1), ("dcTractionControl", T_FLOAT, 1), ("dcTractionControl2", T_FLOAT, 1),
    ("dcAntiRollFront", T_FLOAT, 1), ("dcAntiRollRear", T_FLOAT, 1), ("dcBrakeMisc", T_FLOAT, 1), ("dcThrottleShape", T_FLOAT, 1),
    ("LFpressure", T_FLOAT, 1), ("RFpressure", T_FLOAT, 1), ("LRpressure", T_FLOAT, 1), ("RRpressure", T_FLOAT, 1),
    ("LFrideHeight", T_FLOAT, 1), ("RFrideHeight", T_FLOAT, 1), ("LRrideHeight", T_FLOAT, 1), ("RRrideHeight", T_FLOAT, 1),
    ("LFshockDefl", T_FLOAT, 1), ("RFshockDefl", T_FLOAT, 1), ("LRshockDefl", T_FLOAT, 1), ("RRshockDefl", T_FLOAT, 1),
    ("TireLF_RumblePitch", T_FLOAT, 1), ("TireRF_RumblePitch", T_FLOAT, 1), ("TireLR_RumblePitch", T_FLOAT, 1),
    ("TireRR_RumblePitch", T_FLOAT, 1),
    ("CarIdxLap", T_INT, N_CARS), ("CarIdxLapCompleted", T_INT, N_CARS), ("CarIdxLapDistPct", T_FLOAT, N_CARS),
    ("CarIdxTrackSurface", T_INT, N_CARS), ("CarIdxOnPitRoad", T_BOOL, N_CARS), ("CarIdxPosition", T_INT, N_CARS),
    ("CarIdxClassPosition", T_INT, N_CARS), ("CarIdxF2Time", T_FLOAT, N_CARS), ("CarIdxEstTime", T_FLOAT, N_CARS),
    ("CarIdxLastLapTime", T_FLOAT, N_CARS), ("CarIdxBestLapTime", T_FLOAT, N_CARS), ("CarIdxBestLapNum", T_INT, N_CARS),
    ("CarIdxGear", T_INT, N_CARS), ("CarIdxRPM", T_FLOAT, N_CARS), ("CarIdxSteer", T_FLOAT, N_CARS),
    ("CarIdxSessionFlags", T_BITS, N_CARS), ("CarIdxTireCompound", T_INT, N_CARS),
]

HDR_SIZE = 112
VH_SIZE = 144
SI_CAP = 768 * 1024


class FakeIRFile:
    """Writes iRacing's memory-map layout into a file pyirsdk can open with startup(test_file=path)."""

    def __init__(self, path, vars=VARS, num_buf=3):
        self.path = path
        self.vars = {}
        off = 0
        for name, t, n in vars:
            self.vars[name] = (t, n, off, struct.Struct("<" + _FMT[t] * n))
            off += _SZ[t] * n
            off = (off + 3) // 4 * 4
        self.buf_len = (off + 15) // 16 * 16
        self.num_buf = num_buf
        self.vh_off = HDR_SIZE
        self.si_off = self.vh_off + VH_SIZE * len(vars)
        self.buf0 = (self.si_off + SI_CAP + 4095) // 4096 * 4096
        size = self.buf0 + self.buf_len * num_buf
        with open(path, "wb") as f:
            f.truncate(size)
        self.f = open(path, "r+b")
        self.mm = mmap.mmap(self.f.fileno(), size)
        self.si_update = 0
        self.tick = 0
        self.cur = 0
        struct.pack_into("<iiiiiiiiii", self.mm, 0, 2, 1, 60, 0, 0, self.si_off, len(vars), self.vh_off, num_buf, self.buf_len)
        for i in range(num_buf):
            struct.pack_into("<ii", self.mm, 48 + i * 16, 0, self.buf0 + i * self.buf_len)
        for i, (name, t, n) in enumerate(vars):
            o = self.vh_off + i * VH_SIZE
            struct.pack_into("<iii?", self.mm, o, t, self.vars[name][2], n, False)
            struct.pack_into("32s", self.mm, o + 16, name.encode())
        self.values = {name: ([0] * n if n > 1 else 0) for name, t, n in vars}

    def set_session_info(self, text):
        b = text.encode("latin-1", "replace")[:SI_CAP - 1]
        self.mm[self.si_off:self.si_off + len(b)] = b
        self.mm[self.si_off + len(b):self.si_off + len(b) + 1] = b"\x00"
        self.si_update += 1
        struct.pack_into("<iii", self.mm, 12, self.si_update, len(b) + 1, self.si_off)
        self.values["SessionInfoUpdate"] = self.si_update

    def commit(self):
        """Write self.values into the next buffer and mark it newest (like the sim does 60 times a second)."""
        self.tick += 1
        self.cur = (self.cur + 1) % self.num_buf
        base = self.buf0 + self.cur * self.buf_len
        for name, (t, n, off, st) in self.vars.items():
            v = self.values[name]
            if t == T_CHAR:
                continue
            if n == 1:
                st.pack_into(self.mm, base + off, v)
            else:
                st.pack_into(self.mm, base + off, *v)
        struct.pack_into("<i", self.mm, 48 + self.cur * 16, self.tick)

    def close(self):
        try:
            self.mm.close(); self.f.close()
        except Exception:
            pass


def ir_from_file(path):
    """A real pyirsdk IRSDK reading the fake file."""
    import irsdk
    ir = irsdk.IRSDK()
    assert ir.startup(test_file=path)
    return ir


def _dump_section(name, data):
    return yaml.safe_dump({name: data}, default_flow_style=False, sort_keys=False, allow_unicode=False, width=1000)


class SyntheticRace:
    """A 40-car multiclass race (10 GTP + 30 GT3, us in a GT3) on a 5 km track, deterministic (seeded).

    Story: formation 30 s, green, a timed race; we pit once, a local yellow, a couple of incidents, side-by-side moments.
    Every lap crossing of any car updates the session-info results (SessionInfoUpdate++), like the real sim.
    """
    TRACK_M = 5000.0
    FORM_S = 30.0

    def __init__(self, fake, seed=7, race_s=1500.0, n_gtp=10, n_gt3=30, me=20):
        self.f, self.rng = fake, random.Random(seed)
        self.race_s = race_s
        self.me = me
        self.cars = []
        for i in range(1, 1 + n_gtp + n_gt3):
            gtp = i <= n_gtp
            base = 92.0 if gtp else 101.0
            self.cars.append({"idx": i, "gtp": gtp, "lap_t": base * (1 + self.rng.uniform(-0.015, 0.015)),
                              "start": -(i * 18.0), "pit_lap": self.rng.choice([5, 6, 7, 8]), "laps": 0, "best": 0.0,
                              "last": -1.0, "prog": 0.0, "pit_until": None})
        self.t = 0.0
        self.fuel = 60.0
        self.inc = 0
        self.results_dirty = True
        self._di = self._driver_info()
        self._wk = self._weekend()
        self._write_si()

    # ---------------------------------------------------------- session info
    def _driver_info(self):
        drv = [{"CarIdx": 0, "UserName": "Pace Car", "CarIsPaceCar": 1, "IsSpectator": 0, "CarNumber": "0",
                "CarClassID": 11, "CarClassShortName": "", "CarPath": "safety pcporsche911cup", "CarScreenName": "safety car"}]
        for c in self.cars:
            i = c["idx"]
            drv.append({"CarIdx": i, "UserName": f"Driver {i}", "AbbrevName": f"D, {i}", "Initials": "DD", "UserID": 100000 + i,
                        "TeamName": f"Team {i}", "CarNumber": str(i + 10), "CarNumberRaw": i + 10, "CarIsPaceCar": 0, "IsSpectator": 0,
                        "CarClassID": 4029 if c["gtp"] else 4083, "CarClassShortName": "GTP" if c["gtp"] else "GT3",
                        "CarClassColor": 0xFFDA59 if c["gtp"] else 0x33CEFF, "CarClassEstLapTime": c["lap_t"],
                        "CarPath": "bmwlmdh" if c["gtp"] else "bmwm4gt3",
                        "CarScreenName": "BMW M Hybrid V8" if c["gtp"] else "BMW M4 GT3 EVO",
                        "CarScreenNameShort": "BMW GTP" if c["gtp"] else "BMW M4 GT3", "IRating": 1500 + i * 37,
                        "LicString": "A 3.21", "LicLevel": 18, "CurDriverIncidentCount": 0, "TeamIncidentCount": 0})
        return {"DriverCarIdx": self.me, "DriverUserID": 100000 + self.me, "PaceCarIdx": 0, "DriverCarRedLine": 7400.0,
                "DriverCarSLShiftRPM": 7000.0, "DriverCarFuelMaxLtr": 120.0, "DriverCarFuelKgPerLtr": 0.75,
                "DriverCarEstLapTime": 101.0, "DriverSetupName": "baseline.sto", "Drivers": drv}

    def _weekend(self):
        return {"TrackName": "synthring", "TrackID": 999, "TrackLength": "5.00 km", "TrackDisplayName": "Synthetic Ring",
                "TrackDisplayShortName": "Synth", "TrackConfigName": "GP", "TrackCity": "Nowhere", "TrackCountry": "USA",
                "TrackPitSpeedLimit": "60.00 kph", "TrackNumTurns": 14, "SeriesID": 1, "SeasonID": 1, "SessionID": 5,
                "SubSessionID": 4242, "Official": 1, "EventType": "Race", "Category": "Road", "NumCarClasses": 2,
                "WeekendOptions": {"NumStarters": 40, "IncidentLimit": "17", "FastRepairsLimit": "1", "StandingStart": 0},
                "TelemetryOptions": {"TelemetryDiskFile": ""}}

    def _results(self):
        order = sorted(self.cars, key=lambda c: -self._progress(c))
        rp = []
        cls_n = {True: 0, False: 0}
        for p, c in enumerate(order, 1):
            cls_n[c["gtp"]] += 1
            rp.append({"Position": p, "ClassPosition": cls_n[c["gtp"]] - 1, "CarIdx": c["idx"], "Lap": c["laps"],
                       "Time": round(max(0.0, self.t - self.FORM_S), 4), "FastestLap": 0, "FastestTime": round(c["best"], 4),
                       "LastTime": round(c["last"], 4), "LapsLed": 0, "LapsComplete": c["laps"], "JokerLapsComplete": 0,
                       "LapsDriven": round(self._progress(c), 3), "Incidents": 0, "ReasonOutId": 0, "ReasonOutStr": "Running"})
        return rp

    def _write_si(self):
        si = {"Sessions": [
            {"SessionNum": 0, "SessionLaps": "unlimited", "SessionTime": f"{self.race_s + self.FORM_S:.4f} sec",
             "SessionType": "Race", "SessionName": "RACE", "SessionTrackRubberState": "moderate usage",
             "ResultsPositions": self._results(), "ResultsFastestLap": [{"CarIdx": 1, "FastestLap": 2, "FastestTime": 91.2}],
             "ResultsAverageLapTime": -1.0, "ResultsNumCautionFlags": 0, "ResultsNumCautionLaps": 0,
             "ResultsNumLeadChanges": 0, "ResultsLapsComplete": -1, "ResultsOfficial": 0}]}
        cam = {"Groups": [{"GroupNum": 1, "GroupName": "Nose", "Cameras": [{"CameraNum": 1, "CameraName": "CamNose"}]},
                          {"GroupNum": 2, "GroupName": "Cockpit", "Cameras": [{"CameraNum": 1, "CameraName": "CamCockpit"}]},
                          {"GroupNum": 3, "GroupName": "TV1", "Cameras": [{"CameraNum": 1, "CameraName": "CamTV1"}]}]}
        text = "---\n" + "\n".join([_dump_section("WeekendInfo", self._wk), _dump_section("SessionInfo", si),
                                     _dump_section("CameraInfo", cam), _dump_section("DriverInfo", self._di),
                                     _dump_section("SplitTimeInfo", {"Sectors": [{"SectorNum": 0, "SectorStartPct": 0.0},
                                                                                 {"SectorNum": 1, "SectorStartPct": 0.33},
                                                                                 {"SectorNum": 2, "SectorStartPct": 0.66}]})]) + "\n...\n"
        self.f.set_session_info(text)
        self.results_dirty = False

    # ---------------------------------------------------------- motion
    def _progress(self, c):
        return c["prog"]

    def _speed_at(self, pct, base):
        # a lap with 6 corners: slow at the corners, fast in between
        return base * (0.72 + 0.28 * math.cos(pct * 2 * math.pi * 6) ** 2)

    def advance(self, dt):
        self.t += dt
        race_t = self.t - self.FORM_S
        green = race_t >= 0
        for c in self.cars:
            lap_t = c["lap_t"] * (1.06 if not green else 1.0)
            if c["pit_until"] is not None:
                if self.t >= c["pit_until"]:
                    c["pit_until"] = None
                else:
                    c["prog"] += dt / (lap_t * 2.2)
                    continue
            if self.t < self.FORM_S:
                c["prog"] = (c["start"] / (lap_t * 60)) + self.t / (lap_t * 1.5)
                continue
            before = int(c["prog"])
            c["prog"] += dt / lap_t * (1 + 0.01 * math.sin(self.t / 37.0 + c["idx"]))
            if int(c["prog"]) > before and c["prog"] > 0:
                lt = lap_t * (1 + self.rng.uniform(-0.004, 0.006))
                c["laps"] = int(c["prog"])
                c["last"] = lt
                c["best"] = lt if c["best"] <= 0 else min(c["best"], lt)
                self.results_dirty = True
                if c["laps"] == c["pit_lap"]:
                    c["pit_until"] = self.t + 38.0
        if self.results_dirty:
            self._write_si()
        self._write_vars()
        self.f.commit()

    def _write_vars(self):
        v = self.f.values
        t = self.t
        race_t = t - self.FORM_S
        green = race_t >= 0
        me = next(c for c in self.cars if c["idx"] == self.me)
        order = sorted(self.cars, key=lambda c: -c["prog"])
        pos = {c["idx"]: p for p, c in enumerate(order, 1)}
        cpos, n = {}, {True: 0, False: 0}
        for c in order:
            n[c["gtp"]] += 1
            cpos[c["idx"]] = n[c["gtp"]]
        leader = order[0]
        v["SessionTime"] = t
        v["SessionTick"] = int(t * 60)
        v["SessionNum"] = 0
        state = 3 if not green else (4 if race_t < self.race_s else 5)
        v["SessionState"] = state
        flags = 0x4 if green else 0x0
        if green and 400 < race_t < 425:
            flags |= 0x8 | 0x100                     # local yellow, waving
        if green and race_t >= self.race_s - leader["lap_t"]:
            flags |= 0x2
        if state == 5:
            flags |= 0x1
        v["SessionFlags"] = flags
        v["SessionTimeTotal"] = self.race_s + self.FORM_S
        v["SessionTimeRemain"] = max(0.0, self.race_s + self.FORM_S - t)
        v["SessionLapsRemainEx"] = 32767
        v["SessionTimeOfDay"] = 50400 + t
        v["PlayerCarIdx"] = self.me
        pct = me["prog"] % 1.0
        in_pit = me["pit_until"] is not None
        lt = me["lap_t"]
        spd = (16.6 if in_pit else self._speed_at(pct, self.TRACK_M / lt * 1.25))
        v["Speed"] = spd
        v["IsOnTrack"] = True; v["IsOnTrackCar"] = True; v["IsReplayPlaying"] = False
        v["IsDiskLoggingEnabled"] = True; v["IsDiskLoggingActive"] = True
        v["ReplayPlaySpeed"] = 1
        v["OnPitRoad"] = in_pit
        v["PlayerCarInPitStall"] = in_pit and (me["pit_until"] - t) < 30
        v["PlayerCarClassPosition"] = cpos[self.me]
        corner = math.cos(pct * 2 * math.pi * 6) ** 2 < 0.25
        v["Brake"] = 0.7 if corner and not in_pit else 0.0
        v["BrakeRaw"] = v["Brake"]
        v["Throttle"] = 0.2 if corner else 1.0
        v["ThrottleRaw"] = v["Throttle"]
        v["SteeringWheelAngle"] = 0.6 * math.sin(pct * 2 * math.pi * 6) if corner else 0.02
        v["Gear"] = 3 if corner else 6
        v["RPM"] = 5200.0 + 1500 * v["Throttle"]
        v["Lap"] = max(0, int(me["prog"])) + 1
        v["LapCompleted"] = max(0, int(me["prog"]))
        v["LapDist"] = pct * self.TRACK_M
        v["LapDistPct"] = pct
        v["LapCurrentLapTime"] = pct * lt
        v["LapLastLapTime"] = me["last"]
        v["LapBestLapTime"] = me["best"]
        v["LapDeltaToBestLap"] = 0.12 * math.sin(t / 9.0)
        v["LapDeltaToBestLap_OK"] = me["best"] > 0
        v["Lat"] = 45.0 + 0.01 * math.cos(pct * 2 * math.pi); v["Lon"] = 7.0 + 0.01 * math.sin(pct * 2 * math.pi)
        v["LatAccel"] = 12.0 * v["SteeringWheelAngle"]; v["LongAccel"] = -14.0 * v["Brake"] + 3.0 * v["Throttle"]
        v["VertAccel"] = 9.81 + 0.5 * math.sin(t * 13)
        v["YawRate"] = 0.4 * v["SteeringWheelAngle"]
        v["VelocityX"] = spd; v["VelocityY"] = 0.0
        if green:
            self.fuel = max(0.5, self.fuel - (2.6 / lt) * (1 / 15))
        if in_pit and v["PlayerCarInPitStall"]:
            self.fuel = min(110.0, self.fuel + 0.5)
        v["FuelLevel"] = self.fuel
        v["WaterTemp"] = 88.0; v["OilTemp"] = 101.0; v["OilPress"] = 5.1; v["OilLevel"] = 9.0; v["WaterLevel"] = 9.0
        v["Voltage"] = 13.8
        v["EngineWarnings"] = 0x10 if in_pit else 0
        v["DisplayUnits"] = 1
        v["TrackTemp"] = 31.0; v["TrackTempCrew"] = 31.0; v["AirTemp"] = 22.0; v["TrackWetness"] = 1
        v["WindVel"] = 2.0; v["WindDir"] = 1.0; v["RelativeHumidity"] = 0.5; v["AirPressure"] = 101.0
        v["SolarAltitude"] = 0.6; v["Skies"] = 1
        v["CamCarIdx"] = self.me; v["CamGroupNumber"] = 2; v["CamCameraNumber"] = 1
        v["RadioTransmitCarIdx"] = -1
        if green and 300 < race_t < 302:
            self.inc = 2
        if green and 900 < race_t < 902:
            self.inc = 4
        v["PlayerCarMyIncidentCount"] = self.inc
        v["PlayerTrackSurface"] = 3 if not in_pit else 2
        for k, val in (("dcBrakeBias", 52.5), ("dcABS", 4.0), ("dcTractionControl", 3.0), ("dcTractionControl2", 2.0),
                       ("dcAntiRollFront", 3.0), ("dcAntiRollRear", 2.0), ("dcBrakeMisc", 1.0), ("dcThrottleShape", 1.0)):
            v[k] = val
        for k in ("LF", "RF", "LR", "RR"):
            v[k + "pressure"] = 172.0
        # who's alongside: any car within 6 m of us
        me_d = me["prog"] * self.TRACK_M
        lr = 1
        near = [c for c in self.cars if c is not me and abs(c["prog"] * self.TRACK_M - me_d) < 6.0]
        if len(near) >= 2:
            lr = 4
        elif near:
            lr = 2 if near[0]["idx"] % 2 else 3
        v["CarLeftRight"] = lr if green else 1
        ahead = [c["prog"] * self.TRACK_M - me_d for c in self.cars if c["prog"] * self.TRACK_M > me_d]
        v["CarDistAhead"] = min(ahead) if ahead else 0.0
        arr = lambda d: [d] * N_CARS
        lap, lapc, lp, ts, onp = arr(-1), arr(-1), arr(-1.0), arr(-1), arr(False)
        ps, cps, f2, est, last, best, bln, gear = arr(0), arr(0), arr(0.0), arr(0.0), arr(-1.0), arr(-1.0), arr(-1), arr(-1)
        for c in self.cars:
            i = c["idx"]
            lap[i] = max(0, int(c["prog"])) + 1; lapc[i] = max(0, int(c["prog"])); lp[i] = c["prog"] % 1.0
            ts[i] = 2 if c["pit_until"] is not None else 3
            onp[i] = c["pit_until"] is not None
            ps[i], cps[i] = pos[i], cpos[i]
            f2[i] = 0.0 if pos[i] == 1 else (leader["prog"] - c["prog"]) * c["lap_t"]
            est[i] = (c["prog"] % 1.0) * c["lap_t"]
            last[i], best[i] = c["last"], (c["best"] if c["best"] > 0 else -1.0)
            bln[i] = max(1, c["laps"]) if c["best"] > 0 else -1
            gear[i] = 5
        lp[0] = (leader["prog"] + 0.5) % 1.0; ts[0] = 3
        v["CarIdxLap"], v["CarIdxLapCompleted"], v["CarIdxLapDistPct"], v["CarIdxTrackSurface"] = lap, lapc, lp, ts
        v["CarIdxOnPitRoad"], v["CarIdxPosition"], v["CarIdxClassPosition"], v["CarIdxF2Time"] = onp, ps, cps, f2
        v["CarIdxEstTime"], v["CarIdxLastLapTime"], v["CarIdxBestLapTime"], v["CarIdxBestLapNum"] = est, last, best, bln
        v["CarIdxGear"] = gear
        v["CarIdxRPM"] = arr(6000.0); v["CarIdxSteer"] = arr(0.0); v["CarIdxSessionFlags"] = arr(0); v["CarIdxTireCompound"] = arr(0)
