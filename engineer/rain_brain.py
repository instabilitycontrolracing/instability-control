"""Rain brain (#591, 2026-10-30): is it drying or getting wetter, will it rain any more, and when do slicks (or wets)
become the faster tyre. Plain maths on live telemetry - no AI at race time, and no made-up numbers.

Three parts:
  RainTrend      rolling TrackWetness (last twenty minutes) + Precipitation (last five) -> drying / steady / wetter, with a
                 confidence (low / medium / high) that grows with how long and how consistently we have watched it.
  CompoundLaps   real lap times on each compound this session: your own laps and the other cars in your class
                 (CarIdxTireCompound + CarIdxLastLapTime), so we can see when the slick runners start beating the wet ones.
  crossover()    when slicks become faster than wets (or the other way), from the measured lap-time gap where we have
                 one, shaped by the penalty table in rain.py where we don't. The answer is "now", "in about N laps",
                 "not this stint", or "can't say yet" - with how sure we are and where the numbers came from.

RainBrain ties them together for the strategist: it is fed every tick and every lap, answers the radio questions
("will it rain any more?", "is it drying?", "when do we go to slicks?"), and makes its own calls at the switch
points (respecting the tow / after-the-flag quiet rules and a throttle).

NO NEW SPOKEN LINES WITHOUT APPROVAL: every new line here is a PENDING clip id (rb_*). It plays only once it is
rendered into the engineer's library (the voice has it); until then the answer is shown as text (app radio log,
overlay caption, iPad). The wording waits for the owner: see PENDING below and the rain_brain line proposals.
Existing recorded lines are used where they truly fit (box_wets, rain_worse, ty_opt).

iRacing gives no live forecast in telemetry or the session info (2026 SDK: WeekendInfo has TrackPrecipitation /
TrackWeatherType / TrackSkies, no forecast timeline). forecast_from_info() reads what is there and any forecast-like
field a later SDK adds, and copes with all of it missing. The season schedule's rain chance (strategist _forecast())
is used as the race forecast when known.
"""
import math
from collections import deque
from statistics import median

from . import rain as R

# ------------------------------------------------------------------ thresholds (all in one place, all explainable)
SAMPLE_S = 5.0            # one wetness / rain sample every 5 s of session time
WINDOW_S = 1200.0         # the wetness trend looks at the last twenty minutes (iRacing moves a level every 10-20 min)
PRECIP_WINDOW_S = 300.0   # the rain itself (heavier / easing) over the last five minutes: it changes faster
MIN_SPAN_S = 90.0         # less than this watched: "too early to say"
SLOPE_LVL_MIN = 0.04      # wetness levels per minute that count as drying / wetter (one level in 25 minutes)
RAIN_ON = 0.02            # Precipitation above this = raining (askmore.py uses the same)
RAIN_OFF = 0.005
PRECIP_STEP = 0.03        # precipitation change over the window that counts as heavier / easing
FIELD_WINDOW_S = 240.0    # other cars' laps compared over the last four minutes (and at least two laps)
CALL_GAP_S = 90.0         # proactive rain calls: at least this long apart
HEAVIER_GAP_S = 300.0     # "rain's getting heavier" at most every five minutes
CONF = ("none", "low", "medium", "high")

# ------------------------------------------------------------------ new lines, PENDING the owner's approval
# (in their own file, with no imports, so tools/vocab_spec.py can read them for rendering once approved)
from .rain_brain_lines import PENDING  # noqa: E402
PENDING_IDS = {sid for sid, _ in PENDING}
PENDING_TEXT = {sid: t for sid, t in PENDING}


def _num(x):
    try:
        v = float(str(x).replace("%", "").split()[0])
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, IndexError):
        return None


def forecast_from_info(weekend_info):
    """What the session info says about the weather. Every field may be missing (older / newer SDKs, replays).
    -> {"precip_pct": TrackPrecipitation as a number or None, "weather_type": str, "static": bool,
        "forecast": any forecast-like field the SDK exposes (raw) or None}"""
    wk = weekend_info if isinstance(weekend_info, dict) else {}
    opts = wk.get("WeekendOptions") if isinstance(wk.get("WeekendOptions"), dict) else {}
    wt = str(wk.get("TrackWeatherType") or opts.get("WeatherType") or "")
    fc = None
    for d in (wk, opts):
        for k, v in d.items():
            if "forecast" in str(k).lower() and v not in (None, "", [], {}):
                fc = v
    low = wt.lower()
    return {"precip_pct": _num(wk.get("TrackPrecipitation")), "weather_type": wt,
            "static": ("static" in low or "constant" in low) and "dynamic" not in low, "forecast": fc}


