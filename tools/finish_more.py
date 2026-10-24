import os, site, sys, glob, warnings, re, difflib
warnings.filterwarnings("ignore")
for _d in ["cublas", "cudnn"]:
    _p = os.path.join(site.getsitepackages()[-1], "nvidia", _d, "bin")
    if os.path.isdir(_p):
        os.add_dll_directory(_p); os.environ["PATH"] = _p + os.pathsep + os.environ["PATH"]
sys.path.insert(0, os.path.dirname(__file__))
from test_lines import OUTROOT
from test_lines2 import LINES2
import numpy as np, soundfile as sf
from faster_whisper import WhisperModel
src = os.path.join(OUTROOT, "higgs2_more")
m = WhisperModel("large-v3", device="cuda", device_index=1, compute_type="float16")
norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " ")).split()
scores, parts, sr0 = [], [], None
for i, t in enumerate(LINES2, 1):
    f = os.path.join(src, f"{i:02d}.wav")
    if not os.path.exists(f): print("missing", i); continue
    segs, _ = m.transcribe(f, language="en", beam_size=5)
    heard = " ".join(s.text.strip() for s in segs)
    r = difflib.SequenceMatcher(None, norm(t), norm(heard)).ratio(); scores.append(r)
    if r < 0.8: print(f"   line {i} off -> heard: {heard}")
    y, sr0 = sf.read(f, dtype="float32"); parts += [y, np.zeros(int(0.8 * sr0), np.float32)]
print(f"words match {100*sum(scores)/max(1,len(scores)):.0f}% on average over {len(scores)} lines")
dest = os.path.join(os.environ["USERPROFILE"], "Desktop", "Engineer Voice - Engine Test")
sf.write(os.path.join(dest, "E - Higgs v2 (his voice) - 18 more lines.wav"), np.concatenate(parts), sr0, subtype="PCM_16")
open(os.path.join(dest, "READ ME - 18 more lines.txt"), "w", encoding="utf-8").write(
    "In order:\n" + "\n".join(f"  {i}. {t}" for i, t in enumerate(LINES2, 1)))
print("wrote combined file")
