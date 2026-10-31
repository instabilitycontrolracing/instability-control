"""Team meeting by voice: you talk into your mic, the engineer and mechanic answer out loud.

- HandsFree: the mic stays open; when you stop talking (about 0.8 s of quiet) what you said is turned into
  text (Parakeet, CPU) and sent to the team. While the team is thinking or talking the mic is muted, so
  it never hears itself.
- Speaker: the team's answer is spoken sentence by sentence while it is still being written, so the first
  words come out after a second or two. It goes through your output device with the radio sound.

Voices: for now Windows' built-in voice (engineer as is, mechanic pitched down) as a stand-in. The real
cloned engineer / mechanic voices plug into `_synth_clone` (see TODO) - everything else stays the same.
"""
import io, os, queue, re, threading, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PRESET = os.path.join(ROOT, "tools", "radio_preset.json")
SR_OUT = 24000
SR_MIC = 16000


# ------------------------------------------------------------------ text -> something nice to say
def speakable(t):
    t = t.replace("**", "").replace("*", "").replace("#", "")
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)
    # lap times 3:29.902 -> "3 29 point 9"
    t = re.sub(r"\b(\d):(\d\d)\.(\d)\d*\b", lambda m: f"{m.group(1)} {m.group(2)} point {m.group(3)}", t)
    t = re.sub(r"([+-]?)(\d+)\.(\d+)\s*s\b", lambda m: ("minus " if m.group(1) == "-" else "") + f"{m.group(2)} point {m.group(3)} seconds", t)
    t = re.sub(r"(\d+)\s*km/h", r"\1 kilometres an hour", t)
    t = re.sub(r"(\d+)\s*m\b", r"\1 metres", t)
    t = t.replace("FARB", "front roll bar").replace("RARB", "rear roll bar").replace("TC", "traction control")
    t = t.replace("ABS", "A B S").replace("->", "to").replace("→", "to")
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ strategist library
_CLIPS = {}


