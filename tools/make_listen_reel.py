# Joins rendered clips into long listening files with a timestamped index.
# usage: python make_listen_reel.py <outdir> [prefix_filter]
import json, os, re, sys
import numpy as np, soundfile as sf
V = os.path.join(os.path.dirname(__file__), "..", "Engineer1", "vocab")
out_dir = sys.argv[1]; only = sys.argv[2] if len(sys.argv) > 2 else None
os.makedirs(out_dir, exist_ok=True)
jobs = json.load(open(os.path.join(V, "jobs.json"), encoding="utf-8"))
SR = None

def load(p):
    global SR
    a, sr = sf.read(p, dtype="float32")
    if a.ndim > 1: a = a.mean(1)
    if SR is None: SR = sr
    if sr != SR:
        import librosa; a = librosa.resample(a, orig_sr=sr, target_sr=SR)
    return a

def reel(items, name, title):
    parts, idx, t = [], [title, ""], 0.0
    for label, files in items:
        segs = [load(f) for f in files if os.path.exists(f)]
        if not segs: continue
        gap = np.zeros(int(0.15 * SR), np.float32)
        clip = segs[0]
        for s in segs[1:]: clip = np.concatenate([clip, gap, s])
        m = int(t // 60); s_ = t - 60 * m
        idx.append(f"{m:02d}:{s_:04.1f}  {label}")
        parts += [clip, np.zeros(int(0.9 * SR), np.float32)]
        t += (len(clip) + int(0.9 * SR)) / SR
    if not parts: return 0
    sf.write(os.path.join(out_dir, name + ".wav"), np.concatenate(parts), SR)
    open(os.path.join(out_dir, name + " - index.txt"), "w", encoding="utf-8").write("\n".join(idx))
    return len(idx) - 2

lines, blocks = {}, []
for j in jobs:
    i = j["id"]
    if only and not i.startswith(only): continue
    if not only and i.startswith("lines/b2_"): continue
    f = os.path.join(V, i.replace("/", os.sep) + ".wav")
    if i.startswith("lines/"):
        m = re.match(r"lines/([^/]+)/v(\d+)_(\d+)", i)
        key = (m.group(1), int(m.group(2)))
        lines.setdefault(key, []).append((int(m.group(3)), f, j["text"]))
    else:
        blocks.append((i.split("/", 1)[1] + "  -  " + j["text"], [f]))

items = []
for (sid, v), ps in lines.items():
    ps.sort()
    items.append((f"{sid} (version {v}):  " + " ... ".join(p[2].strip() for p in ps), [p[1] for p in ps]))
tag = " - Batch 2" if only else ""
print("lines:", reel(items, "All script lines" + tag, "Script lines (pieces with a fill-in are played back to back; the gap is where the number/name goes)"))
if not only:
    print("blocks:", reel(blocks, "All fill-ins (numbers, gaps, corners)", "Fill-in pieces"))
