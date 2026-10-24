import sys, os, json, shutil, warnings
warnings.filterwarnings("ignore")
import numpy as np
import site
for _d in ['cublas','cudnn']:
    _p=os.path.join(site.getsitepackages()[-1],'nvidia',_d,'bin')
    if os.path.isdir(_p):
        os.add_dll_directory(_p); os.environ['PATH']=_p+os.pathsep+os.environ['PATH']
import torch
from faster_whisper import WhisperModel, decode_audio

SRC = sys.argv[1]
OUT_DIR = sys.argv[2]
GPU = int(sys.argv[3]) if len(sys.argv) > 3 else 1
os.makedirs(OUT_DIR, exist_ok=True)
base = os.path.splitext(os.path.basename(SRC))[0]
work_copy = os.path.join(OUT_DIR, os.path.basename(SRC))
if not os.path.exists(work_copy):
    shutil.copy2(SRC, work_copy)

SR = 16000
audio = decode_audio(work_copy, sampling_rate=SR)
dur = len(audio) / SR
print(f"Audio length: {dur:.1f}s")

model = WhisperModel("large-v3", device="cuda", device_index=GPU, compute_type="float16")
segs, info = model.transcribe(audio, language="en", word_timestamps=True, vad_filter=True,
                              vad_parameters=dict(min_silence_duration_ms=300))
segs = list(segs)
print(f"Transcribed {len(segs)} segments")

# Build chunks from words: break at segment ends and at pauses > 0.5s
chunks = []
for s in segs:
    words = s.words or []
    cur = []
    for w in words:
        if cur and w.start - cur[-1].end > 0.5:
            chunks.append(cur); cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
items = []
for c in chunks:
    items.append(dict(start=round(c[0].start, 2), end=round(c[-1].end, 2),
                      text="".join(w.word for w in c).strip()))

# Speaker embeddings (ECAPA)
try:
    from speechbrain.inference.speaker import EncoderClassifier
except ImportError:
    from speechbrain.pretrained import EncoderClassifier
kw = dict(source="speechbrain/spkrec-ecapa-voxceleb",
          savedir=os.path.join(os.environ["USERPROFILE"], ".cache", "sb_ecapa"),
          run_opts={"device": "cpu"})
try:
    from speechbrain.utils.fetching import LocalStrategy
    kw["local_strategy"] = LocalStrategy.COPY
except Exception:
    pass
enc = EncoderClassifier.from_hparams(**kw)

def embed(a, b):
    a0 = max(0, int((a - 0.1) * SR)); b0 = min(len(audio), int((b + 0.1) * SR))
    x = torch.from_numpy(audio[a0:b0]).float().unsqueeze(0)
    with torch.no_grad():
        e = enc.encode_batch(x).squeeze().cpu().numpy()
    return e / (np.linalg.norm(e) + 1e-9)

for it in items:
    it["dur"] = it["end"] - it["start"]
    it["emb"] = embed(it["start"], it["end"]) if it["dur"] >= 0.3 else None

# Cluster: reliable chunks (>=1.2s) first, average-linkage merge on cosine similarity
THRESH = float(os.environ.get("SPK_THRESH", "0.40"))
rel = [i for i, it in enumerate(items) if it["emb"] is not None and it["dur"] >= 1.2]
if not rel:
    rel = [i for i, it in enumerate(items) if it["emb"] is not None]
clusters = [[i] for i in rel]
def csim(A, B):
    return float(np.mean([[items[a]["emb"] @ items[b]["emb"] for b in B] for a in A]))
while len(clusters) > 1:
    best, pair = -1, None
    for x in range(len(clusters)):
        for y in range(x + 1, len(clusters)):
            s = csim(clusters[x], clusters[y])
            if s > best: best, pair = s, (x, y)
    if best < THRESH: break
    x, y = pair
    clusters[x] += clusters[y]; del clusters[y]
# Order speakers by total talk time (A = most talking)
clusters.sort(key=lambda c: -sum(items[i]["dur"] for i in c))
cents = []
for k, c in enumerate(clusters):
    m = np.mean([items[i]["emb"] for i in c], axis=0); cents.append(m / np.linalg.norm(m))
    for i in c: items[i]["spk"] = chr(65 + k)
for i, it in enumerate(items):
    if "spk" in it: continue
    if it["emb"] is not None:
        sims = [it["emb"] @ c for c in cents]
        it["spk"] = chr(65 + int(np.argmax(sims))) + "?"
    else:
        it["spk"] = "?"

def ts(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"
lines = []
for it in items:
    lines.append(f"[{ts(it['start'])} - {ts(it['end'])}]  Speaker {it['spk']:<3} {it['text']}")
summary = ["", "Talk time per speaker:"]
for k, c in enumerate(clusters):
    summary.append(f"  Speaker {chr(65+k)}: {sum(items[i]['dur'] for i in c):.1f}s across {len(c)} lines")
txt = "\n".join(lines + summary)
open(os.path.join(OUT_DIR, base + "_transcript.txt"), "w", encoding="utf-8").write(txt)
json.dump([{k: v for k, v in it.items() if k != "emb"} for it in items],
          open(os.path.join(OUT_DIR, base + "_transcript.json"), "w", encoding="utf-8"), indent=1)
print(txt)
