"""When a car ahead in our class pits (2026-10-25, request: "if someone ahead in class pits I want it to tell us if it
is possible to catch them or not or if we will pass them while they're in the pits").

Gaps are worked out from where the cars are on track (laps completed + lap fraction, times our lap time), so they keep
working while a car sits in its pit box and in replays.

  * They turn into the pit lane: how far ahead they are against what a stop costs here (what stops have cost
    the other cars in this race, else this car's usual lane loss plus a tyre change). We say if we jump them
    while they stop, if it'll be close, or how far ahead they'll come out.
  * A few seconds after they leave the pits: the real answer. They're behind us now, or they're X ahead and
    it takes Y a lap to catch them before the flag (or it's too much to catch on pace).
  * What each stop cost them is remembered for the rest of the race, so the next guess is better.
"""


from .voice import PRIO_RACE


class PitWatch:
    LOOK = 90.0          # only cars up to this many seconds ahead are worth a call
    CLOSE = 4.0          # within this many seconds of the stop cost = "it'll be close"

    def __init__(self, brain):
        self.b = brain
        self.reset()

    def reset(self):
        self.prev = {}         # car -> on pit road last tick
        self.entry = {}        # car -> (gap ahead at entry, time)
        self.losses = []       # what stops cost the other cars this race (s)
        self.done = {}         # car -> last time we spoke about it
        self.pit_t = {}        # car -> last time it was on pit road (other cars)
        self.stop_t = {}       # car -> when its last stop began
        self.my_stop_t = -1e9  # when our last stop began
        self.my_was = False
        self.cand = {}         # car -> time it became a pit-cycle candidate (was ahead of us around a stop)
        self.cycle_said = set()
        self.cycle_check_t = 0

    # ---------------------------------------------------------------- helpers
    def lap_s(self):
        return self.b.pace_est() or 100.0

    def progress(self, idx):
        lc = self.b.g("CarIdxLapCompleted") or []
        pct = self.b.g("CarIdxLapDistPct") or []
        if idx >= len(lc) or idx >= len(pct) or lc[idx] is None or pct[idx] is None or pct[idx] < 0 or lc[idx] < 0:
            return None
        return lc[idx] + pct[idx]

    def gap_ahead(self, idx):
        """Seconds car idx is ahead of us on the road (negative = behind us)."""
        a, m = self.progress(idx), self.progress(self.b.me())
        if a is None or m is None:
            return None
        return (a - m) * self.lap_s()

    def stop_cost(self):
        if self.losses:
            xs = sorted(self.losses)
            return xs[len(xs) // 2]
        h = self.b.hist() or {}
        return float(h.get("lane_loss") or 28.0) + float(h.get("tyre_time") or 22.0)

    # ---------------------------------------------------------------- every tick (from brain.pit)
    def pitted_recently(self, idx, within=90.0):
        """This car has been on pit road in the last `within` seconds (or is on it now)."""
        return self.b.clock() - self.pit_t.get(idx, -1e9) <= within

    def live_pos(self):
        """Our class place by where everyone is on the road right now (laps + lap fraction)."""
        b = self.b
        cid, _ = b.my_class()
        m = self.progress(b.me())
        if m is None:
            return None
        return 1 + sum(1 for i in b.class_cars(cid) if i != b.me() and (self.progress(i) or -1) > m)

    def tick(self):
        b = self.b
        if not (b.is_race() and b.green_seen):
            return set()
        now = b.clock()
        # our own stop: every class car within a minute ahead becomes a pit-cycle candidate
        mine_on = bool(b.g("OnPitRoad", False))
        if mine_on and not self.my_was:
            self.my_stop_t = now
            cid, _ = b.my_class()
            for i in b.class_cars(cid):
                g = self.gap_ahead(i) if i != b.me() else None
                if g is not None and 0 < g <= 60:
                    self.cand.setdefault(i, now)
        self.my_was = mine_on
        if now - self.cycle_check_t >= 1.0:
            self.cycle_check_t = now
            self.check_cycle()
        spoke = set()
        me = b.me()
        onp = b.g("CarIdxOnPitRoad") or []
        cid, _ = b.my_class()
        mp = b.class_pos(me)
        we_in_pits = bool(b.g("OnPitRoad", False))
        now = b.clock()
        for idx in b.class_cars(cid):
            if idx == me or idx >= len(onp):
                continue
            on = bool(onp[idx])
            was = self.prev.get(idx, on)
            self.prev[idx] = on
            if on:
                self.pit_t[idx] = now
            if on and not was:
                self.stop_t[idx] = now
                gap = self.gap_ahead(idx)
                ahead = mp and 0 < b.class_pos(idx) < mp
                if gap is None or gap <= 0 or not ahead or we_in_pits:
                    continue
                self.entry[idx] = (gap, now)
                if gap <= 60:
                    self.cand.setdefault(idx, now)
                if gap > self.LOOK or now - self.done.get(idx, -1e9) < 120:
                    continue
                margin = gap - self.stop_cost()
                car = b.car_num(idx)
                b.log(f"[pitwatch] car {car} pits {gap:.1f}s ahead; a stop costs ~{self.stop_cost():.0f}s -> margin {margin:+.1f}")
                if margin < -self.CLOSE:
                    ok = b.say("pit_jump", {"car": car}, prio=PRIO_RACE, key="pitwatch")
                elif margin <= self.CLOSE:
                    ok = b.say("pit_jump_close", {"car": car}, prio=PRIO_RACE, key="pitwatch")
                else:
                    ok = b.say("pit_jump_no", {"car": car, "gap": margin}, prio=PRIO_RACE, key="pitwatch")
                if ok:
                    self.done[idx] = now; spoke.add(idx)
            elif was and not on and idx in self.entry:
                b.later(4, lambda i=idx: self.after_exit(i))
        return spoke

    def after_exit(self, idx):
        b = self.b
        if idx not in self.entry:
            return
        gap0, t0 = self.entry.pop(idx)
        gap = self.gap_ahead(idx)
        if gap is None or b.g("OnPitRoad", False) or b.clock() - t0 > 400:
            return
        loss = gap0 - gap
        if 8 < loss < 240:
            self.losses.append(loss)
        car = b.car_num(idx)
        b.log(f"[pitwatch] car {car} back out: {gap:+.1f}s (the stop cost {loss:.1f}s)")
        if gap0 > self.LOOK:
            return
        if gap < 0:
            b.say("pit_jumped", {"car": car}, prio=PRIO_RACE, key="pitwatch2")
            return
        ltg = b.laps_to_go()
        if not ltg or ltg < 2:
            return
        need = gap / ltg
        if need <= 0.8:
            b.say("pit_catch", {"car": car, "gap": gap, "dec": round(need, 1)}, prio=PRIO_RACE, key="pitwatch2")
        else:
            b.say("pit_catch_no", {"car": car, "gap": gap}, prio=PRIO_RACE, key="pitwatch2")

    def check_cycle(self):
        """2026-10-25 (request: "make him say something if we jump a car through pit strategy, like we just got Px from
        the undercut / overcut"): a car that was ahead of us around a round of stops, both of us have now stopped,
        both are back out, and it's behind us on the road - the strategy won the place. Undercut when we stopped first,
        overcut when they did."""
        b = self.b
        if b.g("OnPitRoad", False):
            return
        onp = b.g("CarIdxOnPitRoad") or []
        now = b.clock()
        for idx, t0 in list(self.cand.items()):
            if now - t0 > 900:                       # a stale pairing (nobody stopped): forget it
                self.cand.pop(idx, None); continue
            ts, tm = self.stop_t.get(idx, -1e9), self.my_stop_t
            if ts < t0 - 120 or tm < t0 - 120 or idx in self.cycle_said:
                continue                              # one of us hasn't stopped in this round yet
            if idx < len(onp) and onp[idx]:
                continue
            g = self.gap_ahead(idx)
            if g is None or g > -0.5:
                continue
            self.cycle_said.add(idx); self.cand.pop(idx, None)
            pos = self.live_pos()
            kind = "pit_cycle_undercut" if tm < ts else "pit_cycle_overcut"
            b.log(f"[pitwatch] {kind}: car {b.car_num(idx)} now {-g:.1f}s behind; we're P{pos}")
            if pos:
                b.say(kind, {"P": pos}, prio=PRIO_RACE, key="pitcycle", cooldown=20)
