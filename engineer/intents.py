"""Understands what the driver asked, in his own words (no exact phrases).

First version: scored keyword groups. The speech-recognition step will hand its text to understand().
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
    ("meeting",     [["strategy", "meeting"], ["debrief"], ["talk", "team"], ["meeting"]]),
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


def understand(text):
    """Returns (intent, score) or (None, 0)."""
    t = " " + re.sub(r"[^a-z0-9 ]+", " ", normalize(text)) + " "
    best, best_s = None, 0
    for name, groups in INTENTS:
        for words in groups:
            if all(f" {w} " in t or (len(w) > 4 and w in t) for w in words):
                s = sum(len(w) for w in words)
                if s > best_s:
                    best, best_s = name, s
    return best, best_s


if __name__ == "__main__":
    for q in ["how's the gap to the car in front", "what position are we", "do we have enough fuel to finish",
              "how many laps left", "who's behind me", "what was my last lap time", "spotter off please",
              "can you hear me", "let's have a strategy meeting", "what's the track temperature",
              "say again", "who's the car ahead", "what's the strength of field", "how much irating do we gain",
              "any damage", "how are the tyres", "where do we come out if we box", "what's the weather",
              "what's the fuel target", "fuel per lap", "what time is it", "who's fastest", "gap to the leader"]:
        print(f"{q!r:45} -> {understand(q)}")
