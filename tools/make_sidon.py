import os, glob, traceback
import numpy as np, soundfile as sf
from audiosronnx import load_sr
D = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1")
clips = sorted(glob.glob(os.path.join(D, "v1_light", "*.wav")))
out = os.path.join(D, "v3_sidon"); os.makedirs(out, exist_ok=True)
m = load_sr("sidon", providers=["CPUExecutionProvider"], chunk_samples=16000 * 20)
for c in clips:
    dst = os.path.join(out, os.path.basename(c))
    if os.path.exists(dst): continue
    try:
        x, sr = sf.read(c, dtype="float32")
        y, nsr = m.upscale(x, sample_rate=sr)
        y = np.asarray(y, dtype=np.float32).squeeze()
        y = y / (np.max(np.abs(y)) + 1e-9) * 0.89
        sf.write(dst, y, nsr, subtype="PCM_16")
        print("SIDON", os.path.basename(c), nsr, flush=True)
    except Exception:
        traceback.print_exc(); print("SIDON FAIL", c, flush=True)
print("ALL DONE", flush=True)
