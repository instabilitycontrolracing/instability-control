"""The F1-style team radio sound (#701/#703, 2026-10-31). Angelo, on the prototype: "that sounds truly excellent that is
the way the radio should sound in ear and on broadcast ... so much depth".

Modelled on his own source recording (CrewChiefVoices\\Engineer1\\TVoice chop.mp3, real F1 team radio), measured:
  - an OPEN channel: a constant car / engine / wind bed about 20 dB under the voice while the radio is keyed
    (taken from the quiet gaps of his recording - personal, never shipped)
  - a full voice: high-pass ~110 Hz (the chest stays), a gentle top roll-off, nothing harsh
  - heavily compressed (~12 dB between loud and quiet words), light warm saturation, NO bit-crush / sample-and-hold fizz
Used for the engineer in the headset (voice.RadioFX), the TV / stream radio (broadcast player) and his live radio.
"""
import os, threading
import numpy as np

SRC = next((p for p in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Engineer1", "TVoice chop.mp3"),
                        os.path.join(os.path.expanduser("~"), "Documents", "CrewChiefVoices", "Engineer1", "TVoice chop.mp3"))
            if os.path.exists(p)), "")
# ic179 (#710, Angelo: "that sound in the background is actually the f1 car ... this is sports cars"): the engineer's
# bed is now the pit stall (his Trackside pit recording, levelled), not the F1 engine. His own mic gets no made-up bed
# (next: the real game sound playing at that moment).
_SND = next((d for d in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Trackside", "sounds"),
                         os.path.join(os.path.expanduser("~"), "Documents", "CrewChiefVoices", "Trackside", "sounds"))
             if os.path.isdir(d)), "")
PIT_SRC = os.path.join(_SND, "pit_gtp_stop_1.wav")
CHEERS = [os.path.join(_SND, f) for f in ("cheer_B_short_mid.wav", "cheer_A_short_mid.wav")]
BED_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RaceEngineer", "radio_bed_pit_48k.npy")
SR_BED = 48000
BED_DB = -17.0
_bed = None
_lock = threading.Lock()
_sos_cache = {}


def bed(sr=SR_BED):
    """The open-channel bed (unit RMS) at sample rate sr, or None if his recording isn't on this PC."""
    global _bed
    with _lock:
        if _bed is None:
            _bed = False
            try:
                if os.path.exists(BED_FILE):
                    _bed = np.load(BED_FILE).astype(np.float32)
                elif os.path.exists(PIT_SRC):
                    _bed = _make_pit_bed()
                    os.makedirs(os.path.dirname(BED_FILE), exist_ok=True)
                    np.save(BED_FILE, _bed)
            except Exception:
                _bed = False
        b = _bed if _bed is not False else None
    if b is None:
        return None
    if sr != SR_BED:
        b = np.interp(np.linspace(0, len(b) - 1, int(len(b) * sr / SR_BED)), np.arange(len(b)), b).astype(np.float32)
    return b


def _load48(path):
    import soundfile as sf
    x, s = sf.read(path, dtype="float32", always_2d=True)
    x = x.mean(1)
    if s != SR_BED:
        from scipy.signal import resample_poly
        x = resample_poly(x, SR_BED, s).astype(np.float32)
    return x


def _make_pit_bed():
    """ic179: the pit-stall recording with its loud and quiet moments evened out (slow level follower), low rumble cut."""
    from scipy.signal import butter, sosfilt
    x = _load48(PIT_SRC)
    hop = int(SR_BED * 0.05); n = len(x) // hop
    r = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-6
    r = np.convolve(r, np.ones(40) / 40, "same")
    g = np.interp(np.arange(len(x)), np.arange(n) * hop + hop / 2, 1 / r)
    g = np.minimum(g, np.percentile(g, 90))
    y = sosfilt(butter(2, 150, "highpass", fs=SR_BED, output="sos"), x * g)
    return (y / (np.sqrt(np.mean(y ** 2)) + 1e-9)).astype(np.float32)


