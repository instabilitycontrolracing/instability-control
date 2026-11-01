"""Sound plays in its own small program (2026-10-29, Angelo: "If it is ever going to chop I don't want it ... completely
eliminate the chop and guarantee it won't happen again").

Why: the crowd and radio used to be played from inside the engineer. The sound card asks for the next piece of sound
every few milliseconds, and Python lets only one part of a program run at a time - so whenever the engineer was busy
(reading iRacing, the timing screen, the broadcast, tidying memory) the sound card's request waited, the piece was
late, and you heard a gap ("chop"). In the race that was 16-35 gaps a minute for the crowd and a few for the radio.

Now: a tiny separate program (this file, run as `python -m engineer.audio_proc ...`, high priority, no window) owns the
sound device. It does nothing but copy ready-made sound out of a shared memory ring - it is never busy, so it is
never late. The engineer stays ahead (the crowd about a third of a second, a radio line is handed over whole), so the
engineer being busy for a moment no longer matters.

And if the engineer ever does fall behind, the player never goes silent: it blends into a recorded crowd loop (the
"bed") until fresh sound arrives. In the pits, garage, menus and loading screens the bed plays on its own the whole time
("Can it just play a static loop for the pit lane all the way until we are in the car") - nothing made live there.

Shared memory layout: CTRL is 16 int64 counters (below), RING is frames x channels float32.
"""
import os, subprocess, sys, threading, time

import numpy as np

# CTRL slots
W, R, UNDERFLOW, DRY, STOP, MODE, LOOP_GEN, BEAT, LOOP_GAIN, READY, CUT, BUSY_OUT, GAIN, ERR = range(14)
NCTRL = 16
SCALE = 1_000_000                     # gains are stored as millionths
NO_WINDOW, HIGH_PRIORITY = 0x08000000, 0x00000080
HIGH_FLAG = r"C:\SimRacing\Tools\deck\audio_high_priority.on"
SPIN_LIMIT = 0.5      # cores; a player above this for SPIN_SECONDS is stuck (seen 30 Oct: 2.4 cores after a device reset)
SPIN_SECONDS = 8


