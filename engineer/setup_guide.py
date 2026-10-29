"""Guided garage (2026-10-29, #514, Angelo: "can the engineer create a file and put that setup in the folder" - it can't:
iRacing's .sto setup files are a closed binary format nobody writes, and there is no API to change a setup. So instead:
"lets do it that way").

The "My style" sheet (style_setup.py) becomes a checklist. When you start the guide, the values iRacing reports for each
change are written down (the CarSetup section of the live session info, plus the in-car dc* channels like brake bias and
ARB). Then, once a second, the live values are compared with that start point:

  todo   - not changed yet
  done   - changed, and the way the sheet says (more / less, forward / rearward, softer / stiffer ...)
  check  - changed, but it looks like the other way (the number moved opposite to the sheet's word) - have a look
  manual - the sheet's change has no value iRacing reports (pads, dampers ...): tick it yourself

Every value shown is the one iRacing reports; nothing is guessed. Works in the garage (the session info updates when
you click Apply / leave the garage) and for in-car adjustments straight away.
"""
import re
import threading
import time

from . import setup_bank

_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")

# words in a step that say which way the number should go (+1 up, -1 down)
_UP = ("more ", "raise", "higher", "stiffer", "forward", "increase", "add ", "one step more", "one click more", "towards zero",
       "less negative")
_DOWN = ("less ", "lower", "softer", "rearward", "reduce", "decrease", "remove", "one step less", "one click less",
         "more negative")


def _num(v):
    """First number in a reported value ('52.5%' -> 52.5, '-2.8 deg' -> -2.8, 'P3' -> 3); None when there is none."""
    if v is None:
        return None
    m = _NUM.search(str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def direction(text):
    """+1 / -1 / 0 from the step's own words. 'more negative' / 'less negative' are checked first (camber, migration)."""
    t = " " + (text or "").lower() + " "
    for w in ("more negative", "less negative", "towards zero"):
        if w in t:
            return -1 if w == "more negative" else +1
    up = any(w in t for w in _UP)
    down = any(w in t for w in _DOWN)
    if up and not down:
        return +1
    if down and not up:
        return -1
    return 0


def live_values(brain):
    """{key: 'value'} for the setup keys the bank knows, from the LIVE session (CarSetup) and in-car dc channels."""
    out = {}
    if brain is None:
        return out
    try:
        setup = brain.info("CarSetup", {}) or {}
    except Exception:
        setup = {}

    def walk(d, path=""):
        for k, v in (d or {}).items():
            if isinstance(v, dict):
                yield from walk(v, path + k + ".")
            else:
                yield path + k, str(v).strip()
    flat = list(walk(setup))
    for key, names in setup_bank.K.items():
        for n in names:
            if n.startswith("@"):
                try:
                    v = brain.g(n[1:], None)
                except Exception:
                    v = None
                if v is not None:
                    out[key] = f"{float(v):.1f}%" if n == "@dcBrakeBias" else str(int(round(float(v))))
                    break
                continue
            hit = next((v for p, v in flat if p.endswith(n) or p.split(".")[-1] == n), None)
            if hit:
                out[key] = hit
                break
    return out


class Guide:
    def __init__(self):
        self.lock = threading.Lock()
        self.steps = []          # [{t, key, where, dir, before, now, state, ticked}]
        self.car = ""
        self.started = 0.0

    @property
    def active(self):
        return bool(self.steps)

    def start(self, changes, brain, car=""):
        vals = live_values(brain)
        steps = []
        for c in changes or []:
            key = c.get("key") or _key_for(c)
            steps.append({"t": c.get("t", ""), "key": key, "where": c.get("where"), "dir": direction(c.get("t", "")),
                          "before": vals.get(key) if key else None, "now": None, "state": "todo" if key else "manual",
                          "ticked": False})
        with self.lock:
            self.steps, self.car, self.started = steps, car, time.time()
        return self.status(brain)

    def stop(self):
        with self.lock:
            self.steps = []

    def tick(self, i, on=True):
        """The driver ticks a step by hand (manual ones, or to accept a 'check')."""
        with self.lock:
            if 0 <= i < len(self.steps):
                self.steps[i]["ticked"] = bool(on)

    def status(self, brain):
        vals = live_values(brain)
        live = brain is not None and bool(vals)
        with self.lock:
            for s in self.steps:
                if not s["key"]:
                    s["state"] = "done" if s["ticked"] else "manual"
                    continue
                now = vals.get(s["key"])
                s["now"] = now
                if s["before"] is None and now is not None:
                    s["before"] = now                      # the value showed up after the start (left the garage)
                b, n = _num(s["before"]), _num(now)
                if s["ticked"]:
                    s["state"] = "done"
                elif now is None or b is None or n is None or abs(n - b) < 1e-9:
                    s["state"] = "todo"
                elif s["dir"] == 0 or (n - b) * s["dir"] > 0:
                    s["state"] = "done"
                else:
                    s["state"] = "check"
            steps = [dict(s) for s in self.steps]
        return {"active": bool(steps), "live": live, "car": self.car, "steps": steps,
                "done": sum(1 for s in steps if s["state"] == "done"), "total": len(steps)}


def _key_for(change):
    """The style sheet keeps each step's bank key out of its output; find it again from the step text."""
    t = (change.get("t") or "").lower()
    for k, words in (("bias", ("brake bias",)), ("mig", ("migration",)), ("abs", ("abs",)), ("tc", ("traction",)),
                     ("farb", ("front anti-roll", "front arb", "front bar")), ("rarb", ("rear anti-roll", "rear arb", "rear bar")),
                     ("wing", ("wing",)), ("preload", ("preload",)), ("press", ("pressure",)),
                     ("camber_f", ("camber",)), ("rh_f", ("front ride height",)), ("rh_r", ("rear ride height",))):
        if any(w in t for w in words):
            return k
    return None