# ------------------------------------------------------------------ 1. the trend
def _slope(ts, ys):
    """Least-squares slope (per second) and the fitted value at the last time."""
    n = len(ts)
    mt, my = sum(ts) / n, sum(ys) / n
    sxx = sum((t - mt) ** 2 for t in ts)
    if sxx <= 0:
        return 0.0, ys[-1]
    b = sum((t - mt) * (y - my) for t, y in zip(ts, ys)) / sxx
    return b, my + b * (ts[-1] - mt)


class RainTrend:
    """Rolling wetness + rain. add() every tick (it keeps one sample every SAMPLE_S); state() whenever asked."""

    def __init__(self, window_s=WINDOW_S):
        self.window_s = window_s
        self.s = deque()                 # (session time, wetness 1..7, precipitation 0..1)
        self.rained = False              # rain seen at any point this session
        self.max_precip = 0.0

    def reset(self):
        self.__init__(self.window_s)

    def add(self, t, wet, precip):
        try:
            t = float(t)
        except (TypeError, ValueError):
            return
        w = _num(wet)
        p = _num(precip)
        if w is None or w < 1:            # 0 = unknown (iRacing's enum), nothing to learn
            return
        p = max(0.0, min(1.0, p or 0.0))
        if self.s and t < self.s[-1][0] - 1:          # time went backwards (replay jump / new session): start over
            self.s.clear()
        if self.s and t - self.s[-1][0] < SAMPLE_S:
            return
        self.s.append((t, max(1.0, min(7.0, w)), p))
        self.rained = self.rained or p > RAIN_ON
        self.max_precip = max(self.max_precip, p)
        while self.s and self.s[-1][0] - self.s[0][0] > self.window_s:
            self.s.popleft()

    def state(self):
        """-> {"dir": "drying"|"steady"|"wetter"|"unknown", "conf": "none"|"low"|"medium"|"high",
               "rate": wetness levels per minute (+ wetter), "level": wetness now (whole level), "level_fit": smoothed,
               "precip": now, "precip_dir": "heavier"|"easing"|"steady", "raining": bool, "span_min": minutes watched,
               "ups"/"downs": wetness level changes seen}"""
        out = {"dir": "unknown", "conf": "none", "rate": 0.0, "level": None, "level_fit": None, "precip": None,
               "precip_dir": "steady", "raining": False, "span_min": 0.0, "ups": 0, "downs": 0, "rained": self.rained}
        if not self.s:
            return out
        ts = [x[0] for x in self.s]
        ws = [x[1] for x in self.s]
        ps = [x[2] for x in self.s]
        span = ts[-1] - ts[0]
        lvl, p = int(round(ws[-1])), ps[-1]
        out.update(level=lvl, level_fit=float(lvl), precip=p, raining=p > RAIN_ON, span_min=span / 60.0)
        if len(self.s) < 3 or span < MIN_SPAN_S:
            out["conf"] = "low" if len(self.s) >= 2 else "none"
            return out
        ups = sum(1 for a, b in zip(ws, ws[1:]) if b > a)
        downs = sum(1 for a, b in zip(ws, ws[1:]) if b < a)
        bw, fit = _slope(ts, ws)
        k0 = next((k for k, t in enumerate(ts) if ts[-1] - t <= PRECIP_WINDOW_S), 0)
        tp, pp = ts[k0:], ps[k0:]
        bp, _ = _slope(tp, pp) if len(tp) >= 3 else (0.0, pp[-1])
        rate = bw * 60.0
        dp = pp[-1] - pp[0]
        pdir = "heavier" if (dp >= PRECIP_STEP and bp > 0) else "easing" if (dp <= -PRECIP_STEP and bp < 0) else "steady"
        # wetness is a whole number: the fitted value tells how far between levels we are (kept within half a level)
        out.update(rate=rate, level_fit=max(lvl - 0.5, min(lvl + 0.49, fit)), precip_dir=pdir, ups=ups, downs=downs)
        if rate <= -SLOPE_LVL_MIN and downs > ups:
            d = "drying"
        elif rate >= SLOPE_LVL_MIN and ups > downs:
            d = "wetter"
        elif pdir == "heavier" and p > 0.05 and downs == 0:
            d = "wetter"                  # the rain is building before the track has caught up
        else:
            d = "steady"
        out["dir"] = d
        # how sure: longer watched and more consistent = surer
        if d == "steady":
            mixed = ups and downs
            conf = "high" if span >= 480 and not (ups or downs) else "medium" if span >= 300 and not mixed else "low"
        else:
            n = downs if d == "drying" else ups
            agree = (p < RAIN_OFF or pdir == "easing") if d == "drying" else (p > 0.05 or pdir == "heavier")
            back = ups if d == "drying" else downs
            if n >= 2 and agree and span >= 360 and not back:
                conf = "high"
            elif (n >= 2 or (n >= 1 and agree)) and span >= 240:
                conf = "medium"
            else:
                conf = "low"
            if n == 0:                    # precipitation-only "wetter": never more than medium
                conf = "medium" if span >= 240 and p > 0.1 else "low"
        out["conf"] = conf
        return out


