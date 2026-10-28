"""Pit crew: plans your stop from the stint (fuel, tyres, your complaints), talks it through on the radio,
and fills in iRacing's pit menu for you. No AI here: rules only, so it works while you drive.

What iRacing lets a program set for a stop (same as CrewChief): fuel, which tyres, each tyre's cold
pressure, tyre compound, windscreen tear-off, fast repair. Garage setup can't change in a race stop.
Anti-roll bars, brake bias/migration, TC, ABS are yours to change from the wheel: the crew suggests
them and confirms when it sees you change them.
"""
import re, time

PSI = 6.894757           # kPa per psi
F_LF, F_RF, F_LR, F_RR, F_FUEL, F_WS, F_FR = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40

# what the driver says about the car -> (problem, end of the car, phase)
COMPLAINTS = [
    ("understeer", [r"under ?steer", r"\bpush(ing|es|y)?\b", r"\btight\b", r"won'?t turn", r"doesn'?t turn", r"front (is )?(washing|sliding|gone)", r"no front"]),
    ("oversteer", [r"over ?steer", r"\bloose\b", r"\bsnap", r"rear (is )?(sliding|stepping|gone|loose|out)", r"no rear", r"spin"]),
    ("front_lock", [r"lock(ing)? (up )?(the )?front", r"front(s)? lock", r"flat ?spot"]),
    ("rear_lock", [r"lock(ing)? (up )?(the )?rear", r"rear(s)? lock"]),
    ("traction", [r"wheel ?spin", r"no traction", r"traction", r"spinning the (rears|wheels)"]),
    ("bottoming", [r"bottom", r"scrap(e|ing)", r"hitting the ground"]),
    ("grip", [r"no grip", r"tyres? (are )?(going off|dropping off|falling off|worn|cooked)", r"losing grip", r"tyres? (are )?(gone|dead|done|finished)", r"tires? (are )?(gone|dead|done|finished)", r"graining", r"overheat"]),
]
PHASES = [("entry", r"entry|turn ?in|braking|in to|into"), ("exit", r"exit|throttle|power|out of|on the gas"), ("mid", r"mid|apex|middle")]

# in-car changes per problem (GTP / GT3): (dash variable, what to say)
IN_CAR = {
    "gtp": {("understeer", "entry"): ("dcBrakeMisc", "brake migration one click more negative"),
            ("understeer", "mid"): ("dcAntiRollFront", "front bar one step softer"),
            ("understeer", "exit"): ("dcAntiRollFront", "front bar one step softer"),
            ("oversteer", "entry"): ("dcBrakeBias", "brake bias half a percent forward"),
            ("oversteer", "mid"): ("dcAntiRollRear", "rear bar one step softer"),
            ("oversteer", "exit"): ("dcTractionControl2", "T C 2 one step up"),
            ("traction", None): ("dcTractionControl2", "T C 2 one step up"),
            ("front_lock", None): ("dcBrakeBias", "brake bias half a percent rearward"),
            ("rear_lock", None): ("dcBrakeBias", "brake bias half a percent forward")},
    "gt3": {("understeer", "entry"): ("dcBrakeBias", "brake bias half a percent rearward"),
            ("oversteer", "entry"): ("dcBrakeBias", "brake bias half a percent forward"),
            ("oversteer", "exit"): ("dcTractionControl", "traction control one step up"),
            ("traction", None): ("dcTractionControl", "traction control one step up"),
            ("front_lock", None): ("dcABS", "A B S one step up"),
            ("rear_lock", None): ("dcBrakeBias", "brake bias half a percent forward")},
}
DASH = ["dcAntiRollFront", "dcAntiRollRear", "dcBrakeBias", "dcBrakeMisc", "dcTractionControl", "dcTractionControl2", "dcABS"]
DASH_NAME = {"dcAntiRollFront": "front bar", "dcAntiRollRear": "rear bar", "dcBrakeBias": "brake bias", "dcBrakeMisc": "migration",
             "dcTractionControl": "T C", "dcTractionControl2": "T C 2", "dcABS": "A B S"}


