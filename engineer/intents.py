"""Understands what the driver asked, in his own words (no exact phrases).

The speech-recognition step (Parakeet) hands its text to understand(). No AI model at race time: everything here is
plain rules that run in well under a millisecond.

2026-10-28 (#453, request: "I need it to be intuitive like we talked about"): understanding in four steps -
  1. clean up what the recogniser mishears (FIXES + ASR_NAMES, and a fuzzy spell-fix for words close to ours),
  2. find who he is talking to (strategist / engineer) and take the name out - the name is not the question,
  3. pick out the things he asks about (fuel, tyres, rain, the gap, a stop, laps left ...) as CONCEPTS,
  4. score EVERY intent (concept RULES + the older keyword groups) and take the best - not the first keyword found.
analyse() returns the whole picture (who it was for, was it a question, the runner-up); understand() keeps its
old (intent, score) answer for the callers.
"""
import re

INTENTS = [
    ("gap_ahead",   [["gap", "ahead"], ["car", "ahead"], ["in front"], ["front", "gap"], ["how far", "ahead"], ["catching"]]),
    ("gap_behind",  [["gap", "behind"], ["car", "behind"], ["behind"], ["who", "behind"], ["how close"]]),
    ("position",    [["position"], ["where", "running"], ["what", "place"], ["p what"], ["what p"]]),
    ("fuel",        [["fuel"], ["gas"], ["make it", "end"], ["enough", "finish"], ["petrol"]]),
    ("laps_left",   [["laps", "left"], ["laps", "to go"], ["how many", "laps"], ["time", "left"], ["how long", "left"], ["minutes"]]),
    ("last_lap",    [["last", "lap", "time"], ["what", "lap", "time"], ["lap time"], ["last lap"]]),
    ("best_lap",    [["best", "lap"], ["fastest", "lap"], ["personal best"]]),
    ("incidents",   [["incident"], ["how many", "x"], ["penalty", "points"], ["safety rating"]]),
    ("track_temp",  [["track", "temp"], ["temperature"], ["how hot"]]),
    ("spotter_off", [["spotter", "off"], ["stop", "spotting"], ["no spotter"]]),
    ("spotter_on",  [["spotter", "on"], ["start", "spotting"]]),
    ("quiet",       [["quiet"], ["shut up"], ["stop", "talking"], ["less", "talk"], ["radio", "off"]]),
    ("talk",        [["talk", "again"], ["back on"], ["keep", "me", "updated"], ["radio", "on"]]),
    ("radio_check", [["radio", "check"], ["can you hear"], ["do you copy"], ["hear me"]]),
    ("rain",        [["rain"], ["wet"], ["drive", "rain"], ["wets"], ["slicks"]]),
    ("strategy",    [["strategy"], ["race", "plan"], ["what", "plan"], ["plan", "a"], ["plan", "b"], ["which", "plan"]]),
    ("next_stop",   [["when", "box"], ["when", "pit"], ["when", "pit", "stop"], ["when", "we", "stop"], ["how", "many", "stops"],
                     ["pit", "window"], ["next", "stop"], ["stops", "left"], ["do", "we", "stop"]]),
    ("pit_plan",    [["pit", "plan"], ["box", "plan"], ["pit", "stop"], ["box", "this", "lap"], ["boxing"], ["pitting"], ["box", "box"], ["coming", "in"]]),
    # v62 (DRE parity)
    ("say_again",   [["say", "again"], ["repeat"], ["didn t", "catch"], ["come again"], ["what", "did", "you", "say"], ["pardon"]]),
    ("time_now",    [["what", "time", "is", "it"], ["time", "of", "day"], ["clock", "time"], ["what s", "the", "time"]]),
    ("who_ahead",   [["who", "car", "ahead"], ["who", "s", "ahead"], ["who", "is", "ahead"], ["who", "in", "front"], ["who", "ahead"]]),
    ("who_behind",  [["who", "car", "behind"], ["who", "s", "behind"], ["who", "is", "behind"]]),
    ("sof",         [["strength", "field"], ["sof"], ["s o f"], ["how", "strong", "field"], ["average", "irating"]]),
    ("irating",     [["irating"], ["i", "rating"], ["rating", "gain"], ["how", "much", "rating"], ["points", "gain"]]),
    ("irating_target", [["position", "gain", "rating"], ["what", "position", "irating"], ["where", "need", "finish"], ["need", "to", "finish", "rating"]]),
    ("damage",      [["damage"], ["repair"], ["is", "the", "car", "ok"], ["car", "okay"], ["anything", "broken"]]),
    ("engine",      [["engine"], ["oil", "temp"], ["water", "temp"], ["oil", "pressure"], ["temps"], ["overheating"]]),
    ("pit_out",     [["where", "come", "out"], ["come", "out", "if"], ["if", "we", "box"], ["if", "i", "pit"], ["rejoin", "where"], ["where", "rejoin"]]),
    ("fuel_target", [["fuel", "target"], ["fuel", "save", "how", "much"], ["target", "per", "lap"], ["how", "much", "save"]]),
    ("fuel_per_lap",[["fuel", "per", "lap"], ["feel", "per", "lap"], ["per", "lapse"], ["fuel", "per", "lapse"], ["per", "lap"], ["using", "per", "lap"], ["consumption"], ["burn", "per", "lap"]]),
    ("weather",     [["weather"], ["air", "temp"], ["wind"], ["humidity"], ["conditions"]]),
    ("tyres",       [["tyre", "wear"], ["tire", "wear"], ["tyres", "left"], ["tires", "left"], ["how", "are", "tyres"], ["how", "are", "tires"], ["laps", "on", "tyres"], ["laps", "on", "tires"], ["tyre", "life"], ["tire", "life"]]),
    ("best_sector", [["best", "sector"], ["strongest", "sector"], ["where", "am", "i", "fast"]]),
    ("pit_loss",    [["pit", "loss"], ["box", "cost"], ["stop", "cost"], ["how", "long", "pit", "stop"], ["how", "long", "is", "a", "stop"], ["how", "long", "stop"], ["time", "lose", "pit"]]),
    ("fastest",     [["who", "fastest"], ["fastest", "car"], ["quickest"], ["who", "s", "quick"]]),
    ("leader_gap",  [["gap", "leader"], ["gap", "to", "p1"], ["how", "far", "leader"], ["leader", "gap"], ["class", "leader"]]),
    # meeting room (future): recognised now so it can be wired up later
    ("meeting",     [["strategy", "meeting"], ["debrief"], ["talk", "team"], ["meeting"], ["night", "review"], ["review", "tonight"]]),
]


