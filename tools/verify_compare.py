import os, site, glob, warnings
warnings.filterwarnings("ignore")
for _d in ["cublas", "cudnn"]:
    _p = os.path.join(site.getsitepackages()[-1], "nvidia", _d, "bin")
    if os.path.isdir(_p):
        os.add_dll_directory(_p); os.environ["PATH"] = _p + os.pathsep + os.environ["PATH"]
from faster_whisper import WhisperModel
m = WhisperModel("large-v3", device="cuda", device_index=1, compute_type="float16")
for f in sorted(glob.glob(os.path.join(os.environ["USERPROFILE"], "Desktop", "Engineer Voice - Compare", "*.wav"))):
    segs, _ = m.transcribe(f, language="en", beam_size=5)
    segs = list(segs)
    text = " ".join(s.text.strip() for s in segs)
    conf = sum(s.avg_logprob for s in segs) / max(1, len(segs))
    print(f"== {os.path.basename(f)}  (clarity score {conf:.2f}, closer to 0 is clearer)\n   {text}\n", flush=True)
