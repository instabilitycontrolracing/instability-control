"""Render the strategist's voice library (Gertrude, CC BY 3.0 tender_buttons) with one engine.
usage: python render_strategist.py chatterbox|f5 [--only keys.txt] [--seed N]
writes  CrewChiefVoices/Strategist/<engine>/raw/{units,fills}/...wav  + raw/index.json"""
import os, sys, json, time, traceback
import numpy as np, soundfile as sf
ROOT = os.path.join(os.path.expanduser("~"), "Documents", "CrewChiefVoices")
sys.path.insert(0, ROOT)
from engineer.strat_lines import units, fill_values, EXAMPLE, CARRIER
HERE = os.path.dirname(os.path.abspath(__file__))
REF5, REF_FULL = os.path.join(HERE, "gertrude_ref5.wav"), os.path.join(HERE, "gertrude_full.wav")
REF_TEXT = "Why is that education? That is education because the two tables which are folding"
engine = sys.argv[1]
only = None
if "--only" in sys.argv:
    only = set(open(sys.argv[sys.argv.index("--only") + 1], encoding="utf-8").read().split("\n")) - {""}
seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 1234
OUT = os.path.join(ROOT, "Strategist", engine, "raw")
os.makedirs(os.path.join(OUT, "units"), exist_ok=True)

jobs = []                                   # (name, text, path)
for key, sent in units():
    t = sent
    for f, ex in EXAMPLE.items():
        t = t.replace(f"[{f}]", ex)
    jobs.append((key, t, os.path.join(OUT, "units", key.replace("~", "__") + ".wav")))
for kind, vals in fill_values().items():
    os.makedirs(os.path.join(OUT, "fills", kind), exist_ok=True)
    for v in vals:
        jobs.append((f"{kind}:{v}", CARRIER[kind].format(v), os.path.join(OUT, "fills", kind, v + ".wav")))
idx_path = os.path.join(OUT, "index.json")
index = json.load(open(idx_path, encoding="utf-8")) if os.path.exists(idx_path) else {}
if only is not None:
    jobs = [j for j in jobs if j[0] in only]
elif "--all" not in sys.argv:                 # default: only clips that are new or whose words changed
    jobs = [j for j in jobs if index.get(j[0], {}).get("text") != j[1] or not os.path.exists(j[2])]
print(engine, len(jobs), "clips", flush=True)

import torch
if engine == "chatterbox":
    from chatterbox.tts import ChatterboxTTS
    m = ChatterboxTTS.from_pretrained(device="cuda")
    cond = None
    def gen(t):
        torch.manual_seed(seed)
        w = m.generate(t, audio_prompt_path=REF_FULL, exaggeration=0.45, cfg_weight=0.5)
        return w.cpu().numpy().squeeze(), m.sr
else:
    from f5_tts.api import F5TTS
    m = F5TTS(device="cuda")
    def gen(t):
        w, sr, _ = m.infer(ref_file=REF5, ref_text=REF_TEXT, gen_text=t, seed=seed, speed=0.82, show_info=lambda *a: None)
        return np.asarray(w).squeeze(), sr

t0 = time.time()
for i, (name, text, path) in enumerate(jobs, 1):
    try:
        w, sr = gen(text)
        w = (w / (np.max(np.abs(w)) + 1e-9) * 0.89).astype(np.float32)
        sf.write(path, w, sr, subtype="PCM_16")
        index[name] = {"text": text, "file": os.path.relpath(path, OUT), "seed": seed}
    except Exception:
        traceback.print_exc()
    if i % 20 == 0 or i == len(jobs):
        json.dump(index, open(idx_path, "w", encoding="utf-8"), indent=0)
        print(f"{engine} {i}/{len(jobs)}  {time.time() - t0:.0f}s", flush=True)
print("ALL DONE", engine, round(time.time() - t0), "s", flush=True)
