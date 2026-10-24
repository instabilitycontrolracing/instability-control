import os, sys, time, traceback, glob
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, soundfile as sf, torch
from test_lines import LINES, OUTROOT, D
from transformers import AutoProcessor, HiggsAudioV2ForConditionalGeneration

out = os.path.join(OUTROOT, "higgs2"); os.makedirs(out, exist_ok=True)
refs = [(os.path.join(D, "v3_sidon", "27.wav"),
         "Hamilton behind with DRS. No moving under braking, turn four. No moving under braking for turn four."),
        (os.path.join(D, "v3_sidon", "33.wav"),
         "And Bottas behind, did a mistake. He's at 1.5 at the moment. Three laps to go. And Bottas with DRS.")]
parts, sr0 = [], None
for p, _ in refs:
    y, sr0 = sf.read(p, dtype="float32"); parts += [y, np.zeros(int(0.35 * sr0), np.float32)]
REF = os.path.join(D, "ref_higgs.wav"); sf.write(REF, np.concatenate(parts[:-1]), sr0)
REF_TEXT = " ".join(t for _, t in refs)

t0 = time.time()
mid = "bosonai/higgs-audio-v2-generation-3B-base"
proc = AutoProcessor.from_pretrained(mid, device_map="auto")
model = HiggsAudioV2ForConditionalGeneration.from_pretrained(mid, device_map="auto", torch_dtype=torch.bfloat16)
print("loaded in", round(time.time() - t0), "s", [round(torch.cuda.memory_allocated(i) / 1e9, 1) for i in range(torch.cuda.device_count())], "GB", flush=True)

ONLY = [int(a) for a in sys.argv[1:]]
for i, (t, lang) in enumerate(LINES, 1):
    if ONLY and i not in ONLY: continue
    dst = os.path.join(out, f"{i:02d}.wav")
    try:
        conv = [
            {"role": "system", "content": [{"type": "text", "text": "Generate audio following instruction."}]},
            {"role": "scene", "content": [{"type": "text", "text": "A calm race engineer talking to his driver over team radio from the pit wall."}]},
            {"role": "user", "content": [{"type": "text", "text": REF_TEXT}]},
            {"role": "assistant", "content": [{"type": "audio", "path": REF}]},
            {"role": "user", "content": [{"type": "text", "text": t}]},
        ]
        inputs = proc.apply_chat_template(conv, add_generation_prompt=True, tokenize=True, return_dict=True,
                                          sampling_rate=24000, return_tensors="pt").to(model.device)
        cap = int(len(t) * 3.5) + 60  # ~25 audio frames/s; stops runaway repeats
        best = None
        for take in range(3 if ONLY else 1):
            if ONLY:
                torch.manual_seed(1000 + take)
                outs = model.generate(**inputs, max_new_tokens=cap, do_sample=True, temperature=0.4, top_p=0.95, top_k=50)
            else:
                outs = model.generate(**inputs, max_new_tokens=1000, do_sample=False)
            tmp = dst + f".take{take}.wav"
            proc.save_audio(proc.batch_decode(outs), tmp)
            yy, sr = sf.read(tmp, dtype="float32"); os.remove(tmp)
            want = len(t) * 0.075
            score = abs(len(yy) / sr - want)
            if best is None or score < best[0]: best = (score, yy)
        y = best[1]; y = y / (np.max(np.abs(y)) + 1e-9) * 0.89
        sf.write(dst, y, sr, subtype="PCM_16")
        print("higgs2", i, "ok", round(len(y) / sr, 1), "s", flush=True)
    except Exception:
        traceback.print_exc()
print("ALL DONE higgs2", round(time.time() - t0, 1), "s", flush=True)
