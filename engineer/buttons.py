"""Reads wheel / button box buttons in the background (works while iRacing has focus).

Windows: polls the Windows game-controller API (winmm joyGetPosEx) - no window needed.
Other systems (testing only): pygame.
"""
import ctypes, os, sys, threading, time


class _JOYINFOEX(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32), ("dwXpos", ctypes.c_uint32),
                ("dwYpos", ctypes.c_uint32), ("dwZpos", ctypes.c_uint32), ("dwRpos", ctypes.c_uint32),
                ("dwUpos", ctypes.c_uint32), ("dwVpos", ctypes.c_uint32), ("dwButtons", ctypes.c_uint32),
                ("dwButtonNumber", ctypes.c_uint32), ("dwPOV", ctypes.c_uint32),
                ("dwReserved1", ctypes.c_uint32), ("dwReserved2", ctypes.c_uint32)]


class _JOYCAPSW(ctypes.Structure):
    _fields_ = [("wMid", ctypes.c_uint16), ("wPid", ctypes.c_uint16), ("szPname", ctypes.c_wchar * 32),
                ("wXmin", ctypes.c_uint32), ("wXmax", ctypes.c_uint32), ("wYmin", ctypes.c_uint32),
                ("wYmax", ctypes.c_uint32), ("wZmin", ctypes.c_uint32), ("wZmax", ctypes.c_uint32),
                ("wNumButtons", ctypes.c_uint32), ("wPeriodMin", ctypes.c_uint32), ("wPeriodMax", ctypes.c_uint32),
                ("wRmin", ctypes.c_uint32), ("wRmax", ctypes.c_uint32), ("wUmin", ctypes.c_uint32),
                ("wUmax", ctypes.c_uint32), ("wVmin", ctypes.c_uint32), ("wVmax", ctypes.c_uint32),
                ("wCaps", ctypes.c_uint32), ("wMaxAxes", ctypes.c_uint32), ("wNumAxes", ctypes.c_uint32),
                ("wMaxButtons", ctypes.c_uint32), ("szRegKey", ctypes.c_wchar * 32),
                ("szOEMVxD", ctypes.c_wchar * 260)]


JOY_RETURNBUTTONS = 0x80


def _oem_name(vid, pid):
    """The real product name ("Thrustmaster ...", "AJAZZ ...") from the Windows game controller list."""
    try:
        import winreg
        k = rf"System\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM\VID_{vid:04X}&PID_{pid:04X}"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, k) as h:
                    return str(winreg.QueryValueEx(h, "OEMName")[0]).strip()
            except OSError:
                continue
    except Exception:
        pass
    return None


class Buttons:
    def __init__(self, on_press, log=print):
        """on_press(device_name, button_index, down: bool)"""
        self.on_press, self.log = on_press, log
        self.capture = None   # callback for "press the button you want" in the window
        self.ok = False
        self.names = []
        target = self._loop_windows if sys.platform == "win32" else self._loop_pygame
        threading.Thread(target=target, daemon=True).start()

    def _fire(self, name, btn, down):
        if down and self.capture:
            cb, self.capture = self.capture, None
            cb(name, btn)
            return
        try:
            self.on_press(name, btn, down)
        except Exception as e:
            self.log(f"[buttons] {e!r}")

    # ---------- Windows ----------
    def _loop_windows(self):
        try:
            winmm = ctypes.WinDLL("winmm")
            n_dev = winmm.joyGetNumDevs()
        except Exception as e:
            self.log(f"[buttons] no controller support: {e}")
            return
        self.ok = True
        devs, last_scan, state = {}, 0, {}
        while True:
            now = time.time()
            if now - last_scan > 3:  # pick up a wheel or button box plugged in later
                last_scan = now
                devs.clear()
                for i in range(min(n_dev, 16)):
                    info = _JOYINFOEX(ctypes.sizeof(_JOYINFOEX), JOY_RETURNBUTTONS)
                    if winmm.joyGetPosEx(i, ctypes.byref(info)) != 0:
                        continue
                    caps = _JOYCAPSW()
                    name = f"Controller {i + 1}"
                    if winmm.joyGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                        name = _oem_name(caps.wMid, caps.wPid) or caps.szPname.strip() or name
                    devs[i] = name
                # same name twice (two identical boxes): number them
                seen = {}
                for i in sorted(devs):
                    n = devs[i]; seen[n] = seen.get(n, 0) + 1
                    if seen[n] > 1:
                        devs[i] = f"{n} #{seen[n]}"
                self.names = list(devs.values())
            for i, name in list(devs.items()):
                info = _JOYINFOEX(ctypes.sizeof(_JOYINFOEX), JOY_RETURNBUTTONS)
                if winmm.joyGetPosEx(i, ctypes.byref(info)) != 0:
                    continue
                b, prev = info.dwButtons, state.get(i)
                if prev is not None and b != prev:
                    for k in range(32):
                        m = 1 << k
                        if (b & m) != (prev & m):
                            self._fire(name, k, bool(b & m))
                state[i] = b
            time.sleep(0.015)

    # ---------- other systems (testing) ----------
    def _loop_pygame(self):
        try:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
            import pygame
            pygame.display.init(); pygame.joystick.init()
        except Exception as e:
            self.log(f"[buttons] no controller support: {e}")
            return
        self.ok = True
        while True:
            try:
                sticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
                self.names = [j.get_name() for j in sticks]
                for ev in pygame.event.get():
                    if ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                        j = next((s for s in sticks if s.get_instance_id() == ev.instance_id), None)
                        self._fire(j.get_name() if j else "?", ev.button, ev.type == pygame.JOYBUTTONDOWN)
            except Exception:
                time.sleep(1)
            time.sleep(0.02)


def matches(binding, name, button):
    return bool(binding) and binding.get("device") == name and binding.get("button") == button


def describe(binding):
    if not binding:
        return "Not set"
    return f"{binding['device']}  -  button {binding['button'] + 1}"