def classify(text):
    t = " " + text.lower() + " "
    for prob, pats in COMPLAINTS:
        if any(re.search(p, t) for p in pats):
            phase = next((ph for ph, p in PHASES if re.search(p, t)), None)
            return prob, phase
    return None, None


class PitCrew:
    def __init__(self, speak, log=print, emit=None):
        """speak(role, text): the crew's voice (meeting.Speaker.say)."""
        self.speak, self.log = speak, log
        self.emit = emit or (lambda e: None)
        self.b = None
        self.reset()

    # ---------------------------------------------------------------- state
    def reset(self):
        self.stint = []              # [(lap, time, clean, fuel_used)]
        self.stint_start = time.time()
        self.complaints = []         # [(lap, corner, problem, phase, text)]
        self.plan = None
        self.awaiting = 0.0          # time we asked "confirm?" (answers within 40 s go to the plan)
        self.prompted = False
        self.watch = {}              # dash var -> value when we suggested a change
        self.dash = {}
        self._last_lc, self._fuel_line, self._was_pit = None, None, None
        self._last_emit = 0

    def g(self, k, d=None):
        try:
            x = self.b.src[k]
            return d if x is None else x
        except Exception:
            return d

    def kind(self):
        return "gtp" if self.b and self.b.is_gtp() else "gt3"

    def metric(self):
        return bool(self.b and self.b.metric())

    # ---------------------------------------------------------------- every tick (engine thread)
    def tick(self, brain):
        if brain is not self.b:
            self.b = brain
            self.reset()
        if brain is None:
            return
        onp = bool(self.g("OnPitRoad", False))
        if self._was_pit and not onp:                       # left the pits: new stint
            keep = self.plan
            self.reset(); self.b = brain
            if keep and keep.get("pressure"):
                self.watch["_pressure"] = keep["pressure"]
        self._was_pit = onp
        lc = self.g("LapCompleted", -1)
        if lc is not None and lc >= 0:
            if self._last_lc is None:
                self._last_lc, self._fuel_line = lc, self.g("FuelLevel")
            elif lc > self._last_lc:
                self._last_lc = lc
                fuel = self.g("FuelLevel")
                t = self.g("LapLastLapTime", -1) or -1
                used = (self._fuel_line - fuel) if (self._fuel_line is not None and fuel is not None) else None
                self._fuel_line = fuel
                clean = t > 0 and not onp and not getattr(brain, "caution_on", False) and len(self.stint) > 0
                self.stint.append((lc, t, clean, used if used and used > 0.05 else None))
                self._lap_done()
        # did he change something on the wheel that we suggested?
        for k in DASH:
            v = self.g(k)
            if v is None:
                continue
            old = self.dash.get(k)
            self.dash[k] = v
            if old is not None and abs(v - old) > 1e-6 and k in self.watch:
                self.watch.pop(k)
                val = f"{v:.1f}" if k == "dcBrakeBias" else f"{v:g}"
                self.speak("ENGINEER", f"Copy, {DASH_NAME[k]} {val}.")
        if time.time() - self._last_emit > 1:
            self._last_emit = time.time()
            self.emit({"t": "pit_state", "s": self.state()})

    def _lap_done(self):
        b = self.b
        if not b.is_race() or self.prompted:
            return
        fl, ltg = self.fuel_per_lap(), b.laps_to_go()
        fuel = self.g("FuelLevel", 0) or 0
        if fl and ltg and fuel / fl < ltg + 0.3 and fuel / fl <= 2.6:
            self.prompted = True
            self.propose(auto=True)

    # ---------------------------------------------------------------- the numbers
    def fuel_per_lap(self):
        xs = [u for _, _, c, u in self.stint if c and u]
        if not xs and self.b:
            # this session's laps, else (2026-10-26, #46) your usual here from earlier sessions until there is one
            return self.b.fuel_lap_est()
        xs = xs[-4:]
        return sum(xs) / len(xs) if xs else None

    def tank(self):
        di = (self.b.info("DriverInfo", {}) if self.b else {}) or {}
        try:
            return float(di.get("DriverCarFuelMaxLtr")) * float(di.get("DriverCarMaxFuelPct") or 1)
        except (TypeError, ValueError):
            return None

    def degradation(self):
        """Seconds lost from the best early laps of the stint to the last laps."""
        ts = [t for _, t, c, _ in self.stint if c]
        if len(ts) < 4:
            return None
        early = min(ts[:4])
        late = sorted(ts[-3:])[1] if len(ts) >= 3 else ts[-1]
        return late - early

    def pressure_now(self):
        out = {}
        for c, k in (("lf", "PitSvLFP"), ("rf", "PitSvRFP"), ("lr", "PitSvLRP"), ("rr", "PitSvRRP")):
            v = self.g(k)
            if not v:
                dp = self.g(f"dp{c.upper()}TireColdPress")
                v = dp / 1000 if dp and dp > 1000 else dp
            out[c] = v
        return out

    def menu(self):
        f = int(self.g("PitSvFlags", 0) or 0)
        return {"lf": bool(f & F_LF), "rf": bool(f & F_RF), "lr": bool(f & F_LR), "rr": bool(f & F_RR),
                "fuel": round(float(self.g("PitSvFuel", 0) or 0), 1) if f & F_FUEL else 0, "ws": bool(f & F_WS),
                "fr": bool(f & F_FR), "press": self.pressure_now(), "compound": self.g("PitSvTireCompound")}

    # ---------------------------------------------------------------- the plan
    def make_plan(self):
        b = self.b
        fl, ltg, tank = self.fuel_per_lap(), b.laps_to_go() if b else None, self.tank()
        fuel = self.g("FuelLevel", 0) or 0
        pct = self.g("LapDistPct", 0) or 0
        plan = {"fuel": None, "fuel_why": "", "tyres": False, "tyres_why": "", "pressure": None, "ws": True,
                "fr": False, "in_car": None, "notes": []}
        at_stop = max(0.0, fuel - (fl or 0) * max(0.0, 1 - pct))
        if b and b.is_race() and fl and ltg:
            need = (ltg + 0.5 + float(getattr(getattr(b, "s", None), "fuel_buffer_laps", 0) or 0)) * fl - at_stop   # + fuel buffer (D10)
            space = (tank - at_stop) if tank else need
            if need <= 0:
                plan["fuel"], plan["fuel_why"] = 0, "enough to the end"
            elif need <= space:
                plan["fuel"], plan["fuel_why"] = round(need + 0.4, 1), "to the end"
            else:
                plan["fuel"], plan["fuel_why"] = round(space, 1), "full, one more stop after this"
        else:
            plan["fuel"], plan["fuel_why"] = (round(tank - at_stop, 1) if tank else 999), "full tank"
        st = getattr(self, "strat", None)
        ns = st.next_stop() if st else None
        if ns and b and b.is_race():
            plan["fuel"], plan["fuel_why"] = ns["fuel"], f"plan {'ABC'[st.rec]}"
        deg = self.degradation()
        n = len(self.stint)
        call = st.tyre_call if st else None         # the rain watcher's decision: "wet" / "dry" / None
        if call == "wet":
            plan["tyres"], plan["tyres_why"], plan["compound"] = True, "wets, they're faster on this track now", st.wet_index()
        elif call == "dry":
            plan["tyres"], plan["tyres_why"], plan["compound"] = True, "slicks, the track is drying", st.dry_index()
        elif deg is not None and deg > 0.5:
            plan["tyres"], plan["tyres_why"] = True, f"you've lost {deg:.1f} seconds a lap"
        elif any(p == "grip" for _, _, p, _, _ in self.complaints):
            plan["tyres"], plan["tyres_why"] = True, "you said the tyres are going"
        elif n >= 2 * max(1, (int(tank / fl) if tank and fl else 8)):
            plan["tyres"], plan["tyres_why"] = True, "double stint done"
        else:
            plan["tyres_why"] = "these are still fine" + (f", only {deg:.1f} slower" if deg is not None else "")
        if ns and b and b.is_race() and ns["tyres"] and not plan["tyres"]:
            plan["tyres"], plan["tyres_why"] = True, "the race plan takes tyres here"
        # the handling complaint heard most this stint
        probs = [(p, ph) for _, _, p, ph, _ in self.complaints if p in ("understeer", "oversteer", "traction", "front_lock", "rear_lock")]
        if probs:
            top = max(set(probs), key=probs.count)
            where = [c for _, c, p, ph, _ in self.complaints if (p, ph) == top and c]
            plan["problem"] = {"what": top[0], "phase": top[1], "times": probs.count(top), "where": sorted(set(where))[:3]}
            if plan["tyres"] and top[0] in ("understeer", "oversteer"):
                end = "front" if top[0] == "understeer" else "rear"
                plan["pressure"] = {"end": end, "psi": -0.5}
            ic = IN_CAR[self.kind()].get(top) or IN_CAR[self.kind()].get((top[0], None)) or \
                next((v for (p, ph), v in IN_CAR[self.kind()].items() if p == top[0]), None)
            if ic:
                plan["in_car"] = {"var": ic[0], "say": ic[1]}
        return plan

    def propose(self, auto=False):
        if not self.b:
            self.speak("ENGINEER", "No data yet.")
            return None
        p = self.plan = self.make_plan()
        lines = ["Box plan." if not auto else "Pit window. Here's the plan."]
        lines.append(self._fuel_words(p))
        lines.append(f"Tyres: {'four new' if p['tyres'] else 'stay on these'}, {p['tyres_why']}.")
        pr = p.get("problem")
        if pr:
            w = f" in {', '.join(pr['where'])}" if pr["where"] else ""
            ph = {"entry": " on entry", "mid": " mid-corner", "exit": " on exit"}.get(pr["phase"], "")
            lines.append(f"You said {pr['what'].replace('_', ' ')}{ph}{w}.")
            if p["pressure"]:
                lines.append(f"{p['pressure']['end'].title()}s half a p s i down.")
            if p["in_car"]:
                lines.append(f"From the wheel: {p['in_car']['say']}.")
        lines.append("Confirm, or tell me what to change.")
        for s in lines:
            self.speak("ENGINEER", s)
        self.awaiting = time.time()
        self.emit({"t": "pit_state", "s": self.state()})
        return p

    def _fuel_words(self, p):
        u = "litres" if self.metric() else "gallons"
        f = p["fuel"]
        if f is None:
            return "Fuel: no data yet."
        if f >= 900:
            return "Fuel: full tank."
        n = f if self.metric() else f / 3.785
        return f"Fuel: {round(n)} {u}, {p['fuel_why']}." if f > 0 else "Fuel: none needed."

    # ---------------------------------------------------------------- answers (radio)
    def wants(self, text):
        """Is this radio message for the pit plan?"""
        return self.plan is not None and time.time() - self.awaiting < 40

    def answer(self, text):
        t = " " + text.lower() + " "
        p = self.plan
        if p is None:
            return False
        if re.search(r"\b(cancel|no stop|not pitting|stay out|forget it)\b", t):
            self.plan, self.awaiting = None, 0
            self.send_clear()
            self.speak("ENGINEER", "Copy, no stop. Pit menu cleared.")
            return True
        # #453 (2026-10-28): a QUESTION ("how are the tyres?", "how's it going?") is not an answer to the plan -
        # let it go to the normal radio. Requests phrased as questions with a clear order still count
        # ("can we do no tyres", "can you fill it up").
        if re.match(r"\s*(how|how's|hows|what|what's|whats|when|where|who|why|which|is|are|does|did|will)\b", t) and not re.search(
                r"\b(new|four|change|take|skip|without|full|fill|brim|repair|tear ?off|cancel|stay out)\b|fuel only|just fuel|only fuel|\d", t):
            return False
        changed = []
        if re.search(r"\b(no|keep|without|skip)\b.{0,12}\b(tyres?|tires?)\b|fuel only|just fuel|only fuel", t):
            p["tyres"], p["pressure"] = False, None; changed.append("no tyres")
        elif re.search(r"\b(new|four|change|take)\b.{0,10}\b(tyres?|tires?)\b|\b(tyres?|tires?)\b", t):
            p["tyres"] = True; changed.append("four tyres")
        if re.search(r"\b(no|keep|leave)\b.{0,15}\bpressures?\b", t):
            p["pressure"] = None; changed.append("pressures as they are")
        if re.search(r"\bfull\b|fill (it|her) up|brim", t):
            tk = self.tank()
            p["fuel"], p["fuel_why"] = (round(tk, 1) if tk else 999), "full tank"; changed.append("full tank")
        m = re.search(r"\b(\d{1,3})\s*(litres?|liters?|l|gallons?|g)?\b", t)
        if m and re.search(r"fuel|litre|liter|gallon", t):
            n, unit = float(m.group(1)), (m.group(2) or "")
            gal = unit.startswith("g") or (not unit and not self.metric())
            p["fuel"] = n * (3.785 if gal else 1)
            p["fuel_why"] = "as you asked"; changed.append(f"fuel {m.group(1)}")
        if re.search(r"tear ?off|screen|visor", t):
            p["ws"] = True; changed.append("tear-off")
        if re.search(r"fast repair|repair", t):
            p["fr"] = True; changed.append("fast repair")
        yes = re.search(r"\b(yes|yeah|yep|confirm|copy|do it|go|go ahead|ok|okay|sounds good|perfect|correct|affirm|affirmative)\b", t)
        if not (yes or changed):
            return False
        self.apply(p)
        self.awaiting = time.time() if changed and not yes else 0
        bits = [self._fuel_words(p).replace("Fuel: ", "fuel ").rstrip("."), "four tyres" if p["tyres"] else "no tyres"]
        if p["pressure"]:
            bits.append(f"{p['pressure']['end']}s minus half")
        self.speak("ENGINEER", "Copy. " + ", ".join(bits) + ". It's in the pit menu.")
        if p["in_car"]:
            self.watch[p["in_car"]["var"]] = self.dash.get(p["in_car"]["var"])
        return True

    # ---------------------------------------------------------------- notes from the radio
    def note(self, text, lap=None, corner=None):
        prob, phase = classify(text)
        if prob:
            self.complaints.append((lap, corner, prob, phase, text))
            self.emit({"t": "pit_state", "s": self.state()})
        return prob

    # ---------------------------------------------------------------- iRacing pit menu
    def _cmd(self, mode, var=0):
        import irsdk
        self.b.src.ir.pit_command(getattr(irsdk.PitCommandMode, mode), int(var))

    def send_clear(self):
        if self.b:
            self._cmd("clear")

    def apply(self, p):
        """Fill in iRacing's pit menu from a plan."""
        if not self.b:
            return False
        self.plan = p
        self._cmd("clear")
        f = p.get("fuel")
        if f is not None and f > 0:
            self._cmd("fuel", min(999, max(1, round(f))))
        if p.get("tyres"):
            pr = self.pressure_now()
            for c in ("lf", "rf", "lr", "rr"):
                kpa = 0
                adj = p.get("pressure")
                if adj and (adj["end"] == "front") == (c in ("lf", "rf")) and pr.get(c):
                    kpa = round(pr[c] + adj["psi"] * PSI)
                self._cmd(c, kpa)
            if p.get("compound") is not None:
                self._cmd("tc", p["compound"])
        if p.get("ws"):
            self._cmd("ws")
        if p.get("fr"):
            self._cmd("fr")
        self.log(f"[pit] menu set: fuel {f}, tyres {p.get('tyres')}, pressure {p.get('pressure')}, ws {p.get('ws')}, fr {p.get('fr')}")
        self.emit({"t": "pit_state", "s": self.state()})
        return True

    # ---------------------------------------------------------------- for the window / iPad
    def state(self):
        if not self.b:
            return {"live": False}
        ts = [t for _, t, c, _ in self.stint if c]
        return {"live": True, "metric": self.metric(), "laps": len(self.stint), "last": ts[-1] if ts else None,
                "best": min(ts) if ts else None, "deg": self.degradation(), "fuel_lap": self.fuel_per_lap(),
                "fuel": self.g("FuelLevel"), "tank": self.tank(), "ltg": self.b.laps_to_go(),
                "complaints": [{"lap": l, "corner": c, "what": p, "phase": ph, "text": tx} for l, c, p, ph, tx in self.complaints[-6:]],
                "plan": self.plan, "awaiting": bool(self.plan and time.time() - self.awaiting < 40),
                "menu": self.menu(), "dash": {DASH_NAME[k]: v for k, v in self.dash.items()}}
