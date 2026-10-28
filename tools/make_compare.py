import os, json
import numpy as np, soundfile as sf, librosa
D = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1")
OUT = os.path.join(os.environ["USERPROFILE"], "Desktop", "Engineer Voice - Compare")
os.makedirs(OUT, exist_ok=True)
SR = 48000
PICK = ["01", "15", "22", "27", "33"]  # same five lines in every version
lines = json.load(open(os.path.join(D, "engineer_lines.json"), encoding="utf-8"))
gap = np.zeros(int(0.7 * SR), dtype=np.float32)

def load(p, sr=None, off=None, dur=None):
    y, s = librosa.load(p, sr=SR, mono=True, offset=off or 0.0, duration=dur)
    return (y / (np.max(np.abs(y)) + 1e-9) * 0.89).astype(np.float32)

def build(name, parts):
    y = np.concatenate([np.concatenate([p, gap]) for p in parts])
    sf.write(os.path.join(OUT, name), y, SR, subtype="PCM_16")
    print("wrote", name, round(len(y) / SR, 1), "s")

src = os.path.join(D, "TVoice chop.mp3")
orig = []
for k in PICK:
    ln = lines[int(k) - 1]
    orig.append(load(src, off=max(0, ln["start"] - 0.12), dur=ln["end"] - ln["start"] + 0.27))
build("0 - Original radio (before).wav", orig)
for fname, folder in [("1 - Light clean.wav", "v1_light"),
                      ("2 - Resemble Enhance.wav", "v2_resemble_enhance"),
                      ("3 - Sidon restoration.wav", "v3_sidon")]:
    build(fname, [load(os.path.join(D, folder, k + ".wav")) for k in PICK])
txt = "These are the same 5 engineer lines in each file:\n" + "\n".join(
    f"  {i+1}. {lines[int(k)-1]['text']}" for i, k in enumerate(PICK))
txt += "\n\nAll 33 clips of each version are in Documents\\CrewChiefVoices\\Engineer1\\v1_light, v2_resemble_enhance, v3_sidon\n"
open(os.path.join(OUT, "READ ME.txt"), "w", encoding="utf-8").write(txt)
print(txt)