# ------------------------------------------------------------------ 2. real lap times on each compound
class CompoundLaps:
    """Lap times on each compound this session: your laps and the other cars in your class.

    feed() every tick with the per-car arrays; a lap counts when the car didn't touch the pit lane during it, it isn't
    the first lap on new tyres, and it isn't far off that car's pace (spins, cautions)."""

    def __init__(self):
        self.cars = {}                    # idx -> {"lc", "pit", "after_pit", "comp"}
        self.laps = []                    # (session time, idx, is_wet_compound, lap time, wetness, mine)

    def reset(self):
        self.__init__()

    def feed(self, t, lcs, last, comps, onpit, wet, me, mine_class, wet_index):
        """lcs / last / comps / onpit: CarIdxLapCompleted / CarIdxLastLapTime / CarIdxTireCompound / CarIdxOnPitRoad.
        mine_class: the car indices in my class (other classes are a different pace). wet_index: my car's wet
        compound number (DriverInfo.DriverTires); the same class runs the same tyre list."""
        if not lcs or t is None:
            return
        for i in mine_class:
            if i >= len(lcs):
                continue
            lc = lcs[i]
            if lc is None or lc < 0:
                continue
            c = self.cars.setdefault(i, {"lc": lc, "pit": False, "after_pit": 0, "comp": None})
            if i < len(onpit) and onpit[i]:
                c["pit"], c["after_pit"] = True, 1       # the laps with pit lane in them, and the first lap on the new set
            comp = comps[i] if i < len(comps) else None
            if lc > c["lc"]:
                lt = last[i] if i < len(last) else None
                ok = lt is not None and 0 < lt < 1200 and not c["pit"] and c["after_pit"] == 0 and lc == c["lc"] + 1
                if ok and comp is not None and comp >= 0:
                    self.laps.append((float(t), i, int(comp) == int(wet_index), float(lt), float(wet or 0), i == me))
                if c["after_pit"] and not c["pit"]:
                    c["after_pit"] -= 1
                c["pit"] = bool(i < len(onpit) and onpit[i])
                c["lc"] = lc
            elif lc < c["lc"]:                           # session reset / replay jump
                c["lc"] = lc
            c["comp"] = comp
        if len(self.laps) > 4000:
            self.laps = self.laps[-3000:]

    def _groups(self, laps, best=None):
        """Per compound: each car's median lap (normalised by that car's best when known) -> {wet: [times]}."""
        per = {}
        for _, i, w, lt, _, _ in laps:
            per.setdefault((i, w), []).append(lt)
        norm = None
        if best:
            bs = [b for b in best.values() if b and b > 0]
            norm = median(bs) if len(bs) >= 3 else None
        out = {True: [], False: []}
        for (i, w), xs in per.items():
            m = median(xs)
            b = (best or {}).get(i)
            if norm and b and b > 0:
                m *= norm / b                            # take out driver speed: compare like with like
            out[w].append(m)
        for w in out:                                    # drop the far-off ones (spins, traffic, cautions)
            if len(out[w]) >= 3:
                med = median(out[w])
                out[w] = [x for x in out[w] if x <= med * 1.12]
        return out

    def field_now(self, t_now, lap_s=None, best=None):
        """Slick minus wet lap time right now (s; + = wets faster), from the recent laps of my class.
        -> (delta, n_slick_cars, n_wet_cars, standard error) or None when one compound has fewer than 2 cars."""
        win = max(FIELD_WINDOW_S, 2.2 * (lap_s or 0))
        recent = [x for x in self.laps if t_now - x[0] <= win]
        g = self._groups(recent, best)
        ns, nw = len(g[False]), len(g[True])
        if ns < 2 or nw < 2:
            return None
        ms, mw = median(g[False]), median(g[True])
        def se(xs):
            m = median(xs)
            mad = median([abs(x - m) for x in xs]) * 1.4826
            return max(mad, 0.003 * m) / math.sqrt(len(xs))
        return ms - mw, ns, nw, math.sqrt(se(g[False]) ** 2 + se(g[True]) ** 2)

    def by_level(self, best=None):
        """Slick minus wet at each whole wetness level this session, where both compounds ran (>= 2 cars each)."""
        out = {}
        for lvl in range(1, 8):
            xs = [x for x in self.laps if int(round(x[4])) == lvl]
            g = self._groups(xs, best)
            if len(g[False]) >= 2 and len(g[True]) >= 2:
                out[lvl] = (median(g[False]) - median(g[True]), len(g[False]), len(g[True]))
        return out

    def mine_by_level(self):
        """Your own laps: slick minus wet at each level where you ran both (this session)."""
        out = {}
        for lvl in range(1, 8):
            s = [x[3] for x in self.laps if x[5] and int(round(x[4])) == lvl and not x[2]]
            w = [x[3] for x in self.laps if x[5] and int(round(x[4])) == lvl and x[2]]
            if s and w:
                out[lvl] = (median(s) - median(w), len(s), len(w))
        return out


