import os, sys, time, json, traceback
import numpy as np, soundfile as sf, torch
from transformers import AutoProcessor, HiggsAudioV2ForConditionalGeneration
ROOT = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1")
V = os.path.join(ROOT, "vocab")
ROUND = int(sys.argv[1]) if len(sys.argv) > 1 else 0
jobs = json.load(open(os.path.join(V, "jobs.json"), encoding="utf-8"))
todo = [j for j in jobs if not os.path.exists(os.path.join(V, j["id"] + ".wav"))]
REF = os.path.join(ROOT, "ref_higgs.wav")
REF_TEXT = ("Hamilton behind with DRS. No moving under braking, turn four. No moving under braking for turn four. "
            "And Bottas behind, did a mistake. He's at 1.5 at the moment. Three laps to go. And Bottas with DRS.")
mid = "bosonai/higgs-audio-v2-generation-3B-base"
proc = AutoProcessor.from_pretrained(mid, device_map="auto")
model = HiggsAudioV2ForConditionalGeneration.from_pretrained(mid, device_map="auto", torch_dtype=torch.bfloat16)
log = open(os.path.join(V, "render_log.txt"), "a", encoding="utf-8")
t0 = time.time()
print(f"round {ROUND}: {len(todo)} clips to render", file=log, flush=True)
for n, j in enumerate(todo, 1):
    dst = os.path.join(V, j["id"] + ".wav"); os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        conv = [
            {"role": "system", "content": [{"type": "text", "text": "Generate audio following instruction."}]},
            {"role": "scene", "content": [{"type": "text", "text": "A calm race engineer talking to his driver over team radio from the pit wall."}]},
            {"role": "user", "content": [{"type": "text", "text": REF_TEXT}]},
            {"role": "assistant", "content": [{"type": "audio", "path": REF}]},
            {"role": "user", "content": [{"type": "text", "text": j["text"]}]},
        ]
        inputs = proc.apply_chat_template(conv, add_generation_prompt=True, tokenize=True, return_dict=True,
                                          sampling_rate=24000, return_tensors="pt").to(model.device)
        torch.manual_seed(1000 + 7 * ROUND + n)
        cap = int(len(j["text"]) * 3.5) + 60
        outs = model.generate(**inputs, max_new_tokens=cap, do_sample=True, temperature=0.4, top_p=0.95, top_k=50)
        tmp = dst + ".tmp.wav"
        proc.save_audio(proc.batch_decode(outs), tmp)
        y, sr = sf.read(tmp, dtype="float32"); os.remove(tmp)
        # trim leading/trailing silence, short fades, normalise
        a = np.abs(y); thr = max(0.02 * a.max(), 1e-4); idx = np.where(a > thr)[0]
        if len(idx):
            s0 = max(0, idx[0] - int(0.03 * sr)); s1 = min(len(y), idx[-1] + int(0.08 * sr)); y = y[s0:s1]
        f = min(int(0.01 * sr), len(y) // 4)
        if f > 0: y[:f] *= np.linspace(0, 1, f); y[-f:] *= np.linspace(1, 0, f)
        y = y / (np.max(np.abs(y)) + 1e-9) * 0.89
        sf.write(dst, y, sr, subtype="PCM_16")
        el = time.time() - t0
        print(f"{n}/{len(todo)} {j['id']} {len(y)/sr:.1f}s  eta {el/n*(len(todo)-n)/60:.0f} min", file=log, flush=True)
    except Exception:
        print("FAIL", j["id"], traceback.format_exc()[-400:], file=log, flush=True)
print(f"round {ROUND} done in {(time.time()-t0)/60:.1f} min", file=log, flush=True)
