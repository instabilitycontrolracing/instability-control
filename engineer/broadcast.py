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
import collections, json
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
        self.mixer = None                              # the crowd mixer (watch()): its bed goes to the player too
        self._bed_sent, self._gain_sent, self._bed_check = None, None, 0.0
        threading.Thread(target=self._loop, daemon=True, name="broadcast-link").start()

    def watch(self, mixer):
        """2026-10-30 (#604): the player gets the crowd's recorded loop (the bed) and its level, so when the crowd
        arrives late it blends into the bed - exactly what the headset player does - instead of going silent."""
        self.mixer = mixer

    def _send_bed(self):
        m = self.mixer
        if m is None or not self.connected:
            return
        try:
            bed = getattr(m, "bed", None)
            if bed is not None and bed is not self._bed_sent and getattr(bed, "ndim", 0) == 2 and bed.shape[1] == 2:
                a = np.ascontiguousarray(bed, np.float32)
                msg = bytearray(HDR.size + a.nbytes)
                HDR.pack_into(msg, 0, 4, RATE, 2, a.shape[0])
                msg[HDR.size:] = memoryview(a).cast("B")
                self.sock.sendall(msg)                 # (this thread owns the socket)
                self._bed_sent = bed
            g = float(getattr(m, "bed_gain", 0.0) or 0.0)
            if self._gain_sent is None or abs(g - self._gain_sent) > 1e-3:
                js = json.dumps({"bed_gain": g}).encode()
                self.sock.sendall(HDR.pack(3, 0, 0, len(js)) + js)
                self._gain_sent = g
        except OSError:
            raise
        except Exception as e:
            self.log(f"[broadcast] bed: {e!r}")

    # ---- taps (called from the audio threads: never block)
    def clip(self, audio, sr):
        if self.connected and getattr(self.s, "bcast_on", True):
            a = np.asarray(audio, dtype=np.float32).reshape(-1)
            self._put(1, int(sr), 1, a)

    # ic173 (#675): the driver's radio, live while the button is held - start (key-up), 16 kHz mic blocks, end (squelch)
    def live_start(self):
        if self.connected and getattr(self.s, "bcast_on", True):
            self._live = True
            self._put(5, 16000, 1, np.zeros(0, np.float32))

    def live_chunk(self, a, sr):
        if getattr(self, "_live", False) and self.connected:
            self._put(6, int(sr), 1, np.asarray(a, np.float32).reshape(-1))

    def live_end(self):
        if getattr(self, "_live", False):
            self._live = False
            self._put(7, 16000, 1, np.zeros(0, np.float32))

    def crowd(self, block):
        if self.connected and getattr(self.s, "bcast_on", True) and getattr(self.s, "bcast_crowd", True):
            b = np.asarray(block, dtype=np.float32)
            if b.ndim == 2 and b.shape[1] == 2:
                self._put(2, RATE, 2, b)                 # _put copies it once into the message (the block is reused)

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
        # 2026-10-29 (efficiency): called from the audio callbacks - one copy of the samples straight into the message
        # (was four: copy, astype, tobytes, header + data)
        try:
            a = np.ascontiguousarray(a, dtype=np.float32)
            msg = bytearray(HDR.size + a.nbytes)
            HDR.pack_into(msg, 0, kind, sr, ch, len(a) if ch == 1 else a.shape[0])
            msg[HDR.size:] = memoryview(a).cast("B")
            self.q.put_nowait(msg)
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
        # ic171 (#685, 2026-10-31: "now we have no audio to the tv"): every change of EXCLUDE_PID makes Apollo restart the
        # TV's sound capture. A short drop (the player hung up after a 10 s stall, then reconnected) flipped it back and
        # forth every 15-20 s and the TV kept cutting out. Now a drop only changes the TV after the player has been gone
        # 30 s (_loop); a reconnect inside that time changes nothing.
        if not on:
            self._gone_at = time.monotonic()
            self.log("[broadcast] player dropped - reconnecting (TV unchanged)")
            return
        self._gone_at = None
        changed = audio_tool.EXCLUDE_PID != os.getpid()
        audio_tool.EXCLUDE_PID = os.getpid()
        self.log("[broadcast] connected - TV + stream get the broadcast radio")
        if changed:
            try:
                self.on_change()
            except Exception as e:
                self.log(f"[broadcast] {e!r}")
        self.push_settings()

    def _gone_check(self):
        """ic171: the player really is gone (30 s) - the TV goes back to hearing the engineer itself."""
        g = getattr(self, "_gone_at", None)
        if self.connected or g is None or time.monotonic() - g < 30:
            return
        self._gone_at = None
        from . import audio_tool
        if audio_tool.EXCLUDE_PID is None:
            return
        audio_tool.EXCLUDE_PID = None
        self.log("[broadcast] player gone - TV hears the engineer as before")
        try:
            self.on_change()
        except Exception as e:
            self.log(f"[broadcast] {e!r}")

    def _loop(self):
        # 2026-10-30 (#604): this thread hands the crowd over; at normal priority it waited behind the engineer's other
        # work and then delivered in big bursts (the player ran dry, then had too much). Same priority as the crowd feed.
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), 2)   # HIGHEST
            except Exception:
                pass
        while self.running:
            self._gone_check()
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
                    self._bed_sent = self._gain_sent = None    # a new player: send the bed again
                    self._set_connected(True)
                except OSError:
                    self._start_player()
                    time.sleep(2)
                    continue
            try:
                now = time.monotonic()
                if now - self._bed_check > 0.5:
                    self._bed_check = now
                    self._send_bed()
                msg = self.q.get(timeout=0.5)
                s = self.sock
                if s is None:
                    continue
                s.sendall(msg)
            except queue.Empty:
                try:
                    s = self.sock
                    if s is not None:                     # (stop() may have closed it meanwhile)
                        s.sendall(HDR.pack(0, 0, 0, 0))   # keep-alive
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


