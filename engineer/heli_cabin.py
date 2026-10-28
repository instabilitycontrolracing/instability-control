"""The 'inside the helicopter' sound for the TV helicopter camera (2026-10-26, #41).

Driver request (2026-10-24): when a replay cuts to the helicopter shot it should sound like you're sitting in the broadcast
chopper. Made here from scratch (no recording, nothing to licence): a low steady rotor thump, the tail rotor's whirr,
a muffled turbine whine, cabin rumble and air noise, all through a headset-style low-pass. Nothing is panned - we're
sitting in it. Every part repeats a whole number of times in the loop and the filtering is done in one circular
pass, so the loop has no seam.

A recording of your own wins: put a file named heli_cabin*.wav in the Trackside Crowd sounds folder.
"""
import numpy as np

RATE = 48000
SECONDS = 8                      # loop length; every frequency below repeats a whole number of times in it


def _tone(t, f, n=SECONDS):
    f = round(f * n) / n          # whole cycles per loop
    return np.sin(2 * np.pi * f * t)


def _band(spec_len, rate, lo, hi, slope=6.0):
    f = np.fft.rfftfreq(spec_len, 1 / rate)
    g = np.ones_like(f)
    with np.errstate(divide="ignore", invalid="ignore"):
        if lo > 0:
            g *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** (2 * slope / 6))
        if hi > 0:
            g *= 1 / np.sqrt(1 + (f / hi) ** (2 * slope / 6))
    return g


def _noise(n, rate, lo, hi, rng, slope=6.0, pink=True):
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / rate)
    if pink:
        spec /= np.sqrt(np.maximum(f, 20.0) / 20.0)
    spec *= _band(n, rate, lo, hi, slope)
    x = np.fft.irfft(spec, n)
    return x / (np.std(x) + 1e-12)


def make(rate=RATE, seconds=SECONDS, seed=7):
    """-> float32 stereo array (frames, 2), seamless loop, about -20 dBFS RMS."""
    n = rate * seconds
    t = np.arange(n) / rate
    rng = np.random.default_rng(seed)
    out = np.zeros((n, 2))
    # main rotor: 4 blades x 5.25 rev/s = 21 Hz blade pass, heard in the cabin as a soft thump with harmonics
    bp = 21.0
    phase = (t * bp) % 1.0
    pulse = np.exp(-((phase - 0.08) / 0.07) ** 2)                      # one soft push per blade
    sway = 1.0 + 0.10 * _tone(t, 0.25) + 0.05 * _tone(t, 0.625)       # slow breathing of the rotor load
    thump = pulse * sway
    thump_body = sum(a * _tone(t, bp * k) for k, a in ((1, 1.0), (2, 0.8), (3, 0.55), (4, 0.35), (5, 0.2), (6, 0.12)))
    rotor = thump_body * (0.35 + 0.65 * thump)
    # tail rotor whirr (about 105 Hz with a buzzy edge), quieter, slightly pulsing with the main rotor
    tail = sum(a * _tone(t, 105.0 * k) for k, a in ((1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15))) * (0.8 + 0.2 * thump)
    # turbine whine: two thin tones a few kHz up with a slow wobble, muffled by the cabin
    wob = 1.0 + 0.0008 * _tone(t, 0.375)
    turb = 0.6 * np.sin(2 * np.pi * np.cumsum(np.full(n, round(2240.0 * seconds) / seconds) * wob) / rate) \
        + 0.35 * np.sin(2 * np.pi * np.cumsum(np.full(n, round(3910.0 * seconds) / seconds) * wob) / rate)
    for ch in range(2):
        rumble = _noise(n, rate, 25, 90, rng, slope=12, pink=False) * (0.6 + 0.4 * thump)      # floor vibration
        air = _noise(n, rate, 120, 900, rng, slope=6)                                          # cabin air / wind
        hiss = _noise(n, rate, 1500, 5000, rng, slope=12, pink=False)                          # door seals
        out[:, ch] = (0.55 * rotor + 0.16 * tail + 0.035 * turb + 0.30 * rumble + 0.22 * air * (0.85 + 0.15 * thump)
                      + 0.03 * hiss)
    # cabin + headset: one circular pass (no seam) - low-pass ~3.2 kHz, a cabin resonance near 160 Hz, no deep sub
    spec = np.fft.rfft(out, axis=0)
    f = np.fft.rfftfreq(n, 1 / rate)
    g = _band(n, rate, 28, 3200, slope=12)
    g *= 1 + 0.6 * np.exp(-((f - 160) / 45) ** 2)
    spec *= g[:, None]
    out = np.fft.irfft(spec, n, axis=0)
    rms = np.sqrt(np.mean(out ** 2))
    out *= 10 ** (-20 / 20) / (rms + 1e-12)
    peak = np.max(np.abs(out))
    if peak > 10 ** (-3 / 20):
        out *= 10 ** (-3 / 20) / peak
    return out.astype(np.float32)


def clip(Clip):
    """A crowd.Clip ('heli_cabin') ready for the mixer (stereo int16 at 48 kHz)."""
    x = make()
    return Clip("heli_cabin", np.ascontiguousarray((np.clip(x, -1, 1) * 32767).astype(np.int16)), 1.0)
