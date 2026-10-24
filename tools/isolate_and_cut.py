import os, json, glob
import numpy as np, soundfile as sf
D = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1")
SRC = os.path.join(D, "TVoice chop.mp3")
STEM_DIR = os.path.join(D, "stems")
os.makedirs(STEM_DIR, exist_ok=True)

stem = glob.glob(os.path.join(STEM_DIR, "*Vocals*.wav"))
if not stem:
    from audio_separator.separator import Separator
    sep = Separator(output_dir=STEM_DIR, output_format="WAV", output_single_stem="Vocals",
                    model_file_dir=os.path.join(os.environ["USERPROFILE"], ".cache", "audio-separator"))
    try:
        sep.load_model(model_filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt")
    except Exception as e:
        print("Fallback to default model:", e)
        sep.load_model()
    sep.separate(SRC)
    stem = glob.glob(os.path.join(STEM_DIR, "*Vocals*.wav"))
stem = stem[0]
print("Vocal stem:", stem)

audio, sr = sf.read(stem, always_2d=True)
audio = audio.mean(axis=1)
lines = json.load(open(os.path.join(D, "engineer_lines.json"), encoding="utf-8"))
out = os.path.join(D, "v1_light")
os.makedirs(out, exist_ok=True)
for n, ln in enumerate(lines, 1):
    a = max(0, int((ln["start"] - 0.12) * sr)); b = min(len(audio), int((ln["end"] + 0.15) * sr))
    x = audio[a:b].copy()
    f = int(0.02 * sr)  # 20 ms fades to avoid clicks
    if len(x) > 2 * f:
        x[:f] *= np.linspace(0, 1, f); x[-f:] *= np.linspace(1, 0, f)
    pk = np.max(np.abs(x)) + 1e-9
    x = x / pk * 0.89  # about -1 dBFS
    sf.write(os.path.join(out, f"{n:02d}.wav"), x.astype(np.float32), sr, subtype="PCM_16")
print(f"Wrote {len(lines)} clips to {out} at {sr} Hz")