# what the speech recogniser mishears on a race radio (found by audit_asr: real recogniser, synthetic voices)
FIXES = [(r"\bcar(\d{1,3})\b", r"car \1"), (r"\b(best|past|vast) repair", "fast repair"), (r"\boxford\b", "box for"),
         (r"\b(wits|whits|wetz|whets)\b", "wets"), (r"\blabs\b", "laps"), (r"\blab\b", "lap"),
         (r"\bfuel for lap\b", "fuel per lap"), (r"\bhalf a side\b", "half a psi"), (r"\bpressure is\b", "pressures"),
         (r"\bi rating\b", "irating"), (r"\bp (\d{1,2})\b", r"p\1"),
         # found by the 2026-10-24 recogniser test (Parakeet, ~2,000 synthetic radio phrases, clean + engine noise)
         (r"[.!,;:]+(\s|$)", r"\1"), (r"\bcart\b", "car"), (r"\bcarahead\b", "car ahead"), (r"\bcar aheads\b", "car ahead"),
         (r"\b(ear|air) (temp|temperature)", r"air \2"), (r"\breign\b", "rain"), (r"\b(eye|high|hi|i) ?(rating|reading)\b", "irating"),
         (r"\birrigating\b", "irating"), (r"\blapse\b", "laps"), (r"\bdealt a\b", "delta"), (r"\bdelta a\b", "delta"),
         (r"^\s*vox\b", "box"), (r"\bvox (this|box)\b", r"box \1"), (r"\bhit (speed|stop|lane|limiter|road)\b", r"pit \1"),
         (r"\bbreak (bias|percent|pressure|balance|migration|shape|pedal)\b", r"brake \1"), (r"\bbreaks\b", "brakes"),
         (r"\bincidence\b", "incidents"), (r"\bqualap\b", "qual lap"), (r"\boutlapped\b", "out lap"), (r"\bpit div\b", "pit diff"),
         (r"\b(dint|stent)\b", "stint"), (r"\bdidn'?t laps\b", "stint laps"), (r"\bi'?m kidding\b", "i'm pitting"),
         (r"\btamp\b", "temp"), (r"\bentire life\b", "tire life"), (r"\bwin (strength|speed|direction)\b", r"wind \1"),
         (r"\bclouding\b", "cloudy"), (r"\bsensori\b", "send sorry"), (r"\bto your off\b", "tear off"), (r"\btear of\b", "tear off"),
         (r"\bdumar?k?\b", "mark"), (r"\bon mark\b", "unmark"), (r"\btarget guess\b", "target gas"),
         (r"\b(tires?|tyres?) lapse\b", r"\1 laps"), (r"\bstinks\b", "stint"),
         (r"\b(cara|kara|car a) ?(had|head)\b", "car ahead"), (r"\bcar ahead ?(stant|stand|stent)\b", "car ahead stint"),
         (r"\b(stand|stant) laps\b", "stint laps"), (r"\btier off\b", "tear off"), (r"\bsing again\b", "say again"),
         (r"\bsansari\b", "send sorry"), (r"\bdraining\b", "graining"), (r"\bp-? ?plan\b", "pit plan"), (r"\bairtemp\b", "air temp"),
         (r"\bperlap\b", "per lap"), (r"\bdelive\b", "delete"), (r"\bqual-class\b", "qual class"), (r"\bclasses the\b", "class is the")]


