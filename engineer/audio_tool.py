"""The sound multitool (2026-10-25, request: "incorporate all that into the engineer thing so it is like a one stop shop").

The developer's chain: games -> Voicemeeter Input -> [Equalizer APO: HeSuVi virtual surround + the Bose 700 correction] ->
Voicemeeter A1 (Yeti -> Bose 700 headphones) and Voicemeeter B1 (Windows "listen" -> CABLE Input -> Apollo -> the TV).

From Settings > Sound mix:
  * headphones: the Bose 700 correction on / off, headphone level (Voicemeeter A1)
  * TV: the stream's level (Voicemeeter B1) and whether the game sound goes to it
  * car sound: engine body (low end) and tyre / detail (presence) boosts, written as an Equalizer APO file that APO
    picks up instantly; applied to the game sound, so headphones and TV both get it

Equalizer APO reads two files of ours, included once from its config.txt:
  C:\\SimRacing\\Audio\\grandstand_car.txt         (car sound)
  C:\\SimRacing\\Audio\\grandstand_headphones.txt  (the Bose 700 correction, moved here from config.txt)
Anything missing (no Voicemeeter, no APO) = that part is skipped, never an error.
"""
import ctypes
import os
import time

AUDIO_DIR = r"C:\SimRacing\Audio"
CAR_FILE = os.path.join(AUDIO_DIR, "grandstand_car.txt")
HP_FILE = os.path.join(AUDIO_DIR, "grandstand_headphones.txt")
TV_FILE = os.path.join(AUDIO_DIR, "grandstand_tv.txt")      # 2026-10-26: home-theatre 2.1 on the TV path only
EXCLUDE_PID = None   # 2026-10-29 (#515): set by broadcast.Link while the broadcast player is connected
STREAM_FILE = os.path.join(AUDIO_DIR, "apollo_tv.txt")      # 2026-10-26 (#303): the same, read by the developer's Apollo build
TRACKSIDE_IR = os.path.join(AUDIO_DIR, "trackside_space.wav")  # 2026-10-26 (#229): the circuit's reflections
# 2026-10-26 (D4 #242 / D5 #243): your own car while driving - the pit wall and garages on pit road, and under a bridge
# or in a tunnel. Same trick as the trackside cameras (an echo of the real game sound, nothing made up).
SPACES = {
    # name: (file, early taps [(seconds, gain, pan)], tail seconds, tail level, tail brightness Hz, air cut dB)
    "trackside": ("trackside_space.wav", [(0.017, 0.30, 0.0), (0.029, 0.22, 0.3), (0.043, 0.18, -0.4), (0.061, 0.14, 0.5),
                                          (0.078, 0.11, -0.2), (0.097, 0.08, 0.6), (0.112, 0.06, -0.6)], 0.16, 0.018, 3500, -2.5),
    "pit": ("pitlane_space.wav", [(0.009, 0.32, -0.7), (0.014, 0.24, -0.5), (0.022, 0.20, 0.6), (0.031, 0.15, -0.6),
                                  (0.044, 0.10, 0.5)], 0.10, 0.012, 5000, 0.0),        # garage doors on one side, the wall on the other
    "tunnel": ("tunnel_space.wav", [(0.006, 0.38, -0.3), (0.011, 0.34, 0.3), (0.018, 0.28, -0.2), (0.026, 0.24, 0.2),
                                    (0.035, 0.20, 0.0), (0.047, 0.16, 0.0)], 0.35, 0.05, 2500, 0.0),  # concrete all round
}

