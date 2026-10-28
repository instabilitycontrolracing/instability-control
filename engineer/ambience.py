"""Trackside ambience on top of the crowd (2026-10-26, request: "everything" from the sound ideas list).

  #204 weather + time of day: rain on the stands' roofs when it rains, wind when the camera car is flat out on a
       windy day, Le Mans at night (crowd thinned, insects, the fairground near Dunlop)
  #205 bridges and tunnels: an echo on the trackside sound and a short whoosh as the camera goes under
  #206 the pit lane: when the car on screen stops in its box - your real pit stop recordings for its class; the pit PA
       while it rolls down the lane

Every sound here is made in code (nothing recorded, nothing to licence) the first time it's needed and kept in
Trackside\\synth\\ - a recording of your own with the same name in Trackside\\sounds\\ wins (amb_rain, amb_wind,
amb_night, amb_fair, fx_whoosh).

Runs inside the crowd director, same mixer, same safety (ceiling, limiter, radio duck, master volume).
"""
import json, math, os, threading, time, urllib.request
import numpy as np

from .track_packs import PACK_BRIDGES

RATE = 48000


# ============================================================== the sounds (made in code, seamless loops)
def _noise(n, rng, lo=20, hi=20000, pink=False, rate=RATE):
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / rate)
    if pink:
        spec /= np.sqrt(np.maximum(f, 20.0) / 20.0)
    g = np.ones_like(f)
    if lo > 0:
        g /= np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** 4)
    if hi > 0:
        g /= np.sqrt(1 + (f / hi) ** 4)
    x = np.fft.irfft(spec * g, n)
    return x / (np.std(x) + 1e-12)


def _norm(x, rms_db=-20, peak_db=-2):
    x = x / (np.sqrt(np.mean(x ** 2)) + 1e-12) * 10 ** (rms_db / 20)
    pk = np.max(np.abs(x))
    if pk > 10 ** (peak_db / 20):
        x *= 10 ** (peak_db / 20) / pk
    return x.astype(np.float32)


def _st(l, r=None):
    return np.stack([l, l if r is None else r], 1)


def _circ_add(dst, src, at):
    """Add src into dst starting at `at`, wrapping round the end (so loops stay seamless)."""
    n = len(dst)
    for i in range(0, len(src), n):
        part = src[i:i + n]
        a = (at + i) % n
        k = min(len(part), n - a)
        dst[a:a + k] += part[:k]
        if k < len(part):
            dst[:len(part) - k] += part[k:]


def make_rain(seconds=12, seed=3):
    n, rng = RATE * seconds, np.random.default_rng(seed)
    out = []
    for ch in range(2):
        bed = _noise(n, rng, 400, 9000, pink=True) * 0.5            # the hiss of rain on canvas / roofs
        drops = np.zeros(n)
        for _ in range(seconds * 260):                               # individual drops on the roof
            at = rng.integers(n); L = rng.integers(60, 400)
            k = np.arange(L)
            d = rng.standard_normal(L) * np.exp(-k / (L / 5)) * rng.uniform(0.2, 1.0)
            _circ_add(drops, d, at)
        f = np.fft.rfftfreq(n, 1 / RATE)
        sp = np.fft.rfft(drops) / np.sqrt(1 + (f / 6000) ** 4) / np.sqrt(1 + (700 / np.maximum(f, 1)) ** 2)
        drops = np.fft.irfft(sp, n); drops /= np.std(drops) + 1e-12
        out.append(bed + 0.35 * drops)
    return _norm(_st(*out))


def make_wind(seconds=16, seed=5):
    n, rng = RATE * seconds, np.random.default_rng(seed)
    t = np.arange(n) / RATE
    gust = 0.55 + 0.25 * np.sin(2 * np.pi * t * (2 / seconds) + 0.3) + 0.2 * np.sin(2 * np.pi * t * (5 / seconds) + 1.7)
    out = []
    for ch in range(2):
        low = _noise(n, rng, 30, 400, pink=True)                     # the rumble of wind past a microphone
        whistle = _noise(n, rng, 600, 1400) * 0.25                   # a little whistle through the fences
        out.append((low + whistle * gust) * gust)
    return _norm(_st(*out), -22)