def normalize(text):
    t = (text or "").lower()
    for a, b in FIXES:
        t = re.sub(a, b, t)
    return t


# ------------------------------------------------------------------ 2026-10-28 (#453): natural questions
# Who he is talking to, as the recogniser writes it ("strategies", "strategy guy", "straight just" ...).
ASR_NAMES = [
    (r"\bstraight ?(just|gist|jist|chest|guest|is)\b", "strategist"), (r"\bstrat ?a ?(gist|jist|just)\b", "strategist"),
    (r"\bstrategy ?(guy|girl|lady|person|desk|side|just|gist)\b", "strategist"),
    (r"\bstrateg(ist s|ists|est|ests|ic|ically)\b", "strategist"), (r"\bstrategist s\b", "strategist"),
    (r"\b(gertrude|gertie|gert)\b", "strategist"), (r"\bstrat\b", "strategist"), (r"\bstratus\b", "strategist"),
    (r"\b(engineers|engineering|engine ear|engine year|engine here)\b", "engineer"),    (r"\brace engineer\b", "engineer"),
]
# for the concepts only (the older keyword groups below were written for the raw form)
CONTRACT = [
    (r"\bfeel (per|a|each|every) lap", r"fuel \1 lap"), (r"\btyres?\b", "tyres"), (r"\btires?\b", "tyres"),
    (r"\bwhat ?s\b", "what is"), (r"\bwho ?s\b", "who is"), (r"\bwhere ?s\b", "where is"), (r"\bhow ?s\b", "how is"),
    (r"\bwhen ?s\b", "when is"), (r"\bwe re\b", "we are"), (r"\bi m\b", "i am"), (r"\bi ll\b", "i will"),
    (r"\bdon t\b", "do not"), (r"\bgonna\b", "going to"), (r"\bgotta\b", "got to"), (r"\bwanna\b", "want to"),
    (r"\bp (one|1)\b", "p1"), (r"\bpee\b", "p"), (r"\bpits\b", "pit"), (r"\bpit stop\b", "pitstop"),
    (r"\bboxing\b", "box"), (r"\bpitting\b", "pit"), (r"\bbucks bucks\b", "box box"),
]
STRAT_WORDS = ("strategist",)
ENG_WORDS = ("engineer",)