# ------------------------------------------------------------------ 3. the crossover
def table_delta(level, base, mine=None):
    """Slick minus wet lap time from the penalty table (rain.py), any wetness between 1 and 7 (interpolated)."""
    level = max(1.0, min(7.0, float(level)))
    lo = int(math.floor(level)); hi = min(7, lo + 1)
    f = level - lo
    d = lambda l: R.lap_on(base, l, False) - R.lap_on(base, l, True, mine)
    return d(lo) * (1 - f) + d(hi) * f


def _zero(fn, lo=1.0, hi=7.0, step=0.05):
    """The wetness where fn crosses zero (going from slicks faster to wets faster), or None."""
    prev_l, prev = lo, fn(lo)
    l = lo + step
    while l <= hi + 1e-9:
        v = fn(l)
        if prev <= 0 < v or prev < 0 <= v:
            return prev_l + (l - prev_l) * (-prev / (v - prev)) if v != prev else l
        prev_l, prev = l, v
        l += step
    return None


def _rank(c):
    return CONF.index(c) if c in CONF else 0


def _min_conf(*cs):
    return CONF[min(_rank(c) for c in cs)]


def crossover(trend, on_wets, base=None, lap_s=None, field=None, levels=None, mine_levels=None, mine=None,
              laps_left=None, stint_laps=None, stop_cost=None, stop_soon=False):
    """When does the other tyre become faster?

    trend        RainTrend.state()
    on_wets      on the wet compound now
    base         dry lap time (strategy model) for the table; lap_s = a lap now (to turn minutes into laps)
    field        CompoundLaps.field_now() (delta, n_slick, n_wet, se) or None
    levels / mine_levels   CompoundLaps.by_level() / mine_by_level()
    laps_left    laps to the flag; stint_laps = laps to the next planned stop (None = to the flag)
    stop_cost    seconds an extra stop costs (lane loss + tyres); stop_soon = a planned stop is this lap or next
    -> {"to": "slicks"|"wets", "call": "now"|"next"|"laps"|"not_this_stint"|"not_yet"|"unknown",
        "laps": N or None, "conf": ..., "source": "field"|"own"|"fit"|"table"|None, "gain": s a lap the other tyre
        is faster now (+) or slower (-) or None, "worth": True/False/None (pays for a stop), "level_x": crossover wetness,
        "why": short reason for the log / text}"""
    to = "slicks" if on_wets else "wets"
    out = {"to": to, "call": "unknown", "laps": None, "conf": "none", "source": None, "gain": None, "worth": None,
           "level_x": None, "why": "", "stop_soon": bool(stop_soon)}
    lvl = trend.get("level_fit") if trend.get("level_fit") is not None else trend.get("level")
    if lvl is None:
        out["why"] = "no wetness reading"
        return out
    # --- the slick-minus-wet curve: measured where we can, table-shaped where we can't
    pts = []                                          # (level, delta, weight, source)
    dconf, source = "none", None
    if field:
        d, ns, nw, se = field
        pts.append((lvl, d, min(ns, nw) / max(se, 0.05), "field"))
    for l, (d, ns, nw) in (levels or {}).items():
        if not field or abs(l - lvl) >= 0.75:         # the current level is already in "field" (more recent)
            pts.append((float(l), d, min(ns, nw) / 1.0, "field"))
    for l, (d, ns, nw) in (mine_levels or {}).items():
        pts.append((float(l), d, min(ns, nw) / 1.5, "own"))
    if not base and lap_s:
        # no dry pace stored yet: work it back from a lap now through the same table (so it is still "table", low)
        pen = (R.WET_PEN if on_wets else R.SLICK_PEN)[int(max(1, min(7, round(lvl))))]
        base = lap_s / (1 + pen)
    have_table = bool(base)
    curve = None
    lvls = {round(p[0]) for p in pts}
    if len(lvls) >= 2:                                # measured at two levels or more: fit a straight line
        sw = sum(p[2] for p in pts)
        ml = sum(p[0] * p[2] for p in pts) / sw
        md = sum(p[1] * p[2] for p in pts) / sw
        sxx = sum(p[2] * (p[0] - ml) ** 2 for p in pts)
        b = sum(p[2] * (p[0] - ml) * (p[1] - md) for p in pts) / sxx if sxx > 0 else 0
        if b > 0:                                     # wetter must favour wets; anything else is noise
            curve = lambda l, ml=ml, md=md, b=b: md + b * (l - ml)
            source = "fit"
            dconf = "high" if len(pts) >= 3 and sum(1 for p in pts if p[3] == "field") >= 2 else "medium"
    if curve is None and pts:
        near = min(pts, key=lambda p: (abs(p[0] - lvl), -p[2]))
        source = near[3]
        if near[3] == "field" and field and near[0] == lvl:
            d, ns, nw, se = field
            slope = abs(table_delta(lvl + 0.5, base, mine) - table_delta(lvl - 0.5, base, mine)) if have_table else None
            se_lvl = se / slope if slope else None
            if min(ns, nw) >= 4 and se_lvl is not None and se_lvl < 0.35:
                dconf = "high"
            elif se_lvl is None or se_lvl < 0.75:
                dconf = "medium"
            else:
                dconf = "low"
        else:
            dconf = "medium" if near[3] == "own" or abs(near[0] - lvl) < 0.75 else "low"
        if have_table:                                # measured offset on the table's shape
            off = near[1] - table_delta(near[0], base, mine)
            curve = lambda l, off=off: table_delta(l, base, mine) + off
        elif abs(near[0] - lvl) < 0.75:               # no table base: only what is measured right now
            curve = lambda l, d0=near[1]: d0
    if curve is None and have_table:
        curve = lambda l: table_delta(l, base, mine)
        source, dconf = "table", "low"
    if curve is None:
        out["why"] = "no lap data on either tyre and no dry pace for the table"
        return out
    out["source"] = source
    sign = -1 if on_wets else 1                       # gain of the OTHER tyre over mine: slicks gain = -(slick - wet)
    gain_at = lambda l: sign * curve(l)
    g_now = gain_at(lvl)
    out["gain"] = g_now
    lx = _zero(curve)
    out["level_x"] = lx
    tconf = trend.get("conf", "none")
    rate = trend.get("rate") or 0.0
    tdir = trend.get("dir")
    lap_s = lap_s or (base * (1 + (R.WET_PEN if on_wets else R.SLICK_PEN)[int(max(1, min(7, round(lvl))))]) if base else None)
    left = stint_laps if stint_laps is not None else laps_left

    def worth(laps_ahead):
        """Does switching now pay for a stop over the laps left (gain follows the trend)?"""
        if stop_cost is None or not laps_left or not lap_s:
            return None
        tot, l = 0.0, lvl
        for _ in range(int(laps_left)):
            tot += gain_at(l)
            l = max(1.0, min(7.0, l + rate * lap_s / 60.0))
        cost = (stop_cost * 0.35) if stop_soon else stop_cost      # at a planned stop only the tyre time is extra
        return tot > cost

    if g_now >= 0:                                    # the other tyre is already faster (or level)
        if source == "table" and lx is not None and abs(lvl - lx) >= 1.5:
            dconf = "medium"                          # far past the table's crossover: no doubt which tyre
        out.update(call="now", laps=0, conf=dconf, worth=worth(0),
                   why=f"{to} {g_now:.1f} s a lap faster now ({source})")
        return out
    # not faster yet: is the track heading its way?
    heading = (on_wets and tdir == "drying" and rate < 0) or (not on_wets and tdir == "wetter")
    if not heading:
        out.update(call="not_yet", conf=_min_conf(dconf, tconf if tconf != "none" else "low") if tdir != "unknown" else "low",
                   why=f"{to} {-g_now:.1f} s a lap slower now, track {tdir}")
        if tdir == "unknown":
            out["call"] = "unknown"
        return out
    if not on_wets and tdir == "wetter" and rate <= 0:   # rain building but the track hasn't moved yet
        out.update(call="not_yet", conf="low", why="rain building, track not wetter yet")
        return out
    if lx is None or rate == 0 or not lap_s:
        out.update(call="unknown", conf="low", why="trend known but no crossover level")
        return out
    mins = (lx - lvl) / rate                           # rate has the right sign by now
    if mins < 0:
        out.update(call="unknown", conf="low", why="crossover behind us on the curve")
        return out
    laps = mins * 60.0 / lap_s
    n = max(1, int(round(laps)))
    conf = _min_conf(dconf, tconf)
    out.update(laps=n, conf=conf, why=f"{to} faster at wetness {lx:.1f}, now {lvl:.1f}, {rate:+.2f}/min, {lap_s:.0f} s laps")
    if left is not None and laps > left + 0.5:
        out["call"] = "not_this_stint"
    else:
        out["call"] = "next" if n <= 1 else "laps"
    return out


