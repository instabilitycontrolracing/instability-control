import os, sys, time, traceback
sys.path.insert(0, os.path.dirname(__file__))
from test_lines import LINES, REF_WAV, F5_REF_WAV, F5_REF_TEXT, BASELINE, OUTROOT
import numpy as np, soundfile as sf
engine = sys.argv[1]
out = os.path.join(OUTROOT, engine); os.makedirs(out, exist_ok=True)
t0 = time.time()

def save(i, wav, sr):
    wav = np.asarray(wav, dtype=np.float32).squeeze()
    wav = wav / (np.max(np.abs(wav)) + 1e-9) * 0.89
    sf.write(os.path.join(out, f"{i:02d}.wav"), wav, sr, subtype="PCM_16")
    print(engine, i, "ok", flush=True)

if engine == "xtts":
    os.environ["COQUI_TOS_AGREED"] = "1"  # the developer agreed to the non-commercial CPML license
    from TTS.api import TTS
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")
    for i, (t, lang) in enumerate(LINES, 1):
        try:
            save(i, tts.tts(text=t, speaker_wav=BASELINE, language=lang), 24000)
        except Exception:
            traceback.print_exc()

elif engine == "chatterbox":
    from chatterbox.tts import ChatterboxTTS
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    en = ChatterboxTTS.from_pretrained(device="cuda")
    mtl = None
    for i, (t, lang) in enumerate(LINES, 1):
        try:
            if lang == "en":
                wav = en.generate(t, audio_prompt_path=REF_WAV, exaggeration=0.5, cfg_weight=0.5); sr = en.sr
            else:
                if mtl is None:
                    mtl = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
                wav = mtl.generate(t, language_id=lang, audio_prompt_path=REF_WAV, exaggeration=0.7, cfg_weight=0.4); sr = mtl.sr
            save(i, wav.cpu().numpy(), sr)
        except Exception:
            traceback.print_exc()

elif engine == "f5":
    from f5_tts.api import F5TTS
    f5 = F5TTS(device="cuda")
    for i, (t, lang) in enumerate(LINES, 1):
        try:
            wav, sr, _ = f5.infer(ref_file=F5_REF_WAV, ref_text=F5_REF_TEXT, gen_text=t, seed=1234)
            save(i, wav, sr)
        except Exception:
            traceback.print_exc()

print("ALL DONE", engine, round(time.time() - t0, 1), "s", flush=True)
