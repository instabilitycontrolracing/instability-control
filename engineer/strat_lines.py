"""The strategist's words: every line he can say, with 2-3 ways of saying it.

Written like a real strategist on the radio: laps of fuel first, then the amount.
Each line has an id and [fills] (numbers, units), so the same list can be recorded as a voice
library later (see recording_script()). Until then the text is spoken by the placeholder voice.
"""
import random

LINES = {
    # [fills] are recorded as their own clips WITH their unit word: [mins] = "45 minutes", [laps]/[flaps] = "13 laps",
    # [lap] = "lap 8", [pos] = "P6", [fuel] = "36 litres", [pct] = "35 percent", [nstops] = "two stops"
    # opening
    # radio check: she only gives the brief if the driver keys up (tap or talk) to answer
    "rc": ["Radio check, it's your strategist.", "Radio check, strategist here.", "Strategist on the radio. Radio check."],
    "rc_ok": ["Loud and clear. Here's the plan.", "Got you, loud and clear. Quick rundown.", "Copy, I hear you. Here's the race."],
    "intro": ["[mins] today, that's about [laps].",
              "It's [mins] today, we're expecting about [laps].",
              "So, [mins] today, should be around [laps]."],
    "intro_nolaps": ["[mins] today.", "It's [mins] today."],
    "start_pos": ["You're starting [pos] in class.", "You start from [pos] in class."],
    # fuel at the start: laps first, then the amount
    "fuel_start": ["You've got [flaps] of fuel in the car. That's [fuel].",
                   "We've given you [flaps] of fuel to start. That's [fuel].",
                   "There's [flaps] of fuel on board. That's [fuel]."],
    # plan A
    "a_nostop": ["Plan A, we go to the end without stopping.", "Plan A is no stop. Straight to the end."],
    "a_one": ["Plan A is one stop. We box on [lap].", "Plan A, one stop, on [lap]."],
    "a_multi": ["Plan A is [nstops]. First one on [lap].", "Plan A, [nstops], the first on [lap]."],
    "stop_fuel": ["We'll give you [flaps] of fuel there. That's [fuel].",
                  "We'll fuel you for [flaps]. That's about [fuel].",
                  "At the stop it's [flaps] of fuel. That's [fuel]."],
    "tyres_yes": ["And we change the tyres.", "Four new tyres as well."],
    "tyres_no": ["No tyres, fuel only.", "Fuel only, we keep the tyres."],
    "save": ["We need you to save [pct] fuel each lap. Lift a little before the big stops.",
             "Save [pct] a lap. Lift and coast into the heavy braking zones.",
             "Small fuel save, [pct] a lap. Lift a touch before the big brake zones."],
    # plan B
    "b_same": ["If we need it, Plan B is to box on [lap] instead.", "Plan B, if we need it, is [lap]."],
    "b_nosave": ["No fuel saving on that one.", "That one needs no fuel saving."],
    "b_other": ["Plan B is [nstops], first on [lap].", "Backup is [nstops], the first on [lap]."],
    "b_nostop": ["Plan B is no stop, with more fuel saving.", "Backup is to go to the end, saving more fuel."],
    # weather
    "rain": ["About [pct] chance of rain today.", "Forecast says about [pct] chance of rain."],
    "rain_stop": ["If it comes before the stop, we put wets on then. No extra stop.",
                  "If it rains before the stop, we take wets there. It won't cost us an extra stop."],
    "rain_box": ["If it gets properly wet earlier, with more than [laps] left, I'll call you in for wets.",
                 "If it's really wet early on, and there's more than [laps] to go, I'll bring you in for wets."],
    "wet_now_3": ["Track is very lightly wet at the start. We stay on slicks, I'll call it every lap."],
    "wet_now_4": ["Track is lightly wet at the start. I'll make the tyre call every lap."],
    "wet_now_5": ["Track is wet at the start. I'll make the tyre call every lap."],
    "wet_now_6": ["Track is very wet at the start. Brake early, I'll make the tyre call every lap."],
    "wet_now_7": ["Track is soaking at the start. Huge care on lap one, I'll make the tyre call every lap."],
    # traffic and the close
    # other classes in the race, by name: [cls] = "GT3 class cars", "LMP2 class cars", "GTP class cars"
    # all classes brake at about the same point: passes happen on the straights, not under braking
    "multi_slower": ["The [cls] brake about where we do, so don't count on out-braking them. Make the pass on the straights.",
                     "We won't out-brake the [cls], they stop as well as we do. Get it done on the straights."],
    "multi_faster": ["The [cls] will come by. Hold your line and let them choose.",
                     "Hold your line when the [cls] come through. Don't move in the braking zones."],
    # tyre warm-up, from your own telemetry
    "warm": ["From your data, cold tyres take about [warm] to come in.",
             "Your tyres usually need about [warm] to come in."],
    "warm_loss": ["That first lap on cold tyres costs you about [secs].",
                  "Expect to lose about [secs] on that first lap while they come in."],
    # practice run plan ([run] = "Run one"..., [nruns] = "three runs", [runname] = "race sim"...)
    "rp_ok": ["Loud and clear. Here's the plan for today.", "Got you, loud and clear. Practice plan coming."],
    "rp_intro": ["Practice plan today, [nruns].", "We've got [nruns] planned today."],
    "rp_settle": ["[run], [laps] to settle in and check the car."],
    "rp_sim": ["[run], race sim, [laps] on race fuel."],
    "rp_save": ["[run], fuel saving, [laps] saving [pct] a lap."],
    "rp_long": ["[run], long run, [laps] on the same tyres so we learn the wear."],
    "rp_wet": ["[run], wet run while the track's wet. We've got no wet laps from you yet."],
    "rp_quali": ["[run], qualifying sim. Low fuel, [laps], full push."],
    "rp_now": ["You're on [run] now.", "This one's [run]."],
    "rp_fuel": ["For this run we'll fuel you for [laps]. That's [fuel] in the car."],
    "rp_done": ["That's the [runname] done. Box this lap.", "That's the [runname] finished, bring it in this lap."],
    "rp_pace": ["You averaged [secs] off your best.", "Average was [secs] off your best lap."],
    "rp_pace_close": ["Average pace was right on your best. Great run."],
    "rp_vs_sim_faster": ["That's [secs] a lap quicker than your last race sim."],
    "rp_vs_sim_slower": ["That's [secs] a lap slower than your last race sim."],
    "rp_fuel_used": ["Fuel was about [fuel] a lap."],
    "rp_next": ["Next up, [run], the [runname].", "[run] next, the [runname]."],
    "rp_all_done": ["That's the plan done. Good session.", "All runs done. Nice work today."],
    "rp_skip": ["Copy, skipping that one."],
    "rp_more": ["Copy, one more lap."],
    # post-race debrief (2026-10-24, Angelo: "the strategist was supposed to give us post race facts")
    "db_pos": ["That's [pos] in class.", "We finish [pos] in class."],
    "db_up": ["Up [places] from the start.", "That's [places] gained from the start."],
    "db_down": ["Down [places] from the start."],
    "db_same": ["Same place we started."],
    "db_best": ["Your best lap was [nth] fastest in class."],
    "db_stops0": ["No stops today."],
    "db_stops1": ["One stop today."],
    "db_stops": ["We made [nstops] today."],
    "db_fl": ["Fastest lap of the race went to [car]."],
    "db_fl_me": ["And the fastest lap of the race was yours."],
    "db_clean": ["A clean one, zero incidents."],
    "db_inc": ["[incs] today."],
    "db_ir_up": ["That's about plus [ir] iRating."],
    "db_ir_down": ["That's about minus [ir] iRating."],
    "db_fuel": ["We finished with [fuel] spare."],
    "db_end": ["Good work today. Cool it down.", "That's it from me. Bring it home."],
    # radio answers (approved by Angelo 2026-10-23)
    "sa_fuel_lap": ["Fuel is about [fuel] a lap.", "You're using about [fuel] a lap."],
    "sa_fuel_hist": ["From your earlier laps here, it's about [fuel] a lap."],
    "sa_fuel_ok": ["Fuel's fine. You've got [flaps] in the car, and we need [laps]."],
    "sa_fuel_short": ["We're short. You've got [flaps], we need [laps]. Save [pct] a lap."],
    "sa_box": ["We box on [lap].", "Next stop is on [lap]."],
    "sa_nostop": ["No more stops. Straight to the end."],
    "close": ["Cold tyres for the first lap. Keep it clean, it's a long race.",
              "Tyres are cold, so easy on lap one. Clean start, the race is long.",
              "Take care on cold tyres. Get through lap one clean, that's the job."],
}

