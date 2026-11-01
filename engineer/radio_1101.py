"""ic188 (#740): the radio calls Angelo approved on 2026-11-01 (sheets claude/engineer-lines-725 / -722 / -702).

Lines: engineer/lines_new.py APPROVED_1101 (on the render list; the stand-in voice says them until they are rendered).
Everything here reads data iRacing really gives (SessionState / SessionFlags, CarIdx* arrays, SolarAltitude,
TrackTempCrew, TrackWetness, PlayerTireCompound, PlayerCarInPitStall, SessionTimeRemain...). Every group has its own
switch (Settings); the ones on by default are once-a-race / once-a-stint calls on plain data, rate-limited.

Rules every call here keeps (brain.py / voice.py do the rest - the talk gate holds speech at the brake point and while
someone is on voice chat, lines older than max_age are dropped):
  * race sessions only, after the green, never while being towed, never in the pit lane or the stall (except the
    "drink" at a pit stop, which is a pit-stop call), never in the quiet part of lap 1 (ic185) or the first 20 s
  * at most one of these chat lines every CHAT_GAP_S seconds (the hazard and read-back calls don't wait), so a busy
    moment never stacks more than ~3 topics
  * each call has a once-per-race / once-per-stint / per-car guard

Groups (setting -> calls)                                   default
  calls_short_lines    #702 shorter versions of long calls  ON  (only once the short versions are RENDERED)
  calls_hazard         A5 car stopped / slow ahead          ON  (racecraft.slow_cars, existing detection)
  calls_start_brief    B1 formation warm-up, B2 on the grid ON
  calls_night          A6 lights at dusk, D5a first dark lap, D5b track cooling   ON
  calls_drink          E1 drink at stops + every ~15 min    ON
  calls_last_30        E2 last 30 minutes                   ON
  calls_rest_after     E4 rest before driving, after a race ON
  calls_dunlop         B3 "brake early into Dunlop"         OFF (said into the ic185 lap-1 quiet; Le Mans only)
  calls_class_traffic  A1 class traffic into [corner], A2 GT ahead in the Porsche Curves   OFF
  calls_let_go         A4 faster car behind, let him go     OFF
  calls_caution_plan   D3 "if there's a yellow, we box / stay out"   OFF
  calls_rain_plan      D4b wets now, D4c wet set-up, D4d drying       OFF
  calls_readback       D6 "Box this lap. Confirm." / "Copy." (needs the copy button)  OFF
Not wired (lines recorded for later): A3 (iRacing doesn't say WHICH car is alongside, or inside / outside),
D1 (no measured tyre-degradation number to weigh against the tyre-change time), D4a (iRacing gives no
minutes-to-rain forecast in the live data).
"""
from .voice import PRIO_URGENT, PRIO_RACE, PRIO_INFO, PRIO_CHAT

CHAT_GAP_S = 45.0          # one of these calls at most every 45 s
DRINK_EVERY_S = 15 * 60.0
DUSK_RAD = 0.0             # sun at the horizon: lights on
DARK_RAD = -0.08           # ~ -4.6 deg: properly dark (crowd.py calls night below -0.03)
COOL_DROP_C = 4.0          # track this much cooler than at dusk = "track's cooling"
RACE_2H40_S = 9600.0

DEFAULTS = {
    "calls_short_lines": True, "calls_hazard": True, "calls_start_brief": True, "calls_night": True,
    "calls_drink": True, "calls_last_30": True, "calls_rest_after": True,
    "calls_dunlop": False, "calls_class_traffic": False, "calls_let_go": False, "calls_caution_plan": False,
    "calls_rain_plan": False, "calls_readback": False,
}

