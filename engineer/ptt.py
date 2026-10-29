"""Push-to-talk: hold the radio button, speak, release. Speech recognition runs on the CPU
(Parakeet TDT 0.6B via sherpa-onnx), so it never takes graphics memory from the game."""
import glob, os, threading, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASR_DIR = os.path.join(ROOT, "asr")
SR = 16000


class Listener:
    def __init__(self, log=print, device=None):
        self.log = log
        self.device = device or None
        self.rec = None
        self.ready = False
        self._buf, self._stream, self._lock = [], None, threading.Lock()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            import sherpa_onnx
            mdir = next(iter(glob.glob(os.path.join(ASR_DIR, "*parakeet*"))), None)
            if not mdir:
                self.log("[voice] speech recognition model not installed yet."); return
            f = lambda pat: next(iter(sorted(glob.glob(os.path.join(mdir, pat)))), None)
            self.rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=f("encoder*.onnx"), decoder=f("decoder*.onnx"), joiner=f("joiner*.onnx"),
                tokens=f("tokens.txt"), model_type="nemo_transducer", num_threads=2, provider="cpu")
            self.ready = True
            self.log("[voice] radio voice recognition ready.")
        except Exception as e:
            self.log(f"[voice] speech recognition not available: {e!r}")

    def set_device(self, dev):
        self.device = dev or None

    # ---------------- recording ----------------
    def start(self):
        import sounddevice as sd
        with self._lock:
            if self._stream:
                return
            self._buf = []
            def cb(indata, frames, t, status):
                self._buf.append(indata[:, 0].copy())
            try:
                self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=self.device, callback=cb, blocksize=1024)
                self._stream.start()
            except Exception as e:
                self._stream = None
                self.log(f"[voice] microphone problem: {e!r}")

    def stop(self):
        """Stop recording and return the text (or '' if nothing heard)."""
        with self._lock:
            s, self._stream = self._stream, None
        if not s:
            return ""
        time.sleep(0.15)   # keep the tail of the last word
        try:
            s.stop(); s.close()
        except Exception:
            pass
        audio = np.concatenate(self._buf) if self._buf else np.zeros(1, np.float32)
        if len(audio) < SR * 0.3 or np.abs(audio).max() < 0.01:
            return ""
        self._to_ipad(audio)
        text = self.transcribe(audio)
        self._keep(audio, text)
        return text

    def _to_ipad(self, audio):
        """2026-10-25 (request: "can it also play what I say into the mic?"): the driver's side of the team radio goes to
        the iPad too - levelled and put through a light radio sound so it sits with the engineer's voice. Sent the moment
        the button is released, so on the iPad it always comes before the engineer's answer."""
        try:
            from . import voice as V
            if not V.TAPS:
                return
            OUT = 48000                    # the radio filter needs room above 8 kHz: run it at 48 kHz, never at the mic's 16 kHz
            x = audio.astype(np.float32).reshape(-1)
            x = x - float(x.mean())
            n_out = int(round(len(x) * OUT / SR))
            x = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x).astype(np.float32)
            x = x * min(8.0, 0.5 / max(1e-3, float(np.abs(x).max())))
            if getattr(self, "_fx", None) is None:
                self._fx = V.RadioFX(None, OUT, 1.4)
            y = np.clip(np.nan_to_num(self._fx(x)), -1.0, 1.0).astype(np.float32)
            if float(np.mean(np.abs(y) > 0.98)) > 0.05:      # the effect misbehaved: send the plain voice instead
                y = x
            for tap in list(V.TAPS):
                try:
                    tap(y, OUT, "you")
                except TypeError:
                    tap(y, OUT)
                except Exception:
                    pass
        except Exception as e:
            self.log(f"[voice] radio to iPad: {e!r}")

    def _keep(self, audio, text):
        """Keep the last 500 radio messages (audio + what was heard) on this PC, so the recogniser can be tested
        against the driver's real voice and mic (request 2026-10-24: "needs to be as accurate as we can get it")."""
        try:
            import json, soundfile as sf
            d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RaceEngineer", "radio_clips")
            os.makedirs(d, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            sf.write(os.path.join(d, stamp + ".wav"), audio.astype(np.float32), SR, subtype="PCM_16")
            with open(os.path.join(d, "heard.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"file": stamp + ".wav", "heard": text}) + "\n")
            wavs = sorted(glob.glob(os.path.join(d, "*.wav")))
            for old in wavs[:-500]:
                os.remove(old)
        except Exception as e:
            self.log(f"[voice] couldn't keep the radio clip: {e!r}")

    def transcribe(self, audio):
        if not self.ready:
            return ""
        audio = audio / max(1e-3, np.abs(audio).max()) * 0.9
        st = self.rec.create_stream()
        st.accept_waveform(SR, audio.astype(np.float32))
        low = _priority(below=True)        # the game keeps first call on the CPU while we listen
        try:
            self.rec.decode_stream(st)
        finally:
            if low:
                _priority(below=False)
        return (st.result.text or "").strip()


def _priority(below):
    """Windows: lower THIS THREAD (the recogniser) to below normal for a moment, and back.
    #538 (2026-10-29): this used to lower the whole program to below normal and "restore" it to plain normal, which
    undid the High priority the app sets for its sound (radio / crowd chopped while it listened, and High never stuck).
    Now only the recogniser's thread steps down; the program keeps its High priority."""
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetCurrentThread.restype = ctypes.c_void_p
        k.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        return bool(k.SetThreadPriority(k.GetCurrentThread(), -1 if below else 0))
    except Exception:
        return False
