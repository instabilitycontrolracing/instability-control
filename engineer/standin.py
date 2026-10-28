"""Stand-in engineer voice (Windows' built-in voice) for lines that are written but not recorded yet.

Used only until a line is rendered into the Engineer1 library; the moment the real clips exist they win.
Returns float32 mono audio at the engine's sample rate, or None when no Windows voice is available.
"""
import io, threading
import numpy as np

_lock = threading.Lock()
_sapi = None
_failed = False


def _engine():
    global _sapi, _failed
    if _sapi is not None or _failed:
        return _sapi
    try:
        import clr
        clr.AddReference("System.Speech, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35")
        from System.Speech.Synthesis import SpeechSynthesizer
        s = SpeechSynthesizer()
        names = [v.VoiceInfo.Name for v in s.GetInstalledVoices()]
        male = next((n for n in names if "David" in n or "Mark" in n or "George" in n), names[0] if names else None)
        if male:
            s.SelectVoice(male)
        s.Rate = 1
        _sapi = s
    except Exception:
        _failed = True
    return _sapi


def synth(text, sr):
    with _lock:
        s = _engine()
        if s is None:
            return None
        try:
            from System.IO import MemoryStream
            import soundfile as sf
            ms = MemoryStream()
            s.SetOutputToWaveStream(ms)
            s.Speak(text)
            s.SetOutputToNull()
            a, r = sf.read(io.BytesIO(bytes(ms.ToArray())), dtype="float32")
        except Exception:
            return None
    if a.ndim > 1:
        a = a.mean(axis=1)
    if r != sr:
        a = np.interp(np.arange(0, len(a), r / sr), np.arange(len(a)), a).astype(np.float32)
    peak = float(np.max(np.abs(a))) if len(a) else 0.0
    return (a / peak * 0.85).astype(np.float32) if peak > 0 else a.astype(np.float32)
