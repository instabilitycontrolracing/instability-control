"""Racecraft calls (2026-10-24, DRE parity round 2 - Angelo: "build it all").

A  racecraft     striking distance, where to pass / defend (sector by sector), a rival losing time, black flag
                 "box this lap", slow or stopped car ahead, rival black flag / meatball, projected finish,
                 qualifying lap "on for P..." / "lap's gone"
B  pit and car   reposition the car in the box, TC/ABS reminder when it gets wet, pit approach and limiter
                 tones, a rival switching tyres, when a rival last stopped
C  voice         holds talk while someone is on iRacing voice chat (brain), connection warnings, new questions:
                 is car X dangerous, my pace vs car X, where will we finish, when do I catch him, where can I
                 pass, when did car X stop, a small calculator

Everything reads per-car data (CarIdx...), so most of it also works while watching a replay. Positions that
drop out for a moment (iRacing does that) are bridged for up to 3 s from the car's last speed.
New lines play in the stand-in voice until they're approved and recorded (lines_new.py).
"""
import math, re
from statistics import median
from .voice import PRIO_URGENT, PRIO_RACE, PRIO_INFO

TS_OFF, TS_STALL, TS_APPROACH, TS_ON = 0, 1, 2, 3
F_BLACK, F_REPAIR, F_CAUTION, F_CAUTION_WAVING = 0x10000, 0x100000, 0x4000, 0x8000
W_LIMITER = 0x10
PITSV_MSG = {100: 1, 101: 2, 102: 3, 103: 4, 104: 5}     # PlayerCarPitSvStatus -> pos_fix variant