def _clip(path):
    a = _CLIPS.get(path)
    if a is None:
        import soundfile as sf
        y, sr = sf.read(path, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        if sr != SR_OUT:
            y = np.interp(np.arange(0, len(y), sr / SR_OUT), np.arange(len(y)), y).astype(np.float32)
        _CLIPS[path] = a = y
    return a


def strat_clip(engine, text):
    """Join the strategist's library pieces for this sentence. -> float32 mono at SR_OUT, or None if any piece is missing."""
    import os, re as _re
    from .strat_lines import SPOKEN, norm_text, KIND
    spec = SPOKEN.get(norm_text(text))
    if not spec:
        return None
    key, template, fills = spec
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Strategist", engine)
    d = os.path.join(base, "s", key.replace("~", "__"))
    names = _re.findall(r"\[([a-z]+)\]", template)
    parts = []
    for n in range(len(names) + 1):
        p = os.path.join(d, f"{n}.wav")
        if not os.path.exists(p):
            return None
        parts.append(_clip(p))
        if n < len(names):
            f = names[n]
            fp = os.path.join(base, "f", KIND.get(f, f), f"{fills.get(f, '')}.wav")
            if not os.path.exists(fp):
                return None
            parts.append(_clip(fp))
    gap = np.zeros(int(0.025 * SR_OUT), np.float32)
    out = []
    for i, p in enumerate(parts):
        if len(p):
            out += [p, gap]
    if not out:
        return None
    y = np.concatenate(out[:-1])
    return (y / (np.abs(y).max() + 1e-9) * 0.85).astype(np.float32)


# ------------------------------------------------------------------ voices
class Speaker:
    def __init__(self, settings, log=print, emit=None):
        self.s, self.log = settings, log
        self.emit = emit or (lambda e: None)
        self.q = queue.Queue()
        self.player = None
        self._sapi = None
        self._gen = 0                # bumps on stop(): drops everything queued before it
        self.busy = False
        self._fx = None
        self._pitch = None
        self._aq = queue.Queue()
        self._making = self._playing = False
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._playback, daemon=True).start()

    # -- public --
    def say(self, role, text):
        text = speakable(text)
        if text:
            self.q.put((self._gen, role, text))

    def stop(self):
        self._gen += 1
        for qq in (self.q, self._aq):
            try:
                while True:
                    qq.get_nowait()
            except queue.Empty:
                pass
        if self.player:
            try:
                self.player.stop()
            except Exception:
                pass

    def idle(self):
        return not self.busy and self.q.empty()

    # -- internals --
    def _ensure_player(self):
        dev = getattr(self.s, "device", "") or None
        if self.player is None or self.player.device != dev:
            from .voice import _Player, RadioFX
            if self.player:
                self.player.close()
            self.player = _Player(SR_OUT, dev)
            self._fx = RadioFX(PRESET, SR_OUT, getattr(self.s, "radio_strength", 1.0))
        if self._fx and abs(self._fx.strength - getattr(self.s, "radio_strength", 1.0)) > 0.01:
            self._fx.set_strength(self.s.radio_strength)

    def _worker(self):
        """Makes the audio, one sentence ahead of what's playing."""
        while True:
            gen, role, text = self.q.get()
            if gen != self._gen:
                continue
            self._making = True
            self.busy = True
            try:
                audio = self._synth(role, text)
                if audio is not None and gen == self._gen:
                    self._aq.put((gen, role, audio))
            except Exception as e:
                self.log(f"[meeting] voice problem: {e!r}")
            finally:
                self._making = False
                self._check_idle()

    def _playback(self):
        while True:
            gen, role, audio = self._aq.get()
            if gen != self._gen:
                self._check_idle(); continue
            try:
                self._ensure_player()
                audio = self._fx(audio) if self._fx else audio
                # ic165: strategist / rest of the crew have their own level on top of the master, peak-limited like the radio
                from .voice import _loud
                k = 1.0 if role == "ENGINEER" else float((getattr(self.s, "strategist_volume", 1.0) if role == "STRATEGIST"
                                                          else getattr(self.s, "crew_volume", 1.0)) or 0)
                audio = np.asarray(_loud(audio, float(getattr(self.s, "volume", 1.0)) * k), dtype=np.float32)
                self._playing = True
                from .voice import RADIO, PRIO_INFO
                for attempt in (1, 2):            # cut off by the spotter? say the line again once it's clear
                    if not RADIO.take(self.player, PRIO_INFO) or gen != self._gen:   # wait for the radio to be free
                        RADIO.give(self.player)
                        break
                    try:
                        self.emit({"t": "meet_talk", "role": role, "on": True})
                        self.player.play(audio, PRIO_INFO)
                    finally:
                        RADIO.give(self.player)
                    if not getattr(self.player, "cut", False) or gen != self._gen:
                        break
            except Exception as e:
                self.log(f"[meeting] playback problem: {e!r}")
            finally:
                self._playing = False
                self._check_idle()

    def _check_idle(self):
        if not self._making and not self._playing and self.q.empty() and self._aq.empty() and self.busy:
            self.busy = False
            self.emit({"t": "meet_talk", "on": False})

    def _synth(self, role, text):
        a = self._synth_clone(role, text)
        if a is None:
            a = self._synth_sapi(role, text)
        return a

    def _synth_clone(self, role, text):
        """Recorded (pre-rendered) voices. Strategist: her library pieces + number clips joined together.
        None = not in the library -> the stand-in voice says it. (Engineer / mechanic clones: TODO.)"""
        if role != "STRATEGIST":
            return None
        eng = getattr(self.s, "strat_voice", "chatterbox")
        if eng not in ("chatterbox", "f5"):
            return None
        try:
            return strat_clip(eng, text)
        except Exception as e:
            self.log(f"[voice] strategist clip: {e!r}")
            return None

    def _synth_sapi(self, role, text):
        if self._sapi is None:
            import clr
            clr.AddReference("System.Speech, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35")
            from System.Speech.Synthesis import SpeechSynthesizer
            self._sapi = SpeechSynthesizer()
            names = [v.VoiceInfo.Name for v in self._sapi.GetInstalledVoices()]
            self._male = next((n for n in names if "David" in n or "Mark" in n), names[0] if names else None)
            self._female = next((n for n in names if "Zira" in n or "Hazel" in n or "Susan" in n), self._male)
            self._sapi.Rate = 1
        # placeholder voices until the real ones exist: strategist = female voice, engineer/mechanic = male
        want = self._female if role == "STRATEGIST" else self._male
        if want:
            self._sapi.SelectVoice(want)
        from System.IO import MemoryStream
        ms = MemoryStream()
        self._sapi.SetOutputToWaveStream(ms)
        self._sapi.Speak(text)
        self._sapi.SetOutputToNull()
        import soundfile as sf
        a, sr = sf.read(io.BytesIO(bytes(ms.ToArray())), dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        a = np.interp(np.arange(0, len(a), sr / SR_OUT), np.arange(len(a)), a).astype(np.float32)
        if role == "MECHANIC":                      # a different voice until the real ones exist
            try:
                if self._pitch is None:
                    from pedalboard import Pedalboard, PitchShift
                    self._pitch = Pedalboard([PitchShift(-3.5)])
                a = self._pitch(a, SR_OUT).astype(np.float32)
            except Exception:
                pass
        return a


class Splitter:
    """Turns the streamed answer into (role, sentence) pieces as soon as each sentence is complete."""
    def __init__(self, out):
        self.out, self.buf, self.role = out, "", "ENGINEER"

    def feed(self, delta):
        self.buf += delta
        while True:
            m = re.search(r"(ENGINEER:|MECHANIC:)", self.buf)
            cut = re.search(r"[.!?](\s|$)(?=\S|$)", self.buf)
            if m and (not cut or m.start() < cut.start()):
                head = self.buf[:m.start()].strip()
                if head:
                    self.out(self.role, head)
                self.role = m.group(1)[:-1]
                self.buf = self.buf[m.end():]
                continue
            cut = re.search(r"[.!?]\s+", self.buf)
            if cut and len(self.buf[:cut.end()].strip()) > 2:
                self.out(self.role, self.buf[:cut.end()].strip())
                self.buf = self.buf[cut.end():]
                continue
            break

    def flush(self):
        if self.buf.strip():
            self.out(self.role, self.buf.strip())
        self.buf = ""


# ------------------------------------------------------------------ hands-free mic
class HandsFree:
    """Open mic with simple voice detection. on_speech(audio) gets each thing you said."""
    FRAME = 480                  # 30 ms at 16 kHz

    def __init__(self, on_speech, can_listen, device=None, log=print, emit=None):
        self.on_speech, self.can_listen = on_speech, can_listen
        self.device, self.log = device, log
        self.emit = emit or (lambda e: None)
        self.on = False
        self._stream = None
        self._q = queue.Queue()

    def start(self):
        if self.on:
            return
        import sounddevice as sd
        try:
            self._stream = sd.InputStream(samplerate=SR_MIC, channels=1, dtype="float32", device=self.device or None,
                                          blocksize=self.FRAME, callback=lambda d, f, t, s: self._q.put(d[:, 0].copy()))
            self._stream.start()
        except Exception as e:
            self.log(f"[meeting] microphone problem: {e!r}")
            self._stream = None
            return
        self.on = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.on = False
        s, self._stream = self._stream, None
        if s:
            try:
                s.stop(); s.close()
            except Exception:
                pass

    def _loop(self):
        floor, talking, quiet, voiced = 0.004, False, 0, 0
        pre, cur, last_level = [], [], 0.0
        while self.on:
            try:
                fr = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            rms = float(np.sqrt(np.mean(fr * fr)) + 1e-9)
            now = time.time()
            if now - last_level > 0.1:
                last_level = now
                self.emit({"t": "meet_level", "v": min(1.0, rms * 12)})
            if not self.can_listen():
                talking, cur, pre, voiced = False, [], [], 0
                continue
            thr = max(0.012, floor * 3.2)
            if not talking:
                floor = 0.97 * floor + 0.03 * min(rms, 0.05)
                pre = (pre + [fr])[-10:]                # 300 ms before you start
                voiced = voiced + 1 if rms > thr else 0
                if voiced >= 3:
                    talking, cur, quiet = True, list(pre), 0
                    self.emit({"t": "meet_state", "state": "hearing"})
            else:
                cur.append(fr)
                quiet = quiet + 1 if rms < thr * 0.7 else 0
                if quiet >= 27 or len(cur) > 25 * SR_MIC // self.FRAME:     # ~0.8 s quiet, or 25 s max
                    talking, voiced = False, 0
                    audio = np.concatenate(cur)
                    cur, pre = [], []
                    if len(audio) > SR_MIC * 0.5:
                        self.on_speech(audio)
                    else:
                        self.emit({"t": "meet_state", "state": "listening"})
