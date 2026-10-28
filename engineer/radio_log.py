"""Team radio in the replay (2026-10-26, W3 #253): real broadcasts play the team radio when they show a car - so
Grandstand replays play back what YOUR engineer actually said to you, at the moment he said it.

While you race (live), every radio call that goes on air is kept with the race clock (iRacing's SubSessionID,
SessionNum and SessionTime) in RaceControl\\radio_log\\<subsession>\\. When you later watch the replay of that race,
each call plays again as the replay reaches that moment - only when playing forward at normal speed, and (by default)
only while the camera is on your car. Old races are cleaned up after 60 days.
"""
import json, os, threading, time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "RaceControl", "radio_log")


class RadioLog:
    def __init__(self, settings, log=print):
        self.s, self.log = settings, log
        self.ctx = None                 # (subsession, session_num, session_time) while live
        self.idx = {}                   # subsession -> list of entries
        self._prev_t = None
        self._playing = False
        self._cleanup()

    def opt(self, k, d):
        return getattr(self.s, k, d)

    # ---------- recording (a voice tap) ----------
    def tap(self, audio, sr):
        ctx = self.ctx
        if ctx is None or not self.opt("radio_replay", True):
            return
        sub, num, t = ctx
        try:
            import soundfile as sf
            d = os.path.join(LOG_DIR, str(sub))
            os.makedirs(d, exist_ok=True)
            name = f"{num}_{t:09.2f}.flac"
            a = np.asarray(audio, dtype=np.float32)
            threading.Thread(target=sf.write, args=(os.path.join(d, name), a, sr), daemon=True).start()
            ent = {"num": int(num), "t": float(t), "file": name, "dur": round(len(a) / sr, 2)}
            self.idx.setdefault(str(sub), []).append(ent)
            with open(os.path.join(d, "index.json"), "w", encoding="utf-8") as f:
                json.dump(self.idx[str(sub)], f)
        except Exception as e:
            self.log(f"[radio log] {e!r}")

    def _load(self, sub):
        sub = str(sub)
        if sub not in self.idx:
            try:
                with open(os.path.join(LOG_DIR, sub, "index.json"), encoding="utf-8") as f:
                    self.idx[sub] = json.load(f)
            except Exception:
                self.idx[sub] = []
        return self.idx[sub]

    # ---------- every tick ----------
    def update(self, sub, num, t, replay, speed, on_me, device=None):
        if not sub:
            return
        if not replay:
            self.ctx = (sub, num, t)
            self._prev_t = None
            return
        self.ctx = None
        if not self.opt("radio_replay", True):
            return
        prev, self._prev_t = self._prev_t, (num, t)
        if prev is None or prev[0] != num or speed != 1 or not (0 < t - prev[1] < 1.0):
            return                                          # jumped, rewinding, fast / slow: never replay old calls
        if self.opt("radio_replay_mine_only", True) and not on_me:
            return
        for e in self._load(sub):
            if e["num"] == num and prev[1] < e["t"] <= t and not self._playing:
                self._play(os.path.join(LOG_DIR, str(sub), e["file"]), device)
                break

    def _play(self, path, device):
        # 2026-10-27 (#403, request: "my recordings from last night were playing on the replay ... now it isn't"): the call
        # used sounddevice's ONE shared player (sd.play, blocking). Any other sound the app started with sd.play (a beep,
        # a click) took that player over, the blocking wait never returned, and "_playing" stayed on for good - so no
        # call ever played again. Now each call gets its own output stream, and a stuck flag clears itself.
        if self._playing and time.time() - getattr(self, "_play_t0", 0) > 30:
            self._playing = False
        def go():
            self._playing = True
            self._play_t0 = time.time()
            try:
                import soundfile as sf, sounddevice as sd
                a, sr = sf.read(path, dtype="float32", always_2d=True)
                a = np.ascontiguousarray(a * float(self.opt("radio_replay_vol", 0.9)), dtype=np.float32)
                with sd.OutputStream(samplerate=sr, channels=a.shape[1], device=device, dtype="float32") as st:
                    st.write(a)
                self.log(f"[radio log] played {os.path.basename(path)}")
            except Exception as e:
                self.log(f"[radio log] play: {e!r}")
            finally:
                self._playing = False
        threading.Thread(target=go, daemon=True).start()

    def _cleanup(self, days=60):
        try:
            cut = time.time() - days * 86400
            for d in os.listdir(LOG_DIR):
                p = os.path.join(LOG_DIR, d)
                if os.path.isdir(p) and os.path.getmtime(p) < cut:
                    import shutil
                    shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
