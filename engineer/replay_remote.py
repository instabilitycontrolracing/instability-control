"""Replay remote (2026-10-28, #499, Angelo: "should I use the controller to wire up replay scrolling controls in sim").

Any Xbox-style controller (his reads as "Xbox 360 Controller for Windows") becomes a replay remote, read through XInput
(all buttons, both triggers and the D-pad) and sent to iRacing as its own replay commands (the SDK's broadcast
messages - no key presses, no extra software):

  A        play / pause                 B      back to normal speed
  D-pad <  rewind  (press again: 2x 4x 8x 16x)
  D-pad >  fast forward (2x 4x 8x 16x)
  D-pad ^  previous lap                 D-pad v  next lap
  LB / RB  previous / next incident     LT (hold)  slow motion
  Y        jump to live (the end)       View/Back  jump to the start of the session
  X        flag this moment for the highlight reel (Grandstand's highlight markers / OBS clip)
  Right stick click (R3)        MusicBee play / pause - ALWAYS, also while driving and without iRacing
                                (2026-10-29, Angelo: "one of the unused buttons to be the play/pause button for musicbee
                                at all times"); only MusicBee is told, never the other players

Only while a replay is playing or you're out of the car - never while you're driving (a stray press can't touch your
race). Off with ENGINEER_REPLAY_REMOTE=0.
"""
import ctypes, glob, json, os, subprocess, threading, time, urllib.request

A, B, X, Y = 0x1000, 0x2000, 0x4000, 0x8000
UP, DOWN, LEFT, RIGHT = 0x0001, 0x0002, 0x0004, 0x0008
BACK, START, LB, RB = 0x0020, 0x0010, 0x0100, 0x0200
L3, R3 = 0x0040, 0x0080
MUSIC = R3          # 2026-10-29: right stick click (Start is taken by Steam's desktop controller mode)
SPEEDS = [2, 4, 8, 16]
# iRacing replay search modes (irsdk_RpySrchMode)
TO_START, TO_END, PREV_LAP, NEXT_LAP, PREV_INC, NEXT_INC = 0, 1, 4, 5, 8, 9


class _GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_uint16), ("bLeftTrigger", ctypes.c_uint8), ("bRightTrigger", ctypes.c_uint8),
                ("sThumbLX", ctypes.c_int16), ("sThumbLY", ctypes.c_int16), ("sThumbRX", ctypes.c_int16), ("sThumbRY", ctypes.c_int16)]


class _STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint32), ("Gamepad", _GAMEPAD)]


def _xinput():
    for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            return getattr(ctypes.windll, dll)
        except Exception:
            continue
    return None


