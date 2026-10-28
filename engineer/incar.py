"""In-car adjustments by voice + in-car setup coaching (2026-10-24).

Requested: "lets incorporate black box menu control ... things you could tell crew chief to do and it would do it"
and "setup tips for in car controls to make the stint easier like ARB or brake shape ... analyze my driving style".

CONTROL  "TC up one", "ABS down", "brake bias forward two clicks", "bias to 54.5", "front bar softer", "rear ARB
         stiffer", "migration up", "TC two to 4". The engineer presses iRacing's own black-box keys (F8 opens the
         in-car adjustments, Up/Down picks a control, Left/Right changes it; "=" / "-" are brake bias) and reads
         the car's live value back to confirm it. Keys are only ever sent while the iRacing window is in front,
         and only on a straight (no braking, little steering). The black box layout is learned per car the first
         time (each item is nudged one click and put straight back) and remembered.
         Pit black box (tyres, fuel, tear-off, fast repair, compound) goes straight through iRacing's pit
         commands (extras.pit_request) - no keys needed.
COACH    Watches every corner live: understeer / oversteer on entry, mid-corner and exit (steering needed per
         unit of rotation against this car's own normal), counter-steer, ABS working hard, plus how you drive
         (trail braking, how fast you pick up the throttle). "What should I change?" gets one in-car change
         with the reason; "explain the front bar / brake migration / TC / ABS / bias" says what it does and when
         to use it. "Do it" / "yes" right after a suggestion makes the change.
"""
import json, math, os, re, threading, time
from collections import deque
from statistics import median
from .voice import PRIO_URGENT, PRIO_INFO

# ------------------------------------------------------------------ the controls we can change
# name -> (telemetry var, step per click guess, spoken label variant in ic_set, words)
CONTROLS = {
    "bias":   ("dcBrakeBias",        r"brake bias|bias|brake balance"),
    "tc2":    ("dcTractionControl2", r"\btc ?2\b|tc two|traction( control)? two|traction slip"),
    "tc":     ("dcTractionControl",  r"\btc\b|traction( control)?"),
    "abs":    ("dcABS",              r"\babs\b|a b s|anti ?lock"),
    "farb":   ("dcAntiRollFront",    r"front (anti ?roll )?bar|front arb|front roll bar|front sway bar"),
    "rarb":   ("dcAntiRollRear",     r"rear (anti ?roll )?bar|rear arb|rear roll bar|rear sway bar"),
    "mig":    ("dcBrakeMisc",        r"migration|brake shape|brake mig|bias migration"),
    "map":    ("dcEnginePower",      r"engine map|power map|engine mode|\bmap\b"),
    "mix":    ("dcFuelMixture",      r"fuel mix(ture)?|fuel map"),
    "deploy": ("dcMGUKDeployMode",   r"deploy( mode)?|hybrid mode|mguk deploy|boost mode"),
    "regen":  ("dcMGUKRegenGain",    r"regen( gain)?"),
}
ORDER = ["bias", "tc", "tc2", "abs", "farb", "rarb", "mig", "map", "mix", "deploy", "regen"]
SET_VARIANT = {"bias": 1, "tc": 2, "tc2": 3, "abs": 4, "farb": 5, "rarb": 6, "mig": 7, "map": 8, "mix": 9, "deploy": 10, "regen": 11}
EXPLAIN_VARIANT = {"farb": 1, "rarb": 2, "bias": 3, "mig": 4, "tc": 5, "tc2": 6, "abs": 7, "map": 8, "deploy": 9}

# words for "more / less"
UP = r"\b(up|more|increase|raise|higher|stiffer|stiffen|harder|forward|forwards|plus|add)\b"
DOWN = r"\b(down|less|decrease|lower|softer|soften|reduce|back|backward|backwards|rearward|rearwards|minus|take off)\b"
NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "a click": 1, "one click": 1, "a step": 1, "half a": 1}

