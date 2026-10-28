"""The Philips Hue rig (2026-10-26, #239 H1 / #240 H2).

"I have Philips Hue lights - two lamps, one on either side of me, and a strip light below my desk ... include an option
in the settings of our app to sync and do that stuff."

Each light gets a place (left lamp, right lamp, desk strip) and a job:
  flags     the race flags only (green start, yellow, caution, red, blue, white last lap, chequered), calm otherwise
  picture   follows the picture on the main screen, like Ambilight: the left lamp takes the left edge's colour, the
            right lamp the right edge, the desk strip the bottom of the screen
  both      the picture, and a flag takes over the moment one is out
  off       left alone

The bridge is found on the home network, paired once (press the round button on the bridge, then "Pair" in the app),
and the lights go back to exactly how they were when the sync is switched off or the app closes.
"""
import json, threading, time, urllib.request

from .lights import COLOURS, flag_state, _rgb_to_xy

ROLES = ("left", "right", "desk")


def _http(url, body=None, method=None, timeout=1.5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("PUT" if body is not None else "GET"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "null")


def find_bridge():
    """-> IP address of the Hue bridge on this network, or "". Philips' discovery page first, then the PC's own
    neighbour table (Hue bridges' network cards start EC:B5:FA / 00:17:88)."""
    try:
        with urllib.request.urlopen("https://discovery.meethue.com/", timeout=6) as r:
            d = json.loads(r.read().decode())
        if d and d[0].get("internalipaddress"):
            return d[0]["internalipaddress"]
    except Exception:
        pass
    try:
        import subprocess
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5,
                             creationflags=0x08000000).stdout.lower()
        for line in out.splitlines():
            if "ec-b5-fa" in line or "00-17-88" in line:
                return line.split()[0]
    except Exception:
        pass
    return ""


