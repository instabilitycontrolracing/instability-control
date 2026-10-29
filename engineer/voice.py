"""Engineer voice: builds a spoken line from rendered clips + fill-ins, adds the radio sound, plays it.

A line in the manifest is a list of parts: {"clip": ...} pieces and {"fill": "P"} slots.
Fill values are turned into building-block clips by fills.py.
"""
import json, os, random, re, threading, time, queue, heapq, itertools
import numpy as np

try:
    from . import simload            # #454 loading screens: the radio waits
except ImportError:
    import simload
import soundfile as sf

from . import fills as F
from . import lines_new

# Parts we never say: iRacing has no driver-controlled hybrid deploy (driver request, 2026-10-22).
SKIP_PART = re.compile(r"(?i)deploy|battery|recharge|mode overtake|mode defend|overtake not available|engine braking")

PRIO_SPOTTER, PRIO_URGENT, PRIO_RACE, PRIO_INFO, PRIO_CHAT = 0, 1, 2, 3, 4

# The one clean "Car." take (checked by speech recognition 2026-10-24); used for every line that opens with "Car".
CAR_CLIP = "lines/car_inc/v1_1.wav"



def _loud(x, vol):
    """2026-10-26 (request: "all the radio voices at least 30 percent louder", then "another 30 percent"): volume can go
    above 100 %. The old version scaled the whole clip back down when its loudest peak passed full scale, so on clips
    already near full scale a higher volume did nothing. Now a smooth peak limiter only turns down the few loud peaks
    (about 5 ms around each), so the voice really gets louder and still never clips or crackles."""
    y = np.asarray(x, dtype=np.float32) * float(vol)
    if not y.size:
        return y
    ceil = 0.97
    a = np.abs(y) if y.ndim == 1 else np.abs(y).max(axis=1)
    if float(a.max()) <= ceil:
        return y
    try:
        from scipy.ndimage import minimum_filter1d, uniform_filter1d
        g = np.minimum(1.0, ceil / np.maximum(a, 1e-9)).astype(np.float32)
        w = 241                                              # ~5 ms at 48 kHz: centred min, then average -> never above need
        g = uniform_filter1d(minimum_filter1d(g, size=w, mode="nearest"), size=w, mode="nearest")
        y = y * (g if y.ndim == 1 else g[:, None])
        pk = float(np.abs(y).max())
        return y * (ceil / pk) if pk > ceil else y           # safety net for rounding
    except Exception:                                        # no scipy: soft saturation keeps it loud without clipping
        return (ceil * np.tanh(y / ceil)).astype(np.float32)

def _pit_echo(a, sr):
    """2026-10-26: race control heard in the pit lane - the PA bouncing off the garages and the pit wall (the same early
    reflections the old pit-road space used). Only race control; the team radio is always dry, in the ear."""
    a = np.asarray(a, dtype=np.float32)
    taps = [(0.009, 0.32), (0.014, 0.24), (0.022, 0.20), (0.031, 0.15), (0.044, 0.10), (0.070, 0.06), (0.105, 0.035)]
    n = len(a) + int(0.12 * sr)
    y = np.zeros(n, np.float32); y[:len(a)] += a
    for t, g in taps:
        k = int(t * sr); y[k:k + len(a)] += a * g
    pk = float(np.abs(y).max()) or 1.0
    return y * (min(1.0, float(np.abs(a).max()) / pk))


