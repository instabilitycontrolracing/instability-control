"""Flag lights (2026-10-26, #236, request: room lighting that flashes with the flags - "all of them").

Built ahead of the hardware, like the bass shaker: smart lights behind the TV / around the rig follow the race -
green at the start, yellow under a local yellow, amber pulsing under a full-course caution, red for a red flag, blue
when you're being lapped (only while you drive), white on the last lap, black-and-white flashing for the chequered flag,
then back to a calm room colour.

Three kinds of lights, all talked to on your home network (no cloud account, no app in between):
  WLED       LED strips with the free WLED firmware - just the light's IP address
  Hue        a Philips Hue bridge - its IP address, then press the bridge's round button and "Pair" (once)
  Govee      Govee lights with "LAN Control" switched on in the Govee app - the light's IP address

Off until you pick a kind and an address in Settings > Lights. Never blocks the app: every send goes through one
background worker with a short timeout, and a light that doesn't answer is simply skipped.
"""
import json, socket, threading, time, urllib.request
from queue import Queue, Empty

F_CHECKERED, F_WHITE, F_GREEN, F_YELLOW, F_RED, F_BLUE = 0x1, 0x2, 0x4, 0x8, 0x10, 0x20
F_YELLOW_WAVING, F_CAUTION, F_CAUTION_WAVING = 0x100, 0x4000, 0x8000

COLOURS = {
    "idle": (255, 147, 41),       # calm warm room light
    "green": (0, 255, 40),
    "yellow": (255, 200, 0),
    "caution": (255, 150, 0),
    "red": (255, 0, 0),
    "blue": (0, 60, 255),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
}


def flag_state(flags, driving, green_age):
    """SessionFlags -> what the room shows. green_age: seconds since the green flag first appeared."""
    f = int(flags or 0)
    if f & F_CHECKERED:
        return "chequered"
    if f & F_RED:
        return "red"
    if f & (F_CAUTION | F_CAUTION_WAVING):
        return "caution"
    if f & (F_YELLOW | F_YELLOW_WAVING):
        return "yellow"
    if driving and f & F_BLUE:
        return "blue"
    if f & F_WHITE:
        return "white"
    if f & F_GREEN and green_age is not None and green_age < 8:
        return "green"
    return "idle"