class HueRig:
    def __init__(self, settings, log=print):
        self.s, self.log = settings, log
        self.status = "off"
        self.flag = "idle"
        self._saved = {}                # light id -> its state before we took over
        self._want = {}                 # light id -> (r, g, b) we want it to show
        self._sent = {}
        self._pic = {}                  # role -> (r, g, b) from the screen
        self._green_since = None
        self._last_flags = 0
        self._test_until = 0.0
        self._lock = threading.Lock()
        threading.Thread(target=self._sender, daemon=True, name="hue-send").start()
        threading.Thread(target=self._picture, daemon=True, name="hue-picture").start()

    def opt(self, k, d):
        return getattr(self.s, k, d)

    @property
    def base(self):
        host, user = (self.opt("lights_host", "") or "").strip(), (self.opt("hue_user", "") or "").strip()
        return f"http://{host}/api/{user}" if host and user else ""

    def active(self):
        return bool(self.opt("hue_sync", False)) and bool(self.base)

    def roles(self):
        """role -> (light id, job)"""
        out = {}
        for r in ROLES:
            lid = str(self.opt(f"hue_{r}", "") or "").strip()
            job = self.opt(f"hue_{r}_job", "both" if r != "desk" else "picture") or "off"
            if lid and job != "off":
                out[r] = (lid, job)
        return out

    # ---------- setup ----------
    def list_lights(self):
        b = self.base
        if not b:
            return []
        d = _http(b + "/lights") or {}
        return [{"id": k, "name": v.get("name", k), "type": v.get("type", "")} for k, v in sorted(d.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)]

    def pair(self):
        host = (self.opt("lights_host", "") or "").strip()
        if not host:
            return {"ok": False, "msg": "Find the bridge first"}
        try:
            r = _http(f"http://{host}/api", {"devicetype": "race_engineer#rig"}, method="POST", timeout=4)
            item = (r or [{}])[0]
            if "success" in item:
                return {"ok": True, "user": item["success"]["username"], "msg": "Paired with your Hue bridge"}
            desc = (item.get("error") or {}).get("description", "No answer")
            if "link button" in desc:
                desc = "Press the round button on top of the Hue bridge, then click Pair again within 30 seconds"
            return {"ok": False, "msg": desc}
        except Exception as e:
            return {"ok": False, "msg": f"Can't reach the bridge: {str(e)[:60]}"}

    def test(self):
        """7 s through every flag colour on every light with a job - works with or without iRacing running."""
        self._test_until = time.monotonic() + 7.0

        def run():
            while time.monotonic() < self._test_until:
                self.update(0, False)
                time.sleep(0.1)
        threading.Thread(target=run, daemon=True).start()
        return self.active()

    # ---------- every tick ----------
    def update(self, flags, driving):
        self._last_update = time.monotonic()
        if not self.active():
            if self._saved:
                self._restore()
            self.status = "off" if not self.base else "paired - sync off"
            return
        now = time.monotonic()
        f = int(flags or 0)
        if f & 0x4 and not self._last_flags & 0x4:
            self._green_since = now
        self._last_flags = f
        age = (now - self._green_since) if self._green_since is not None else None
        if now < self._test_until:
            seq = ("green", "yellow", "caution", "red", "blue", "white", "idle")
            self.flag = seq[int((now - (self._test_until - 7)) % 7)]
        else:
            self.flag = flag_state(f, driving, age)
        want = {}
        for role, (lid, job) in self.roles().items():
            flag_on = self.flag != "idle"
            if job == "flags" or (job == "both" and flag_on) or now < self._test_until:
                want[lid] = self._flag_colour(self.flag, now)
            elif job in ("picture", "both"):
                want[lid] = self._pic.get(role, (40, 30, 20))
        with self._lock:
            self._want = want

    def _flag_colour(self, st, now):
        bri = max(5, min(100, int(self.opt("lights_bri", 80)))) / 100.0
        if st == "chequered":
            st = "white" if int(now * 2) % 2 == 0 else "black"
        if st == "caution":
            bri *= 1.0 if int(now * 2) % 2 == 0 else 0.35
        if st == "idle":
            bri *= max(0, min(100, int(self.opt("lights_idle", 30)))) / 100.0
        r, g, b = COLOURS.get(st, COLOURS["idle"])
        return (int(r * bri), int(g * bri), int(b * bri))

    # ---------- the picture (H2) ----------
    def _picture(self):
        """Samples the main screen's left edge, right edge and bottom a few times a second (only while a light has
        the picture job) and turns each into one colour."""
        sct = None
        while True:
            try:
                need = (self.active() and any(job in ("picture", "both") for _, job in self.roles().values())
                        and time.monotonic() - getattr(self, "_last_update", 0.0) < 5.0)   # only while iRacing runs
                if not need:
                    time.sleep(0.5); continue
                if sct is None:
                    import mss
                    sct = mss.mss()
                import numpy as np
                mon = sct.monitors[1]
                W, H = mon["width"], mon["height"]
                regions = {"left": (0, int(H * 0.15), int(W * 0.12), int(H * 0.7)),
                           "right": (W - int(W * 0.12), int(H * 0.15), int(W * 0.12), int(H * 0.7)),
                           "desk": (int(W * 0.1), H - int(H * 0.18), int(W * 0.8), int(H * 0.18))}
                for role, (x, y, w, h) in regions.items():
                    img = sct.grab({"left": mon["left"] + x, "top": mon["top"] + y, "width": w, "height": h})
                    a = np.frombuffer(img.raw, dtype=np.uint8).reshape(img.height, img.width, 4)[::8, ::8, :3]
                    px = a.reshape(-1, 3).astype(np.float32)[:, ::-1]           # BGRA -> RGB
                    sat = px.max(1) - px.min(1)
                    w8 = 0.2 + sat / 255.0                                         # colourful pixels count more
                    c = (px * w8[:, None]).sum(0) / w8.sum()
                    m = max(c.max(), 1)
                    gain = max(0.15, min(1.0, m / 200.0))                          # keep dark scenes dim, not off
                    c = c / m * 255 * gain
                    prev = self._pic.get(role)
                    if prev is not None:                                           # smooth, no flicker
                        c = np.array(prev) * 0.5 + c * 0.5
                    self._pic[role] = tuple(int(v) for v in c)
                time.sleep(1.0 / max(1, int(self.opt("hue_picture_fps", 4))))
            except Exception as e:
                self.status = f"picture: {str(e)[:60]}"
                sct = None
                time.sleep(2.0)

    # ---------- the network side ----------
    def _sender(self):
        while True:
            time.sleep(0.12)
            if not self.active():
                continue
            if time.monotonic() - getattr(self, "_last_update", 0.0) > 5.0:     # iRacing closed: lights back to normal
                if self._saved:
                    self._restore()
                    self.status = "waiting for iRacing (lights back to normal)"
                continue
            with self._lock:
                want = dict(self._want)
            b = self.base
            try:
                for lid, c in want.items():
                    if lid not in self._saved:
                        self._save(lid)
                    last = self._sent.get(lid)
                    if last is not None and max(abs(a - b_) for a, b_ in zip(last, c)) < 6:
                        continue
                    on = any(v > 2 for v in c)
                    body = {"on": on, "transitiontime": 2}
                    if on:
                        body["xy"] = _rgb_to_xy(*c)
                        body["bri"] = max(1, min(254, int(max(c) / 255 * 254)))
                    _http(f"{b}/lights/{lid}/state", body)
                    self._sent[lid] = c
                    time.sleep(0.1)                     # the bridge takes about 10 commands a second
                self.status = f"sync on: {len(want)} light(s), {self.flag}"
            except Exception as e:
                self.status = f"bridge not answering: {str(e)[:60]}"
                time.sleep(1.0)

    def _save(self, lid):
        try:
            st = (_http(f"{self.base}/lights/{lid}") or {}).get("state", {})
            keep = {k: st[k] for k in ("on", "bri", "xy", "ct", "hue", "sat") if k in st}
            if st.get("colormode") == "ct":
                keep.pop("xy", None); keep.pop("hue", None); keep.pop("sat", None)
            elif st.get("colormode") == "xy":
                keep.pop("ct", None); keep.pop("hue", None); keep.pop("sat", None)
            self._saved[lid] = keep
        except Exception:
            self._saved[lid] = {}

    def _restore(self):
        b = self.base
        for lid, st in list(self._saved.items()):
            try:
                if st and b:
                    _http(f"{b}/lights/{lid}/state", dict(st, transitiontime=10))
            except Exception:
                pass
        self._saved.clear(); self._sent.clear()

    def close(self):
        self._restore()
