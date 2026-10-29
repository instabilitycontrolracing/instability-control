"""Broadcast audio (2026-10-29, #515, Angelo: "make the radio distortion much more evident in the TV and OBS broadcast ...
louder in the mix ... and on the broadcast for the TV or OBS I want the radio key up sound to play").

Your headset keeps exactly the radio you have now. The broadcast (TV + stream) gets its own version, played by a small
separate program, "IC Broadcast Audio":
  * every team-radio clip, roughed up more (narrower band, more drive, a little grit), louder in the mix, with the
    radio key-up click before it and the squelch tail after it;
  * the crowd / ambience, so the broadcast keeps the atmosphere.
It plays to an output nobody listens to (Steam Streaming Speakers, else VB-CABLE), so it never reaches your headphones.
  - The TV: our Apollo build records every app EXCEPT the engineer's own process (its number goes in apollo_tv.txt as
    "Exclude PID: n" while the broadcast player is connected) - so the TV hears iRacing + the broadcast version.
  - OBS: "Broadcast radio" = an Audio Output Capture of that same output (set up by the OBS script).
The player is started through WMI so it is NOT in the engineer's process tree (Apollo leaves out the whole tree).
If the player isn't running, nothing changes: the TV hears the engineer as before (the Exclude line is removed).

Wire format (127.0.0.1:PORT, one client): 1 byte type, 4 bytes sample rate, 1 byte channels, 4 bytes frames, float32 data.
  type 1 = radio clip (mono), 2 = crowd block (stereo), 3 = settings (json in place of audio: frames = byte length).
"""
import json
import os
import queue
import socket
import struct
import subprocess
import sys
import threading
import time

import numpy as np

PORT = 8781
RATE = 48000
HDR = struct.Struct("<BIBI")
DEVICES = ("Steam Streaming Speakers", "CABLE Input")


# ============================================================ engineer side
class Link:
    """In the engineer: starts the player (outside our process tree), feeds it clips + crowd, keeps the TV file right."""

    def __init__(self, settings, log=print, on_change=None):
        self.s, self.log, self.on_change = settings, log, on_change or (lambda: None)
        self.sock = None
        self.q = queue.Queue(maxsize=400)
        self.connected = False
        self.running = True
        self._started_at = 0.0
        threading.Thread(target=self._loop, daemon=True, name="broadcast-link").start()

    # ---- taps (called from the audio threads: never block)
    def clip(self, audio, sr):
        if self.connected and getattr(self.s, "bcast_on", True):
            a = np.asarray(audio, dtype=np.float32).reshape(-1)
            self._put(1, int(sr), 1, a)

    def crowd(self, block):
        if self.connected and getattr(self.s, "bcast_on", True) and getattr(self.s, "bcast_crowd", True):
            b = np.asarray(block, dtype=np.float32)
            if b.ndim == 2 and b.shape[1] == 2:
                self._put(2, RATE, 2, b.copy())

    def push_settings(self):
        if self.connected:
            js = json.dumps({"grit": float(getattr(self.s, "bcast_grit", 1.0)), "db": float(getattr(self.s, "bcast_db", 6.0)),
                             "keyup": bool(getattr(self.s, "bcast_keyup", True)),
                             "crowd_db": float(getattr(self.s, "bcast_crowd_db", 0.0))}).encode()
            try:
                self.q.put_nowait(HDR.pack(3, 0, 0, len(js)) + js)
            except queue.Full:
                pass

    def _put(self, kind, sr, ch, a):
        try:
            self.q.put_nowait(HDR.pack(kind, sr, ch, len(a) if ch == 1 else a.shape[0]) + a.astype(np.float32).tobytes())
        except queue.Full:
            pass                                     # never hold up the headset audio

    # ---- connection
    def _start_player(self):
        """Start 'IC Broadcast Audio' through WMI (its parent is WMI, not us - Apollo excludes our whole tree)."""
        if time.time() - self._started_at < 30:
            return
        self._started_at = time.time()
        exe = sys.executable.replace("python.exe", "pythonw.exe") if sys.executable.lower().endswith("python.exe") else sys.executable
        cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = f'"{exe}" -m engineer.broadcast --serve'
        ps = ("$r = ([wmiclass]'Win32_Process').Create('" + cmd.replace("'", "''") + "', '" + cwd.replace("'", "''") + "'); "
              "$r.ReturnValue")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], capture_output=True,
                               text=True, timeout=20, creationflags=0x08000000)
            self.log(f"[broadcast] started the broadcast player (WMI {r.stdout.strip() or r.stderr.strip()[:80]})")
        except Exception as e:
            self.log(f"[broadcast] couldn't start the broadcast player: {e!r}")

    def _set_connected(self, on):
        if on == self.connected:
            return
        self.connected = on
        from . import audio_tool
        audio_tool.EXCLUDE_PID = os.getpid() if on else None
        self.log("[broadcast] connected - TV + stream get the broadcast radio" if on else "[broadcast] player gone - TV hears the engineer as before")
        try:
            self.on_change()
        except Exception as e:
            self.log(f"[broadcast] {e!r}")
        if on:
            self.push_settings()

    def _loop(self):
        while self.running:
            if not getattr(self.s, "bcast_on", True):
                self._close()
                time.sleep(1)
                continue
            if self.sock is None:
                try:
                    s = socket.create_connection(("127.0.0.1", PORT), timeout=1.0)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self.sock = s
                    while not self.q.empty():
                        self.q.get_nowait()
                    self._set_connected(True)
                except OSError:
                    self._start_player()
                    time.sleep(2)
                    continue
            try:
                msg = self.q.get(timeout=0.5)
                self.sock.sendall(msg)
            except queue.Empty:
                try:
                    self.sock.sendall(HDR.pack(0, 0, 0, 0))   # keep-alive
                except OSError:
                    self._close()
            except OSError:
                self._close()

    def _close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self._set_connected(False)

    def stop(self):
        self.running = False
        self._close()