# Things he asks about. Each concept: the words / phrases that mean it (spaces = whole words).
CONCEPTS = {
    "FUEL": ["fuel", "fuels", "gas", "petrol", "juice", "litres", "liters", "gallons"],
    "PERLAP": ["per lap", "a lap", "each lap", "every lap", "per laps", "lap average", "average per lap"],
    "BURN": ["using", "use", "used", "burn", "burning", "burnt", "consumption", "consuming", "drinking", "uses"],
    "ENOUGH": ["enough", "make it", "last", "finish", "the end", "to the end", "the flag", "go the distance", "short",
               "run out", "running out"],
    "SAVE": ["save", "saving", "lift and coast", "conserve", "target"],
    "TYRE": ["tyres", "rubber", "fronts", "rears", "front left", "front right", "rear left", "rear right", "compound"],
    "WEAR": ["wear", "worn", "life", "holding up", "going off", "degradation", "deg", "grip", "falling off", "shape",
             "condition", "how are", "how is", "left", "graining", "temps", "pressures"],
    "RAIN": ["rain", "raining", "rains", "rainy", "wet", "wets", "inters", "intermediates", "drizzle", "shower", "showers",
             "spitting", "slicks", "storm", "dry"],
    "WEATHER": ["weather", "forecast", "conditions", "wind", "windy", "humidity", "air temp", "air temperature", "cloud",
                "clouds", "cloudy", "sunny", "sky"],
    "PIT": ["box", "pit", "pitstop", "stop", "stops", "stopping", "i come in", "we come in", "i will come in",
            "coming in", "bring it in", "bring her in", "in lap", "service"],
    "WHEN": ["when", "what lap", "which lap", "how long until", "how long till", "how long before", "how many laps until",
             "how many laps till", "how many laps before", "how soon"],
    "HOWMANY": ["how many"],
    "WINDOW": ["window"],
    "NEED": ["need", "have to", "got to", "should", "must", "do we", "are we", "will we", "is there", "do i", "am i"],
    "NEXT": ["next"],
    "GAP": ["gap", "interval", "how far", "distance", "how much time", "margin", "how close", "split", "splits", "seconds"],
    "AHEAD": ["ahead", "in front", "front", "up the road", "next car", "the car ahead", "lead car"],
    "BEHIND": ["behind", "how far back", "far back", "back to the", "back of me", "following", "chasing", "on my tail", "mirror", "mirrors", "back there"],
    "CATCH_ME": ["catching me", "closing on me", "gaining on me", "coming at me", "reeling me in", "closing in on me",
                 "catching us", "gaining on us", "closing on us", "on me"],
    "CATCH_HIM": ["am i catching", "are we catching", "catching him", "catching them", "catching her", "closing on him",
                  "gaining on him", "reeling him in", "catching the car", "catching up", "closing the gap", "closing in",
                  "gaining"],
    "WHO": ["who", "whose", "which car", "what car", "which driver", "what driver", "name of", "what number"],
    "POSITION": ["position", "place", "what p", "p what", "standings", "where am i", "where are we", "where do we stand",
                 "where we at", "where are we running", "where am i running", "running", "classified", "what spot",
                 "what are we running"],
    "LAPS": ["laps", "lap"],
    "LEFT": ["left", "remaining", "remain", "to go", "more", "until the end", "till the end", "longer", "how much longer"],
    "TIMEW": ["time", "minutes", "how long", "clock"],
    "LAST": ["last", "previous", "that lap", "just do", "just now", "lap time", "my time", "that one"],
    "BEST": ["best", "fastest", "quickest", "personal best", "pb", "best time"],
    "LEADER": ["leader", "leading", "p1", "first place", "the lead", "front runner"],
    "DAMAGE": ["damage", "damaged", "broken", "broke", "break anything", "repair", "repairs", "hurt", "bent", "wing",
               "suspension", "car ok", "car okay", "car alright", "car fine", "anything wrong", "car good",
               "something wrong", "car is ok", "car is okay", "car is alright", "car is fine", "car is good"],
    "ENGINE": ["engine", "oil", "water temp", "water temperature", "overheating", "coolant", "motor", "radiator"],
    "TRACK": ["track", "surface", "asphalt", "tarmac"],
    "TEMP": ["temp", "temps", "temperature", "temperatures", "hot", "warm", "cold"],
    "STRAT": ["strategy", "strategies", "plan", "the call", "what is the call", "game plan", "plan a", "plan b", "plan c",
              "what are we doing", "what do we do", "what should we do", "what should i do", "what do you think",
              "what now", "options", "what is the move", "your thoughts", "thoughts"],
    "LOOKING": ["how are we looking", "how is it looking", "how we looking", "how are we doing", "how is it going",
                "how we doing", "how am i doing", "how am i looking", "update", "status", "how is the race"],
    "WHERE_OUT": ["come out", "rejoin", "end up", "where would i be", "where would we be", "drop to"],
    "COST": ["cost", "costs", "lose", "loss", "lost", "how long is", "how long does", "how long will", "how long is a",
             "take in"],
    "RADIO": ["radio check", "can you hear", "do you copy", "you there", "are you there", "hear me", "you copy",
              "anyone there", "anybody there", "you on", "come in", "you read me", "do you read", "are you on"],
    "INCIDENT": ["incident", "incidents", "x", "penalty points", "safety rating", "how many x"],
    "AGAIN": ["say again", "repeat", "repeat that", "come again", "what was that", "did not catch", "didn t catch",
              "didn t get that", "missed that", "pardon", "one more time"],
    # rain brain (#591, 2026-10-30): will it rain any more, is it drying, when do we go to slicks / wets
    "RAINW": ["rain", "raining", "rains", "rainy", "drizzle", "shower", "showers", "spitting", "storm", "precipitation",
              "downpour", "pouring"],
    "DRYCOMP": ["slicks", "slick", "dries", "drys", "dry tyres", "dry ones", "dry rubber", "dry set", "slick tyres"],
    "WETCOMP": ["wets", "wet tyres", "wet ones", "rain tyres", "wet set", "inters", "intermediates"],
    "SWITCH": ["switch", "switching", "change", "changing", "swap", "swapping", "go to", "go onto", "go on to", "move to",
               "put on", "time for", "back to", "go back to", "bolt on", "change over", "changeover", "crossover",
               "cross over", "go for", "going to", "pit for", "box for", "ready for"],
    "CHANGE_T": ["switch", "switching", "change", "changing", "swap", "swapping", "change over", "changeover",
                 "crossover", "cross over", "time for"],
    "DRYING": ["drying", "dry out", "drying out", "dries out", "drying up", "dry up", "dry line", "dried", "drier",
               "dryer", "getting dry", "getting drier", "dry yet", "dry enough"],
    "CROSS": ["crossover", "cross over", "changeover", "change over", "switch point", "switch over"],
    "WETTER": ["wetter", "getting wet", "more wet", "wet again"],
    "HEAVIER": ["heavier", "harder", "worse", "picking up", "intensifying", "getting heavy", "coming down", "building",
                "lighter", "easing", "ease off", "ease up", "eases", "letting up", "let up", "dying down", "tailing off"],
    "MORE": ["any more", "anymore", "more rain", "rain again", "again", "keep raining", "keep on raining",
             "stop raining", "going to stop", "gonna stop", "rain stop", "stopping", "finish raining", "done raining",
             "still raining", "rain more", "carry on", "over soon", "last long", "more coming", "rain later"],
}
# the rain brain's words are not added to the recogniser spell-fix list ("better" must never become "wetter")
NO_SPELLFIX = {"RAINW", "DRYCOMP", "WETCOMP", "SWITCH", "CHANGE_T", "CROSS", "DRYING", "WETTER", "HEAVIER", "MORE"}
CALLING = {"hey", "ok", "okay", "yo", "the", "my", "can", "could", "i", "talk", "to", "get", "me", "put", "on",
           "need", "want", "where", "is", "please", "go", "ahead", "copy", "quick", "question", "a", "you", "with",
           "speak", "come", "in", "are", "there", "radio", "check", "hello", "hi", "mate", "buddy", "um", "uh", "so",
           "now", "for", "second", "sec", "minute", "of", "your", "help", "listen", "do", "be", "here"}

