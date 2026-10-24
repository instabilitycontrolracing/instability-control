import os, sys, glob, traceback
import pathlib
pathlib.PosixPath = pathlib.WindowsPath  # model file was saved on Linux
import numpy as np, soundfile as sf, torch
D = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1")
SRC = os.path.join(D, "v1_light")
clips = sorted(glob.glob(os.path.join(SRC, "*.wav")))
which = sys.argv[1] if len(sys.argv) > 1 else "all"

def norm_write(path, x, sr):
    x = np.asarray(x, dtype=np.float32).squeeze()
    if x.ndim > 1: x = x.mean(axis=0 if x.shape[0] < x.shape[-1] else 1)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.89
    sf.write(path, x, sr, subtype="PCM_16")

if which in ("all", "re"):
    from resemble_enhance.enhancer.inference import enhance
    out = os.path.join(D, "v2_resemble_enhance"); os.makedirs(out, exist_ok=True)
    for c in clips:
        dst = os.path.join(out, os.path.basename(c))
        if os.path.exists(dst): continue
        try:
            x, sr = sf.read(c, dtype="float32")
            y, nsr = enhance(torch.from_numpy(x), sr, "cuda", nfe=64, solver="midpoint", lambd=0.9, tau=0.5)
            norm_write(dst, y.cpu().numpy(), nsr)
            print("RE", os.path.basename(c), nsr, flush=True)
        except Exception:
            traceback.print_exc(); print("RE FAIL", c, flush=True)

if which in ("all", "sidon"):
    from audiosronnx import load_sr
    m = load_sr("sidon", providers=["CPUExecutionProvider"])
    out = os.path.join(D, "v3_sidon"); os.makedirs(out, exist_ok=True)
    for c in clips:
        dst = os.path.join(out, os.path.basename(c))
        if os.path.exists(dst): continue
        try:
            x, sr = sf.read(c, dtype="float32")
            y, nsr = m.upscale(x, sample_rate=sr)
            norm_write(dst, y, nsr)
            print("SIDON", os.path.basename(c), nsr, flush=True)
        except Exception:
            traceback.print_exc(); print("SIDON FAIL", c, flush=True)
print("ALL DONE", flush=True)