class Lights:
    def __init__(self, settings, log=print):
        self.s, self.log = settings, log
        self.q = Queue(maxsize=8)
        self.state, self.sent = "idle", None
        self.green_since = None
        self.status = "off"
        self._test_until = 0.0
        self._last_flags = 0
        threading.Thread(target=self._worker, daemon=True, name="lights").start()

    def opt(self, k, d):
        return getattr(self.s, k, d)

    # ---------- called every tick by the app ----------
    def update(self, flags, driving):
        if (self.opt("lights_kind", "wled") or "").lower() == "hue":     # Hue has its own rig (hue_rig.py)
            self.status = "hue"
            return
        if not self.opt("lights_on", False) or not self.opt("lights_host", ""):
            if self.sent is not None:
                self.sent = None
            self.status = "off"
            return
        now = time.monotonic()
        f = int(flags or 0)
        if f & F_GREEN and not self._last_flags & F_GREEN:
            self.green_since = now
        self._last_flags = f
        age = (now - self.green_since) if self.green_since is not None else None
        if now < self._test_until:
            seq = ("green", "yellow", "caution", "red", "blue", "white", "idle")
            st = seq[int((now - (self._test_until - 7)) % 7)]
        else:
            st = flag_state(f, driving, age)
        self.state = st
        colour = self._colour(st, now)
        if colour != self.sent:
            self.sent = colour
            try:
                self.q.put_nowait(colour)
            except Exception:
                pass

    def _colour(self, st, now):
        bri = max(5, min(100, int(self.opt("lights_bri", 80)))) / 100.0
        if st == "chequered":                                   # black / white, twice a second
            st = "white" if int(now * 2) % 2 == 0 else "black"
        if st == "caution":                                     # amber pulsing (two levels, once a second)
            bri *= 1.0 if int(now * 2) % 2 == 0 else 0.35
        if st == "idle":
            bri *= max(0, min(100, int(self.opt("lights_idle", 30)))) / 100.0
        r, g, b = COLOURS.get(st, COLOURS["idle"])
        return (int(r * bri), int(g * bri), int(b * bri))

    def test(self):
        """7 seconds through every colour, once a second."""
        self._test_until = time.monotonic() + 7.0
        return bool(self.opt("lights_on", False) and self.opt("lights_host", ""))

    # ---------- the network side ----------
    def _worker(self):
        while True:
            try:
                c = self.q.get(timeout=1.0)
            except Empty:
                continue
            while not self.q.empty():                           # only the newest colour matters
                try:
                    c = self.q.get_nowait()
                except Empty:
                    break
            kind = (self.opt("lights_kind", "wled") or "wled").lower()
            host = (self.opt("lights_host", "") or "").strip()
            try:
                if kind == "hue":
                    self._hue(host, c)
                elif kind == "govee":
                    self._govee(host, c)
                else:
                    self._wled(host, c)
                self.status = f"on: {kind} {host}"
            except Exception as e:
                self.status = f"{kind} {host} not answering: {str(e)[:60]}"

    @staticmethod
    def _post(url, body, method="POST", timeout=0.8):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "null")

    def _wled(self, host, c):
        on = any(c)
        self._post(f"http://{host}/json/state", {"on": on, "bri": 255, "transition": 2,
                                                  "seg": [{"col": [list(c)], "fx": 0}]})

    def _hue(self, host, c):
        user = (self.opt("hue_user", "") or "").strip()
        if not user:
            raise RuntimeError("not paired yet - press the bridge button, then Pair")
        ids = [x.strip() for x in str(self.opt("hue_lights", "") or "").split(",") if x.strip()]
        if not ids:
            ids = list((self._get(f"http://{host}/api/{user}/lights") or {}).keys())
        on = any(c)
        xy = _rgb_to_xy(*c) if on else [0.3, 0.3]
        bri = max(1, min(254, int(max(c) / 255 * 254)))
        for i in ids:
            self._post(f"http://{host}/api/{user}/lights/{i}/state",
                       {"on": on, "xy": xy, "bri": bri, "transitiontime": 1}, method="PUT")

    @staticmethod
    def _get(url, timeout=0.8):
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode() or "null")

    def hue_pair(self):
        """After the bridge's round button was pressed: ask the bridge for this app's key (kept in settings)."""
        host = (self.opt("lights_host", "") or "").strip()
        if not host:
            return {"ok": False, "msg": "Type the Hue bridge's IP address first"}
        try:
            r = self._post(f"http://{host}/api", {"devicetype": "race_engineer#rig"}, timeout=3)
            item = (r or [{}])[0]
            if "success" in item:
                return {"ok": True, "user": item["success"]["username"], "msg": "Paired with the Hue bridge"}
            return {"ok": False, "msg": (item.get("error") or {}).get("description", "No answer")}
        except Exception as e:
            return {"ok": False, "msg": f"Can't reach the bridge: {str(e)[:60]}"}

    @staticmethod
    def _govee(host, c):
        on = any(c)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(0.5)
            if not on:
                msgs = [{"msg": {"cmd": "turn", "data": {"value": 0}}}]
            else:
                msgs = [{"msg": {"cmd": "turn", "data": {"value": 1}}},
                        {"msg": {"cmd": "colorwc", "data": {"color": {"r": c[0], "g": c[1], "b": c[2]}, "colorTemInKelvin": 0}}},
                        {"msg": {"cmd": "brightness", "data": {"value": 100}}}]
            for m in msgs:
                s.sendto(json.dumps(m).encode(), (host, 4003))
        finally:
            s.close()


def _rgb_to_xy(r, g, b):
    """sRGB -> CIE xy for Hue (the standard Philips formula)."""
    def lin(v):
        v = v / 255.0
        return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92
    r, g, b = lin(r), lin(g), lin(b)
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    s = X + Y + Z
    return [round(X / s, 4), round(Y / s, 4)] if s > 0 else [0.3, 0.3]
