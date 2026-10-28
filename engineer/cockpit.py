"""The cockpit layer (2026-10-26, request: "I want all of D"):

  D1 (#239)  wind rush on the car and helmet, rising with speed
  D2 (#240)  your own heartbeat and breathing in the last laps of a close fight, or a late restart (off by default)
  D3 (#241)  rain on the roof and the windscreen, plus spray from the car in front on a wet track

Only ever from the developer's OWN recordings (his rule: no made-up environmental sounds) - drop them in Trackside\\sounds:
  cockpit_wind.*        steady wind / helmet rush recorded at speed (the engine as quiet as possible)
  cockpit_heartbeat.*   a calm, close heartbeat
  cockpit_breathing.*   breathing inside a helmet
  cockpit_rain_roof.*   rain on a car roof from inside
  cockpit_spray.*       driving in heavy rain from inside: tyre hiss and spray on the windscreen
A missing file = that part stays silent. Only while YOU are driving (live, your own car) - never in replays, never on
the TV cameras. Its own little mixer, so the crowd's switches and the helmet muffling never touch it.
"""
import time

from .crowd import Mixer


class Cockpit:
    def __init__(self, settings, clips_fn, device=None, log=print):
        self.s, self.clips_fn, self.log = settings, clips_fn, log
        self.m = Mixer(max_voices=6, log=log)
        self.m.volume = 0.5
        self.m.ceiling = 10 ** (-16 / 20)
        self.device = device
        self.started = False
        self.v = {}
        self.heart_until = 0.0
        self._last_green = None
        self._prev_flags = 0

    def opt(self, k, d):
        return getattr(self.s, k, d)

    def _start(self):
        if not self.started:
            self.started = self.m.start(self.device)

    def _loop(self, name, level, glide=0.5):
        """Keep one recording looping at `level` (0 = fade out)."""
        clips = self.clips_fn() or {}
        c = clips.get(name)
        v = self.v.get(name)
        if c is None:
            return
        if level > 0.01:
            if v is None or v.done:
                v = self.m.play(c, 1.0, loop=True, family=name)
                self.v[name] = v
            if v is not None:
                v.target = max(0.0, min(1.5, level))
        elif v is not None:
            v.stop()
            self.v.pop(name, None)

    def update(self, driving, speed_kmh, rain, wet, gap_ahead, gap_behind, laps_left, is_race, flags):
        if not self.opt("cockpit_on", True):
            self.m.muted = True
            return
        clips = self.clips_fn() or {}
        if not any(n.startswith("cockpit_") for n in clips):
            return                                               # no recordings yet: nothing to do
        self._start()
        self.m.heartbeat()
        self.m.volume = max(0.0, min(1.0, float(self.opt("cockpit_volume", 50)) / 100.0))
        self.m.muted = not driving
        if not driving:
            return
        v = max(0.0, float(speed_kmh or 0))
        fast = max(0.0, min(1.0, (v - 70.0) / 230.0)) ** 1.6       # nothing below 70 km/h, full at 300
        # D1 wind
        self._loop("cockpit_wind", fast * 0.9 if self.opt("cockpit_wind", True) else 0.0)
        # D3 rain on the roof (heavier with the rain, louder with speed) and spray (wet track, speed, a car close ahead)
        if self.opt("cockpit_rain", True):
            r = max(0.0, min(1.0, float(rain or 0)))
            self._loop("cockpit_rain_roof", r * (0.55 + 0.45 * fast))
            close = 1.0 if (gap_ahead is not None and gap_ahead < 1.2) else 0.45
            w = max(0.0, min(1.0, float(wet or 0)))
            self._loop("cockpit_spray", w * fast * close)
        else:
            self._loop("cockpit_rain_roof", 0); self._loop("cockpit_spray", 0)
        # D2 heartbeat + breathing: the last 3 laps of a race with a car within a second, or the first 20 s of a restart
        now = time.monotonic()
        f = int(flags or 0)
        if f & 0x4 and not self._prev_flags & 0x4:
            self._last_green = now
        self._prev_flags = f
        tense = False
        if is_race and self.opt("cockpit_heart", False):
            fight = (gap_ahead is not None and gap_ahead < 1.0) or (gap_behind is not None and gap_behind < 1.0)
            if fight and laps_left is not None and 0 < laps_left <= 3:
                tense = True
            if self._last_green is not None and now - self._last_green < 20 and laps_left is not None and laps_left < 10:
                tense = True
        if tense:
            self.heart_until = now + 6.0
        on = now < self.heart_until
        self._loop("cockpit_heartbeat", 0.5 if on else 0.0)
        self._loop("cockpit_breathing", 0.35 if on else 0.0)

    def close(self):
        self.m.close()
