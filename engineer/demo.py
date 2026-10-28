"""Sample race at Spa run through the real brain with fake iRacing data.
Makes a wav of everything the engineer says (with the real gaps between calls squeezed down) and plays it.
"""
import os, time
import numpy as np
import soundfile as sf

from .voice import Voice
from .corners import Corners
from .brain import Brain, Settings, F_GREEN, F_WHITE, F_CHECKERED, F_YELLOW, F_BLUE

TRACK_M = 7004.0
LAP = 138.0


class SimClock:
    t = 0.0
    def __call__(self):
        return self.t


class FakeRace:
    """Me (#28 BMW M4 GT3) starting P4 in GT3, three GT3 rivals, two GTP cars lapping us."""
    def __init__(self, clock):
        self.c = clock
        self.drv = [
            dict(CarIdx=0, CarNumber="28", CarClassID=1, CarClassShortName="GT3", CarPath="bmwm4gt3",
                 CarScreenName="BMW M4 GT3", CarClassEstLapTime=LAP),
            dict(CarIdx=1, CarNumber="7", CarClassID=1, CarClassShortName="GT3", CarClassEstLapTime=LAP),
            dict(CarIdx=2, CarNumber="91", CarClassID=1, CarClassShortName="GT3", CarClassEstLapTime=LAP),
            dict(CarIdx=3, CarNumber="44", CarClassID=1, CarClassShortName="GT3", CarClassEstLapTime=LAP),
            dict(CarIdx=4, CarNumber="25", CarClassID=2, CarClassShortName="GTP", CarClassEstLapTime=LAP * 0.86),
            dict(CarIdx=5, CarNumber="6", CarClassID=2, CarClassShortName="GTP", CarClassEstLapTime=LAP * 0.86),
        ]
        self.green_t = 40.0
        self.laps_total = 6
        self.fuel = 40.0

    def info(self, sec):
        if sec == "DriverInfo":
            return {"DriverCarIdx": 0, "Drivers": self.drv}
        if sec == "WeekendInfo":
            return {"TrackName": "spa up", "TrackLength": "7.00 km", "TrackPitSpeedLimit": "60.00 kph",
                    "WeekendOptions": {"IncidentLimit": "17"}}
        if sec == "SessionInfo":
            return {"Sessions": [{"SessionNum": 0, "SessionType": "Race"}]}
        return {}

    # --- the story of the race ---
    def race_t(self):
        return max(0.0, self.c.t - self.green_t)

    def my_lapf(self):
        return self.race_t() / LAP

    def __getitem__(self, k):
        t, rt = self.c.t, self.race_t()
        lapf = self.my_lapf()
        lap_done = int(lapf)
        pct = lapf % 1 if t >= self.green_t else 0.02 + t / 4000
        flags = 0
        state = 3 if t < self.green_t else 4
        if t >= self.green_t:
            flags |= F_GREEN
        if lap_done >= self.laps_total - 1:
            flags |= F_WHITE
        if lap_done >= self.laps_total:
            flags |= F_CHECKERED
            state = 5
        yellow = 3 * LAP + 50 < rt < 3 * LAP + 75
        if yellow:
            flags |= F_YELLOW
        # my class position over the race: P4 -> P3 at the start -> P2 on lap 5
        pos = 4 if rt < 9 else (3 if rt < 4 * LAP + 60 else 2)
        if k == "SessionNum": return 0
        if k == "SessionState": return state
        if k == "SessionFlags": return flags
        if k == "IsOnTrack": return True
        if k == "PlayerCarIdx": return 0
        if k == "Speed": return 60.0
        if k == "OnPitRoad": return False
        if k == "DisplayUnits": return 0
        if k == "TrackTempCrew": return 31.0
        if k == "LapDist": return pct * TRACK_M
        if k == "LapDistPct": return pct
        if k == "LapCompleted": return lap_done if t >= self.green_t else 0
        if k == "LapLastLapTime":
            return [0, 141.2, 139.6, 137.9, 138.4, 137.2, 138.0][min(lap_done, 6)] if lap_done else -1
        if k == "LapBestLapTime": return 137.2
        if k == "FuelLevel": return self.fuel - 3.1 * lapf
        if k == "SessionLapsRemainEx": return max(0, self.laps_total - lap_done)
        if k == "SessionTimeRemain": return -1
        if k == "PlayerCarMyIncidentCount":
            return 1 if rt > LAP + 27 else 0   # off at Raidillon on lap 2
        if k == "CarLeftRight":
            s = rt
            if 2 < s < 5: return 2          # car left off the line
            if 5 <= s < 7: return 4         # three wide into La Source
            if 7 <= s < 9: return 3         # left one dropped back
            if 9 <= s < 12: return 1
            return 1
        if k == "Brake": return 0.0
        if k == "SteeringWheelAngle": return 0.0
        if k == "CarIdxClassPosition":
            others = {3: [1, 2, 4, 3], 2: [1, 3, 4, 2]}.get(pos, [1, 2, 3, 4])
            # idx0 = me, idx1..3 rivals: put rivals in the positions I'm not in
            rest = [p for p in (1, 2, 3, 4) if p != pos]
            return [pos, rest[0], rest[1], rest[2], 1, 2]
        if k == "CarIdxF2Time":
            mine = 6.0 + (lap_done * -0.35)
            ahead_gap = max(0.4, 2.6 - 0.55 * lap_done)
            arr = [0.0] * 6
            arr[0] = mine
            cp = self["CarIdxClassPosition"]
            for i in (1, 2, 3):
                arr[i] = mine + (cp[i] - pos) * (ahead_gap if cp[i] < pos else 1.4)
                if cp[i] == 1: arr[i] = 0.0
            return arr
        if k == "CarIdxLapDistPct":
            g1 = (pct - 0.006) % 1          # GTP car arriving behind on lap 3
            arr = [pct, (pct + 0.01) % 1, (pct + 0.003) % 1, (pct - 0.02) % 1, (pct + 0.4) % 1, (pct + 0.6) % 1]
            if 2 * LAP + 30 < rt < 2 * LAP + 45:
                arr[4] = g1
            if yellow:
                arr[3] = 0.55  # car stopped off ahead of us
            return arr
        if k == "CarIdxTrackSurface":
            s = [3] * 6
            if yellow: s[3] = 0
            return s
        if k == "CarIdxOnPitRoad": return [False] * 6
        if k == "CarIdxBestLapTime": return [137.2, 136.9, 137.5, 138.1, 119.0, 119.4]
        if k == "WeatherDeclaredWet": return False
        return None