# (intent, score, all of these concepts, none of these, only as a question / only as a statement / addressee)
RULES = [
    ("fuel_per_lap", 21, ("FUEL", "PERLAP"), ()), ("fuel_per_lap", 19, ("BURN", "PERLAP"), ("TYRE",)),
    ("fuel_per_lap", 18, ("FUEL", "BURN"), ("TYRE",)),
    ("fuel_target", 23, ("FUEL", "SAVE"), ()), ("fuel_target", 17, ("SAVE", "PERLAP"), ("TYRE",)),
    ("fuel_target", 14, ("SAVE",), ("TYRE", "RAIN")),
    ("fuel", 14, ("FUEL",), ()), ("fuel", 19, ("FUEL", "ENOUGH"), ()), ("fuel", 18, ("FUEL", "LAPS"), ()),
    ("fuel", 18, ("FUEL", "LEFT"), ()),
    ("fuel", 12, ("ENOUGH",), ("TYRE", "PIT", "LAST", "BEST", "RAIN", "DAMAGE", "TIMEW", "LAPS")),
    ("tyres", 13, ("TYRE",), ("RAIN",)), ("tyres", 20, ("TYRE", "WEAR"), ("RAIN",)),
    ("tyres", 20, ("TYRE", "LAPS"), ("RAIN",)), ("tyres", 20, ("TYRE", "ENOUGH"), ("RAIN",)),
    ("rain", 16, ("RAIN",), ()), ("rain", 22, ("RAIN", "TYRE"), ()), ("rain", 20, ("RAIN", "WEATHER"), ()),
    ("rain", 21, ("RAIN", "PIT"), (), "question"),
    ("weather", 14, ("WEATHER",), ("RAIN", "TRACK")),
    ("next_stop", 20, ("PIT", "WHEN"), ("WHERE_OUT", "COST")), ("next_stop", 19, ("PIT", "HOWMANY"), ("WHERE_OUT", "COST")),
    ("next_stop", 20, ("PIT", "WINDOW"), ()), ("next_stop", 16, ("WINDOW",), ()),
    ("next_stop", 18, ("PIT", "NEED"), ("WHERE_OUT", "COST", "DAMAGE")), ("next_stop", 18, ("PIT", "NEXT"), ("WHERE_OUT", "COST")),
    ("next_stop", 17, ("PIT", "LEFT"), ("WHERE_OUT", "COST")),
    ("pit_plan", 12, ("PIT",), ("WHEN", "HOWMANY", "WINDOW", "NEED", "WHERE_OUT", "COST", "NEXT", "LEFT"), "statement"),
    ("pit_out", 23, ("PIT", "WHERE_OUT"), ()), ("pit_out", 18, ("WHERE_OUT",), ()),
    ("pit_loss", 22, ("PIT", "COST"), ()),
    ("gap_ahead", 20, ("GAP", "AHEAD"), ("WHO", "BEHIND")), ("gap_ahead", 16, ("CATCH_HIM",), ("CATCH_ME",)),
    ("gap_ahead", 11, ("GAP",), ("BEHIND", "LEADER", "CATCH_ME")), ("gap_ahead", 13, ("AHEAD",), ("WHO", "BEHIND", "PIT")),
    ("gap_behind", 20, ("GAP", "BEHIND"), ("WHO",)), ("gap_behind", 18, ("CATCH_ME",), ()),
    ("gap_behind", 13, ("BEHIND",), ("WHO", "AHEAD")),
    ("who_ahead", 23, ("WHO", "AHEAD"), ("BEST",)), ("who_behind", 23, ("WHO", "BEHIND"), ("BEST",)),
    ("leader_gap", 23, ("GAP", "LEADER"), ()), ("leader_gap", 16, ("LEADER",), ("BEST",)),
    ("position", 15, ("POSITION",), ("GAP", "WHERE_OUT", "PIT", "LEADER")),
    ("position", 12, ("LOOKING",), (), None, "engineer"),
    ("strategy", 14, ("STRAT",), ("RAIN",)), ("strategy", 13, ("LOOKING",), (), None, "strategist"),
    ("laps_left", 18, ("LAPS", "LEFT"), ("TYRE", "FUEL", "PIT")), ("laps_left", 17, ("TIMEW", "LEFT"), ("TYRE", "FUEL", "PIT")),
    ("last_lap", 17, ("LAST", "LAPS"), ("LEFT", "FUEL", "TYRE", "BEST")), ("last_lap", 14, ("LAST",), ("LEFT", "FUEL", "TYRE", "BEST", "ENOUGH", "AGAIN")),
    ("best_lap", 18, ("BEST", "LAPS"), ("WHO",)), ("best_lap", 15, ("BEST",), ("WHO", "SAVE")),
    ("fastest", 21, ("WHO", "BEST"), ()),
    ("damage", 17, ("DAMAGE",), ()),
    ("engine", 17, ("ENGINE",), ()),
    ("track_temp", 22, ("TRACK", "TEMP"), ()),
    ("radio_check", 20, ("RADIO",), ()),
    ("incidents", 17, ("INCIDENT",), ()),
    ("say_again", 17, ("AGAIN",), ("LAPS",)),
    # rain brain (#591): only as questions ("wets please" stays a pit request, "rain's getting heavier" a remark)
    ("tyre_switch", 25, ("SWITCH", "DRYCOMP"), ("WETCOMP",), "question"),
    ("tyre_switch", 24, ("WHEN", "DRYCOMP"), (), "question"),
    ("tyre_switch", 23, ("DRYCOMP", "DRYING"), (), "question"),
    ("tyre_switch", 24, ("CHANGE_T", "WETCOMP"), ("DRYCOMP",), "question"),
    ("tyre_switch", 23, ("CHANGE_T", "TYRE"), ("WEAR", "DRYCOMP", "WETCOMP"), "question"),
    ("tyre_switch", 23, ("CHANGE_T", "DRYCOMP", "WETCOMP"), (), "question"),
    ("tyre_switch", 22, ("CROSS",), ("FUEL", "GAP"), "question"),
    ("rain_trend", 24, ("DRYING",), ("DRYCOMP", "WETCOMP"), "question"),
    ("rain_trend", 24, ("WETTER",), ("DRYCOMP", "WETCOMP"), "question"),
    ("rain_trend", 24, ("RAINW", "HEAVIER"), ("DRYCOMP", "WETCOMP", "MORE"), "question"),
    ("rain_trend", 20, ("TRACK", "HEAVIER"), ("DRYCOMP", "WETCOMP", "TYRE", "TEMP"), "question"),
    ("rain_more", 24, ("RAINW", "MORE"), ("DRYCOMP", "WETCOMP", "TYRE", "AGAIN"), "question"),
    ("rain_more", 24, ("RAINW", "MORE", "AGAIN"), ("DRYCOMP", "WETCOMP", "TYRE"), "question"),
]
# the strategist's own subjects: when he talks to her and two meanings score the same, hers wins
STRAT_INTENTS = {"fuel", "fuel_per_lap", "fuel_target", "next_stop", "strategy", "rain", "weather", "pit_out", "pit_loss",
                 "tyres", "rain_more", "rain_trend", "tyre_switch"}