# ============================================================ broadcast FX (player side; pure, testable)
def _bandpass(x, sr, lo, hi):
    try:
        from scipy.signal import butter, sosfilt
        sos = butter(4, [lo, min(hi, sr * 0.45)], btype="band", fs=sr, output="sos")
        return sosfilt(sos, x).astype(np.float32)
    except Exception:
        return x


def broadcast_fx(x, sr, grit=1.0, db=6.0):
    """The broadcast radio: on top of the headset version, a narrower band, more drive and a little grit, then louder
    with a peak limiter (never clips). grit 0 = only louder, 1 = clearly 'radio', 2 = heavy."""
    x = np.asarray(x, dtype=np.float32)
    if not x.size:
        return x
    g = float(max(0.0, min(2.0, grit)))
    if g > 0:
        lo, hi = 300 + 150 * g, 3400 - 600 * g
        y = _bandpass(x, sr, lo, hi)
        drive = 1.0 + 3.0 * g
        y = np.tanh(y * drive) / np.tanh(drive)
        if g > 0.5:                                         # a little grit: 10-bit steps, sample-and-hold at 16 kHz
            hold = max(1, int(sr / 16000))
            if hold > 1:
                y = np.repeat(y[::hold], hold)[:len(y)]
            y = np.round(y * 512) / 512
        x = y.astype(np.float32)
    from .voice import _loud
    return _loud(x, 10 ** (db / 20.0))


def keyup_click(sr=RATE, seed=1):
    """Radio key-up: a short transmit click plus a burst of filtered static (~90 ms)."""
    rng = np.random.default_rng(seed)
    n = int(0.09 * sr)
    t = np.arange(n) / sr
    noise = _bandpass(rng.standard_normal(n).astype(np.float32), sr, 900, 4000) * 0.35
    env = np.exp(-t / 0.03)
    click = np.zeros(n, np.float32); click[:int(0.004 * sr)] = 0.6 * np.hanning(int(0.008 * sr))[:int(0.004 * sr)]
    return (noise * env + click).astype(np.float32)


def squelch_tail(sr=RATE, seed=2):
    """Key-down: the squelch burst after the call (~140 ms)."""
    rng = np.random.default_rng(seed)
    n = int(0.14 * sr)
    t = np.arange(n) / sr
    noise = _bandpass(rng.standard_normal(n).astype(np.float32), sr, 600, 5000) * 0.45
    env = np.minimum(1.0, t / 0.01) * np.exp(-t / 0.05)
    return (noise * env).astype(np.float32)


