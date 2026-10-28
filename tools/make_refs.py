import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, soundfile as sf
from test_lines import BASE, REF_WAV
# ~11 s single reference: the two longest clean baseline clips joined with a short pause
parts = []
for n in ["engineer_10.wav", "engineer_05.wav"]:
    y, sr = sf.read(os.path.join(BASE, n), dtype="float32")
    parts += [y, np.zeros(int(0.3 * sr), dtype=np.float32)]
y = np.concatenate(parts[:-1])
sf.write(REF_WAV, y, sr, subtype="PCM_16")
print("ref", round(len(y) / sr, 2), "s at", sr)
