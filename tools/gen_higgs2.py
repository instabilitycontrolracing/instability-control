import os, sys, time, traceback
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, soundfile as sf, torch
from test_lines import LINES, OUTROOT, D
from transformers import BitsAndBytesConfig
import boson_multimodal.serve.serve_engine as se
from boson_multimodal.data_types import ChatMLSample, Message, AudioContent

# --- fit the 5.8B model on one 12 GB card: load it in 8-bit ---
_Orig = se.HiggsAudioModel
class _Q8:
    @staticmethod
    def from_pretrained(path, torch_dtype=None, **kw):
        m = _Orig.from_pretrained(path, torch_dtype=torch.bfloat16, device_map={"": 0},
                                  quantization_config=BitsAndBytesConfig(load_in_8bit=True))
        m.to = lambda *a, **k: m  # already placed on the GPU
        return m
se.HiggsAudioModel = _Q8

out = os.path.join(OUTROOT, "higgs2"); os.makedirs(out, exist_ok=True)
# reference: two clean Sidon lines joined, with their exact words
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
eng = se.HiggsAudioServeEngine("bosonai/higgs-audio-v2-generation-3B-base",
                               "bosonai/higgs-audio-v2-tokenizer", device="cuda:0",
                               torch_dtype=torch.bfloat16)
print("loaded in", round(time.time() - t0), "s;", round(torch.cuda.memory_allocated(0) / 1e9, 1), "GB on GPU", flush=True)
system = ("Generate audio following instruction.\n\n<|scene_desc_start|>\n"
          "A calm race engineer talking to his driver over team radio from the pit wall.\n<|scene_desc_end|>")
for i, (t, lang) in enumerate(LINES, 1):
    try:
        msgs = [Message(role="system", content=system),
                Message(role="user", content=REF_TEXT),
                Message(role="assistant", content=AudioContent(audio_url=REF)),
                Message(role="user", content=t)]
        r = eng.generate(chat_ml_sample=ChatMLSample(messages=msgs), max_new_tokens=1024,
                         temperature=0.3, top_p=0.95, top_k=50,
                         stop_strings=["<|end_of_text|>", "<|eot_id|>"], seed=1234)
        y = np.asarray(r.audio, np.float32); y = y / (np.max(np.abs(y)) + 1e-9) * 0.89
        sf.write(os.path.join(out, f"{i:02d}.wav"), y, r.sampling_rate, subtype="PCM_16")
        print("higgs2", i, "ok", flush=True)
    except Exception:
        traceback.print_exc()
print("ALL DONE higgs2", round(time.time() - t0, 1), "s", flush=True)