# =============================================================================== engineer side
class ProcOut:
    """Sound out through the separate player. write() blocks of float32 (frames x channels)."""

    def __init__(self, rate, channels, device=None, seconds=8.0, name="sound", loop=None, log=print, latency=0.4):
        from multiprocessing import shared_memory
        self.rate, self.ch, self.log, self.name = int(rate), int(channels), log, name
        self.frames = int(rate * seconds)
        self._ctrl_shm = shared_memory.SharedMemory(create=True, size=NCTRL * 8)
        self._ring_shm = shared_memory.SharedMemory(create=True, size=self.frames * self.ch * 4)
        self.ctrl = np.ndarray((NCTRL,), np.int64, self._ctrl_shm.buf); self.ctrl[:] = 0
        self.ring = np.ndarray((self.frames, self.ch), np.float32, self._ring_shm.buf); self.ring[:] = 0
        self.ctrl[GAIN] = SCALE
        self._loop_dir = os.path.join(os.environ.get("TEMP", "/tmp"), "ic_sound")
        os.makedirs(self._loop_dir, exist_ok=True)
        self._loop_path = os.path.join(self._loop_dir, f"{name}_{os.getpid()}_bed.npy")
        if loop is not None:
            self.set_loop(loop)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        exe = sys.executable
        args = [exe, "-m", "engineer.audio_proc", self._ctrl_shm.name, self._ring_shm.name, str(self.ch), str(self.rate),
                "" if device is None else str(device), str(self.frames), str(os.getpid()), self._loop_path, str(latency), name]
        flags = (NO_WINDOW | HIGH_PRIORITY) if os.name == "nt" else 0
        self.proc = subprocess.Popen(args, cwd=root, creationflags=flags, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 8.0:                     # the player says when the device is open
            if self.ctrl[READY] or self.ctrl[ERR] or self.proc.poll() is not None:
                break
            time.sleep(0.02)
        if not self.ctrl[READY]:
            err = int(self.ctrl[ERR])
            self.close()
            raise RuntimeError(f"{name} player did not start (code {err})")

    # ---- feeding
    def ahead(self):
        """Frames written but not yet played."""
        return int(self.ctrl[W] - self.ctrl[R])

    def room(self):
        return self.frames - self.ahead()

    def write(self, block):
        n = len(block)
        if n == 0 or n > self.room():
            return False
        w = int(self.ctrl[W]); p = w % self.frames; k = min(n, self.frames - p)
        self.ring[p:p + k] = block[:k]
        if n > k:
            self.ring[:n - k] = block[k:]
        self.ctrl[W] = w + n                                  # published last: the player only reads up to W
        return True

    def written(self):
        return int(self.ctrl[W])

    def played(self):
        return int(self.ctrl[R])

    def cut(self):
        """Drop whatever is queued (with a short fade in the player)."""
        self.ctrl[CUT] += 1

    # ---- the bed
    def set_loop(self, loop):
        """A seamless loop (frames x channels float32) the player falls back on / plays in static mode."""
        try:
            tmp = self._loop_path + ".tmp.npy"
            np.save(tmp, np.ascontiguousarray(loop, np.float32))
            os.replace(tmp, self._loop_path)
            self.ctrl[LOOP_GEN] += 1
        except Exception as e:
            self.log(f"[{self.name}] bed: {e!r}")

    def set_static(self, on):
        self.ctrl[MODE] = 1 if on else 0

    def set_loop_gain(self, g):
        self.ctrl[LOOP_GAIN] = int(max(0.0, min(1.0, float(g))) * SCALE)

    def set_gain(self, g):
        self.ctrl[GAIN] = int(max(0.0, min(1.0, float(g))) * SCALE)

    def gaps(self):
        """(device underflows, times the engineer fell behind) since the start."""
        return int(self.ctrl[UNDERFLOW]), int(self.ctrl[DRY])

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        try:
            self.ctrl[STOP] = 1
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            try: self.proc.kill()
            except Exception: pass
        for s in (getattr(self, "_ring_shm", None), getattr(self, "_ctrl_shm", None)):
            try:
                s.close(); s.unlink()
            except Exception:
                pass
        try:
            os.remove(self._loop_path)
        except Exception:
            pass


# =============================================================================== Windows: keep the sound on time
# 2026-10-30 (#604, research): on Windows 11 a program with no window counts as "background" - Windows may run it on the
# slow cores at reduced speed (power throttling / EcoQoS) and ignores its timer requests. The sound programs opt out,
# run at high priority, and register their sound thread with the Multimedia Class Scheduler as "Pro Audio" (the same
# thing DAWs and Voicemeeter do), so iRacing in VR + OBS + the encode can't keep them waiting. Each step is optional:
# whatever Windows refuses is simply skipped.
def boost_process():
    """High priority, no power throttling, 1 ms timer. Returns what was done (for the log)."""
    if os.name != "nt":
        return "not Windows"
    done = []
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)      # own instance: typed handles (64-bit safe)
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.SetPriorityClass.restype = wintypes.BOOL
        k.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.SetProcessInformation.restype = wintypes.BOOL
        h = k.GetCurrentProcess()
        # 2026-10-30 evening (#629): High priority class OFF by default. Since ic160 made it work, VR frames reached the
        # headset late far more often (late frames 54-67% -> 81-90%). The sound thread keeps MMCSS "Pro Audio" (ThreadBoost),
        # which is what protects the audio. The old behaviour comes back with C:\SimRacing\Tools\deck\audio_high_priority.on
        if os.path.exists(HIGH_FLAG) and k.SetPriorityClass(h, HIGH_PRIORITY):
            done.append("high priority")
        else:
            done.append("normal priority")

        class PPTS(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
        st = PPTS(1, 0x1 | 0x4, 0)            # EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION, state 0 = never throttle
        if k.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st)):    # ProcessPowerThrottling
            done.append("no power throttling")
        else:
            done.append(f"(throttling opt-out failed: {ctypes.get_last_error()})")
        if ctypes.windll.winmm.timeBeginPeriod(1) == 0:
            done.append("1 ms timer")
    except Exception as e:
        done.append(f"({e!r})")
    return ", ".join(done) or "nothing"


class ThreadBoost:
    """Registers the thread it is first called on (the sound card's callback thread) as MMCSS "Pro Audio", once.
    (2026-10-30: the earlier call sat on the program's main thread, which only sleeps - the callback never got it.)"""

    def __init__(self):
        self.tid, self.handle = None, None

    def once(self):
        tid = threading.get_ident()
        if tid == self.tid:
            return
        self.tid = tid
        if os.name != "nt":
            return
        try:
            import ctypes
            av = ctypes.windll.avrt
            av.AvSetMmThreadCharacteristicsW.restype = ctypes.c_void_p
            idx = ctypes.c_ulong(0)
            self.handle = av.AvSetMmThreadCharacteristicsW("Pro Audio", ctypes.byref(idx))
            if self.handle:
                av.AvSetMmThreadPriority(ctypes.c_void_p(self.handle), 1)          # AVRT_PRIORITY_HIGH
        except Exception:
            pass


