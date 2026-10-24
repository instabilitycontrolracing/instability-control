import os, sys, glob
sys.path.insert(0, os.path.dirname(__file__))
from test_lines import LINES, OUTROOT
import numpy as np, soundfile as sf, librosa
DEST = os.path.join(os.environ["USERPROFILE"], "Desktop", "Engineer Voice - Engine Test")
os.makedirs(DEST, exist_ok=True)
SR = 48000
gap = np.zeros(int(0.8 * SR), dtype=np.float32)
names = {"xtts": "A - XTTS (CrewChief tool default).wav",
         "chatterbox": "B - Chatterbox.wav",
         "f5": "C - F5-TTS.wav",
         "higgs2": "D - Higgs v2 (his voice).wav"}
for eng, fname in names.items():
    files = sorted(glob.glob(os.path.join(OUTROOT, eng, "*.wav")))
    if not files:
        print("skip", eng); continue
    parts = []
    for f in files:
        y, _ = librosa.load(f, sr=SR, mono=True)
        parts += [y / (np.max(np.abs(y)) + 1e-9) * 0.89, gap]
    sf.write(os.path.join(DEST, fname), np.concatenate(parts).astype(np.float32), SR, subtype="PCM_16")
    print("wrote", fname, len(files), "lines")
open(os.path.join(DEST, "READ ME.txt"), "w", encoding="utf-8").write(
    "Each file has the same lines, in this order:\n" + "\n".join(f"  {i}. {t}" for i, (t, _) in enumerate(LINES, 1)))