RAIN_INTENTS = {"rain_more": "more", "rain_trend": "trend", "tyre_switch": "switch"}     # -> RainBrain.answer() kinds
QUESTION_START = {"what", "whats", "how", "when", "where", "who", "which", "why", "do", "does", "did", "are", "is", "am",
                  "can", "could", "should", "will", "would", "have", "has", "any", "tell", "give", "gimme", "we", "update"}


def _compile():
    pats = {}
    for c, words in CONCEPTS.items():
        words = sorted(set(words), key=len, reverse=True)
        pats[c] = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])")
    vocab = set()
    for c, words in CONCEPTS.items():
        if c in NO_SPELLFIX:
            continue
        for w in words:
            vocab.update(x for x in w.split() if len(x) >= 4)
    for _, groups in INTENTS:
        for g in groups:
            vocab.update(x for x in g if len(x) >= 4 and " " not in x)
    vocab.update(("strategist", "engineer", "position", "temperature"))
    return pats, sorted(vocab)


_PATS, _VOCAB = _compile()
_VOCAB_SET = set(_VOCAB)
# ...but they are never "fixed" into something else either ("dries" is not "drive", "changing" is not "chasing")
_KEEP = {x for c in NO_SPELLFIX for w in CONCEPTS[c] for x in w.split()}
COMMON = set("""there their they these those think about would could should right thing things going doing looking
again where which other first please thanks thank sorry really maybe still just mate buddy okay alright guys
gonna wanna gotta getting being having little bit quite sure think know need want like tell give doing does
said says saying hello radio check copy roger understood affirmative negative whats whos heres theres
turning turned braking brake brakes corner corners apex entry exits throttle steering gearbox balance handling
missing listen running learning burning warning morning evening coming going racing passing pushing lifting
shifting moving staying waiting watching driving trying slower faster gears tired nothing second minute
seconds sector sectors class classes driver drivers flags started stated slowly lower power tower showed""".split())