# number clips (each recorded with its unit word, like the end of a sentence)
NUM_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
MINUTES = [15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 90, 100, 120, 150, 160, 180, 240]
PERCENT = list(range(1, 11)) + list(range(15, 101, 5))


def f_mins(n):  return f"{n} minutes"
def f_laps(n):  return "1 lap" if n == 1 else f"{n} laps"
def f_lap(n):   return f"lap {n}"
def f_pos(n):   return f"P{n}"
def f_litres(x):
    n = int(round(x))
    return "1 litre" if n == 1 else f"{n} litres"
def f_gallons(x): return f"{x / 3.785:.1f} gallons"
def f_pct(x, rain=False):
    n = int(round(x))
    if rain or n > 10:
        n = max(5, int(5 * round(n / 5)))        # rain chances are said to the nearest 5
    return f"{n} percent"
def f_stops(n): return f"{NUM_WORDS.get(n, n)} stops"
_WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
_ORD = ["", "the", "the second", "the third", "the fourth", "the fifth", "the sixth", "the seventh", "the eighth", "the ninth", "the tenth"]
def f_places(n): return "one place" if n == 1 else f"{_WORDS[n] if n < len(_WORDS) else n} places"
def f_nth(n):
    if n <= 10: return _ORD[n]
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"the {n}{suf}"
def f_car(n): return f"car {n}"
def f_incs(n): return "1 incident" if n == 1 else f"{n} incidents"
def f_ir(n): return str(max(5, int(5 * round(abs(n) / 5))))