# The TV path is CABLE Input (Voicemeeter B1 -> Windows "listen" -> CABLE Input -> Apollo -> the TV). This tuning is
# for a 2.1 home-theatre (the receiver's own crossover feeds the sub): weight under the engine for the subwoofer, the
# low-mid mud thinned, voices / team radio lifted, a little air for the crowd. Gated to CABLE Input, so the headphones
# never get it; the preamp leaves room for the boosts, so it can't clip.
# 2026-10-26 (request: "the TV needs home-theatre tuning on all the time ... Samsung 7 series 65\" 4K, optical out to a
# Sony DAV-HDX279W, front left/right speakers and the stock bass speaker only"): tuned for that 2.1 - a stereo optical
# feed, the Sony's own crossover sends the lows to its passive sub. So: nothing below ~30 Hz (that sub can't play it,
# it only eats power and muddies), a moderate lift through 40-90 Hz for engine and kerbs, less 250 Hz boxiness from the
# tall front speakers, a voice / radio lift around 2.5 kHz, a touch of air. Preamp keeps every boost below clipping.
HOME_THEATRE = """Device: CABLE Input
Channel: all
Preamp: -6 dB
Filter 1: ON HP Fc 30 Hz Q 0.71
Filter 2: ON LSC Fc 85 Hz Gain 4.5 dB Q 0.71
Filter 3: ON PK Fc 55 Hz Gain 1.5 dB Q 1.10
Filter 4: ON PK Fc 250 Hz Gain -2.0 dB Q 1.00
Filter 5: ON PK Fc 2500 Hz Gain 2.0 dB Q 1.00
Filter 6: ON HSC Fc 8000 Hz Gain 1.0 dB Q 0.71
"""
# 2026-10-26 (#208, late-night mode): LoudMax (Thomas Mundt's free look-ahead limiter, installed only on this PC, never
# shipped) after a +12 dB lift. Quiet moments come up 12 dB, the loud ones are held at -9 dB - checked offline with APO's
# Benchmark: a -34 dB passage came out at -22 dB, a -6 dB one at -9 dB, so the quiet-to-loud gap went from 28 to 13 dB.
LOUDMAX = r"C:\SimRacing\Audio\VST\LoudMax\LoudMax64.dll"
NIGHT = f"""Preamp: 12 dB
VSTPlugin: Library "{LOUDMAX}" Thresh 0.6 Output 0.7
"""
VM_DLL = r"C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote64.dll"
APO_CONFIG = r"C:\Program Files\EqualizerAPO\config\config.txt"

# the Bose 700 correction (the developer's tuned curve, as it was in config.txt)
BOSE_700 = """Device: Voicemeeter Input
Stage: post-mix
Channel: L R
Preamp: -7.0 dB
Filter 1: ON LSC Fc 105 Hz Gain -2.5 dB Q 0.70
Filter 2: ON PK Fc 180 Hz Gain -3.8 dB Q 0.99
Filter 3: ON PK Fc 1236 Hz Gain 2.7 dB Q 4.06
Filter 4: ON PK Fc 27 Hz Gain 3.7 dB Q 0.98
Filter 5: ON PK Fc 8335 Hz Gain 6.8 dB Q 1.58
Filter 6: ON HSC Fc 10000 Hz Gain 0.3 dB Q 0.70
Filter 7: ON PK Fc 4828 Hz Gain -4.2 dB Q 5.68
Filter 8: ON PK Fc 3430 Hz Gain 1.4 dB Q 2.66
Filter 9: ON PK Fc 6625 Hz Gain 1.8 dB Q 6.00
Filter 10: ON PK Fc 816 Hz Gain -0.7 dB Q 2.91
"""

BUS_HP, BUS_TV, STRIP_GAME = 0, 1, 2      # Voicemeeter (standard): A1 = headphones, B1 = TV stream; Voicemeeter Input