# ------------------------------------------------------------------ 4. what to say
def _say(sid, text, fills=None, fallback=None, fb_fills=None):
    """sid = the line to play (a PENDING one plays only once rendered), text = what is shown, fallback = an existing
    clip that truly fits (played with the text on screen when sid isn't rendered yet)."""
    return {"sid": sid, "fills": fills or {}, "text": text, "fallback": fallback, "fb_fills": fb_fills or {}}


def _laps_word(n):
    return "lap" if n == 1 else "laps"


def conf_note(conf, source):
    if source == "table" and conf not in ("low", "none"):
        return " From the general wet-weather table, not lap times."
    if source == "table" or conf in ("low", "none"):
        return " Low confidence: " + ("from the general wet-weather table, not lap times." if source == "table"
                                       else "not much data yet.")
    if conf == "medium":
        return " Medium confidence."
    return ""


def answer_more(trend, forecast_pct=None, static=False):
    """"Will it rain any more?" -> what is said / shown."""
    if trend.get("level") is None and trend.get("precip") is None:
        return _say("rb_unsure", "No weather data yet.", fallback="tb_no_data")
    p = trend.get("precip") or 0.0
    if trend.get("raining"):
        pd = trend.get("precip_dir")
        pct = f"{p * 100:.0f} percent"
        if trend.get("conf") in ("none", "low") or trend.get("span_min", 0) < MIN_SPAN_S / 60:
            return _say("rb_more_steady", f"Still raining ({pct}). Too early to say if it's building or easing.")
        if pd == "heavier":
            return _say("rb_more_heavier", f"Still raining, and it's getting heavier ({pct} now).", fallback="rain_worse")
        if pd == "easing":
            return _say("rb_more_easing", f"Still raining, but it's easing off ({pct} now).")
        return _say("rb_more_steady", f"Still raining, about the same ({pct}).")
    if static:
        return _say("rb_more_static", "No rain now, and the weather is set to static for this session, so it shouldn't change.")
    if trend.get("rained"):
        return _say("rb_more_stopped", "Rain has stopped for now. iRacing doesn't give us a live forecast, so I'll call it if it starts again.")
    if forecast_pct is not None:
        f = int(5 * round(forecast_pct / 5))
        return _say("rb_more_none_fc", f"No rain now. The forecast for this race was {f} percent.", {"percent": f})
    return _say("rb_more_none", "No rain now. We don't get a live forecast for this session, so I'll call it if it starts.")


