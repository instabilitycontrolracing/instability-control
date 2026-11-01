"""Headset cues on their own high-priority channel (#693/#694, 2026-10-31).

Angelo: "what if we had a high priority circuit for things like the shift beep and the radio key up and key out sounds
that play in the headset?" - and he picked the 'struck chime' set ("yeah I love it").

Why: every cue used to open a brand-new connection to the sound card (sounddevice.play) - slow when the PC is busy
(the beep landed late = "the shift beeps get stalled"), and only one such sound could play at a time (a radio chirp
could cut a beep off). Now one small sound program (audio_proc.py, the same one that fixed the radio / crowd chop)
stays open the whole time with a short buffer, at top priority, and a cue is dropped straight into it.

The sounds (research: IEC 60601-1-8 / Patterson - base note 150-1000 Hz with overtones up to ~4 kHz, a soft start;
Foley, Schlesinger & Schutz - struck, decaying sounds are less annoying AND easier to notice; urgency from repetition):
  shift      one "ting", B5 988 Hz (follows the shift-pitch slider: 1400 on the slider = 988 Hz)
  radio down two notes rising, G5 784 -> C6 1047 Hz        radio up  the same falling, then a short squelch
  limiter    a rising fifth, A5 880 -> E6 1319 Hz           pit fast  a 932 Hz ting (the caller repeats it faster)
"""
import os, threading, time
import numpy as np

SR = 48000
LATENCY = 0.03            # the sound card cushion: ~30 ms, so a cue is heard almost at once
_lock = threading.Lock()
_out = None               # the ProcOut (separate sound program), or None
_starting = False
_failed = False
_cache = {}


# ------------------------------------------------------------------ the sounds
def strike(f0, dur=0.16, tau=0.085, attack=0.006, amp=1.0):
    """One struck note: the base + 2x/3x/4x overtones and a short glassy 2.76x 'sparkle', higher ones fading faster;
    a 6 ms soft start, then a natural decay. Peak = amp."""
    n = int(SR * dur); t = np.arange(n) / SR
    parts = [(1.0, 1.00, tau), (2.0, 0.42, tau * 0.55), (3.0, 0.22, tau * 0.40), (4.0, 0.12, tau * 0.30), (2.76, 0.18, tau * 0.22)]
    x = np.zeros(n)
    for ratio, a, tt in parts:
        f = f0 * ratio
        if f > 4200:
            continue
        x += a * np.sin(2 * np.pi * f * t) * np.exp(-t / tt)
    x *= np.minimum(1.0, t / attack)
    fade = int(SR * 0.01); x[-fade:] *= np.linspace(1, 0, fade)
    return (amp * x / max(1e-9, np.abs(x).max())).astype(np.float32)


def _place(notes, total):
    y = np.zeros(int(SR * total), np.float32)
    for at, x in notes:
        i = int(SR * at); y[i:i + len(x)] += x[:len(y) - i]
    return y


def _squelch(level=0.22):
    rng = np.random.default_rng(2); n = int(SR * 0.06)
    s = rng.standard_normal(n) * level * np.linspace(1, 0, n) ** 2
    try:
        from scipy.signal import butter, sosfilt
        s = sosfilt(butter(4, [700, 4500], btype="band", fs=SR, output="sos"), s)
    except Exception:
        pass
    return s.astype(np.float32)


def sound(kind, f0=988.0, length_ms=60):
    """The cue at unit level (peak ~1); the caller sets the volume."""
    key = (kind, round(f0), int(length_ms))
    x = _cache.get(key)
    if x is not None:
        return x
    if kind == "shift":
        x = strike(f0, tau=0.09 * max(0.5, min(3.0, length_ms / 60.0)), dur=max(0.12, min(0.45, 0.16 * length_ms / 60.0)))
    elif kind == "radio_down":
        x = _place([(0, strike(784, 0.12, 0.05)), (0.06, strike(1047, 0.13, 0.055))], 0.2)
    elif kind == "radio_up":
        x = np.concatenate([_place([(0, strike(1047, 0.12, 0.05)), (0.06, strike(784, 0.13, 0.055))], 0.16), _squelch() / 0.42])
    elif kind == "limiter":
        x = _place([(0, strike(880, 0.12, 0.05)), (0.11, strike(1319, 0.13, 0.055))], 0.26)
    elif kind == "pit_fast":
        x = strike(932, 0.12, 0.05)
    else:
        x = strike(f0, 0.12, 0.05)
    x = (x / max(1e-9, float(np.abs(x).max()))).astype(np.float32)
    x.setflags(write=False)
    _cache[key] = x
    return x


# ------------------------------------------------------------------ the channel
def start(settings, log=print):
    """Open the cue channel in the background (the engine calls this at start-up); cues fall back to the old way
    until it's ready, or if it can't open."""
    global _starting
    with _lock:
        if _out is not None or _starting or _failed:
            return
        _starting = True
    def go():
        global _out, _starting, _failed
        try:
            from .audio_proc import ProcOut
            dev = getattr(settings, "device", None) or None
            o = ProcOut(SR, 1, dev, seconds=3.0, name="cues", log=log, latency=LATENCY)
            _out = o
            log("[cues] headset cue channel ready (high priority, ~30 ms)")
        except Exception as e:
            _failed = True
            log(f"[cues] cue channel couldn't open ({e!r}) - cues play the old way")
        finally:
            _starting = False
    threading.Thread(target=go, daemon=True).start()


def stop():
    global _out
    o, _out = _out, None
    if o is not None:
        try: o.close()
        except Exception: pass


def play(x, vol, settings=None):
    """Play a cue (unit-level float32 at 48 kHz) at volume vol (0..1). Never blocks, never cuts another cue off."""
    vol = max(0.0, min(1.0, float(vol)))
    if vol <= 0:
        return
    y = (x * vol).astype(np.float32)
    o = _out
    if o is not None:
        try:
            if o.alive() and o.ahead() < int(SR * 0.4):          # never queue a stale cue behind a backlog
                if o.write(y.reshape(-1, 1)):
                    return
        except Exception:
            pass
    try:                                                         # fallback: the old way
        import sounddevice as sd
        dev = getattr(settings, "device", None) if settings is not None else None
        sd.play(y, SR, device=dev or None, blocking=False)
    except Exception:
        pass