# Car "voices" for the Sound mix sliders (2026-10-26, #300). Each filter: (slider, type, Hz, dB at 100 %, Q).
# The Engine body slider scales the "engine" filters, Tyres & detail the "detail" ones.
CAR_VOICES = {
    "": {"name": "generic", "filters": [
        ("engine", "LSC", 95, 6.0, 0.70), ("engine", "PK", 170, 2.5, 1.00),
        ("detail", "PK", 2800, 4.5, 1.20), ("detail", "PK", 5200, 2.0, 2.00)]},
    # BMW M Hybrid V8 (P66/3: 4.0 l twin-turbo 90-degree V8, 8,200 rpm limit - BMW press kit). A four-stroke V8 fires 4
    # times per turn, so its note sits at rpm / 15: ~300 Hz on a slow exit (4,500 rpm), ~550 Hz at the limiter. The
    # voice lifts that firing band (where the generic one lifted only the low rumble), adds a little chest under it and
    # some bite from the 2nd harmonic; detail goes on tyre scrub / kerbs / gear whine, but NOT above 5 kHz, where the
    # Bose correction already lifts the treble (the developer found that region hissy).
    "bmwlmdh": {"name": "BMW M Hybrid V8", "filters": [
        ("engine", "LSC", 100, 3.0, 0.70),      # chest / weight
        ("engine", "PK", 420, 5.0, 0.80),       # the V8's firing note, 300-550 Hz
        ("engine", "PK", 900, 1.5, 1.00),       # 2nd harmonic: bite on the upshift
        ("engine", "PK", 220, -1.0, 1.20),      # keeps the low-mids from going boxy under the lift
        ("detail", "PK", 2600, 4.0, 1.20),      # tyres, kerbs, brakes
        ("detail", "PK", 1600, 1.5, 2.00)]},    # gearbox / hybrid whine region
}


def voice_for(car_path):
    """-> (voice key, voice). The car's own tuned voice; else (2026-10-29, car parity E4) a draft voice for its engine
    type, worked out from the sourced cylinder count and Lovely Car Data's shift-light rpm the same way as the BMW's
    (cars.voice_band); else the generic one. The two BMWs keep exactly what they had (Hybrid V8 voice / generic)."""
    if car_path in CAR_VOICES:
        return car_path, CAR_VOICES[car_path]
    if car_path in ("bmwm4gt3", "bmwm4evogt3"):
        return "", CAR_VOICES[""]
    try:
        from . import cars
        band = cars.voice_band(car_path)
    except Exception:
        band = None
    if not band:
        return "", CAR_VOICES[""]
    note = band["note"]
    filters = [("engine", "LSC", 100, 3.0, 0.70),              # chest / weight (as the BMW voice)
               ("engine", "PK", note, 5.0, 0.80),              # this engine's firing note
               ("engine", "PK", min(2 * note, 4000), 1.5, 1.00)]   # 2nd harmonic: bite on the upshift
    if note >= 330:
        filters.append(("engine", "PK", 220, -1.0, 1.20))     # keeps the low-mids from going boxy (only clear of the note)
    filters += [("detail", "PK", 2600, 4.0, 1.20), ("detail", "PK", 1600, 1.5, 2.00)]
    name = f"{cars.engine_label(car_path) or str(band['cyl']) + '-cylinder'} draft ({band['rpm']} rpm shift light)"
    return car_path, {"name": name, "filters": filters, "draft": True}