class RecordingVoice(Voice):
    """Builds every call immediately and stores it with its sim time."""
    def __init__(self, *a, **k):
        k["output"] = False
        super().__init__(*a, **k)
        self.timeline = []
        self.clock = None

    def say(self, sid, fills=None, prio=3, max_age=None):
        audio, text = self.build(sid, fills or {})
        if audio is None:
            self.log(f"[demo] can't say {sid} {fills}")
            return
        self.log(f"{self.clock.t:7.1f}s ENGINEER: {text}")
        self.timeline.append((self.clock.t, audio))

    def hold(self, flag):
        pass


def run_demo(vocab, preset, landmarks, record, device, volume, log):
    clock = SimClock()
    v = RecordingVoice(vocab, preset, volume=volume, log=log)
    v.clock = clock
    corners = Corners(landmarks, v.blocks.get("corner", {}), exists=v.clip_exists)
    race = FakeRace(clock)
    b = Brain(race, v, corners, Settings(), log=log, clock=clock)
    end = race.green_t + LAP * race.laps_total + 40
    while clock.t < end:
        b.tick()
        clock.t += 0.25
    # stitch: keep real order, squeeze long silences to ~1.2 s
    sr = v.sr
    out, last_end = [], 0.0
    for t, a in v.timeline:
        gap = min(max(0.35, t - last_end), 1.2)
        out += [np.zeros(int(gap * sr), np.float32), a]
        last_end = t + len(a) / sr
    wav = np.concatenate(out) if out else np.zeros(sr, np.float32)
    path = record or os.path.join(os.path.expanduser("~"), "Desktop", "Engineer Voice - Listen", "Engineer demo race.wav")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, wav, sr)
    log(f"Demo saved: {path}  ({len(v.timeline)} calls, {len(wav) / sr:.0f} s)")
    if device != "none":
        try:
            import sounddevice as sd
            sd.play(wav, sr, device=device); sd.wait()
        except Exception as e:
            log(f"(couldn't play: {e})")