def make_night(seconds=20, seed=7):
    """Night trackside: insects in the grass, a low distant hum."""
    n, rng = RATE * seconds, np.random.default_rng(seed)
    t = np.arange(n) / RATE
    out = []
    for ch in range(2):
        hum = _noise(n, rng, 40, 250, pink=True) * 0.35
        crick = np.zeros(n)
        for _ in range(seconds * 9):                                 # cricket chirps: 3-4 short pulses at ~4.5 kHz
            at = rng.integers(n); f0 = rng.uniform(4200, 5200); amp = rng.uniform(0.1, 0.6)
            for p in range(int(rng.integers(3, 5))):
                L = int(0.018 * RATE); k = np.arange(L)
                c = np.sin(2 * np.pi * f0 * k / RATE) * np.sin(np.pi * k / L) ** 2 * amp
                _circ_add(crick, c, at + p * int(0.032 * RATE))
        out.append(hum + crick)
    return _norm(_st(*out), -24)


def make_fair(seconds=24, seed=11):
    """The fairground near Dunlop at night, far away: a fairground-organ waltz, softened by distance."""
    n, rng = RATE * seconds, np.random.default_rng(seed)
    beat = 60 / 132                                                   # 132 bpm waltz, whole bars in the loop
    bars = int(seconds / (beat * 3)); n = int(round(bars * 3 * beat * RATE)); t = np.arange(n) / RATE
    chords = [(196.0, 246.9, 293.7), (261.6, 329.6, 392.0), (293.7, 370.0, 440.0), (196.0, 246.9, 293.7)]
    melody = [392.0, 440.0, 493.9, 523.3, 493.9, 440.0, 392.0, 370.0, 392.0, 329.6, 293.7, 329.6]
    sig = np.zeros(n)
    def note(f, at, dur, amp):
        L = int(dur * RATE); k = np.arange(L)
        env = np.minimum(1, k / (0.01 * RATE)) * np.exp(-k / (0.6 * RATE))
        w = sum(np.sin(2 * np.pi * f * h * k / RATE) / h for h in (1, 2, 3, 4))   # reedy organ
        _circ_add(sig, w * env * amp, at)
    for b in range(bars):
        ch = chords[b % len(chords)]
        base = int(b * 3 * beat * RATE)
        note(ch[0] / 2, base, beat * 0.9, 0.5)                            # oom
        for k in (1, 2):
            for f in ch:
                note(f, base + int(k * beat * RATE), beat * 0.5, 0.18)    # pah pah
        for k in range(3):
            note(melody[(b * 3 + k) % len(melody)] * 2, base + int(k * beat * RATE), beat * 0.95, 0.22)
    f = np.fft.rfftfreq(n, 1 / RATE)
    sp = np.fft.rfft(sig) / np.sqrt(1 + (f / 1800) ** 4)                 # far away: no highs
    sig = np.fft.irfft(sp, n)
    # a big outdoor space: a few circular echoes
    rev = sig.copy()
    for d, g in ((0.11, 0.35), (0.23, 0.25), (0.41, 0.18), (0.67, 0.1)):
        rev += np.roll(sig, int(d * RATE)) * g
    crowd = _noise(n, rng, 150, 1200, pink=True) * 0.12                   # people walking about
    return _norm(_st(rev + crowd, np.roll(rev, int(0.013 * RATE)) + crowd), -24)


def make_whoosh():
    n = int(0.9 * RATE); rng = np.random.default_rng(13); k = np.arange(n)
    x = _noise(n, rng, 200, 3000, pink=True) * np.sin(np.pi * k / n) ** 3
    return _norm(_st(x, np.roll(x, 40)), -20)


# 2026-10-26 (#222, request: "those are not in the game, we can't mod them in"): no fireworks, no made-up pit stop
MAKERS = {"amb_rain": make_rain, "amb_wind": make_wind, "amb_night": make_night, "amb_fair": make_fair,
          "fx_whoosh": make_whoosh}


def load_or_make(Clip, own_clips, cache_dir, log=print):
    """-> {name: Clip}. Your own recording (same name in the sounds folder) wins; else the cached synth; else made now."""
    out = {}
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError:
        cache_dir = None
    for name, fn in MAKERS.items():
        if name in own_clips:
            out[name] = own_clips[name]; continue
        x = None
        p = os.path.join(cache_dir, name + ".npy") if cache_dir else None
        if p and os.path.exists(p):
            try:
                x = np.load(p)
            except Exception:
                x = None
        if x is None:
            try:
                x = (np.clip(fn(), -1, 1) * 32767).astype(np.int16)
                if p:
                    np.save(p, x)
            except Exception as e:
                log(f"[ambience] {name}: {e!r}"); continue
        out[name] = Clip(name, np.ascontiguousarray(x), 1.0)
    return out