# #702: old sid -> its shorter versions (used only once those are rendered - until then the old recording plays)
SHORT = {
    "leader_pitting": "s_leader_pitting", "car_ahead_pitting": "s_car_ahead_pitting", "fuel_ok": "s_fuel_ok",
    "halfway": "s_halfway", "b2_halfway_in_a_long_race": "s_b2_halfway", "half_fuel_ok": "s_half_fuel_ok",
    "b2_hours_left": "s_hours_left", "lost_place": "s_lost_place", "pit_exit": "s_pit_exit",
    "rejoin_pits": "s_rejoin_pits", "rolling_start": "s_rolling_start", "one_minute": "s_one_minute",
    "minutes_ask": "s_minutes", "leader_finished": "s_leader_finished", "fuel_short": "s_fuel_short",
    "pace_consistent": "s_pace_consistent", "five_min_podium": "s_five_min_podium",
    "b2_one_hour_left": "s_one_hour_left", "incident_close": "s_incident_close",
    "b2_tiredness_check": "s_tiredness_check", "engine_hot": "s_engine_hot",
}
# calls that tell him to box: the read-back (D6) waits for his "copy" after these
BOX_SIDS = {"bf_box", "box_wets", "box_call", "rl_wets_now"}


def setting(b, k):
    return bool(getattr(b.s, k, DEFAULTS.get(k, False)))


def short_sid(b, sid, fills):
    """#702: the shorter version of a long call, once it is rendered (and the switch is on). -> (sid, fills)"""
    alt = SHORT.get(sid)
    if not alt or not setting(b, "calls_short_lines"):
        return sid, fills
    if alt not in (getattr(b.v, "lines", None) or {}):
        return sid, fills                     # not recorded yet: the old line, never the stand-in (the sheet's rule)
    if fills and "_variant" in fills:         # a variant number meant for the old line
        fills = {k: v for k, v in fills.items() if k != "_variant"}
    return alt, fills


def _num(x):
    try:
        return float(str(x).split()[0])
    except (ValueError, IndexError, TypeError):
        return None