def _fix_word(w):
    """A word the recogniser got nearly right ('tyers', 'positon', 'strategest') -> our word. Cached, ~50 us."""
    if len(w) < 5 or w in _VOCAB_SET or w in COMMON or w in _KEEP or w.isdigit():
        return w
    r = _FIX_CACHE.get(w)
    if r is None:
        import difflib
        m = difflib.get_close_matches(w, _VOCAB, n=1, cutoff=0.8)
        r = m[0] if m else w
        if len(_FIX_CACHE) < 5000:
            _FIX_CACHE[w] = r
    return r


_FIX_CACHE = {}


def _clean(text):
    raw = (text or "").lower()
    question = "?" in raw
    t = re.sub(r"[^a-z0-9 ]+", " ", normalize(text))
    t = " ".join(_fix_word(w) for w in t.split())
    for a, b in ASR_NAMES:
        t = re.sub(a, b, t)
    t1 = " ".join(t.split())
    for a, b in CONTRACT:
        t = re.sub(a, b, t)
    return t1, " ".join(t.split()), question


def _concepts(t):
    return {c for c, p in _PATS.items() if p.search(t)}


def _pattern_scores(t):
    """The older keyword groups, scored for every intent (kept so nothing that worked before stops working)."""
    tt = " " + t + " "
    out = {}
    for name, groups in INTENTS:
        for words in groups:
            if all(f" {w} " in tt or (len(w) > 4 and w in tt) for w in words):
                s = sum(len(w) for w in words)
                if s > out.get(name, 0):
                    out[name] = s
    return out


