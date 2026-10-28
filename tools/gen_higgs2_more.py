import os, sys, time, traceback, re, difflib, site
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, soundfile as sf, torch
from test_lines import OUTROOT, D
from test_lines2 import LINES2
from transformers import AutoProcessor, HiggsAudioV2ForConditionalGeneration

out = os.path.join(OUTROOT, "higgs2_more"); os.makedirs(out, exist_ok=True)
REF = os.path.join(D, "ref_higgs.wav")
REF_TEXT = ("Hamilton behind with DRS. No moving under braking, turn four. No moving under braking for turn four. "
            "And Bottas behind, did a mistake. He's at 1.5 at the moment. Three laps to go. And Bottas with DRS.")
mid = "bosonai/higgs-audio-v2-generation-3B-base"
proc = AutoProcessor.from_pretrained(mid, device_map="auto")
model = HiggsAudioV2ForConditionalGeneration.from_pretrained(mid, device_map="auto", torch_dtype=torch.bfloat16)
t0 = time.time()
for i, t in enumerate(LINES2, 1):
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
        cap = int(len(t) * 3.5) + 60
        best = None
        for take in range(3):
            torch.manual_seed(1000 + take)
            outs = model.generate(**inputs, max_new_tokens=cap, do_sample=True, temperature=0.4, top_p=0.95, top_k=50)
            tmp = dst + f".take{take}.wav"
            proc.save_audio(proc.batch_decode(outs), tmp)
            yy, sr = sf.read(tmp, dtype="float32"); os.remove(tmp)
            score = abs(len(yy) / sr - len(t) * 0.075)
            if best is None or score < best[0]: best = (score, yy)
        y = best[1] / (np.max(np.abs(best[1])) + 1e-9) * 0.89
        sf.write(dst, y, sr, subtype="PCM_16")
        print("more", i, "ok", round(len(y) / sr, 1), "s", flush=True)
    except Exception:
        traceback.print_exc()
print("ALL DONE more", round(time.time() - t0, 1), "s", flush=True)
