# Headset/radio voice treatment demo: same audio, three strengths.
import os, numpy as np, soundfile as sf
from pedalboard import (Pedalboard, HighpassFilter, LowpassFilter, PeakFilter, LowShelfFilter,
                        HighShelfFilter, Compressor, Distortion, Gain, Limiter)
D = os.path.join(os.environ["USERPROFILE"], "Desktop", "Engineer Voice - Listen")
src, sr = sf.read(os.path.join(D, "All script lines.wav"), dtype="float32")
src = src[: int(sr * 70)]
if src.ndim > 1: src = src.mean(1)
rng = np.random.default_rng(1)

def hiss(n, db):  # faint band-limited radio noise floor
    h = rng.standard_normal(n).astype(np.float32) * (10 ** (db / 20))
    return Pedalboard([HighpassFilter(1500), LowpassFilter(6000)])(h, sr)

FX = {
 "1 - Barely (A30 mic, light radio)": (Pedalboard([
     HighpassFilter(160), LowShelfFilter(250, -2), PeakFilter(2800, 2.5, 1.0),
     LowpassFilter(7500), Compressor(-20, 3, 5, 120), Distortion(2), Gain(-1), Limiter(-1)]), -66),
 "2 - Headset over radio (medium)": (Pedalboard([
     HighpassFilter(250), LowShelfFilter(300, -3), PeakFilter(2200, 3.5, 0.9),
     LowpassFilter(5200), Compressor(-22, 4, 3, 100), Distortion(5), Gain(-2), Limiter(-1)]), -58),
 "3 - TV team radio (strong, for comparison)": (Pedalboard([
     HighpassFilter(320), PeakFilter(1800, 5, 0.8), LowpassFilter(3500),
     Compressor(-25, 6, 2, 80), Distortion(10), Gain(-4), Limiter(-1)]), -50),
}
sf.write(os.path.join(D, "Radio test - 0 - Clean (no effect).wav"), src, sr)
for name, (board, ndb) in FX.items():
    y = board(src, sr)
    y = y + hiss(len(y), ndb) * (np.abs(src) > 0.003).astype(np.float32)  # hiss only while he talks (mic keyed)
    y = y / max(1e-6, np.abs(y).max()) * 0.89
    sf.write(os.path.join(D, f"Radio test - {name}.wav"), y.astype(np.float32), sr)
print("ok", sr)