# ============================================================== when they play
class Ambience:
    def __init__(self, director, clips, log=print):
        self.d, self.c, self.log = director, clips, log
        self.v = {}                     # bed name -> Voice
        self.places = []                # Grandstand's named places (bridges / tunnels)
        self._places_t = 0.0
        self.pit_state = {}             # car -> (stopped since, sequence played)
        self.prev_prog = {}
        self.under = False
        self.night = False
        self.last_cut_t = 0.0

    def opt(self, k, dflt):
        return self.d.opt(k, dflt)

    # ---------- places from Grandstand (bridges, tunnels) ----------
    def _fetch_places(self):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8790/api/places", timeout=1.5) as r:
                d = json.loads(r.read().decode("utf-8"))
            self.places = [s for s in (d.get("stops") or []) if s.get("s0") is not None]
        except Exception:
            pass

    def _under_bridge(self, pct, track_id):
        if time.time() - self._places_t > 60:
            self._places_t = time.time()
            threading.Thread(target=self._fetch_places, daemon=True).start()
        spans = []
        for s in self.places:
            nm = f"{s.get('name', '')} {s.get('eye', '')}".lower()
            if "bridge" in nm or "tunnel" in nm or "under" in nm:
                spans.append((float(s["s0"]), float(s["s1"])))
        if "lemans" in (track_id or "").lower().replace(" ", ""):
            # 2026-10-26 (driver request, wet Le Mans practice: "the Dunlop bridge sound is way off from where it is and needs to
            # be way shorter"): the old guess (11.5 % of the lap) was the wrong place, and the window was up to 270 m long.
            # The bridge spans the track just after the Dunlop chicane exit (Grandstand's chicane ends at 7.27 %).
            spans = [(0.0761, 0.0769)]
        else:
            # 2026-10-28: the same for the Sports Car tracks whose research pack places a bridge over the track (Lime Rock,
            # Road Atlanta, Mid-Ohio, Road America): spans from CrewChief's corner metres, per iRacing layout id
            # (windows ~6 m either side of the bridge, like Le Mans', so they're checked as they are)
            key = "".join(ch for ch in (track_id or "").lower() if ch.isalnum())
            if key in PACK_BRIDGES:
                return any(a <= pct <= b for a, b in PACK_BRIDGES[key])
        for a, b in spans:
            mid, half = (a + b) / 2, max(0.0003, abs(b - a) / 2)
            # 2026-10-26 (request: "a very very short bridge underpass, maybe a quarter of a second"): ~6 m either side
            if abs(((pct - mid + 0.5) % 1) - 0.5) < min(half, 0.00045):
                return True
        return False

    # ---------- beds ----------
    def bed(self, name, want, level, fade_in_delay=0.0):
        v = self.v.get(name)
        if want <= 0.01:
            if v is not None:
                v.stop(); self.v.pop(name, None)
            return
        if v is None or v.done or v.fade_target <= 0:
            v = self.d.m.play(self.c.get(name), level=level * want, loop=True, delay=fade_in_delay, family="amb:" + name)
            if v is None:
                return
            self.v[name] = v
        v.target = want

    def _bed_clip(self, name, want):
        """bed() for a clip from the main sounds folder (your own recordings)."""
        v = self.v.get(name)
        if want <= 0.01:
            if v is not None:
                v.stop(); self.v.pop(name, None)
            return
        if v is None or v.done or v.fade_target <= 0:
            v = self.d.m.play(self.d.clips.get(name), level=1.0, loop=True, family="amb:" + name)
            if v is None:
                return
            self.v[name] = v
        v.target = want

    def stop_all(self):
        for v in self.v.values():
            v.stop()
        self.v.clear()

    # ---------- per tick ----------
    def update(self, f, dt):
        if not self.opt("crowd_ambience", True):
            self.stop_all(); self.d.m.echo_target = 0.0
            return
        aerial = getattr(f, "aerial", "")
        # weather
        rain = max(0.0, min(1.0, float(getattr(f, "rain", 0.0) or 0.0)))
        wet = max(0.0, min(1.0, float(getattr(f, "wet", 0.0) or 0.0)))
        rain_level = rain if rain > 0 else (0.25 if wet > 0.5 else 0.0)
        self.bed("amb_rain", 0.0 if aerial else rain_level, 0.8)
        wind = float(getattr(f, "wind_ms", 0.0) or 0.0)
        fast = float(getattr(f, "speed_kmh", 0.0) or 0.0) > 200
        w = 0.0 if aerial else max(0.0, min(1.0, (wind - 3.0) / 9.0)) * (1.0 if fast else 0.4)
        self.bed("amb_wind", w, 0.7)
        # night
        night = bool(getattr(f, "night", False))
        self.night = night
        self.d.night_scale = 0.6 if night else 1.0              # the crowd beds are thinner at night
        self.bed("amb_night", 0.0 if (aerial or not night) else 0.5, 0.6)
        lemans = "lemans" in (f.track_id or "").lower().replace(" ", "")
        fair = 0.0
        if night and lemans and not aerial:
            near = abs(((f.pct - 0.115 + 0.5) % 1) - 0.5)       # the fairground sits behind the Dunlop curve
            fair = max(0.15, 1.0 - near / 0.05) if near < 0.12 else 0.0
        self.bed("amb_fair", fair, 0.55)
        # 2026-10-26 (#214-215): the circuit's own race-day atmosphere from your sights & sounds videos
        # (amb_track_<track>.wav in the Trackside sounds folder: lemans, daytona, ...), quietly under everything
        key = "".join(ch for ch in (f.track_id or "").lower() if ch.isalnum())
        tb = next((k for k in self.d.clips if k.startswith("amb_track_") and k[10:] and key.startswith(k[10:])), None)
        for k in [n for n in self.v if n.startswith("amb_track_") and n != tb]:
            self.bed(k, 0, 0)
        if tb:
            # #220: no race, no race-day sound. #225 (request: "no cars passing by audio unless on replay cams for trackside,
            # onboard would sound totally different per car, let the game handle that"): these recordings have cars going
            # past in them, so they only play on TV / trackside cameras - onboard, the game's own car sound is the car.
            lvl = 0.0 if (aerial or getattr(f, "empty", False) or not f.tv) else 0.55 * (0.7 if night else 1.0)
            self._bed_clip(tb, lvl)
        # bridges and tunnels (onboard / chase cameras only - not from the blimp)
        under = (not aerial) and self._under_bridge(f.pct, f.track_id)
        self.d.m.echo_target = 0.45 if under else 0.0
        if under and not self.under and f.speed_kmh > 80 and not f.tv:
            self.d.m.play(self.c.get("fx_whoosh"), 0.55, family="whoosh")
        self.under = under
        # pit stops of the car on screen (replays / TV cameras)
        self._pits(f, dt)
        self._extras(f, aerial, night, lemans)

    # ---------- 2026-10-26: the owner's picks (W5, W6, W7, C2, C3, C6, C7) - all from his own recordings ----------
    def _pick(self, prefix):
        opts = sorted(k for k in self.d.clips if k.startswith(prefix))
        return self.d.clips[opts[int(self.d.rnd.random() * len(opts))]] if opts else None

    def _extras(self, f, aerial, night, lemans):
        cam = (getattr(f, "cam", "") or "").lower()
        tv = bool(getattr(f, "tv", False)) and not aerial
        running = not getattr(f, "empty", False)
        # W5 (#255) camera-specific sound: the pit-lane camera is the pits (crowd down, garages up); scenic / far
        # cameras hear the crowd from further off
        pitcam = tv and "pit" in cam
        self.d.cam_scale = 0.5 if pitcam else 0.6 if (tv and ("scenic" in cam or "far" in cam)) else 1.0
        # C6 (#285) garage life: on the pit-lane camera, or a TV camera on a car stopped in its box
        boxed = tv and any(st.get("since") for st in self.pit_state.values())
        self._bed_clip("amb_garage", (0.55 if pitcam else 0.35 if boxed else 0.0) if running or pitcam else 0.0)
        # W6 (#256) the night palette: generators humming round the pits on the pit-lane camera / main straight at night
        near_pits = abs(((f.pct + 0.5) % 1) - 0.5) < 0.03
        self._bed_clip("amb_night_generators", 0.45 if (night and tv and (pitcam or near_pits)) else 0.0)
        # C3 (#282) Le Mans campsites at night, out along the Mulsanne side of the lap
        self._bed_clip("amb_campsite_lemans", 0.4 if (night and lemans and tv and 0.3 < f.pct < 0.65) else 0.0)
        # W7 (#257) distant thunder when it rains (every 1-3 minutes)
        rain = float(getattr(f, "rain", 0) or 0)
        if rain > 0.25 and not aerial and self.d.now > getattr(self, "_next_thunder", 0.0):
            self._next_thunder = self.d.now + 60 + self.d.rnd.random() * 120
            c = self._pick("fx_thunder_")
            if c is not None:
                self.d.m.play(c, 0.35 + 0.3 * rain, family="thunder", pan=self.d.rnd.random() * 1.4 - 0.7, reserve=1)
        # C2 (#281) chants and clapping: under a caution every 40-90 s, and on the last lap
        caution = bool(getattr(f, "caution", False))
        last = bool(getattr(self.d, "white_seen", False)) and not bool(getattr(self.d, "chequer_seen", False))
        if running and (caution or last) and self.d.now > getattr(self, "_next_chant", 0.0):
            self._next_chant = self.d.now + (40 + self.d.rnd.random() * 50 if caution else 25 + self.d.rnd.random() * 20)
            c = self._pick("crowd_chant_" if self.d.rnd.random() < 0.5 else "crowd_clap_") or self._pick("crowd_chant_") or self._pick("crowd_clap_")
            if c is not None:
                self.d.m.play(c, 0.6 * getattr(self.d, "sess_scale", 1.0), family="chant", pan=self.d.rnd.random() * 0.8 - 0.4, reserve=1)
        # C7 (#286) the podium: two minutes after the flag - the podium crowd, then the champagne
        cq = getattr(self.d, "chequer_t", None)
        if cq is not None and not getattr(self, "_podium_done", False) and self.d.now - cq > 120:
            self._podium_done = True
            c = self._pick("crowd_podium")
            if c is not None:
                self.d.m.play(c, 0.7, family="podium", reserve=1)
                ch = self._pick("fx_champagne")
                if ch is not None:
                    self.d.m.play(ch, 0.6, delay=4.0, family="champagne", reserve=1)

    def _pits(self, f, dt):
        """2026-10-26 (#206, #212-213): the car on screen stops in its box -> a real pit stop recording for its class
        (pit_gtp_stop_*, pit_gt3_stop_* in the Trackside sounds folder: tyres, tear-off, fuel...) while it sits there, then the
        matching take-off (pit_*_go_*) the moment it pulls away. Classes without a recording stay quiet (#222)."""
        follow = getattr(f, "follow", None)
        car = next((c for c in f.cars if c.id == follow), None) if follow is not None else None
        if car is None or not f.tv:
            self._pit_end(None)
            return
        prev = self.prev_prog.get(car.id)
        self.prev_prog[car.id] = car.progress
        if not car.in_pits:
            self._pit_end(car.id, go=True)
            self.pit_state.pop(car.id, None)
            return
        moving = prev is not None and abs(car.progress - prev) * max(f.track_len, 1000) > max(dt, 0.05) * 1.5
        st = self.pit_state.setdefault(car.id, {"since": None, "played": False, "pa": False, "voice": None,
                                                "cls": (getattr(f, "follow_class", "") or "").lower()})
        if not st["pa"] and moving:                     # rolling down the lane: the pit-lane speaker
            st["pa"] = True
            c = self.d.pick("pa_far_") if hasattr(self.d, "pick") else None
            if c is not None:
                self.d.m.play(c, 0.7, family="pa")
        if moving:
            if st["played"]:
                self._pit_end(car.id, go=True)          # pulling away after the stop
            st["since"] = None
            return
        st["since"] = st["since"] or self.d.now
        if not st["played"] and self.d.now - st["since"] > 0.6:   # stopped in the box: the crew goes to work
            st["played"] = True
            cls = st["cls"] if st["cls"] in ("gtp", "gt3") else ("gt3" if st["cls"] in ("gtd", "gtd_pro") else st["cls"])
            idx = 1 + int(self.d.rnd.random() * 8)
            stops = sorted(k for k in self.d.clips if k.lower().startswith(f"pit_{cls}_stop_")) if cls else []
            if stops:
                name = stops[idx % len(stops)]
                st["go"] = name.replace("_stop_", "_go_")
                st["voice"] = self.d.m.play(self.d.clips[name], 0.85, family="pit_stop")
                return

    def _pit_end(self, car_id, go=False):
        """The stop is over (car moving / out of the pits / camera elsewhere): fade the stop out, play its take-off."""
        for cid, st in list(self.pit_state.items()):
            if car_id is not None and cid != car_id:
                continue
            v = st.get("voice")
            if v is not None:
                v.stop(); st["voice"] = None
                g = st.pop("go", None)
                if go and g and g in self.d.clips:
                    self.d.m.play(self.d.clips[g], 0.9, family="pit_go")