def answer_trend(trend):
    """"Is it drying?" / "is it getting wetter?" -> what is said / shown."""
    d, c = trend.get("dir"), trend.get("conf")
    lvl = trend.get("level")
    if lvl is None:
        return _say("rb_unsure", "No track wetness reading yet.", fallback="tb_no_data")
    name = R.WET_NAME.get(int(lvl), "wet")
    mins = trend.get("span_min", 0)
    if d == "unknown" or c in ("none",):
        return _say("rb_trend_unsure", f"Track is {name}. Too early to say which way it's going.")
    rate = abs(trend.get("rate") or 0) * 10
    tail = f" Track is {name}" + (f", about {rate:.1f} levels per ten minutes" if d != "steady" and rate >= 0.1 else "") + \
           f" (watched {mins:.0f} min, {c} confidence)."
    if c == "low":
        return _say("rb_trend_unsure", f"Not sure yet, it looks {d}." + tail)
    if d == "drying":
        return _say("rb_trend_drying", "The track is drying." + tail)
    if d == "wetter":
        fb = "rain_worse" if trend.get("raining") and trend.get("precip_dir") == "heavier" else None
        return _say("rb_trend_wetter", "The track is getting wetter." + tail, fallback=fb)
    return _say("rb_trend_steady", "The track is steady, not drying and not getting wetter." + tail)


