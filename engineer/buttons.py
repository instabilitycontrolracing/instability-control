"""Reads wheel / button box buttons in the background (works while iRacing has focus).

Windows: polls the Windows game-controller API (winmm joyGetPosEx) - no window needed.
Other systems (testing only): pygame. pygame is never imported on Windows.

#322 (2026-10-27): the "[buttons] video system not initialized" lines in the 2026-10-24 22:18-22:20 log came from the
build before the winmm reader, when pygame read the wheel on Windows too: pygame.event.get() needs SDL's video system,
and when that wasn't up the reader thread logged the error and stopped - no button presses at all until a restart.
Windows now polls winmm only. The binding itself was never lost (engineer_settings.json kept it); a binding that
names "X" now also matches "X #2" (and the other way round) when only one such device is plugged in, and the
controller list is logged at start and whenever it changes.
"""
import ctypes, os, re, sys, threading, time


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
    def __init__(self, on_press, log=print, on_devices=None):
        """on_press(device_name, button_index, down: bool); on_devices(names) when the controller list changes"""
        self.on_press, self.log = on_press, log
        self.capture = None   # callback for "press the button you want" in the window
        self.ok = False
        self.names = []
        self.on_devices = on_devices   # callback(names) whenever the list of controllers changes (and once at start)
        self._logged_names = None
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
            self.log(f"[buttons] press of {name} button {btn + 1} failed: {e!r}")

    def _set_names(self, names):
        self.names = list(names)
        if self.names == self._logged_names:
            return
        self._logged_names = list(self.names)
        self.log("[buttons] controllers: " + (", ".join(self.names) if self.names else "none found"))
        cb = self.on_devices
        if cb:
            try:
                cb(list(self.names))
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
        devs, last_scan, state, names = {}, 0, {}, {}
        while True:
            now = time.time()
            if now - last_scan > 3:  # pick up a wheel or button box plugged in later
                last_scan = now
                was = set(devs)
                devs.clear()
                for i in range(min(n_dev, 16)):
                    info = _JOYINFOEX(ctypes.sizeof(_JOYINFOEX), JOY_RETURNBUTTONS)
                    if winmm.joyGetPosEx(i, ctypes.byref(info)) != 0:
                        names.pop(i, None)
                        continue
                    # 2026-10-29 (efficiency): a device that stayed plugged in keeps its name - the driver query and the
                    # registry lookup only run for a newly seen one (they ran for every device every 3 s)
                    if i not in was or i not in names:
                        caps = _JOYCAPSW()
                        name = f"Controller {i + 1}"
                        if winmm.joyGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                            name = _oem_name(caps.wMid, caps.wPid) or caps.szPname.strip() or name
                        names[i] = name
                    devs[i] = names[i]
                # same name twice (two identical boxes): number them
                seen = {}
                for i in sorted(devs):
                    n = devs[i]; seen[n] = seen.get(n, 0) + 1
                    if seen[n] > 1:
                        devs[i] = f"{n} #{seen[n]}"
                self._set_names(devs.values())
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
        last_err = None
        while True:
            try:
                sticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
                self._set_names(j.get_name() for j in sticks)
                for ev in pygame.event.get():
                    if ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                        j = next((s for s in sticks if s.get_instance_id() == ev.instance_id), None)
                        self._fire(j.get_name() if j else "?", ev.button, ev.type == pygame.JOYBUTTONDOWN)
            except Exception as e:
                if repr(e) != last_err:             # say it once, keep trying (it used to die silently)
                    last_err = repr(e)
                    self.log(f"[buttons] controller read problem: {e!r}")
                time.sleep(1)
            time.sleep(0.02)


_NUM = re.compile(r"\s+#\d+$")


def base_name(name):
    """'Thrustmaster Advanced Mode Racer #2' -> 'Thrustmaster Advanced Mode Racer'."""
    return _NUM.sub("", str(name or "")).strip()


def matches(binding, name, button, names=None):
    """Does a press of `button` on device `name` belong to `binding`?

    Exact device name first. Otherwise "X" and "X #n" count as the same device when exactly one device of that
    kind is plugged in (`names` = the controllers connected now), so a box that came back with a number after a
    restart, or lost it, still works. With two identical devices only the exact name matches."""
    if not binding or binding.get("button") != button:
        return False
    dev = binding.get("device")
    if dev == name:
        return True
    b = base_name(dev)
    if not b or b != base_name(name) or names is None:
        return False
    return sum(1 for n in names if base_name(n) == b) == 1


def connected(binding, names):
    """Is the binding's device plugged in now (same rules as matches)?"""
    if not binding:
        return True
    dev = binding.get("device")
    if dev in names:
        return True
    b = base_name(dev)
    return sum(1 for n in names if base_name(n) == b) == 1


def describe(binding):
    if not binding:
        return "Not set"
    return f"{binding['device']}  -  button {binding['button'] + 1}"