def _resample(x, sr, rate=RATE):
    if sr == rate or not len(x):
        return x.astype(np.float32)
    n = int(round(len(x) * rate / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def build_call(x, sr, grit=1.0, db=6.0, keyup=True):
    """A whole broadcast radio call at 48 kHz mono: key-up, the roughed-up voice, squelch tail."""
    v = broadcast_fx(_resample(np.asarray(x, np.float32), sr), RATE, grit, db)
    if not keyup:
        return v
    k, s = keyup_click(), squelch_tail()
    gap = np.zeros(int(0.03 * RATE), np.float32)
    return np.concatenate([k * 10 ** (db / 40.0), gap, v, s * 10 ** (db / 40.0)]).astype(np.float32)


# ============================================================ player side (python -m engineer.broadcast --serve)
class Player:
    def __init__(self, log=print):
        self.log = log
        self.cfg = {"grit": 1.0, "db": 6.0, "keyup": True, "crowd_db": 0.0}
        self.calls = []                                    # queued calls (numpy mono)
        self.cur, self.pos = None, 0
        self.crowd = np.zeros((RATE * 2, 2), np.float32)   # 2 s ring
        self.cw = self.cr = 0
        self.lock = threading.Lock()

    def device(self):
        import sounddevice as sd
        devs = sd.query_devices()
        for want in DEVICES:
            for i, d in enumerate(devs):
                if want.lower() in d["name"].lower() and d["max_output_channels"] >= 2:
                    return i, d["name"]
        return None, None

    def add_call(self, x, sr):
        c = self.cfg
        call = build_call(x, sr, c["grit"], c["db"], c["keyup"])
        with self.lock:
            self.calls.append(call)

    def add_crowd(self, b):
        n = len(b)
        with self.lock:
            for i in range(n):
                self.crowd[(self.cw + i) % len(self.crowd)] = b[i]
            self.cw = (self.cw + n) % len(self.crowd)

    def render(self, out):
        frames = out.shape[0]
        out[:] = 0
        with self.lock:
            # crowd: play what has arrived (keep ~100 ms behind the writer for jitter)
            avail = (self.cw - self.cr) % len(self.crowd)
            if avail > int(0.1 * RATE) + frames or avail > RATE:
                if avail > RATE:                          # fell far behind: skip ahead
                    self.cr = (self.cw - int(0.1 * RATE) - frames) % len(self.crowd)
                idx = (self.cr + np.arange(frames)) % len(self.crowd)
                out += self.crowd[idx] * (10 ** (self.cfg["crowd_db"] / 20.0))
                self.cr = (self.cr + frames) % len(self.crowd)
            # radio: one call at a time, centred
            if self.cur is None and self.calls:
                self.cur, self.pos = self.calls.pop(0), 0
            if self.cur is not None:
                n = min(frames, len(self.cur) - self.pos)
                seg = self.cur[self.pos:self.pos + n]
                out[:n, 0] += seg; out[:n, 1] += seg
                self.pos += n
                if self.pos >= len(self.cur):
                    self.cur = None
        np.clip(out, -0.98, 0.98, out=out)

    def serve(self):
        import sounddevice as sd
        dev, name = self.device()
        if dev is None:
            self.log("no silent output (Steam Streaming Speakers / CABLE Input) - not starting")
            return
        stream = sd.OutputStream(samplerate=RATE, channels=2, dtype="float32", device=dev, blocksize=1024, latency=0.12,
                                 callback=lambda o, f, t, s: self.render(o))
        stream.start()
        self.log(f"playing the broadcast mix on: {name}")
        srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", PORT)); srv.listen(1)
        idle_since = time.time()
        srv.settimeout(5)
        while True:
            try:
                c, _ = srv.accept()
            except socket.timeout:
                if time.time() - idle_since > 120:        # the engineer is gone for good
                    self.log("no engineer for 2 minutes - closing")
                    break
                continue
            self.log("engineer connected")
            c.settimeout(10)
            try:
                self._client(c)
            except Exception as e:
                self.log(f"client: {e!r}")
            c.close()
            idle_since = time.time()
            self.log("engineer disconnected")
        stream.stop(); stream.close()

    def _client(self, c):
        def read(n):
            b = bytearray()
            while len(b) < n:
                d = c.recv(n - len(b))
                if not d:
                    raise ConnectionError("closed")
                b += d
            return bytes(b)
        while True:
            kind, sr, ch, frames = HDR.unpack(read(HDR.size))
            if kind == 0:
                continue
            if kind == 3:
                self.cfg.update(json.loads(read(frames)))
                self.log(f"settings {self.cfg}")
                continue
            data = np.frombuffer(read(frames * max(1, ch) * 4), dtype=np.float32)
            if kind == 1:
                self.add_call(data, sr)
            elif kind == 2:
                self.add_crowd(data.reshape(-1, 2))


def _main():
    logf = os.path.join(os.environ.get("LOCALAPPDATA", "."), "RaceEngineer", "broadcast_audio.log")
    def log(m):
        try:
            with open(logf, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")
        except Exception:
            pass
    try:                                                   # only one player at a time
        t = socket.socket(); t.bind(("127.0.0.1", PORT)); t.close()
    except OSError:
        log("already running"); return
    log(f"IC Broadcast Audio started (pid {os.getpid()})")
    Player(log).serve()


if __name__ == "__main__" and "--serve" in sys.argv:
    _main()
