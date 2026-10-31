"""More radio questions (Batch E, 2026-10-24 - Requested: "the exhaustive list done so we dont have any more surprises").

Built from the row-by-row check of DRE's 857 voice commands: everything a solo GT3 / GTP driver would really ask
that we didn't answer yet.

  stint      how long into the stint, how long left on this fuel, how long the whole stint is, when it ends
  fuel       time left on fuel, use per minute, last lap, average, fuel for N laps / N minutes, save for N stops,
             am I in the fuel window, own fuel target (set / set to last lap / calls on / off / compare)
  other car  position overall / class, start and qualifying position, lap number, where on track, gap,
             best / average / median lap, last lap / best lap / five-lap delta vs me, improving or not,
             pit stops (count, last stop lap, last stop time, pit lane time, laps on tyres, stops vs me),
             tyre type, name, class, car, laps of the cars around me
  session    best lap overall, start position, pit speed limit, fast repairs left, cars in the race / my class,
             track length, setup name
  weather    is it raining, will it rain (this week's forecast), humidity, pressure, skies, wind, values at the
             start and the change since
  tyres      do I need tyres / when, which tyre is right now
  pit menu   fuel only, no service, full service, max fuel, take N litres / N laps of fuel off
  radio      stop talking (cut the current line), alerts off, timer left / cancel, remind me at a clock time,
             read back / clear my notes, debris, start checklist

Questions about another car read per-car data (CarIdx...), so they also work while watching a replay.
"""
from . import classes
import math, re, time
from statistics import median
from .voice import PRIO_URGENT, PRIO_INFO

GAL = 3.78541
DIRS = ["north", "north_east", "east", "south_east", "south", "south_west", "west", "north_west"]
SKIES = {0: "clear", 1: "partly_cloudy", 2: "mostly_cloudy", 3: "overcast"}