class AudioMix:
    def __init__(self, log=print):
        self.log = log
        self._dll = None
        self._tried = False
        self.last_error = ""

    # ------------------------------------------------------------------ Voicemeeter
    def _vm(self):
        if self._tried:
            return self._dll
        self._tried = True
        try:
            if os.path.exists(VM_DLL):
                d = ctypes.WinDLL(VM_DLL)
                if d.VBVMR_Login() in (0, 1):
                    time.sleep(0.2)
                    d.VBVMR_IsParametersDirty()
                    self._dll = d
        except Exception as e:
            self.last_error = f"Voicemeeter: {e}"
        return self._dll

    def _get(self, name):
        d = self._vm()
        if not d:
            return None
        v = ctypes.c_float()
        d.VBVMR_IsParametersDirty()
        return v.value if d.VBVMR_GetParameterFloat(name.encode(), ctypes.byref(v)) == 0 else None

    def _set(self, name, value):
        d = self._vm()
        if d:
            d.VBVMR_SetParameterFloat(name.encode(), ctypes.c_float(float(value)))

    # ------------------------------------------------------------------ Equalizer APO files
    @staticmethod
    def _write(path, text):
        if not os.path.exists(AudioMix.APO_CONFIG) and not os.path.isdir(AUDIO_DIR):
            return      # distribution: no Equalizer APO and no audio folder on this PC - nothing reads these files
        os.makedirs(AUDIO_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        AudioMix._nudge_apo()

    APO_CONFIG = r"C:\Program Files\EqualizerAPO\config\config.txt"

    @staticmethod
    def _nudge_apo():
        """2026-10-26: Equalizer APO only reloads when config.txt itself changes - NOT when a file it includes changes
        (measured: a new preamp in grandstand_tv.txt was ignored for 20 s+). So after every write, touch config.txt
        (the developer's account was given write access to that one file)."""
        try:
            os.utime(AudioMix.APO_CONFIG, None)
        except OSError:
            pass

    def write_car(self, engine, detail, trackside=None, space=None):
        """engine / detail: 0..100. Engine body = low shelf + a little low-mid; detail = presence for tyre squeal,
        kerbs and gear whine. The preamp drops by the largest boost so nothing can clip.
        trackside (#229): on a trackside / TV camera the game's cars get the circuit around them - the sound bouncing
        back off the grandstands and the pit wall, and a touch of distance in the top end. Onboard and driving stay dry."""
        self._eng, self._det = engine, detail
        if space is None:
            space = ("trackside" if trackside else "") if trackside is not None else getattr(self, "_space", "")
        self._space = space or ""
        self._ts_on = self._space == "trackside"
        e, t = max(0, min(100, int(engine))) / 100.0, max(0, min(100, int(detail))) / 100.0
        lines = ["# Grandstand car sound (written by the Race Engineer app - Settings > Sound mix)",
                 "Device: Voicemeeter Input", "Stage: post-mix", "Channel: all"]
        # 2026-10-26: Voicemeeter Input ONLY. Naming the Yeti too made everything that reaches the Yeti through
        # Voicemeeter get this file a second time (request: "I never want to see the double correction again").
        voice = voice_for(getattr(self, "voice", ""))[1]
        if e <= 0 and t <= 0:
            lines.append("# off")
        else:
            filt = [(k, fc, g * (e if part == "engine" else t), q) for part, k, fc, g, q in voice["filters"]
                    if (e if part == "engine" else t) > 0]
            boost = max([g for _, _, g, _ in filt if g > 0] or [0.0])
            lines.append(f"# voice: {voice['name']}")
            lines.append(f"Preamp: {-boost:.1f} dB")
            for n, (k, fc, g, q) in enumerate(filt, 1):
                lines.append(f"Filter {n}: ON {k} Fc {fc} Hz Gain {g:.1f} dB Q {q:.2f}")
        sp = SPACES.get(self._space)
        if sp:
            ir = os.path.join(AUDIO_DIR, sp[0])
            if os.path.exists(ir):
                lines.append(f"# space: {self._space} (#229 trackside camera / #242 pit road / #243 bridge, tunnel)")
                if sp[5]:
                    lines.append(f"Filter: ON HSC Fc 9000 Hz Gain {sp[5]:.1f} dB Q 0.70")
                lines.append(f"Convolution: {ir}")
        self._write(CAR_FILE, "\n".join(lines) + "\n")

    @staticmethod
    def make_space_ir(kind, rate=48000):
        """Reflections for one space as an impulse response (made once, in code - it shapes the REAL game sound)."""
        import wave
        import numpy as np
        fname, taps, tail_s, tail_g, bright, _ = SPACES[kind]
        path = os.path.join(AUDIO_DIR, fname)
        rng = np.random.default_rng(229 + len(kind))
        n = int(max(0.5, tail_s * 5) * rate)
        ir = np.zeros((n, 2))
        for t, g, pan in taps:
            i = int(t * rate)
            ir[i, 0] += g * (1 - max(0, pan)); ir[i, 1] += g * (1 + min(0, pan))
        k = np.arange(n) / rate
        tail = rng.standard_normal((n, 2)) * np.exp(-k / tail_s)[:, None] * tail_g
        tail[: int(0.02 * rate)] = 0
        f = np.fft.rfftfreq(n, 1 / rate)
        tail = np.fft.irfft(np.fft.rfft(tail, axis=0) * (1 / np.sqrt(1 + (f / bright) ** 2))[:, None], n, axis=0)
        early = np.fft.irfft(np.fft.rfft(ir, axis=0) * (1 / np.sqrt(1 + (f / 6000.0) ** 2))[:, None], n, axis=0)
        out = early + tail
        out[0] = 1.0
        out *= 0.85
        pcm = (np.clip(out, -1, 1) * 32767).astype("<i2")
        os.makedirs(AUDIO_DIR, exist_ok=True)
        with wave.open(path, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.tobytes())
        return path

    def space(self, s, kind):
        """kind: "" (dry), "trackside", "pit", "tunnel". Rewrites the car file only on a change."""
        on_ok = {"trackside": getattr(s, "snd_trackside_space", True), "pit": getattr(s, "snd_driving_space", True),
                 "tunnel": getattr(s, "snd_driving_space", True)}
        kind = kind if (kind in SPACES and on_ok.get(kind, False)) else ""
        if kind == getattr(self, "_space", ""):
            return
        try:
            if kind and not os.path.exists(os.path.join(AUDIO_DIR, SPACES[kind][0])) and os.path.exists(APO_CONFIG):
                self.make_space_ir(kind)      # (only with Equalizer APO installed - nothing else uses it)
            self.write_car(getattr(self, "_eng", getattr(s, "snd_engine", 0)), getattr(self, "_det", getattr(s, "snd_detail", 0)),
                           space=kind)
        except Exception as e:
            self.last_error = f"space: {e}"[:160]

    @staticmethod
    def make_trackside_ir(path=TRACKSIDE_IR, rate=48000):
        """The circuit's reflections as an impulse response (made once, in code): the direct sound untouched, then
        the slap back off the pit wall and the grandstands (15-110 ms, each a little duller) and a short open-air
        tail (about 0.7 s, 20 dB down) - a big outdoor space, not a hall."""
        import wave
        import numpy as np
        rng = np.random.default_rng(229)
        n = int(0.8 * rate)
        ir = np.zeros((n, 2))
        ir[0] = 1.0
        taps = [(0.017, 0.30, 0.0), (0.029, 0.22, 0.3), (0.043, 0.18, -0.4), (0.061, 0.14, 0.5),
                (0.078, 0.11, -0.2), (0.097, 0.08, 0.6), (0.112, 0.06, -0.6)]
        for t, g, pan in taps:
            i = int(t * rate)
            ir[i, 0] += g * (1 - max(0, pan)); ir[i, 1] += g * (1 + min(0, pan))
        k = np.arange(n) / rate
        tail = rng.standard_normal((n, 2)) * np.exp(-k / 0.16)[:, None] * 0.018
        tail[: int(0.03 * rate)] = 0
        f = np.fft.rfftfreq(n, 1 / rate)
        damp = 1 / np.sqrt(1 + (f / 3500.0) ** 2)                    # air soaks up the highs
        tail = np.fft.irfft(np.fft.rfft(tail, axis=0) * damp[:, None], n, axis=0)
        early = ir.copy(); early[0] = 0
        early = np.fft.irfft(np.fft.rfft(early, axis=0) * (1 / np.sqrt(1 + (f / 6000.0) ** 2))[:, None], n, axis=0)
        out = early + tail
        out[0] = 1.0
        out *= 0.85                                                    # room for the extra energy
        pcm = (np.clip(out, -1, 1) * 32767).astype("<i2")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with wave.open(path, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.tobytes())
        return path

    def trackside(self, s, on):
        """(kept for older callers) trackside camera on / off."""
        self.space(s, "trackside" if on else "")
        return
        on = bool(on) and bool(getattr(s, "snd_trackside_space", True))
        if on == getattr(self, "_ts_on", False):
            return
        try:
            if on and not os.path.exists(TRACKSIDE_IR):
                self.make_trackside_ir()
            self.write_car(getattr(self, "_eng", getattr(s, "snd_engine", 0)), getattr(self, "_det", getattr(s, "snd_detail", 0)), on)
        except Exception as e:
            self.last_error = f"trackside: {e}"[:160]

    def write_headphones(self, on):
        head = "# Bose 700 correction (Race Engineer app - Settings > Sound mix)\n"
        self._write(HP_FILE, head + (BOSE_700 if on else "# off\n"))

    def write_stream(self, s=None):
        """2026-10-26 (#295 / #303): the TV's own mix for the developer's Apollo build. Apollo now records every app's sound
        BEFORE the headphone processing (Windows process loopback) and runs this file itself: the home-theatre curve,
        TV volume, mute, lip-sync delay and late-night mode - so they finally reach the TV, and never the headphones."""
        if s is not None:
            self._stream_opts = (float(getattr(s, "snd_tv_db", 0.0) or 0.0), bool(getattr(s, "snd_tv_mute", False)),
                                 int(getattr(s, "snd_tv_delay_ms", 0) or 0))
        vol, mute, delay = getattr(self, "_stream_opts", (0.0, False, 0))
        if getattr(self, "_tv_on", None) is None and s is not None:      # before the first tick (iRacing closed)
            self._stream_base = (bool(getattr(s, "snd_tv_ht", True)) and bool(getattr(s, "snd_tv_ht_live", False)),
                                 bool(getattr(s, "snd_tv_night", False)))
        on, night = getattr(self, "_tv_on", None) or getattr(self, "_stream_base", (False, False))
        lines = ["# TV stream mix, read live by Apollo (Race Engineer app - Settings > Sound mix)",
                 f"Volume: {vol:.1f} dB", f"Mute: {1 if mute else 0}", f"Delay: {delay} ms", f"Night: {1 if night else 0}"]
        if on:
            lines += [x for x in HOME_THEATRE.splitlines() if x.startswith(("Preamp", "Filter"))]
        if EXCLUDE_PID:                                  # #515: the TV hears the broadcast radio, not the headset one
            lines.append(f"Exclude PID: {int(EXCLUDE_PID)}")
        text = "\n".join(lines) + "\n"
        if getattr(self, "_stream_last", None) != text:
            self._stream_last = text
            self._write(STREAM_FILE, text)

    def write_tv(self, on, night=False):
        night = bool(night)
        if getattr(self, "_tv_on", None) == (on, night):
            return
        self._tv_on = (on, night)
        self.write_stream()
        night = night and os.path.exists(LOUDMAX)
        head = "# TV home-theatre 2.1 for the Samsung -> optical -> Sony DAV-HDX279W (Race Engineer app - Settings > Sound mix)\n"
        if on:
            body = HOME_THEATRE + (NIGHT if night else "")
        elif night:
            body = "Device: CABLE Input\nChannel: all\n" + NIGHT
        else:
            body = "# off\n"
        self._write(TV_FILE, head + body)

    def tv_tick(self, s, replay):
        """Called by the app a few times a second: the home-theatre tuning follows the replay (or always, if chosen)."""
        on = bool(getattr(s, "snd_tv_ht", True)) and (bool(replay) or bool(getattr(s, "snd_tv_ht_live", False)))
        try:
            self.write_tv(on, getattr(s, "snd_tv_night", False))
        except Exception as e:
            self.last_error = f"TV: {e}"[:160]
        self.default_guard(s)

    # ------------------------------------------------------------------ Driving / Broadcast mode (2026-10-26)
    YETI = "Speakers (Yeti Stereo Microphone)"
    IRACING_INI = os.path.join(os.path.expanduser("~"), "Documents", "iRacing", "app.ini")

    def set_mode(self, mode):
        """2026-10-26 (audio overhaul Phase B). "driving": the fastest path for VR - Voicemeeter lets go of the Yeti and
        Windows (and iRacing) play straight to it; 3D from Windows Sonic, the Bose correction from Equalizer APO's Yeti
        block. "broadcast": the Voicemeeter chain with the TV copy (HeSuVi 3D). Returns a list of what was done / needs doing."""
        out = []
        from pycaw.pycaw import AudioUtilities as A
        def dev(prefix):
            return next((d for d in A.GetAllDevices() if (d.FriendlyName or "").startswith(prefix)
                         and str(d.state).endswith("Active")), None)
        d = self._vm()
        if mode == "driving":
            if d:
                d.VBVMR_SetParameterStringA(b"Bus[0].device.wdm", b"")
                out.append("Voicemeeter let go of the Yeti")
            time.sleep(1.5)
            y = dev(self.YETI)
            if y is None:
                return {"ok": False, "steps": out, "msg": "Yeti not found"}
            A.SetDefaultDevice(y.id, self._roles())
            out.append("Windows now plays straight to the Yeti")
        else:
            if d:
                d.VBVMR_SetParameterStringA(b"Bus[0].device.wdm", self.YETI.encode())
                out.append("Voicemeeter has the Yeti again")
            vmi = dev("Voicemeeter Input")
            if vmi is not None:
                A.SetDefaultDevice(vmi.id, self._roles())
                out.append("Windows plays to Voicemeeter (TV copy on)")
        out.append(self.iracing_follow_default())
        return {"ok": True, "steps": out, "msg": "; ".join(x for x in out if x)}

    @staticmethod
    def _roles():
        """Both of Windows' default-device slots (console + multimedia) - pycaw only sets "console" on its own."""
        from pycaw.constants import ERole
        return [ERole.eConsole, ERole.eMultimedia]

    def iracing_follow_default(self):
        """iRacing: play to Windows' default device (so the mode switch moves it). Only edited while iRacing is closed -
        it rewrites app.ini on exit. Takes effect the next time iRacing starts."""
        try:
            import subprocess
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq iRacingSim64DX11.exe"], capture_output=True, text=True,
                               creationflags=0x08000000)
            if "iRacingSim64DX11.exe" in r.stdout:
                return "iRacing is running - it switches the next time it starts"
            p = self.IRACING_INI
            t = open(p, encoding="latin-1", newline="").read()   # byte-exact round trip
            if "devSpeakerDefault=1" in t:
                return "iRacing already follows Windows' default device"
            import re
            t2 = re.sub(r"devSpeakerDefault=\d", "devSpeakerDefault=1", t, count=1)
            if t2 != t:
                import shutil
                shutil.copy(p, p + ".bak_before_followdefault")
                open(p, "w", encoding="latin-1", newline="").write(t2)
                return "iRacing set to follow Windows' default device"
            return ""
        except Exception as e:
            return f"iRacing setting not changed: {e!r}"[:120]

    def default_guard(self, s):
        """2026-10-26 (request: "it plays on the TV but not my headphones"): Apollo switches Windows' default sound output
        to its TV device (CABLE Input) when a stream starts, and then everything skips Voicemeeter -> no headphones. The
        TV gets its copy from Voicemeeter B1 anyway, so the default goes straight back to Voicemeeter Input (checked
        every 3 s; only ever away from CABLE Input, so a device you pick yourself is left alone)."""
        if not getattr(s, "snd_keep_default", True):
            return
        now = time.time()
        if now - getattr(self, "_guard_t", 0) < 3.0:
            return
        self._guard_t = now
        try:
            from pycaw.pycaw import AudioUtilities as A
            cur = A.GetSpeakers()
            name = getattr(cur, "FriendlyName", "") or ""
            if not name.startswith("CABLE Input"):
                return
            want = self.YETI if getattr(s, "audio_mode", "broadcast") == "driving" else "Voicemeeter Input"
            vm = next((d for d in A.GetAllDevices() if (d.FriendlyName or "").startswith(want)
                       and str(d.state).endswith("Active")), None)
            if vm is not None:
                A.SetDefaultDevice(vm.id, self._roles())
                self.log(f"[sound] Windows' default output had moved to CABLE Input (Apollo) - back to {want}")
        except Exception as e:
            if not getattr(self, "_guard_err", False):
                self._guard_err = True
                self.log(f"[sound] default-output guard: {e!r}")

    @staticmethod
    def cable_has_apo():
        """Is Equalizer APO installed on the TV path (CABLE Input)? Without it the TV tuning file has no effect."""
        try:
            import winreg
            base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EqualizerAPO\Child APOs") as k:
                apos = {winreg.EnumKey(k, i).lower() for i in range(winreg.QueryInfoKey(k)[0])}
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    g = winreg.EnumKey(k, i)
                    try:
                        with winreg.OpenKey(k, g + r"\Properties") as p:
                            name = winreg.QueryValueEx(p, "{a45c254e-df1c-4efd-8020-67d146a850e0},2")[0]
                    except OSError:
                        continue
                    if name == "CABLE Input" and g.lower() in apos:
                        return True
        except OSError:
            pass
        return False

    def _hooked_tv(self):
        try:
            with open(APO_CONFIG, encoding="utf-8", errors="replace") as f:
                return TV_FILE.lower() in f.read().lower()
        except OSError:
            return False

    def apo_hooked(self):
        try:
            with open(APO_CONFIG, encoding="utf-8", errors="replace") as f:
                t = f.read()
            return CAR_FILE.lower() in t.lower() and HP_FILE.lower() in t.lower()
        except OSError:
            return False

    # ------------------------------------------------------------------ apply settings
    def apply(self, s, key=None):
        """Apply one changed setting (key) or, with key=None, only the APO files (start-up: Voicemeeter levels are
        never touched at start, so a running intro's TV ducking isn't undone)."""
        try:
            if key is None or key in ("snd_engine", "snd_detail"):
                self.write_car(getattr(s, "snd_engine", 0), getattr(s, "snd_detail", 0))
            if key is None or key == "snd_hp_eq":
                self.write_headphones(getattr(s, "snd_hp_eq", True))
            if key in ("snd_tv_ht", "snd_tv_ht_live", "snd_tv_night"):
                self._tv_on = None                       # rewritten on the next tick with the new choice
            if key == "snd_hp_db":
                self._set(f"Bus[{BUS_HP}].Gain", max(-40.0, min(6.0, float(s.snd_hp_db))))
            elif key == "snd_tv_db":
                self._set(f"Bus[{BUS_TV}].Gain", max(-60.0, min(6.0, float(s.snd_tv_db))))
            elif key == "snd_tv_game":
                self._set(f"Strip[{STRIP_GAME}].B1", 1.0 if s.snd_tv_game else 0.0)
            elif key == "snd_tv_mute":
                self._set(f"Bus[{BUS_TV}].Mute", 1.0 if s.snd_tv_mute else 0.0)
            if key is None or key in ("snd_tv_db", "snd_tv_mute", "snd_tv_delay_ms", "snd_tv_ht", "snd_tv_ht_live", "snd_tv_night"):
                self.write_stream(s)                     # the TV's own mix in Apollo (#303)
            self.last_error = ""
        except Exception as e:
            self.last_error = str(e)[:160]
            self.log(f"[sound] {e!r}")

    def _setup_state(self):
        """Is Equalizer APO installed / hooked up (files + the whole render-device registry)? Asked twice a second
        while the Sound page is open; it changes only when the driver installs something - checked every 5 s
        (2026-10-29, efficiency). The live levels below stay twice a second."""
        now = time.monotonic()
        c = getattr(self, "_setup_c", None)
        if c is None or now - c[0] > 5.0:
            c = self._setup_c = (now, {"apo": os.path.exists(APO_CONFIG), "apo_hooked": self.apo_hooked(),
                                       "tv_apo": self.cable_has_apo(), "tv_hooked": self._hooked_tv()})
        return c[1]

    def state(self):
        vm = self._vm() is not None
        su = self._setup_state()
        st = {"voicemeeter": vm, "apo": su["apo"], "apo_hooked": su["apo_hooked"], "error": self.last_error,
              "tv_apo": su["tv_apo"], "tv_hooked": su["tv_hooked"], "tv_on": bool(getattr(self, "_tv_on", False))}
        if vm:
            st["hp_db"] = self._get(f"Bus[{BUS_HP}].Gain")
            st["tv_db"] = self._get(f"Bus[{BUS_TV}].Gain")
            st["tv_game"] = (self._get(f"Strip[{STRIP_GAME}].B1") or 0) > 0.5
            st["tv_mute"] = (self._get(f"Bus[{BUS_TV}].Mute") or 0) > 0.5
            lv = []
            d = self._dll
            for ch in (0, 1, 8, 9):
                v = ctypes.c_float()
                lv.append(round(v.value, 3) if d.VBVMR_GetLevel(3, ch, ctypes.byref(v)) == 0 else 0)
            st["hp_level"], st["tv_level"] = max(lv[0], lv[1]), max(lv[2], lv[3])
        return st