# DirectInput scan codes (iRacing reads scan codes, not virtual keys)
SC = {"F8": (0x42, False), "UP": (0x48, True), "DOWN": (0x50, True), "LEFT": (0x4B, True), "RIGHT": (0x4D, True),
      "EQUALS": (0x0D, False), "MINUS": (0x0C, False)}

MAP_PATH = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RaceEngineer", "incar_map.json")


def _press(name, hold=0.035):
    """One key press (scan code) through SendInput."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    sc, ext = SC[name]
    fl = 0x0008 | (0x0001 if ext else 0)          # SCANCODE (+ EXTENDEDKEY for arrows)
    for f in (fl, fl | 0x0002):                    # down, up
        i = INPUT(type=1); i.u.ki = KEYBDINPUT(0, sc, f, 0, 0)
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))
        time.sleep(hold)


class InCar:
    def __init__(self, brain):
        self.b = brain
        self.busy = False
        self.pending = None           # (control, delta, until) a suggestion waiting for "do it"
        self.maps = self._load()
        self.reset()

    # ------------------------------------------------------------------ helpers
    def g(self, k, d=None):
        return self.b.g(k, d)

    def A(self, sid, f=None, prio=PRIO_URGENT):
        self.b.say(sid, f, prio=prio)
        return True

    def car(self):
        d = self.b.drivers().get(self.b.me(), {}) or {}
        return d.get("CarPath") or "car"

    def have(self, ctl):
        v = self.g(CONTROLS[ctl][0])
        return v is not None

    def dc_snapshot(self):
        out = {}
        for c in ORDER:
            v = self.g(CONTROLS[c][0])
            if v is not None:
                out[c] = float(v)
        return out

    def _load(self):
        try:
            return json.load(open(MAP_PATH, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(MAP_PATH), exist_ok=True)
            json.dump(self.maps, open(MAP_PATH, "w", encoding="utf-8"), indent=1)
        except OSError:
            pass

    def say_value(self, ctl):
        v = self.g(CONTROLS[ctl][0])
        if v is None:
            return self.A("ic_msg", {"_variant": 2})
        v = float(v)
        if ctl == "bias":
            whole, tenth = int(v), int(round((v - int(v)) * 10)) % 10
            return self.A("ic_set", {"n": [whole, tenth], "_variant": 1})
        return self.A("ic_set", {"n": int(round(v)), "_variant": SET_VARIANT[ctl]})

    # ------------------------------------------------------------------ live coaching (every tick)
    def reset(self):
        self.base = {}                # speed band -> deque of steering indices (this car's normal)
        self.lap = self._fresh()
        self.hist = deque(maxlen=4)   # last laps' summaries
        self.lc = None
        self.prev_thr, self.prev_t = 0.0, None

    def _fresh(self):
        return {"n": {"entry": 0, "mid": 0, "exit": 0}, "us": {"entry": 0, "mid": 0, "exit": 0},
                "os": {"entry": 0, "mid": 0, "exit": 0}, "cs": 0, "abs": 0, "brk": 0, "trail": 0, "thr_rate": []}

    def tick(self):
        g = self.g
        lc = g("LapCompleted")
        if lc is not None and lc != self.lc:
            if self.lc is not None and sum(self.lap["n"].values()) > 50:
                self.hist.append(self.lap)
            self.lap, self.lc = self._fresh(), lc
        if not g("IsOnTrack", False) or g("OnPitRoad", False):
            return
        v, yr, sw, la = g("Speed"), g("YawRate"), g("SteeringWheelAngle"), g("LatAccel")
        thr, brk = g("Throttle", 0) or 0, g("Brake", 0) or 0
        if None in (v, yr, sw, la):
            return
        now = self.b.clock()
        L = self.lap
        if brk > 0.15:
            L["brk"] += 1
            if abs(sw) > 0.08:
                L["trail"] += 1
            if g("BrakeABSactive", False):
                L["abs"] += 1
        if self.prev_t is not None and thr > self.prev_thr and 0 < now - self.prev_t < 0.2 and abs(sw) > 0.1:
            L["thr_rate"].append((thr - self.prev_thr) / (now - self.prev_t))
            L["thr_rate"] = L["thr_rate"][-400:]
        self.prev_thr, self.prev_t = thr, now
        if v < 15 or abs(yr) < 0.06 or abs(la) < 3:
            return
        if abs(sw) > 0.05 and (sw > 0) != (yr > 0):        # opposite lock: the rear is stepping out
            L["cs"] += 1
            phase = "entry" if brk > 0.1 else ("exit" if thr > 0.3 else "mid")
            L["n"][phase] += 1; L["os"][phase] += 1
            return
        idx = abs(sw) * v / abs(yr)
        band = int(v // 6)
        phase = "entry" if brk > 0.1 else ("exit" if thr > 0.3 else "mid")
        q = self.base.setdefault((band, phase), deque(maxlen=400))
        q.append(idx)
        # the car's normal at this speed = the middle of the three phases' medians, so one bad phase stands out
        meds = [median(self.base[(band, p)]) for p in ("entry", "mid", "exit") if len(self.base.get((band, p), ())) >= 30]
        if len(meds) < 2:
            return
        ref = median(meds) if len(meds) == 3 else min(meds, key=lambda m: abs(m - median(q)))
        L["n"][phase] += 1
        r = idx / ref if ref else 1.0
        if r > 1.18:
            L["us"][phase] += 1
        elif r < 0.84:
            L["os"][phase] += 1

    def diagnosis(self):
        """(problem, phase, share, style) from the last laps, or None."""
        laps = list(self.hist) + ([self.lap] if sum(self.lap["n"].values()) > 200 else [])
        if not laps:
            return None
        tot = {k: {p: sum(l[k][p] for l in laps) for p in ("entry", "mid", "exit")} for k in ("n", "us", "os")}
        best = None
        for p in ("entry", "mid", "exit"):
            n = tot["n"][p]
            if n < 40:
                continue
            for prob, key in (("understeer", "us"), ("oversteer", "os")):
                share = tot[key][p] / n
                if share >= 0.22 and (best is None or share > best[2]):
                    best = (prob, p, share)
        brk = sum(l["brk"] for l in laps)
        style = {"trail": (sum(l["trail"] for l in laps) / brk) if brk else 0.0,
                 "abs": (sum(l["abs"] for l in laps) / brk) if brk else 0.0,
                 "throttle": median([x for l in laps for x in l["thr_rate"]] or [0]),
                 "laps": len(laps)}
        if style["abs"] > 0.35 and (best is None or best[2] < 0.3):
            best = ("front_lock", None, style["abs"])
        return (best + (style,)) if best else (None, None, 0, style)

    # ------------------------------------------------------------------ advice
    def kind(self):
        return "gtp" if self.b.is_gtp() else "gt3"

    def advise(self, prob=None, phase=None, reported=False, asked=False):
        """One in-car change for the problem (measured, or what the driver said). Returns True if said."""
        from .pit import IN_CAR
        if prob is None:
            d = self.diagnosis()
            if not d or d[0] is None:
                st = d[3] if d else None
                if st and st["laps"] >= 1:
                    return self.A("ic_tip", {"_variant": 1})        # balance looks good
                return self.A("ic_tip", {"_variant": 2})            # not enough laps yet
            prob, phase, _, st = d
        else:
            st = (self.diagnosis() or (None, None, 0, {}))[3] or {}
        table = IN_CAR[self.kind()]
        rule = table.get((prob, phase)) or (table.get((prob, None)) if phase is None else None)
        sv0 = {("understeer", "entry"): 3, ("understeer", "mid"): 4, ("understeer", "exit"): 5,
               ("oversteer", "entry"): 6, ("oversteer", "mid"): 7, ("oversteer", "exit"): 8}.get((prob, phase))
        if not rule:
            if reported and not asked:
                return True                                  # the reply already covered it
            if asked:
                return self.A("ic_tip", {"_variant": 11})
            if sv0:
                self.A("ic_tip", {"_variant": sv0})
            return self.A("ic_tip", {"_variant": 11})        # nothing on the wheel for that: setup at the stop
        var = rule[0]
        ctl = next((c for c, (vv, _) in CONTROLS.items() if vv == var), None)
        if ctl is None or not self.have(ctl):
            return self.A("ic_tip", {"_variant": 2})
        delta = self._direction(rule[1])
        # what we saw, then the change, then the offer to do it
        sv = {("understeer", "entry"): 3, ("understeer", "mid"): 4, ("understeer", "exit"): 5,
              ("oversteer", "entry"): 6, ("oversteer", "mid"): 7, ("oversteer", "exit"): 8,
              ("traction", None): 8, ("front_lock", None): 9, ("rear_lock", None): 10}.get((prob, phase))
        if sv and not reported:
            self.A("ic_tip", {"_variant": sv})
        self.A("ic_do", {"_variant": {"bias": 1, "tc": 3, "tc2": 5, "abs": 7, "farb": 9, "rarb": 11, "mig": 13}.get(ctl, 1) + (0 if delta > 0 else 1)})
        if prob == "oversteer" and phase == "entry" and st.get("trail", 0) > 0.55:
            self.A("ic_style", {"_variant": 1})            # lots of trail braking: release a bit earlier
        if prob in ("oversteer", "traction") and phase == "exit" and st.get("throttle", 0) > 4.0:
            self.A("ic_style", {"_variant": 2})            # very quick on the throttle
        self.pending = (ctl, delta, self.b.clock() + 25)
        self.A("ic_offer")
        return True

    def _direction(self, words):
        w = words.lower()
        if re.search(r"rearward|softer|down|negative|less", w):
            return -1
        return 1

    # ------------------------------------------------------------------ voice
    def command(self, text, tt):
        b = self.b
        # "do it" / "yes" right after a suggestion
        if self.pending and b.clock() < self.pending[2] and re.fullmatch(r"\s*(yes|yeah|yep|do it|go ahead|change it|ok do it|okay do it|copy do it|please)\s*", tt):
            ctl, delta, _ = self.pending; self.pending = None
            return self.adjust(ctl, delta=delta)
        if self.pending and re.fullmatch(r"\s*(no|nope|leave it|not now|no thanks)\s*", tt):
            self.pending = None
            return self.A("ack", {"_variant": 1})
        # explain a control
        if re.search(r"\b(explain|what does|what do|tell me about|how does|what s the point of|what is the point of)\b", tt) and \
                not re.search(r"\b(set|at|on)\b.{0,6}\d", tt):
            for ctl, (var, pat) in CONTROLS.items():
                if re.search(pat, tt) and ctl in EXPLAIN_VARIANT:
                    return self.A("ic_explain", {"_variant": EXPLAIN_VARIANT[ctl]})
        # "explain oversteer at entry" / "how do I fix understeer mid corner" / "car is loose on exit, what can I do"
        m = re.search(r"\b(oversteer|understeer|loose|tight|push(es|ing)?|snap(py)?|rotat\w*)\b", tt)
        if m and re.search(r"\b(explain|fix|help|what (can|should|do) (i|we)|how do (i|we)|what about|tips?)\b", tt):
            prob = "oversteer" if m.group(1) in ("oversteer", "loose", "snap", "snappy") else "understeer"
            if m.group(1).startswith("rotat"):
                prob = "understeer" if re.search(r"\b(won t|doesn t|not|no)\b", tt) else "oversteer"
            phase = "entry" if re.search(r"entry|turn ?in|braking|into", tt) else "exit" if re.search(r"exit|out of|throttle|traction", tt) \
                else "mid" if re.search(r"mid|middle|apex", tt) else None
            sv = {("understeer", "entry"): 3, ("understeer", "mid"): 4, ("understeer", "exit"): 5, ("oversteer", "entry"): 6,
                  ("oversteer", "mid"): 7, ("oversteer", "exit"): 8}.get((prob, phase or "mid"))
            return self.advise(prob, phase or "mid", reported=True, asked=True)
        # advice: "what should I change", "any setup advice", "how's the balance", "how do I fix the understeer"
        if re.search(r"what should (i|we) (change|do|adjust)|any (setup |car )?(advice|tips?)|setup (tip|advice)|how( s| is)? the balance|"
                     r"what would you change|help me with the (car|balance)|in ?car (adjustment|change|tips?)|what can i change", tt):
            return self.advise()
        # what is the TC on / what's my bias
        if re.search(r"\b(what s|whats|what is|what|where s|where is|current)\b", tt) and not re.search(UP + "|" + DOWN, tt):
            for ctl in ORDER:
                if re.search(CONTROLS[ctl][1], tt) and self.have(ctl):
                    return self.say_value(ctl)
        # change a control
        ctl = next((c for c in ORDER if re.search(CONTROLS[c][1], tt)), None)
        if ctl is None:
            return False
        m = re.search(r"\b(to|at|on)\s*(\d+(?:\.\d+)?)\b", tt)
        up, down = re.search(UP, tt), re.search(DOWN, tt)
        if not m and not up and not down:
            return False
        if not self.have(ctl):
            return self.A("ic_msg", {"_variant": 2})                 # this car doesn't have it
        if m:
            return self.adjust(ctl, target=float(m.group(2)))
        n = 1
        mm = re.search(r"\b(\d+)\s*(clicks?|steps?|notch(es)?|points?)?\b", tt)
        if mm and int(mm.group(1)) <= 10:
            n = int(mm.group(1))
        else:
            for w, k in NUMW.items():
                if re.search(r"\b" + w + r"\b", tt):
                    n = k
        if ctl == "bias" and re.search(r"half", tt):
            n = 1
        return self.adjust(ctl, delta=n if (up and not down) or (up and down and up.start() < down.start()) else -n)

    # ------------------------------------------------------------------ pressing the keys
    def adjust(self, ctl, delta=None, target=None):
        from .extras import _sim_in_front
        if self.busy:
            return self.A("ic_msg", {"_variant": 3})
        ir = getattr(self.b.src, "ir", None)
        if ir is None or getattr(ir, "fake", False):
            return self.A("ic_msg", {"_variant": 1})
        self.busy = True
        threading.Thread(target=self._run, args=(ctl, delta, target), daemon=True).start()
        return True

    def _wait_straight(self, secs=8.0):
        t0 = time.time()
        while time.time() - t0 < secs:
            sw, brk = self.g("SteeringWheelAngle", 0) or 0, self.g("Brake", 0) or 0
            if abs(sw) < 0.25 and brk < 0.05:
                return True
            time.sleep(0.05)
        return False

    def _changed(self, before, wait=0.25):
        t0 = time.time()
        while time.time() - t0 < wait:
            time.sleep(0.04)
            now = self.dc_snapshot()
            for c, v in now.items():
                if c in before and abs(v - before[c]) > 1e-6:
                    return c, now[c] - before[c]
        return None, 0

    def _run(self, ctl, delta, target):
        from .extras import _sim_in_front
        try:
            var = CONTROLS[ctl][0]
            cur = self.g(var)
            if cur is None:
                self.A("ic_msg", {"_variant": 2}); return
            if not self._wait_straight():
                self.A("ic_msg", {"_variant": 4}); return            # never found a straight
            if not _sim_in_front():
                self.A("ic_msg", {"_variant": 1}); return            # keys only ever go to iRacing
            if target is not None:
                step = self._step(ctl)
                delta = int(round((target - float(cur)) / step)) if step else 0
                if delta == 0:
                    self.say_value(ctl); return
            ok = False
            if ctl == "bias":                       # iRacing's default brake bias keys first
                ok = self._direct(delta)
            if not ok:
                ok = self._blackbox(ctl, delta)
            if ok:
                time.sleep(0.15)
                self.say_value(ctl)
            else:
                self.A("ic_msg", {"_variant": 5})                 # the keys didn't do anything
        except Exception as e:
            self.b.log(f"[incar] {e!r}")
        finally:
            self.busy = False

    def _step(self, ctl):
        return self.maps.get(self.car(), {}).get("step", {}).get(ctl) or (0.5 if ctl == "bias" else 1.0)

    def _remember_step(self, ctl, d):
        m = self.maps.setdefault(self.car(), {})
        m.setdefault("step", {})[ctl] = abs(d)
        self._save()

    def _direct(self, delta):
        from .extras import _sim_in_front
        before = self.dc_snapshot()
        key = "EQUALS" if delta > 0 else "MINUS"
        if not _sim_in_front():
            return False
        _press(key)
        c, d = self._changed(before)
        if c != "bias":
            return False
        self._remember_step("bias", d)
        for _ in range(abs(delta) - 1):
            if not _sim_in_front():
                return True
            _press(key); time.sleep(0.06)
        return True

    def _probe(self):
        """Which control is selected in the black box? Nudge it one click (Right, or Left if it's at the top)
        and put it straight back. -> (control or None, step size)"""
        for key, undo in (("RIGHT", "LEFT"), ("LEFT", "RIGHT")):
            before = self.dc_snapshot()
            _press(key)
            c, d = self._changed(before)
            if c:
                _press(undo); time.sleep(0.05)
                self._remember_step(c, d)
                return c, d
        return None, 0

    def _locate(self, slots):
        """Current position in the slot list (walks Up until a known control shows), or None."""
        for k in range(len(slots) + 1):
            c, _ = self._probe()
            if c in slots:
                return slots.index(c)
            _press("UP"); time.sleep(0.06)
        return None

    def _blackbox(self, ctl, delta):
        from .extras import _sim_in_front
        m = self.maps.setdefault(self.car(), {})
        _press("F8"); time.sleep(0.15)
        slots = m.get("slots")
        if not slots or ctl not in slots:
            slots = self._learn()
            if not slots or ctl not in slots:
                return False
        pos = self._locate(slots)
        if pos is None:
            m.pop("slots", None); self._save()
            return False
        n = len(slots)
        steps = (slots.index(ctl) - pos) % n
        key, cnt = ("UP", steps) if steps <= n - steps else ("DOWN", n - steps)
        for _ in range(cnt):
            if not _sim_in_front():
                return False
            _press(key); time.sleep(0.06)
        before = self.dc_snapshot()
        _press("RIGHT" if delta > 0 else "LEFT")
        c, dd = self._changed(before)
        if c != ctl:
            if c is not None:
                _press("LEFT" if delta > 0 else "RIGHT")     # wrong item: put it back, relearn next time
                m.pop("slots", None); self._save()
                return False
            # no change: at its limit already
            self.A("ic_msg", {"_variant": 6})
            return True
        for _ in range(abs(delta) - 1):
            if not _sim_in_front():
                return True
            _press("RIGHT" if delta > 0 else "LEFT"); time.sleep(0.06)
        return True

    def _learn(self):
        """Walk the in-car black box once with Up, noting which control each item is (items without a live value,
        like wipers or the tear-off, are left alone: they are only ever nudged by one click and put back - the
        tear-off and wipers aren't touched because they don't respond to Left/Right)."""
        from .extras import _sim_in_front
        slots = []
        first = None
        for k in range(30):
            if not _sim_in_front():
                return None
            c, _ = self._probe()
            if c is not None and c == first and k > 0:
                break                                    # back to the start: one full lap of the box
            if first is None and c is not None:
                first = c
            slots.append(c)
            _press("UP"); time.sleep(0.08)
        # trim leading empties before the first control so positions line up with the cycle
        if first is None:
            return None
        i0 = slots.index(first)
        slots = slots[i0:] + slots[:i0]
        m = self.maps.setdefault(self.car(), {})
        m["slots"] = slots
        self._save()
        self.b.log(f"[incar] black box for {self.car()}: {slots}")
        return slots
