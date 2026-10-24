import os, glob, json
import numpy as np, soundfile as sf, librosa
D = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1")
SRC = os.path.join(D, "v3_sidon")
OUT = os.path.join(D, "baseline")
EXCLUDE = {"01", "22"}  # Angelo: wonky "Hamilton ... 1.7" and cut-off "stay positive"
SR = 22050              # format the voice-cloning tool expects
os.makedirs(OUT, exist_ok=True)
for f in glob.glob(os.path.join(OUT, "*.wav")):
    os.remove(f)

pieces = []
for f in sorted(glob.glob(os.path.join(SRC, "*.wav"))):
    k = os.path.splitext(os.path.basename(f))[0]
    if k in EXCLUDE:
        continue
    y, _ = librosa.load(f, sr=SR, mono=True)
    iv = librosa.effects.split(y, top_db=35, frame_length=1024, hop_length=256)
    # merge speech regions separated by pauses shorter than 0.45 s
    merged = []
    for a, b in iv:
        if merged and (a - merged[-1][1]) < 0.45 * SR:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    for a, b in merged:
        seg = y[a:b]
        # keep each piece at 10 s or less (the tool ignores anything longer)
        while len(seg) > 0:
            part, seg = seg[:10 * SR], seg[10 * SR:]
            if len(part) >= 1.5 * SR:
                pieces.append((k, part))

# use the longest 25 pieces (tool limit), keep original order
pieces_sorted = sorted(range(len(pieces)), key=lambda i: -len(pieces[i][1]))[:25]
chosen = [pieces[i] for i in sorted(pieces_sorted)]
log = []
for n, (k, part) in enumerate(chosen, 1):
    f = int(0.01 * SR)
    part = part.copy(); part[:f] *= np.linspace(0, 1, f); part[-f:] *= np.linspace(1, 0, f)
    part = part / (np.max(np.abs(part)) + 1e-9) * 0.95
    name = f"engineer_{n:02d}.wav"
    sf.write(os.path.join(OUT, name), part.astype(np.float32), SR, subtype="FLOAT")
    log.append((name, k, round(len(part) / SR, 2)))
tot = sum(x[2] for x in log)
print(f"{len(log)} baseline clips, {tot:.1f}s total, from {len(set(x[1] for x in log))} source lines")
for x in log:
    print(x)
json.dump(log, open(os.path.join(OUT, "_sources.json"), "w"), indent=1)