class RadioFX:
    """Headset-over-radio sound. strength 0 = clean, 1 = the default preset (radio test 2), 2 = TV team radio."""
    CLEAN = dict(hp=60, ls_f=300, ls_g=0, pk_f=2200, pk_g=0, pk_q=0.9, lp=11500, c_th=-10, c_r=1.5,
                 c_a=5, c_rel=120, drive=0, gain=0, hiss=-90)
    STRONG = dict(hp=320, ls_f=300, ls_g=-3, pk_f=1800, pk_g=5, pk_q=0.8, lp=3500, c_th=-25, c_r=6,
                  c_a=2, c_rel=80, drive=10, gain=-4, hiss=-50)

    def __init__(self, preset_path, sr, strength=1.0):
        self.sr = sr
        self.board = None
        self.mid = dict(self.CLEAN)
        try:
            P = json.load(open(preset_path, encoding="utf-8"))
            for st in P["chain"]:
                f = st["fx"]
                if f == "HighpassFilter": self.mid["hp"] = st["cutoff_hz"]
                elif f == "LowpassFilter": self.mid["lp"] = st["cutoff_hz"]
                elif f == "LowShelfFilter": self.mid.update(ls_f=st["cutoff_hz"], ls_g=st["gain_db"])
                elif f == "PeakFilter": self.mid.update(pk_f=st["cutoff_hz"], pk_g=st["gain_db"], pk_q=st.get("q", 0.7))
                elif f == "Compressor": self.mid.update(c_th=st["threshold_db"], c_r=st["ratio"], c_a=st["attack_ms"], c_rel=st["release_ms"])
                elif f == "Distortion": self.mid["drive"] = st["drive_db"]
                elif f == "Gain": self.mid["gain"] = st["gain_db"]
            self.mid["hiss"] = P.get("hiss", {}).get("level_db", -90)
        except Exception as e:
            print("[voice] radio preset not found, using defaults:", e)
            self.mid = dict(self.CLEAN)
        self.set_strength(strength)

    def set_strength(self, s):
        s = max(0.0, min(2.0, float(s)))
        self.strength = s
        lo, hi, t = (self.CLEAN, self.mid, s) if s <= 1 else (self.mid, self.STRONG, s - 1)
        k = {n: lo[n] + (hi[n] - lo[n]) * t for n in lo}
        try:
            from pedalboard import (Pedalboard, HighpassFilter, LowpassFilter, PeakFilter, LowShelfFilter,
                                    Compressor, Distortion, Gain, Limiter)
            if s < 0.02:
                self.board = Pedalboard([Limiter(-1)])
                self.hiss = None
            else:
                self.board = Pedalboard([
                    HighpassFilter(k["hp"]), LowShelfFilter(k["ls_f"], k["ls_g"]),
                    PeakFilter(k["pk_f"], k["pk_g"], k["pk_q"]), LowpassFilter(k["lp"]),
                    Compressor(k["c_th"], k["c_r"], k["c_a"], k["c_rel"]), Distortion(k["drive"]),
                    Gain(k["gain"]), Limiter(-1)])
                self.hiss = k["hiss"]
                self._hp = Pedalboard([HighpassFilter(1500), LowpassFilter(6000)])
        except Exception as e:  # no pedalboard: play clean
            print("[voice] radio effect off:", e)
            self.board = None

    # 2026-10-26 (#210, team radio realism): the conditions the radio is working in, set by the app each tick.
    # rain 0..1 = more static; far 0..1 = how far round the lap from the pit wall (short dips and crackle). Subtle.
    COND = {"rain": 0.0, "far": 0.0, "on": True}

    _PW = None                      # the pit-wall recording (#244 D6), loaded once

    def _pitwall(self, n):
        """2026-10-26 (#244, D6): the pit wall behind the engineer when he keys up - generators, people, other teams'
        radios far away. Only from the developer's own recordings (Trackside\\sounds\\amb_pitwall_radio.*); none = nothing."""
        if RadioFX._PW is None:
            RadioFX._PW = False
            try:
                import soundfile as sf
                d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Trackside", "sounds")
                for ext in (".wav", ".ogg", ".flac"):
                    f = os.path.join(d, "amb_pitwall_radio" + ext)
                    if os.path.exists(f):
                        a, sr = sf.read(f, dtype="float32", always_2d=True)
                        a = a.mean(1)
                        if sr != self.sr:
                            idx = np.arange(0, len(a), sr / self.sr)
                            a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
                        a /= (np.sqrt(np.mean(a ** 2)) + 1e-9)
                        RadioFX._PW = a
                        break
            except Exception as e:
                print("[voice] pit wall bed:", e)
        a = RadioFX._PW
        if a is False or a is None or len(a) < n:
            return None
        at = np.random.randint(0, len(a) - n + 1)
        return a[at:at + n]

    def __call__(self, x, cond=True):
        if self.board is None:
            return x
        if cond and RadioFX.COND.get("pitwall", True) and RadioFX.COND.get("on", True):
            bed = self._pitwall(len(x) if np.ndim(x) == 1 else x.shape[-1])
            if bed is not None:
                lvl = np.sqrt(np.mean(np.square(x))) + 1e-9
                if np.ndim(x) == 1:
                    x = x + bed * lvl * 0.06                # about 24 dB under the voice, then through the radio
                else:
                    x = x + bed[None, :] * lvl * 0.06
        y = self.board(x, self.sr)
        c = RadioFX.COND
        rain, far = (float(c.get("rain", 0) or 0), float(c.get("far", 0) or 0)) if (cond and c.get("on", True)) else (0.0, 0.0)
        hiss = self.hiss
        if hiss is not None and (rain > 0.05 or far > 0.3):
            hiss = max(hiss, -62) + 9 * rain + 4 * max(0.0, far - 0.3)
        if hiss is not None and hiss > -85:
            h = np.random.standard_normal(len(y)).astype(np.float32) * (10 ** (hiss / 20))
            y = y + self._hp(h, self.sr)
        if far > 0.45 and len(y) > self.sr // 2:        # the far side of the lap: a couple of short signal dips + crackle
            rng = np.random.default_rng()
            n = len(y)
            for _ in range(int(rng.integers(0, 2 + int(3 * (far - 0.45))))):
                at = int(rng.integers(self.sr // 4, n - self.sr // 10)); L = int(rng.uniform(0.03, 0.09) * self.sr)
                env = 1 - (1 - rng.uniform(0.15, 0.4)) * np.sin(np.linspace(0, np.pi, min(L, n - at))) ** 2
                y[at:at + len(env)] *= env.astype(np.float32)
                k = min(int(0.012 * self.sr), n - at)
                y[at:at + k] += (rng.standard_normal(k) * 0.05 * far).astype(np.float32)
        return y.astype(np.float32)


# ---------- spotter calls in a CrewChief spotter voice (read from the user's own CrewChief install) ----------
CC_VOICE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CrewChiefV4", "Sounds", "voice")
SPOT_MAP = {"car_left": "car_left", "car_right": "car_right", "clear_left": "clear_left", "clear_right": "clear_right",
            "clear": "clear_all_round", "still_there": "still_there", "three_wide": "in_the_middle"}
SPOT_TEXT = {"car_left": "Car left.", "car_right": "Car right.", "clear_left": "Clear left.", "clear_right": "Clear right.",
             "clear": "Clear all round.", "still_there": "Still there.", "three_wide": "Three wide, you're in the middle."}


# built-in spotter voices (2026-10-24): invented voices rendered for Instability Control, same folder layout as CrewChief's
SPOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Spotter")
DEFAULT_SPOTTER = "Max"
# race control / race director clips (2026-10-24): the user's own recordings, one file per moment
# (gotogrid, formation, green, practice, qualifying .wav) - personal files, never shipped
RC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "RaceControl")
# what the race director actually says in each clip (transcribed 2026-10-23) - shown word for word on the overlay card
RC_TEXT = {"gotogrid": "Race control: Teams and drivers, go to the grid for a race start.",
           "formation": "Race control: Formation lap has started.",
           "green": "Race control: Green flag, green flag.",
           "practice": "Race control: 8, 7, 6, 5, 4, 3, 2, 1. Pit exit is now open. Pit exit is now open. Free practice has started.",
           "qualifying": "Race control: Under 30 seconds to open pit exit. 2, 1. Pit exit is now open. Qualifying session has started. Pit exit is open."}

# the same words with timing (seconds into the clip) so the overlay card captions him live
RC_CUES = {"gotogrid": "[[0]]Teams and drivers, go to the grid for a race start.[[end=4.1]]",
           "formation": "[[0]]Formation lap has started.[[end=2.4]]",
           "green": "[[0]]Green flag, green flag.[[end=2.1]]",
           "practice": "[[0]]8, 7, 6, 5, 4, 3, 2, 1.[[9.0]]Pit exit is now open.[[10.9]]Pit exit is now open.[[12.8]]Free practice has started.[[end=15.9]]",
           "qualifying": "[[0]]Under 30 seconds to open pit exit.[[4.4]]2, 1.[[6.7]]Pit exit is now open.[[8.6]]Qualifying session has started.[[10.7]]Pit exit is open.[[end=14.6]]"}


def builtin_spotters():
    """Built-in spotter voices that have their calls rendered -> ["Jess", "Leo", "Max"]"""
    out = []
    try:
        for n in sorted(os.listdir(SPOT_DIR)):
            d = os.path.join(SPOT_DIR, n)
            if all(os.path.isdir(os.path.join(d, k)) and any(f.endswith(".wav") for f in os.listdir(os.path.join(d, k)))
                   for k in set(SPOT_MAP.values())):
                out.append(n)
    except OSError:
        pass
    return out


def spotter_dir(name):
    """Folder holding a spotter voice: built-in first, then the user's CrewChief install ("cc:Clare" or a plain old name)."""
    if not name:
        return None
    if name.startswith("cc:"):
        return os.path.join(CC_VOICE_DIR, f"spotter_{name[3:]}")
    d = os.path.join(SPOT_DIR, name)
    return d if os.path.isdir(d) else os.path.join(CC_VOICE_DIR, f"spotter_{name}")


def cc_spotters():
    """CrewChief spotter voices installed on this PC -> ["Clare", "Geoffrey", ...]"""
    try:
        return sorted(d[len("spotter_"):] for d in os.listdir(CC_VOICE_DIR) if d.startswith("spotter_"))
    except OSError:
        return []


def _recorded_name(manifest):
    """The first name the voice library was recorded with, worked out from the library itself: the word the
    recorded lines have that their name-free versions (lines_new.NAME_FREE) don't. "" when it can't be told."""
    votes = {}
    by_sid = {}
    for ln in manifest.get("lines", []):
        by_sid.setdefault(ln.get("situation"), []).append(ln.get("text") or "")
    word = lambda t: set(re.findall(r"[^\W\d_]+", re.sub(r"\[[^\]]*\]|\{[^}]*\}", " ", t).lower()))
    for sid, _lang, free in getattr(lines_new, "NAME_FREE", []):
        fw = word(free)
        for t in by_sid.get(sid, []):
            extra = [w for w in word(t) - fw if len(w) > 2]
            if len(extra) == 1:
                votes[extra[0]] = votes.get(extra[0], 0) + 1
    if not votes:
        return ""
    w, n = max(votes.items(), key=lambda kv: kv[1])
    return w.capitalize() if n >= 3 else ""


class Voice:
    def __init__(self, vocab_dir, preset_path=None, gtp=False, fuel_metric=False, corners=None,
                 output=True, device=None, volume=1.0, log=print, strength=1.0):
        self.dir = vocab_dir
        self.m = json.load(open(os.path.join(vocab_dir, "manifest.json"), encoding="utf-8"))
        self.lines = {}
        for ln in self.m["lines"]:
            self.lines.setdefault(ln["situation"], []).append(ln)
        self.blocks = self.m["blocks"]
        self.new = lines_new.table()     # written but not rendered yet -> stand-in voice
        self.last_said = None            # (sid, fills) of the last line played, for "say again"
        self.driver_name = ""            # the name the team uses; recorded variants that say another name are skipped
        self.recorded_name = self.m.get("recorded_name") or _recorded_name(self.m)   # the name the library was recorded with
        self.gtp, self.fuel_metric, self.corners = gtp, fuel_metric, corners
        self.log, self.volume = log, volume
        self._cache, self._last_variant = {}, {}
        self.sr = 24000
        self.fx = RadioFX(preset_path, self.sr, strength)
        self._q, self._seq = [], itertools.count()
        self._cv = threading.Condition()
        self._stop_now = False
        self.recording = None  # list of arrays when recording a demo
        self.player = None
        self.on_say = None     # callback(text) for the window's live readout
        self._alive = True
        self.rc_volume = 0.8   # race control clips (Settings > Race Control)
        self.spotter = ""      # "" = engineer's voice; a built-in spotter ("Max"); or a CrewChief one ("cc:Clare")
        if output:
            self.player = _Player(self.sr, device)
            threading.Thread(target=self._worker, daemon=True).start()

    def set_device(self, device):
        if self.player:
            old = self.player
            self.player = _Player(self.sr, device)
            old.close()

    def close(self):
        self._alive = False
        if self.player:
            self.player.close()

    def test_tone(self):
        """Say a radio check right now (for the Sound tab)."""
        self.say("radio_check", prio=PRIO_URGENT)

    # ---------- building ----------
    def _load(self, rel):
        if rel in self._cache:
            return self._cache[rel]
        p = os.path.join(self.dir, rel.replace("/", os.sep))
        if not os.path.exists(p):
            self._cache[rel] = None
            return None
        a, sr = sf.read(p, dtype="float32")
        if a.ndim > 1:
            a = a.mean(1)
        if sr != self.sr:
            try:
                import librosa
                a = librosa.resample(a, orig_sr=sr, target_sr=self.sr)
            except ImportError:
                a = np.interp(np.arange(0, len(a), sr / self.sr), np.arange(len(a)), a).astype(np.float32)
        self._cache[rel] = a
        return a

    def clip_exists(self, rel):
        """Is this library clip (relative path from the manifest) rendered?"""
        return os.path.exists(os.path.join(self.dir, rel.replace("/", os.sep)))

    def has(self, sid):
        if sid.startswith("rc:"):          # race control clip: there if the file is (2026-10-24 fix: was always "no")
            return os.path.exists(os.path.join(RC_DIR, sid[3:] + ".wav"))
        return sid in self.lines or sid in self.new

    def _names_ok(self, text):
        """False for a recorded variant that says a name other than the driver's."""
        rec = (self.recorded_name or "").strip().lower()
        if not rec:                                        # library name unknown: nothing to skip
            return True
        n = (self.driver_name or "").strip().lower()      # beta (2026-10-24): no name set = skip the named variants
        return n == rec or not re.search(r"\b" + re.escape(rec) + r"\b", (text or "").lower())

    def _standin(self, sid, fills, texts=None):
        """A line that isn't recorded yet, said by the stand-in voice. (audio, text) or (None, None)."""
        vs = texts or self.new.get(sid)
        if not vs:
            return None, None
        want = fills.get("_variant")
        text = vs[want - 1] if want and 0 < want <= len(vs) else random.choice(vs)
        used = {}
        def sub(m):
            name = m.group(1)
            val = fills.get(name)
            if isinstance(val, (list, tuple)):
                k = used.get(name, 0); used[name] = k + 1
                val = val[min(k, len(val) - 1)] if val else None
            t = F.fill_text(name, val, self.fuel_metric)
            if t is None:
                raise KeyError(name)
            return t
        try:
            text = re.sub(r"\[([^\]]+)\]", sub, text)
        except KeyError:
            return None, None
        if not self.gtp:
            text = re.sub(r"\s*\{GTP:[^}]*\}", "", text)
        text = text.replace("{GTP:", "").replace("}", "")
        from . import standin
        a = standin.synth(text, self.sr)
        if a is None:
            return None, text
        lead = np.zeros(int(0.05 * self.sr), np.float32)
        return _loud(self.fx(np.concatenate([lead, a, lead])), self.volume), text

    def _usable(self, ln, fills):
        """List of clip paths for this variant, or None if it can't be said."""
        clips, spoken, used = [], False, {}
        texts, ti = self._texts_of(ln), 0
        for part in ln["parts"]:
            if "fill" in part:
                name = part["fill"]
                val = fills.get(name)
                if isinstance(val, (list, tuple)):  # same slot twice in one line, e.g. "[laps] laps, [laps] to go"
                    k = used.get(name, 0); used[name] = k + 1
                    val = val[min(k, len(val) - 1)] if val else None
                c = F.fill_clips(name, val, self.blocks, self)
                if c is None:
                    return None
                # same fill used twice (e.g. "[P], [P]") -> repeat it
                clips += c
                continue
            txt = texts[ti] if ti < len(texts) else ""; ti += 1
            if part.get("gtp") and not self.gtp:
                continue
            if SKIP_PART.search(txt):
                continue
            clip = part["clip"]
            # 2026-10-24 (request: "he says car like carrrrrrr"): "Car" was rendered separately for every line and
            # many takes drag ("CAH!", "Carl!"). Every part that is just "Car" uses one clean take.
            if CAR_CLIP and re.sub(r"[^a-z]", "", txt.lower()) == "car" and self._load(CAR_CLIP) is not None:
                clip = CAR_CLIP
            if self._load(clip) is None:
                return None
            clips.append(clip); spoken = True
        return clips or None

    _TOK = re.compile(r"(\[[^\]]+\]|\{GTP:[^}]*\})")

    def _texts_of(self, ln):
        """Script text of each spoken piece, in order (same split the renderer used)."""
        if "_texts" not in ln:
            out = []
            for tok in self._TOK.split(ln["text"]):
                tok = tok.strip()
                if not tok or (tok.startswith("[") and tok.endswith("]")):
                    continue
                t = tok[5:-1] if tok.startswith("{GTP:") else tok
                if re.search(r"[A-Za-z0-9]", t):
                    out.append(t)
            ln["_texts"] = out
        return ln["_texts"]

    def _build_spotter(self, sid):
        base = spotter_dir(self.spotter)
        if not base:
            return None, None
        d = os.path.join(base, SPOT_MAP[sid])
        try:
            wavs = sorted(f for f in os.listdir(d) if f.lower().endswith(".wav"))
        except OSError:
            return None, None
        if not wavs:
            return None, None
        last = self._last_variant.get("spot:" + sid)
        f = random.choice([w for w in wavs if w != last] or wavs)
        self._last_variant["spot:" + sid] = f
        a = self._load(os.path.join(d, f))         # absolute path: os.path.join keeps it
        if a is None:
            return None, None
        lead = np.zeros(int(0.03 * self.sr), np.float32)
        return _loud(self.fx(np.concatenate([lead, a, lead]), cond=False), self.volume), SPOT_TEXT[sid]   # spotter: never dips

    def build(self, sid, fills=None):
        fills = fills or {}
        if sid.startswith("rc:"):          # race control clip: clean (no radio effect), own volume, capped
            name = sid[3:]
            a = self._load(os.path.join(RC_DIR, name + ".wav"))
            if a is None:
                return None, None
            vol = min(1.0, max(0.0, float(getattr(self, "rc_volume", 0.8))))
            if RadioFX.COND.get("pitlane"):
                a = _pit_echo(a, self.sr if hasattr(self, "sr") else 24000)
            return (a * vol * min(1.0, self.volume)).astype(np.float32), RC_TEXT.get(name, "Race control.")
        if self.spotter and sid in SPOT_MAP:
            a, t = self._build_spotter(sid)
            if a is not None:
                return a, t
        vs = self.lines.get(sid, [])
        want = fills.get("_variant")
        if want:
            vs = [ln for ln in vs if ln["variant"] == want] or vs
        opts = []
        for ln in vs:
            if not self._names_ok(ln["text"]):
                continue
            c = self._usable(ln, fills)
            if c:
                opts.append((ln, c))
        if not opts:
            if sid in self.new:
                return self._standin(sid, fills)
            named = [ln for ln in vs if not self._names_ok(ln["text"])]
            if named:      # every recording says the recorded name: the stand-in says it with the right name (English ones first)
                nm = (self.driver_name or "").strip() or "driver"
                pick = [ln for ln in named if ln.get("lang", "en") == "en"] or named
                rx = r"(?i)\b" + re.escape(self.recorded_name.strip()) + r"\b"
                return self._standin(sid, fills, texts=[re.sub(rx, nm, ln["text"]) for ln in pick])
            return None, None
        last = self._last_variant.get(sid)
        pick = [o for o in opts if o[0]["variant"] != last] or opts
        ln, clips = random.choice(pick)
        self._last_variant[sid] = ln["variant"]
        said = ln["text"] if self.gtp else re.sub(r"\s*\{GTP:[^}]*\}", "", ln["text"])
        gap = np.zeros(int(0.06 * self.sr), np.float32)
        audio = []
        for c in clips:
            a = self._load(c)
            if a is not None:
                audio += [a, gap]
        x = np.concatenate(audio) if audio else np.zeros(1, np.float32)
        lead = np.zeros(int(0.05 * self.sr), np.float32)
        x = np.concatenate([lead, x, lead])
        for k, val in fills.items():
            if k.startswith("_"):
                continue
            vals = list(val) if isinstance(val, (list, tuple)) else [val]
            i = 0
            while f"[{k}]" in said:
                xv = vals[min(i, len(vals) - 1)]; i += 1
                shown = F.shown(k, xv) or str(round(xv, 1) if isinstance(xv, float) else xv).replace("_", " ")
                if k == "corner":
                    shown = shown.title().replace("Nascar", "NASCAR")
                said = said.replace(f"[{k}]", shown, 1)
        return _loud(self.fx(x), self.volume), said

    # ---------- speaking ----------
    def say(self, sid, fills=None, prio=PRIO_INFO, max_age=None):
        """Queue a line. Spotter calls cut off whatever is playing. max_age drops stale messages."""
        with self._cv:
            if prio == PRIO_SPOTTER:
                # spotter is about now: drop older spotter calls, interrupt lower-priority speech
                self._q = [q for q in self._q if q[0] != PRIO_SPOTTER]
                heapq.heapify(self._q)
                if self.player and self.player.playing_prio is not None and self.player.playing_prio > PRIO_SPOTTER:
                    self.player.stop()
            if prio <= PRIO_URGENT:              # also cut the strategist / team voice
                RADIO.interrupt_below(prio, me=self.player)
            exp = time.time() + (max_age if max_age else (2.0 if prio == PRIO_SPOTTER else 30.0))
            heapq.heappush(self._q, (prio, next(self._seq), sid, fills or {}, exp))
            self._cv.notify()

    def say_now(self, sid, fills=None, max_age=20.0):
        """Race control (2026-10-25): plays right now - stops whatever this voice or any other voice is saying, jumps
        the queue (even the spotter waits), and is never held back while braking."""
        with self._cv:
            if self.player and self.player.playing_prio is not None:
                self.player.stop()
            RADIO.interrupt_below(-1, me=self.player)
            heapq.heappush(self._q, (-1, next(self._seq), sid, fills or {}, time.time() + max_age))
            self._cv.notify()

    def pending(self):
        with self._cv:
            return len(self._q)

    def hold(self, flag):
        """While held (driver braking/turning), only spotter and urgent calls are spoken."""
        self._hold = flag

    def _worker(self):
        self._hold = False
        while self._alive:
            with self._cv:
                while self._alive:
                    now = time.time()
                    if simload.BUSY:
                        # #454: loading screen - nothing is said (the PC is at its busiest and the sound would chop);
                        # lines are kept, their clocks paused, and play once the sim runs smoothly again
                        self._q = [(p_, s_, i_, f_, e_ + 0.1) for (p_, s_, i_, f_, e_) in self._q]
                        heapq.heapify(self._q)
                        self._cv.wait(0.1)
                        continue
                    self._q = [q for q in self._q if q[4] > now]
                    heapq.heapify(self._q)
                    if self._q and (not self._hold or self._q[0][0] <= PRIO_URGENT):
                        want = self._q[0][0]
                        break
                    self._cv.wait(0.1)
                else:
                    return
            # wait for the shared radio WITHOUT taking the line yet, so a spotter call arriving meanwhile goes first
            if not RADIO.take(self.player, want, timeout=0.15):
                continue
            with self._cv:
                now = time.time()
                self._q = [q for q in self._q if q[4] > now]
                heapq.heapify(self._q)
                if not self._q or (self._hold and self._q[0][0] > PRIO_URGENT):
                    RADIO.give(self.player)
                    continue
                prio, _, sid, fills, _ = heapq.heappop(self._q)
            RADIO.owner = (self.player, prio)
            audio, text = self.build(sid, fills)
            if audio is None:
                RADIO.give(self.player)
                self.log(f"[voice] can't say {sid} {fills}")
                continue
            self.log(f"ENGINEER: {text}")
            if sid != "b2_repeat_last_message" and PRIO_SPOTTER < prio <= PRIO_INFO:   # never repeat a stale "car left"
                self.last_said = (sid, fills)
            if self.on_say:
                try: self.on_say(text)
                except Exception: pass
            if self.recording is not None:
                self.recording += [audio, np.zeros(int(0.5 * self.sr), np.float32)]
            try:
                self.player.play(audio, prio)
            finally:
                RADIO.give(self.player)


class _Radio:
    """One radio channel for every voice (engineer clips, strategist, mechanic, team).
    Only one talks at a time; the most important waiting line goes next; a short breath between
    different voices; spotter and urgent calls cut off a lower-priority voice that is talking."""
    BREATH = 0.35

    def __init__(self):
        self.cv = threading.Condition()
        self.owner = None            # (player, prio)
        self.last, self.free_at = None, 0.0
        self.waiting = {}            # token -> prio

    def take(self, player, prio, timeout=60.0):
        end = time.time() + timeout
        with self.cv:
            self._n = getattr(self, "_n", 0) + 1
            tok = (prio, self._n)                 # most important first, then first come first served
            self.waiting[tok] = prio
            try:
                while True:
                    now = time.time()
                    alone = len(self.waiting) == 1
                    free = self.owner is None and ((player is self.last and alone) or now >= self.free_at or prio <= 0)   # spotter / race control: no pause
                    if free and tok == min(self.waiting):
                        self.owner = (player, prio)
                        return True
                    if now > end:
                        return False
                    self.cv.wait(0.05)
            finally:
                self.waiting.pop(tok, None)

    def give(self, player):
        with self.cv:
            if self.owner and self.owner[0] is player:
                self.owner = None
                self.last, self.free_at = player, time.time() + self.BREATH
            self.cv.notify_all()

    def interrupt_below(self, prio, me=None):
        """A more important call is waiting: cut whoever is talking if they matter less."""
        o = self.owner
        if o and o[1] > prio and o[0] is not me:
            try:
                o[0].stop()
            except Exception:
                pass


RADIO = _Radio()


# 2026-10-25 (request: "can I hear the engineer team radio on the iPad?"): every voice that goes on air passes through
# _Player.play; listeners here (the iPad link) get a copy of the clip as it starts. Never blocks or breaks playback.
TAPS = []


class _Player:
    def __init__(self, sr, device):
        import sounddevice as sd
        self.sd, self.sr, self.device = sd, sr, device
        self.playing_prio = None
        self._buf, self._pos = None, 0
        self._done = threading.Event()
        self._lock = threading.Lock()
        # 2026-10-27 (#451): 120 ms cushion (was ~10 ms) - the radio chopped whenever the app was busy for a moment
        self.stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32", device=device,
                                      callback=self._cb, blocksize=2048, latency=0.4)   # 2026-10-29: 0.4 s cushion - busy moments never chop
        self.stream.start()

    def _cb(self, out, frames, t, status):
        with self._lock:
            if self._buf is None:
                out[:] = 0
                return
            n = min(frames, len(self._buf) - self._pos)
            out[:n, 0] = self._buf[self._pos:self._pos + n]
            out[n:] = 0
            self._pos += n
            if self._pos >= len(self._buf):
                self._buf = None
                self._done.set()

    def play(self, audio, prio):
        for tap in list(TAPS):
            try:
                tap(audio, self.sr)
            except Exception:
                pass
        with self._lock:
            self._buf, self._pos = audio, 0
            self.playing_prio = prio
            self.cut = False
            self._done.clear()
        self._done.wait()
        self.playing_prio = None

    def close(self):
        try:
            self.stream.stop(); self.stream.close()
        except Exception:
            pass
        self._done.set()

    def stop(self):
        with self._lock:
            if self._buf is not None:
                self.cut = True
                # short fade so it doesn't click
                end = min(len(self._buf), self._pos + int(0.03 * self.sr))
                fade = self._buf[self._pos:end] * np.linspace(1, 0, end - self._pos, dtype=np.float32)
                self._buf = np.concatenate([self._buf[:self._pos], fade])
