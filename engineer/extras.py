"""DRE-parity calls (v62): everything DRE does for an iRacing driver that the engineer didn't do yet.

1 pit lane          limiter, stall, repair countdown and release, stop time, where you come out
2 pit requests      single tyres / sides / pressures / fuel / fast repair / tear-off by voice
3 other drivers     iRating, licence, strength of field, iRating projection, marked drivers, low-SR
                    warnings, "keep me updated on car X", lap times and incidents of any car
4 car health        water/oil temperature, oil and fuel pressure, stall, damage report, pedal checks, shift beep
5 fuel extras       fuel window, live fuel target per lap, low fuel on the grid
6 practice traffic  car on a push lap behind you, traffic ahead on your push lap, find space on the out lap,
                    track rubbering in
7 timing + weather  sector loss calls, green sectors, per-lap readout, track/air temperature, wind, tyre wear
8 radio             say again, timers, time of day, quick chat messages, more ways to ask

The brain calls tick() every frame and answer()/command() for the radio. Nothing here blocks: one-shot work
(chat typing) runs in its own thread. Lines not recorded yet are spoken by the stand-in voice (voice.py).
"""
import json, math, os, re, threading, time
from .voice import PRIO_SPOTTER, PRIO_URGENT, PRIO_RACE, PRIO_INFO

# EngineWarnings bits (irsdk_EngineWarnings)
W_WATER, W_FUELP, W_OILP, W_STALL, W_LIMITER, W_REVLIM, W_OILT = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40
# PitSvFlags
F_LF, F_RF, F_LR, F_RR, F_FUEL, F_WS, F_FR = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40
# track surface
TS_OFF, TS_STALL, TS_APPROACH, TS_ON = 0, 1, 2, 3
PSI = 6.894757        # kPa per psi
GAL = 3.785411784
BR1 = 1600 / math.log(2)

DATA = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "RaceEngineer")
MARKS = os.path.join(DATA, "marked_drivers.json")

NUMWORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMWORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
                 "won": 1, "hundred": 100})

_MARKS = None


def marks():
    """Marked drivers {user id: {name, car, at}}, shared by the brain and the Settings screen."""
    global _MARKS
    if _MARKS is None:
        try:
            _MARKS = json.load(open(MARKS, encoding="utf-8"))
        except (OSError, ValueError):
            _MARKS = {}
    return _MARKS


def save_marks():
    try:
        os.makedirs(DATA, exist_ok=True)
        json.dump(marks(), open(MARKS, "w", encoding="utf-8"), indent=1)
    except OSError:
        pass


CHAT = [  # (what the driver says, what gets typed)
    (r"good luck|g ?l\b", "Good luck all, have a clean one!"),
    (r"good race|g ?g\b|well done", "Good race, thanks all!"),
    (r"sorry|my bad|apolog", "Sorry!"),
    (r"thanks|thank you|cheers", "Thanks!"),
    (r"pass(ing)? (on the )?left|go left", "Pass left"),
    (r"pass(ing)? (on the )?right|go right", "Pass right"),
]


def words_to_numbers(text):
    """'add twenty five litres' -> 'add 25 litres', 'up point five' -> 'up 0.5', 'one and a half' -> '1.5'."""
    toks = re.sub(r"[^a-z0-9.#' ]", " ", re.sub(r"'s\b", "", text.lower().replace("-", " "))).split()
    out, acc, i = [], None, 0

    def flush():
        nonlocal acc
        if acc is not None:
            out.append(f"{acc:g}")
            acc = None
    while i < len(toks):
        w = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if w == "point" and (nxt in NUMWORDS or nxt.isdigit()):
            d = NUMWORDS.get(nxt, nxt)
            acc = float(f"{int(acc or 0)}.{d}"); i += 2; continue
        if w in ("and", "a") and acc is not None and nxt in ("half", "a") :
            i += 1; continue
        if w == "and" and acc is not None and acc >= 100 and acc % 100 == 0 and NUMWORDS.get(nxt, 100) < 100:
            i += 1; continue                       # "one hundred and five" -> 105
        if w == "half":
            acc = (acc or 0) + 0.5; i += 1; continue
        v = NUMWORDS.get(w)
        if v is None and re.fullmatch(r"\d+(\.\d+)?", w):
            v = float(w) if "." in w else int(w)
        if v is not None:
            if w == "hundred" and acc is not None:
                acc *= 100
            elif acc is not None and acc >= 20 and acc % 10 == 0 and v < 10:
                acc += v
            elif acc is not None and acc >= 100 and acc % 100 == 0 and v < 100:
                acc += v
            else:
                flush(); acc = v
            i += 1; continue
        flush(); out.append(w); i += 1
    flush()
    return " ".join(out)


def sof(irs):
    irs = [r for r in irs if r and r > 0]
    if not irs:
        return None
    return BR1 * math.log(len(irs) / sum(math.exp(-r / BR1) for r in irs))


def irating_change(irs, me, pos):
    """Estimated iRating change for driver index `me` in `irs` (class field, all starters) finishing at pos (1-based).
    The community formula used by the iRating calculators; iRacing's own numbers can differ by a few points."""
    n = len(irs)
    if n < 2 or not (1 <= pos <= n):
        return None
    def chance(a, b):
        ea, eb = math.exp(-a / BR1), math.exp(-b / BR1)
        return (1 - ea) * eb / ((1 - eb) * ea + (1 - ea) * eb)
    ra = irs[me]
    expected = sum(chance(ra, rb) for rb in irs) - 0.5
    fudge = (n / 2 - pos) / 100
    return (n - pos - expected - fudge) * 200 / n


def lic_parts(s):
    """'A 3.41' -> ('A', 3.41)"""
    m = re.match(r"\s*([A-Za-z]+)\s*([\d.]+)?", str(s or ""))
    if not m:
        return None, None
    try:
        return m.group(1)[:1].upper() if m.group(1).lower() != "pro" else "P", float(m.group(2)) if m.group(2) else None
    except ValueError:
        return m.group(1)[:1].upper(), None