# a few track lines for lap one (recordable per track)
TRACK_LAP1 = {
    "circuitdes24heuresdumans": ["Lap one, careful into the Dunlop Chicane. That's where it piles up, so brake early.",
                                 "Into the Dunlop Chicane on lap one, brake early. It always piles up there."],
    "michelinracewayroadatlanta": ["Turn one is uphill and blind. Brake early on lap one."],
    "circuitdespafrancorchamps": ["La Source on lap one is chaos. Stay out of trouble there."],
    "daytonainternationalspeedway": ["Turn one on lap one, expect the pile-up. Brake early."],
    "watkinsgleninternational": ["Turn one downhill on lap one, brake early, it gets busy."],
    "longbeachstreetcircuit": ["Turn one on lap one, walls everywhere. Brake early, get through it."],
    "fujiinternationalspeedway": ["Big stop into turn one. Watch the late divers on lap one."],
    "indianapolismotorspeedway": ["Turn one on lap one, brake early. It always gets messy."],
    "sebringinternationalraceway": ["Bumpy into turn one. Brake in a straight line on lap one."],
}


class Lines:
    """Pick one way of saying each line (different every race) and fill in the numbers."""

    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def say(self, lid, **fills):
        opts = LINES.get(lid) or TRACK_LAP1.get(lid) or [lid]
        k = self.rng.randrange(len(opts))
        t = opts[k]
        for f, v in fills.items():
            t = t.replace(f"[{f}]", str(v))
        _register(lid, k, opts[k], fills)
        return {"id": lid, "v": k, "fills": fills, "text": t}


# ------------------------------------------------------------------ voice library (rendered clips)
# Every template is split into sentences; each sentence is one library unit "<id>~<variant>~<n>".
# A unit is rendered once with example numbers and cut into pieces around its [fills];
# the fills are their own clips (rendered inside a short carrier sentence, then cut out).
import re as _re

KIND = {"mins": "mins", "laps": "laps", "flaps": "laps", "lap": "lap", "pos": "pos", "fuel": "litres",
        "pct": "percent", "nstops": "stops", "cls": "cls", "warm": "warm", "secs": "secs",
        "run": "run", "nruns": "nruns", "runname": "runname",
        "places": "places", "nth": "nth", "car": "car", "incs": "incs", "ir": "ir"}