_FIXED = {}


def _fixed(fn, sr, seed):
    """keyup_click / squelch_tail are the same every call (fixed seed): made once (they're read-only)."""
    k = (fn.__name__, sr, seed)
    if k not in _FIXED:
        a = fn(sr, seed)
        a.setflags(write=False)
        _FIXED[k] = a
    return _FIXED[k]


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
    k, s = _fixed(keyup_click, RATE, 1), _fixed(squelch_tail, RATE, 2)
    gap = np.zeros(int(0.03 * RATE), np.float32)
    return np.concatenate([k * 10 ** (db / 40.0), gap, v, s * 10 ** (db / 40.0)]).astype(np.float32)


# ============================================================ player side (python -m engineer.broadcast --serve)
class Player:
    def __init__(self, log=print):
        self.log = log
        self.cfg = {"grit": 1.0, "db": 6.0, "keyup": True, "crowd_db": 0.0, "bed_gain": 0.0}
        self.calls = []                                    # queued calls (numpy mono)
        # ic173 (#675): the driver's live radio - a short queue of processed 48 kHz blocks, played back to back
        self.live, self.live_n, self.live_play, self.live_open = collections.deque(), 0, False, False
        self.live_zi, self.live_prev, self.live_pk = None, 0.0, 0.05
        self.cur, self.pos = None, 0
        self.crowd = np.zeros((int(RATE * self.RING_S), 2), np.float32)
        self.cw = self.cr = 0
        self.queued = 0                                    # crowd frames waiting (exact; the ring never wraps onto itself)
        self.crowd_on = False
        self.frac = 0.0
        # pauses between deliveries, as a sliding-window maximum (each entry is bigger than every later one): the
        # longest pause of the window is always arrivals[0], found without a scan in the sound card's callback
        self.arrivals, self.last_arrival = collections.deque(), 0.0
        self.underruns = self.skips = self.dropped = self.dev_gaps = 0
        self.lock = threading.Lock()
        # the bed (the same recorded crowd loop the headset player falls back on), sent by the engineer
        self.bed, self.bpos = None, 0
        self.g_feed = self.g_bed = 0.0
        self._bufs(4096)

    def _bufs(self, n):
        """Work buffers made once (the sound card's callback allocates nothing in the normal case)."""
        self._n = n
        self._ar = np.arange(n, dtype=np.float64)
        self._pos = np.empty(n, np.float64)
        self._fl = np.empty(n, np.float64)
        self._i0 = np.empty(n, np.intp)
        self._i1 = np.empty(n, np.intp)
        self._w = np.empty((n, 2), np.float32)
        self._a = np.empty((n, 2), np.float32)
        self._b = np.empty((n, 2), np.float32)
        self._seg = np.empty((n, 2), np.float32)
        self._ramp_buf = np.empty((n, 2), np.float32)        # full width: no numpy scratch buffer per multiply
        self._ar2 = np.repeat(self._ar[:, None], 2, axis=1).astype(np.float32)
        self._wd = np.empty(n, np.float64)

    def device(self, wasapi=False):
        """The silent output. wasapi=True (setting bcast_wasapi) prefers its Windows WASAPI entry; otherwise the first
        match in PortAudio's list, as before (on Windows that is usually the DirectSound entry)."""
        import sounddevice as sd
        devs = sd.query_devices()
        try:
            apis = [a["name"] for a in sd.query_hostapis()]
        except Exception:
            apis = []
        for want in DEVICES:
            hits = [(i, d) for i, d in enumerate(devs)
                    if want.lower() in d["name"].lower() and d["max_output_channels"] >= 2]
            if wasapi:
                w = [(i, d) for i, d in hits if d.get("hostapi", -1) < len(apis) and "WASAPI" in apis[d["hostapi"]]]
                hits = w + hits
            if hits:
                i, d = hits[0]
                api = apis[d["hostapi"]] if d.get("hostapi", -1) < len(apis) else "?"
                return i, f"{d['name']} ({api})"
        return None, None

    def add_call(self, x, sr):
        c = self.cfg
        call = build_call(x, sr, c["grit"], c["db"], c["keyup"])
        with self.lock:
            self.calls.append(call)

    def set_bed(self, bed):
        bed = np.ascontiguousarray(np.asarray(bed, np.float32).reshape(-1, 2))
        with self.lock:
            self.bed = bed if len(bed) > RATE // 4 else None
            self.bpos = 0

    def add_crowd(self, b):
        n = len(b)
        L = len(self.crowd)
        with self.lock:
            # 2026-10-29 (efficiency): two slice copies around the ring end instead of an index array per block
            now = time.monotonic()
            if self.last_arrival:
                gap = now - self.last_arrival
                ar = self.arrivals
                while ar and ar[-1][1] <= gap:
                    ar.pop()
                ar.append((now, gap))
            self.last_arrival = now
            w, end = self.cw, (self.cw + n) % L
            if n > L:                                 # never expected: only the newest part survives, where it always went
                w, b, n = (w + n - L) % L, b[-L:], L
            k = min(n, L - w)
            self.crowd[w:w + k] = b[:k]
            if n > k:
                self.crowd[:n - k] = b[k:]
            self.cw = end
            self.queued += n
            if self.queued > L - 4096:                # (8 s ring: only if the player itself stopped) keep the newest
                over = self.queued - (L - 4096)
                self.cr = (self.cr + over) % L
                self.queued -= over
                self.dropped += 1

    # 2026-10-29 evening: the crowd arrives on the headset card's clock and plays on another card's clock; the two never
    # tick at exactly the same speed, so the queue slowly emptied (1-3 audible "ran dry" gaps a minute even with the PC
    # idle) or filled up. Now the player gently speeds up / slows down the crowd (at most 0.5 %, inaudible) to keep the
    # queue at the target - no gaps from drift.
    # 2026-10-30 (#604, the broadcast log: 1-7 "ran dry" and 0-4 "skipped ahead" EVERY minute of the race; the recordings
    # had crowd holes of 100-440 ms): the crowd comes from the engineer in bursts (its link thread waits its turn behind
    # the engineer's other work, then hands over everything at once). The old queue aimed at 0.12 s, forgot a long pause
    # after 30 s, went SILENT when it ran out (and waited for a whole cushion before coming back), and threw away
    # everything past 1 s with a hard jump. Now, the same design as the headset player (audio_proc.py):
    #   * a bigger cushion: at least 0.3 s, and 1.5x the longest pause between deliveries in the last 2 minutes (max 1 s);
    #   * running low: the recorded crowd loop (the bed) blends in over 30 ms BEFORE the queue is empty, so it never goes
    #     silent; the live crowd blends back over 0.3 s only once a full cushion is queued again (no flutter);
    #   * too much queued (a burst after a pause): played a little faster (up to 2 %) until it is back near the target,
    #     never skipped. Only a queue of more than 4 s (the engineer and the player out of step) is trimmed, with a fade.
    RING_S = 8.0
    TARGET = 0.3               # seconds of crowd kept queued at least
    TARGET_MAX = 1.0           # ...and at most
    WINDOW_S = 120.0           # how long a long pause between deliveries is remembered
    MAX_TRIM = 0.005           # normal speed correction (0.5 %)
    CATCH_TRIM = 0.02          # catching up after a burst (2 %, crowd noise - not heard as a change)
    SKIP_S = 4.0               # only past this much queued is any crowd dropped (with a fade)
    LOW_S = 0.06               # blend into the bed when less than this would be left after the block
    DRY_S = 0.03               # live -> bed blend
    BACK_S = 0.3               # bed -> live blend

    def _target(self):
        now = time.monotonic()
        while self.arrivals and now - self.arrivals[0][0] > self.WINDOW_S:
            self.arrivals.popleft()
        worst = self.arrivals[0][1] if self.arrivals else 0.0
        return int(min(self.TARGET_MAX, max(self.TARGET, worst * 1.5)) * RATE)

    def _ramp(self, g0, g1, n):
        if g0 == g1:
            return float(g0)       # a plain float (a numpy float64 makes numpy work in float64: a temporary copy)
        r = self._ramp_buf[:n]
        np.multiply(self._ar2[:n], np.float32((g1 - g0) / n), out=r)
        r += np.float32(g0)
        return r

    def _crowd_block(self, frames, ratio, out_ab):
        """frames of the queued crowd at speed ratio (linear interpolation) into out_ab; advances the read point."""
        L = len(self.crowd)
        pos, fl, i0, i1, w = self._pos[:frames], self._fl[:frames], self._i0[:frames], self._i1[:frames], self._w[:frames]
        a, b = out_ab, self._b[:frames]
        np.multiply(self._ar[:frames], ratio, out=pos)
        pos += self.frac
        np.floor(pos, out=fl)
        wd = self._wd[:frames]
        np.subtract(pos, fl, out=wd)
        w[:, 0] = wd
        w[:, 1] = wd
        fl += self.cr
        np.remainder(fl, L, out=fl)
        np.copyto(i0, fl, casting="unsafe")
        np.add(i0, 1, out=i1)
        i1[i1 >= L] -= L
        np.take(self.crowd, i0, axis=0, out=a, mode="wrap")   # (indices are in range; "raise" buffers the copy)
        np.take(self.crowd, i1, axis=0, out=b, mode="wrap")
        b -= a
        b *= w
        a += b
        need = self.frac + frames * ratio
        step = int(need)
        self.cr = (self.cr + step) % L
        self.queued -= step
        self.frac = need - step

    def live_start(self):
        with self.lock:
            self.live.clear(); self.live_n = 0; self.live_play = False; self.live_open = True
            self.live_zi, self.live_prev, self.live_pk = None, 0.0, 0.05
            if self.cfg.get("keyup", True) or True:
                k = (_fixed(keyup_click, RATE, 1) * 10 ** (self.cfg.get("db", 0.0) / 40.0)).astype(np.float32)
                self.live.append(np.concatenate([k, np.zeros(int(0.03 * RATE), np.float32)]))
                self.live_n += len(self.live[-1])

    def live_chunk(self, x, sr):
        """One mic block -> 48 kHz (continuous across blocks), the broadcast radio band with filter state carried over
        (no clicks at the joins), drive, a slow level follower, and into the queue."""
        x = np.asarray(x, np.float32)
        if not len(x):
            return
        n_out = int(round(len(x) * RATE / sr))
        xx = np.concatenate([[self.live_prev], x]).astype(np.float32)
        y = np.interp(np.arange(n_out) * (sr / RATE), np.arange(len(xx)), xx).astype(np.float32)
        self.live_prev = float(x[-1])
        g = float(max(0.0, min(2.0, self.cfg.get("grit", 1.0))))
        try:
            from scipy.signal import butter, sosfilt, sosfilt_zi
            if self.live_zi is None:
                self._live_sos = butter(4, [300 + 150 * g, min(3400 - 600 * g, RATE * 0.45)], btype="band", fs=RATE, output="sos")
                self.live_zi = sosfilt_zi(self._live_sos) * 0.0
            y, self.live_zi = sosfilt(self._live_sos, y, zi=self.live_zi)
            y = y.astype(np.float32)
        except Exception:
            pass
        drive = 1.0 + 3.0 * g
        y = np.tanh(y * drive * 4.0) / np.tanh(drive)
        pk = float(np.abs(y).max()) if len(y) else 0.0
        self.live_pk = max(pk, self.live_pk * 0.97, 0.02)
        gain = min(8.0, 0.55 / self.live_pk) * 10 ** (self.cfg.get("db", 0.0) / 20.0)
        y = np.clip(y * gain, -0.95, 0.95).astype(np.float32)
        with self.lock:
            if self.live_n > 1.5 * RATE:                      # never let the radio fall behind: drop the oldest
                while self.live and self.live_n > 0.3 * RATE:
                    self.live_n -= len(self.live.popleft())
            self.live.append(y); self.live_n += len(y)

    def live_end(self):
        with self.lock:
            sq = (_fixed(squelch_tail, RATE, 2) * 10 ** (self.cfg.get("db", 0.0) / 40.0)).astype(np.float32)
            self.live.append(sq); self.live_n += len(sq)
            self.live_open = False

    def _live_mix(self, out, frames):
        """(inside render, lock held) the live radio: starts once ~0.1 s is queued, so mic blocks arriving a little
        unevenly never leave gaps; plays to the end after the button is released."""
        if not self.live_play:
            if self.live_n >= int(0.10 * RATE) or (not self.live_open and self.live_n > 0):
                self.live_play = True
            else:
                return
        i = 0
        while i < frames and self.live:
            blk = self.live[0]
            k = min(frames - i, len(blk))
            out[i:i + k, 0] += blk[:k]; out[i:i + k, 1] += blk[:k]
            if k == len(blk):
                self.live.popleft()
            else:
                self.live[0] = blk[k:]
            self.live_n -= k; i += k
        if not self.live:
            self.live_play = False
            self.live_n = 0

    def render(self, out):
        frames = out.shape[0]
        if frames > self._n:
            self._bufs(frames)
        out[:] = 0
        with self.lock:
            L = len(self.crowd)
            target = self._target()
            avail = self.queued
            cg = 10 ** (self.cfg["crowd_db"] / 20.0)
            ratio = 1.0
            if avail > self.SKIP_S * RATE:                # way out of step: drop to the target (faded below)
                over = avail - target
                self.cr = (self.cr + over) % L
                self.queued -= over
                avail, self.frac = target, 0.0
                self.skips += 1
                self.g_feed = 0.0
            if not self.crowd_on and avail >= target:
                self.crowd_on, self.frac = True, 0.0
            if self.crowd_on:
                err = (avail - target) / RATE
                hi = self.CATCH_TRIM if avail > (self.TARGET_MAX + 0.25) * RATE else self.MAX_TRIM
                ratio = 1.0 + max(-self.MAX_TRIM, min(hi, err * 0.05))
                need = self.frac + frames * ratio
                if avail < need + 2 + self.LOW_S * RATE:  # running low: the bed takes over (live fades out on what's left)
                    self.crowd_on = False
                    self.underruns += 1
            ratio_now = ratio if self.crowd_on else 1.0
            have_bed = self.bed is not None and self.cfg.get("bed_gain", 0.0) > 0
            tf = 1.0 if self.crowd_on else 0.0
            tb = 0.0 if self.crowd_on else (1.0 if have_bed else 0.0)
            g0f, g0b = self.g_feed, self.g_bed
            sf = frames / (RATE * (self.BACK_S if tf > g0f else self.DRY_S))
            sb = frames / (RATE * (self.DRY_S if tb > g0b else 0.4))
            g1f = min(tf, g0f + sf) if tf > g0f else max(tf, g0f - sf)
            g1b = min(tb, g0b + sb) if tb > g0b else max(tb, g0b - sb)
            if g0f > 0 or g1f > 0:                        # live crowd (also while it fades out)
                need = self.frac + frames * ratio_now
                if self.queued >= int(need) + 2:
                    a = self._a[:frames]
                    self._crowd_block(frames, ratio_now, a)
                    a *= self._ramp(g0f * cg, g1f * cg, frames)
                    out += a
                else:                                     # (only if a burst was shorter than LOW_S) what's left, faded
                    m = min(frames, max(0, self.queued - 2))
                    if m > 0:
                        a = self._a[:m]
                        self._crowd_block(m, 1.0, a)
                        a *= self._ramp(g0f * cg, 0.0, m)
                        out[:m] += a
                    g1f = 0.0
            self.g_feed = g1f
            bed = self.bed
            if bed is not None:
                Lb = len(bed)
                bg = self.cfg.get("bed_gain", 0.0) * cg
                if (g0b > 0 or g1b > 0) and bg > 0:
                    seg = self._seg[:frames]; p = self.bpos; i = 0
                    while i < frames:
                        k = min(frames - i, Lb - p)
                        seg[i:i + k] = bed[p:p + k]
                        i += k; p = (p + k) % Lb
                    seg *= self._ramp(g0b * bg, g1b * bg, frames)
                    out += seg
                self.bpos = (self.bpos + frames) % Lb     # keeps time while silent: seamless returns
            self.g_bed = g1b
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
            if self.live_n or self.live:
                self._live_mix(out, frames)                # ic173: the driver's radio, live
        np.clip(out, -0.98, 0.98, out=out)

    LATENCY = 0.2              # device cushion (was 0.12; 2026-10-30, #604)

    def serve(self):
        import sounddevice as sd
        from . import audio_proc
        # 2026-10-30 (#604): this player had normal priority, so with VR + OBS + the 4K encode loading the PC, Windows
        # could keep it waiting past its 0.12 s cushion. Now it runs like the headset sound program: high priority,
        # its sound thread registered as "Pro Audio" (MMCSS), no Windows power throttling.
        self.log("priority: " + audio_proc.boost_process())
        try:                  # #604: the first radio call imported scipy / the voice code while the sound was playing
            build_call(np.sin(np.arange(4800) * 0.3).astype(np.float32), RATE)       # loud: warms the limiter too
        except Exception:
            pass
        wasapi = bool(_setting("bcast_wasapi", False))
        dev, name = self.device(wasapi=wasapi)
        if dev is None:
            self.log("no silent output (Steam Streaming Speakers / CABLE Input) - not starting")
            return
        mm = audio_proc.ThreadBoost()

        def cb(o, f, t, s):
            mm.once()
            if s and s.output_underflow:
                self.dev_gaps += 1
            try:
                self.render(o)
            except Exception:
                o[:] = 0
        kw = {}
        if wasapi and "WASAPI" in (name or ""):
            try:
                kw["extra_settings"] = sd.WasapiSettings(auto_convert=True)
            except Exception:
                pass
        try:
            stream = sd.OutputStream(samplerate=RATE, channels=2, dtype="float32", device=dev, blocksize=1024,
                                     latency=self.LATENCY, callback=cb, **kw)
        except Exception as e:
            if not kw:
                raise
            self.log(f"WASAPI open failed ({e!r}) - using the usual entry")
            dev, name = self.device(wasapi=False)
            stream = sd.OutputStream(samplerate=RATE, channels=2, dtype="float32", device=dev, blocksize=1024,
                                     latency=self.LATENCY, callback=cb)
        stream.start()
        try:
            self.log(f"device cushion {stream.latency * 1000:.0f} ms, block 1024")
        except Exception:
            pass
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
            c.settimeout(60)   # ic171: keep-alives come every 0.5 s; 10 s hung up on a busy engineer and flipped the TV sound
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
        last = time.time()
        while True:
            if time.time() - last > 60:
                last = time.time()
                if self.dev_gaps:
                    self.log(f"sound card gaps in the last minute: {self.dev_gaps} (this player was late)")
                    self.dev_gaps = 0
                if self.underruns or self.skips or self.dropped:
                    self.log(f"crowd in the last minute: ran low {self.underruns}x (the bed covered it"
                             f"{'' if self.bed is not None else ' - NO BED YET, so it went quiet'}), "
                             f"{self.skips} trimmed after falling 4 s out of step, {self.dropped} overfilled")
                self.underruns = self.skips = self.dropped = 0
            kind, sr, ch, frames = HDR.unpack(read(HDR.size))
            if kind == 0:
                continue
            if kind == 3:
                d = json.loads(read(frames))
                quiet = set(d) <= {"bed_gain"}
                self.cfg.update(d)
                if not quiet:
                    self.log(f"settings {self.cfg}")
                continue
            data = np.frombuffer(read(frames * max(1, ch) * 4), dtype=np.float32)
            if kind == 1:
                self.add_call(data, sr)
            elif kind == 2:
                self.add_crowd(data.reshape(-1, 2))
            elif kind == 5:                                # ic173: the driver keyed the radio
                self.live_start()
            elif kind == 6:
                self.live_chunk(data, sr)
            elif kind == 7:
                self.live_end()
            elif kind == 4:                                # the crowd bed (2026-10-30, #604)
                self.set_bed(data.reshape(-1, 2))
                self.log(f"crowd bed received ({len(data) // 2 / RATE:.0f} s)")


def _setting(key, default):
    """One value from the engineer's settings file (this player runs before the engineer sends anything)."""
    try:
        from .settings import PATH
        with open(PATH, encoding="utf-8-sig") as f:
            return json.load(f).get(key, default)
    except Exception:
        return default


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
