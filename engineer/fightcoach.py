"""Live coaching in a fight (2026-10-25, request: "there should be something actively telling me during a fight where I
lose time to the opponent ahead or behind ... directly correlated to where I am on track", "like to tell me what to
adjust in the corners ahead to be faster").

Every car in my class is timed corner by corner: a stretch runs from the end of one corner to the end of the next, so
it holds the braking, the corner and the exit. For each stretch we keep, per car, the time, where the braking started
(the speed first dropping off the top speed of the straight), the slowest speed in the corner and the speed at the
exit - all from the cars' lap-distance movement, so it works the same for every car, live or in a replay.

While I'm in a fight (car ahead within 1.2 s, or car behind within 1.0 s) and the next corner is 250-700 m away, the
engineer compares my last two runs through that corner with the other car's. When he's been a tenth or more quicker
there, I hear where and why: he brakes later, carries more speed in the middle, or gets on the power earlier. When
I'm the quicker one against the car ahead, I'm told to attack there. One call per corner per rival every 90 s, and
at least 20 s between calls.
"""
from statistics import median
from .voice import PRIO_RACE

FIGHT_AHEAD_S, FIGHT_BEHIND_S = 1.2, 1.0
LOSE_S, GAIN_S = 0.08, 0.10


class FightCoach:
    def __init__(self, rc):
        self.rc = rc
        self.b = rc.b
        self.reset()

    def reset(self):
        self.key = None          # (track length, marks) the stretches were built for
        self.segs = []           # [(seg start m, corner start m, corner end m, clip key)]
        self.run = {}            # idx -> current stretch being timed
        self.data = {}           # idx -> {seg: [(time, brake_m, vmin, vexit)]}
        self.cool = {}

    # ------------------------------------------------------------------ stretches from the corner map
    def build(self, L):
        marks = list(getattr(self.b.c, "marks", None) or []) if getattr(self.b, "c", None) else []
        key = (round(L), tuple(marks))
        if key == self.key:
            return bool(self.segs)
        self.key, self.run, self.data = key, {}, {}
        self.segs = []
        n = len(marks)
        for j, (a, e, k) in enumerate(marks):
            prev_end = marks[j - 1][1] if n > 1 else e - L / 2
            if j == 0:
                prev_end -= L                       # the stretch into the first corner starts on the last lap
            self.segs.append((prev_end, a, e, k))
        return bool(self.segs)

    def seg_of(self, d, L):
        """Index of the stretch holding lap distance d (metres)."""
        for j, (s0, a, e, k) in enumerate(self.segs):
            if s0 <= d < e or s0 <= d - L < e:
                return j
        return 0 if self.segs else None

    # ------------------------------------------------------------------ every tick
    def tick(self, now):
        b, rc = self.b, self.rc
        L = b.track_len_m()
        if not L or not self.build(L):
            return
        st = rc.g("SessionTime", None)
        if st is None:
            return
        me = b.me()
        cars = set(rc.my_class_cars()) | {me}
        for i in cars:
            pos = rc.pos.get(i)
            if not pos or now - pos[1] > 0.5:
                self.run.pop(i, None)
                continue
            p, _, spd = pos
            self.track(i, p * L, spd * L * 3.6, st, L, bool(rc.at("CarIdxOnPitRoad", i, False)))
        self.coach(me, L)

    def track(self, i, d, kmh, st, L, onp):
        j = self.seg_of(d, L)
        if j is None:
            return
        r = self.run.get(i)
        if r is None or r["j"] != j:
            if r is not None and j == (r["j"] + 1) % len(self.segs) and not r["dirty"] and not onp:
                t = st - r["t0"]
                if 1.0 < t < 200 and r["vmin"] < 999:
                    rec = (t, r["brake"], r["vmin"], kmh)
                    lst = self.data.setdefault(i, {}).setdefault(r["j"], [])
                    lst.append(rec)
                    del lst[:-3]
            fresh = r is None
            self.run[i] = r = {"j": j, "t0": st, "vpeak": 0.0, "brake": None, "vmin": 999.0, "dirty": fresh or onp}
        if onp:
            r["dirty"] = True
        s0, a, e, k = self.segs[j]
        dd = d if s0 <= d < e else d - L
        if dd < a:                                       # the approach: top speed, then where the speed drops off
            if r["brake"] is None:
                if kmh > r["vpeak"]:
                    r["vpeak"] = kmh
                elif r["vpeak"] > 80 and kmh < r["vpeak"] * 0.97 and a - dd < 450:
                    r["brake"] = dd
        else:
            r["vmin"] = min(r["vmin"], kmh)

    # ------------------------------------------------------------------ the call
    def stats(self, i, j):
        lst = (self.data.get(i) or {}).get(j) or []
        if len(lst) < 2:
            return None
        lst = lst[-2:]
        br = [x[1] for x in lst if x[1] is not None]
        return (median(x[0] for x in lst), median(br) if br else None,
                median(x[2] for x in lst), median(x[3] for x in lst))

    def once(self, key, every):
        now = self.b.clock()
        if now - self.cool.get(key, -1e9) < every:
            return False
        self.cool[key] = now
        return True

    def coach(self, me, L):
        b, rc = self.b, self.rc
        if not b.is_race() or not getattr(b, "green_seen", False) or rc.caution():
            return
        if not rc.g("IsOnTrack", True) or rc.g("OnPitRoad", False):
            return
        mpos = rc.pos.get(me)
        if not mpos:
            return
        ahead, ga, behind, gb = b.neighbours()
        rivals = []
        if ahead is not None and ga is not None and ga <= FIGHT_AHEAD_S:
            rivals.append((ahead, "ahead"))
        if behind is not None and gb is not None and gb <= FIGHT_BEHIND_S:
            rivals.append((behind, "behind"))
        if not rivals:
            return
        d = mpos[0] * L
        # the next corner 250-700 m up the road (not while in a corner)
        nxt = None
        for j, (s0, a, e, k) in enumerate(self.segs):
            ahead_m = (a - d) % L
            if 250 <= ahead_m <= 700:
                nxt = j
                break
        if nxt is None:
            return
        mine = self.stats(me, nxt)
        if not mine:
            return
        k = self.segs[nxt][3]
        for i, side in rivals:
            his = self.stats(i, nxt)
            if not his:
                continue
            diff = mine[0] - his[0]                       # + = he's quicker through here
            if diff >= LOSE_S:
                why = self.why(mine, his)
                if self.once(("fc", i, nxt), 90) and self.once("fc", 20):
                    v = {"brake": 1, "mid": 2, "exit": 3, "gen": 4}[why] + (0 if side == "ahead" else 4)
                    b.log(f"[fight] {side} car {b.car_num(i)} quicker into {k} by {diff:.2f}s ({why})")
                    rc.say("fc_lose", {"corner": k, "_variant": v}, prio=PRIO_RACE, max_age=6)
                    return
            elif side == "ahead" and diff <= -GAIN_S:
                if self.once(("fcg", i, nxt), 120) and self.once("fc", 20):
                    b.log(f"[fight] quicker than car {b.car_num(i)} into {k} by {-diff:.2f}s")
                    rc.say("fc_gain", {"corner": k}, prio=PRIO_RACE, max_age=6)
                    return

    @staticmethod
    def why(mine, his):
        _, mb, mv, mx = mine
        _, hb, hv, hx = his
        if mb is not None and hb is not None and hb - mb >= 12:
            return "brake"                                # he starts braking 12 m+ later
        if hv - mv >= 4:
            return "mid"                                  # 4 km/h+ more at the slowest point
        if hx - mx >= 4:
            return "exit"                                 # 4 km/h+ more coming out
        return "gen"