# =============================================================================== the player program
class Player:
    """Runs in the player program. Also used directly by the tests (render without a device)."""
    XF_S = 1.0          # static <-> live blend
    DRY_S = 0.03        # quick blend into the bed when the engineer falls behind
    REFILL_S = 0.25     # ...and the live sound only comes back once this much is queued (no flutter between the two)
    BACK_S = 0.6        # blend from the bed back to the live sound (2026-10-31: 0.3 -> 0.6, the hand-back was audible)
    UNDER = 0.3         # 2026-10-31 (#623/#624, "the crowd chops"): the bed stays mixed in UNDER the live crowd at this
                        # level, so falling back on it (or coming back) is a small level change, not a switch of sound

    def __init__(self, ctrl, ring, rate, loop_path="", name=""):
        self.ctrl, self.ring, self.rate, self.name = ctrl, ring, rate, name
        self.frames, self.ch = ring.shape
        self.loop, self.lpos, self.loop_path, self.loop_gen = None, 0, loop_path, -1
        self.g_feed, self.g_bed, self.g_out = 1.0, 0.0, 1.0
        self.cut_seen = int(ctrl[CUT])
        self.dry = False                   # behind: the bed plays until the engineer is REFILL_S ahead again
        self._f = None
        self._mk(4096)

    def _mk(self, n):
        """Work buffers made once (2026-10-30: the callback allocated a few arrays per block before)."""
        self._nmax = n
        # ramps are full width (frames x channels): a (frames x 1) ramp broadcast over the channels made numpy
        # allocate a scratch buffer on every multiply
        self._ar = np.repeat(np.arange(n, dtype=np.float32)[:, None], self.ch, axis=1)
        self._r = [np.empty((n, self.ch), np.float32) for _ in range(3)]
        self._seg = np.empty((n, self.ch), np.float32)

    def reload_loop(self):
        gen = int(self.ctrl[LOOP_GEN])
        if gen == self.loop_gen:
            return
        self.loop_gen = gen
        try:
            lp = np.load(self.loop_path)
            if lp.ndim == 1:
                lp = lp[:, None]
            if lp.shape[1] != self.ch:
                lp = np.repeat(lp[:, :1], self.ch, axis=1)
            self.loop = np.ascontiguousarray(lp, np.float32) if len(lp) > 1000 else None
            self.lpos = 0
        except Exception:
            pass

    def _ramp(self, g0, g1, n, slot=0):
        """g0 -> g1 over n frames (end excluded), in a buffer made once."""
        if g0 == g1:
            return float(g0)       # a plain float: a numpy float64 here made numpy work in float64 (a temporary copy)
        r = self._r[slot][:n]
        np.multiply(self._ar[:n], np.float32((g1 - g0) / n), out=r)
        r += np.float32(g0)
        return r

    def render(self, out):
        n = len(out)
        if n > self._nmax:
            self._mk(n)
        if self._f is None or len(self._f) < n:
            self._f = np.zeros((n, self.ch), np.float32)
        f = self._f[:n]
        c = self.ctrl
        w, r = int(c[W]), int(c[R])
        cut = int(c[CUT])
        if cut != self.cut_seen:                               # radio stopped: fade what's playing, drop the rest
            self.cut_seen = cut
            avail = min(n, w - r)
            p = r % self.frames; k = min(avail, self.frames - p)
            f[:] = 0
            f[:k] = self.ring[p:p + k]
            if avail > k:
                f[k:avail] = self.ring[:avail - k]
            f *= self._ramp(1.0, 0.0, n)
            np.multiply(f, self.g_out, out=out)
            c[R] = w
            return
        avail = w - r
        static = c[MODE] == 1
        loop = self.loop                                       # one look: reload_loop may swap it meanwhile
        has_loop = loop is not None
        if self.dry and (static or not has_loop or avail >= int(self.rate * self.REFILL_S)):
            self.dry = False                                   # caught up: the live sound blends back in
        take = 0 if (self.dry and not static) else min(n, max(0, avail))
        p = r % self.frames; k = min(take, self.frames - p)
        f[:k] = self.ring[p:p + k]
        if take > k:
            f[k:take] = self.ring[:take - k]
        f[take:] = 0
        c[R] = r + take
        short = take < n
        if short and not static and has_loop and not self.dry:
            self.dry = True                                    # the engineer fell behind - the bed covers it
            c[DRY] += 1                                        # counted once per time, not per block
        # targets
        if static:
            tf, tb = 0.0, 1.0
        elif self.dry:
            tf, tb = 0.0, 1.0                                  # the bed alone until the feed is well ahead again
        else:
            tf, tb = 1.0, (self.UNDER if self.name == "crowd" else 0.0)   # the radio never gets a bed under it
        if static:
            speed_f = n / (self.rate * self.XF_S)
        elif self.dry:
            speed_f = n / (self.rate * self.DRY_S)
        else:
            speed_f = n / (self.rate * self.BACK_S)
        speed_b = n / (self.rate * (self.DRY_S if (self.dry and not static) else self.XF_S))
        g0f, g0b = self.g_feed, self.g_bed
        g1f = min(tf, g0f + speed_f) if tf > g0f else max(tf, g0f - speed_f)
        g1b = min(tb, g0b + speed_b) if tb > g0b else max(tb, g0b - n / (self.rate * 0.4))
        self.g_feed, self.g_bed = g1f, g1b
        go0 = self.g_out; go1 = c[GAIN] / SCALE
        go1 = go0 + (go1 - go0) * min(1.0, n / (self.rate * 0.1))
        self.g_out = go1
        if g0f != 1.0 or g1f != 1.0:
            f *= self._ramp(g0f, g1f, n)
        if has_loop:
            lg = c[LOOP_GAIN] / SCALE
            L = len(loop)
            if self.lpos >= L:
                self.lpos = 0
            if g0b > 0 or g1b > 0:
                pos = self.lpos; i = 0
                seg = self._seg[:n]
                while i < n:
                    kk = min(n - i, L - pos)
                    seg[i:i + kk] = loop[pos:pos + kk]
                    i += kk; pos = (pos + kk) % L
                seg *= self._ramp(g0b * lg, g1b * lg, n, 1)
                f += seg
            self.lpos = (self.lpos + n) % L                    # the bed keeps time even when silent: seamless returns
        np.multiply(f, self._ramp(go0, go1, n, 2), out=out)
        np.clip(out, -1.0, 1.0, out=out)


