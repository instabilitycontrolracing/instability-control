"""Bass shaker (tactile transducer) output (2026-10-26, #211, request: "I don't have a bass shaker but build it").

A bass shaker is a speaker without a cone, bolted to the seat or the pedals and driven by a small amplifier from a
sound output of the PC (any spare one: the motherboard's green jack, a USB sound card). This makes the signal for it
straight from iRacing's live data, so you FEEL the car instead of hearing it:

  engine    a low hum at the engine's firing rhythm (V8 in the GTP, straight six in the M4), stronger with throttle
  shifts    a short kick on every gear change
  kerbs     road and kerb bumps from the car's vertical movement
  ABS       the ABS pulsing under braking
  impacts   a hard thump on a big hit

Everything is kept below 80 Hz (a shaker can't do more, and it never leaks into the room as noise). OFF until you
pick its output in Settings > Sound mix > Bass shaker. Reads iRacing on its own (60 times a second), so it keeps
working whatever the rest of the app is doing, and it never touches your headphones or the TV.
"""
import math, threading, time
import numpy as np
try:
    from scipy.signal import lfilter
except Exception:      # no scipy: a plain filter
    lfilter = None

RATE = 48000
BLOCK = 480                     # 10 ms


class Shaker:
    """prefix "shaker_" = the seat shaker; "pedal_" = D11 (#249) a second transducer on the pedals / a haptic cushion,
    with its own output, strength and effects (default: ABS, kerbs and the limiter - what you feel through your feet)."""
    def __init__(self, settings, log=print, prefix="shaker_"):
        self.s, self.log, self.prefix = settings, log, prefix
        self.stream = None
        self.state = {"rpm": 0.0, "thr": 0.0, "gear": 0, "abs": False, "vert": 0.0, "long": 0.0, "lat": 0.0,
                      "on": False, "cyl": 6, "pit": False, "limiter": False, "rumble": 0.0}
        self._vhist = []                # D10 (#248): recent vertical accel, to tell a rumble strip from a bump
        self._shift = 0.0               # kick envelope
        self._hit = 0.0
        self._bump = 0.0
        self._ph = [0.0, 0.0, 0.0]
        self._lp = 0.0
        self._prev_vert = 0.0
        self._abs_ph = 0.0
        self._test_until = 0.0
        self.status = "off"
        self.alive = True
        threading.Thread(target=self._read_loop, daemon=True, name="shaker-read").start()
        self.apply()

    def opt(self, k, d):
        if self.prefix != "shaker_" and k.startswith("shaker_"):
            k = self.prefix + k[len("shaker_"):]
        return getattr(self.s, k, d)

    # ---------- the output ----------
    def apply(self):
        dev = self.opt("shaker_device", "") or ""
        on = bool(self.opt("shaker_on", False)) and dev
        if not on:
            self.close(); self.status = "off"
            return
        if self.stream is not None and getattr(self, "_dev", None) == dev:
            return
        self.close()
        try:
            import sounddevice as sd
            self.stream = sd.OutputStream(samplerate=RATE, channels=2, dtype="float32", device=dev, blocksize=BLOCK,
                                          callback=lambda out, n, t, st: self.render(out))
            self.stream.start()
            self._dev = dev
            self.status = f"on: {dev}"
        except Exception as e:
            self.stream = None
            self.status = f"can't open {dev}: {str(e)[:80]}"
            self.log(f"[shaker] {e!r}")

    def close(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop(); s.close()
            except Exception:
                pass

    def test(self):
        """2 seconds of the engine rumble, rising - so you can feel it work and set the amp."""
        self._test_until = time.time() + 2.0
        return self.stream is not None

    # ---------- iRacing ----------
    def _read_loop(self):
        ir = None
        while self.alive:
            if self.stream is None:
                time.sleep(0.5); continue
            try:
                if ir is None:
                    import irsdk
                    ir = irsdk.IRSDK()
                if not (ir.is_initialized and ir.is_connected):
                    ir.shutdown()
                    if not ir.startup():
                        self.state["on"] = False
                        time.sleep(1.0); continue
                    di = ir["DriverInfo"] or {}
                    me = next((d for d in (di.get("Drivers") or []) if d.get("CarIdx") == di.get("DriverCarIdx")), {})
                    path = (me.get("CarPath") or "").lower()
                    self.state["cyl"] = 8 if ("lmdh" in path or "v8" in path) else 6
                ir.freeze_var_buffer_latest()
                def g(k, d=0.0, ir=ir):                        # 2026-10-29: one read per value (was two)
                    v = ir[k]
                    return v if v is not None else d
                st = self.state
                gear = int(g("Gear", 0) or 0)
                if gear != st["gear"] and st["on"]:
                    self._shift = 1.0 if st["cyl"] == 6 else 0.75     # D10: the GT3's sequential bangs harder than the GTP
                vert = float(g("VertAccel", 9.81) or 9.81)
                lng, lat = float(g("LongAccel", 0) or 0), float(g("LatAccel", 0) or 0)
                jolt = math.hypot(lng - st["long"], lat - st["lat"])
                if jolt > 25 and st["on"]:                     # a big hit (more than 2.5 g change in one tick)
                    self._hit = min(1.0, jolt / 60)
                # D10 (#248): a rumble strip is a fast rattle in the vertical accel (high-pass energy), a bump is one big swing
                self._vhist.append(vert); self._vhist = self._vhist[-12:]
                if len(self._vhist) >= 6:
                    hv = [self._vhist[i] - self._vhist[i - 1] for i in range(1, len(self._vhist))]
                    rattle = sum(abs(hv[i] - hv[i - 1]) for i in range(1, len(hv))) / max(1, len(hv) - 1)
                    st["rumble"] = min(1.0, rattle / 18.0)
                ew = int(g("EngineWarnings", 0) or 0)
                st["limiter"] = bool(ew & 0x10)                  # pit speed limiter on
                st.update(rpm=float(g("RPM", 0) or 0), thr=float(g("Throttle", 0) or 0), gear=gear,
                          abs=bool(g("BrakeABSactive", False)), vert=vert, long=lng, lat=lat,
                          on=bool(g("IsOnTrack", False)) and not bool(g("IsReplayPlaying", False)),
                          pit=bool(g("OnPitRoad", False)))
                ir.unfreeze_var_buffer_latest()
                time.sleep(1 / 60)
            except Exception as e:
                self.log(f"[shaker] read: {e!r}")
                ir = None
                time.sleep(2.0)

    # ---------- the signal ----------
    def render(self, out):
        try:
            n = len(out)
            t = np.arange(n) / RATE
            st = self.state
            master = max(0.0, min(1.5, float(self.opt("shaker_gain", 0.6))))
            sig = np.zeros(n)
            testing = time.time() < self._test_until
            if st["on"] or testing:
                # engine: firing frequency, folded down into 25-60 Hz
                rpm = st["rpm"] if not testing else 3000 + 5000 * (1 - (self._test_until - time.time()) / 2.0)
                f = rpm / 60.0 * st["cyl"] / 2.0
                while f > 60:
                    f /= 2
                if f >= 15 and (self.opt("shaker_engine", True) or testing):
                    a = (0.25 + 0.55 * (st["thr"] if not testing else 1.0)) * min(1.0, rpm / 6000)
                    ph = self._ph[0] + 2 * np.pi * f * t
                    sig += a * np.sin(ph) + 0.25 * a * np.sin(2 * ph)
                    self._ph[0] = float((ph[-1] + 2 * np.pi * f / RATE) % (2 * np.pi))
                # gear shift kick (45 Hz, 80 ms)
                if self._shift > 0.01 and self.opt("shaker_shifts", True):
                    env = self._shift * np.exp(-t / 0.03)
                    sig += 0.9 * env * np.sin(2 * np.pi * 45 * t)
                    self._shift *= math.exp(-n / RATE / 0.03)
                # kerbs / bumps: vertical acceleration away from 1 g, as a 35 Hz rumble
                if self.opt("shaker_kerbs", True):
                    target = min(1.0, abs(st["vert"] - 9.81) / 12.0)
                    self._bump += (target - self._bump) * 0.5
                    ph = self._ph[1] + 2 * np.pi * 35 * t
                    sig += 0.8 * self._bump * np.sign(np.sin(ph)) * 0.6
                    self._ph[1] = float((ph[-1] + 2 * np.pi * 35 / RATE) % (2 * np.pi))
                # D10 (#248): rumble strips - a fast 42 Hz rattle that follows the strip, on top of the bump rumble
                if st["rumble"] > 0.08 and self.opt("shaker_kerbs", True):
                    ph = self._ph[2] + 2 * np.pi * 42 * t
                    sig += 0.55 * st["rumble"] * np.sign(np.sin(ph)) * (0.6 + 0.4 * np.sin(2 * np.pi * 11 * t))
                    self._ph[2] = float((ph[-1] + 2 * np.pi * 42 / RATE) % (2 * np.pi))
                # D10 (#248): the pit limiter - a steady pulsing buzz while it holds the car
                if st["limiter"] and self.opt("shaker_limiter", True):
                    sig += 0.35 * (np.sin(2 * np.pi * 6 * t + time.time() * 37.7) > 0) * np.sin(2 * np.pi * 28 * t)
                # ABS pulsing (about 18 pulses a second)
                if st["abs"] and self.opt("shaker_abs", True):
                    ph = self._abs_ph + 2 * np.pi * 18 * t
                    sig += 0.5 * (np.sin(ph) > 0.3) * np.sin(2 * np.pi * 50 * t)
                    self._abs_ph = float((ph[-1]) % (2 * np.pi))
                # impact thump
                if self._hit > 0.01 and self.opt("shaker_impacts", True):
                    env = self._hit * np.exp(-t / 0.12)
                    sig += 1.2 * env * np.sin(2 * np.pi * 30 * t)
                    self._hit *= math.exp(-n / RATE / 0.12)
            # keep it below ~80 Hz (one-pole low-pass, state kept between blocks) and never clip
            a = math.exp(-2 * math.pi * 80 / RATE)
            if lfilter is not None:
                y, zf = lfilter([1 - a], [1, -a], sig, zi=[self._lp])
                self._lp = float(zf[0])
            else:
                y = sig
            y = np.tanh(y * master * 1.4) * 0.9
            out[:, 0] = y; out[:, 1] = y
        except Exception:
            out[:] = 0