EXAMPLE = {"mins": "45 minutes", "laps": "13 laps", "flaps": "8 laps", "lap": "lap 8", "pos": "P6",
           "fuel": "36 litres", "pct": "2 percent", "nstops": "two stops", "cls": "GT3 class cars",
           "warm": "half a lap", "secs": "5 seconds", "run": "Run two", "nruns": "three runs", "runname": "race sim",
           "places": "three places", "nth": "the fifth", "car": "car 29", "incs": "4 incidents", "ir": "35"}
CARRIER = {"mins": "It's {} today.", "laps": "That's about {}.", "lap": "We box on {}.", "pos": "You're starting {} in class.",
           "litres": "That's about {}.", "percent": "Save {} a lap.", "stops": "Plan A is {}.",
           "cls": "Watch the {} today.", "warm": "They take about {} to come in.", "secs": "It costs about {}.",
           "run": "{} is next.", "nruns": "We've got {} today.", "runname": "That's the {} done.",
           "places": "Up {} from the start.", "nth": "Your best lap was {} fastest in class.", "car": "It went to {}.",
           "incs": "That's {} today.", "ir": "That's about plus {} iRating."}
CLASSES = ["GTP class cars", "LMP2 class cars", "GT3 class cars",
           "GTP and LMP2 class cars", "LMP2 and GT3 class cars", "GTP and GT3 class cars"]


def fill_values():
    return {"mins": [f_mins(n) for n in MINUTES], "laps": [f_laps(n) for n in range(1, 61)],
            "lap": [f_lap(n) for n in range(1, 61)], "pos": [f_pos(n) for n in range(1, 41)],
            "litres": [f_litres(n) for n in range(1, 121)], "percent": [f"{n} percent" for n in PERCENT],
            "stops": [f_stops(n) for n in range(2, 7)], "cls": list(CLASSES),
            "warm": list(_WARM), "secs": list(_SECS), "run": ["Run one", "Run two", "Run three", "Run four"],
            "nruns": ["one run", "two runs", "three runs", "four runs"],
            "runname": ["settle-in run", "race sim", "fuel saving run", "long run", "wet run", "qualifying sim"],
            "places": [f_places(n) for n in range(1, 41)], "nth": [f_nth(n) for n in range(1, 41)],
            "car": [f_car(n) for n in range(0, 100)], "incs": [f_incs(n) for n in range(1, 41)],
            "ir": [str(n) for n in range(5, 205, 5)]}


_WARM = ["a few corners", "a third of a lap", "half a lap", "most of a lap", "one lap", "a lap and a half", "two laps", "three laps"]
_SECS = ["half a second", "1 second"] + [f"{n} seconds" for n in range(2, 9)]


def sentences(t):
    return [x for x in _re.split(r"(?<=[.!?])\s+", t.strip()) if x]


def units():
    """(key, template sentence) for everything the strategist can say."""
    out = []
    for d in (LINES, TRACK_LAP1):
        for lid, opts in d.items():
            for v, t in enumerate(opts):
                for n, sent in enumerate(sentences(t)):
                    out.append((f"{lid}~{v}~{n}", sent))
    return out


def norm_text(t):
    return _re.sub(r"\s+", " ", t).strip().lower()


SPOKEN = {}          # spoken sentence (normalised) -> (unit key, template sentence, fills in it)


def _register(lid, v, template, fills):
    for n, sent in enumerate(sentences(template)):
        txt = sent
        used = {}
        for f, val in fills.items():
            if f"[{f}]" in txt:
                used[f] = str(val)
                txt = txt.replace(f"[{f}]", str(val))
        SPOKEN[norm_text(txt)] = (f"{lid}~{v}~{n}", sent, used)
        if len(SPOKEN) > 500:
            SPOKEN.pop(next(iter(SPOKEN)))


def track_lap1(track_key):
    from .track_theme import norm
    t = norm(track_key or "")
    for k in TRACK_LAP1:
        if k in t or (len(t) > 4 and t in k) or (t.startswith("lemans") and k.startswith("circuitdes24")):
            return k
    return None


def recording_script():
    """Everything the strategist can say, for recording a voice library: (id, variant, text)."""
    out = []
    for d in (LINES, TRACK_LAP1):
        for lid, opts in d.items():
            for k, t in enumerate(opts):
                out.append((lid, k, t))
    return out