class AskMore:
    def __init__(self, brain):
        self.b = brain
        self.reset()

    # ------------------------------------------------------------------ helpers
    def g(self, k, d=None):
        return self.b.g(k, d)

    def arr(self, k):
        return self.g(k) or []

    def at(self, k, i, d=None):
        a = self.arr(k)
        return a[i] if i is not None and 0 <= i < len(a) and a[i] is not None else d

    def A(self, sid, f=None):
        self.b.say(sid, f, prio=PRIO_URGENT)
        return True

    def no(self):
        return self.A("tb_no_data")

    def num(self, i):
        return self.b.car_num(i)

    def fuel_u(self, litres):
        return litres if self.b.metric() else litres / GAL

    def reset(self):
        self.sess = None
        self.car = {}               # idx -> per-car pit / lap stats (all cars)
        self.start_pos = {}         # idx -> (overall, class) at the start of the race
        self.wx0 = None             # weather when the session started
        self.stint_t0 = None        # session time when this stint started (pit exit / green)
        self.stint_lc0 = None
        self.onp_me = None
        self.fuel_at_line = None
        self.fuel_lap_last = None
        self.lc_me = None
        self.fuel_target = None     # litres per lap (driver's own)
        self.ft_calls = False
        self.alarms = []            # (epoch seconds, said)

    # ------------------------------------------------------------------ every tick
    def tick(self):
        b = self.b
        if self.sess != b.sess_num:
            self.reset(); self.sess = b.sess_num
        st = self.g("SessionTime")
        if st is None:
            return
        if self.wx0 is None and self.g("AirTemp") is not None:
            self.wx0 = {k: self.g(k) for k in ("AirTemp", "TrackTempCrew", "RelativeHumidity", "AirPressure",
                                                "WindVel", "WindDir", "Skies", "Precipitation")}
        self.track_cars(st)
        self.my_stint(st)
        self.my_fuel()
        now = time.time()
        for a in self.alarms:
            if not a[1] and now >= a[0]:
                a[1] = True
                b.say("timer_done", prio=PRIO_URGENT)
        self.alarms = [a for a in self.alarms if not a[1]]

    def track_cars(self, st):
        b = self.b
        lc_arr, onp_arr, lt_arr = self.arr("CarIdxLapCompleted"), self.arr("CarIdxOnPitRoad"), self.arr("CarIdxLastLapTime")
        pct_arr, pos_arr, cpos_arr = self.arr("CarIdxLapDistPct"), self.arr("CarIdxPosition"), self.arr("CarIdxClassPosition")
        racing = b.is_race() and int(self.g("SessionState", 0) or 0) >= 4
        for i in b.drivers():
            lc = lc_arr[i] if i < len(lc_arr) else None
            if lc is None or lc < -1:
                continue
            onp = bool(onp_arr[i]) if i < len(onp_arr) else False
            p = pct_arr[i] if i < len(pct_arr) else -1
            c = self.car.setdefault(i, {"stops": 0, "last_stop_lap": None, "out_lap": None, "stop_t": None,
                                        "lane_t": None, "lane_total": 0.0, "stall_total": 0.0, "times": [],
                                        "lc": lc, "onp": onp, "in_t": None, "still_t": None, "p": p, "compound": None})
            if racing and i not in self.start_pos and (lc or 0) <= 0:
                po = pos_arr[i] if i < len(pos_arr) else 0
                cp = cpos_arr[i] if i < len(cpos_arr) else 0
                if po and po > 0:
                    self.start_pos[i] = (po, cp)
            if onp and not c["onp"]:                      # pit lane in
                c["in_t"], c["still_t"], c["stall_acc"] = st, None, 0.0
            if onp and c["in_t"] is not None:             # standing still in the box
                still = p is not None and p >= 0 and c["p"] is not None and abs(p - c["p"]) < 1e-5
                if still and c["still_t"] is None:
                    c["still_t"] = st
                elif not still and c["still_t"] is not None:
                    c["stall_acc"] = c.get("stall_acc", 0.0) + (st - c["still_t"]); c["still_t"] = None
            if not onp and c["onp"] and c["in_t"] is not None:   # pit lane out
                lane = st - c["in_t"]
                stall = c.get("stall_acc", 0.0) + ((st - c["still_t"]) if c["still_t"] is not None else 0.0)
                if 5 < lane < 900 and (not racing or (lc or 0) > 0 or stall > 2):
                    c["stops"] += 1
                    c["last_stop_lap"] = lc
                    c["lane_t"], c["stop_t"] = lane, stall if stall > 0.5 else None
                    c["lane_total"] += lane; c["stall_total"] += stall
                c["out_lap"] = lc + 1
                c["in_t"] = None
            if lc != c["lc"]:
                t = lt_arr[i] if i < len(lt_arr) else None
                if t and 0 < t < 1000 and not onp and not c["onp"]:
                    c["times"] = (c["times"] + [t])[-12:]
                c["lc"] = lc
            c["onp"], c["p"] = onp, p
            comp = self.at("CarIdxTireCompound", i)
            if comp is not None and comp >= 0:
                c["compound"] = comp

    def my_stint(self, st):
        onp = bool(self.g("OnPitRoad", False))
        lc = self.g("LapCompleted", 0) or 0
        if self.stint_t0 is None and not onp and self.g("IsOnTrack", False):
            self.stint_t0, self.stint_lc0 = st, lc
        if self.onp_me and not onp:
            self.stint_t0, self.stint_lc0 = st, lc
        self.onp_me = onp

    def my_fuel(self):
        lc = self.g("LapCompleted")
        f = self.g("FuelLevel")
        if lc is None or f is None or f <= 0:
            return
        if self.lc_me is None:
            self.lc_me, self.fuel_at_line = lc, f; return
        if lc != self.lc_me:
            if self.fuel_at_line is not None and 0 < self.fuel_at_line - f < 30 and not self.g("OnPitRoad", False):
                self.fuel_lap_last = self.fuel_at_line - f
                if self.ft_calls and self.fuel_target:
                    d = self.fuel_lap_last - self.fuel_target
                    if abs(d) < 0.05:
                        self.b.say("ft_cmp", {"_variant": 3}, prio=PRIO_INFO)
                    else:
                        self.b.say("ft_cmp", {"dec": round(self.fuel_u(abs(d)), 1), "_variant": 1 if d > 0 else 2}, prio=PRIO_INFO)
            self.lc_me, self.fuel_at_line = lc, f

    # ------------------------------------------------------------------ numbers
    def fpl(self):
        return self.b.fuel_lap_est()

    def pace(self):
        return self.b.pace_est()

    def fuel_now(self):
        f = self.g("FuelLevel")
        return f if f and f > 0 else None

    def laps_on_fuel(self):
        f, fl = self.fuel_now(), self.fpl()
        return f / fl if f and fl else None

    def pace_of(self, i):
        xs = self.car.get(i, {}).get("times") or []
        return xs

    # ------------------------------------------------------------------ the questions
    def command(self, text):
        from .intents import normalize
        from .extras import words_to_numbers
        b, x = self.b, self.b.x
        t = " " + normalize(text).strip() + " "
        tt = " " + re.sub(r"\s+", " ", words_to_numbers(t)) + " "
        tt = tt.replace(" tyre", " tire").replace(" gas ", " fuel ")
        # app settings said out loud ("change wind alert to disabled") are not questions for the engineer
        if re.match(r"\s*(change|set)\b.{0,60}\bto (enabled|disabled)\b", tt):
            return False
        if re.match(r"\s*(change|set)\b.{0,60}\b(to|for)\b", tt) and re.search(r"alert|signal|volume|threshold|mode|warning|provider|graph|override|types?\b|passes|tear off", tt):
            return False

        # ---- radio control
        # 2026-10-26 (request: "I need to be able to turn the radio up while driving, like 'radio volume up 10 percent',
        # and he says copy"): "radio up", "radio volume down 20 percent", "turn the radio up", "radio louder" ...
        m = (re.search(r"\b(radio|team radio|engineer|voice|voices)( volume)? (up|down|louder|quieter|softer|higher|lower)\b", tt)
             or re.search(r"\bturn (the )?(radio|engineer|voices?)( volume)? (up|down)\b", tt)
             or re.search(r"\b(louder|quieter) (radio|please)\b", tt))
        if m:
            up = re.search(r"\b(up|louder|higher)\b", m.group(0)) is not None
            n = re.search(r"\b(\d+)\s*(percent|per cent|%)", tt)
            step = max(5, min(50, int(n.group(1)))) / 100.0 if n else 0.10
            try:
                cur = float(getattr(b.s, "volume", 1.0) or 1.0)
                new = round(max(0.3, min(5.0, cur + (step if up else -step))), 2)   # 2026-10-31: up to 500 %
                b.s.volume = new
                try:
                    b.v.volume = new
                except Exception:
                    pass
                try:
                    b.s.save()
                except Exception:
                    pass
            except Exception:
                pass
            return self.A("ack", {"_variant": 1})
        if re.search(r"\b(stop|cancel) (speaking|talking|current speech|what you('re| are)? saying)\b|\bstop what you('re| are) saying\b", tt):
            try:
                pl = b.v.player
                if pl is not None:
                    pl.stop()
            except Exception:
                pass
            return True
        if re.search(r"\b(disable|stop|silence|mute|turn off)( all)? (the )?alerts\b|\balerts off\b", tt):
            return b.answer("quiet") or True
        if re.search(r"\b(enable|start|turn on|unmute)( all)? (the )?alerts\b|\balerts on\b", tt):
            return b.answer("talk") or True
        if re.search(r"\b(stop|deactivate|disable|no more) (the )?(delta|lap time)s?( timing| times| calls)?\b|\blap times off\b", tt):
            b.s.lap_readout = [w for w in (getattr(b.s, "lap_readout", None) or []) if w != "time"]
            return self.A("ft_onoff", {"_variant": 3})
        # timers and alarms
        if re.search(r"\b(time|what s|whats|how much)\b.{0,20}\b(left|remaining)\b.{0,10}\btimer\b|\btimer\b.{0,10}\b(left|remaining)\b", tt):
            now, lap = b.clock(), self.g("LapCompleted", 0) or 0
            ts = [tm for tm in x.timers]
            if not ts:
                return self.A("tm_none")
            due_t, due_lap = ts[0]
            if due_t is not None:
                return self.A("tm_left", {"minutes": max(1, round((due_t - now) / 60)), "_variant": 1})
            return self.A("tm_left", {"laps": max(1, due_lap - lap), "_variant": 2})
        if re.search(r"\b(cancel|stop|delete|clear)\b.{0,6}\b(the )?(timer|countdown|alarm|reminder)s?\b", tt):
            x.timers.clear(); self.alarms = []
            return self.A("tm_off")
        m = re.search(r"\b(remind me|set (an |the )?alarm|alarm|reminder) (at|for) (\d{1,4})(?:[ :.](\d{2}))? ?(a ?m|p ?m)?\b", tt)
        if m:
            h, mi = int(m.group(4)), int(m.group(5) or 0)
            if h > 99:                                   # "remind me at 0211" -> 2:11
                h, mi = h // 100, h % 100
            ap = (m.group(6) or "").replace(" ", "")
            if ap == "pm" and h < 12: h += 12
            if ap == "am" and h == 12: h = 0
            lt = time.localtime()
            base = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h % 24, mi, 0, 0, 0, -1))
            if not ap and h <= 12:                       # "remind me at 2" -> the next 2 o'clock
                while base <= time.time():
                    base += 12 * 3600
            elif base <= time.time():
                base += 24 * 3600
            self.alarms.append([base, False])
            hh = time.localtime(base)
            return self.A("tm_alarm", {"time": (hh.tm_hour % 12 or 12) * 60 + hh.tm_min})
        # notes
        if re.search(r"\b(read|what s|whats|what are)\b.{0,12}\bnotes?\b|^\s*(my|the) notes\s*$|\bwhat s in my notes\b", tt):
            return self.read_notes()
        if re.search(r"\b(clear|delete|erase)\b.{0,6}\b(my |the )?notes\b", tt):
            return self.clear_notes()
        if re.search(r"\b(run|do|start|go) (through )?(the )?(checklist|start procedure|pre ?race check)", tt):
            return self.A("ck_list")
        if re.search(r"\bdebris\b", tt):
            rc = getattr(b, "rcft", None)
            return self.A("dbr_none")

        # ---- in-car adjustments by voice, "explain the front bar", "what should I change" (incar.py)
        ic = getattr(b, "incar", None)
        if ic is not None and ic.command(text, tt):
            return True
        # ---- the app itself by voice ("racecraft calls off", "louder", "gaps every lap", "spotter Jess")
        if self.app_control(tt):
            return True
        # ---- a bare yes / no / cancel with nothing waiting for an answer (the pit plan takes its own yes/no first)
        if re.fullmatch(r"\s*(cancel|abort|never ?mind|forget it)\s*", tt):
            try:
                b.v.player.stop()
            except Exception:
                pass
            return True
        if re.fullmatch(r"\s*(yes|yeah|yep|yes sir|yes ma am|affirmative|correct|no|nope|negative|not yet|no thanks|no thank you|skip that|thanks but no)\s*", tt):
            return self.A("ack", {"_variant": 1})
        # ---- quick chat: "say thanks" / "say sorry" / "say good race"
        m = re.match(r"\s*(please )?say (thanks|thank you|sorry|you( a)?re welcome|good luck|good race|gg)\b", tt)
        if m and b.s.__dict__.get("chat_enabled", True) is not False:
            from .extras import CHAT
            w = m.group(2)
            if "welcome" in w:
                x.chat("You're welcome!"); return True
            for pat, msg in CHAT:
                if re.search(pat, w):
                    x.chat(msg); return True
        # ---- car readouts
        if re.search(r"\b(what s|whats|what is|my)\b.{0,8}\b(speed|rpm|revs|rounds per minute|throttle|brake (pedal|percent)|oil level|water level|voltage|battery|steering( wheel)?( angle)?|clutch)\b", tt) \
                and not re.search(r"pit|limit|wind", tt):
            return self.readout(tt)
        # ---- session facts the stand-in says (free text)
        if re.search(r"\bsession (type|state)\b|\bwhat (kind of )?session\b", tt):
            v = b.sess_type if "type" in tt or "kind" in tt else {0: "invalid", 1: "get in car", 2: "warm up", 3: "parade laps",
                4: "racing", 5: "checkered", 6: "cool down"}.get(int(self.g("SessionState", 0) or 0))
            return self.A("tr_txt", {"txt": str(v), "_variant": 2}) if v else self.no()
        if re.search(r"\btrack (type|state|rubber)\b|\bhow much rubber\b", tt):
            wk = b.info("WeekendInfo", {}) or {}
            if "type" in tt:
                v = wk.get("TrackType")
            else:
                v = (b.session() or {}).get("SessionTrackRubberState")
            return self.A("tr_txt", {"txt": str(v), "_variant": 1}) if v else self.no()
        if re.search(r"\b(number of|how many) (classes|car types|car models|cars types)\b|\b(class|car types?) count\b", tt):
            ds = b.drivers()
            if not ds:
                return self.no()
            if "class" in tt:
                return self.A("ses_classes", {"n": len({d.get("CarClassID") for d in ds.values()}), "_variant": 1})
            return self.A("ses_classes", {"n": len({d.get("CarPath") for d in ds.values()}), "_variant": 2})
        # ---- stint
        if re.search(r"\bstint\b", tt) and not re.search(r"\b(car|number) \d", tt) and not re.search(r"\b(ahead|behind|leader)\b", tt):
            return self.stint(tt)

        # ---- fuel
        if re.search(r"\bfuel\b", tt):
            r = self.fuel(tt)
            if r:
                return True
        if re.search(r"\b(are|am) (we|i) in the (fuel |pit )?window\b|\bis this the (fuel |pit )?window\b|\bin the (fuel |pit )?window\b", tt) \
                and not re.search(r"\b(car|number) \d|\b(ahead|behind|leader)\b", tt):
            return self.window()
        if re.search(r"\btime left (in|on) (the )?(tank|fuel)\b", tt):
            return self.fuel("fuel time left")

        # ---- pit menu (orders, not questions)
        r = self.pit_menu(tt)
        if r:
            return True

        # ---- tyres
        if re.search(r"\b(do|should) (i|we) (need to )?(come in|pit|box)\b.{0,20}\btires?\b|\bneed (new )?tires\b", tt):
            return self.tyres_need(when=False)
        if re.search(r"\bwhen\b.{0,30}\b(come in|pit|box)\b.{0,20}\btires?\b|\bwhen do (i|we) need (new )?tires\b", tt):
            return self.tyres_need(when=True)
        if re.search(r"\b(optimal|best|fastest) tire\b|\bwhich tire\b|\bwhat tire should\b|\b(is|are) (the )?(wets|slicks|wet tires|dry tires) (optimal|fastest|faster|better|the right)", tt):
            return self.tyre_opt()

        # ---- weather
        w = self.weather(tt)
        if w:
            return True

        # ---- session
        if re.search(r"\b(best|fastest) (overall )?(lap|time)\b.{0,20}\b(overall|session|server|of the race|anyone)\b|\boverall best\b|\bbest overall\b|\bsession best\b", tt):
            return self.session_best()
        if re.search(r"\bpit ?(lane )?speed( limit)?\b|\bspeed limit\b.{0,10}\bpit", tt):
            return self.pit_speed()
        if re.search(r"\bfast repairs?\b.{0,12}\b(left|remain|remaining|used|spent|taken|have|got)\b|\bhow many fast repairs\b", tt):
            return self.fast_repairs()
        if re.search(r"\b(number of|how many) (drivers|cars)\b|\b(drivers|cars|numbers) in (my |our |the )?class\b|\bclass (drivers|numbers|car count)\b|\bdrivers (connected|on track)\b", tt):
            return self.counts()
        if re.search(r"\btrack (length|long)\b|\bhow long is (the|this) track\b|\blength of the track\b", tt):
            return self.track_length()
        if re.search(r"\bsetup name\b|\bwhich setup\b|\bwhat setup\b|\bmy (current )?setup\b", tt):
            return self.setup_name()
        if re.search(r"\bwhere do (i|we) (increase|gain) (i ?rating|irating|rating)\b|\bwhere (do|should) (i|we) (finish|need to finish) (to gain|for)", tt):
            return b.x.answer("irating_target") or True
        if re.search(r"\b(lap|lap times?) (of|for) (the )?cars? (ahead and behind|around)|\b(previous|last) lap times? (of )?(the cars )?ahead and behind\b|\bahead and behind\b.{0,10}\blap", tt):
            return self.around()
        if re.search(r"\bwhere (do|did) (i|we) start\b|\b(my|our) (start(ing)?|grid) position\b|\bposition at (the )?start\b(?!.{0,6}car)", tt) \
                and not re.search(r"\b(car|number) \d|\b(ahead|behind|leader)\b", tt):
            return self.start_of(b.me(), me=True)
        if re.search(r"\bwhere (do|am) (i|we) (need to be faster|slow)|\bwhich sectors? am i slow|\bwhere am i (losing|slow)", tt):
            return b.answer("best_sector") or True
        if re.search(r"\bwho( s| is)? near (me|us)\b.{0,20}\b(pit|exit|after)|\bposition after (the )?(pit|stop)\b", tt):
            return b.answer("pit_out") or True

        # ---- another car
        if re.search(r"\b(car|number) \d{1,3}\b|\bthe (car|guy|driver) (ahead|behind|in front)\b|\b(ahead|behind)\b|\bleader\b", tt):
            idx = x.car_from_text(tt)
            r = self.other(tt, idx)
            if r:
                return True
        return False

    # ------------------------------------------------------------------ stint
    def stint(self, tt):
        st = self.g("SessionTime")
        lc = self.g("LapCompleted", 0) or 0
        el = (st - self.stint_t0) if (st is not None and self.stint_t0 is not None) else None
        el_l = lc - (self.stint_lc0 or 0) if self.stint_lc0 is not None else None
        lof, pace = self.laps_on_fuel(), self.pace()
        rem_m = (lof * pace / 60) if (lof and pace) else None
        if re.search(r"elapsed|gone|passed|done|into|in this stint|so far", tt):
            if el is None:
                return self.no()
            return self.A("st_elapsed", {"minutes": max(0, round(el / 60)), "laps": max(0, el_l or 0)})
        if re.search(r"end|over|finish|completed", tt):
            if rem_m is None:
                return self.no()
            return self.A("st_end", {"minutes": max(0, round(rem_m)), "n": lc + int(lof) + 1})
        if re.search(r"total|duration|how long is|whole", tt):
            if rem_m is None or el is None:
                return self.no()
            return self.A("st_total", {"minutes": round(el / 60 + rem_m), "laps": int((el_l or 0) + lof)})
        if rem_m is None:
            return self.no()
        return self.A("st_left", {"minutes": max(0, round(rem_m)), "laps": max(0, int(lof))})

    # ------------------------------------------------------------------ fuel
    def fuel(self, tt):
        b = self.b
        fl, f, pace = self.fpl(), self.fuel_now(), self.pace()
        # own fuel target
        if re.search(r"\b(stop|disable|deactivate|turn off|cancel)\b.{0,12}\bfuel (burn )?target\b|\bfuel target off\b", tt):
            self.ft_calls = False; return self.A("ft_onoff", {"_variant": 2})
        if re.search(r"\b(start|enable|activate|turn on)\b.{0,12}\bfuel (burn )?target\b|\bfuel target on\b", tt):
            if not self.fuel_target:
                return self.no()
            self.ft_calls = True; return self.A("ft_onoff", {"_variant": 1})
        if re.search(r"\bset (the )?fuel (burn )?target\b.{0,20}\b(previous|last) lap", tt):
            if not self.fuel_lap_last:
                return self.no()
            self.fuel_target = self.fuel_lap_last
            return self.A("fuel_target", {"dec": round(self.fuel_u(self.fuel_target), 1)})
        m = re.search(r"\bset (the )?fuel (burn )?target (to|at) (\d+(?:\.\d+)?)", tt)
        if m:
            v = float(m.group(4))
            self.fuel_target = v if b.metric() or "lit" in tt else v * GAL
            return self.A("fuel_target", {"dec": round(self.fuel_u(self.fuel_target), 1)})
        if re.search(r"\b(current|get|what s|whats|my) (the )?(target fuel|fuel target)\b|\bcompare\b.{0,10}\btarget\b", tt) and self.fuel_target:
            self.A("fuel_target", {"dec": round(self.fuel_u(self.fuel_target), 1)})
            if self.fuel_lap_last:
                d = self.fuel_lap_last - self.fuel_target
                self.A("ft_cmp", {"_variant": 3} if abs(d) < 0.05 else {"dec": round(self.fuel_u(abs(d)), 1), "_variant": 1 if d > 0 else 2})
            return True
        # amounts
        if re.search(r"\b(time left|minutes left)\b|\btime\b.{0,6}\b(in|on) (the )?(tank|fuel)\b|\bhow long (will|does) (the )?fuel last\b", tt):
            if not (f and fl and pace):
                return self.no()
            return self.A("fu_time", {"minutes": max(0, round(f / fl * pace / 60))})
        if re.search(r"\bper minute\b|\bfuel rate\b|\bminute\b.{0,6}\bfuel\b", tt) and not re.search(r"\d+ minutes", tt):
            if not (fl and pace):
                return self.no()
            return self.A("fu_rate", {"dec": round(self.fuel_u(fl / pace * 60), 1)})
        if re.search(r"\b(previous|last) lap\b", tt) and not re.search(r"set", tt):
            if not self.fuel_lap_last:
                return self.no()
            return self.A("fu_last", {"dec": round(self.fuel_u(self.fuel_lap_last), 1)})
        if re.search(r"\baverage\b|\bmean\b", tt):
            xs = (getattr(b, "fuel_laps", None) or [])[-5:]
            v = sum(xs) / len(xs) if xs else fl
            if not v:
                return self.no()
            return self.A("fu_avg", {"dec": round(self.fuel_u(v), 1)})
        m = re.search(r"\b(\d+(?:\.\d+)?|an?|one)\s*(laps?|minutes?|mins?|hours?)\b", tt)
        if m and re.search(r"how much|fuel (usage|burn|use|needed)|need for", tt) and not re.search(r"\bsave\b|\bstops?\b", tt):
            n = 1.0 if m.group(1) in ("a", "an", "one") else float(m.group(1))
            unit = m.group(2)
            if not fl:
                return self.no()
            if unit.startswith("lap"):
                need = fl * n
                return self.A("fu_calc", {"laps": int(n), "n": round(self.fuel_u(need)), "_variant": 1})
            mins = n * 60 if unit.startswith("hour") else n
            if not pace:
                return self.no()
            need = fl * mins * 60 / pace
            return self.A("fu_calc", {"minutes": int(mins), "n": round(self.fuel_u(need)), "_variant": 2})
        m = re.search(r"\bsave\b.{0,40}\b(\d+|one|two|three|no) (pit )?stops?\b|\b(\d+|one|two|three|no) (pit )?stops?\b.{0,30}\bsave\b|\bmake it (on|with) (\d+|one|two|three) stops?\b", tt)
        if m:
            raw = next((gx for gx in m.groups() if gx and re.fullmatch(r"\d+|one|two|three|no", gx)), "1")
            n = {"one": 1, "two": 2, "three": 3, "no": 0}.get(raw, None)
            n = int(raw) if n is None else n
            return self.save_for(n)
        if re.search(r"\b(are|am) (we|i) in the (fuel )?window\b|\bfuel window\b", tt) and not re.search(r"\b(car|number) \d|\b(ahead|behind)\b", tt):
            return self.window()
        if re.search(r"\b(fuel pressure)\b", tt):
            self.b.x.engine_answer(); return True
        return False

    def stops_needed(self):
        fl, f, ltg, tank = self.fpl(), self.fuel_now(), self.b.laps_to_go(), self.b.x.tank()
        if not (fl and f and ltg and tank):
            return None
        need = ltg * fl + float(getattr(self.b.s, "fuel_buffer_laps", 0) or 0) * fl - f
        return max(0, math.ceil(need / tank - 1e-6)) if need > 0 else 0

    def window(self):
        fl, ltg, tank = self.fpl(), self.b.laps_to_go(), self.b.x.tank()
        n = self.stops_needed()
        if n is None:
            return self.no()
        if n == 0:
            return self.A("fw", {"_variant": 3})
        k = math.ceil(ltg - n * tank / fl)
        if k <= 0:
            return self.A("fw", {"_variant": 1})
        return self.A("fw", {"laps": k, "_variant": 2})

    def save_for(self, n):
        fl, f, ltg, tank = self.fpl(), self.fuel_now(), self.b.laps_to_go(), self.b.x.tank()
        if not (fl and f and ltg and tank):
            return self.no()
        have = f + n * tank * 0.98
        need = ltg * fl
        base = 1 if n > 1 else (4 if n == 1 else 7)      # "two stops" / "one stop" / "no stop" wording
        if have >= need:
            return self.A("fu_stops", {"n": n, "_variant": base + 1})
        save = fl - have / ltg
        if save / fl > 0.15:
            return self.A("fu_stops", {"n": n, "_variant": base + 2})
        return self.A("fu_stops", {"n": n, "dec": round(self.fuel_u(save), 1) or 0.1, "_variant": base})

    # ------------------------------------------------------------------ pit menu
    def pit_menu(self, tt):
        x = self.b.x
        if re.search(r"^\s*(please )?(what|how|when|is|are|do|does|can we|should)\b", tt) and not re.search(r"^\s*(can|could) you\b", tt):
            return False
        # CrewChief-style "clear ..." for the pit black box (iRacing pit commands, no keys)
        if re.search(r"\b(clear|reset)\b.{0,8}\b(all|everything|the (pit )?menu|pit menu)\b|\bpit menu clear\b|\bclear the (pit )?stop\b", tt):
            x.pit_cmd("clear"); return self.A("req_clear")
        if re.search(r"\bclear\b.{0,6}\b(the )?tires\b|\bclear tires\b", tt):
            x.pit_cmd("clear_tires"); return self.A("req_tyres", {"_variant": 6})
        if re.search(r"\b(clear|cancel|remove)\b.{0,6}\b(the )?tear ?off\b", tt):
            x.pit_cmd("clear_ws"); return self.A("req_tearoff", {"_variant": 2})
        if re.search(r"\b(clear|cancel|remove)\b.{0,6}\b(the )?fast repairs?\b", tt):
            x.pit_cmd("clear_fr"); return self.A("req_fast_repair", {"_variant": 2})
        if re.search(r"\b(clear|cancel|remove)\b.{0,6}\b(the )?fuel\b", tt):
            x.pit_cmd("clear_fuel"); return self.A("req_no_fuel")
        if re.search(r"\b(windscreen|windshield|visor)\b", tt) and not re.search(r"\b(no|clear|cancel|don t)\b", tt):
            x.pit_cmd("ws"); return self.A("req_tearoff", {"_variant": 1})
        m = re.search(r"\b(change|switch|put|go)\b.{0,12}\b(to|on)\b.{0,6}\b(dry|dries|slicks?|wets?|wet|rain|inters?)( tires)?\b", tt)
        if m:
            wet = m.group(3).startswith(("wet", "rain", "inter"))
            ci = x.compound_index(wet)
            if ci is None:
                return self.no()
            x.pit_cmd("tc", ci)
            return self.A("req_compound", {"_variant": 1 if wet else 2})
        if re.search(r"\b(fuel|gas) only\b|\bjust fuel\b|\bonly fuel\b", tt):
            x.pit_cmd("clear_tires")
            need = x.fuel_to_end()
            if need:
                x.pit_cmd("fuel", int(math.ceil(need)))
            return self.A("pm_fuel_only")
        if re.search(r"\bno service\b|\bpit ?stop clear\b|\bnothing at the stop\b", tt):
            x.pit_cmd("clear")
            return self.A("req_clear")
        if re.search(r"\bfull service\b|\bfull pit ?stop\b|\bchange everything\b", tt):
            for c in ("lf", "rf", "lr", "rr"):
                x.pit_cmd(c)
            tank = x.tank()
            x.pit_cmd("fuel", int(tank) if tank else 999)
            x.pit_cmd("ws")
            return self.A("pm_full")
        if re.search(r"\b(max|maximum|maximize|full tank|fill (it|her) up|brim)\b.{0,12}(fuel)?", tt) and re.search(r"fuel|tank|fill|brim", tt):
            tank = x.tank()
            x.pit_cmd("fuel", int(tank) if tank else 999)
            return self.A("pm_max")
        m = re.search(r"\b(remove|subtract|minus|take off|take out|less)\b\s*(\d+(?:\.\d+)?)\s*(laps?|litres?|liters?|gallons?|of)?\b.{0,10}\b(fuel)?", tt)
        if m and "fuel" in tt:
            n = float(m.group(2))
            cur = self.g("PitSvFuel")
            if cur is None or cur <= 0:
                cur = x.fuel_to_end() or 0
            if (m.group(3) or "").startswith("lap"):
                fl = self.fpl()
                if not fl:
                    return self.no()
                amt = n * fl
            else:
                amt = n if (self.b.metric() or "lit" in (m.group(3) or "")) else n * GAL
            new = max(0.0, cur - amt)
            if new <= 0.5:
                x.pit_cmd("clear_fuel")
            else:
                x.pit_cmd("fuel", int(round(new)))
            return self.A("pm_less", {"n": round(self.fuel_u(amt)), "fuel unit": round(self.fuel_u(amt))})
        return False

    # ------------------------------------------------------------------ tyres
    def tyres_need(self, when):
        x = self.b.x
        est = x.tyre_est()
        ltg = self.b.laps_to_go()
        rate = getattr(x, "wear_rate", None)
        if est is None or not rate:
            return self.no()
        laps_left = max(0, int((est - 30) / rate)) if rate > 0 else 999
        if ltg is not None and laps_left >= ltg:
            return self.A("ty_need", {"_variant": 2})
        if laps_left <= 1:
            return self.A("ty_need", {"_variant": 1})
        return self.A("ty_need", {"laps": laps_left, "_variant": 3})

    def tyre_opt(self):
        wet = self.g("TrackWetness")
        if wet is None:
            return self.no()
        declared = bool(self.g("WeatherDeclaredWet", False))
        if wet >= 4 or (declared and wet >= 3):
            return self.A("ty_opt", {"_variant": 2})
        if wet == 3:
            return self.A("ty_opt", {"_variant": 3})
        return self.A("ty_opt", {"_variant": 1})

    # ------------------------------------------------------------------ weather
    def weather(self, tt):
        b = self.b
        if re.search(r"\bis it raining\b|\bis it wet\b(?! .*tomorrow)|\braining (now|right now|at the moment)\b|\bany rain (now|right now)\b", tt):
            p = self.g("Precipitation")
            wet = self.g("TrackWetness")
            if p is None and wet is None:
                return self.no()
            if (p or 0) > 0.02:
                return self.A("rn_now", {"percent": round((p or 0) * 100), "_variant": 1})
            return self.A("rn_now", {"_variant": 2})
        if re.search(r"\b(going to|will it|gonna|expected|forecast|coming)\b.{0,15}\brain\b|\brain\b.{0,15}\b(expected|coming|forecast|later)\b|\bweather report\b|\bthe forecast\b", tt):
            st = getattr(b, "strat", None)
            nx = None
            try:
                nx = st._forecast() if st else None
            except Exception:
                nx = None
            rain = (nx or {}).get("rain")
            if rain is None:
                return self.A("rn_fc", {"_variant": 3})
            if rain < 5:
                return self.A("rn_fc", {"_variant": 2})
            return self.A("rn_fc", {"percent": int(5 * round(rain / 5)), "_variant": 1})
        start = re.search(r"\b(at the start|starting|start of)\b", tt)
        change = re.search(r"\bchange(d)?\b|\bdelta\b|\bsince (the )?start\b", tt)
        w0 = self.wx0 or {}
        if re.search(r"\bhumidity\b", tt):
            v = (w0 if start else {}).get("RelativeHumidity") if start else self.g("RelativeHumidity")
            if change and w0.get("RelativeHumidity") is not None and self.g("RelativeHumidity") is not None:
                return self.delta("hum", (self.g("RelativeHumidity") - w0["RelativeHumidity"]) * 100)
            return self.A("wx_hum", {"percent": round(v * 100)}) if v is not None else self.no()
        if re.search(r"\b(air )?pressure\b", tt) and not re.search(r"tire|tyre|oil|fuel|click|psi|kpa|\bup\b|\bdown\b|\bset\b|front|rear|left|right|plus|minus", tt):
            v = w0.get("AirPressure") if start else self.g("AirPressure")
            return self.A("wx_press", {"n": round(self.hpa(v))}) if v else self.no()
        if re.search(r"\bskies\b|\bsky\b|\bcloud(y|s)?\b|\bsunny\b|\bovercast\b", tt):
            v = w0.get("Skies") if start else self.g("Skies")
            return self.A("wx_sky", {"skies": SKIES.get(int(v), "clear")}) if v is not None else self.no()
        if re.search(r"\bwind\b", tt):
            vel = w0.get("WindVel") if start else self.g("WindVel")
            d = w0.get("WindDir") if start else self.g("WindDir")
            if vel is None:
                return self.no()
            if change and w0.get("WindVel") is not None:
                return self.delta("wind", self.speed(self.g("WindVel")) - self.speed(w0["WindVel"]))
            if re.search(r"direction|where|from", tt) and d is not None:
                return self.A("wx_wind", {"dir": self.dir_name(d), "_variant": 2})
            return self.A("wx_wind", {"n": round(self.speed(vel)), "speed unit": 1, "dir": self.dir_name(d) if d is not None else None,
                                      "_variant": 1 if d is not None else 3})
        if re.search(r"\btrack temp", tt) and (start or change):
            if not w0.get("TrackTempCrew"):
                return self.no()
            if change:
                return self.delta("track", b.x.temp_units(self.g("TrackTempCrew") or 0) - b.x.temp_units(w0["TrackTempCrew"]), temp=True)
            return self.A("track_temp", {"n": round(b.x.temp_units(w0["TrackTempCrew"]))})
        if re.search(r"\bair temp", tt) and (start or change):
            if not w0.get("AirTemp"):
                return self.no()
            if change:
                return self.delta("air", b.x.temp_units(self.g("AirTemp") or 0) - b.x.temp_units(w0["AirTemp"]), temp=True)
            return self.A("air_temp", {"n": round(b.x.temp_units(w0["AirTemp"]))})
        if re.search(r"\bair temp", tt):
            at = self.g("AirTemp")
            return self.A("air_temp", {"n": round(b.x.temp_units(at))}) if at is not None else self.no()
        return False

    def delta(self, what, d, temp=False):
        v = {"track": 1, "air": 2, "wind": 3, "hum": 4}[what]
        if abs(d) < 0.5:
            return self.A("wx_delta", {"_variant": 9})
        return self.A("wx_delta", {"n": round(abs(d)), "speed unit": 1, "_variant": v if d > 0 else v + 4})

    def hpa(self, v):
        v = float(v)
        if v > 2000:            # Pa
            return v / 100
        if v < 40:              # inches of mercury
            return v * 33.8639
        return v

    def speed(self, ms):
        kmh = float(ms) * 3.6
        return kmh if self.b.metric() else kmh / 1.609

    def dir_name(self, rad):
        k = int(round((float(rad) % (2 * math.pi)) / (math.pi / 4))) % 8
        return DIRS[k]

    # ------------------------------------------------------------------ session
    def session_best(self):
        best, who = None, None
        bl = self.arr("CarIdxBestLapTime")
        for i in self.b.drivers():
            t = bl[i] if i < len(bl) else None
            if t and t > 0 and (best is None or t < best):
                best, who = t, i
        if best is None:
            return self.no()
        return self.A("sb_overall", {"time": best, "car": self.num(who)})

    def pit_speed(self):
        s = str((self.b.info("WeekendInfo", {}) or {}).get("TrackPitSpeedLimit", ""))
        m = re.match(r"([\d.]+)\s*(kph|km/h|mph)", s)
        if not m:
            return self.no()
        v, u = float(m.group(1)), m.group(2)
        kph = v if u != "mph" else v * 1.609
        return self.A("psl", {"n": round(kph if self.b.metric() else kph / 1.609), "speed unit": 1})

    def fast_repairs(self):
        lim = str((self.b.info("WeekendInfo", {}) or {}).get("WeekendOptions", {}).get("FastRepairsLimit", "")).lower()
        used = self.g("FastRepairUsed")
        if used is None:
            used = self.g("PlayerFastRepairsUsed")
        if "unlim" in lim:
            return self.A("fr_left", {"_variant": 3})
        try:
            n = int(re.sub(r"\D", "", lim) or "x")
        except ValueError:
            return self.no()
        left = max(0, n - int(used or 0))
        if left == 0:
            return self.A("fr_left", {"_variant": 2})
        return self.A("fr_left", {"n": left, "_variant": 1 if left != 1 else 4})

    def counts(self):
        b = self.b
        ds = b.drivers()
        cid, _ = b.my_class()
        ncls = sum(1 for d in ds.values() if d.get("CarClassID") == cid)
        if not ds:
            return self.no()
        if len({d.get("CarClassID") for d in ds.values()}) <= 1:
            return self.A("ses_cars", {"n": len(ds), "_variant": 2})
        return self.A("ses_cars", {"n": len(ds), "laps": ncls, "_variant": 1})

    def track_length(self):
        m = self.b.track_len_m()
        if not m:
            return self.no()
        if self.b.metric():
            return self.A("tr_len", {"dec": round(m / 1000, 1), "_variant": 1})
        return self.A("tr_len", {"dec": round(m / 1609.34, 1), "_variant": 2})

    def setup_name(self):
        n = (self.b.info("DriverInfo", {}) or {}).get("DriverSetupName")
        if not n:
            return self.no()
        n = re.sub(r"\.sto$", "", str(n).split("\\")[-1].split("/")[-1]).replace("_", " ")
        return self.A("setup_name", {"txt": n})

    def around(self):
        ahead, _, behind, _ = self.b.neighbours()
        la, lb = self.at("CarIdxLastLapTime", ahead), self.at("CarIdxLastLapTime", behind)
        if not (la and la > 0) and not (lb and lb > 0):
            return self.no()
        if la and la > 0 and lb and lb > 0:
            return self.A("ar_laps", {"time": [la, lb], "_variant": 1})
        if la and la > 0:
            return self.A("ar_laps", {"time": la, "_variant": 2})
        return self.A("ar_laps", {"time": lb, "_variant": 3})

    def start_of(self, idx, me=False):
        sp = self.start_pos.get(idx)
        if sp is None:
            q = self.quali_of(idx)
            if q is None:
                return self.no()
            sp = (q[0], q[1])
        cls = sp[1] or sp[0]
        if me:
            return self.A("my_start", {"P": cls})
        return self.A("oc_pos", {"car": self.num(idx), "P": cls, "_variant": 3})

    def quali_of(self, idx):
        """(overall, class, fastest) from the qualifying results, or None."""
        q = self.b.info("QualifyResultsInfo", {}) or {}
        for r in q.get("Results", []) or []:
            if r.get("CarIdx") == idx:
                return ((r.get("Position") or 0) + 1, (r.get("ClassPosition") or 0) + 1, r.get("FastestTime"))
        for s in (self.b.info("SessionInfo", {}) or {}).get("Sessions", []) or []:
            if "qual" in str(s.get("SessionType", "")).lower():
                for r in s.get("ResultsPositions") or []:
                    if r.get("CarIdx") == idx:
                        return (r.get("Position"), (r.get("ClassPosition") or 0) + 1, r.get("FastestTime"))
        return None

    # ------------------------------------------------------------------ another car
    def other(self, tt, idx):
        b, x = self.b, self.b.x
        if re.search(r"rating|\bfinish\b|dangerous|careful|clean|crash|wreck|\bpace\b|incident|license|licence|\bsr\b", tt):
            return False                  # iRating, projected finish, "is he dangerous", pace vs: other handlers
        mine = bool(re.search(r"\bmy\b|\bam i\b|\bi am\b|\bwhere am i\b", tt)) and not re.search(r"\b(car|number) \d", tt)
        if mine:
            # the driver's own lap times, position and gaps already have answers (best_lap, position, gap intents)
            if re.search(r"\b(best|fastest|last|previous) (lap|time)\b|\bgap\b|\binterval\b", tt) and not re.search(r"median|average|qual", tt):
                return False
            if re.search(r"\bposition\b", tt) and not re.search(r"class|start|qual|grid", tt):
                return False
            idx = b.me()
        if idx is None:
            if re.search(r"\b(car|number) \d", tt):
                return self.no()
            return False
        n = self.num(idx)
        c = self.car.get(idx, {})
        times = c.get("times") or []
        my = self.car.get(b.me(), {}).get("times") or list(getattr(b, "lap_times", []) or [])
        # what he drives / who he is
        if re.search(r"\bname\b|\bwho( s| is) driving\b", tt):
            d = x.driver(idx)
            nm = d.get("UserName") or d.get("TeamName")
            return self.A("oc_name", {"car": n, "txt": nm}) if nm else self.no()
        if re.search(r"\bwhich class\b|\bwhat class\b|\bclass is\b|\b(car|number) \d+ class\b(?! position)", tt) and "position" not in tt:
            d = x.driver(idx)
            c = classes.spoken(d)
            return self.A("oc_class", {"car": n, "class": c}) if c else self.no()
        if re.search(r"\b(what|which) (car|kind of car|make)\b.{0,20}\b(driving|drive|have)\b|\bwhat is (car|number) \d+ driving\b|\bcar make\b|\bwhat am i driving\b", tt):
            d = x.driver(idx)
            nm = d.get("CarScreenName")
            return self.A("oc_make", {"car": n, "txt": nm}) if nm else self.no()
        if re.search(r"\bcar number\b|\bwhat( s| is) (his|the) number\b|\bmy number\b", tt):
            return self.A("oc_num", {"car": n})
        # positions
        if re.search(r"\bqual(i|ify|ifying)?\b", tt):
            q = self.quali_of(idx)
            if q is None:
                return self.no()
            if re.search(r"\b(time|lap)\b", tt):
                return self.A("oc_best", {"car": n, "time": q[2], "_variant": 2}) if q[2] and q[2] > 0 else self.no()
            return self.A("oc_pos", {"car": n, "P": q[1] if "class" in tt else q[0], "_variant": 4})
        if re.search(r"\b(start|started|starting|grid)\b", tt) and re.search(r"position|where|start", tt):
            return self.start_of(idx)
        if re.search(r"\bclass position\b|\bposition in class\b", tt):
            p = b.class_pos(idx)
            return self.A("oc_pos", {"car": n, "P": p, "_variant": 2}) if p else self.no()
        if re.search(r"\b(overall )?position\b|\bwhat p\b|\bp what\b", tt) and not re.search(r"pit", tt):
            p = self.at("CarIdxPosition", idx, 0)
            return self.A("oc_pos", {"car": n, "P": p, "_variant": 1}) if p else self.no()
        if re.search(r"\b(current )?lap( number)?\b(?! ?time)", tt) and re.search(r"\bcurrent lap\b|\blap number\b|\bwhat lap\b|\bwhich lap\b|\bon lap\b", tt):
            lc = self.at("CarIdxLapCompleted", idx)
            return self.A("oc_lap", {"car": n, "n": lc + 1}) if lc is not None and lc >= 0 else self.no()
        if re.search(r"\b(location|where on (the )?track|whereabouts)\b|\bwhere is\b.{0,20}\bon track\b|\bwhere am i\b", tt):
            return self.where(idx)
        if re.search(r"\b(gap|interval)\b", tt):
            fm, fi = b.f2(b.me()), b.f2(idx)
            if fm is None or fi is None or idx == b.me():
                return self.no()
            return self.A("oc_gap", {"car": n, "gap": abs(fi - fm), "_variant": 1 if fi < fm else 2})
        if re.search(r"\bfuel window\b|\bpit window\b|\bin the window\b", tt):
            if idx == b.me():
                return self.window()
            lc = self.at("CarIdxLapCompleted", idx)
            if c.get("last_stop_lap") is None or lc is None:
                return self.A("rt_nostop", {"car": n})
            return self.A("rt_stint", {"car": n, "n": max(0, lc - c["last_stop_lap"])})
        # pit stops
        if re.search(r"\bpit\b|\bstops?\b|\bpitlane\b|\blane\b|\bout ?lap\b", tt):
            if re.search(r"\b(diff|difference|more|fewer|compared|vs|versus)\b", tt) and idx != b.me():
                d = c.get("stops", 0) - self.car.get(b.me(), {}).get("stops", 0)
                if d == 0:
                    return self.A("oc_pitdiff", {"car": n, "_variant": 3})
                return self.A("oc_pitdiff", {"car": n, "n": abs(d), "_variant": 1 if d > 0 else 2})
            if re.search(r"\bout ?lap\b", tt):
                return self.A("oc_outlap", {"car": n, "n": c["out_lap"]}) if c.get("out_lap") else self.no()
            if re.search(r"\b(total|accumulated|all)\b", tt):
                v = c.get("lane_total") if re.search(r"lane", tt) else c.get("stall_total")
                return self.A("oc_pittime", {"car": n, "n": round(v), "_variant": 2}) if v else self.no()
            if re.search(r"\b(time|long|how long|duration)\b", tt):
                v = c.get("lane_t") if re.search(r"lane", tt) else (c.get("stop_t") or c.get("lane_t"))
                return self.A("oc_pittime", {"car": n, "n": round(v), "_variant": 1}) if v else self.no()
            if re.search(r"\b(lap|when)\b", tt) and not re.search(r"how many", tt):
                if c.get("last_stop_lap") is None:
                    return self.A("rt_nostop", {"car": n})
                return self.A("oc_pitlap", {"car": n, "n": c["last_stop_lap"]})
            if c.get("stops", 0) == 0:
                return self.A("rt_nostop", {"car": n})
            return self.A("oc_stops", {"car": n, "n": c["stops"], "_variant": 1 if c["stops"] != 1 else 2})
        if re.search(r"\bfuel window\b|\bpit window\b|\bin the window\b", tt):
            if idx == b.me():
                return self.window()
            lc = self.at("CarIdxLapCompleted", idx)
            if c.get("last_stop_lap") is None or lc is None:
                return self.A("rt_nostop", {"car": n})
            return self.A("rt_stint", {"car": n, "n": max(0, lc - c["last_stop_lap"])})
        if re.search(r"\bstint laps?\b|\blaps (in|into) (the|this|his) stint\b|\blaps stint\b|\blaps on (the )?tires?\b|\btire (set )?laps\b|\blaps on tire set\b", tt):
            lc = self.at("CarIdxLapCompleted", idx)
            if lc is None:
                return self.no()
            since = c.get("last_stop_lap") if c.get("last_stop_lap") is not None else 0
            return self.A("oc_tyrelaps", {"car": n, "n": max(0, lc - since)})
        if re.search(r"\btire (type|compound)\b|\b(which|what) tires?\b|\bon wets\b|\bon slicks\b", tt):
            comp = c.get("compound")
            if comp is None:
                return self.no()
            wet = x.compound_index(True) if hasattr(x, "compound_index") else 1
            return self.A("oc_comp", {"car": n, "_variant": 2 if comp == wet and comp > 0 else 1})
        # lap times
        if re.search(r"\bimprov|\bgetting (faster|quicker|slower)\b|\bgoing faster\b", tt):
            if len(times) < 4:
                return self.no()
            a, z = median(times[-6:-3]) if len(times) >= 6 else times[0], median(times[-3:])
            if z < a - 0.2:
                return self.A("oc_trend", {"car": n, "_variant": 1})
            if z > a + 0.2:
                return self.A("oc_trend", {"car": n, "_variant": 2})
            return self.A("oc_trend", {"car": n, "_variant": 3})
        if re.search(r"\bdelta\b|\bdifference\b|\bcompared\b", tt) and idx != b.me() and not re.search(r"\bpace\b", tt):
            if re.search(r"\bfive\b|\b5\b", tt):
                if len(times) < 5 or len(my) < 5:
                    return self.no()
                d = sum(my[-5:]) - sum(times[-5:])
                return self.A("oc_delta", {"car": n, "gap": abs(d), "_variant": 5 if d > 0 else 6})
            if re.search(r"\bbest\b|\bfastest\b", tt):
                bi, bm = self.at("CarIdxBestLapTime", idx), self.at("CarIdxBestLapTime", b.me())
                if not (bi and bi > 0 and bm and bm > 0):
                    return self.no()
                d = bm - bi
                return self.A("oc_delta", {"car": n, "gap": abs(d), "_variant": 3 if d > 0 else 4})
            li, lm = self.at("CarIdxLastLapTime", idx), self.at("CarIdxLastLapTime", b.me())
            if not (li and li > 0 and lm and lm > 0):
                return self.no()
            d = lm - li
            return self.A("oc_delta", {"car": n, "gap": abs(d), "_variant": 1 if d > 0 else 2})
        if re.search(r"\bmedian\b|\baverage\b|\bmean\b", tt) and re.search(r"lap|time", tt):
            xs = times if idx != b.me() else (my or times)
            if len(xs) < 2:
                return self.no()
            v = median(xs[-10:]) if "median" in tt else sum(xs[-10:]) / len(xs[-10:])
            return self.A("oc_best", {"car": n, "time": v, "_variant": 3})
        if re.search(r"\b(best|fastest) (lap|time)\b|\b(best|fastest)\b.{0,6}\blap time\b", tt):
            bt = self.at("CarIdxBestLapTime", idx)
            return self.A("oc_best", {"car": n, "time": bt, "_variant": 1}) if bt and bt > 0 else self.no()
        return False

    def where(self, idx):
        b = self.b
        p = self.at("CarIdxLapDistPct", idx, -1)
        if p is None or p < 0:
            return self.no()
        n = self.num(idx)
        if self.at("CarIdxOnPitRoad", idx, False):
            return self.A("wh_car", {"car": n, "_variant": 3})
        corner = b.c.at(p * b.track_len_m()) if getattr(b, "c", None) else None
        if corner:
            return self.A("oc_where", {"car": n, "corner": corner, "_variant": 1})
        return self.A("oc_where", {"car": n, "sector": min(3, int(p * 3) + 1), "_variant": 2})

    APP = [  # (words, setting) - "turn off X" / "X off" / "no more X"
        (r"spotter", "spotter"), (r"gaps?( updates?| calls?)?", "gaps"), (r"racecraft( calls)?", "calls_racecraft"),
        (r"sector (calls|times)", "calls_sectors"), (r"weather (calls|updates)", "calls_weather"), (r"tyre (calls|wear calls)", "calls_tyres"),
        (r"pit tones?|pit beeps?|limiter beeps?", "pit_tones"), (r"shift beeps?|shift lights? beep", "shift_beep"), (r"radio beeps?|radio chirps?|button beeps?", "radio_beep"),
        (r"connection warnings?|lag warnings?", "net_warnings"), (r"race control|race director", "race_control"),
        (r"captions|subtitles|overlay radio", "overlay_radio"), (r"formation (brief|rundown)", "formation_brief"),
        (r"(low )?safety rating warnings?", "low_sr_warn"), (r"practice traffic( calls)?", "calls_practice_traffic"),
        (r"(car )?health calls|engine calls|damage calls", "calls_health"), (r"pit (lane )?calls", "calls_pitlane"),
        (r"driver calls|other drivers calls", "calls_drivers"), (r"fuel (window|target) calls", "calls_fuel_extras"),
        (r"quiet in (the )?corners|hold in (the )?corners", "hold_in_corners"), (r"overlap (tone|beep)", "sig_overlap"),
        (r"spray (tone|beep|warning)", "sig_spray"), (r"rev (limit|limiter) (tone|beep)", "sig_revlimit"),
        (r"launch (tone|beep)", "sig_launch"), (r"chat( messages)?", "chat_enabled"), (r"telemetry( recording)?", "auto_telemetry"),
    ]
    READOUT = {"lap times?": "time", "positions?": "position", "fuel (readout|every lap)": "fuel", "gaps every lap readout": "gaps"}

    def app_control(self, tt):
        b = self.b
        s = b.s
        if re.search(r"\badmin\b|\bvoice chat\b|\bchat volume\b|\b(sim|simulator|iracing) spotter\b", tt):
            return False                     # iRacing's own chat / spotter / admin, not ours
        def save():
            try:
                s.save()
            except Exception:
                pass
        if re.search(r"\b(louder|volume up|turn (it|yourself|the radio|the volume) up|speak up)\b", tt):
            s.volume = min(5.0, round(float(getattr(s, "volume", 1.0)) + 0.1, 2)); b.v.volume = s.volume; save()
            return self.A("app_set", {"_variant": 3})
        if re.search(r"\b(quieter|volume down|turn (it|yourself|the radio|the volume) down|too loud)\b", tt):
            s.volume = max(0.2, round(float(getattr(s, "volume", 1.0)) - 0.1, 2)); b.v.volume = s.volume; save()
            return self.A("app_set", {"_variant": 4})
        m = re.search(r"\bgaps? (updates? )?every (\d+|one|two|three|five|other) laps?\b|\bgaps? every lap\b", tt)
        if m:
            n = {"one": 1, "two": 2, "three": 3, "five": 5, "other": 2}.get(m.group(2) or "1", None) or int(m.group(2) or 1)
            s.gaps, s.gaps_every = True, n; save()
            return self.A("app_set", {"laps": n, "_variant": 6 if n == 1 else 5})
        m = re.search(r"\bspotter (voice )?(to )?(max|jess|leo|clare)\b|\b(use|switch to|change to) (max|jess|leo|clare)\b", tt)
        if m:
            name = (m.group(3) or m.group(5)).title()
            s.spotter_voice = name if name != "Clare" else "cc:Clare"
            try:
                b.v.spotter = s.spotter_voice
            except Exception:
                pass
            save()
            return self.A("app_set", {"_variant": 7})
        on = re.search(r"\b(turn|switch|put)\b.{0,30}\bon\b|\b(enable|start|resume)\b|\bon (please|again)\b|\bback on\b|\bon\s*$", tt)
        off = re.search(r"\b(turn|switch|put)\b.{0,30}\boff\b|\b(disable|stop|no more|mute|kill|cancel)\b|\boff\b", tt)
        if not (on or off):
            return False
        for pat, key in self.READOUT.items():
            if re.search(r"\b(read ?out|every lap)\b", tt) and re.search(pat, tt):
                cur = list(getattr(s, "lap_readout", None) or [])
                if off and not on:
                    cur = [w for w in cur if w != key]
                elif key not in cur:
                    cur.append(key)
                s.lap_readout = cur; save()
                return self.A("app_set", {"_variant": 1 if off and not on else 2})
        for pat, key in self.APP:
            if re.search(r"\b(" + pat + r")\b", tt) and hasattr(s, key):
                val = bool(on) and not (off and off.start() > on.start())
                setattr(s, key, val); save()
                return self.A("app_set", {"_variant": 2 if val else 1})
        return False

    def readout(self, tt):
        b = self.b
        if re.search(r"speed", tt):
            v = self.g("Speed")
            return self.A("rd", {"n": round(self.speed(v)), "speed unit": 1, "_variant": 1}) if v is not None else self.no()
        if re.search(r"rpm|revs|rounds", tt):
            v = self.g("RPM")
            return self.A("rd", {"n": int(round(v, -1)), "_variant": 2}) if v is not None else self.no()
        if re.search(r"throttle", tt):
            v = self.g("Throttle")
            return self.A("rd", {"percent": round(v * 100), "_variant": 3}) if v is not None else self.no()
        if re.search(r"brake", tt):
            v = self.g("Brake")
            return self.A("rd", {"percent": round(v * 100), "_variant": 4}) if v is not None else self.no()
        if re.search(r"steering", tt):
            v = self.g("SteeringWheelAngle")
            return self.A("rd", {"n": abs(round(math.degrees(v))), "_variant": 8 if v >= 0 else 9}) if v is not None else self.no()
        if re.search(r"clutch", tt):
            v = self.g("Clutch")
            return self.A("rd", {"percent": round((1 - v) * 100), "_variant": 10}) if v is not None else self.no()
        if re.search(r"voltage|battery", tt):
            v = self.g("Voltage")
            return self.A("rd", {"dec": round(v, 1), "_variant": 5}) if v else self.no()
        if re.search(r"oil level", tt):
            v = self.g("OilLevel")
            return self.A("rd", {"dec": round(v, 1), "fuel unit": 2, "_variant": 6}) if v else self.no()
        if re.search(r"water level", tt):
            v = self.g("WaterLevel")
            return self.A("rd", {"dec": round(v, 1), "fuel unit": 2, "_variant": 7}) if v else self.no()
        return self.no()

    # ------------------------------------------------------------------ notes
    def read_notes(self):
        from . import notes as N
        import json, os
        rows = []
        try:
            for line in open(N.PATH, encoding="utf-8"):
                r = json.loads(line)
                if r.get("time", 0) >= time.time() - 6 * 3600:
                    rows.append(r)
        except OSError:
            pass
        rows = [r for r in rows if not r.get("cleared")][-3:]
        if not rows:
            return self.A("nt_none")
        for r in rows:
            self.A("nt_read", {"txt": r.get("text", "")})
        return True

    def clear_notes(self):
        from . import notes as N
        import json, os
        try:
            rows = [json.loads(l) for l in open(N.PATH, encoding="utf-8")]
            for r in rows:
                if r.get("time", 0) >= time.time() - 6 * 3600:
                    r["cleared"] = True
            with open(N.PATH, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return self.A("nt_clear")