_cheers = None


def _cheer(sr):
    """ic179: a crowd cheer (unit RMS, band-limited like a far-off crowd through the radio) or None."""
    global _cheers
    with _lock:
        if _cheers is None:
            _cheers = []
            for f in CHEERS:
                try:
                    if os.path.exists(f):
                        from scipy.signal import butter, sosfilt
                        c = sosfilt(butter(2, [250, 3500], "bandpass", fs=SR_BED, output="sos"), _load48(f))
                        _cheers.append((c / (np.sqrt(np.mean(c ** 2)) + 1e-9)).astype(np.float32))
                except Exception:
                    pass
        cs = list(_cheers)
    if not cs:
        return None
    c = cs[np.random.default_rng().integers(0, len(cs))]
    if sr != SR_BED:
        c = np.interp(np.linspace(0, len(c) - 1, int(len(c) * sr / SR_BED)), np.arange(len(c)), c).astype(np.float32)
    return c


def _make_bed():
    import soundfile as sf
    x, s = sf.read(SRC, dtype="float32", always_2d=True)
    x = x.mean(1)
    if s != SR_BED:
        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * SR_BED / s)), np.arange(len(x)), x).astype(np.float32)
    hop = 2400
    fr = np.lib.stride_tricks.sliding_window_view(x, hop)[::hop]
    rms = np.sqrt((fr ** 2).mean(1)); thr = np.percentile(rms, 20)
    pieces = [fr[i] for i in range(len(fr)) if 1e-5 < rms[i] <= thr]
    xf = 240; out = pieces[0].copy()
    for p in pieces[1:400]:
        ramp = np.linspace(0, 1, xf); out[-xf:] = out[-xf:] * (1 - ramp) + p[:xf] * ramp; out = np.concatenate([out, p[xf:]])
    return (out / (np.sqrt(np.mean(out ** 2)) + 1e-9)).astype(np.float32)


def _sos(sr):
    s = _sos_cache.get(sr)
    if s is None:
        from scipy.signal import butter
        s = (butter(2, 110, "highpass", fs=sr, output="sos"), butter(2, 3200, "lowpass", fs=sr, output="sos"),
             butter(2, min(10000, sr * 0.45), "lowpass", fs=sr, output="sos"))
        _sos_cache[sr] = s
    return s


def _comp(x, sr, thresh_db=-24.0, ratio=6.0, rel=0.08):
    """Fast compressor (vectorised): a peak-follower envelope (instant attack, ~80 ms release), 6:1 above -24 dB."""
    from scipy.signal import lfilter
    a = np.exp(-1.0 / (rel * sr))
    env = lfilter([1 - a], [1, -a], np.abs(x))
    env = np.maximum(env, np.abs(x) * 0.7)
    lin = 10 ** (thresh_db / 20)
    g = np.ones_like(env)
    m = env > lin
    g[m] = (lin * (env[m] / lin) ** (1.0 / ratio)) / env[m]
    return x * g