class ReplayRemote:
    def __init__(self, ir, log=print, flag_url="http://127.0.0.1:8790/api/highlight"):
        """ir = a connected pyirsdk IRSDK (reads IsReplayPlaying / IsOnTrack / ReplayPlaySpeed; sends the commands)."""
        self.ir, self.log, self.flag_url = ir, log, flag_url
        self.running = True
        self._slow = False
        self._dir = 0            # -1 rewinding, +1 fast-forwarding, 0 normal
        self._step = 0
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._loop_dinput, daemon=True, name="music-dinput").start()

    def stop(self):
        self.running = False

    # ---- what the sim is doing
    def _g(self, k, d=None):
        try:
            v = self.ir[k]
            return d if v is None else v
        except Exception:
            return d

    def allowed(self):
        """Never while driving: a replay must be playing, or you must be out of the car."""
        if not (getattr(self.ir, "is_initialized", False) and getattr(self.ir, "is_connected", False)):
            return False
        return bool(self._g("IsReplayPlaying", False)) or not bool(self._g("IsOnTrack", False))

    # ---- commands
    def speed(self, s, slow=False):
        self.ir.replay_set_play_speed(int(s), bool(slow))

    def search(self, mode):
        self.ir.replay_search(mode)

    def press(self, btn):
        if btn == A:
            playing = int(self._g("ReplayPlaySpeed", 1) or 0) != 0
            self.speed(0 if playing else 1); self._dir = self._step = 0
            self.log("[replay remote] " + ("pause" if playing else "play"))
        elif btn == B:
            self.speed(1); self._dir = self._step = 0
        elif btn in (LEFT, RIGHT):
            d = -1 if btn == LEFT else 1
            self._step = self._step + 1 if self._dir == d else 0
            self._dir = d
            s = SPEEDS[min(self._step, len(SPEEDS) - 1)]
            self.speed(d * s)
            self.log(f"[replay remote] {'rewind' if d < 0 else 'fast forward'} {s}x")
        elif btn == UP:
            self.search(PREV_LAP)
        elif btn == DOWN:
            self.search(NEXT_LAP)
        elif btn == LB:
            self.search(PREV_INC); self.log("[replay remote] previous incident")
        elif btn == RB:
            self.search(NEXT_INC); self.log("[replay remote] next incident")
        elif btn == Y:
            self.search(TO_END); self.speed(1); self._dir = self._step = 0
        elif btn == BACK:
            self.search(TO_START); self.speed(1); self._dir = self._step = 0
        elif btn == X:
            self.flag()

    def music(self):
        """MusicBee play / pause through MusicBee's own command line (/PlayPause): only MusicBee reacts (a media key
        would also pause a browser video). Nothing happens if MusicBee isn't installed / running."""
        exe = getattr(self, "_mb", None)
        if exe is None:
            cands = [os.path.join(os.environ.get(v, ""), "MusicBee", "MusicBee.exe") for v in ("ProgramFiles(x86)", "ProgramFiles")]
            cands += glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "MusicBee", "MusicBee.exe"))
            exe = self._mb = next((c for c in cands if c and os.path.exists(c)), "")
        if not exe:
            self.log("[replay remote] MusicBee not found")
            return
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MusicBee.exe", "/NH"], capture_output=True, text=True,
                                 timeout=3, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            if "MusicBee.exe" not in out:
                return                       # not open: don't start it from a button press mid-race
            subprocess.Popen([exe, "/PlayPause"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.log("[replay remote] music play / pause")
        except Exception as e:
            self.log(f"[replay remote] music: {e!r}"[:160])

    def flag(self):
        """Ask Grandstand to write a highlight marker now (its control app API on this PC)."""
        def go():
            try:
                req = urllib.request.Request(self.flag_url, data=json.dumps({"label": "Flagged moment"}).encode(),
                                             headers={"Content-Type": "application/json", "X-Grandstand": "1"}, method="POST")
                urllib.request.urlopen(req, timeout=2).read()
                self.log("[replay remote] moment flagged")
            except Exception as e:
                self.log(f"[replay remote] couldn't flag the moment (is Grandstand running?): {e!r}"[:160])
        threading.Thread(target=go, daemon=True).start()

    # ---- 2026-10-29 (Angelo: "make it just work in both modes"): the same pad in its OTHER mode shows up as a plain
    # "Gamepad" (USB id 0079:181c), not an Xbox controller - XInput can't see it. Read through Windows' game controller
    # list instead: there the right stick click is button 15 (index 14). Music only - the replay buttons stay XInput.
    DINPUT_PADS = {(0x0079, 0x181C): 14}

    def _loop_dinput(self):
        try:
            from .buttons import _JOYINFOEX, _JOYCAPSW, JOY_RETURNBUTTONS
            w = ctypes.windll.winmm
        except Exception:
            return
        pads, next_scan, prev = {}, 0.0, {}
        while self.running:
            time.sleep(1 / 60)
            now = time.monotonic()
            if now >= next_scan:                         # which slots hold that pad (re-checked every 5 s: plug / unplug)
                next_scan = now + 5.0
                pads = {}
                for i in range(16):
                    caps = _JOYCAPSW()
                    if w.joyGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                        bit = self.DINPUT_PADS.get((caps.wMid, caps.wPid))
                        if bit is not None:
                            pads[i] = bit
            for i, bit in pads.items():
                info = _JOYINFOEX(); info.dwSize = ctypes.sizeof(info); info.dwFlags = JOY_RETURNBUTTONS
                if w.joyGetPosEx(i, ctypes.byref(info)) != 0:
                    prev.pop(i, None)
                    continue
                down = bool(info.dwButtons >> bit & 1)
                if down and not prev.get(i, True):
                    threading.Thread(target=self.music, daemon=True).start()
                prev[i] = down

    # ---- the loop
    def _loop(self):
        xi = _xinput()
        if xi is None:
            self.log("[replay remote] no XInput on this PC")
            return
        prev = {}
        told = False
        # 2026-10-29 (efficiency): Microsoft: "for performance reasons, don't call XInputGetState for an 'empty' user
        # slot every frame ... space out checks for new controllers every few seconds". A connected pad is still read
        # 60 times a second; the empty slots only every 2 s (a pad plugged in is picked up within 2 s).
        empty_next = {}
        while self.running:
            time.sleep(1 / 60)
            now = time.monotonic()
            for pad in range(4):
                if pad not in prev and now < empty_next.get(pad, 0.0):
                    continue
                st = _STATE()
                if xi.XInputGetState(pad, ctypes.byref(st)) != 0:
                    prev.pop(pad, None)
                    empty_next[pad] = now + 2.0
                    continue
                if not told:
                    told = True
                    self.log("[replay remote] controller ready: A play/pause, D-pad rewind/forward, LB/RB incidents, "
                             "LT slow motion, Y live, X flag the moment")
                gp = st.Gamepad
                b, p = gp.wButtons, prev.get(pad, (gp.wButtons, 0))[0]
                lt = gp.bLeftTrigger > 120
                prev[pad] = (b, lt)
                try:
                    # only a new press or a trigger change can do anything: ask iRacing only then (same result)
                    if not ((b & ~p) or lt != self._slow):
                        continue
                    if (b & MUSIC) and not (p & MUSIC):     # music: always (driving or not, iRacing or not)
                        threading.Thread(target=self.music, daemon=True).start()
                    if not self.allowed():
                        continue
                    for m in (A, B, X, Y, UP, DOWN, LEFT, RIGHT, BACK, LB, RB):
                        if (b & m) and not (p & m):
                            self.press(m)
                    if lt != self._slow:
                        self._slow = lt
                        self.speed(1, slow=True) if lt else self.speed(1)
                        if lt:
                            self._dir = self._step = 0
                except Exception as e:
                    self.log(f"[replay remote] {e!r}"[:160])


def start(ir, log=print):
    if os.environ.get("ENGINEER_REPLAY_REMOTE", "1") == "0" or os.name != "nt":
        return None
    return ReplayRemote(ir, log=log)