class Calls1101:
    BOX_SIDS = BOX_SIDS

    def __init__(self, brain):
        self.b = brain
        self.last_v = {}          # sid -> last variant said (rotation across races too)
        self.reset()

    # ------------------------------------------------------------------ helpers
    def reset(self):
        self.sess = None
        self.done = set()         # once-per-session keys
        self.last_chat = -1e9
        self.state_prev = None
        self.grid_t = None
        self.form_t = None
        self.lc_prev = None
        self.sa_prev = None
        self.saw_day = False
        self.dusk_t = None
        self.dusk_tt = None
        self.drink_t = None
        self.stall_prev = False
        self.t30 = None
        self.fin_t = None
        self.stint_said = False
        self.stint_lap0 = None
        self.onp_prev = None
        self.trf_seen = {}
        self.behind_since = {}
        self.let_seen = {}
        self.wet_hi_t = self.wet_lo_t = None
        self.on_wets_prev = None
        self.pit_exit_t = None
        self.copy_wait = None     # (due time, origin) after a box call
        self.copy_asked_t = None
        self.copy_said = False

    def g(self, k, d=None):
        return self.b.g(k, d)

    def on(self, k):
        return setting(self.b, k)

    def towing(self):
        from . import voice as _v
        return bool(_v.TOWING)

    def in_pits(self):
        return bool(self.g("OnPitRoad", False) or self.g("PlayerCarInPitStall", False))

    def racing(self):
        """Race, after the green, not finished, out on track at speed, not towed, not in the pits, not the start."""
        b = self.b
        if not b.is_race() or not b.green_seen or b.finished or self.towing():
            return False
        if not self.g("IsOnTrack", False) or self.in_pits() or (self.g("Speed", 0) or 0) < 15:
            return False
        if b._lap1_quiet() or (b.green_t and b.clock() - b.green_t < 20):
            return False
        return True

    def caution(self):
        from .brain import F_CAUTION, F_CAUTION_WAVING
        return bool(getattr(self.b, "caution_on", False)) or bool(int(self.g("SessionFlags", 0) or 0) & (F_CAUTION | F_CAUTION_WAVING))

    def pick(self, sid, allowed):
        """Rotate the versions: never the one said last time when there is a choice."""
        last = self.last_v.get(sid)
        opts = [v for v in allowed if v != last] or list(allowed)
        import random
        v = random.choice(opts)
        self.last_v[sid] = v
        return v

    def chat_ok(self):
        return self.b.clock() - self.last_chat >= CHAT_GAP_S

    def say(self, sid, fills=None, prio=PRIO_INFO, max_age=15, variants=None, chat=True):
        f = dict(fills or {})
        if variants:
            f["_variant"] = self.pick(sid, variants)
        ok = self.b.say(sid, f, prio=prio, max_age=max_age)
        if ok and chat:
            self.last_chat = self.b.clock()
        return ok

    def race_len_s(self):
        return _num(self.b.session().get("SessionTime"))

    # ------------------------------------------------------------------ every tick
    def tick(self):
        b = self.b
        if b.sess_num != self.sess:
            self.reset(); self.sess = b.sess_num
        now = b.clock()
        state = self.g("SessionState", 0) or 0
        ps, self.state_prev = self.state_prev, state
        lc = self.g("LapCompleted", -1)
        new_lap = self.lc_prev is not None and lc is not None and lc > self.lc_prev
        if lc is not None and lc >= 0:
            self.lc_prev = lc
        onp = self.in_pits()
        if self.onp_prev and not onp:
            self.pit_exit_t = now
            self.stint_said, self.stint_lap0 = False, lc
        self.onp_prev = onp
        if self.stint_lap0 is None and b.green_seen:
            self.stint_lap0 = lc
        self.start_brief(now, state, ps)
        self.dunlop(now)
        self.night(now, new_lap)
        self.drink(now, new_lap)
        self.last_30(now)
        self.rest_after(now)
        self.class_traffic(now)
        self.let_go(now)
        self.caution_plan(new_lap, lc)
        self.rain_plan(now)
        self.readback(now)

    # ------------------------------------------------------------------ B1 / B2 grid and formation
    def start_brief(self, now, state, ps):
        b = self.b
        if not b.is_race():
            return
        if state == 1 and ps is not None and ps != 1:
            self.grid_t = now                 # only when we saw the grid open (joining late says nothing)
        if state == 3 and ps is not None and ps != 3:
            self.form_t = now
        if not self.on("calls_start_brief") or self.towing() or b.green_seen:
            return
        on_grid = self.g("IsOnTrack", False) and not self.in_pits()
        if self.grid_t is not None and state in (1, 2) and "B2" not in self.done and 20 <= now - self.grid_t < 50 and on_grid:
            self.done.add("B2")
            rl = self.race_len_s()
            vs = (1, 2, 3) if rl and abs(rl - RACE_2H40_S) <= 300 else (2, 3)      # "two hours forty" only when true
            self.say("rl_grid_clean", prio=PRIO_INFO, max_age=15, variants=vs, chat=False)
        if self.form_t is not None and state == 3 and "B1" not in self.done and 40 <= now - self.form_t < 70 and on_grid:
            self.done.add("B1")
            self.say("rl_form_warm", prio=PRIO_INFO, max_age=20, variants=(1, 2), chat=False)

    # ------------------------------------------------------------------ B3 Dunlop (Le Mans, off by default)
    def dunlop(self, now):
        b = self.b
        if not self.on("calls_dunlop") or "B3" in self.done or not b.is_race() or not b.green_seen or self.towing():
            return
        if not b.green_t or now - b.green_t > 4:
            return
        tn = str((b.info("WeekendInfo", {}) or {}).get("TrackName", "")).lower().replace(" ", "")
        if "lemans" not in tn or self.in_pits():
            return
        self.done.add("B3")
        self.say("rl_dunlop", prio=PRIO_URGENT, max_age=6, variants=(1, 2), chat=False)

    # ------------------------------------------------------------------ A6 / D5 night
    def night(self, now, new_lap):
        sa = self.g("SolarAltitude")
        if sa is None:
            return
        try:
            sa = float(sa)
        except (TypeError, ValueError):
            return
        prev, self.sa_prev = self.sa_prev, sa
        if sa > 0.02:
            self.saw_day = True
        tt = self.g("TrackTempCrew")
        if prev is not None and prev >= DUSK_RAD > sa and self.dusk_t is None and self.saw_day:
            self.dusk_t, self.dusk_tt = now, tt
        if self.dusk_tt is None and sa < DUSK_RAD and tt is not None and self.saw_day:
            self.dusk_tt = tt
        if not self.on("calls_night") or not self.racing():
            return
        # A6: once, as the sun goes down (only a race that started in daylight)
        if self.dusk_t is not None and "A6" not in self.done and now - self.dusk_t < 600 and self.chat_ok():
            if self.say("rl_lights_on", prio=PRIO_INFO, max_age=20, variants=(1, 2)):
                self.done.add("A6")
            return
        if not new_lap or not self.saw_day or sa >= DARK_RAD or not self.chat_ok():
            return
        # D5a: the first lap that is properly dark
        if "D5a" not in self.done:
            if self.say("rl_night_brake", prio=PRIO_INFO, max_age=20, variants=(1, 2)):
                self.done.add("D5a")
            return
        # D5b: the track has cooled since dusk
        if "D5b" not in self.done and tt is not None and self.dusk_tt is not None and tt <= self.dusk_tt - COOL_DROP_C:
            if self.say("rl_track_cooling", prio=PRIO_INFO, max_age=20, variants=(1, 2)):
                self.done.add("D5b")

    # ------------------------------------------------------------------ E1 drink
    def drink(self, now, new_lap):
        b = self.b
        stall = bool(self.g("PlayerCarInPitStall", False))
        rise, self.stall_prev = stall and not self.stall_prev, stall
        if not self.on("calls_drink") or not b.is_race() or not b.green_seen or b.finished or self.towing():
            return
        last = self.drink_t if self.drink_t is not None else (b.green_t or now)
        if rise and (self.drink_t is None or now - self.drink_t > 300):
            # at the stop: the one call allowed in the pit box that isn't about the stop itself (the sheet: "each pit stop")
            self.drink_t = now
            b.later(4.0, lambda: self.say("rl_drink", prio=PRIO_CHAT, max_age=10, variants=(1, 2, 3), chat=False)
                    if self.g("PlayerCarInPitStall", False) else None)
            return
        if new_lap and now - last >= DRINK_EVERY_S and self.racing() and self.chat_ok():
            # crossing the line = on the pit straight; under a caution too (the best time to drink)
            if self.say("rl_drink", prio=PRIO_CHAT, max_age=10, variants=(1, 2, 3)):
                self.drink_t = now

    # ------------------------------------------------------------------ E2 last 30 minutes
    def last_30(self, now):
        b = self.b
        if not self.on("calls_last_30") or "E2" in self.done or not b.is_race() or not b.green_seen or b.finished:
            return
        lap_based = 0 <= (self.g("SessionLapsRemainEx", 32767) or 32767) < 32000
        rl = self.race_len_s()
        if lap_based or not rl or rl < 3600:
            return
        tr = self.g("SessionTimeRemain", -1)
        if tr is None or tr < 0:
            return
        if self.t30 is None:
            if 1500 < tr <= 1800:
                self.t30 = now                # the 30-minute call goes first; this follows ~20 s later
            elif tr <= 1500:
                self.done.add("E2")           # joined (or restarted) after the moment: nothing
            return
        if now - self.t30 > 300:
            self.done.add("E2"); return
        if now - self.t30 < 20 or not self.racing() or not self.chat_ok():
            return
        vs = (1,) if b.prev.get("fuel_state") == "ok" else (2,)     # "Last stint" only when we make it on fuel
        if self.say("rl_last_30", prio=PRIO_INFO, max_age=20, variants=vs):
            self.done.add("E2")

    # ------------------------------------------------------------------ E4 after the race
    def rest_after(self, now):
        b = self.b
        if not self.on("calls_rest_after") or "E4" in self.done or not b.is_race() or not b.finished:
            return
        if self.fin_t is None:
            self.fin_t = now
            rl = self.race_len_s()
            ran = (now - b.green_t) if b.green_t else 0
            if not ((rl and rl >= 2400) or ran >= 2400):     # an endurance-length race (40 min +)
                self.done.add("E4")
            return
        if now - self.fin_t >= 60 and not self.towing():
            self.done.add("E4")
            self.say("rl_rest_after", prio=PRIO_CHAT, max_age=60, variants=(1, 2), chat=False)

    # ------------------------------------------------------------------ A1 / A2 class traffic ahead (off)
    def class_traffic(self, now):
        b = self.b
        if not self.on("calls_class_traffic") or not self.racing() or self.caution() or b.alone():
            return
        if now - self.trf_seen.get("_t", -1e9) < 0.5:
            return
        self.trf_seen["_t"] = now
        drv, me = b.drivers(), b.me()
        mine = drv.get(me, {})
        my_est = mine.get("CarClassEstLapTime") or 0
        pct = self.g("CarIdxLapDistPct") or []
        surf = self.g("CarIdxTrackSurface") or []
        onp = self.g("CarIdxOnPitRoad") or []
        if not my_est or me >= len(pct) or pct[me] is None or pct[me] < 0 or not b.c:
            return
        L = b.track_len_m()
        group = []
        for i, d in drv.items():
            if i == me or i >= len(pct) or pct[i] is None or pct[i] < 0 or d.get("CarClassID") == mine.get("CarClassID"):
                continue
            if (i < len(surf) and surf[i] != 3) or (i < len(onp) and onp[i]):
                continue
            est = d.get("CarClassEstLapTime") or 0
            ahead = ((pct[i] - pct[me]) % 1) * L
            if est > my_est * 1.03 and 250 < ahead < 900:
                group.append((ahead, i, d))
        if not group or not self.chat_ok():
            return
        if any(now - self.trf_seen.get(i, -1e9) < 90 for _, i, _ in group):
            for _, i, _ in group:
                self.trf_seen[i] = now
            return
        group.sort()
        first = group[0]
        corner = b.c.at(pct[first[1]] * L) or b.c.next_after(pct[first[1]] * L)
        if not corner:
            return
        for _, i, _ in group:
            self.trf_seen[i] = now
        from . import classes
        cls = classes.spoken(first[2]) or ""
        if "porsche" in str(corner).lower():
            self.say("rl_gt_curves", prio=PRIO_INFO, max_age=5, variants=(1, 2))         # A2
            return
        n = len(group)
        if n >= 2 and cls.upper().startswith("GT"):
            self.say("rl_traffic_into", {"n": n, "corner": corner}, prio=PRIO_INFO, max_age=5, variants=(3,))
        elif cls:
            self.say("rl_traffic_into", {"class": cls, "corner": corner}, prio=PRIO_INFO, max_age=5, variants=(1,))
        else:
            self.say("rl_traffic_into", {"corner": corner}, prio=PRIO_INFO, max_age=5, variants=(2,))

    # ------------------------------------------------------------------ A4 faster car behind (off)
    def let_go(self, now):
        b = self.b
        if not self.on("calls_let_go") or not self.racing() or self.caution() or b.alone():
            return
        drv, me = b.drivers(), b.me()
        mine = drv.get(me, {})
        my_est = mine.get("CarClassEstLapTime") or 0
        pct = self.g("CarIdxLapDistPct") or []
        spd = max(20.0, float(self.g("Speed", 0) or 0))
        if not my_est or me >= len(pct) or pct[me] is None or pct[me] < 0:
            return
        L = b.track_len_m()
        close = set()
        for i, d in drv.items():
            if i == me or i >= len(pct) or pct[i] is None or pct[i] < 0 or d.get("CarClassID") == mine.get("CarClassID"):
                continue
            est = d.get("CarClassEstLapTime") or 0
            behind_s = ((pct[me] - pct[i]) % 1) * L / spd
            if est and est < my_est * 0.97 and 0.05 < behind_s < 0.8:
                close.add(i)
        self.behind_since = {i: self.behind_since.get(i, now) for i in close}
        for i, t0 in self.behind_since.items():
            if now - t0 >= 8 and now - self.let_seen.get(i, -1e9) > 180 and self.chat_ok():
                self.let_seen[i] = now
                self.say("rl_let_him_go", prio=PRIO_RACE, max_age=4, variants=(1, 2, 3))
                return

    # ------------------------------------------------------------------ D3 caution plan (off)
    def caution_plan(self, new_lap, lc):
        b = self.b
        if not self.on("calls_caution_plan") or not new_lap or self.stint_said or self.caution() or not self.racing():
            return
        if self.stint_lap0 is None or lc is None or lc - self.stint_lap0 < 3 or not self.chat_ok():
            return
        per = b.fuel_lap_est()
        fuel = self.g("FuelLevel", 0) or 0
        ltg = b.fuel_laps_needed() or b.laps_to_go()
        di = b.info("DriverInfo", {}) or {}
        tank = (_num(di.get("DriverCarFuelMaxLtr")) or 0) * (_num(di.get("DriverCarMaxFuelPct")) or 1)
        if not per or ltg is None or tank <= 0 or fuel <= 0:
            return
        have = fuel / per
        if have >= ltg + 0.5:
            sid = "rl_yellow_stay"            # no stop needed: a yellow doesn't help
        elif fuel <= 0.6 * tank:
            sid = "rl_yellow_box"             # a stop is coming and the tank has room: a yellow is a cheap stop
        else:
            sid = "rl_yellow_stay"            # just filled up: stopping under a yellow wastes it
        if self.say(sid, prio=PRIO_INFO, max_age=15, variants=(1, 2)):
            self.stint_said = True

    # ------------------------------------------------------------------ D4 rain plan (off)
    def rain_plan(self, now):
        b = self.b
        if not self.on("calls_rain_plan") or not b.is_race() or not b.green_seen or b.finished:
            return
        wet = self.g("TrackWetness")
        comp = self.g("PlayerTireCompound")
        try:
            wi = b.x.compound_index(True)
        except Exception:
            wi = None
        if wet is None or comp is None or wi is None:
            return
        wet = int(wet)
        on_wets = int(comp) == wi
        was, self.on_wets_prev = self.on_wets_prev, on_wets
        self.wet_hi_t = (self.wet_hi_t or now) if wet >= 5 else None
        self.wet_lo_t = (self.wet_lo_t or now) if wet <= 2 else None
        if wet <= 2:
            self.done.discard("D4b")
        if wet >= 4:
            self.done.discard("D4d")
        if not on_wets:
            self.done.discard("D4c")
        if not self.racing() or self.caution():
            return
        if not on_wets and self.wet_hi_t and now - self.wet_hi_t >= 60 and "D4b" not in self.done \
                and self.g("WeatherDeclaredWet", False):
            self.done.add("D4b")
            self.say("rl_wets_now", prio=PRIO_RACE, max_age=10, variants=(1, 2))
        elif on_wets and "D4c" not in self.done and self.pit_exit_t and 15 <= now - self.pit_exit_t < 120 and self.chat_ok():
            self.done.add("D4c")
            self.say("rl_wet_setup", prio=PRIO_INFO, max_age=15, variants=(1, 2))
        elif on_wets and self.wet_lo_t and now - self.wet_lo_t >= 120 and "D4d" not in self.done and self.chat_ok():
            self.done.add("D4d")
            self.say("rl_drying", prio=PRIO_INFO, max_age=15, variants=(1, 2))

    # ------------------------------------------------------------------ D6 read-back (off; needs the copy button)
    def expect_copy(self, origin=""):
        """A box call went out: if he doesn't press "copy" within ~8 s, ask once."""
        if not self.on("calls_readback") or not self.b.is_race():   # ic189 (#744): race sessions only
            return
        self.copy_wait = (self.b.clock() + 8.0, origin)
        self.copy_said = False

    def readback(self, now):
        w = self.copy_wait
        if not w:
            return
        if self.g("OnPitRoad", False) or self.b.finished:
            self.copy_wait = None             # he's coming in: he heard it
            return
        if now >= w[0] and not self.copy_said:
            self.copy_said = True
            self.copy_asked_t = now
            if not self.towing():
                self.say("rl_confirm_box", prio=PRIO_RACE, max_age=6, variants=(1, 2), chat=False)
        elif self.copy_said and now - (self.copy_asked_t or now) > 25:
            self.copy_wait = None             # asked once - never again

    def copy(self):
        """The copy button (wheel binding "copy" or the iPad's Copy). True = handled (never 'didn't catch')."""
        if self.copy_wait and self.b.is_race():   # ic189 (#744): never outside a race (the button is his reset there)
            self.copy_wait = None
            self.say("rl_copy", prio=PRIO_URGENT, max_age=5, variants=(1, 2), chat=False)
        return True