def _parent_alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0); return True
        except OSError:
            return False
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
    if not h:
        return False
    try:
        return k.WaitForSingleObject(h, 0) != 0           # 0 = it has exited
    finally:
        k.CloseHandle(h)


def main(argv):
    from multiprocessing import shared_memory
    ctrl_name, ring_name, ch, rate, device, frames, ppid, loop_path, latency, name = argv[:10]
    ch, rate, frames, ppid, latency = int(ch), int(rate), int(frames), int(ppid), float(latency)
    cs = shared_memory.SharedMemory(name=ctrl_name)
    rs = shared_memory.SharedMemory(name=ring_name)
    ctrl = np.ndarray((NCTRL,), np.int64, cs.buf)
    ring = np.ndarray((frames, ch), np.float32, rs.buf)
    pl = Player(ctrl, ring, rate, loop_path, name)
    pl.reload_loop()
    try:
        import gc
        gc.disable()                                       # nothing here makes garbage worth a pause
        boost_process()                                    # high priority, no power throttling, 1 ms timer
    except Exception:
        pass
    mm = ThreadBoost()
    try:
        import sounddevice as sd
        dev = None
        if device not in ("", "None"):
            dev = int(device) if device.lstrip("-").isdigit() else device

        def cb(outdata, n, t, status):
            mm.once()                                      # this thread: MMCSS "Pro Audio"
            if status and status.output_underflow:
                ctrl[UNDERFLOW] += 1
            try:
                pl.render(outdata)
            except Exception:
                outdata[:] = 0
            ctrl[BEAT] += 1

        stream = sd.OutputStream(samplerate=rate, channels=ch, dtype="float32", device=dev, callback=cb,
                                 blocksize=256 if name == "cues" else 1024, latency=latency)   # ic175: cues = 5 ms blocks
        stream.start()
    except Exception:
        ctrl[ERR] = 2
        return 2
    ctrl[READY] = 1
    n = 0
    spin, cpu0, wall0 = 0, time.process_time(), time.monotonic()
    rc = 0
    while not ctrl[STOP]:
        time.sleep(0.05)
        pl.reload_loop()
        n += 1
        if n % 20 == 0:
            if not _parent_alive(ppid):                        # the engineer is gone: so are we
                break
            cpu1, wall1 = time.process_time(), time.monotonic()    # stuck-spinning guard: quit, the engineer restarts us
            use = (cpu1 - cpu0) / max(0.001, wall1 - wall0)
            cpu0, wall0 = cpu1, wall1
            spin = spin + 1 if use > SPIN_LIMIT else 0
            if spin >= SPIN_SECONDS:
                ctrl[ERR] = 3
                rc = 3
                break
    try:
        stream.stop(); stream.close()
    except Exception:
        pass
    del ctrl, ring, pl
    try:
        cs.close(); rs.close()
    except Exception:
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
