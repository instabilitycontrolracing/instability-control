"""Trackside crowd (2026-10-24): grandstands that come alive around the lap.

Moved here from the developer's SimHub add-on "Trackside Crowd" (C#), which once made a very loud noise.
This version is safe by design:
  * every file is loudness-normalised once at load (gains cached in Trackside/levels.json)
  * the final mix goes through a peak limiter AND a hard clip at the user's ceiling (default -18 dBFS),
    after a master volume (default 30%) - the output can never be louder than the ceiling
  * every gain glides (fade-ins/outs, no clicks); at most N voices at once; the same event never stacks
  * any error (bad file, bad numbers, device problem) -> silence, never noise
  * it fades out by itself when the engineer stops sending updates (iRacing closed, engine off),
    and (optionally) in the garage / pit lane
  * it ducks under radio speech and never touches the RADIO channel

Structure: Mixer (audio thread, preallocated buffers) <- Director (the brain's tick, tiny state
updates) <- Crowd (what the app talks to). Sounds and track files live in CrewChiefVoices\\Trackside\\
(sounds\\*.wav, tracks\\*.json) - the owner's own files, never shipped.
"""
import json, math, os, random, shutil, threading, time
from collections import deque

import numpy as np

try:
    from . import simload            # #454 loading screens: the crowd waits
except ImportError:                  # offline tools import this file on its own
    import simload

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TS_DIR = os.path.join(ROOT, "Trackside")                   # next to RaceControl\
# 2026-10-28: grandstand maps that ship with the app (Mexico City, Suzuka, Silverstone, Sebring, Monza); loaded
# first, so a file of your own in Trackside\tracks\ for the same track still wins (find_track: last match wins)
BUNDLED_TRACKS = os.path.join(HERE, "trackside_tracks")
SIMHUB_ROOTS = [r"C:\Program Files (x86)\SimHub", r"C:\Program Files\SimHub"]

try:
    from scipy.signal import lfilter as _lfilter
except Exception:                                   # no scipy: no helmet filter
    _lfilter = None

RATE = 48000
TAPS = []   # 2026-10-29 (#515): listeners that get each rendered crowd block (stereo, RATE)
BLOCK = 1024
TARGET_RMS_DB = -20.0          # every file is brought to this loudness...
FILE_PEAK_DB = -1.0            # ...without its peaks going over this
MAX_FILE_SECONDS = 150         # longer files are cut (memory)
CEILING_MIN_DB, CEILING_MAX_DB = -48.0, -6.0   # the user's "max loudness" is kept inside this range

# every sound the director asks for (from the C# Director). A family ending in "_" takes any number
# of files (whistles_1.wav, whistles_2.wav ...); the rest may come as _near / _mid / _far.
SOUND_NAMES = [
    "bed_stadium_crowd_near", "bed_stadium_crowd_far", "bed_crowd_buzz_mid", "bed_crowd_excited_mid",
    "bed_crowd_whistling_mid", "bed_crowd_roaring_mid", "bed_crowd_roar_mid", "bed_vuvuzela_stadium_far",
    "bed_helicopter_hover_far",
    "roar_goal_near", "roar_goal_mid", "roar_stadium_near", "roar_stadium_mid", "cheer_B_near", "cheer_B_mid",
    "cheer_B_peak_near", "cheer_B_peak_mid", "roar_stadium_short_near", "roar_stadium_short_mid",
    "roar_goal_short_near", "roar_goal_short_mid", "cheer_B_short_near", "cheer_B_short_mid",
    "cheer_A_short_near", "cheer_A_short_mid", "gq_big_", "gq_soft_", "whistles_", "vuvuzela_swell_",
    "grumble_", "groan_", "pregreen_buildup_near", "pregreen_buildup_mid", "green_flag_roar_near",
    "helicopter_low_hover", "helicopter_flyover_", "helicopter_approach", "helicopter_pass_close", "pa_far_",
]


def _f(x, d=0.0):
    try:
        x = float(x)
        return x if math.isfinite(x) else d
    except (TypeError, ValueError):
        return d


def db2lin(db):
    return float(10 ** (db / 20.0))


def lin2db(x):
    return 20 * math.log10(max(float(x), 1e-9))


def wrap(p):
    p = p % 1.0
    return p + 1.0 if p < 0 else p


# =================================================================== track maps
class Stand:
    def __init__(self, d):
        g = _ci(d)
        self.name = str(g("Name", "Grandstand"))
        self.frm = wrap(float(g("From", 0.0)))
        self.to = wrap(float(g("To", 0.0)))
        self.side = "R" if str(g("Side", "L")).upper().startswith("R") else "L"
        self.offset = max(5.0, float(g("Offset", 40.0)))
        self.size = int(g("Size", 2))
        self.vibe = str(g("Vibe", "stand")).lower()

    @property
    def sign(self):                      # + = right of the car in the direction of travel
        return 1.0 if self.side == "R" else -1.0

    @property
    def length(self):
        return self.to - self.frm if self.to >= self.frm else self.to + 1 - self.frm

    @property
    def mid(self):
        return wrap(self.frm + self.length / 2)

    def emitters(self, L, spacing=160.0):
        n = max(1, int(round(self.length * L / spacing)))
        return [wrap(self.frm + self.length * (i + 0.5) / n) for i in range(n)]

    def closest(self, at):
        """The point of the stand nearest a lap fraction (the stand is a line beside the track)."""
        if wrap(at - self.frm) <= self.length:
            return wrap(at)
        a, b = abs(wrap(at - self.frm + 0.5) - 0.5), abs(wrap(at - self.to + 0.5) - 0.5)
        return self.frm if a <= b else self.to


class TrackMap:
    def __init__(self, d=None, source=""):
        g = _ci(d or {})
        self.track = str(g("Track", "") or "")
        self.match = [str(m).lower() for m in (g("Match", []) or []) if str(m).strip()]
        self.length_m = float(g("LengthMeters", 0) or 0)
        self.pa_at = wrap(float(g("PaAt", 0.0) or 0.0))
        self.stands = sorted((Stand(s) for s in (g("Stands", []) or [])), key=lambda s: s.frm)
        self.source = source

    def matches(self, track_id, track_name):
        a, b = (track_id or "").lower(), (track_name or "").lower()
        return any(m in a or m in b for m in self.match)


def _ci(d):
    """Case-insensitive getter (the SimHub add-on read its JSON case-insensitively)."""
    low = {str(k).lower(): v for k, v in (d.items() if isinstance(d, dict) else [])}
    return lambda k, default=None: low.get(k.lower(), default)


def find_track(folders, track_id, track_name, log=None):
    """Last match wins: bundled maps first, the user's own after (same rule as the add-on)."""
    best = None
    for folder in folders:
        try:
            files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".json"))
        except OSError:
            continue
        for f in files:
            p = os.path.join(folder, f)
            try:
                with open(p, encoding="utf-8-sig") as fh:
                    m = TrackMap(json.load(fh), p)
            except Exception as e:
                if log:
                    log(f"[crowd] track file {f} unreadable: {e}")
                continue
            if m.matches(track_id, track_name):
                best = m
    return best


def fallback_map(name):
    return TrackMap({"Track": name or "Unknown track", "PaAt": 0.0,
                     "Stands": [{"Name": "Main grandstand", "From": 0.975, "To": 0.03, "Side": "L",
                                 "Offset": 45, "Size": 3, "Vibe": "main"}]})


# =================================================================== sounds
class Clip:
    __slots__ = ("name", "data", "frames", "gain")

    def __init__(self, name, data, gain=1.0):
        self.name, self.data, self.frames, self.gain = name, data, len(data), gain