def answer_switch(x, trend, on_wets, ask_for=None):
    """"When do we go to slicks?" / "should we switch tyres?" -> what is said / shown. x = crossover()."""
    lvl = trend.get("level")
    if lvl is None:
        return _say("rb_unsure", "No track wetness reading yet.", fallback="tb_no_data")
    to = x["to"]
    note = conf_note(x["conf"], x["source"])
    g = x.get("gain")
    # seconds a lap only when they come from real lap times (the table's numbers are a guess, so no number)
    gtxt = f" by about {abs(g):.1f} seconds a lap" if g is not None and x["source"] not in (None, "table") else ""
    if not on_wets and lvl <= 1 and not trend.get("raining"):
        return _say("ty_opt", "Track is dry. Slicks are right.", {"_variant": 1})
    if x["call"] == "unknown" or x["conf"] == "none":
        return _say("rb_unsure", f"I can't call the {to} yet. Not enough data." + (f" ({x['why']})" if x["why"] else ""),
                    fallback="tb_no_data")
    if x["call"] == "now" and x["conf"] == "low":
        # on the boundary and not sure (table only, or thin data): the existing line says exactly that -
        # "It's the crossover. Slicks if you are comfortable, wets if it gets worse."
        return _say("ty_opt", f"{to.capitalize()} look faster now{(',' + gtxt) if gtxt else ''}." + note, {"_variant": 3})
    if x["call"] == "now":
        if to == "slicks":
            if x["worth"] is True and x.get("stop_soon"):
                return _say("rb_slicks_now_stop", f"Slicks are faster now{(',' + gtxt) if gtxt else ''}. We take them at the stop." + note)
            if x["worth"] is True:
                return _say("rb_slicks_now_box", f"Slicks are faster now{(',' + gtxt) if gtxt else ''}. Box this lap for slicks." + note)
            if x["worth"] is False:
                return _say("rb_slicks_now_wait", f"Slicks are just faster now{(',' + gtxt) if gtxt else ''}, but not by enough to pay for a stop yet." + note)
            return _say("rb_slicks_now_box", f"Slicks are faster now{(',' + gtxt) if gtxt else ''}." + note)
        if x["worth"] is False:
            return _say("rb_wets_now_wait", f"Wets are faster now{(',' + gtxt) if gtxt else ''}, but not by enough to pay for a stop yet." + note)
        # the recorded "Box this lap for wets. Box for wets."
        return _say("box_wets", f"Wets are faster now{(',' + gtxt) if gtxt else ''}. Box this lap for wets." + note)
    if x["call"] in ("next", "laps"):
        n = x["laps"] or 1
        rough = x["conf"] == "low"
        if x["call"] == "next":
            return _say(f"rb_{to}_next", f"{to.capitalize()} should be faster next lap." + note)
        sid = f"rb_{to}_in_rough" if rough else f"rb_{to}_in"
        lead = "Rough guess, " if rough else ""
        return _say(sid, f"{lead}{to} should be faster in about {n} {_laps_word(n)}." + note, {"laps": n})
    if x["call"] == "not_this_stint":
        if to == "slicks":
            return _say("rb_slicks_not_stint", f"Not this stint. Stay on the wets (slicks maybe in about {x['laps']} laps)." + note)
        return _say("rb_wets_not", f"Stay on slicks. Wets not this stint (maybe in about {x['laps']} laps)." + note)
    # not_yet: the track isn't heading that way
    td = trend.get("dir")
    if to == "slicks":
        return _say("rb_slicks_not_yet", f"Not yet. Slicks are slower{gtxt} and the track is {td}, not drying. Stay on the wets." + note)
    return _say("rb_wets_not", f"Stay on slicks. Wets aren't faster yet, the track is {td}." + note)


