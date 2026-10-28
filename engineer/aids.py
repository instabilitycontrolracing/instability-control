"""TC and lock-up lights for the iPad (2026-10-25, request: "show the TC and brake lights too, just like on the overlay").

The same logic as Grandstand's onboard pods (RaceStateService.BuildOnboard):
  * LOCK - iRacing's ABS flag where the car really has ABS, otherwise a sudden drop in braking grip: deceleration per
    unit of brake falls below 70 % of the best seen at that speed (a locked wheel). Every car, the GTP included.
  * TC   - live: the engine getting clearly less throttle than the pedal asks for (Throttle < ThrottleRaw), never on the
    pit limiter. Replays (no pedal recorded): flat out but pulling clearly less than this car can at that speed, not
    right after a gear change.
Severity like the BMW M Hybrid V8's dash: the lock grows with how long it lasts (1-3 LEDs), the inside wheels first,
brake (nearly) off = the rears; TC flickers for a little intervention and goes solid when it's heavy.
"""
import time


class Aids:
    def __init__(self):
        self.brake_grip = [0.0] * 12
        self.drive_grip = [0.0] * 12
        self.lock_since = None
        self.tc_since = None
        self.raw_seen = False
        self.last_gear = None
        self.gear_t = 0.0
        self.lock_rear = False
        self.lock_start = None

    def tick(self, g):
        t = time.time()
        try:
            spd = float(g("Speed", 0) or 0)
            brk = float(g("Brake", 0) or 0)
            thr = float(g("Throttle", 0) or 0)
            raw = g("ThrottleRaw", None)
            la = g("LongAccel", None)
            gear = g("Gear", 0)
            steer = float(g("SteeringWheelAngle", 0) or 0)
            limiter = (int(g("EngineWarnings", 0) or 0) & 0x10) != 0
        except Exception:
            return None
        lock = bool(g("BrakeABSactive", False)) and brk > 0.05
        if la is not None and brk > 0.35 and spd > 15:
            band = max(0, min(11, int(spd / 10)))
            grip = -float(la) / brk
            if grip > self.brake_grip[band]:
                self.brake_grip[band] = grip
            low = self.brake_grip[band] > 8 and grip < self.brake_grip[band] * 0.7
            if low:
                self.lock_since = self.lock_since or t
            else:
                self.lock_since = None
            lock = lock or (self.lock_since is not None and t - self.lock_since >= 0.08)
        else:
            self.lock_since = None
        if gear != self.last_gear:
            self.last_gear, self.gear_t = gear, t
        tc = False
        if raw is not None and float(raw) > 0.02:
            self.raw_seen = True
        if self.raw_seen and raw is not None:
            tc = not limiter and float(raw) > 0.25 and float(raw) - thr > 0.06 and spd > 8
        elif la is not None and not limiter:
            band = max(0, min(11, int(spd / 10)))
            flat = thr > 0.9 and 8 < spd < 70 and t - self.gear_t > 0.35
            pull = float(la)
            if flat and pull > self.drive_grip[band]:
                self.drive_grip[band] = pull
            cut = flat and self.drive_grip[band] > 3 and pull < self.drive_grip[band] * 0.72
            if cut:
                self.tc_since = self.tc_since or t
            else:
                self.tc_since = None
            tc = self.tc_since is not None and t - self.tc_since >= 0.1
        if tc:
            self._tc0 = getattr(self, "_tc0", None) or t
        else:
            self._tc0 = None
        if lock:
            if self.lock_start is None:
                self.lock_start, self.lock_rear = t, brk < 0.2
        else:
            self.lock_start = None
        held = t - self.lock_start if self.lock_start else 0
        sev = 0 if not lock else 1 if held < 0.12 else 2 if held < 0.3 else 3
        sl = sr = sev
        if sev and abs(steer) > 0.06:
            if steer > 0:
                sr = max(1, sev - 1)       # turning left: the right (outside) wheels lock less
            else:
                sl = max(1, sev - 1)
        return {"tc": 1 if tc else 0, "tcs": 1 if (tc and self._tc0 and t - self._tc0 > 0.4) else 0,
                "ll": sl, "lr": sr, "rear": 1 if self.lock_rear else 0}
