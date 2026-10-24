import os, site, sys, glob, warnings, re, difflib
warnings.filterwarnings("ignore")
for _d in ["cublas", "cudnn"]:
    _p = os.path.join(site.getsitepackages()[-1], "nvidia", _d, "bin")
    if os.path.isdir(_p):
        os.add_dll_directory(_p); os.environ["PATH"] = _p + os.pathsep + os.environ["PATH"]
sys.path.insert(0, os.path.dirname(__file__))
from test_lines import LINES, OUTROOT
from faster_whisper import WhisperModel
m = WhisperModel("large-v3", device="cuda", device_index=1, compute_type="float16")
norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " ")).split()
for eng in (sys.argv[1:] or ["xtts", "chatterbox", "f5"]):
    scores, bad = [], []
    for i, (t, lang) in enumerate(LINES, 1):
        f = os.path.join(OUTROOT, eng, f"{i:02d}.wav")
        if not os.path.exists(f):
            bad.append((i, "MISSING")); continue
        segs, _ = m.transcribe(f, language=lang, beam_size=5)
        heard = " ".join(s.text.strip() for s in segs)
        r = difflib.SequenceMatcher(None, norm(t), norm(heard)).ratio()
        scores.append(r)
        if r < 0.8:
            bad.append((i, heard))
    print(f"== {eng}: words match {100*sum(scores)/max(1,len(scores)):.0f}% on average")
    for i, h in bad:
        print(f"   line {i} off -> heard: {h}")