# ------------------------------------------------------------------ 5. the whole thing, for the strategist
class RainBrain:
    """Fed by the strategist (strat_live.py) every tick and lap. Answers questions; makes the switch-point calls.

    say_clip(sid, fills, answer) -> bool    plays a clip if the engineer's library has it (False = not rendered yet)
    show(role, text)                text on the app radio log / overlay / iPad (no voice)
    quiet() -> bool                 True while no proactive call may be made (towed, after the flag, not driving)
    """

    def __init__(self, say_clip=None, show=None, quiet=None, log=print, clock=None):
        self.say_clip = say_clip or (lambda sid, fills=None, answer=False: False)
        self.show = show or (lambda role, text: None)
        self.quiet = quiet or (lambda: False)
        self.log = log
        import time as _t
        self.clock = clock or _t.time
        self.reset()

    def reset(self):
        self.trend = RainTrend()
        self.laps = CompoundLaps()
        self.last_call_t = -1e9
        self.last_heavier_t = -1e9
        self.called = set()           # calls made for the current approach (cleared when the situation changes)
        self.prev_dir = None
        self.prev_comp = None
        self.heavier_at = None        # when the trend turned wetter (the call waits for water on the track)
        self.last_x = None

    # -------------------------------------------------------------- feeding
    def tick(self, g, me, mine_class, wet_index, t=None):
        """g = telemetry getter. Called every strategist tick."""
        t = g("SessionTime") if t is None else t
        if t is None:
            return
        self.trend.add(t, g("TrackWetness"), g("Precipitation"))
        try:
            self.laps.feed(t, g("CarIdxLapCompleted") or [], g("CarIdxLastLapTime") or [], g("CarIdxTireCompound") or [],
                           g("CarIdxOnPitRoad") or [], g("TrackWetness"), me, mine_class, wet_index)
        except Exception as e:
            self.log(f"[rain] laps: {e!r}")

    # -------------------------------------------------------------- the picture now
    def estimate(self, ctx):
        """ctx: on_wets, base, lap_s, laps_left, stint_laps, stop_cost, stop_soon, mine, t, best -> crossover()."""
        st = self.trend.state()
        field = self.laps.field_now(ctx.get("t") or 0, ctx.get("lap_s"), ctx.get("best"))
        x = crossover(st, bool(ctx.get("on_wets")), base=ctx.get("base"), lap_s=ctx.get("lap_s"), field=field,
                      levels=self.laps.by_level(ctx.get("best")), mine_levels=self.laps.mine_by_level(),
                      mine=ctx.get("mine"), laps_left=ctx.get("laps_left"), stint_laps=ctx.get("stint_laps"),
                      stop_cost=ctx.get("stop_cost"), stop_soon=bool(ctx.get("stop_soon")))
        self.last_x = x
        return st, x

    def answer(self, kind, ctx):
        """kind: "more" | "trend" | "switch" -> {"sid", "fills", "text", "fallback"} or None (= the old path answers)."""
        st, x = self.estimate(ctx)
        if kind == "more":
            fc = ctx.get("forecast") or {}
            return answer_more(st, ctx.get("forecast_pct"), static=bool(fc.get("static")))
        if kind == "trend":
            return answer_trend(st)
        if kind == "switch":
            return answer_switch(x, st, bool(ctx.get("on_wets")))
        return None

    # -------------------------------------------------------------- proactive calls (once a lap)
    def lap(self, ctx, box_called=False):
        """After each of my laps: call the switch point if it's coming or here. box_called = the strategist's own
        "box this lap for slicks / wets" call went out this lap (then the crossover call isn't repeated).
        -> the call made (dict) or None."""
        st, x = self.estimate(ctx)
        now = self.clock()
        d = st.get("dir")
        made = None
        # the trend flipping to wetter while on slicks: "rain's getting heavier, think about wets" - once the water is
        # really on the track (a level off dry, or heavy rain), not at the first drops (that's "Rain starting.")
        if d == "wetter" and self.prev_dir in ("drying", "steady") and _rank(st.get("conf")) >= 2:
            self.heavier_at = now
        if d in ("drying", "steady") and _rank(st.get("conf")) >= 2:
            self.heavier_at = None
        if d in ("drying", "steady", "wetter") and _rank(st.get("conf")) >= 2:
            if {d, self.prev_dir} == {"drying", "wetter"}:
                self.called = {c for c in self.called if c.startswith(d)}     # the trend turned round: calls can come again
            self.prev_dir = d
        comp = bool(ctx.get("on_wets"))
        if comp != self.prev_comp:                                        # new tyres on: a new approach
            self.called, self.prev_comp = set(), comp
        if self.quiet():
            return None
        if now - self.last_call_t < CALL_GAP_S:
            return None
        wet_enough = (st.get("level") or 1) >= 2 or (st.get("precip") or 0) >= 0.3
        if self.heavier_at is not None and not comp and st.get("raining") and wet_enough \
                and now - self.last_heavier_t >= HEAVIER_GAP_S and x["call"] != "now":
            made = _say("rb_call_heavier", "Rain's getting heavier. Think about wets."
                        + (f" Track is {R.WET_NAME.get(st['level'], 'wet')}." if st.get("level") else ""), fallback="rain_worse")
            self.last_heavier_t, self.heavier_at = now, None
        elif x["conf"] in ("medium", "high") and not box_called:
            key = None
            if x["to"] == "slicks" and x["call"] == "now" and x["source"] != "table":
                key = "drying:slicks_now"
                made = _say("rb_call_slicks_now", f"Crossover. Slicks are faster now, about {abs(x['gain'] or 0):.1f} seconds a lap."
                            + (" Not enough to pay for a stop yet." if x["worth"] is False else ""))
            elif x["call"] in ("next", "laps") and (x["laps"] or 99) <= 3:
                n = x["laps"]
                key = f"{'drying' if x['to'] == 'slicks' else 'wetter'}:{x['to']}_soon"
                if x["call"] == "next":
                    made = _say(f"rb_{x['to']}_next", f"{x['to'].capitalize()} should be faster next lap. Get ready.")
                else:
                    made = _say(f"rb_call_{x['to']}_soon",
                                f"Track's {'drying' if x['to'] == 'slicks' else 'getting wetter'}. {x['to'].capitalize()} in about "
                                f"{n} laps, get ready.", {"laps": n})
            if key in self.called:
                made = None
            elif key:
                self.called.add(key)
        if made:
            self.last_call_t = now
            self.deliver(made, role="ENGINEER")
            self.log(f"[rain] call {made['sid']}: {x['why']} conf={x['conf']} src={x['source']} trend={d}/{st.get('conf')}")
        return made

    def deliver(self, a, role="ENGINEER", answer=False):
        """Play the new clip if it's rendered; else an existing clip that fits (plus the text); else text only.
        -> "clip" | "fallback" | "text"."""
        sid, fills = a["sid"], dict(a.get("fills") or {})
        if sid and self.say_clip(sid, fills, answer):
            if sid not in PENDING_IDS:            # an existing line (shorter wording): the full answer on screen too
                self.show(role, a["text"])
            return "clip"
        fb = a.get("fallback")
        if fb and fb != sid and self.say_clip(fb, dict(a.get("fb_fills") or {}), answer):
            self.show(role, a["text"])
            return "fallback"
        self.show(role, a["text"])
        return "text"
