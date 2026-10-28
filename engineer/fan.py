"""Speed fan (2026-10-26, D12 #250 / H4 #287): a fan on the rig that blows harder the faster you go - ready for the
hardware, like the bass shaker.

Two ways to drive it:
  hue    a Philips Hue smart plug on the same bridge as the lights: ON above the "on at" speed, OFF below (a plug can
         only switch). Pick the plug in Settings.
  url    anything with a web address that takes a level - a Shelly / Tasmota dimmer plug, a fan controller, Home
         Assistant. Type the address with {pct} where the level (0-100) goes, e.g.
         http://192.168.1.60/light/0?turn=on&brightness={pct}
Only while you drive (live, your car); off in the pits, in replays and when iRacing closes.
"""
import threading, time, urllib.request


class Fan:
    def __init__(self, settings, hue_base_fn, log=print):
        self.s, self.hue_base_fn, self.log = settings, hue_base_fn, log
        self.status = "off"
        self.want, self.sent = 0, None
        self._t = 0.0
        threading.Thread(target=self._worker, daemon=True, name="fan").start()

    def opt(self, k, d):
        return getattr(self.s, k, d)

    def update(self, driving, speed_kmh, in_pits):
        self._t = time.monotonic()
        if not self.opt("fan_on", False):
            self.want = 0
            return
        v = float(speed_kmh or 0)
        lo, hi = float(self.opt("fan_from", 40)), float(self.opt("fan_full", 280))
        pct = 0 if (not driving or in_pits or v < lo) else int(min(100, 15 + 85 * (v - lo) / max(1.0, hi - lo)))
        self.want = int(round(pct / 5.0) * 5)

    def _worker(self):
        while True:
            time.sleep(0.5)
            want = self.want if time.monotonic() - self._t < 5 else 0      # iRacing closed: fan off
            if want == self.sent:
                continue
            kind = (self.opt("fan_kind", "url") or "url").lower()
            try:
                if kind == "hue":
                    base, plug = self.hue_base_fn(), str(self.opt("fan_plug", "") or "")
                    if base and plug:
                        import json
                        req = urllib.request.Request(f"{base}/lights/{plug}/state", data=json.dumps({"on": want > 0}).encode(),
                                                     method="PUT", headers={"Content-Type": "application/json"})
                        urllib.request.urlopen(req, timeout=1.5).read()
                else:
                    url = str(self.opt("fan_url", "") or "")
                    if url:
                        urllib.request.urlopen(url.replace("{pct}", str(want)), timeout=1.5).read()
                self.sent = want
                self.status = f"on: {want}%" if self.opt("fan_on", False) else "off"
            except Exception as e:
                self.status = f"fan not answering: {str(e)[:60]}"
                time.sleep(2)