class Racecraft:
    def __init__(self, brain):
        self.b = brain
        self.reset()

    # ------------------------------------------------------------------ helpers
    def s(self, k, d=True):
        return getattr(self.b.s, k, d)

    def g(self, k, d=None):
        return self.b.g(k, d)

    def arr(self, k):
        return self.g(k) or []

    def at(self, k, i, d=None):
        a = self.arr(k)
        return a[i] if 0 <= i < len(a) and a[i] is not None else d

    def say(self, sid, fills=None, prio=PRIO_INFO, cooldown=0, key=None, max_age=None):
        return self.b.say(sid, fills, prio=prio, cooldown=cooldown, key=key, max_age=max_age)

    def reset(self):
        self.sess = None
        self.pos = {}            # idx -> (pct, t, speed pct/s)
        self.sec = {}            # idx -> {"cur": s, "t0": time, "times": {1: [], 2: [], 3: []}, "dirty": bool}
        self.laps = {}           # idx -> {"lc": n, "times": [...], "pitted": bool, "last_stop_lap": n|None}
        self.gaps = {}           # idx -> [(my lap, gap)]
        self.cool = {}
        self.flags = {}
        self.comp = {}
        self.my_lc = None
        self.t_slow = 0.0
        self.bf_lap = None
        self.pct_prev = None
        self.svs_prev = 0
        self.wet_prev = None
        self.ew_prev = 0
        self.tone_t = 0.0
        self.net = {"base": [], "bad_since": None, "bad": False, "good_since": None}
        self.ql_lap = None
        self.proj_said = None
        # Batch D (2026-10-24)
        self.pace_prev = 0
        self.caution_prev = False
        self.pc_said = False
        self.pit_exit_pcts = []
        self.onp_prev = {}
        self.leader = None
        self.class_best = {}
        self.offs = {}            # idx -> off-track count (all cars)
        self.off_since = {}
        self.on_track_prev = None
        self.sig_t = {}

    def once(self, key, every):
        now = self.b.clock()
        if now - self.cool.get(key, -1e9) < every:
            return False
        self.cool[key] = now
        return True

    def my_class_cars(self):
        cid, _ = self.b.my_class()
        return self.b.class_cars(cid)

    def rel(self, i):
        """'ahead' / 'behind' in class order, or None."""
        me = self.b.me()
        pm, pi = self.b.class_pos(me), self.b.class_pos(i)
        if not pm or not pi:
            return None
        return "ahead" if pi < pm else "behind"

    def pct(self, i):
        """Lap position 0..1, bridging short dropouts from the car's last speed."""
        p = self.at("CarIdxLapDistPct", i, -1)
        now = self.b.clock()
        if p is not None and p >= 0:
            return p
        last = self.pos.get(i)
        if last and now - last[1] < 3.0:
            return (last[0] + last[2] * (now - last[1])) % 1.0
        return None

    def caution(self):
        f = int(self.g("SessionFlags", 0) or 0)
        return bool(f & (F_CAUTION | F_CAUTION_WAVING)) or getattr(self.b, "caution_on", False)

    def pace(self, i):
        d = self.laps.get(i)
        if not d or len(d["times"]) < 2:
            return None
        return median(d["times"][-3:])

    def ltg(self):
        return self.b.laps_to_go()

    # ------------------------------------------------------------------ every tick
    def tick(self):
        b = self.b
        if b.sess_num != self.sess:
            self.reset(); self.sess = b.sess_num
        if not self.s("calls_racecraft"):
            return
        now = b.clock()
        try:
            self.track_cars(now)
            self.my_lap(now)
            self.black_flag_box()
            self.pit_box_position()
            self.pit_tones(now)
            self.off_tracks(now)
            self.signals(now)
            self.auto_telemetry()
            if now - self.t_slow >= 0.25:
                self.t_slow = now
                self.slow_cars(now)
                self.rival_flags()
                self.rival_tyres()
                self.wet_aids()
                self.connection(now)
                self.quali_lap()
                self.caution_nav()
                self.opponent_pit_exit()
                self.leader_change()
        except Exception as e:
            b.log(f"[racecraft] {e!r}")

    # -------------------------------------------------- per-car tracking (positions, sectors, laps)
    def track_cars(self, now):
        st = self.g("SessionTime", None)
        if st is None:
            return
        lc_arr, lt_arr, onp_arr = self.arr("CarIdxLapCompleted"), self.arr("CarIdxLastLapTime"), self.arr("CarIdxOnPitRoad")
        mine = set(self.my_class_cars()) | {self.b.me()}
        for i in self.b.drivers():
            p = self.at("CarIdxLapDistPct", i, -1)
            if p is not None and p >= 0:
                last = self.pos.get(i)
                spd = last[2] if last else 0.0
                if last and now > last[1]:
                    dp = (p - last[0]) % 1.0
                    if dp < 0.2:
                        spd = 0.7 * spd + 0.3 * dp / (now - last[1])
                self.pos[i] = (p, now, spd)
            if i not in mine:
                continue
            onp = bool(onp_arr[i]) if i < len(onp_arr) else False
            # sectors (thirds of the lap, same as the engineer's own sector calls)
            pp = self.pct(i)
            if pp is not None:
                s = min(3, int(pp * 3) + 1)
                d = self.sec.setdefault(i, {"cur": s, "t0": st, "times": {1: [], 2: [], 3: []}, "dirty": True})
                if onp:
                    d["dirty"] = True
                if s != d["cur"]:
                    done, t = d["cur"], st - d["t0"]
                    ok = s == done % 3 + 1 and not d["dirty"] and 1 < t < 300
                    d["cur"], d["t0"] = s, st
                    if ok:
                        d["times"][done] = (d["times"][done] + [t])[-4:]
                        self.sector_best(i, done, t)
                    if done == 3 or not ok:
                        d["dirty"] = onp
            # laps
            lc = lc_arr[i] if i < len(lc_arr) else None
            if lc is None or lc < 0:
                continue
            L = self.laps.setdefault(i, {"lc": lc, "times": [], "pitted": True, "last_stop_lap": None, "lap_onp": onp})
            if onp:
                L["pitted"] = True
                if not L.get("lap_onp"):
                    L["last_stop_lap"] = lc
            L["lap_onp"] = onp
            if lc != L["lc"]:
                t = lt_arr[i] if i < len(lt_arr) else None
                clean = not L["pitted"] and t and 0 < t < 1000 and not self.caution()
                prev = list(L["times"])
                if clean:
                    L["times"] = (L["times"] + [t])[-6:]
                L["lc"], L["pitted"] = lc, onp
                if t and t > 0 and not onp:
                    self.rival_time_loss(i, t, prev, L)

    # -------------------------------------------------- A3 a rival lost big time last lap
    def rival_time_loss(self, i, t, prev, L):
        b = self.b
        if i == b.me() or not b.is_race() or not b.green_seen or self.caution() or len(prev) < 2:
            return
        base = median(prev[-3:])
        lost = t - base
        mp, ip = b.class_pos(b.me()), b.class_pos(i)
        if not mp or not ip or abs(mp - ip) > 3 or not (4 <= lost < 90):
            return
        if L.get("last_stop_lap") is not None and L["lc"] - L["last_stop_lap"] <= 1:
            return                                             # that was a pit lap
        if self.once(("tl", i), 180) and self.once("tl", 20):
            self.say("tl_rival", {"car": b.car_num(i), "n": min(60, round(lost)), "_variant": 1 if ip < mp else 2},
                     prio=PRIO_INFO, max_age=10)

    # -------------------------------------------------- once a lap for me: striking distance, sectors, finish
    def my_lap(self, now):
        b = self.b
        lc = self.g("LapCompleted", -1)
        if lc is None or lc < 0 or lc == self.my_lc:
            return
        first = self.my_lc is None
        self.my_lc = lc
        if first or not b.is_race() or not b.green_seen or self.caution():
            return
        ahead, ga, behind, gb = b.neighbours()
        for i, g in ((ahead, ga), (behind, gb)):
            if i is not None and g is not None:
                self.gaps[i] = (self.gaps.get(i, []) + [(lc, g)])[-6:]
        said = self.striking(lc, ahead, ga, behind, gb, auto=True)
        if not said:
            said = self.sector_vulnerability(ahead, ga, behind, gb, auto=True)
        ltg = self.ltg()
        total = (ltg or 0) + lc
        if not said and ltg and total > 6 and lc >= total * 0.4 and lc % 5 == 0:
            self.projected_finish(auto=True)

    def closing(self, i, sign):
        """Seconds a lap the gap to car i is shrinking (sign: +1 ahead, +1 behind; both 'gap gets smaller')."""
        h = self.gaps.get(i, [])
        if len(h) < 3:
            return None
        (l0, g0), (l1, g1) = h[max(0, len(h) - 4)], h[-1]
        if l1 <= l0:
            return None
        return (g0 - g1) / (l1 - l0)

    def striking(self, lc, ahead, ga, behind, gb, auto=False, ask=None):
        b = self.b
        ltg = self.ltg() or 99
        out = None
        if ask in (None, "ahead") and ahead is not None and ga is not None:
            r = self.closing(ahead, 1)
            if r and r > 0.12 and ga > (1.2 if auto else 0):
                n = math.ceil(ga / r)
                if 2 <= n <= min(12, ltg):
                    out = ("sd_catch", {"car": b.car_num(ahead), "laps": n}, ("sd", ahead))
                elif not auto:
                    out = ("sd_flat", {}, None)
            elif not auto:
                out = ("sd_flat", {}, None)
        if out is None and ask in (None, "behind") and behind is not None and gb is not None:
            r = self.closing(behind, 1)
            if r and r > 0.12 and gb > (1.2 if auto else 0):
                n = math.ceil(gb / r)
                if 2 <= n <= min(12, ltg):
                    out = ("sd_caught", {"car": b.car_num(behind), "laps": n}, ("sd", behind))
                elif not auto:
                    out = ("sd_safe", {}, None)
            elif not auto:
                out = ("sd_safe", {}, None)
        if out is None:
            if not auto:
                self.say("tb_no_data", prio=PRIO_URGENT)
            return False
        sid, f, key = out
        if auto and (key is None or not self.once(key, 5 * (self.b.pace_est() or 120))):
            return False
        self.say(sid, f, prio=PRIO_URGENT if not auto else PRIO_INFO, max_age=10)
        return True

    def sector_diff(self, i):
        """[(sector, his median - my median)] for sectors with data. Positive = I'm faster there."""
        me = self.b.me()
        a, m = self.sec.get(i), self.sec.get(me)
        if not a or not m:
            return []
        out = []
        for s in (1, 2, 3):
            ta, tm = a["times"][s][-3:], m["times"][s][-3:]
            if len(ta) >= 2 and len(tm) >= 2:
                out.append((s, median(ta) - median(tm)))
        return out

    def sector_vulnerability(self, ahead, ga, behind, gb, auto=False, ask=None):
        b = self.b
        if ask in (None, "pass") and ahead is not None and (not auto or (ga is not None and ga < 1.5)):
            d = [x for x in self.sector_diff(ahead) if x[1] >= 0.15]
            if d:
                s = max(d, key=lambda x: x[1])[0]
                if not auto or self.once(("sva", ahead), 300):
                    self.say("sv_attack", {"car": b.car_num(ahead), "sector": s}, prio=PRIO_INFO if auto else PRIO_URGENT, max_age=12)
                    return True
        if ask in (None, "defend") and behind is not None and (not auto or (gb is not None and gb < 1.5)):
            d = [x for x in self.sector_diff(behind) if x[1] <= -0.15]
            if d:
                s = min(d, key=lambda x: x[1])[0]
                if not auto or self.once(("svd", behind), 300):
                    self.say("sv_defend", {"car": b.car_num(behind), "sector": s}, prio=PRIO_INFO if auto else PRIO_URGENT, max_age=12)
                    return True
        if not auto:
            self.say("sv_none" if (ahead is not None or behind is not None) else "tb_no_data", prio=PRIO_URGENT)
        return False

    # -------------------------------------------------- A7 projected finish
    def projected(self):
        b = self.b
        me = b.me()
        ltg, pm, fm = self.ltg(), self.pace(me) or b.pace_est(), b.f2(me)
        if not ltg or not pm or fm is None:
            return None
        ahead = 0
        for i in self.my_class_cars():
            if i == me:
                continue
            fi, pi = b.f2(i), self.pace(i)
            if fi is None or fi <= 0 and b.class_pos(i) == 0:
                continue
            gap_end = (fi - fm) + ((pi - pm) * ltg if pi else 0.0)     # >0 = behind us at the flag
            if gap_end < 0:
                ahead += 1
        return ahead + 1

    def projected_finish(self, auto=False):
        p = self.projected()
        if not p:
            if not auto:
                self.say("tb_no_data", prio=PRIO_URGENT)
            return
        cur = self.b.class_pos(self.b.me())
        if auto and (p == cur or p == self.proj_said):
            return
        self.proj_said = p
        self.say("proj_finish", {"P": p}, prio=PRIO_INFO if auto else PRIO_URGENT, max_age=15)

    # -------------------------------------------------- A4 black flag: box this lap
    def black_flag_box(self):
        b = self.b
        f = int(self.g("SessionFlags", 0) or 0)
        p = self.g("LapDistPct", -1)
        prev, self.pct_prev = self.pct_prev, p
        if not (f & F_BLACK) or not b.is_race() or self.caution() or p is None or prev is None:
            return
        if prev < 0.85 <= p and self.bf_lap != self.g("LapCompleted", 0):
            self.bf_lap = self.g("LapCompleted", 0)
            self.say("bf_box", prio=PRIO_URGENT)

    # -------------------------------------------------- A5 slow or stopped car ahead
    def slow_cars(self, now):
        b = self.b
        if not self.g("IsOnTrack", False) or self.g("OnPitRoad", False) or b.alone() or self.caution():
            return
        my_spd = self.g("Speed", 0) or 0
        if my_spd < 20:
            return
        L = b.track_len_m()
        me = b.me()
        mp = self.pct(me)
        if mp is None:
            return
        for i, (p, t, spd) in list(self.pos.items()):
            if i == me or now - t > 1.0:
                continue
            surf = self.at("CarIdxTrackSurface", i, TS_ON)
            if surf not in (TS_ON, TS_OFF) or self.at("CarIdxOnPitRoad", i, False):
                continue
            ahead_m = ((p - mp) % 1.0) * L
            if not (60 <= ahead_m <= 650):
                continue
            v = spd * L                                         # m/s
            if v > 9 or v > my_spd * 0.35:
                continue
            if not self.once(("slow", i), 25):
                continue
            corner = (b.c.at(p * L) or b.c.nearest_behind(p * L, 250)) if getattr(b, "c", None) else None
            sid = "stopped_ahead" if v < 2.5 else "slow_ahead"
            f = {"corner": corner, "_variant": 1} if corner else {"_variant": 2}
            self.say(sid, f, prio=PRIO_URGENT, max_age=3)
            return

    # -------------------------------------------------- A6 a rival's black flag / meatball
    def rival_flags(self):
        b = self.b
        if not b.is_race():
            return
        fl = self.arr("CarIdxSessionFlags")
        mp = b.class_pos(b.me())
        for i in self.my_class_cars():
            if i == b.me() or i >= len(fl):
                continue
            f = int(fl[i] or 0)
            was = self.flags.get(i, f)
            self.flags[i] = f
            ip = b.class_pos(i)
            if not mp or not ip or abs(mp - ip) > 3:
                continue
            v = 1 if ip < mp else 2
            if (f & F_BLACK) and not (was & F_BLACK) and self.once(("rfb", i), 120):
                self.say("rf_black", {"car": b.car_num(i), "_variant": v}, prio=PRIO_INFO, max_age=10)
            elif (f & F_REPAIR) and not (was & F_REPAIR) and self.once(("rfm", i), 120):
                self.say("rf_meatball", {"car": b.car_num(i), "_variant": v}, prio=PRIO_INFO, max_age=10)

    # -------------------------------------------------- B4 a rival switching tyres
    def rival_tyres(self):
        b = self.b
        if not b.is_race():
            return
        tc = self.arr("CarIdxTireCompound")
        mp = b.class_pos(b.me())
        for i in self.my_class_cars():
            if i == b.me() or i >= len(tc) or tc[i] is None or tc[i] < 0:
                continue
            c = int(tc[i])
            was = self.comp.get(i)
            self.comp[i] = c
            ip = b.class_pos(i)
            if was is None or was == c or not mp or not ip or abs(mp - ip) > 3:
                continue
            wet = c >= 1                                         # iRacing: 0 = dry, 1+ = wet
            ahead = ip < mp
            v = (1 if ahead else 2) if wet else (3 if ahead else 4)
            if self.once(("rt", i), 60):
                self.say("rt_compound", {"car": b.car_num(i), "_variant": v}, prio=PRIO_INFO, max_age=15)

    # -------------------------------------------------- B1 reposition the car in the box
    def pit_box_position(self):
        s = int(self.g("PlayerCarPitSvStatus", 0) or 0)
        prev, self.svs_prev = self.svs_prev, s
        if s != prev and s in PITSV_MSG and self.g("OnPitRoad", False):
            self.say("pos_fix", {"_variant": PITSV_MSG[s]}, prio=PRIO_URGENT)

    # -------------------------------------------------- B2 TC / ABS when it gets wet
    def wet_aids(self):
        wet = int(self.g("TrackWetness", 0) or 0)
        prev, self.wet_prev = self.wet_prev, wet
        if prev is None or not self.g("IsOnTrack", False):
            return
        if prev < 3 <= wet and self.once("wet_aids", 900):        # 3 = lightly wet
            self.b.later(4, lambda: self.say("wet_aids", prio=PRIO_RACE))

    # -------------------------------------------------- B3 pit approach + limiter tones
    def pit_tones(self, now):
        if not self.s("pit_tones"):
            return
        from .extras import play_beep
        ew = int(self.g("EngineWarnings", 0) or 0)
        if (ew & W_LIMITER) and not (self.ew_prev & W_LIMITER) and self.g("IsOnTrack", False):
            self._beep(1800, 50); self.b.later(0.12, lambda: self._beep(2200, 50))     # limiter on: two quick pips
        self.ew_prev = ew
        surf = self.at("CarIdxTrackSurface", self.b.me(), TS_ON)
        plim = self.b.pit_limit_ms() if hasattr(self.b, "pit_limit_ms") else None
        spd = self.g("Speed", 0) or 0
        if surf == TS_APPROACH and plim and not self.g("OnPitRoad", False) and not (ew & W_LIMITER) and spd > plim + 0.8:
            over = spd - plim
            gap = max(0.12, 0.5 - over * 0.02)                 # faster beeps the more you're over
            if now - self.tone_t >= gap:
                self.tone_t = now
                self._beep(1200, 45)

    def _beep(self, hz, ms):
        from .extras import play_beep
        class _S:   # reuse the shift beep player with its own tone (volume capped there)
            pass
        x = _S()
        x.shift_pitch, x.shift_length = hz, ms
        x.shift_volume = min(0.3, float(getattr(self.b.s, "shift_volume", 0.25) or 0.25))
        x.device = getattr(self.b.s, "device", None)
        play_beep(x)

    # -------------------------------------------------- C3 connection warnings
    def connection(self, now):
        if not self.s("net_warnings") or self.g("IsReplayPlaying", False) or not self.g("IsOnTrack", False):
            return
        lat, q = self.g("ChanLatency"), self.g("ChanQuality")
        if not lat or q is None or lat <= 0:
            return
        n = self.net
        if len(n["base"]) < 240:
            n["base"].append(lat)
            return
        base = median(n["base"])
        bad = q < 0.75 or lat > max(base * 2.0, base + 0.08)
        if bad:
            n["good_since"] = None
            n["bad_since"] = n["bad_since"] or now
            if not n["bad"] and now - n["bad_since"] >= 4 and self.once("net", 180):
                n["bad"] = True
                self.say("net_bad", prio=PRIO_RACE)
        else:
            n["bad_since"] = None
            if n["bad"]:
                n["good_since"] = n["good_since"] or now
                if now - n["good_since"] >= 20:
                    n["bad"] = False
                    self.say("net_ok", prio=PRIO_INFO)

    # -------------------------------------------------- A7b qualifying: is this lap worth finishing?
    def quali_lap(self):
        b = self.b
        if not b.is_quali() or getattr(b.x, "lap_kind", None) != "push":
            return
        p = self.g("LapDistPct", -1)
        lc = self.g("LapCompleted", 0)
        if p is None or p < 0.66 or p > 0.72 or self.ql_lap == lc:
            return
        if not self.g("LapDeltaToBestLap_OK", False):
            return
        best = self.g("LapBestLapTime", 0) or 0
        if best <= 0:
            return
        self.ql_lap = lc
        pred = best + (self.g("LapDeltaToBestLap", 0) or 0)
        if pred > best + 0.4:
            self.say("ql_abort", prio=PRIO_RACE, max_age=4)
            return
        bests = self.arr("CarIdxBestLapTime")
        me = b.me()
        ahead = sum(1 for i in self.my_class_cars() if i != me and i < len(bests) and bests[i] and 0 < bests[i] < pred)
        newp, cur = ahead + 1, b.class_pos(me)
        if not cur or newp < cur:
            self.say("ql_on", {"P": newp}, prio=PRIO_RACE, max_age=4)


    # ================================================================== Batch D (2026-10-24)
    # -------------------------------------------------- D1 caution rules: lucky dog, wave around, end of line,
    # hold position, pace car gap. iRacing: CarIdxPaceFlags bits EndOfLine 0x1, FreePass 0x2, WavedAround 0x4.
    def caution_nav(self):
        b = self.b
        if not b.is_race():
            return
        me = b.me()
        pf = int(self.at("CarIdxPaceFlags", me, 0) or 0)
        prev, self.pace_prev = self.pace_prev, pf
        rise = lambda m: (pf & m) and not (prev & m)
        if rise(0x2):
            self.say("cn_free", prio=PRIO_URGENT)
        elif rise(0x4):
            self.say("cn_wave", prio=PRIO_URGENT)
        elif rise(0x1):
            self.say("cn_eol", prio=PRIO_URGENT)
        cau = self.caution()
        if cau and not self.caution_prev:
            self.pc_said = False
            if not (pf & 0x6):
                b.later(8, lambda: self.say("cn_hold", prio=PRIO_RACE))
        self.caution_prev = cau
        if cau and not self.pc_said and self.g("IsOnTrack", False) and not self.g("OnPitRoad", False):
            pc = next((d["CarIdx"] for d in (b.info("DriverInfo", {}) or {}).get("Drivers", []) or [] if d.get("CarIsPaceCar")), None)
            if pc is None:
                return
            pp, mp = self.at("CarIdxLapDistPct", pc, -1), self.pct(me)
            if pp is None or pp < 0 or mp is None:
                return
            ahead_s = ((pp - mp) % 1.0) * (self.b.pace_est() or 120) * 1.6     # caution pace is slower
            # first time we're the car right behind the pace car area: within 2-15 s and nobody between us
            between = [i for i in b.drivers() if i != me and self.pct(i) is not None
                       and 0 < (self.pct(i) - mp) % 1.0 < (pp - mp) % 1.0 and self.at("CarIdxTrackSurface", i, TS_ON) == TS_ON]
            if 2 <= ahead_s <= 15 and not between:
                self.pc_said = True
                self.say("pc_gap", {"gap": ahead_s}, prio=PRIO_RACE)

    # -------------------------------------------------- D2 opponents coming out of the pits as you reach the merge
    def opponent_pit_exit(self):
        b = self.b
        onp = self.arr("CarIdxOnPitRoad")
        L = b.track_len_m()
        for i in b.drivers():
            o = bool(onp[i]) if i < len(onp) else False
            if self.onp_prev.get(i) and not o:
                p = self.pct(i)
                if p is not None:
                    self.pit_exit_pcts = (self.pit_exit_pcts + [p])[-15:]     # learn where the pit exit is
            self.onp_prev[i] = o
        if len(self.pit_exit_pcts) < 2 or not self.g("IsOnTrack", False) or self.g("OnPitRoad", False) or b.alone():
            return
        ex = median(self.pit_exit_pcts)
        me = b.me()
        mp = self.pct(me)
        if mp is None:
            return
        to_exit = ((ex - mp) % 1.0) * L                       # metres until we pass the pit exit
        if not (80 <= to_exit <= 450):
            return
        for i in b.drivers():
            if i == me or not (i < len(onp) and onp[i]):
                continue
            p, last = self.pct(i), self.pos.get(i)
            if p is None or not last:
                continue
            before_exit = ((ex - p) % 1.0) * L
            if before_exit < 250 and last[2] * L > 12 and self.once(("opx", i), 40):      # moving down the exit road
                self.say("op_exit", {"car": b.car_num(i)}, prio=PRIO_URGENT, max_age=4)
                return

    # -------------------------------------------------- D3 new class leader
    def leader_change(self):
        b = self.b
        if not b.is_race() or not b.green_seen:
            return
        lead = next((i for i in self.my_class_cars() if b.class_pos(i) == 1), None)
        prev, self.leader = self.leader, lead
        if prev is not None and lead is not None and lead != prev and lead != b.me() and self.once("leader", 30):
            self.say("ld_class", {"car": b.car_num(lead)}, prio=PRIO_INFO, max_age=10)

    # -------------------------------------------------- D4 fastest sector in class (race and qualifying)
    def sector_best(self, i, sec, t):
        b = self.b
        best = self.class_best.get(sec)
        if best is None or t < best:
            self.class_best[sec] = t
            n_with = sum(1 for d in self.sec.values() if d["times"][sec])
            if i == b.me() and best is not None and n_with >= 3 and (b.is_race() or b.is_quali()) and self.once(("ps", sec), 60):
                self.say("ps_class", {"sector": sec}, prio=PRIO_INFO, max_age=6)

    # -------------------------------------------------- D6 off-track counts for every car (incidents are hidden in
    # official races) - feeds "how many off tracks?", "is he dangerous?" and "how many incidents has car X?"
    def off_tracks(self, now):
        surf = self.arr("CarIdxTrackSurface")
        for i in self.b.drivers():
            if i >= len(surf):
                continue
            off = surf[i] == TS_OFF
            st = self.off_since.get(i)
            if off and st is None:
                self.off_since[i] = now
            elif off and st is not None and st > 0 and now - st >= 0.3:
                self.off_since[i] = -1.0
                self.offs[i] = self.offs.get(i, 0) + 1
            elif not off:
                self.off_since[i] = None

    def est_offs(self, i):
        return self.offs.get(i, 0)

    # -------------------------------------------------- D8 automatic telemetry recording (.ibt) in and out of the car
    def auto_telemetry(self):
        if not self.s("auto_telemetry") or self.g("IsReplayPlaying", False):
            return
        on = bool(self.g("IsOnTrack", False))
        prev, self.on_track_prev = self.on_track_prev, on
        if prev is None or on == prev:
            return
        ir = getattr(self.b.src, "ir", None)
        if ir is None:
            return
        try:
            import irsdk
            ir.telem_command(irsdk.TelemCommandMode.start if on else irsdk.TelemCommandMode.stop)
            self.b.log(f"[racecraft] telemetry recording {'started' if on else 'stopped'}")
        except Exception as e:
            self.b.log(f"[racecraft] telemetry: {e!r}")

    # -------------------------------------------------- D9 optional sound signals (off by default)
    def signals(self, now):
        b = self.b
        if not self.g("IsOnTrack", False) or self.g("IsReplayPlaying", False):
            return
        def every(key, gap):
            if now - self.sig_t.get(key, -1e9) >= gap:
                self.sig_t[key] = now
                return True
            return False
        thr, brk = self.g("Throttle", 0) or 0, self.g("Brake", 0) or 0
        if self.s("sig_overlap", False) and brk > 0.1 and thr > 0.1 and (self.g("Speed", 0) or 0) > 15 and every("ov", 0.25):
            self._beep(700, 35)                                            # brake + throttle together
        if self.s("sig_spray", False) and int(self.g("TrackWetness", 0) or 0) >= 5:
            me, mp, L = b.me(), self.pct(b.me()), b.track_len_m()
            if mp is not None:
                near = min((((self.pct(i) - mp) % 1.0) * L for i in b.drivers() if i != me and self.pct(i) is not None
                            and self.at("CarIdxTrackSurface", i, TS_ON) == TS_ON), default=9999)
                if 5 < near < 120 and every("spray", 0.15 + near / 200):    # closer = faster pulses
                    self._beep(320, 40)
        if self.s("sig_revlimit", False):
            di = b.info("DriverInfo", {}) or {}
            blink = float(di.get("DriverCarSLBlinkRPM") or 0)
            if blink > 0 and (self.g("RPM", 0) or 0) >= blink and every("rev", 0.3):
                self._beep(2600, 30)
        if self.s("sig_launch", False) and b.is_race() and int(self.g("SessionState", 0) or 0) in (3, 4) and not b.green_seen:
            lead = next((i for i in self.my_class_cars() if b.class_pos(i) == 1), None)
            rpm = self.at("CarIdxRPM", lead, 0) if lead is not None and lead != b.me() else 0
            if rpm and every("launch", 0.15):
                self._beep(int(300 + min(rpm, 9000) / 9), 60)               # pitch follows the class leader's revs

    # ------------------------------------------------------------------ radio: questions and requests
    # -------------------------------------------------- driver feedback after "tyre phase / brake shape update"
    TYRE = r"\b(tyres?|tires?|rubber|grip|rears?|fronts?|front left|front right|rear left|rear right)\b"
    BRAKE = r"\b(brakes?|braking|pedal|stopping)\b"
    GOOD = r"\b(good|fine|ok|okay|great|alright|all right|perfect|mint|holding( up)?|no problems?|strong|plenty)\b"
    BAD = (r"\b(gone|going( off)?|dropping( off)?|falling off|bad|graining|blistering|overheating|hot|worn|dead|done|"
           r"finished|sliding|degrading|struggling|no grip|losing grip|fading|fade|long|soft|spongy|locking|lock(ing)? up|locks|cooked)\b")

    def feedback(self, tt):
        """'Tyres are good, brakes are fading' -> one reply per part. True if it was feedback."""
        import re as _re
        # a note, a chat message or a question isn't a report on the car ("remind me the brakes feel soft")
        if _re.search(r"^\s*(remind|remember|set a reminder|make a note|note|take a note|chat|send|say|start (writing|typing)|type|tell)\b", tt) \
                or _re.search(r"\b(remember|remind me|make a note)\b", tt) \
                or _re.search(r"^\s*(is|are|do|does|did|which|what|whats|how|should|can|could|will|would|not sure)\b", tt):
            return False
        if _re.search(r"\b(all good|everything('?s| is)? (good|fine|ok|okay)|car('?s| is)? (good|fine|ok|okay)|all fine|no problems)\b", tt) \
                and not _re.search(self.BAD, tt):
            self.say("fb_all_good", prio=PRIO_URGENT); return True
        said = False
        segs = []
        for chunk in _re.split(r"\b(?:but|and|while)\b|,", tt):
            # speech comes without commas: "tires feel fine brakes are good" -> one piece per thing talked about
            subs = []
            for m in _re.finditer(self.TYRE + "|" + self.BRAKE, chunk):
                same = subs and bool(_re.match(self.TYRE, m.group(0))) == bool(_re.match(self.TYRE, subs[-1].group(0)))
                if same and m.start() - subs[-1].end() <= 2:
                    continue                                  # "front left tyre" = one subject
                subs.append(m)
            if len(subs) <= 1:
                segs.append(chunk); continue
            for k, m in enumerate(subs):
                a = subs[k - 1].end() if k else 0
                z = subs[k + 1].start() if k + 1 < len(subs) else len(chunk)
                segs.append(chunk[a:z] if k else chunk[:z])
        for part in segs:
            tyre, brake = _re.search(self.TYRE, part), _re.search(self.BRAKE, part)
            bad, good = _re.search(self.BAD, part), _re.search(self.GOOD, part)
            if not (tyre or brake) or not (bad or good):
                continue
            if brake and not tyre:
                if bad and _re.search(r"lock", part):
                    self.say("fb_brakes_lock", prio=PRIO_URGENT)
                    self._incar_tip("front_lock", None)
                elif bad:
                    self.say("fb_brakes_bad", prio=PRIO_URGENT)
                else:
                    self.say("fb_brakes_good", prio=PRIO_URGENT)
            else:
                if bad:
                    rear, front = _re.search(r"\brears?\b|rear (left|right)", part), _re.search(r"\bfronts?\b|front (left|right)", part)
                    self.say("fb_tyres_bad", {"_variant": 2 if rear and not front else 3 if front and not rear else 1}, prio=PRIO_URGENT)
                    if rear and not front:
                        self._incar_tip("traction", None)          # TC up one (offer: "do it")
                    self.b.feedback_note = "tyres are gone"          # the pit plan takes tyres at the next stop
                else:
                    self.say("fb_tyres_good", prio=PRIO_URGENT)
            said = True
        return said

    def _incar_tip(self, prob, phase):
        ic = getattr(self.b, "incar", None)
        if ic is not None:
            try:
                ic.advise(prob, phase, reported=True)
            except Exception as e:
                self.b.log(f"[incar] {e!r}")

    def command(self, text):
        """New questions (C4). True if handled."""
        from .intents import normalize
        from .extras import words_to_numbers, lic_parts
        b = self.b
        t = " " + normalize(text).strip() + " "
        tt = " " + words_to_numbers(t) + " "
        x = b.x
        # calculator: "what's 25 percent of 80", "12 times 3", "80 divided by 4"
        m = re.search(r"(\d+(?:\.\d+)?)\s*(percent of|% of|times|x|plus|minus|divided by|over)\s*(\d+(?:\.\d+)?)", tt)
        if m and re.search(r"\b(what|whats|what s|calculate|how much is)\b", tt):
            a, op, c = float(m.group(1)), m.group(2), float(m.group(3))
            r = {"percent of": a * c / 100, "% of": a * c / 100, "times": a * c, "x": a * c, "plus": a + c,
                 "minus": a - c}.get(op)
            if r is None:
                r = a / c if c else None
            if r is None:
                self.say("tb_no_data", prio=PRIO_URGENT); return True
            if abs(r - round(r)) < 0.05:
                self.say("calc", {"n": int(round(r)), "_variant": 1}, prio=PRIO_URGENT)
            else:
                self.say("calc", {"dec": round(r, 1), "_variant": 2}, prio=PRIO_URGENT)
            return True
        if self.feedback(tt):
            return True
        ahead, ga, behind, gb = b.neighbours()
        # D6: how many off tracks have I got
        if re.search(r"how many (off ?tracks|track limits|times (have i been|i've been|i went) off)|off ?track count|my off ?tracks", tt):
            n_ot = self.est_offs(b.me()) or getattr(b, "tl_count", 0)
            self.say("ot_count", {"n": n_ot, "_variant": 2 if n_ot == 1 else 1}, prio=PRIO_URGENT); return True
        # D5: where's car 33 / where's P1 / where's the leader
        m = re.search(r"where('?s| is)?( the)? (car|number) (\d{1,3})|where('?s| is)?( the)? (p|position) ?(\d{1,2})|where('?s| is)? the (class )?leader", tt)
        if m:
            idx = None
            if m.group(4):
                idx = x.num_to_idx(m.group(4))
            elif m.group(8):
                idx = next((i for i in self.my_class_cars() if b.class_pos(i) == int(m.group(8))), None)
            else:
                idx = next((i for i in self.my_class_cars() if b.class_pos(i) == 1), None)
            if idx is None:
                self.say("tb_no_data", prio=PRIO_URGENT); return True
            if self.at("CarIdxOnPitRoad", idx, False):
                self.say("wh_car", {"car": b.car_num(idx), "_variant": 3}, prio=PRIO_URGENT); return True
            fm, fi, p = b.f2(b.me()), b.f2(idx), b.class_pos(idx)
            if fm is None or fi is None or not p:
                self.say("tb_no_data", prio=PRIO_URGENT); return True
            self.say("wh_car", {"car": b.car_num(idx), "P": p, "gap": abs(fi - fm), "_variant": 1 if fi < fm else 2}, prio=PRIO_URGENT)
            return True
        # where will we finish
        if re.search(r"where (will|do|are) (we|i) (finish|end up)|projected|finish position|will (i|we) finish|on for", tt):
            self.projected_finish(); return True
        # striking distance
        if re.search(r"\b(is|are) (he|they|the car behind|anyone|somebody) catching|catching me|how long (until|till) .*catch(es)? me", tt):
            self.striking(None, ahead, ga, behind, gb, ask="behind"); return True
        if re.search(r"when (do|will|can) (i|we) catch|how long (until|till) (i|we) catch|am i catching|are we catching|can (i|we) catch", tt):
            self.striking(None, ahead, ga, behind, gb, ask="ahead"); return True
        # where to pass / defend
        if re.search(r"where (can|do|should|could) (i|we) (pass|attack|overtake|get him)|where am i faster|where (are|am) (we|i) quicker", tt):
            self.sector_vulnerability(ahead, ga, behind, gb, ask="pass"); return True
        if re.search(r"where (do|should) (i|we) defend|where is he (faster|quicker)|where('?s| is)? he (faster|quicker)", tt):
            self.sector_vulnerability(ahead, ga, behind, gb, ask="defend"); return True
        about_car = re.search(r"\b(car|number) \d{1,3}\b|\b(car|guy|driver|he|him) (ahead|behind|in front)\b|\b(ahead|behind)\b|\bleader\b", tt)
        if about_car:
            idx = x.car_from_text(tt)
            # is car X dangerous
            if re.search(r"dangerous|careful with|safe driver|clean driver|crasher|wreck(er|less)|is (he|car \d+) (ok|okay|clean)", tt):
                if idx is None:
                    self.say("tb_no_data", prio=PRIO_URGENT); return True
                d = x.driver(idx)
                lic, sr = lic_parts(d.get("LicString"))
                inc = d.get("CurDriverIncidentCount")
                if inc is None or inc < 0:
                    inc = self.est_offs(idx) * 2                 # official races hide incidents: estimate from off-tracks
                danger = x.is_marked(d) or (sr is not None and sr < 2.0) or lic == "R" or (inc is not None and inc >= 12)
                self.say("dg_yes" if danger else "dg_no", {"car": b.car_num(idx)}, prio=PRIO_URGENT)
                return True
            # my pace vs car X
            if re.search(r"pace (compared|vs|versus|against|to)|faster than|quicker than|slower than|my pace", tt):
                if idx is None:
                    self.say("tb_no_data", prio=PRIO_URGENT); return True
                pm, pi = self.pace(b.me()) or b.pace_est(), self.pace(idx)
                if not pm or not pi:
                    self.say("tb_no_data", prio=PRIO_URGENT); return True
                d = pi - pm
                if abs(d) < 0.1:
                    self.say("pv_same", {"car": b.car_num(idx)}, prio=PRIO_URGENT)
                else:
                    self.say("pv_faster" if d > 0 else "pv_slower", {"car": b.car_num(idx), "gap": abs(d)}, prio=PRIO_URGENT)
                return True
            # when did car X stop / how old are his tyres
            if re.search(r"(when did|has|did) .{0,20}(stop|pit|box)|tyre age|tire age|how old .{0,10}(tyres|tires)|(fresh|new|old) (tyres|tires)", tt):
                if idx is None:
                    self.say("tb_no_data", prio=PRIO_URGENT); return True
                L = self.laps.get(idx, {})
                lc = self.at("CarIdxLapCompleted", idx)
                if L.get("last_stop_lap") is None or lc is None:
                    self.say("rt_nostop", {"car": b.car_num(idx)}, prio=PRIO_URGENT)
                else:
                    self.say("rt_stint", {"car": b.car_num(idx), "n": max(0, lc - L["last_stop_lap"])}, prio=PRIO_URGENT)
                return True
        return False