def process(x, sr, bed_db=BED_DB, seed=None, open_bed=True, cheer_db=None):
    """A whole radio clip -> the F1-style radio sound (float32, peak ~0.85)."""
    from scipy.signal import sosfilt
    x = np.asarray(x, np.float32).reshape(-1)
    if not x.size:
        return x
    hp, lp1, lp2 = _sos(sr)
    y = sosfilt(hp, x)
    y = sosfilt(lp1, y) * 0.35 + sosfilt(lp2, y) * 0.65
    y = y / (np.abs(y).max() + 1e-9)
    y = _comp(y, sr)
    y = np.tanh(y * 1.6) / np.tanh(1.6)
    y = y / (np.abs(y).max() + 1e-9) * 0.85
    b = bed(sr) if open_bed else None
    if b is not None and len(b) > sr:
        rng = np.random.default_rng(seed)
        st = int(rng.integers(0, len(b)))
        bb = np.resize(np.roll(b, -st), len(y))
        lvl = np.sqrt(np.mean(y[np.abs(y) > 0.05] ** 2)) if np.any(np.abs(y) > 0.05) else 0.2
        f = min(int(0.03 * sr), len(y) // 2)
        env = np.ones(len(y), np.float32)
        if f > 0:
            env[:f] = np.linspace(0, 1, f); env[-f:] = np.linspace(1, 0, f)
        y = y + bb * (lvl * 10 ** (bed_db / 20)) * env
    if cheer_db is not None:                       # ic179: good-news call -> the crowd cheers under it, swelling in
        c = _cheer(sr)
        if c is not None:
            lvl = np.sqrt(np.mean(y[np.abs(y) > 0.05] ** 2)) if np.any(np.abs(y) > 0.05) else 0.2
            cc = np.resize(c, len(y)) * np.minimum(1.0, np.arange(len(y)) / (0.4 * sr))
            f = min(int(0.15 * sr), len(y) // 2)
            if f > 0:
                cc[-f:] *= np.linspace(1, 0, f)
            y = y + cc * (lvl * 10 ** (cheer_db / 20))
    pk = float(np.abs(y).max())
    if pk > 0.9:                                   # ic179: bring it down rather than clip the voice peaks
        y = y * (0.88 / pk)
    return np.clip(y, -0.98, 0.98).astype(np.float32)


class Stream:
    """The same sound for live audio in blocks (his push-to-talk radio): filter states, the compressor envelope and the
    bed position carry over from block to block, so there are no clicks at the joins."""

    def __init__(self, sr):
        from scipy.signal import sosfilt_zi
        self.sr = sr
        self.hp, self.lp1, self.lp2 = _sos(sr)
        self.z = [sosfilt_zi(s) * 0.0 for s in (self.hp, self.lp1, self.lp2)]
        self.env = 0.0
        self.a = np.exp(-1.0 / (0.08 * sr))
        self.pk = 0.05
        self.b = None          # ic179: no bed on his own mic (the F1 engine is gone; the real game sound comes next)
        self.bpos = 0 if self.b is None else int(np.random.default_rng().integers(0, len(self.b)))

    def block(self, x):
        from scipy.signal import sosfilt
        x = np.asarray(x, np.float32).reshape(-1)
        y, self.z[0] = sosfilt(self.hp, x, zi=self.z[0])
        a1, self.z[1] = sosfilt(self.lp1, y, zi=self.z[1])
        a2, self.z[2] = sosfilt(self.lp2, y, zi=self.z[2])
        y = a1 * 0.35 + a2 * 0.65
        pk = float(np.abs(y).max()) if len(y) else 0.0          # slow level follower instead of per-clip normalising
        if getattr(self, "_g", None) is None:
            self.pk = max(pk, 0.02)
        self.pk = max(pk, self.pk * 0.97, 0.02)
        g_new = 1.0 / self.pk
        g_old = getattr(self, "_g", None) or g_new
        self._g = g_new
        y = y * np.linspace(g_old, g_new, len(y), dtype=np.float32)   # glide, never a step between blocks
        env = np.empty_like(y); e = self.env; a = self.a
        for i, v in enumerate(np.abs(y)):                        # one block (~1000 samples): fine in a loop
            e = v if v > e else a * e + (1 - a) * v
            env[i] = e
        self.env = e
        lin = 10 ** (-24 / 20); g = np.ones_like(env); m = env > lin
        g[m] = (lin * (env[m] / lin) ** (1 / 6.0)) / env[m]
        y = np.tanh(y * g * 1.6) / np.tanh(1.6) * 0.85
        if self.b is not None:
            n = len(y); idx = (np.arange(n) + self.bpos) % len(self.b); self.bpos = (self.bpos + n) % len(self.b)
            y = y + self.b[idx] * (0.3 * 10 ** (BED_DB / 20))
        return np.clip(y, -0.98, 0.98).astype(np.float32)