# a remark about the car ("the tyres are going off", "fronts are graining") is a note for later, not a question
NOTE_CUES = re.compile(r"\b(feels?|feeling|getting|going off|falling off|is a bit|are a bit|loose|tight|understeer\w*|"
                       r"oversteer\w*|graining|fading|locking|lock up|bottoming|snappy|sliding|vibrat\w*|i think|"
                       r"no grip|lost|losing|chewed|gone|shot|dead)\b")


def _score(t1, t, question, who):
    cs = _concepts(t)
    sc = _pattern_scores(t1)
    if not question and who is None and NOTE_CUES.search(t):
        return sc, cs
    for rule in RULES:
        name, s, need, forbid = rule[:4]
        mode = rule[4] if len(rule) > 4 else None
        to = rule[5] if len(rule) > 5 else None
        if to == "engineer" and who == "strategist":
            continue
        if to == "strategist" and who != "strategist":
            continue
        if (mode == "statement" and question) or (mode == "question" and not question):
            continue
        if all(c in cs for c in need) and not any(c in cs for c in forbid):
            if s > sc.get(name, 0):
                sc[name] = s
    if who == "strategist":
        for k in list(sc):
            if k in STRAT_INTENTS:
                sc[k] += 1
    return sc, cs


def _is_question(words, question_mark):
    return question_mark or (bool(words) and words[0] in QUESTION_START) or " or not" in " ".join(words)


def addressee(text):
    """'strategist' / 'engineer' / None: who he was talking to."""
    return analyse(text)["to"]


def analyse(text):
    """Everything understand() works out: {"intent", "score", "to", "question", "alt", "unclear", "text"}.

    to       - "strategist" / "engineer" / None (who he called by name)
    question - it was asked (question mark from the recogniser, or starts like a question)
    alt      - the runner-up (intent, score), for the log
    unclear  - nothing understood but it was a question or meant for someone: ask him again, never just "copy"
    """
    t1, t, qmark = _clean(text)
    words, words1 = t.split(), t1.split()
    names = STRAT_WORDS + ENG_WORDS
    who = None
    if any(w in STRAT_WORDS for w in words):
        who = "strategist"
    elif any(w in ENG_WORDS for w in words):
        who = "engineer"
    rest = [w for w in words if w not in names]
    rest1 = [w for w in words1 if w not in names]
    # "Strategy, how is the fuel?" - the recogniser often writes her name as the plain word
    if who is None and words and words[0] in ("strategy", "strategies") and len(words) >= 3:
        sc2, _ = _score(" ".join(words1[1:]), " ".join(words[1:]), qmark or words[1] in QUESTION_START, "strategist")
        if sc2 and max(sc2.values()) >= 12 and max(sc2, key=sc2.get) != "strategy":
            who, rest, rest1 = "strategist", words[1:], words1[1:]
    rt = " ".join(rest)
    question = _is_question(rest, qmark)
    sc, cs = _score(" ".join(rest1), rt, question, who)
    # her name on its own (or "can I talk to the strategist") = she gives the plan (#452); the engineer's = radio check
    calling = who is not None and all(w in CALLING for w in rest)
    if calling and not (sc and max(sc.values()) >= 12):
        if who == "strategist":
            sc = {"strategy": 8}
        else:
            sc = {"radio_check": 8}
    ranked = sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))
    best, best_s = ranked[0] if ranked else (None, 0)
    alt = ranked[1] if len(ranked) > 1 else (None, 0)
    if best is None and words and words[0] in ("strategy", "strategies") and not rest[1:]:
        best, best_s = "strategy", 8
    return {"intent": best, "score": best_s, "to": who, "question": question, "alt": alt,
            "unclear": best is None and (question or who is not None), "text": rt, "concepts": sorted(cs)}


def understand(text):
    """Returns (intent, score) or (None, 0)."""
    a = analyse(text)
    return a["intent"], a["score"]


if __name__ == "__main__":
    for q in ["how's the gap to the car in front", "what position are we", "do we have enough fuel to finish",
              "how many laps left", "who's behind me", "what was my last lap time", "spotter off please",
              "can you hear me", "let's have a strategy meeting", "what's the track temperature",
              "say again", "who's the car ahead", "what's the strength of field", "how much irating do we gain",
              "any damage", "how are the tyres", "where do we come out if we box", "what's the weather",
              "what's the fuel target", "fuel per lap", "what time is it", "who's fastest", "gap to the leader"]:
        print(f"{q!r:45} -> {understand(q)}")