def measure(x, rate=RATE):
    """(loudness dBFS, peak dBFS) of a float clip. Loudness = RMS of the louder half of 50 ms windows,
    so a short cheer with silence around it isn't pushed up too far."""
    mono = np.abs(x).max(axis=1) if x.ndim > 1 else np.abs(x)
    peak = float(mono.max()) if len(mono) else 0.0
    w = max(1, int(rate * 0.05))
    n = len(x) // w
    if n == 0:
        rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    else:
        sq = np.square(x[:n * w].astype(np.float64)).reshape(n, w, -1).mean(axis=(1, 2))
        top = np.sort(sq)[n // 2:]
        rms = float(np.sqrt(top.mean())) if len(top) else 0.0
    return lin2db(rms), lin2db(peak)


def norm_gain(rms_db, peak_db):
    """Gain that brings a file to TARGET_RMS_DB, never lifting its peak over FILE_PEAK_DB."""
    if rms_db < -90:
        return 0.0                                  # digital silence: leave it silent
    return min(db2lin(TARGET_RMS_DB - rms_db), db2lin(FILE_PEAK_DB - peak_db))


def _resample(x, sr, rate):
    if sr == rate:
        return x
    try:
        import soxr
        return soxr.resample(x, sr, rate).astype(np.float32)
    except Exception:
        pass
    try:
        from scipy.signal import resample_poly
        g = math.gcd(int(sr), int(rate))
        return resample_poly(x, rate // g, sr // g, axis=0).astype(np.float32)
    except Exception:
        t = np.arange(0, len(x), sr / rate)
        return np.stack([np.interp(t, np.arange(len(x)), x[:, c]) for c in range(x.shape[1])], 1).astype(np.float32)


def load_sounds(folder, cache_path=None, rate=RATE, log=print):
    """Every .wav / .flac / .ogg in the folder -> {name: Clip}, normalised, stereo int16 at `rate`.
    A file that can't be read (or holds NaN/inf) is skipped. Gains are measured once and cached."""
    import soundfile as sf
    clips = {}
    try:
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith((".wav", ".flac", ".ogg")))
    except OSError:
        return clips
    cache = {}
    if cache_path:
        try:
            with open(cache_path, encoding="utf-8") as fh:
                cache = json.load(fh)
        except Exception:
            cache = {}
    changed = False
    for f in files:
        p = os.path.join(folder, f)
        try:
            st = os.stat(p)
            x, sr = sf.read(p, dtype="float32", always_2d=True)
            if x.size == 0 or not np.isfinite(x).all():
                raise ValueError("empty or broken samples")
            if x.shape[1] == 1:
                x = np.repeat(x, 2, axis=1)
            elif x.shape[1] > 2:
                x = x[:, :2]
            x = x[: int(sr * MAX_FILE_SECONDS)]
            x = _resample(x, sr, rate)
            key = f"{f}|{st.st_size}|{int(st.st_mtime)}"
            ent = cache.get(f)
            if not ent or ent.get("key") != key:
                rms_db, peak_db = measure(x, rate)
                ent = {"key": key, "rms_db": round(rms_db, 2), "peak_db": round(peak_db, 2),
                       "gain": round(norm_gain(rms_db, peak_db), 5)}
                cache[f] = ent; changed = True
            gain = max(0.0, min(float(ent["gain"]), 1000.0))
            y = np.clip(x * gain, -1.0, 1.0)
            data = np.ascontiguousarray((y * 32767).astype(np.int16))
            name = os.path.splitext(f)[0]
            clips[name] = Clip(name, data, gain)
        except Exception as e:
            log(f"[crowd] skipped {f}: {e}")
    if cache_path and changed:
        try:
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(cache, fh, indent=1)
        except OSError:
            pass
    return clips


# =================================================================== mixer
class Voice:
    """One playing sound. The director writes target/pan/level; the audio thread glides toward them."""
    __slots__ = ("clip", "pos", "loop", "level", "gain", "target", "pan", "gl", "gr", "fade", "fade_target",
                 "delay", "done", "family", "at", "offset", "side", "maxd", "tag")

    def __init__(self, clip, level, loop, delay_frames, family, pan):
        self.clip, self.loop, self.family = clip, loop, family
        self.level = max(0.0, min(2.0, float(level)))
        self.pos = random.randrange(clip.frames) if loop and clip.frames > 1 else 0
        self.gain, self.target = 0.0, 1.0
        self.pan = max(-1.0, min(1.0, float(pan)))
        self.gl = self.gr = None
        self.fade, self.fade_target = 0.0, 1.0       # every sound fades in
        self.delay = int(max(0, delay_frames))
        self.done = False
        self.at, self.offset, self.side, self.maxd, self.tag = None, 0.0, 0.0, 700.0, 1.0

    def stop(self):
        self.fade_target = 0.0


def _pan_gains(pan):
    a = (max(-1.0, min(1.0, pan)) + 1) * math.pi / 4
    return min(1.0, math.sqrt(2) * math.cos(a)), min(1.0, math.sqrt(2) * math.sin(a))


class Mixer:
    """Mixes in the audio callback with buffers allocated once. render() is also used offline (tests)."""
    WATCHDOG_S = 1.0          # no update from the director for this long -> fade to silence
    DUCK = db2lin(-9)         # crowd level while the radio is talking

    def __init__(self, max_voices=6, rate=RATE, block=BLOCK, log=print):
        self.rate, self.block, self.max_voices, self.log = rate, block, max_voices, log
        self.voices, self._new = [], deque()
        self._lock = threading.Lock()
        self.volume = 0.3                       # master (0..1)
        self.ceiling = db2lin(-18)              # hard output ceiling (linear peak)
        self.muted = False
        self.master = 0.0                       # current master gain (glides)
        self.lim = 1.0                          # limiter gain
        self.duck_fn = None                     # -> True while someone talks on the radio
        self.duck_on = True
        self._duck = 1.0
        self.helmet_target, self.helmet = 0.0, 0.0     # 2026-10-26 (#230): crowd heard through a helmet while driving
        self._hz = None
        self.last_beat = time.monotonic()
        self.clock = time.monotonic
        self.test_until = 0.0
        self.errors, self.failed = 0, False
        self.peak_out = 0.0                     # last block's output peak (for status / tests)
        self._quiet = 0
        self.stream = None
        self.device_error = ""
        n = block
        self._mix = np.zeros((n, 2), np.float32)
        self._tmp = np.zeros((n, 2), np.float32)
        self._abs = np.zeros((n, 2), np.float32)
        self._rl = np.zeros(n, np.float32); self._rr = np.zeros(n, np.float32); self._rm = np.zeros(n, np.float32)
        self._lpb = np.zeros((n, 2), np.float32)
        self._base = (np.arange(n, dtype=np.float32) / n)
        self._i16 = np.float32(1 / 32768)
        # 2026-10-26 (#205): an echo under bridges / in tunnels (two taps + feedback), gliding in and out
        self.echo_target, self.echo = 0.0, 0.0
        self._eb = np.zeros((rate, 2), np.float32); self._ew = 0

    # ---------- control (any thread) ----------
    def heartbeat(self):
        self.last_beat = self.clock()

    def set_ceiling_db(self, db):
        try:
            db = float(db)
        except (TypeError, ValueError):
            db = -18.0
        if not math.isfinite(db):
            db = -18.0
        self.ceiling = db2lin(max(CEILING_MIN_DB, min(CEILING_MAX_DB, db)))

    def set_volume(self, v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        self.volume = max(0.0, min(1.0, v)) if math.isfinite(v) else 0.0

    def count(self):
        with self._lock:
            return sum(1 for v in self.voices if not v.done) + len(self._new)

    def playing(self, family):
        with self._lock:
            return any(v.family == family and not v.done and v.fade_target > 0 for v in list(self.voices) + list(self._new))

    def play(self, clip, level=1.0, loop=False, delay=0.0, family=None, pan=0.0, reserve=0):
        """Start a sound. None if there's no room (N voices) or the same family is already playing."""
        if clip is None or self.failed:
            return None
        with self._lock:
            live = [v for v in self.voices if not v.done] + list(self._new)
            if len(live) + reserve >= self.max_voices:
                return None
            if family and any(v.family == family and v.fade_target > 0 for v in live):
                return None                              # no stacking of the same event
            v = Voice(clip, level, loop, delay * self.rate, family, pan)
            self._new.append(v)
            return v

    def stop_all(self):
        with self._lock:
            for v in self.voices:
                v.fade_target = 0.0
            for v in self._new:
                v.fade_target = 0.0; v.done = True
            self._new.clear()

    def _want_master(self):
        now = self.clock()
        if now < self.test_until:
            return self.volume
        if self.muted or now - self.last_beat > self.WATCHDOG_S:
            return 0.0
        if simload.BUSY:                       # #454: loading screen - the crowd fades out (glides, never clicks)
            return 0.0
        return self.volume

    # ---------- audio thread ----------
    def render(self, out):
        """Fill out (frames x 2 float32). Never raises; on any problem the block is silent."""
        try:
            frames = len(out)
            if frames > self.block:                    # never expected; split, no new buffers
                for i in range(0, frames, self.block):
                    self.render(out[i:i + self.block])
                return
            if not self.voices and not self._new and self.master < 1e-5:
                out[:] = 0                             # idle: nothing to mix
                self.peak_out = 0.0
                return
            mix = self._mix[:frames]
            mix.fill(0)
            with self._lock:
                while self._new:
                    self.voices.append(self._new.popleft())
            for v in self.voices:
                self._voice(v, mix, frames)
            if any(v.done for v in self.voices):
                with self._lock:
                    self.voices = [v for v in self.voices if not v.done]
            self._finish(mix, out)
        except Exception as e:
            out[:] = 0
            self.errors += 1
            if self.errors <= 3:
                try: self.log(f"[crowd] audio error, silent: {e!r}")
                except Exception: pass
            if self.errors > 20:
                self.failed = True
                self.stop_all()

    def _voice(self, v, mix, frames):
        if v.done:
            return
        c = v.clip
        if v.delay >= frames:
            v.delay -= frames
            return
        start, v.delay = v.delay, 0
        tmp = self._tmp[:frames]
        if start:
            tmp[:start] = 0
        i, n, end = start, c.frames, False
        while i < frames:
            take = min(frames - i, n - v.pos)
            if take <= 0:
                if v.loop and n > 1:
                    v.pos = 0
                    continue
                tmp[i:] = 0
                end = True
                break
            np.multiply(c.data[v.pos:v.pos + take], self._i16, out=tmp[i:i + take], casting="unsafe")
            v.pos += take; i += take
        # glides: level ~80 ms, fade in 0.25 s / out 0.6 s, pan ~100 ms
        r = self.rate
        g0 = v.gain
        tg = max(0.0, min(2.0, v.target * v.level)) if math.isfinite(v.target) else 0.0
        g1 = g0 + (tg - g0) * min(1.0, frames / (r * 0.08))
        f0 = v.fade
        f1 = max(v.fade_target, f0 - frames / (r * 0.6)) if v.fade_target < f0 else min(v.fade_target, f0 + frames / (r * 0.25))
        tl, tr = _pan_gains(v.pan)
        if v.gl is None:
            v.gl, v.gr = tl, tr
        k = min(1.0, frames / (r * 0.10))
        l0, r0 = v.gl, v.gr
        l1, r1 = l0 + (tl - l0) * k, r0 + (tr - r0) * k
        a0, a1 = g0 * f0, g1 * f1
        base = self._base[:frames] * (self.block / frames) if frames != self.block else self._base
        rl, rr = self._rl[:frames], self._rr[:frames]
        np.multiply(base, a1 * l1 - a0 * l0, out=rl); rl += a0 * l0
        np.multiply(base, a1 * r1 - a0 * r0, out=rr); rr += a0 * r0
        tmp[:, 0] *= rl; tmp[:, 1] *= rr
        mix += tmp
        v.gain, v.fade, v.gl, v.gr = g1, f1, l1, r1
        if end or (v.fade_target <= 0 and f1 <= 0.001):
            v.done = True

    def _finish(self, mix, out):
        frames = len(mix)
        if self.echo_target > 0 or self.echo > 1e-3:
            self.echo += (self.echo_target - self.echo) * min(1.0, frames / (self.rate * 0.06))   # quick: a bridge is ~0.25 s
            eb, n, w = self._eb, len(self._eb), self._ew
            idx = (w + np.arange(frames)) % n
            d1 = eb[(idx - int(0.083 * self.rate)) % n]; d2 = eb[(idx - int(0.131 * self.rate)) % n]
            wet = (d1 * 0.6 + d2[:, ::-1] * 0.45)
            eb[idx] = mix + wet * 0.35
            mix += wet * self.echo
            self._ew = (w + frames) % n
        # 2026-10-26 (#230): driving, you hear the crowd through your helmet in a closed cockpit - duller (top end
        # rolled off from about 1.8 kHz) and quieter. An onboard REPLAY is you watching, so it stays open.
        if self.helmet_target > 0 or self.helmet > 1e-3:
            self.helmet += (self.helmet_target - self.helmet) * min(1.0, frames / (self.rate * 0.5))
            if _lfilter is not None:
                if self._hz is None:
                    from scipy.signal import butter
                    self._hb, self._ha = butter(2, 1800, btype="low", fs=self.rate)
                    self._hz = np.zeros((2, 2))
                lp = self._lpb[:frames]                 # 2026-10-29: buffer made once (this runs every block while driving)
                for ch in range(2):
                    lp[:, ch], self._hz[:, ch] = _lfilter(self._hb, self._ha, mix[:, ch], zi=self._hz[:, ch])
                h = self.helmet
                mix *= (1 - h)
                mix += lp * (h * 0.6)                   # muffled and about 4.5 dB down
                # master (volume x mute x watchdog x radio duck), gliding so mute/unmute never clicks
        want = self._want_master()
        talking = False
        if self.duck_on and self.duck_fn:
            try:
                talking = bool(self.duck_fn())
            except Exception:
                talking = False
        dk = self.DUCK if talking else 1.0
        self._duck += (dk - self._duck) * min(1.0, frames / (self.rate * (0.12 if dk < self._duck else 0.6)))
        m0 = self.master
        if want <= 0:                                   # muting: a straight 0.3 s fade to true silence
            m1 = max(0.0, m0 - frames / (self.rate * 0.3))
        else:
            m1 = m0 + (want * self._duck - m0) * min(1.0, frames / (self.rate * 0.25))
        base = self._base[:frames] * (self.block / frames) if frames != self.block else self._base
        rm = self._rm[:frames]
        np.multiply(base, m1 - m0, out=rm); rm += m0
        mix *= rm[:, None]
        self.master = m1
        # fully faded out for 2 s (watchdog / mute): let go of every voice so nothing runs in the dark
        if want == 0 and m1 < 1e-4:
            self._quiet += 1
            if self._quiet * frames > self.rate * 2:
                for v in self.voices:
                    v.done = True
        else:
            self._quiet = 0
        ab = self._abs[:frames]
        np.abs(mix, out=ab)
        peak = float(ab.max()) if frames else 0.0
        if not math.isfinite(peak):                     # NaN / inf anywhere: this block is silence
            out[:] = 0
            self.lim = 0.05
            self.errors += 1
            self.peak_out = 0.0
            return
        # peak limiter: instant attack (whole block), slow release, never above the ceiling...
        ceil = self.ceiling
        room = ceil * 0.98 / peak if peak > 1e-9 else 1.0
        if room < self.lim:
            g0 = g1 = room
        else:
            g0, g1 = self.lim, min(room, 1.0, self.lim + (1.0 - self.lim) * 0.05)
        np.multiply(base, g1 - g0, out=rm); rm += g0
        np.multiply(mix, rm[:, None], out=out)
        self.lim = g1
        # ...and a hard clip at the ceiling as the last word
        np.clip(out, -ceil, ceil, out=out)
        np.abs(out, out=ab)
        self.peak_out = float(ab.max()) if frames else 0.0

    # ---------- device ----------
    def start(self, device=None):
        self.close()
        try:
            import sounddevice as sd

            def cb(outdata, frames, t, status):
                self.render(outdata)
                for tap in list(TAPS):                     # #515: the broadcast player gets a copy (never blocks)
                    try:
                        tap(outdata)
                    except Exception:
                        pass
            # 2026-10-27 (#451, request: radio + crowd "chopping" in the race): a bigger cushion - 120 ms of sound queued
            # ahead - so a moment of the app being busy (or the PC loaded by VR) never reaches the ears as a gap
            self.stream = sd.OutputStream(samplerate=self.rate, channels=2, dtype="float32", device=device,
                                          callback=cb, blocksize=max(self.block, 2048), latency=0.4)   # 2026-10-29: 0.4 s cushion
            self.stream.start()
            self.device_error = ""
            return True
        except Exception as e:
            self.stream = None
            self.device_error = str(e)[:160]
            self.log(f"[crowd] sound device problem, crowd stays silent: {e!r}")
            return False

    def close(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop(); s.close()
            except Exception:
                pass


# =================================================================== director
class CarState:
    __slots__ = ("id", "is_player", "pos", "cpos", "progress", "in_pits")

    def __init__(self, id, is_player, pos, cpos, progress, in_pits):
        self.id, self.is_player, self.pos, self.cpos, self.progress, self.in_pits = id, is_player, pos, cpos, progress, in_pits


class Frame:
    """What the director needs each tick (tiny, built from the brain)."""
    def __init__(self, **kw):
        self.running = True
        self.on_track = True
        self.in_pits = False
        self.track_id = self.track_name = self.session = ""
        self.track_len = 0.0
        self.pct = 0.0
        self.speed_kmh = 0.0
        self.lap = 0
        self.green = self.white = self.chequered = False      # rising edges come from the brain
        self.before_green = False                              # we were here before the start (no roar when joining mid-race)
        self.spin = False                                      # the brain saw us spin / crash this tick
        self.tv = False                                        # replay/spectating on a TV-style camera (2026-10-25)
        self.cut = False                                       # the camera just cut (other camera or other car)
        self.aerial = False                                    # helicopter / blimp camera: the crowd goes quiet
        self.rain = 0.0; self.wet = 0.0; self.wind_ms = 0.0    # weather (2026-10-26, #204)
        self.night = False
        self.follow = None                                     # the car on screen
        self.cars = []
        self.cars_running = None                               # cars out on the circuit (None = unknown) (2026-10-26, #220)
        self.empty = False                                     # nobody running: no crowd, no race atmosphere
        self.sstate = 0                                        # iRacing SessionState: 1 get in car, 2 warm-up, 3 formation, 4 racing
        self.driving = False                                   # we are driving (live, our own onboard camera) (#230)
        self.hero = None                                       # C1 (#283): the "home hero" car's CarIdx, if one is set
        self.cam = ""                                          # the camera group name on air (W5)
        self.caution = False                                   # full-course caution out (C2)
        self.__dict__.update(kw)

    @property
    def is_race(self):
        return "race" in (self.session or "").lower()


class Stage:
    """Per-grandstand state."""
    def __init__(self, stand, L, idx, now):
        self.s = stand
        self.emit = stand.emitters(L)
        self.E = 0.0
        self.bed = None; self.bed_near = None
        self.last_react = -99.0; self.last_groan = -99.0; self.pending_until = -1.0
        self.approach_lap = -1
        r = random.Random(hash(stand.name) ^ (idx * 7919))
        beds = ["bed_stadium_crowd", "bed_crowd_buzz_mid", "bed_crowd_excited_mid", "bed_stadium_crowd"]
        if stand.vibe == "main" or stand.size >= 3:
            self.near, self.far, self.life_rate = "bed_crowd_roar_mid", "bed_stadium_crowd_far", 1.6
        elif stand.vibe == "campsite":
            self.near, self.far, self.life_rate = "bed_crowd_buzz_mid", "bed_crowd_buzz_mid", 1.3
        elif stand.size <= 1:
            self.near = self.far = "bed_crowd_buzz_mid"; self.life_rate = 0.6
        else:
            b = beds[idx % len(beds)]
            self.near = "bed_stadium_crowd_near" if b == "bed_stadium_crowd" else b
            self.far = "bed_stadium_crowd_far" if b == "bed_stadium_crowd" else b
            self.life_rate = 1.0
        self.char = 0.8 + 0.4 * r.random()
        self.next_life = now + r.random() * 4


SMALL, NORMAL, BIG = 0, 1, 2


class Director:
    """The C# Director, in Python. Simplified: 1-D geometry (lap distance + stand offset, stereo side)
    instead of the learned 3-D track shape; one bed per nearby stand (the two closest) instead of one per
    emitter; no surround / cockpit-muffle filtering - distance comes from the _near/_mid/_far recordings."""
    BED_SLOTS = 2

    def __init__(self, mixer, clips, track_folders=(), settings=None, rng=None, log=print):
        self.m, self.clips, self.folders, self.log = mixer, clips, list(track_folders), log
        self._base_clips = None
        self.s = settings
        self.rnd = rng or random.Random()
        self.now = 0.0
        self.L, self.lp = 4000.0, 0.0
        self.map, self.stands = None, []
        self.loaded_for = None
        self.status = "waiting for a session"
        self.passes_seen = self.crashes_seen = 0
        self._gain_lap, self._gain_pos, self.lap_gain = None, None, 0
        self._last_clip = {}
        self._prev_prog = {}
        self._pair_cool = {}
        self._motion = {}
        self._family_cool = {}
        self.green_seen = self.white_seen = self.chequer_seen = self.build_started = False
        self.cool_until = 0.0
        self.chequer_t = None
        if getattr(self, "amb", None) is not None:
            self.amb._podium_done = False
        self.next_heli = self.next_pa = 0.0
        self.silent = True
        # helicopter camera bed: a recording of your own (heli_cabin*) if there is one, else the made-up one
        bl = sorted(k for k in clips if k.lower().startswith("blimp_cabin"))
        self.blimp_clip = clips[bl[0]] if bl else None
        own = sorted(k for k in clips if k.lower().startswith("heli_cabin"))
        self.cabin_clip = clips[own[0]] if own else None
        if self.cabin_clip is None:
            try:
                from . import heli_cabin
                self.cabin_clip = heli_cabin.clip(Clip)
            except Exception as e:
                log(f"[crowd] helicopter cabin sound: {e!r}")
        self.cabin = None
        # 2026-10-26 (#204-206): weather, night, bridges, pit stops - sounds made in code, kept in Trackside\synth
        self.night_scale = 1.0
        self.amb = None
        try:
            from . import ambience
            amb_clips = ambience.load_or_make(Clip, clips, os.path.join(TS_DIR, "synth"), log)
            self.clips.update({k: v for k, v in amb_clips.items() if k not in self.clips})
            self.amb = ambience.Ambience(self, amb_clips, log)
        except Exception as e:
            log(f"[crowd] ambience: {e!r}")
        self.names = sorted(clips)
        self.pan_scale = 1.0       # 1 = onboard (stands pan left/right), 0 = TV camera (wide, unpanned bed)
        self.cut_duck = 0.0        # short dip on camera cuts so the sound doesn't jump

    # ---------- settings ----------
    def opt(self, k, d):
        return getattr(self.s, k, d) if self.s is not None else d

    # ---------- per tick ----------
    def update(self, f, dt):
        self.now += max(0.0, min(0.25, dt))
        self.m.heartbeat()
        mute_pits = self.opt("crowd_mute_pits", True)
        off = not self.opt("crowd_on", True) or self.opt("crowd_mute", False) or not f.running
        aerial = getattr(f, "aerial", "") or ""
        aerial = ("chopper" if aerial is True else aerial) if aerial else ""
        self.trackside_cam = bool(f.running and getattr(f, "tv", False) and not aerial)   # #229: read by the sound mix
        # 2026-10-26 (#41): the helicopter camera sounds like sitting in the broadcast chopper (no crowd up there)
        # 2026-10-26 (#203): the blimp camera gets the inside of the Goodyear blimp (blimp_cabin*), the chopper camera the helicopter
        clip = (self.blimp_clip or self.cabin_clip) if aerial == "blimp" else self.cabin_clip
        if aerial and not off and self.opt("crowd_heli_cabin", True) and clip is not None:
            self.m.muted = False
            if not self.silent:
                self.silence()
            self.silent = True                       # stands get reloaded when we come back down
            if self.cabin is not None and self.cabin.clip is not clip:
                self.cabin.stop(); self.cabin = None # blimp <-> chopper cut: swap the sound
            if self.cabin is None or self.cabin.done or self.cabin.fade_target <= 0:
                self.cabin = self.m.play(clip, level=0.8, loop=True, delay=1.0 if f.cut else 0.3, family="cabin")
            return
        if self.cabin is not None:
            self.cabin.stop(); self.cabin = None
        quiet = (off or (mute_pits and (not f.on_track or f.in_pits))
                 or aerial)      # 2026-10-25 (driver request): "the helicopter has crowd sounds"
        self.m.muted = bool(quiet)
        if quiet:
            if not self.silent:
                self.silence()
            return
        self.silent = False
        key = f"{f.track_id}|{f.track_name}|{f.session}".lower()
        if key != self.loaded_for:
            self.load(f, key)
        # 2026-10-26 (#220, request: "some of those crowd noises can't play if there are no cars on track"): with
        # nobody out on the circuit (3 s, so a single car crossing the pit exit doesn't flicker it) the stands go
        # quiet and the race-day atmosphere stops; weather, night insects and the fairground carry on.
        # #230 helmet while driving; #231 how full the stands are by session; #232 rain softens the crowd
        self.m.helmet_target = 1.0 if (getattr(f, "driving", False) and self.opt("crowd_helmet", True)) else 0.0
        sess = (f.session or "").lower()
        self.sess_scale = (0.35 if "practice" in sess or "test" in sess else 0.65 if "qual" in sess
                           else 0.5 if "warm" in sess else 1.0 if "race" in sess else 0.8)
        self.rain_now = max(0.0, min(1.0, float(getattr(f, "rain", 0.0) or 0.0)))
        cr = getattr(f, "cars_running", None)
        if cr is None or cr > 0:
            self._cars_seen = self.now
        f.empty = self.now - getattr(self, "_cars_seen", -99.0) > 3.0
        if f.empty:
            for st in self.stands:
                if st.bed is not None:
                    st.bed.stop(); st.bed = None
            self.pre_race(f, waiting=True, formation=False)
            if self.amb is not None:
                try:
                    self.amb.update(f, dt)
                except Exception as e:
                    if not getattr(self, "_amb_err", False):
                        self._amb_err = True; self.log(f"[crowd] ambience: {e!r}")
            return
        if f.track_len > 100:
            self.L = f.track_len
        elif self.map and self.map.length_m > 0:
            self.L = self.map.length_m
        # 2026-10-25: onboard cameras travel with the car; TV cameras (replays / spectating) hear the area
        # of the car being shown, unpanned and following slowly; cuts get a half-second dip
        target = wrap(f.pct)
        if f.cut:
            self.lp, self.cut_duck = target, 1.0
        elif f.tv:
            d = wrap(target - self.lp)
            if d > 0.5:
                d -= 1
            self.lp = wrap(self.lp + d * min(1.0, dt / 1.5)) if abs(d) * self.L < 600 else target
        else:
            self.lp = target
        self.pan_scale += ((0.0 if f.tv else 1.0) - self.pan_scale) * min(1.0, dt / 0.4)
        self.cut_duck = max(0.0, self.cut_duck - dt / 0.5)
        self.beds()
        st_ = int(getattr(f, "sstate", 0) or 0)
        self.pre_race(f, waiting=f.is_race and 0 < st_ < 3 and not self.green_seen,
                      formation=f.is_race and st_ == 3 and not self.green_seen)
        if f.is_race:
            self.race_events(f)
            self.cooldown(f)
        self.passes(f)
        self.crashes(f)
        self.approaches(f)
        self.ambient(f)
        if self.amb is not None:
            try:
                self.amb.update(f, dt)
            except Exception as e:
                if not getattr(self, "_amb_err", False):
                    self._amb_err = True; self.log(f"[crowd] ambience: {e!r}")
        self.spatialise()
        for st in self.stands:
            st.E = max(0.0, st.E - dt * 0.06)

    def silence(self):
        self.m.stop_all()
        for st in self.stands:
            st.bed = None
        self.silent = True

    def _track_pack(self, f):
        """C5 (#284): per-track crowd packs. Trackside\\track_sounds\\<track>\\ (e.g. daytona, lemans, spa) holds
        recordings with the same names as the normal crowd sounds; at that track they replace the normal ones."""
        root = getattr(self, "pack_root", None)
        if self._base_clips is None:
            self._base_clips = dict(self.clips)
        self.clips.clear(); self.clips.update(self._base_clips)
        self.names = sorted(self.clips)
        if not root or not os.path.isdir(root):
            return
        key = "".join(ch for ch in (f.track_id or f.track_name or "").lower() if ch.isalnum())
        for d in sorted(os.listdir(root)):
            k = "".join(ch for ch in d.lower() if ch.isalnum())
            if k and key.startswith(k) and os.path.isdir(os.path.join(root, d)):
                pack = load_sounds(os.path.join(root, d), os.path.join(root, d, "levels.json"), log=self.log)
                self.clips.update(pack)
                self.names = sorted(self.clips)
                if pack:
                    self.log(f"[crowd] {d}: {len(pack)} track sounds")
                break

    def load(self, f, key):
        self.silence(); self.silent = False
        self.loaded_for = key
        try:
            self._track_pack(f)
        except Exception as e:
            self.log(f"[crowd] track sounds: {e!r}")
        try:
            self.heli_prepare()
        except Exception:
            pass
        self._prev_prog.clear(); self._motion.clear(); self._pair_cool.clear()
        self.green_seen = self.white_seen = self.chequer_seen = self.build_started = False
        self.passes_seen = self.crashes_seen = 0
        self._gain_lap, self._gain_pos, self.lap_gain = None, None, 0
        m = find_track(self.folders, f.track_id, f.track_name, self.log)
        self.map = m or fallback_map(f.track_name)
        if f.track_len > 100:
            self.L = f.track_len
        elif self.map.length_m > 0:
            self.L = self.map.length_m
        self.stands = [Stage(s, self.L, i, self.now) for i, s in enumerate(self.map.stands)]
        self.next_heli = self.now + 25 + self.rnd.random() * 20
        self.next_pa = self.now + 15 + self.rnd.random() * 15
        self.status = f"{self.map.track}: {len(self.stands)} grandstands" + ("" if m else " (no track file - start/finish only)")
        self.log(f"[crowd] {self.status}")

    # ---------- geometry ----------
    def along(self, at):
        d = wrap(at - self.lp)
        if d > 0.5:
            d -= 1
        return d * self.L

    def dist(self, at, offset):
        a = self.along(at)
        return math.sqrt(a * a + offset * offset)

    @staticmethod
    def max_d(stand):
        return 950.0 if stand.size >= 3 else 700.0 if stand.size == 2 else 480.0

    @staticmethod
    def fall(d, maxd):
        """Full up close, a steep drop, then a hard stop - the track goes quiet between crowds."""
        g = 1.0 if d <= 45 else (45.0 / d) ** 1.6
        if d > maxd - 150:
            g *= max(0.0, (maxd - d) / 150)
        return g

    @staticmethod
    def size_gain(stand):
        return 1.45 if stand.size >= 3 else 1.0 if stand.size == 2 else 0.6

    def gains_for(self, at, offset, side, maxd):
        """(gain, pan) of a sound at lap fraction `at`, `offset` m off the track on `side` (+1 right)."""
        d = self.dist(at, offset)
        return self.fall(d, maxd), side * min(0.92, offset / max(1.0, d)) * self.pan_scale, d

    def nearest_stand(self, at, max_m=1e9):
        best, bd = None, max_m
        for st in self.stands:
            d = abs(wrap(st.s.closest(at) - at + 0.5) - 0.5) * self.L
            if d < bd:
                best, bd = st, d
        return best

    def stands_near(self, at, max_m):
        return [st for st in self.stands if abs(wrap(st.s.closest(at) - at + 0.5) - 0.5) * self.L <= max_m]

    def place(self, v, at, offset, side, maxd=None):
        if v is None:
            return None
        v.at, v.offset, v.side = at, offset, side
        if maxd is None:
            st = self.nearest_stand(at, 400)
            maxd = self.max_d(st.s) if st else 700.0
        v.maxd = maxd
        v.target, v.pan, _ = self.gains_for(at, offset, side, maxd)
        v.target *= 1.0 - 0.65 * self.cut_duck
        return v

    def spatialise(self):
        for v in list(self.m.voices) + list(self.m._new):
            if v.at is None or v.done:
                continue
            g, pan, _ = self.gains_for(v.at, v.offset, v.side, v.maxd)
            ns = (self.night_scale * getattr(self, "pre_scale", 1.0) * getattr(self, "sess_scale", 1.0) * getattr(self, "cam_scale", 1.0)
                  * (1.0 - 0.3 * getattr(self, "rain_now", 0.0))) if str(v.family or "").startswith("bed:") else 1.0
            v.target, v.pan = g * v.tag * ns * (1.0 - 0.65 * self.cut_duck), pan

    # ---------- clips ----------
    def get(self, name):
        return self.clips.get(name)

    def has(self, prefix):
        p = prefix.lower()
        return any(n.lower().startswith(p) for n in self.names)

    def pick(self, prefix):
        """Random clip of a family, never the same twice running."""
        p = prefix.lower()
        opts = [n for n in self.names if n.lower().startswith(p)]
        if not opts:
            return None
        last = self._last_clip.get(prefix)
        pool = [n for n in opts if n != last] or opts
        n = self.rnd.choice(pool)
        self._last_clip[prefix] = n
        return self.clips[n]

    def variant(self, family, d):
        """The recording made for about this distance, falling back to what exists."""
        want = "_near" if d < 120 else "_mid" if d < 400 else "_far"
        order = {"_near": ("_near", "_mid", "_far"), "_mid": ("_mid", "_near", "_far"), "_far": ("_far", "_mid", "_near")}[want]
        for suf in order:
            if self.has(family + suf):
                return family + suf
        return family

    def one(self, prefix, level, at, offset, side, delay=0.0, family=None, reserve=0, maxd=None):
        """Play one placed sound of a family; no stacking (same family) and a short per-family cooldown."""
        fam = family or prefix.rstrip("_")
        if self.now < self._family_cool.get(fam, -1):
            return None
        c = self.pick(prefix)
        if c is None:
            return None
        v = self.m.play(c, level, False, delay, family=fam, reserve=reserve)
        if v is not None:
            self._family_cool[fam] = self.now + 1.0
            self.place(v, at, offset, side, maxd)
        return v

    # ---------- beds ----------
    def beds(self):
        ranked = []
        for st in self.stands:
            d = self.dist(st.s.closest(self.lp), st.s.offset)
            ranked.append((d, st))
        ranked.sort(key=lambda t: t[0])
        want = {id(st) for d, st in ranked[:self.BED_SLOTS] if d < self.max_d(st.s) + 150}
        for d, st in ranked:
            if id(st) not in want:
                if st.bed is not None:
                    st.bed.stop(); st.bed = None
                continue
            near = d < (180 if st.bed_near else 140)          # hysteresis
            name = st.near if near else st.far
            if st.bed is not None and st.bed.done:
                st.bed = None
            if st.bed is None or (st.bed_near != near and st.bed.clip.name != (self.get(name) or st.bed.clip).name):
                c = self.get(name) or self.get("bed_stadium_crowd_near" if near else "bed_stadium_crowd_far") or self.get(st.far) or self.get(st.near)
                if c is not None:
                    v = self.m.play(c, (0.55 if near else 0.7) * self.size_gain(st.s) * st.char, loop=True, family=f"bed:{id(st)}:{near}")
                    if v is not None:
                        if st.bed is not None:
                            st.bed.stop()                     # crossfade: the new one fades in as the old fades out
                        st.bed, st.bed_near = v, near
            if st.bed is not None:
                at = st.s.closest(self.lp)
                self.place(st.bed, at, st.s.offset, st.s.sign, self.max_d(st.s))
                st.bed.tag = 1.0 + 0.4 * st.E                  # a wound-up stand is louder for a while
            # the crowd is alive even when nothing's happening
            if self.now > st.next_life and not getattr(self, "_waiting", False):   # #227: nobody cheers while waiting
                inten = self.opt("crowd_intensity", 100) / 100.0
                rate = st.life_rate * self.size_gain(st.s) * (0.35 + 0.65 * inten) * (1.0 if self.green_seen else 0.6) * (1 + st.E)
                st.next_life = self.now + (2.0 + self.rnd.random() * 7.0) / max(0.2, rate)
                if d < 500:
                    self.life(st)

    def life(self, st):
        spot = self.rnd.choice(st.emit)
        sg = self.size_gain(st.s) * st.char
        vuvu = 0.45 if st.s.vibe == "campsite" else 0.22
        r = self.rnd.random()
        o, sd = st.s.offset, st.s.sign
        if r < vuvu:
            self.one("vuvuzela_swell_", 0.45 * sg, spot, o, sd, reserve=2)
        elif r < vuvu + 0.4:
            self.one("whistles_", (0.45 + 0.3 * self.rnd.random()) * sg, spot, o, sd, reserve=2)
        elif r < 0.9:
            self.one("gq_soft_", 0.42 * sg, spot, o, sd, reserve=2)
        else:
            self.one("cheer_A_short_mid", 0.38 * sg, spot, o, sd, reserve=2)

    # ---------- reactions ----------
    def react(self, st, at, kind, from_player=True):
        if st is None:
            return
        if kind != BIG and self.now - st.last_react < (2.5 if kind == NORMAL else 5):
            return
        st.last_react = self.now
        inten = self.opt("crowd_intensity", 100) / 100.0
        e = st.s.closest(at)
        o, sd = st.s.offset, st.s.sign
        d = self.dist(e, o)
        late = min(2.5, d / 343.0)                        # sound takes time to cross a circuit
        ss = getattr(self, "sess_scale", 1.0)
        sg = self.size_gain(st.s) * (0.5 + 0.5 * ss) * (1.0 - 0.25 * getattr(self, "rain_now", 0.0))   # #231 / #232
        fam = f"react:{id(st)}"
        if kind == BIG:                                   # the big moment takes over from a smaller cheer
            for v in list(self.m.voices) + list(self.m._new):
                if v.family == fam:
                    v.stop()
            self._family_cool.pop(fam, None)
            big = self.rnd.choice(["roar_goal", "roar_stadium", "cheer_B"])
            self.one(self.variant(big, d), 1.1 * sg, e, o, sd, late, family=fam)
            self.one(self.variant("cheer_B_peak", d), 0.55 * sg, e, o, sd, late + 1.2, family=fam + ":peak")
            st.E = 1.0
        elif kind == NORMAL:
            fm = self.rnd.choice(["roar_goal_short", "roar_stadium_short", "cheer_B_short", "cheer_A_short", "gq_big_"])
            self.one(fm if fm == "gq_big_" else self.variant(fm, d), 0.95 * sg, e, o, sd, late, family=fam)
            st.E = min(1.0, st.E + 0.6)
        else:
            pfx = "gq_soft_" if self.rnd.random() < 0.5 and self.has("gq_soft_") else self.variant("cheer_A_short", d)
            self.one(pfx, 0.7 * sg, e, o, sd, late, family=fam)
            st.E = min(1.0, st.E + 0.3)
        extras = int(round((4 if kind == BIG else 2 if kind == NORMAL else 1) * (0.3 + 0.7 * inten) * ss))
        for _ in range(extras):
            if self.rnd.random() < 0.8 * getattr(self, "rain_now", 0.0):    # #232: umbrellas up, fewer whistles and horns
                continue
            spot = self.rnd.choice(st.emit)
            dl = late + 0.25 + self.rnd.random() * (3.0 if kind == BIG else 1.6)
            if self.rnd.random() < 0.65:
                self.one("whistles_", (0.75 + 0.3 * self.rnd.random()) * sg, spot, o, sd, dl, reserve=1)
            else:
                self.one("vuvuzela_swell_", 0.6 * sg, spot, o, sd, dl, reserve=1)

    def mood(self, st, at, prefix, level, delay):
        if st is None:
            return
        e = st.s.closest(at); d = self.dist(e, st.s.offset)
        self.one(prefix, level * self.size_gain(st.s) * st.char, e, st.s.offset, st.s.sign, delay + min(2.5, d / 343.0))
        st.last_react = self.now

    def news_ahead(self, at):
        n = int(self.opt("crowd_stands_ahead", 2))
        ahead = sorted((st for st in self.stands if wrap(st.s.frm - at) * self.L > 250), key=lambda st: wrap(st.s.frm - at))[:n]
        for st in ahead:
            st.pending_until = self.now + 400

    # ---------- overtakes ----------
    def passes(self, f):
        cars = [c for c in f.cars if not c.in_pits and c.progress > 0]
        prev = self._prev_prog
        near = max(0.002, 70.0 / self.L)
        known = [c for c in cars if c.id in prev]
        if len(known) >= 2:
            p0 = np.array([prev[c.id] for c in known]); p1 = np.array([c.progress for c in known])
            ok = ~((p1 - p0 > 0.05) | (p1 < p0 - 0.02))           # tow / reset / teleport
            hit = (p0[:, None] < p0[None, :]) & (p1[:, None] > p1[None, :]) & ((p1[:, None] - p1[None, :]) < near)
            hit &= ok[:, None] & ok[None, :]
            for ia, ib in zip(*np.nonzero(hit)):
                a, b = known[ia], known[ib]
                k = f"{a.id}>{b.id}"
                if self.now < self._pair_cool.get(k, -1):
                    continue
                self._pair_cool[k] = self._pair_cool[f"{b.id}>{a.id}"] = self.now + 8
                lapping = math.floor(a.progress) != math.floor(b.progress) or (a.pos or 0) > (b.pos or 0) + 3
                self.on_pass(f, a, b, wrap(a.progress), lapping)
        self._prev_prog = {c.id: c.progress for c in cars}

    def on_pass(self, f, att, dfd, at, lapping):
        self.passes_seen += 1
        hero = getattr(f, "hero", None)                         # C1 (#283): the home hero is cheered like you are
        if hero is not None and not att.is_player and att.id == hero and not lapping:
            k = BIG if (att.cpos == 1 or att.pos == 1 or (self.white_seen and not self.chequer_seen)) else NORMAL
            for st in (self.stands_near(at, 420) or [self.nearest_stand(at, 900)]):
                if st:
                    self.react(st, at, k, False)
            return
        for_lead = att.cpos == 1 or att.pos == 1
        last_lap = self.white_seen and not self.chequer_seen
        if att.is_player:
            k = SMALL if lapping else BIG if (for_lead or last_lap) else NORMAL
            hit = self.stands_near(at, 420)
            if not hit:
                n = self.nearest_stand(at, 900)
                hit = [n] if n else []
            for st in hit:
                self.react(st, at, k)
            if not lapping:
                self.news_ahead(at)
        elif dfd.is_player:
            st = self.nearest_stand(at, 320)
            if st and self.has("grumble_") and self.rnd.random() < 0.5:
                self.mood(st, at, "grumble_", 0.8, 0.2)
            else:
                self.react(st, at, SMALL)
        elif self.opt("crowd_others", True) and not lapping:
            st = self.nearest_stand(at, 320)
            if st and self.dist(st.s.closest(at), st.s.offset) < 1100:
                self.react(st, at, NORMAL if for_lead else SMALL, False)

    # ---------- crashes ----------
    def crashes(self, f):
        if f.spin:
            self.on_crash(True, self.lp)
        for c in f.cars:
            if c.is_player:
                continue                                  # our own spins come from the brain
            m = self._motion.get(c.id)
            if m is None:
                self._motion[c.id] = {"t": self.now, "p": c.progress, "v": 0.0, "hist": deque(), "cool": 0.0}
                continue
            if self.now - m["t"] < 0.25:
                continue
            v = (c.progress - m["p"]) * self.L / (self.now - m["t"])
            if v < -5 or v > 140:
                v = m["v"]
            m["t"], m["p"], m["v"] = self.now, c.progress, v
            m["hist"].append((self.now, v))
            while m["hist"] and self.now - m["hist"][0][0] > 2.5:
                m["hist"].popleft()
            peak = max(x[1] for x in m["hist"])
            if not c.in_pits and peak > 25 and v < 8 and self.now > m["cool"]:
                m["cool"] = self.now + 25
                self.on_crash(False, wrap(c.progress))

    def on_crash(self, player, at):
        self.crashes_seen += 1
        st = self.nearest_stand(at, 450)
        if st is None or self.now - st.last_groan < 6:      # one groan per stand for a pile-up
            return
        e = st.s.closest(at); d = self.dist(e, st.s.offset)
        if not player and d > 1100:
            return
        st.last_groan = self.now
        sg = self.size_gain(st.s) * st.char
        late = min(2.5, d / 343.0)
        self.one("groan_", 0.9 * sg, e, st.s.offset, st.s.sign, late + 0.15)
        if self.has("grumble_") and self.rnd.random() < 0.6:
            self.mood(st, e, "grumble_", 0.65, 1.9)
        st.E = min(1.0, st.E + 0.4)
        st.last_react = self.now

    def approaches(self, f):
        # 2026-10-25 (request: "if we made an overtake the places with crowds would cheer loudly as we pass them, in
        # correlation to how many places we gained on the previous lap"): at each lap line, the class places we gained
        # on the lap just finished set how hard every grandstand cheers as we come past on the next lap -
        # 1 place a cheer, 2 a roar, 3 or more the roar plus a second wave.
        me = next((c for c in f.cars if c.is_player), None)
        if me is not None and me.cpos:
            lapno = int(math.floor(me.progress))
            if self._gain_lap is None or lapno < self._gain_lap:
                self._gain_lap, self._gain_pos, self.lap_gain = lapno, me.cpos, 0
            elif lapno > self._gain_lap:
                self.lap_gain = max(0, (self._gain_pos or me.cpos) - me.cpos) if f.is_race and self.green_seen else 0
                self._gain_lap, self._gain_pos = lapno, me.cpos
                if self.lap_gain > 0:
                    self.log(f"[crowd] gained {self.lap_gain} place(s) last lap - the grandstands cheer us round this lap")
        on_me = me is not None and abs(((wrap(me.progress) - self.lp + 0.5) % 1.0) - 0.5) * self.L < 250
        for st in self.stands:
            ahead = self.along(st.s.frm)
            if ahead < 0 and self.along(st.s.to) < 0:
                continue
            if st.approach_lap == f.lap:
                continue
            if 0 < ahead < 180:
                st.approach_lap = f.lap
                if st.pending_until > self.now:
                    st.pending_until = -1
                    self.react(st, st.s.frm, NORMAL)
                    continue
                if self.lap_gain > 0 and on_me and f.is_race and self.green_seen:
                    self.react(st, wrap(st.s.frm + 0.002), BIG if self.lap_gain >= 2 else NORMAL)
                    if self.lap_gain >= 3:                      # a second wave rolls along the stand
                        e = st.s.closest(wrap(st.s.frm + 0.004)); d = self.dist(e, st.s.offset)
                        self.one(self.variant("roar_stadium", d), 1.0 * self.size_gain(st.s), e, st.s.offset, st.s.sign,
                                 min(2.5, d / 343.0) + 1.6, family=f"wave:{id(st)}")
                    continue
                battle = any(not c.is_player and abs(wrap(c.progress) - self.lp) * self.L < 45 for c in f.cars)
                p = (0.7 if battle else 0.22) * (0.3 + 0.7 * self.opt("crowd_intensity", 100) / 100.0)
                if f.is_race and self.green_seen and self.rnd.random() < p:
                    self.react(st, wrap(st.s.frm + 0.002), NORMAL if battle else SMALL)

    # ---------- race moments ----------
    def race_events(self, f):
        pa = self.map.pa_at
        if not self.green_seen and not self.build_started and f.speed_kmh > 25 and f.before_green:
            to_line = wrap(pa - self.lp) * self.L
            if 50 < to_line < 800:
                self.build_started = True
                c = self.get("pregreen_buildup_near") or self.get("pregreen_buildup_mid")
                self.place(self.m.play(c, 1.2, family="pregreen"), pa, 50, -1, 950)
                for st in self.stands:
                    st.E = max(st.E, 0.5)
        if f.green and not self.green_seen:
            self.green_seen = True
            if f.before_green:
                self.green()
        if f.white and not self.white_seen and self.green_seen:
            self.white_seen = True
            for st in self.stands:
                st.E = max(st.E, 0.8)
            self.next_pa = min(self.next_pa, self.now + 2)
        if f.chequered and not self.chequer_seen and self.green_seen:
            self.chequer_seen = True
            self.cool_until = self.now + 150                     # #233: the cooldown lap
            self.chequer_t = self.now                            # C7 (#286): the podium two minutes later
            self.react(self.nearest_stand(pa), self.lp, BIG)
            self.place(self.m.play(self.get("green_flag_roar_near"), 1.1, delay=0.3, family="finish_roar"), pa, 50, -1, 950)
            if self.opt("crowd_heli", True):
                self.m.play(self.get("helicopter_low_hover"), 0.55, delay=2.5, family="heli", pan=0.0)
            for st in self.stands:
                st.E = 1.0

    def green(self):
        """2026-10-26 (#224, request: "green flag should make people go crazy at the start"): the whole circuit erupts -
        the start-line roar, every grandstand roaring (each heard as late as sound takes to cross the circuit), a second
        wave two seconds later, whistles and horns everywhere, and the stands stay wound up for a while."""
        if self.opt("crowd_heli", True):
            # #223 (request: "the flyover at the start of the race - make it sound cooler or amplify it without changing it
            # too much"): the same helicopter, louder, with more rotor thump and wider, sweeping across overhead
            self.m.play(self.heli_big(), 0.8, delay=1.0, family="heli")
        pa = self.map.pa_at
        self.place(self.m.play(self.get("green_flag_roar_near"), 1.35, family="green_roar"), pa, 50, -1, 950)
        ranked = sorted(self.stands, key=lambda st: self.dist(st.s.closest(self.lp), st.s.offset))
        for i, st in enumerate(ranked):
            st.last_react = -99
            self.react(st, st.s.closest(self.lp), BIG)
            st.E = 1.0
            if i < 3:                                         # the nearest stands: a second wave as the field gets away
                e = st.s.closest(self.lp); d = self.dist(e, st.s.offset)
                self.one(self.variant("roar_stadium", d), 0.9 * self.size_gain(st.s), e, st.s.offset, st.s.sign,
                         2.0 + min(2.5, d / 343.0) + self.rnd.random() * 0.4, family=f"green2:{id(st)}", reserve=1)

    def pre_race(self, f, waiting, formation):
        """2026-10-26 (#227, request: "what about when the cars are on the formation lap or before it - we need crowd
        ambience when no cars are on track"):
          waiting    nobody out yet, or the cars sitting on the grid before the race: the crowd chatting and milling
                     about in the stands, the circuit PA a bit more often - no cheers, nobody to cheer for
          formation  the formation lap: the stands buzzing with excitement, whistles and horns here and there,
                     building into the start (the start-line build-up and the green-flag eruption take over from it)"""
        hold = self._hold
        # before the start the stands are calmer (half as loud), so the green flag has somewhere to explode to
        self.pre_scale = 0.3 if waiting else 0.55 if formation else 1.0
        self._waiting = waiting
        hold("_wait_bed", waiting, ("bed_crowd_buzz_mid", "bed_stadium_crowd_far"), 0.5)
        hold("_form_bed", formation, ("bed_crowd_excited_mid", "bed_crowd_roar_mid", "bed_stadium_crowd_mid"), 0.4)
        if waiting and self.opt("crowd_pa", True) and self.now > self.next_pa:
            self.next_pa = self.now + 35 + self.rnd.random() * 35
            c = self.pick("pa_far_")
            if c is not None:
                self.m.play(c, 0.55, family="pa", pan=self.rnd.random() * 0.8 - 0.4, reserve=1)
        if formation and self.stands and self.now > getattr(self, "_form_next", 0.0):
            self._form_next = self.now + 4 + self.rnd.random() * 6
            st = self.rnd.choice(self.stands)
            spot = self.rnd.choice(st.emit)
            pfx = "whistles_" if self.rnd.random() < 0.7 else "vuvuzela_swell_"
            self.one(pfx, 0.6 * self.size_gain(st.s), spot, st.s.offset, st.s.sign, 0.0, reserve=2)

    def _hold(self, attr, on, names, level):
        """Keep one looping, unplaced bed playing while `on` (fades in / out)."""
        v = getattr(self, attr, None)
        if on and (v is None or v.done):
            c = next((self.get(n) for n in names if self.get(n) is not None), None)
            setattr(self, attr, self.m.play(c, level, loop=True, family=attr) if c is not None else None)
        elif not on and v is not None:
            v.stop(); setattr(self, attr, None)

    def cooldown(self, f):
        """2026-10-26 (#233): after the chequered flag the crowd stays on its feet for the cooldown lap - applause
        under everything, and a cheer from a grandstand every few seconds as the cars come round."""
        on = self.now < getattr(self, "cool_until", 0.0)
        self._hold("_cool_bed", on, ("bed_crowd_excited_mid", "bed_crowd_roar_mid", "bed_stadium_crowd_mid"), 0.45)
        if on and self.stands and self.now > getattr(self, "_cool_next", 0.0):
            self._cool_next = self.now + 5 + self.rnd.random() * 6
            st = self.rnd.choice(self.stands)
            st.last_react = -99
            self.react(st, st.s.closest(self.lp), NORMAL if self.rnd.random() < 0.6 else SMALL)

    def heli_big(self):
        """helicopter_low_hover made bigger once and kept: +6 dB of rotor thump below 140 Hz, a little warmth, a wide
        left-to-right sweep over its length (the same recording - nothing new added)."""
        if getattr(self, "_heli_big", None) is not None:
            return self._heli_big
        c = self.get("helicopter_low_hover")
        if c is None:
            return None
        # 2026-10-29 (efficiency): made ahead in a background thread when the track loads (heli_prepare) - it used to be
        # made at the green flag itself, an FFT of the whole recording on the engine's thread just as the start plays.
        # Same clip, same result; if it isn't ready yet it's made here as before.
        pre = getattr(self, "_heli_pre", None)
        if pre is not None and pre[0] is c:
            self._heli_big = pre[1]
        else:
            self._heli_big = self._make_heli_big(c)
        return self._heli_big

    def heli_prepare(self):
        """Background: make the bigger helicopter for the clip the green flag would use now (track packs included)."""
        if getattr(self, "_heli_big", None) is not None:
            return
        c = self.get("helicopter_low_hover")
        if c is None or (getattr(self, "_heli_pre", None) or (None,))[0] is c:
            return
        def run():
            out = self._make_heli_big(c)
            self._heli_pre = (c, out)
        threading.Thread(target=run, daemon=True, name="crowd-heli").start()

    def _make_heli_big(self, c):
        try:
            raw = np.asarray(c.data)
            x = raw.astype(np.float32) / (32768.0 if raw.dtype == np.int16 else 1.0)    # clips are kept as 16-bit
            if x.ndim == 1:
                x = np.stack([x, x], 1)
            n = len(x)
            spec = np.fft.rfft(x, axis=0)
            f = np.fft.rfftfreq(n, 1 / RATE)
            shelf = 1 + (10 ** (6 / 20) - 1) / (1 + (f / 140.0) ** 4)          # +6 dB low shelf at 140 Hz
            y = np.fft.irfft(spec * shelf[:, None], n, axis=0)
            y = np.tanh(y * 1.6) / 1.6                                           # warmth, no harsh peaks
            t = np.linspace(-0.85, 0.85, n)                                      # the sweep, left to right
            a = (t + 1) * np.pi / 4
            mono = y.mean(1)
            side = (y[:, 0] - y[:, 1]) * 0.5
            out = np.stack([mono * np.cos(a) * 1.41 + side, mono * np.sin(a) * 1.41 - side], 1)
            out *= (np.abs(x).max() + 1e-9) / (np.abs(out).max() + 1e-9) * 1.4   # +3 dB louder than the original peak
            out = np.clip(out, -0.98, 0.98)
            out = (out * 32767).astype(np.int16) if raw.dtype == np.int16 else out.astype(raw.dtype)
            return Clip("helicopter_green_flyover", out, c.gain)
        except Exception as e:
            self.log(f"[crowd] heli_big: {e!r}")
            return c

    # ---------- ambience ----------
    def ambient(self, f):
        if self.opt("crowd_heli", True) and self.now > self.next_heli:
            self.next_heli = self.now + 90 + self.rnd.random() * 90
            r = self.rnd.random()
            c = self.pick("helicopter_flyover_") if r < 0.6 else self.get("helicopter_approach") if r < 0.8 else self.get("helicopter_pass_close")
            self.m.play(c, 0.8, family="heli", pan=self.rnd.random() * 1.2 - 0.6, reserve=1)
        if self.opt("crowd_pa", True) and self.now > self.next_pa:
            self.next_pa = self.now + 55 + self.rnd.random() * 65
            c = self.pick("pa_far_")
            self.place(self.m.play(c, 0.9, family="pa", reserve=1), self.map.pa_at, 80, -1, 950)

    # ---------- test buttons ----------
    def test_cheer(self):
        """One quiet cheer, centred, whatever the session state."""
        c = None
        for p in ("cheer_A_short_mid", "cheer_A_short_near", "gq_soft_", "cheer_A_short", "cheer_", "gq_", "roar_"):
            c = self.pick(p)
            if c is not None:
                break
        if c is None:
            return False
        self.m.test_until = self.m.clock() + c.frames / self.m.rate + 1.0
        return self.m.play(c, 0.5, family="test") is not None


# =================================================================== the app's handle
class Crowd:
    """Owned by the app. tick(brain) from the engine's loop; everything else from the settings page."""

    def __init__(self, settings, log=print, device=None, root=TS_DIR):
        self.s, self.log = settings, log
        self.root = root
        self.sounds_dir = os.path.join(root, "sounds")
        self.tracks_dir = os.path.join(root, "tracks")
        self.mixer = Mixer(max_voices=max(12, int(getattr(settings, "crowd_max_voices", 12) or 12)), log=log)   # 2026-10-26: room for the ambience
        try:
            from .voice import RADIO
            self.mixer.duck_fn = lambda: RADIO.owner is not None
        except Exception:
            pass
        self.director = None
        self.device = device
        self.state = "loading"
        self.copy_msg = ""
        self._last_t = None
        self._b_prev = {}
        self._drivers, self._drivers_t = {}, -99
        self.apply()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            os.makedirs(self.sounds_dir, exist_ok=True); os.makedirs(self.tracks_dir, exist_ok=True)
        except OSError:
            pass
        clips = load_sounds(self.sounds_dir, os.path.join(self.root, "levels.json"), log=self.log)
        self.director = Director(self.mixer, clips, [BUNDLED_TRACKS, self.tracks_dir], self.s, log=self.log)
        self.director.pack_root = os.path.join(self.root, "track_sounds")          # C5 (#284)
        os.makedirs(self.director.pack_root, exist_ok=True)
        self.state = "ready" if clips else "no_sounds"
        if clips:
            self.log(f"[crowd] {len(clips)} crowd sounds ready")
            if getattr(self.s, "crowd_on", True):
                self.mixer.start(self.device)

    def reload(self):
        self.mixer.stop_all()
        self.state = "loading"
        threading.Thread(target=self._load, daemon=True).start()

    def apply(self):
        s = self.s
        self.mixer.set_volume(getattr(s, "crowd_volume", 0.3))
        self.mixer.set_ceiling_db(getattr(s, "crowd_max_db", -18.0))
        self.mixer.duck_on = bool(getattr(s, "crowd_duck", True))
        if self.director:
            self.director.s = s
            if not getattr(s, "crowd_on", True) or getattr(s, "crowd_mute", False):
                self.mixer.muted = True
        on = getattr(s, "crowd_on", True)
        if not on and self.mixer.stream is not None:
            self.mixer.stop_all(); self.mixer.close()
        elif on and self.mixer.stream is None and self.state == "ready":
            self.mixer.start(self.device)

    def set_device(self, dev):
        self.device = dev or None
        if self.mixer.stream is not None:
            self.mixer.start(self.device)

    def tick(self, brain):
        """Every engine tick: a small Frame from the brain. brain None = iRacing not running."""
        d = self.director
        if d is None:
            return
        now = time.monotonic()
        dt = 0.0 if self._last_t is None else min(0.25, now - self._last_t)
        self._last_t = now
        try:
            f = self._frame(brain) if brain is not None else Frame(running=False)
        except Exception as e:
            f = Frame(running=False)
            if not getattr(self, "_ferr", False):
                self._ferr = True; self.log(f"[crowd] {e!r}")
        try:
            d.update(f, dt)
        except Exception as e:
            self.mixer.stop_all()
            if not getattr(self, "_uerr", False):
                self._uerr = True; self.log(f"[crowd] director problem, crowd silent: {e!r}")

    ONBOARD = ("cockpit", "roll bar", "rollbar", "gyro", "chase", "nose", "gearbox", "susp", "wing", "in car", "incar", "onboard", "driver", "mirror")
    _cam_prev = None
    _cam_live = None
    _cam_pending = None
    _cam_groups = None

    _cam_names = None

    def _cam_name(self, b, grp, num):
        """Name of the live camera inside a group (2026-10-25: TV groups cut between trackside and in-car
        cameras - "CamGyro", "CamRoll Bar" - and a "CamChopper"), '' if unknown."""
        if self._cam_names is None or (grp, num) not in self._cam_names:
            try:
                self._cam_names = {(int(g.get("GroupNum", 0)), int(c.get("CameraNum", 0))): str(c.get("CameraName", "")).lower()
                                   for g in ((b.info("CameraInfo", {}) or {}).get("Groups") or [])
                                   for c in (g.get("Cameras") or [])}
            except Exception:
                self._cam_names = {}
        return self._cam_names.get((grp, num), "")

    def _cam_group(self, b, num):
        """Camera group name for a group number, from the session's CameraInfo (cached; '' if unknown)."""
        if self._cam_groups is None or (num and num not in self._cam_groups):
            try:
                self._cam_groups = {int(g.get("GroupNum", 0)): str(g.get("GroupName", "")).lower()
                                    for g in ((b.info("CameraInfo", {}) or {}).get("Groups") or [])}
            except Exception:
                self._cam_groups = {}
        return self._cam_groups.get(num, "")

    def _class_of(self, idx):
        """GTP / LMP2 / GT3 ... for a car (iRacing's class name / number - classes.py)."""
        try:
            from . import classes
            return classes.label(self._drivers.get(idx, {})) or ""
        except Exception:
            return ""

    def _frame(self, b):
        """Reuse what the brain already detects: green flag, white flag, the finish, our spins."""
        p = self._b_prev
        n = b.g("SessionNum", 0)
        if p.get("sess") != n:
            p.clear(); p["sess"] = n
            p["before_green"] = (b.g("SessionState", 0) or 0) < 4
            self._drivers_t = -99
        green = bool(getattr(b, "green_seen", False)); white = bool(b.prev.get("last_lap_said")); fin = bool(getattr(b, "finished", False))
        ev = getattr(b, "crowd_ev", None)
        spin = bool(ev)
        if ev:
            del ev[:]
        wk = b.info("WeekendInfo", {}) or {}
        now = time.monotonic()
        if now - self._drivers_t > 5:
            self._drivers, self._drivers_t = b.drivers(), now
        me = b.me()
        pct = b.g("CarIdxLapDistPct") or []
        lc = b.g("CarIdxLapCompleted") or []
        pos = b.g("CarIdxPosition") or []
        cpos = b.g("CarIdxClassPosition") or []
        onp = b.g("CarIdxOnPitRoad") or []
        cars = []
        for i in self._drivers:
            if i >= len(pct) or pct[i] is None or pct[i] < 0:
                continue
            lap = lc[i] if i < len(lc) and lc[i] is not None and lc[i] >= 0 else 0
            cars.append(CarState(i, i == me, pos[i] if i < len(pos) else 0, cpos[i] if i < len(cpos) else 0,
                                 lap + pct[i], bool(onp[i]) if i < len(onp) else False))
        # camera (2026-10-25): which car is on screen and whether the camera is onboard or TV-style
        replay = bool(b.g("IsReplayPlaying", False))
        cam = b.g("CamCarIdx")
        follow = cam if isinstance(cam, int) and 0 <= cam < len(pct) and pct[cam] is not None and pct[cam] >= 0 else me
        here = pct[follow] if isinstance(follow, int) and 0 <= follow < len(pct) and pct[follow] is not None and pct[follow] >= 0 \
            else (b.g("LapDistPct", 0) or 0)
        grp = b.g("CamGroupNumber", 0) or 0
        gname = self._cam_name(b, grp, b.g("CamCameraNumber", 0) or 0) or self._cam_group(b, grp)
        aerial = "blimp" if "blimp" in gname else "chopper" if "chopper" in gname else ""   # aerial shot: no crowd up there
        onboard = (any(k in gname for k in self.ONBOARD) if gname else (follow == me and not replay)) and not aerial
        tv = not onboard
        # 2026-10-25: in replays the camera data changes before the picture cuts (about 2 s early on the developer's
        # rig), so the new camera is only followed after crowd_cam_delay; until then the old car stays on air
        camkey = (grp, follow, tv, aerial)
        now = time.monotonic()
        delay = float(getattr(self.s, "crowd_cam_delay", 1.8) or 0) if replay else 0.0
        if self._cam_live is None:
            self._cam_live = camkey
        if camkey != self._cam_live:
            if self._cam_pending is None or self._cam_pending[0] != camkey:
                self._cam_pending = (camkey, now)
            if now - self._cam_pending[1] >= delay:
                self._cam_live, self._cam_pending = camkey, None
        else:
            self._cam_pending = None
        grp, follow, tv, aerial = self._cam_live
        if isinstance(follow, int) and 0 <= follow < len(pct) and pct[follow] is not None and pct[follow] >= 0:
            here = pct[follow]
        surf = b.g("CarIdxTrackSurface")                       # -1 not in the world, 0 off track, 1 in the pit stall, 2 pit lane / approaching, 3 on track
        running = None if not surf else sum(1 for v in surf if v in (0, 2, 3))
        cut = self._cam_prev is not None and self._cam_live != self._cam_prev
        self._cam_prev = self._cam_live
        return Frame(running=True, on_track=bool(b.g("IsOnTrack", False)) or replay, in_pits=bool(b.g("OnPitRoad", False)) and not tv,
                     tv=tv, cut=cut, aerial=aerial, follow=follow, follow_class=self._class_of(follow),
                     rain=_f(b.g("Precipitation", 0.0)), wet=max(0.0, (_f(b.g("TrackWetness", 1)) - 1) / 6.0),
                     wind_ms=_f(b.g("WindVel", 0.0)), night=_f(b.g("SolarAltitude", 1.0)) < -0.03,
                     track_id=str(wk.get("TrackName", "")), track_name=f"{wk.get('TrackDisplayName', '')} {wk.get('TrackConfigName', '')}",
                     session=b.sess_type, track_len=b.track_len_m(), pct=here,
                     speed_kmh=(b.g("Speed", 0) or 0) * 3.6, lap=b.g("Lap", 0) or 0,
                     green=green, white=white, chequered=fin, before_green=p["before_green"], spin=spin, cars=cars,
                     cars_running=running, sstate=int(b.g("SessionState", 0) or 0),
                     driving=(not replay) and (not tv) and follow == me, hero=self._hero_idx(b),
                     cam=gname or "", caution=bool((b.g("SessionFlags", 0) or 0) & 0xC000))

    def _hero_idx(self, b):
        """C1 (#283): the car number set as the home hero (Settings > Crowd) -> its CarIdx this session."""
        num = str(getattr(self.s, "crowd_hero", "") or "").strip().lstrip("#")
        if not num:
            return None
        if getattr(self, "_hero_key", None) != num or time.monotonic() - getattr(self, "_hero_t", 0) > 30:
            self._hero_key, self._hero_t, self._hero_i = num, time.monotonic(), None
            try:
                for d in (b.info("DriverInfo", {}) or {}).get("Drivers", []) or []:
                    if str(d.get("CarNumber", "")).strip() == num:
                        self._hero_i = d.get("CarIdx"); break
            except Exception:
                pass
        return self._hero_i

    def test(self):
        if self.director is None or self.state != "ready":
            return {"ok": False, "msg": "No crowd sounds yet - copy them from SimHub first"}
        if self.mixer.stream is None and not self.mixer.start(self.device):
            return {"ok": False, "msg": "Sound device problem: " + self.mixer.device_error}
        ok = self.director.test_cheer()
        return {"ok": ok, "msg": "Playing a quiet cheer" if ok else "No cheer sound found"}

    def info(self):
        d = self.director
        n_tracks = 0
        try:
            n_tracks = sum(1 for f in os.listdir(self.tracks_dir) if f.lower().endswith(".json"))
        except OSError:
            pass
        return {"state": self.state, "sounds": len(d.clips) if d else 0, "tracks": n_tracks,
                "status": d.status if d else "", "playing": self.mixer.count(),
                "peak_db": round(lin2db(self.mixer.peak_out), 1) if self.mixer.peak_out > 0 else None,
                "device_error": self.mixer.device_error, "simhub": bool(find_simhub()), "copy": self.copy_msg,
                "folder": self.root}

    def copy_from_simhub(self):
        r = copy_from_simhub(self.root, log=self.log)
        self.copy_msg = r["msg"]
        if r["copied"]:
            self.reload()
        return r

    def close(self):
        self.mixer.stop_all()
        self.mixer.close()


# =================================================================== copy from SimHub
def find_simhub(roots=None):
    for r in roots or SIMHUB_ROOTS:
        if os.path.isdir(os.path.join(r, "TracksideCrowd", "sounds")):
            return r
    return None


def copy_from_simhub(dest=TS_DIR, roots=None, log=print):
    """Copy the SimHub add-on's sounds and track files into Trackside\\. Copies only - never moves or
    deletes anything, on either side. The user's own marked tracks (PluginsData) are copied too."""
    root = find_simhub(roots)
    if not root:
        return {"ok": False, "copied": 0, "skipped": 0, "msg": "SimHub Trackside Crowd not found on this PC"}
    pairs = [(os.path.join(root, "TracksideCrowd", "sounds"), os.path.join(dest, "sounds"), (".wav", ".mp3", ".flac", ".ogg")),
             (os.path.join(root, "TracksideCrowd", "tracks"), os.path.join(dest, "tracks"), (".json",)),
             (os.path.join(root, "PluginsData", "TracksideCrowd", "tracks"), os.path.join(dest, "tracks"), (".json",))]
    copied = skipped = failed = 0
    for src, dst, exts in pairs:
        try:
            names = sorted(os.listdir(src))
        except OSError:
            continue
        os.makedirs(dst, exist_ok=True)
        for n in names:
            s = os.path.join(src, n)
            if not os.path.isfile(s) or not n.lower().endswith(exts):
                continue
            d = os.path.join(dst, n)
            try:
                if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s) and os.path.getmtime(d) >= os.path.getmtime(s) - 2:
                    skipped += 1
                    continue
                shutil.copy2(s, d)
                copied += 1
            except OSError as e:
                failed += 1
                log(f"[crowd] couldn't copy {n}: {e}")
    cr = os.path.join(root, "TracksideCrowd", "credits.txt")
    if os.path.isfile(cr):
        try:
            shutil.copy2(cr, os.path.join(dest, "credits.txt"))
        except OSError:
            pass
    msg = f"Copied {copied} files" + (f", {skipped} already there" if skipped else "") + (f", {failed} failed" if failed else "")
    log(f"[crowd] {msg} from {root}")
    return {"ok": failed == 0, "copied": copied, "skipped": skipped, "failed": failed, "msg": msg}