class Extras:
    def __init__(self, brain):
        self.b = brain
        self.marks = self._load_marks()
        self.reset()

    # ------------------------------------------------------------------ helpers
    def s(self, k, d=True):
        return getattr(self.b.s, k, d)

    def g(self, k, d=None):
        return self.b.g(k, d)

    def say(self, sid, fills=None, prio=PRIO_INFO, cooldown=0, key=None, max_age=None):
        return self.b.say(sid, fills, prio=prio, cooldown=cooldown, key=key, max_age=max_age)

    def arr(self, k):
        return self.g(k) or []

    def at(self, k, i, d=None):
        a = self.arr(k)
        return a[i] if 0 <= i < len(a) and a[i] is not None else d

    def driver(self, idx):
        return self.b.drivers().get(idx, {})

    def lap_est(self):
        b = self.b
        if b.lap_times:
            xs = sorted(b.lap_times[-5:])
            return xs[len(xs) // 2]
        return float(self.driver(b.me()).get("CarClassEstLapTime") or 0) or 120.0

    def track_gap(self, i):
        """On-track seconds: >0 = car i is behind me on the road, <0 = ahead (nearest way round)."""
        me = self.b.me()
        pm, pi = self.at("CarIdxLapDistPct", me, -1), self.at("CarIdxLapDistPct", i, -1)
        if pm < 0 or pi < 0:
            return None
        d = (pm - pi) % 1.0
        if d > 0.5:
            d -= 1.0
        return d * self.lap_est()

    def num_to_idx(self, num):
        num = str(num).lstrip("#")
        for i, d in self.b.drivers().items():
            if str(d.get("CarNumber", "")).lstrip("0") == num.lstrip("0") or str(d.get("CarNumber")) == num:
                return i
        return None

    def metric(self):
        return self.b.metric()

    def fuel_units(self, litres):
        return litres if self.metric() else litres / GAL

    def pit_cmd(self, mode, var=0):
        try:
            import irsdk
            m = getattr(irsdk.PitCommandMode, mode)
        except Exception:
            m = mode
        ir = getattr(self.b.src, "ir", None)
        if ir is None:
            self.b.log(f"[pit] (no iRacing) {mode} {var}")
            return False
        ir.pit_command(m, int(var))
        return True

    # ------------------------------------------------------------------ state
    def reset(self):
        self.t_slow = 0.0
        self.prev = {}
        # pit lane
        self.stall_said = False
        self.in_stall_since = None
        self.stop_rep0 = 0.0
        self.rep_counted = set()
        self.released = False
        self.pit_exit_t = None
        self.limiter_off_said = False
        self.stop_had_tyres = False
        # drivers
        self.sof_said = False
        self.near_said = {}
        self.watch = None
        self.watch_lc = None
        # health
        self.ew = 0
        self.hot = False
        self.rep_seen = None
        self.lap_thr_max = 0.0
        self.pedal_said = False
        self.overlap_since = None
        self.rpm_prev = 0.0
        # fuel
        self.window_said = False
        self.target_said = None
        self.grid_checked = False
        # practice traffic
        self.lap_kind = None
        self.dist_prev = {}
        self.found_space_said = False
        self.rubber = None
        # timing
        self.sec_marks = []         # [(lap, sector, time)]
        self.sec_t0 = None
        self.sec_cur = None
        self.sec_hist = {1: [], 2: [], 3: []}
        self.sec_best = {}
        self.lap_dirty = False
        self.sector_said_lap = -99
        # weather
        self.track_said = None
        self.air_said = None
        self.wind_said = 0.0
        self.weather_t = 0.0
        self.on_since = None
        self.moving_t = -1e9
        # tyres
        self.set_start_lap = 0
        self.wear_rate = None
        self.wear_said_crit = False
        # radio
        self.timers = []            # [(due_time or None, due_lap or None)]

    # ------------------------------------------------------------------ every tick
    def tick(self):
        b = self.b
        now = b.clock()
        try:
            self.pitlane(now)
            self.health_fast(now)
            if now - self.t_slow >= 0.5:
                self.t_slow = now
                self.drivers_near(now)
                self.watch_lap()
                self.practice_traffic(now)
                self.weather(now)
                self.radio_timers(now)
                self.grid_fuel()
            self.sectors(now)
            lc = self.g("LapCompleted", -1)
            if lc is not None and lc >= 0 and lc != self.prev.get("lc"):
                first = "lc" not in self.prev
                self.prev["lc"] = lc
                if not first:
                    self.lap_done(lc)
        except Exception as e:
            b.log(f"[extras] {e!r}")

    def lap_done(self, lc):
        self.fuel_extras(lc)
        self.pedal_lap()
        self.tyre_lap(lc)
        self.lap_readout()
        self.radio_timers(self.b.clock(), lap=lc)
        self.lap_thr_max = 0.0

    # ================================================================== 1 pit lane
    def pitlane(self, now):
        if not self.s("calls_pitlane"):
            return
        b = self.b
        me = b.me()
        onp = bool(self.g("OnPitRoad", False))
        ew = int(self.g("EngineWarnings", 0) or 0)
        lim = bool(ew & W_LIMITER)
        spd = self.g("Speed", 0) or 0
        surf = self.at("CarIdxTrackSurface", me, TS_ON)
        plim = b.pit_limit_ms()
        # coming into the pits without the limiter
        # (not on the way OUT: the pit exit road also reads "approaching pits" - 2026-10-24 replay test)
        just_out = self.pit_exit_t and now - self.pit_exit_t < 45
        if surf == TS_APPROACH and not onp and not lim and plim and spd > plim + 3 and not just_out:
            self.say("limiter_on", prio=PRIO_URGENT, cooldown=25)
        # out of the pits with the limiter still on
        was = self.prev.get("onp", onp); self.prev["onp"] = onp
        if was and not onp:
            self.pit_exit_t = now; self.limiter_off_said = False
            self.stall_said = False
        # only just after the exit: later the limiter is on for a reason (next pit entry, behind the pace car)
        if not onp and self.pit_exit_t and 4 < now - self.pit_exit_t < 20 and lim and not self.limiter_off_said \
                and self.g("IsOnTrack", False) and surf != TS_APPROACH:
            self.limiter_off_said = True
            self.say("limiter_off", prio=PRIO_URGENT)
        if onp and not was:
            self.stall_said = False
            if b.is_race() and b.green_seen and not b.finished:   # 2026-10-29: after the flag there's no "we come out P3"
                b.later(1.5, lambda: self.predict_exit(say=True, entering=True))
        # pit stall coming up
        stall = (b.info("DriverInfo", {}) or {}).get("DriverPitTrkPct")
        pct = self.g("LapDistPct", -1)
        if onp and stall is not None and pct is not None and pct >= 0 and not self.stall_said:
            d = ((float(stall) - pct) % 1.0) * b.track_len_m()
            if 40 < d < 110 and not self.g("PlayerCarInPitStall", False):
                self.stall_said = True
                self.say("stall_close", prio=PRIO_RACE, max_age=4)
        # in the box: repairs, countdown, release
        inst = bool(self.g("PlayerCarInPitStall", False))
        rep = float(self.g("PitRepairLeft", 0) or 0)
        opt = float(self.g("PitOptRepairLeft", 0) or 0)
        if inst and self.in_stall_since is None:
            self.in_stall_since, self.released, self.rep_counted = now, False, set()
            self.stop_had_tyres = bool(int(self.g("PitSvFlags", 0) or 0) & (F_LF | F_RF | F_LR | F_RR))
            self.stop_rep0 = rep
            self.tyre_stall()
            if rep > 25:
                b.later(1.0, lambda: self.say("repair_long", {"n": round(rep)}, prio=PRIO_URGENT))
                b.later(6.0, lambda: self.say("eng_off", prio=PRIO_RACE))       # DRE parity D7 (2026-10-24)
            elif rep > 0.5:
                b.later(1.0, lambda: self.say("b2_repairs_underway", {"n": round(rep)}, prio=PRIO_URGENT))
        if inst and self.stop_rep0 > 12:
            for mark in (10, 5):
                if rep <= mark < rep + 1.0 and mark not in self.rep_counted and rep > 0:
                    self.rep_counted.add(mark)
                    self.say("repair_left", {"n": mark}, prio=PRIO_URGENT, max_age=2)
        sv = int(self.g("PlayerCarPitSvStatus", 0) or 0)
        if inst and not self.released and now - (self.in_stall_since or now) > 1.5 and (sv == 2 or (sv == 0 and rep <= 0 and self.stop_rep0 > 0)):
            self.released = True
            self.say("stop_go_go", prio=PRIO_URGENT, max_age=3)
        if not inst and self.in_stall_since is not None:
            still = now - self.in_stall_since
            self.in_stall_since = None
            if self.stop_had_tyres:
                self.set_start_lap = self.g("LapCompleted", 0) or 0
                self.wear_said_crit = False
            if still > 3 and b.is_race():
                b.later(6, lambda: self.say("b2_stop_time", {"n": round(still)}, prio=PRIO_INFO))

    def stop_model(self):
        b = self.b
        try:
            from . import strategy as S
            car = self.driver(b.me()).get("CarPath")
            track = (b.info("WeekendInfo", {}) or {}).get("TrackName")
            m = S.model(car, track) if car and track else None
            return m, S
        except Exception:
            return None, None

    def predict_exit(self, say=True, entering=False):
        """Where we come out if we box now (or the stop we're doing now). Returns (P, car, ahead_of) or None."""
        b = self.b
        me = b.me()
        m, S = self.stop_model()
        f = int(self.g("PitSvFlags", 0) or 0)
        fuel_add = float(self.g("PitSvFuel", 0) or 0) if f & F_FUEL else 0.0
        tyres = bool(f & (F_LF | F_RF | F_LR | F_RR))
        rep = float(self.g("PitRepairLeft", 0) or 0)
        if m and S:
            loss = S.stop_time(m, fuel_add, tyres) + rep
        else:
            loss = 28.0 + max(fuel_add / 2.4, 22.0 if tyres else 0.0, 4.0) + rep
        if entering:
            loss = max(10.0, loss - 3.0)          # part of the lane is already behind us
        cid, _ = b.my_class()
        mp = b.class_pos(me)
        mf = b.f2(me)
        if not mp or mf is None:
            if say and not entering:            # asked: answer; automatic call on pit entry: stay quiet
                self.say("tb_no_data", prio=PRIO_URGENT)
            return None
        onp = self.arr("CarIdxOnPitRoad")
        passed = 0
        for i in b.class_cars(cid):
            if i == me or (i < len(onp) and onp[i]):
                continue
            fi = b.f2(i)
            if fi is not None and 0 < fi - mf < loss:
                passed += 1
        newp = mp + passed
        # who's on the road next to us at pit exit
        best = None
        for i in b.drivers():
            if i == me or (i < len(onp) and onp[i]) or self.at("CarIdxTrackSurface", i, TS_ON) != TS_ON:
                continue
            tg = self.track_gap(i)
            if tg is None or tg <= 0:
                continue
            if abs(tg - loss) < 2.5 and (best is None or abs(tg - loss) < abs(best[1] - loss)):
                best = (i, tg)
        if say:
            if best:
                ahead_of = best[1] > loss
                self.say("pit_out_ahead" if ahead_of else "pit_out_behind",
                         {"P": newp, "car": b.car_num(best[0])}, prio=PRIO_RACE)
                # who else is around the rejoin point (2026-10-24, DRE "who's near me after I pit")
                near = []
                for i in b.drivers():
                    if i in (me, best[0]) or (i < len(onp) and onp[i]) or self.at("CarIdxTrackSurface", i, TS_ON) != TS_ON:
                        continue
                    tg = self.track_gap(i)
                    if tg is not None and tg > 0 and abs(tg - loss) < 2.0:
                        near.append((abs(tg - loss), i))
                if near:
                    o = min(near)[1]
                    self.say("pit_out_near", {"car": [b.car_num(best[0]), b.car_num(o)]}, prio=PRIO_RACE)
            elif b.g("OnPitRoad", False):
                # 2026-10-25 (request: it said "if we box, we come out P8" while we were already on pit lane): already in -
                # "we come out P8"
                if not self.say("tb_pit_out", {"P": newp}, prio=PRIO_RACE):
                    self.say("pit_rejoin_pos", {"P": newp}, prio=PRIO_RACE)
            else:
                self.say("pit_rejoin_pos", {"P": newp}, prio=PRIO_RACE)
        return newp, (b.car_num(best[0]) if best else None), (best[1] > loss if best else None)

    # ================================================================== 2 pit requests by voice
    def pit_request(self, t):
        """Driver asked for something specific in the pit menu. True if handled."""
        b = self.b
        tt = " " + words_to_numbers(t) + " "
        if not re.search(r"tyre|tire|fuel|litre|liter|gallon|pressure|psi|fast repair|tear ?off|pit menu|"
                         r"wets|slicks|lefts|rights|fronts|rears|left side|right side|pit stop|no stop", tt):
            return False
        # a question is never a pit menu change ("do we have enough fuel to finish", "do we need new tyres")
        # ...but "can you / could you give us four tyres" is a polite order, even when the recogniser adds a "?"
        polite = re.match(r"\s*(please\s+)?(can|could|would|will) you\b", tt)
        if not polite and re.search(r"\?|^\s*(how|what|what'?s|when|where|which|who|why|is|are|have|has|was|were|"
                     r"(do|does|did|can|could|should|will|would|shall) (we|i|you|they|it|the|my|our))\b", tt):
            return False
        did = False
        if re.search(r"\b(clear|reset|empty)\b.{0,12}\b(pit|menu|stop)\b|\bclear (everything|all)\b", tt):
            self.pit_cmd("clear"); self.say("req_clear", prio=PRIO_URGENT); return True
        # tyres
        tyre_words = r"(tyres?|tires?|wheels?)"
        sets = [(r"\bno (new )?" + tyre_words + r"|\bkeep (the )?" + tyre_words + r"|don'?t change (the )?" + tyre_words + r"|without " + tyre_words, 6, []),
                (r"\bleft(s| side| hand side)\b|\bleft " + tyre_words, 2, ["lf", "lr"]),
                (r"\bright(s| side| hand side)\b|\bright " + tyre_words, 3, ["rf", "rr"]),
                (r"\bfronts?\b.{0,8}" + tyre_words + r"|\bfronts\b|\bfront (left and right|pair)\b", 4, ["lf", "rf"]),
                (r"\brears?\b.{0,8}" + tyre_words + r"|\brears\b", 5, ["lr", "rr"]),
                (r"\b(four|4|all|all four|full set( of)?|new) " + tyre_words + r"|\bfour new\b|\ball four\b", 1, ["lf", "rf", "lr", "rr"])]
        press = re.search(r"(pressures?|psi|kpa)\b", tt)
        # a request, not a complaint ("the rear tyres are gone" is a note for the crew, not a menu change)
        asks = re.search(r"\b(change|new|fit|put|take|give|want|need|only|box|swap|do|let'?s|go with|request|"
                         r"no|keep|don'?t|without|four|4|all|just|please)\b", tt)
        if not press and asks:
            for pat, var, cs in sets:
                if re.search(pat, tt):
                    self.pit_cmd("clear_tires")
                    for c in cs:
                        self.pit_cmd(c, 0)
                    self.say("req_tyres", {"_variant": var}, prio=PRIO_URGENT)
                    did = True
                    break
        if not asks:
            pass
        elif re.search(r"\b(wets|wet (tyres?|tires?)|rain (tyres?|tires?)|inters)\b", tt):
            idx = self.compound_index(wet=True)
            if idx is not None:
                self.pit_cmd("tc", idx); self.say("req_compound", {"_variant": 1}, prio=PRIO_URGENT); did = True
        elif re.search(r"\b(slicks|dry (tyres?|tires?)|drys)\b", tt):
            idx = self.compound_index(wet=False)
            if idx is not None:
                self.pit_cmd("tc", idx); self.say("req_compound", {"_variant": 2}, prio=PRIO_URGENT); did = True
        # pressures (only with a tyre change in iRacing)
        if press:
            m = re.search(r"\b(up|plus|raise|increase|add|more|down|minus|lower|drop|decrease|less|reduce)\b\D{0,12}(\d+(\.\d+)?)?", tt)
            if m:
                amt = float(m.group(2)) if m.group(2) else 1.0
                down = m.group(1) in ("down", "minus", "lower", "drop", "decrease", "less", "reduce")
                which = ["lf", "rf", "lr", "rr"]
                if re.search(r"\bfronts?\b", tt): which = ["lf", "rf"]
                elif re.search(r"\brears?\b", tt): which = ["lr", "rr"]
                elif re.search(r"\blefts?\b", tt): which = ["lf", "lr"]
                elif re.search(r"\brights?\b", tt): which = ["rf", "rr"]
                # "up one" = one step of Settings > Calls > Pressure step; saying "psi" / "kpa" means exactly that
                if re.search(r"kpa", tt):
                    kpa, shown = amt, amt
                elif re.search(r"psi", tt):
                    kpa, shown = amt * PSI, amt
                else:
                    step = float(self.s("press_step", 1.0) or 1.0)
                    unit_kpa = 1.0 if self.s("press_unit", "psi") == "kpa" else PSI
                    kpa, shown = amt * step * unit_kpa, amt * step
                kpa_step = kpa * (-1 if down else 1)
                cur = self.pressures()
                for c in which:
                    if cur.get(c):
                        self.pit_cmd(c, round(cur[c] + kpa_step))
                self.say("req_press", {"dec": shown, "_variant": 2 if down else 1}, prio=PRIO_URGENT)
                did = True
        # fuel
        if re.search(r"\bno fuel\b|don'?t (add|put) (any )?fuel|without fuel|zero fuel", tt):
            self.pit_cmd("clear_fuel"); self.say("req_no_fuel", prio=PRIO_URGENT); did = True
        elif re.search(r"fuel (to|until|for) the (end|finish)|enough fuel|fuel to finish|fill (it )?to the end|finish the race", tt):
            need = self.fuel_to_end()
            if need is None:
                self.say("tb_no_data", prio=PRIO_URGENT)
            elif need < 0.5:
                self.pit_cmd("clear_fuel"); self.say("req_no_fuel", prio=PRIO_URGENT)
            else:
                self.pit_cmd("fuel", max(1, round(need)))
                self.say("req_fuel_end", {"n": round(self.fuel_units(need)), "fuel unit": 2}, prio=PRIO_URGENT)
            did = True
        elif re.search(r"\b(fill (it |her )?up|full tank|full fuel|brim)\b", tt):
            tank = self.tank()
            have = self.g("FuelLevel", 0) or 0
            if tank:
                add = max(1, tank - have)
                self.pit_cmd("fuel", round(add))
                self.say("req_fuel_add", {"n": round(self.fuel_units(add)), "fuel unit": 2}, prio=PRIO_URGENT)
            did = True
        elif re.search(r"\bfuel (for|to do|to last)\D{0,6}\d+\s*(more )?laps?\b", tt):
            # "fuel for 10 laps" = enough for 10 laps, not 10 litres
            n_laps = int(re.search(r"\bfuel (for|to do|to last)\D{0,6}(\d+)", tt).group(2))
            fl, have = self.fuel_per_lap(), self.g("FuelLevel", 0) or 0
            if not fl:
                self.say("tb_no_data", prio=PRIO_URGENT)
            else:
                add = (n_laps + 0.5) * fl - have
                tank = self.tank()
                if tank:
                    add = min(add, tank - have)
                if add < 0.5:
                    self.pit_cmd("clear_fuel"); self.say("req_no_fuel", prio=PRIO_URGENT)
                else:
                    self.pit_cmd("fuel", max(1, round(add)))
                    self.say("req_fuel_add", {"n": round(self.fuel_units(add)), "fuel unit": 2}, prio=PRIO_URGENT)
            did = True
        else:
            m = re.search(r"(\d+(\.\d+)?)\s*(litres?|liters?|l\b|gallons?|gal\b)", tt)
            n = unit = None
            if m:
                n, unit = float(m.group(1)), m.group(3)
            elif "fuel" in tt:
                m2 = re.search(r"\b(add|put in|fuel)\b\D{0,10}(\d+(\.\d+)?)", tt)
                if m2:
                    n, unit = float(m2.group(2)), ""
            if n:
                gal = unit.startswith("g") if unit else not self.metric()
                litres = n * GAL if gal else n
                self.pit_cmd("fuel", max(1, round(litres)))
                shown = round(self.fuel_units(litres))      # read back in the sim's display units ("fuel unit" follows them)
                self.say("req_fuel_add", {"n": shown, "fuel unit": 2 if shown != 1 else 1}, prio=PRIO_URGENT)
                did = True
        # fast repair / tear-off
        if re.search(r"fast repair", tt):
            off = re.search(r"\b(no|off|don'?t|without|cancel)\b.{0,6}fast repair|fast repair (off|no)\b", tt)
            self.pit_cmd("clear_fr" if off else "fr")
            self.say("req_fast_repair", {"_variant": 2 if off else 1}, prio=PRIO_URGENT); did = True
        if re.search(r"tear ?off|windscreen|visor|clean the screen", tt):
            off = re.search(r"\b(no|off|don'?t|without|cancel)\b.{0,6}(tear ?off|windscreen)|tear ?off (off|no)\b", tt)
            self.pit_cmd("clear_ws" if off else "ws")
            self.say("req_tearoff", {"_variant": 2 if off else 1}, prio=PRIO_URGENT); did = True
        return did

    def compound_index(self, wet):
        tires = (self.b.info("DriverInfo", {}) or {}).get("DriverTires") or []
        for tr in tires:
            kind = str(tr.get("TireCompoundType", "")).lower()
            if ("wet" in kind or "rain" in kind) == wet:
                return int(tr.get("TireIndex", 0))
        return None

    def pressures(self):
        out = {}
        for c, k in (("lf", "PitSvLFP"), ("rf", "PitSvRFP"), ("lr", "PitSvLRP"), ("rr", "PitSvRRP")):
            v = self.g(k)
            if not v:
                dp = self.g(f"dp{c.upper()}TireColdPress")
                v = dp / 1000 if dp and dp > 1000 else dp
            out[c] = v
        return out

    def tank(self):
        di = self.b.info("DriverInfo", {}) or {}
        if getattr(self.b, "electric", False):
            return None                             # electric car (car parity E15): no fuel tank
        try:
            return float(di.get("DriverCarFuelMaxLtr")) * float(di.get("DriverCarMaxFuelPct") or 1)
        except (TypeError, ValueError):
            return None

    def fuel_per_lap(self):
        return self.b.fuel_lap_est()                # this session, or your usual here from earlier sessions

    def fuel_to_end(self):
        fl, ltg = self.fuel_per_lap(), self.b.laps_to_go()
        if not fl or not ltg:
            return None
        have = self.g("FuelLevel", 0) or 0
        pct = self.g("LapDistPct", 0) or 0
        at_stop = max(0.0, have - fl * max(0.0, 1 - pct))
        need = (ltg + 0.5 + float(getattr(self.b.s, "fuel_buffer_laps", 0) or 0)) * fl - at_stop   # + fuel buffer (D10)
        tank = self.tank()
        if tank:
            need = min(need, tank - at_stop)
        return max(0.0, need)

    # ================================================================== 3 other drivers
    def car_from_text(self, tt):
        """'car 44' / 'number 7' / 'the car ahead|behind' / 'leader' -> idx or None"""
        b = self.b
        m = re.search(r"\b(car|number|#)\s*(\d{1,3})\b", tt)
        if m:
            return self.num_to_idx(m.group(2))
        ahead, _, behind, _ = b.neighbours()
        if re.search(r"\b(ahead|in front|front)\b", tt):
            return ahead
        if re.search(r"\bbehind\b", tt):
            return behind
        if re.search(r"\bleader\b", tt):
            cid, _ = b.my_class()
            return next((i for i in b.class_cars(cid) if b.class_pos(i) == 1), None)
        return None

    def drv_info(self, idx):
        if idx is None:
            return self.say("tb_no_data", prio=PRIO_URGENT)
        d = self.driver(idx)
        lic, sr = lic_parts(d.get("LicString"))
        ir = d.get("IRating")
        if not ir or not lic:
            return self.say("tb_no_data", prio=PRIO_URGENT)
        self.say("drv_info", {"car": d.get("CarNumber"), "n": ir, "lic": lic, "dec": sr if sr is not None else 0},
                 prio=PRIO_URGENT)

    def class_field(self):
        """[(idx, iRating)] for my class, starters only."""
        b = self.b
        cid, _ = b.my_class()
        out = []
        for i in b.class_cars(cid):
            d = self.driver(i)
            if d.get("CarIsAI"):
                continue
            out.append((i, int(d.get("IRating") or 0)))
        return out

    def sof_value(self):
        f = self.class_field()
        return sof([r for _, r in f]) if len(f) >= 2 else None

    def irating_now(self, pos=None):
        b = self.b
        f = self.class_field()
        me = b.me()
        idxs = [i for i, _ in f]
        if me not in idxs or len(f) < 2 or not any(r for _, r in f):
            return None
        pos = pos or b.class_pos(me)
        if not pos:
            return None
        irs = [r if r else 1350 for _, r in f]
        return irating_change(irs, idxs.index(me), min(pos, len(irs)))

    def irating_target(self):
        b = self.b
        n = len(self.class_field())
        for p in range(n, 0, -1):
            c = self.irating_now(p)
            if c is not None and c >= 0:
                return p
        return None

    def mark(self, idx, on=True):
        if idx is None:
            return self.say("tb_no_data", prio=PRIO_URGENT)
        d = self.driver(idx)
        uid = str(d.get("UserID") or d.get("CustID") or d.get("UserName") or "")
        if not uid:
            return self.say("tb_no_data", prio=PRIO_URGENT)
        if on:
            self.marks[uid] = {"name": d.get("UserName", ""), "car": d.get("CarNumber"), "at": time.time()}
        else:
            self.marks.pop(uid, None)
        self._save_marks()
        self.say("mark_ok" if on else "unmark_ok", {"car": d.get("CarNumber")}, prio=PRIO_URGENT)

    def _load_marks(self):
        return marks()

    def _save_marks(self):
        save_marks()

    def is_marked(self, d):
        uid = str(d.get("UserID") or d.get("CustID") or d.get("UserName") or "")
        return bool(uid) and uid in self.marks

    def drivers_near(self, now):
        b = self.b
        if not self.g("IsOnTrack", False) or self.g("OnPitRoad", False) or b.alone():
            return
        # strength of field once per race, on the formation lap
        if b.is_race() and not self.sof_said and self.g("SessionState", 0) == 3 and self.s("calls_drivers"):
            v = self.sof_value()
            if v:
                self.sof_said = True
                b.later(40, lambda: self.say("sof", {"n": int(round(v, -1))}, prio=PRIO_INFO))
        me = b.me()
        for i, d in b.drivers().items():
            if i == me or self.at("CarIdxTrackSurface", i, TS_ON) != TS_ON:
                continue
            tg = self.track_gap(i)
            if tg is None or abs(tg) > 1.5:
                continue
            behind = tg > 0
            key = (i, behind)
            if self.is_marked(d) and self.s("calls_drivers"):
                if now - self.near_said.get(("m",) + key, -1e9) > 120:
                    self.near_said[("m",) + key] = now
                    self.say("marked_near", {"car": d.get("CarNumber"), "_variant": 1 if behind else 2},
                             prio=PRIO_RACE, max_age=5)
                continue
            if b.is_race() and self.s("low_sr_warn") and d.get("CarClassID") == self.driver(me).get("CarClassID"):
                lic, sr = lic_parts(d.get("LicString"))
                below = float(self.s("low_sr_below", 2.0) or 0)
                rookie = self.s("low_sr_rookies", False) and lic == "R"
                low = (rookie or (sr is not None and sr < below)) and not d.get("CarIsAI")
                # once per car per session (2026-10-24: it repeated every few minutes in a busy field)
                if low and ("s", i) not in self.near_said:
                    self.near_said[("s", i)] = now
                    self.say("low_sr_near", {"car": d.get("CarNumber"), "_variant": 1 if behind else 2},
                             prio=PRIO_INFO, max_age=5)

    def watch_lap(self):
        """'Keep me updated on car 44': one line each time that car finishes a lap."""
        if self.watch is None:
            return
        i = self.watch
        lc = self.at("CarIdxLapCompleted", i)
        if lc is None or lc == self.watch_lc:
            return
        self.watch_lc = lc
        t = self.at("CarIdxLastLapTime", i)
        mf, fi = self.b.f2(self.b.me()), self.b.f2(i)
        gap = abs(fi - mf) if mf is not None and fi is not None else None
        if t and t > 0 and gap is not None:
            self.say("watch_report", {"car": self.b.car_num(i), "gap": gap, "time": t}, prio=PRIO_INFO, max_age=20)

    # ================================================================== 4 car health
    def health_fast(self, now):
        b = self.b
        ew = int(self.g("EngineWarnings", 0) or 0)
        rise = lambda m: (ew & m) and not (self.ew & m)
        on = self.g("IsOnTrack", False) and not self.g("OnPitRoad", False)
        spd = self.g("Speed", 0) or 0
        rpm = float(self.g("RPM", 0) or 0)
        # the warning lights are all on with the engine off (sitting in the garage / on the grid before engine start):
        # only listen once the car has been driven, and for the stall only if we were moving a moment ago
        if spd > 10:
            self.moving_t = now
        driving = on and now - getattr(self, "moving_t", -1e9) < 8
        if self.s("calls_health") and driving and rpm > 800:
            if rise(W_WATER) or rise(W_OILT):
                self.hot = True
                self.say("engine_hot", prio=PRIO_RACE, cooldown=120)
            elif self.hot and not (ew & (W_WATER | W_OILT)):
                self.hot = False
                self.say("engine_ok", prio=PRIO_INFO, cooldown=120)
            if rise(W_OILP):
                self.say("oil_low", prio=PRIO_RACE, cooldown=120)
            if rise(W_FUELP):
                self.say("fuel_pressure", prio=PRIO_RACE, cooldown=120)
        if self.s("calls_health") and driving and rise(W_STALL) and spd < 3:
            self.say("stalled", prio=PRIO_URGENT, cooldown=10)
        self.ew = ew
        # damage after a hit
        rep = float(self.g("PitRepairLeft", 0) or 0) + float(self.g("PitOptRepairLeft", 0) or 0)
        if self.rep_seen is None:
            self.rep_seen = rep
        elif rep > self.rep_seen + 1.0 and on and self.s("calls_health"):
            r = rep
            self.say("damage_report", {"n": round(r)}, prio=PRIO_RACE, cooldown=20)
            self.rep_seen = rep
        elif rep < self.rep_seen:
            self.rep_seen = rep
        # pedals
        if on and spd > 15:
            thr = self.g("ThrottleRaw", self.g("Throttle", 0)) or 0
            brk = self.g("BrakeRaw", self.g("Brake", 0)) or 0
            self.lap_thr_max = max(self.lap_thr_max, thr)
            if brk > 0.2 and thr > 0.9 and spd > 30:
                self.overlap_since = self.overlap_since or now
                if now - self.overlap_since > 3 and self.s("calls_health"):
                    self.say("pedal_stuck", prio=PRIO_RACE, cooldown=600)
            else:
                self.overlap_since = None
        # shift beep - never during replays (2026-10-27, request: "turn off shift beep during replays only")
        if self.s("shift_beep", False) and not self.g("IsReplayPlaying", False):
            self.shift_beep()

    def pedal_lap(self):
        b = self.b
        if self.pedal_said or not self.s("calls_health"):
            return
        t = self.g("LapLastLapTime", -1) or -1
        if t > 0 and b.lap_times and 0.05 < self.lap_thr_max < 0.95 and len(b.lap_times) >= 2:
            self.pedal_said = True
            self.say("pedal_check", prio=PRIO_INFO)

    def shift_beep(self):
        di = self.b.info("DriverInfo", {}) or {}
        try:
            srpm = float(di.get("DriverCarSLShiftRPM") or 0)
            top = int(di.get("DriverCarGearNumForward") or 0)
        except (TypeError, ValueError):
            return
        rpm = float(self.g("RPM", 0) or 0)
        gear = int(self.g("Gear", 0) or 0)
        srpm *= float(self.s("shift_point", 1.0) or 1.0)
        # 2026-10-26 (request: "it's late, it's coming in a little too high"): the beep takes ~0.12 s to reach the ears
        # (sound chain) and the driver needs a moment to react, so it fires when the revs WILL reach the shift point
        # in shift_lead seconds, from how fast they're climbing right now
        now = time.time()
        dt = max(1e-3, now - getattr(self, "_rpm_t", now - 0.016))
        self._rpm_t = now
        rate = max(0.0, (rpm - self.rpm_prev) / dt) if self.rpm_prev else 0.0
        rate = min(rate, 8000.0)
        pred = rpm + rate * float(self.s("shift_lead", 0.18) or 0.0)
        prev_pred = getattr(self, "_pred_prev", 0.0)
        if (srpm > 0 and 1 <= gear < top and prev_pred < srpm <= pred and rpm < srpm * 1.02
                and (self.g("Throttle", 0) or 0) > 0.8 and now - getattr(self, "_beep_t", 0) > 0.6):
            self._beep_t = now
            self.beep()
        self._pred_prev = pred if gear == getattr(self, "_gear_prev", gear) else 0.0
        self._gear_prev = gear
        self.rpm_prev = rpm

    def beep(self):
        play_beep(self.b.s)

    def damage_answer(self):
        rep = float(self.g("PitRepairLeft", 0) or 0) + float(self.g("PitOptRepairLeft", 0) or 0)
        if rep > 0.5:
            self.say("damage_report", {"n": round(rep)}, prio=PRIO_URGENT)
        else:
            self.say("car_fine", prio=PRIO_URGENT)

    def engine_answer(self):
        ew = int(self.g("EngineWarnings", 0) or 0)
        if ew & (W_WATER | W_OILT):
            self.say("engine_hot", prio=PRIO_URGENT)
        elif ew & W_OILP:
            self.say("oil_low", prio=PRIO_URGENT)
        elif ew & W_FUELP:
            self.say("fuel_pressure", prio=PRIO_URGENT)
        else:
            self.say("engine_ok", prio=PRIO_URGENT)

    # ================================================================== 5 fuel extras
    def fuel_extras(self, lc):
        b = self.b
        if not b.is_race() or not b.green_seen or not self.s("calls_fuel_extras"):
            return
        fl, ltg, tank = self.fuel_per_lap(), b.laps_to_go(), self.tank()
        if not fl or not ltg or len(b.fuel_laps) < 2:
            return
        fuel = self.g("FuelLevel", 0) or 0
        have = fuel / fl
        # one stop from here reaches the end: the window is open
        if have < ltg - 0.3 and tank and (ltg + 0.5) * fl - fuel <= tank and not self.window_said:
            self.window_said = True
            self.say("b2_pit_window_opens", prio=PRIO_RACE)
        # just short: give a target per lap
        st = b.prev.get("fuel_state")
        if st == "short" and have >= ltg - 1.5:
            target = fuel / (ltg + 0.15)
            shown = round(self.fuel_units(target), 2 if not self.metric() else 1)
            if self.target_said is None or abs(shown - self.target_said) >= (0.05 if not self.metric() else 0.1):
                if self.say("fuel_target", {"dec": shown, "fuel unit": 2}, prio=PRIO_RACE, cooldown=180):
                    self.target_said = shown

    def fuel_target_answer(self):
        b = self.b
        ltg = b.laps_to_go()
        if not ltg:
            return self.say("tb_no_data", prio=PRIO_URGENT)
        fuel = self.g("FuelLevel", 0) or 0
        target = fuel / (ltg + 0.15)
        self.say("fuel_target", {"dec": round(self.fuel_units(target), 2 if not self.metric() else 1), "fuel unit": 2},
                 prio=PRIO_URGENT)

    def grid_fuel(self):
        """On the formation lap: is there enough fuel in the car for the first stint?"""
        b = self.b
        if self.grid_checked or not b.is_race() or self.g("SessionState", 0) != 3 or not self.s("calls_fuel_extras"):
            return
        self.grid_checked = True
        m, _ = self.stop_model()
        fl = (m or {}).get("fuel_lap")
        tank = self.tank()
        fuel = self.g("FuelLevel", 0) or 0
        if not fl or not tank or fuel <= 0.5:        # replays/spectating report an empty tank: no false alarm
            return
        race_laps = None
        laps = str(b.session().get("SessionLaps", ""))
        if laps.isdigit():
            race_laps = int(laps)
        else:
            try:
                race_laps = float(str(b.session().get("SessionTime", "")).split()[0]) / self.lap_est() + 1
            except (ValueError, IndexError):
                pass
        if not race_laps:
            return
        want = min(race_laps + 0.5, tank / fl)          # the whole race, or a full tank's worth
        if fuel / fl < want - 1.5:
            self.say("grid_low_fuel", prio=PRIO_RACE)

    # ================================================================== 6 practice / qualifying traffic
    def practice_traffic(self, now):
        b = self.b
        if b.is_race() or b.alone() or not self.s("calls_practice_traffic"):
            return
        if not self.g("IsOnTrack", False) or self.g("OnPitRoad", False):
            self.dist_prev = {}
            return
        me = b.me()
        spd = max(10.0, self.g("Speed", 0) or 0)
        L = b.track_len_m()
        pm = self.at("CarIdxLapDistPct", me, -1)
        if pm < 0:
            return
        kind = self.lap_kind
        dists = {}
        for i in b.drivers():
            if i == me or self.at("CarIdxTrackSurface", i, TS_ON) != TS_ON or self.at("CarIdxOnPitRoad", i, False):
                continue
            pi = self.at("CarIdxLapDistPct", i, -1)
            if pi < 0:
                continue
            d = (pm - pi) % 1.0
            if d > 0.5:
                d -= 1.0
            dists[i] = d * L                      # + behind me, - ahead of me (metres)
        for i, d in dists.items():
            p = self.dist_prev.get(i)
            if p is None:
                continue
            dt = now - p[1]
            if dt <= 0:
                continue
            closing = (p[0] - d) / dt if d > 0 else (d - p[0]) / dt   # m/s towards me (behind) / me towards him (ahead)
            secs = abs(d) / spd
            warn = float(self.s("traffic_warn", 2.5) or 2.5)
            if d > 0 and kind in ("out", "cool") and secs < warn and closing > 2.0:
                self.say("b2_car_on_push_lap_behind_you", prio=PRIO_RACE, cooldown=40, key=f"pushbehind{i}", max_age=3)
            elif d < 0 and kind == "push" and secs < warn + 1.5 and closing > 3.0:
                self.say("b2_push_lap_traffic_ahead", prio=PRIO_RACE, cooldown=30, max_age=3)
        self.dist_prev = {i: (d, now) for i, d in dists.items()}
        # out lap: is there space behind us?
        if kind == "out" and not self.found_space_said and (self.g("LapDistPct", 0) or 0) > 0.15:
            behind = [d / spd for d in dists.values() if 0 < d / spd < 3.0]
            if behind:
                self.found_space_said = True
                self.say("b2_out_lap_find_space", {"gap": min(behind)}, prio=PRIO_INFO, max_age=5)
        # track rubbering in
        r = str(b.session().get("SessionTrackRubberState", "") or "").lower()
        order = [("moderately low", 2), ("moderately high", 4), ("moderate", 3), ("clean", 0), ("low", 1), ("high", 5), ("max", 6)]
        lvl = next((k for w, k in order if w in r), None)
        if lvl is not None:
            if self.rubber is not None and lvl > self.rubber:
                self.say("b2_track_getting_faster_rubber", prio=PRIO_INFO, cooldown=900)
            self.rubber = lvl

    def lap_kind_update(self):
        """At the start of each lap: out lap (left the pits), push lap, or cool-down."""
        b = self.b
        if self.pit_exit_t and b.clock() - self.pit_exit_t < self.lap_est() * 0.9:
            self.lap_kind = "out"
            self.found_space_said = False
            return
        ok = self.g("LapDeltaToBestLap_OK", False)
        dlt = self.g("LapDeltaToBestLap", 0) or 0
        last = self.g("LapLastLapTime", -1) or -1
        if b.best and last > 0 and last > b.best + 4:
            self.lap_kind = "cool"
        else:
            self.lap_kind = "push" if (not ok or dlt < 1.5) else "cool"

    # ================================================================== 7 timing, weather, tyres
    def sectors(self, now):
        """My three sectors (thirds of the lap): loss against my usual, and green sectors on a push lap."""
        b = self.b
        if not self.g("IsOnTrack", False):
            self.sec_cur = None
            return
        pct = self.g("LapDistPct", -1)
        st = self.g("SessionTime", None)
        if pct is None or pct < 0 or st is None:
            return
        sec = min(3, int(pct * 3) + 1)
        if self.g("OnPitRoad", False) or b.caution_on:
            self.lap_dirty = True
        if self.sec_cur is None:
            self.sec_cur, self.sec_t0 = sec, st
            self.lap_dirty = True
            return
        if sec == self.sec_cur:
            return
        done = self.sec_cur
        valid = (sec == done % 3 + 1)              # moved forward exactly one sector
        t = st - self.sec_t0
        self.sec_cur, self.sec_t0 = sec, st
        if done == 3:
            self.lap_kind_update()
        if not valid or self.lap_dirty or t <= 1:
            if done == 3:
                self.lap_dirty = bool(self.g("OnPitRoad", False))
            return
        hist = self.sec_hist[done]
        if len(hist) >= 3 and self.s("calls_sectors"):
            med = sorted(hist[-8:])[len(hist[-8:]) // 2]
            lc = self.g("LapCompleted", 0) or 0
            if b.is_race() and t > med + float(self.s("sector_alert", 0.35) or 0.35) and t < med + 5 and lc - self.sector_said_lap >= 3:
                self.sector_said_lap = lc
                self.say("sector_off", {"sector": done, "n": min(50, round((t - med) * 10))}, prio=PRIO_INFO,
                         max_age=8)
            elif not b.is_race() and self.lap_kind == "push" and done in self.sec_best and t < self.sec_best[done] - 0.05:
                self.say("b2_push_lap_sector_good", {"sector": done}, prio=PRIO_INFO, cooldown=15, max_age=4)
        hist.append(t)
        self.sec_best[done] = min(t, self.sec_best.get(done, 1e9))
        if done == 3:
            self.lap_dirty = False

    def lap_readout(self):
        """Settings: what to read out every lap (lap time, position, fuel, gaps). Off by default."""
        b = self.b
        what = getattr(b.s, "lap_readout", None) or []
        if not what or b.caution_on:
            return
        t = self.g("LapLastLapTime", -1) or -1
        if "time" in what and t > 0:
            self.say("ans_time", {"time": t}, prio=PRIO_INFO, max_age=15)
        if "position" in what and b.class_pos(b.me()):
            self.say("ans_position", {"P": b.class_pos(b.me())}, prio=PRIO_INFO, max_age=15)
        if "fuel" in what and b.fuel_laps:
            fl = self.fuel_per_lap()
            if fl:
                self.say("b2_fuel_per_lap", {"n": round(self.fuel_units(fl)), "fuel unit": 2}, prio=PRIO_INFO, max_age=15)
        if "gaps" in what and b.is_race():
            _, ga, _, gb = b.neighbours()
            if ga is not None and gb is not None:
                self.say("gaps_each_lap", {"gap": [ga, gb]}, prio=PRIO_INFO, max_age=15)

    def temp_units(self, c):
        return c if self.metric() else c * 9 / 5 + 32

    def weather(self, now):
        b = self.b
        if not self.s("calls_weather") or not self.g("IsOnTrack", False):
            return
        if now - self.weather_t < 10:
            return
        self.weather_t = now
        # the sim settles its temperatures in the first minute of a session: baseline after that
        self.on_since = getattr(self, "on_since", None) or now
        if now - self.on_since < 60:
            return
        tt, at, wv = self.g("TrackTempCrew"), self.g("AirTemp"), self.g("WindVel")
        if tt is not None:
            if self.track_said is None:
                self.track_said = tt
            elif abs(tt - self.track_said) >= 3:
                up = tt > self.track_said
                if self.say("b2_track_temperature_rising" if up else "b2_track_temperature_falling", prio=PRIO_INFO,
                            cooldown=300, key="trk_temp"):
                    self.track_said = tt
                    b.later(4, lambda: self.say("track_temp", {"n": round(self.temp_units(tt))}, prio=PRIO_INFO))
        if at is not None:
            if self.air_said is None:
                self.air_said = at
            elif abs(at - self.air_said) >= 4:
                if self.say("air_temp", {"n": round(self.temp_units(at))}, prio=PRIO_INFO, cooldown=600):
                    self.air_said = at
        if wv is not None and wv >= 7 and wv >= self.wind_said + 3:
            kmh = wv * 3.6
            if self.say("wind_strong", {"n": round(kmh if self.metric() else kmh / 1.609)}, prio=PRIO_INFO, cooldown=900):
                self.wind_said = wv

    def weather_answer(self):
        tt, at, wv = self.g("TrackTempCrew"), self.g("AirTemp"), self.g("WindVel")
        if tt is None:
            return self.say("tb_no_data", prio=PRIO_URGENT)
        if self.g("WeatherDeclaredWet"):
            self.say("track_temp", {"n": round(self.temp_units(tt))}, prio=PRIO_URGENT)
        else:
            self.say("b2_weather", {"n": round(self.temp_units(tt))}, prio=PRIO_URGENT)
        if at is not None:
            self.say("air_temp", {"n": round(self.temp_units(at))}, prio=PRIO_URGENT)
        if wv is not None and wv >= 5:
            kmh = wv * 3.6
            self.say("wind_strong", {"n": round(kmh if self.metric() else kmh / 1.609)}, prio=PRIO_URGENT)

    # tyres: iRacing only shows wear when the car is in the pit box, so we learn wear per lap there
    def tyre_stall(self):
        wear = self.tyre_wear()
        if not wear:
            return
        laps = (self.g("LapCompleted", 0) or 0) - self.set_start_lap
        worst_c, worst = min(wear.items(), key=lambda kv: kv[1])
        if laps >= 3 and worst < 99:
            self.wear_rate = (100 - worst) / laps
        if laps >= 3 and self.s("calls_tyres"):
            if worst < 75:
                self.b.later(3, lambda: self.say("b2_wear_report_one_tire_worn",
                                                 {"tyre corner": worst_c, "percent": round(worst)}, prio=PRIO_INFO))
            else:
                self.b.later(3, lambda: self.say("b2_wear_report_all_good", prio=PRIO_INFO))

    def tyre_wear(self):
        out = {}
        for c, name in (("LF", "front left"), ("RF", "front right"), ("LR", "rear left"), ("RR", "rear right")):
            vs = [self.g(f"{c}wear{p}") for p in "LMR"]
            vs = [v for v in vs if v is not None]
            if vs:
                out[name] = min(vs) * (100 if max(vs) <= 1.0 else 1)
        return out

    def tyre_est(self):
        if not self.wear_rate:
            return None
        laps = (self.g("LapCompleted", 0) or 0) - self.set_start_lap
        return max(0.0, 100 - self.wear_rate * laps)

    def tyre_lap(self, lc):
        est = self.tyre_est()
        if est is not None and est <= 30 and not self.wear_said_crit and self.s("calls_tyres") and self.b.is_race():
            self.wear_said_crit = True
            self.say("tyres_critical", {"percent": round(est)}, prio=PRIO_RACE)

    def tyre_answer(self):
        est = self.tyre_est()
        laps = (self.g("LapCompleted", 0) or 0) - self.set_start_lap
        if est is not None:
            self.say("tyres_left", {"percent": round(est)}, prio=PRIO_URGENT)
        if laps > 0:
            self.say("b2_laps_on_these_tires", {"laps": laps}, prio=PRIO_URGENT)
        elif est is None:
            self.say("tb_no_data", prio=PRIO_URGENT)

    # ================================================================== 8 radio extras
    def radio_timers(self, now, lap=None):
        # the radio thread appends timers while the brain thread runs this: remove in place, never rebind the list
        for tm in list(self.timers):
            due_t, due_lap = tm
            if (due_t is not None and now >= due_t) or (due_lap is not None and lap is not None and lap >= due_lap):
                try:
                    self.timers.remove(tm)
                except ValueError:
                    continue
                self.say("timer_done", prio=PRIO_URGENT)

    def say_again(self):
        last = self.b.v.last_said
        if not last:
            return self.say("tb_no_data", prio=PRIO_URGENT)
        sid, fills = last
        self.say("b2_repeat_last_message", prio=PRIO_URGENT)
        self.b.v.say(sid, fills, PRIO_URGENT)

    def time_now(self):
        lt = time.localtime()
        h = lt.tm_hour % 12 or 12
        self.say("time_now", {"time": h * 60 + lt.tm_min}, prio=PRIO_URGENT)

    def chat(self, msg):
        """Type a message into iRacing's chat (opens chat, types, Enter)."""
        ir = getattr(self.b.src, "ir", None)
        if ir is None or getattr(ir, "fake", False) or not _sim_in_front():
            # never type anywhere but iRacing's own window (keys go to whatever window is in front)
            self.b.log(f"[chat] not sent, iRacing isn't the window in front: {msg}")
            self.say("tb_no_data", prio=PRIO_URGENT)
            return
        def run():
            try:
                import irsdk
                ir.chat_command(irsdk.ChatCommandMode.begin_chat)
                time.sleep(0.25)
                if _sim_in_front():
                    _type_text(msg + "\n")
                    self.b.log(f"[chat] {msg}")
            except Exception as e:
                self.b.log(f"[chat] {e!r}")
        threading.Thread(target=run, daemon=True).start()
        self.say("chat_sent", prio=PRIO_URGENT)

    # ================================================================== radio: free text with numbers / cars
    def command(self, text):
        """Requests that carry a value (car number, litres, minutes, a chat message). True if handled."""
        from .intents import normalize
        t = " " + normalize(text).strip() + " "
        tt = " " + words_to_numbers(t) + " "
        b = self.b
        # chat
        if self.s("chat_enabled", True) and re.search(r"\b(send|chat|type in chat|tell (them|everyone|everybody))\b", tt):
            for pat, msg in CHAT:
                if re.search(pat, tt):
                    self.chat(msg); return True
        # timers / reminders
        m = re.search(r"\b(timer|remind me|reminder)\b\D{0,20}(\d+(\.\d+)?)\s*(minutes?|mins?|laps?)", tt)
        if m:
            n = float(m.group(2))
            if m.group(4).startswith("lap"):
                self.timers.append((None, (self.g("LapCompleted", 0) or 0) + int(n)))
                self.say("timer_set", {"n": int(n), "_variant": 2}, prio=PRIO_URGENT)
            else:
                self.timers.append((b.clock() + n * 60, None))
                self.say("timer_set", {"n": int(n), "_variant": 1}, prio=PRIO_URGENT)
            return True
        # mark / unmark drivers
        m = re.search(r"\b(un ?mark|clear the mark|remove the mark|mark)\b", tt)
        if m and re.search(r"\b(car|number|ahead|behind|front|him|driver|leader)\b", tt):
            idx = self.car_from_text(tt)
            if idx is None and re.search(r"\bhim\b", tt):
                ahead, ga, behind, gb = b.neighbours()
                idx = behind if (gb or 99) < (ga or 99) else ahead
            self.mark(idx, on=not m.group(1).replace(" ", "").startswith("un") and "clear" not in m.group(1)
                      and "remove" not in m.group(1))
            return True
        # keep me updated on car X
        if re.search(r"(keep me (updated|posted)|updates? on|keep an eye on)\b.{0,20}\b(car|number|ahead|behind|leader)"
                     r"|\bwatch (car|number) \d|\bwatch the (leader|car (ahead|behind))", tt):
            idx = self.car_from_text(tt)
            if idx is None:
                self.say("tb_no_data", prio=PRIO_URGENT); return True
            self.watch, self.watch_lc = idx, self.at("CarIdxLapCompleted", idx)
            self.say("watch_ok", {"car": b.car_num(idx)}, prio=PRIO_URGENT)
            return True
        if re.search(r"\b(stop|no more|cancel)\b.{0,12}\b(updates?|watching|following)\b|\bupdates? off\b", tt):
            self.watch = None
            self.say("watch_off", prio=PRIO_URGENT)
            return True
        # about another car: lap time / iRating / incidents
        if re.search(r"\b(car|number) \d{1,3}\b|\b(car|guy|driver) (ahead|behind|in front)\b|\bleader\b", tt):
            idx = self.car_from_text(tt)
            if re.search(r"i ?rating|license|licence|safety rating|\bsr\b|who is|who's|what is .* rating", tt):
                self.drv_info(idx); return True
            if re.search(r"incident|\bx\b|how clean|dirty", tt):
                if idx is None:
                    self.say("tb_no_data", prio=PRIO_URGENT); return True
                n = self.driver(idx).get("CurDriverIncidentCount")
                if n is None or n < 0:
                    rc = getattr(b, "rcft", None)             # official races hide them: say how often he's been off
                    offs = rc.est_offs(idx) if rc else 0
                    self.say("est_inc", {"car": b.car_num(idx), "n": offs}, prio=PRIO_URGENT) if rc else self.say("tb_no_data", prio=PRIO_URGENT)
                else:
                    self.say("car_inc", {"car": b.car_num(idx), "n": n, "_variant": 2 if n == 1 else 1}, prio=PRIO_URGENT)
                return True
            if re.search(r"lap ?time|last lap|what did|doing|pace|running", tt) and idx is not None:
                lt = self.at("CarIdxLastLapTime", idx)
                if not lt or lt <= 0:
                    self.say("tb_no_data", prio=PRIO_URGENT)
                else:
                    self.say("car_lap", {"car": b.car_num(idx), "time": lt}, prio=PRIO_URGENT)
                return True
        # pit menu requests
        if self.pit_request(t):
            return True
        return False

    # ================================================================== radio: plain questions (intents)
    def answer(self, intent):
        """Intents added in v62. True if handled."""
        b = self.b
        A = lambda sid, f=None: self.say(sid, f, prio=PRIO_URGENT)
        if intent == "say_again":
            self.say_again(); return True
        if intent == "time_now":
            self.time_now(); return True
        if intent == "who_ahead":
            self.drv_info(b.neighbours()[0]); return True
        if intent == "who_behind":
            self.drv_info(b.neighbours()[2]); return True
        if intent == "sof":
            v = self.sof_value()
            A("sof", {"n": int(round(v, -1))}) if v else A("tb_no_data"); return True
        if intent == "irating":
            c = self.irating_now()
            if c is None:
                A("tb_no_data")
            elif abs(c) < 0.5:
                A("irating_even")
            else:
                A("irating_gain", {"n": abs(round(c)), "_variant": 1 if c > 0 else 2})
            return True
        if intent == "irating_target":
            p = self.irating_target()
            A("irating_target", {"P": p}) if p else A("tb_no_data"); return True
        if intent == "damage":
            self.damage_answer(); return True
        if intent == "engine":
            self.engine_answer(); return True
        if intent == "pit_out":
            self.predict_exit(say=True); return True
        if intent == "fuel_target":
            self.fuel_target_answer(); return True
        if intent == "fuel_per_lap":
            fl = self.fuel_per_lap()
            A("b2_fuel_per_lap", {"n": round(self.fuel_units(fl)), "fuel unit": 2}) if fl else A("tb_no_data"); return True
        if intent == "weather":
            self.weather_answer(); return True
        if intent == "tyres":
            self.tyre_answer(); return True
        if intent == "best_sector":
            if not self.sec_best:
                A("tb_no_data")
            else:
                # the sector where my best is closest to my usual = where I'm strongest
                rel = {k: (sorted(v)[len(v) // 2] - self.sec_best[k]) for k, v in self.sec_hist.items() if v}
                A("b2_best_sector", {"sector": min(rel, key=rel.get)})
            return True
        if intent == "pit_loss":
            m, S = self.stop_model()
            A("b2_pit_stop_time_loss", {"n": round(m["lane_loss"])}) if m else A("tb_no_data"); return True
        if intent == "fastest":
            cid, _ = b.my_class()
            bests = self.arr("CarIdxBestLapTime")
            cand = [(bests[i], i) for i in b.class_cars(cid) if i < len(bests) and bests[i] and bests[i] > 0]
            if not cand:
                A("tb_no_data")
            else:
                t, i = min(cand)
                A("b2_who_is_fastest_right_now", {"car": b.car_num(i), "time": t})
            return True
        if intent == "leader_gap":
            cid, _ = b.my_class()
            ld = next((i for i in b.class_cars(cid) if b.class_pos(i) == 1), None)
            mf = b.f2(b.me())
            if ld is None or ld == b.me() or mf is None or b.f2(ld) is None:
                A("tb_no_data")
            else:
                A("b2_gap_to_the_class_leader", {"gap": mf - b.f2(ld)})
            return True
        return False


# ---------------------------------------------------------------------- typing into iRacing's chat (Windows)
def _sim_in_front():
    """True only when the iRacing simulator window is the one in front (where typed keys will land)."""
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        return buf.value.startswith("iRacing.com Simulator")
    except Exception:
        return False


def _type_text(text):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    KEYEVENTF_UNICODE, KEYEVENTF_KEYUP = 0x0004, 0x0002
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def send(vk=0, scan=0, flags=0):
        i = INPUT(type=1)
        i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))

    for ch in text:
        if ch == "\n":
            send(vk=0x0D); send(vk=0x0D, flags=KEYEVENTF_KEYUP)
        else:
            send(scan=ord(ch), flags=KEYEVENTF_UNICODE); send(scan=ord(ch), flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        time.sleep(0.012)


def play_beep(settings):
    """Shift beep with the Race Control page's pitch / volume / length. Volume is hard-capped at 0.6
    and the tone has soft edges, so it can never click or blast (2026-10-24). 2026-10-26 (request: "way too quiet"): cap 1.0."""
    try:
        import numpy as np, sounddevice as sd
        sr = 24000
        hz = min(4000, max(200, int(getattr(settings, "shift_pitch", 1400) or 1400)))
        vol = min(1.0, max(0.0, float(getattr(settings, "shift_volume", 0.25) or 0)))
        ms = min(400, max(20, int(getattr(settings, "shift_length", 60) or 60)))
        n = int(sr * ms / 1000)
        t = np.arange(n) / sr
        edge = max(1, int(sr * 0.006))
        env = np.minimum(1, np.minimum(np.arange(n), n - 1 - np.arange(n)) / edge)
        x = (vol * np.sin(2 * np.pi * hz * t) * env).astype(np.float32)
        sd.play(x, sr, device=getattr(settings, "device", None) or None, blocking=False)
    except Exception:
        pass


def play_radio_click(settings, down=True):
    """2026-10-26 (request: "the radio when I press the button has no beep"): a short radio key-up chirp when the radio
    button goes down and a lower "roger" chirp with a little squelch when it comes up. Soft edges, volume capped."""
    if not getattr(settings, "radio_beep", True):
        return
    try:
        import numpy as np, sounddevice as sd
        sr = 24000
        vol = min(0.45, 0.28 * max(0.5, min(2.0, float(getattr(settings, "volume", 1.0) or 1.0))))
        def tone(f0, f1, ms):
            n = int(sr * ms / 1000); t = np.arange(n) / sr
            f = np.linspace(f0, f1, n); ph = 2 * np.pi * np.cumsum(f) / sr
            edge = max(1, int(sr * 0.005))
            env = np.minimum(1, np.minimum(np.arange(n), n - 1 - np.arange(n)) / edge)
            return np.sin(ph) * env
        gap = np.zeros(int(sr * 0.025))
        if down:
            x = np.concatenate([tone(1250, 1250, 45), gap, tone(1650, 1650, 55)])
        else:
            sq = np.random.default_rng().standard_normal(int(sr * 0.06)) * 0.25
            sq *= np.linspace(1, 0, sq.size) ** 2
            x = np.concatenate([tone(1650, 1150, 80), sq])
        sd.play((vol * x).astype(np.float32), sr, device=getattr(settings, "device", None) or None, blocking=False)
    except Exception:
        pass


class RaceControl:
    """Race director calls (2026-10-24, moved here from the developer's SimHub add-on): practice / qualifying
    when the session loads; in a race: go to the grid (get in car), formation lap, green flag.
    Each once per session. Plays the user's own clips from CrewChiefVoices\\RaceControl."""

    def __init__(self, brain):
        self.b = brain
        self.session = None
        self.done = set()
        self.min_state = 99

    def tick(self):
        b = self.b
        if not getattr(b.s, "race_control", True):
            return
        n = b.g("SessionNum", -1)
        if n != self.session:
            self.session, self.done, self.min_state = n, set(), 99
            # ic169 (2026-10-31, Angelo: "dont let the race director voice play on load in, we are already in a session,
            # it does not need to repeat"): what race control already said is remembered per session (event id +
            # session number) on disk, so reloading into the same session or restarting the app doesn't say it again
            self.key = self._key(n)
            self.done |= set(self._said().get(self.key, []))
            # loading into a session that is already running (it started more than a minute and a half ago): its
            # opening calls were already made - nothing from race control until something new happens
            try:
                if float(b.g("SessionTime", 0) or 0) > 90:
                    self.done |= {"practice", "qualifying", "gotogrid", "formation"}
                    self._remember()
            except Exception:
                pass
        st = (b.sess_type or "").lower()
        state = int(b.g("SessionState", 0) or 0)
        if state > 0:
            self.min_state = min(self.min_state, state)
        if "race" in st:
            # only calls we actually got to see: joining (or a replay jumping) into a running race
            # doesn't announce a green flag that happened minutes ago
            for want, name in ((1, "gotogrid"), (3, "formation"), (4, "green")):
                if state == want and self.min_state <= want and (want == 1 or self.min_state < want):
                    self.play(name, once_before=("formation", "green") if name == "gotogrid" else
                              ("green",) if name == "formation" else ())
        elif "qual" in st:
            self.play("qualifying")
        elif "practice" in st or "test" in st:
            self.play("practice")

    _FILE = os.path.join(os.environ.get("LOCALAPPDATA", "."), "RaceEngineer", "rc_said.json")

    def _key(self, n):
        try:
            wi = self.b.info("WeekendInfo", {}) or {}
            return f"{wi.get('SubSessionID') or wi.get('SessionID') or 0}:{n}"
        except Exception:
            return f"0:{n}"

    def _said(self):
        try:
            import json
            return json.load(open(self._FILE, encoding="utf-8"))
        except Exception:
            return {}

    def _remember(self):
        try:
            import json
            d = self._said()
            d[getattr(self, "key", "0:0")] = sorted(self.done)
            if len(d) > 60:
                for k in list(d)[:-60]:
                    d.pop(k, None)
            os.makedirs(os.path.dirname(self._FILE), exist_ok=True)
            json.dump(d, open(self._FILE, "w", encoding="utf-8"))
        except Exception:
            pass

    def play(self, name, once_before=()):
        if name in self.done or any(x in self.done for x in once_before):
            return
        # 2026-10-25 (request: "race control should always be heard right at the moment they trigger ... except if they
        # interrupt the intro full screen part"): while Grandstand's full-screen intro runs, wait (checked every tick);
        # a call that has gone out of date meanwhile (the next one is due) is dropped by once_before
        if _grandstand_intro():
            return
        self.done.add(name)
        self._remember()
        self.b.v.rc_volume = float(getattr(self.b.s, "race_control_volume", 0.8) or 0)
        # top priority: cuts whatever the engineer / strategist is saying, and the rest waits until it's done
        self.b.v.say_now("rc:" + name)

_intro_cache = [0.0, False]
def _grandstand_intro():
    """True while Grandstand's full-screen intro (the grid opener) is playing. Asked at most twice a second; no
    Grandstand running = False."""
    import time as _t, json as _j, urllib.request as _u
    now = _t.time()
    if now - _intro_cache[0] < 0.5:
        return _intro_cache[1]
    _intro_cache[0] = now
    try:
        _intro_cache[1] = bool(_j.loads(_u.urlopen("http://127.0.0.1:8790/api/state", timeout=0.3).read()).get("intro"))
    except Exception:
        _intro_cache[1] = False
    return _intro_cache[1]
