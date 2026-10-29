"""Setup helper bank: problem -> technique check -> ordered setup changes, per car type, dry and wet.

No AI. Sources: iRacing's BMW M4 GT3 and BMW M Hybrid V8 manuals (+ Porsche/Cadillac GTP manuals for
brake migration), see project doc mechanic-setup-rulebook.md. Directions that run "backwards" in iRacing
are spelled out (e.g. GTP diff ramp angles: lower = more locking).

Car kinds: "gtp" (M Hybrid V8), "gt3" (M4 GT3 / EVO), "other" (anything else, generic advice). Since 2026-10-29 the
mechanic names more kinds (gt4, gte, lmp2, tcr, cup ...): they use the "other" table (TABLE / table_kind below).
Each change: what to do, where to find it, which setup value to show (keys), and why.
"""

AREAS = [
    {"id": "braking", "label": "Braking", "sub": "before the corner"},
    {"id": "entry", "label": "Corner entry", "sub": "turn-in"},
    {"id": "mid", "label": "Mid-corner", "sub": "apex"},
    {"id": "exit", "label": "Corner exit", "sub": "on throttle"},
    {"id": "bumps", "label": "Bumps & kerbs", "sub": "kerbs · bumps"},
    {"id": "straights", "label": "Straights", "sub": "top speed · stability"},
    {"id": "tyres", "label": "Tyres", "sub": "long runs"},
]

# where things live (shown to the driver)
W = {
    "gtp": {"bias": "In car (dash: BB) or Garage → Brakes/Drive Unit", "mig": "In car (dash: migration) or Garage → Brakes/Drive Unit",
            "farb": "In car: FARB on the dash (higher = stiffer)", "rarb": "In car: RARB on the dash (higher = stiffer)",
            "tc1": "In car: TC1 (gain, higher = cuts harder)", "tc2": "In car: TC2 (slip, higher = steps in sooner)",
            "wing": "Garage → Tires/Aero → Rear wing angle", "rh": "Garage → Chassis → pushrod length offsets / perch offsets",
            "diff": "Garage → Brakes/Drive Unit → Rear diff", "damp": "Garage → Chassis → dampers (each corner)",
            "heave": "Garage → Chassis → Front heave spring / Rear third spring", "press": "Garage → Tires/Aero → starting pressure",
            "camber": "Garage → Chassis → camber (each corner)", "toe": "Garage → Chassis → toe"},
    "gt3": {"bias": "In car (brake bias) or Garage", "abs": "In car: ABS (higher = more help)", "tc": "In car: TC (higher = more intervention)",
            "farb": "Garage → Chassis → Front ARB", "rarb": "Garage → Chassis → Rear ARB", "wing": "Garage → Aero → Rear wing",
            "rh": "Garage → Chassis → ride heights", "diff": "Garage → Rear diff (preload / friction faces)", "damp": "Garage → Dampers",
            "spring": "Garage → Chassis → springs", "press": "Garage → Tyres → cold pressure", "camber": "Garage → Chassis → camber",
            "toe": "Garage → Chassis → toe", "bump": "Garage → Chassis → bump rubber gap"},
}
W["other"] = dict(W["gt3"])

K = {  # setup keys to read the current value from (telemetry setup / in-car channel)
    "bias": ["BrakePressureBias", "BrakeBias", "@dcBrakeBias"], "mig": ["BrakeBiasMigration"],
    "farb": ["@dcAntiRollFront", "Front.ArbBlades", "Front.ArbSize", "FrontArb", "Front.ArbSetting"],
    "rarb": ["@dcAntiRollRear", "Rear.ArbBlades", "Rear.ArbSize", "RearArb", "Rear.ArbSetting"],
    "tc1": ["TractionControlGain"], "tc2": ["TractionControlSlip"], "tc": ["@dcTractionControl", "TractionControl"],
    "abs": ["@dcABS", "AbsSetting"], "wing": ["RearWingAngle", "RearWingPosition", "WingSetting"],
    "preload": ["Preload", "DiffPreload"], "ramps": ["CoastDriveRampAngles"], "plates": ["ClutchFrictionPlates", "FrictionFaces"],
    "rh_f": ["LeftFront.RideHeight"], "rh_r": ["LeftRear.RideHeight"], "heave": ["HeaveSpring"], "third": ["ThirdSpring"],
    "press": ["StartingPressure", "ColdPressure"], "camber_f": ["LeftFront.Camber"], "camber_r": ["LeftRear.Camber"],
}


def C(text, where=None, key=None, why=""):
    return {"t": text, "where": where, "key": key, "why": why}


PROBLEMS = [
 # ---------------------------------------------------------------- braking
 {"id": "lock_front", "area": "braking", "label": "Front wheels lock", "speed": False,
  "check": ["Are you holding full brake pressure all the way to the corner? Hit it hard at the start, then release as the speed drops: the car needs less brake as it slows."],
  "fix": {
   "gtp": [C("Brake bias 0.5–1% rearward", "bias", "bias", "Less of the braking on the fronts. The BMW GTP has no ABS: front lock shows as the pink lights."),
           C("Brake migration one click less negative", "mig", "mig", "Keeps a bit less front bias as you trail off."),
           C("Lower-friction brake pads", "Garage → Brakes → pad compound", None, "Easier to modulate at the limit.")],
   "gt3": [C("One step more ABS", "abs", "abs", "More ABS help stops the lock-up."),
           C("Brake bias 0.5% rearward", "bias", "bias", "Moves braking work off the fronts."),
           C("Lower-friction brake pads", "Garage → Brakes → pads", None, "Less bite, easier to modulate.")],
   "other": [C("Brake bias 0.5–1% rearward", "bias", "bias", "Moves braking work off the fronts."),
             C("More ABS if the car has it", "abs", "abs", "")]},
  "wet": "In the wet lock-ups come much earlier: brake earlier and softer, and move bias 1–2% rearward from your dry setting."},
 {"id": "lock_rear", "area": "braking", "label": "Rear wheels lock / rear steps out under braking", "speed": False,
  "check": ["Are you downshifting very quickly, or turning while still on heavy brake? Both unload the rear."],
  "fix": {
   "gtp": [C("Brake bias 0.5–1% forward", "bias", "bias", "Rear lock shows as the yellow lights on the BMW GTP."),
           C("Brake migration one click more positive (towards zero)", "mig", "mig", "Less rear braking as you trail off."),
           C("A little more diff preload, or a lower coast ramp angle", "diff", "preload", "More locking off throttle keeps the rear in line. On the GTP a LOWER ramp angle = MORE locking.")],
   "gt3": [C("Brake bias 0.5% forward", "bias", "bias", "Takes braking work off the rears."),
           C("A little more diff preload", "diff", "preload", "Manual: more preload = less lift-off oversteer, more entry stability."),
           C("More rear low-speed rebound", "damp", None, "Slows the rear rising under braking, keeps it planted.")],
   "other": [C("Brake bias 0.5% forward", "bias", "bias", ""), C("More diff preload", "diff", "preload", "")]},
  "wet": "In the wet bring bias forward and add a little preload; the rear locks easily on a wet track."},
 {"id": "brake_unstable", "area": "braking", "label": "Car moves around / unstable under braking", "speed": False,
  "check": ["Are you braking in a straight line before you turn? Braking hard while turning makes any car nervous."],
  "fix": {
   "gtp": [C("Brake bias 0.5% forward", "bias", "bias", "A forward bias is more stable."),
           C("Stiffer front heave spring", "heave", "heave", "Stops the nose diving and the aero balance jumping forward."),
           C("More rear low-speed rebound", "damp", None, "Keeps the rear from rising and going light.")],
   "gt3": [C("Brake bias 0.5% forward", "bias", "bias", ""), C("More diff preload", "diff", "preload", "More stability off throttle."),
           C("A little more rear toe-in", "toe", None, "More straight-line stability.")],
   "other": [C("Brake bias 0.5% forward", "bias", "bias", ""), C("More diff preload", "diff", "preload", "")]},
  "wet": "In the wet move bias forward a touch more than in the dry."},
 # ---------------------------------------------------------------- entry
 {"id": "entry_us", "area": "entry", "label": "Understeer on turn-in (won't turn)", "speed": False,
  "check": ["Are you still on heavy brake when you start turning? Bleed the brake off while you turn in.",
            "Are you letting go of the brake all at once before the corner? The front goes light and won't bite: release gradually."],
  "fix": {
   "gtp": [C("Brake migration one click more negative", "mig", "mig", "More rear braking as you trail off helps the car rotate on entry."),
           C("FARB one step softer (in the car)", "farb", "farb", "Softer front bar = more front grip."),
           C("A little less diff preload", "diff", "preload", "Less locking off throttle lets the car turn.")],
   "gt3": [C("Brake bias 0.5% rearward", "bias", "bias", "Rear does more braking, the car rotates more."),
           C("One step less ABS (if it's working a lot)", "abs", "abs", "Too much ABS can make the car push on entry."),
           C("Front ARB one step softer", "farb", "farb", "More front grip."),
           C("A little less diff preload", "diff", "preload", "")],
   "other": [C("Brake bias 0.5% rearward", "bias", "bias", ""), C("Softer front anti-roll bar", "farb", "farb", ""),
             C("Less diff preload", "diff", "preload", "")]},
  "wet": "In the wet entry understeer is normal: slow down more before turning. Softer bars all round help in the wet."},
 {"id": "entry_os", "area": "entry", "label": "Oversteer / rear loose on turn-in", "speed": False,
  "check": ["Are you trail braking very deep or downshifting mid-corner? Finish the downshifts in a straight line.",
            "Are you lifting off the throttle suddenly in a fast corner? Lift gently."],
  "fix": {
   "gtp": [C("Brake bias 0.5% forward", "bias", "bias", "More stable on entry."),
           C("Brake migration one click towards zero", "mig", "mig", "Less rear braking while you trail off."),
           C("More diff preload (or a lower coast ramp angle)", "diff", "preload", "Manual: more preload = less lift-off oversteer. GTP: lower ramp angle = more locking."),
           C("RARB one step softer (in the car)", "rarb", "rarb", "")],
   "gt3": [C("Brake bias 0.5% forward", "bias", "bias", ""), C("More diff preload", "diff", "preload", "Less lift-off oversteer, more entry stability."),
           C("More rear low-speed rebound", "damp", None, ""), C("Rear ARB one step softer", "rarb", "rarb", "")],
   "other": [C("Brake bias 0.5% forward", "bias", "bias", ""), C("More diff preload", "diff", "preload", ""), C("Softer rear anti-roll bar", "rarb", "rarb", "")]},
  "wet": "In the wet: bias forward, softer rear bar, and be gentle lifting off."},
 # ---------------------------------------------------------------- mid
 {"id": "mid_us_slow", "area": "mid", "label": "Understeer mid-corner (slow corners)", "speed": "slow",
  "check": ["Are you adding more and more steering while the car doesn't turn more? You're scrubbing the front: carry less steering, slow a little more on entry."],
  "fix": {
   "gtp": [C("FARB one step softer (in the car)", "farb", "farb", "Mechanical balance in slow corners comes from the bars."),
           C("RARB one step stiffer (in the car)", "rarb", "rarb", ""),
           C("A little less diff preload", "diff", "preload", "Preload adds mid-corner understeer.")],
   "gt3": [C("Front ARB one step softer", "farb", "farb", ""), C("Rear ARB one step stiffer", "rarb", "rarb", ""),
           C("A little less diff preload", "diff", "preload", "")],
   "other": [C("Softer front anti-roll bar", "farb", "farb", ""), C("Stiffer rear anti-roll bar", "rarb", "rarb", "")]},
  "wet": "In the wet go softer on the front bar first."},
 {"id": "mid_us_fast", "area": "mid", "label": "Understeer mid-corner (fast corners)", "speed": "fast",
  "check": ["Is it only in the fast corners? Then it's aero balance, not the roll bars."],
  "fix": {
   "gtp": [C("A little more rake: rear pushrod up a touch", "rh", "rh_r", "Rear higher = aero balance forward = more front grip at speed."),
           C("One click less rear wing", "wing", "wing", "Balance forward (and less drag). The manual says one click at a time.")],
   "gt3": [C("Raise the rear ride height a little (more rake)", "rh", "rh_r", "Balance forward at speed."),
           C("One click less rear wing", "wing", "wing", "To keep the same balance per wing click: front ∓1.5 mm or rear ±4.5 mm.")],
   "other": [C("A little more rake (rear up)", "rh", "rh_r", ""), C("One click less rear wing", "wing", "wing", "")]},
  "wet": "In the wet you usually want MORE wing overall: fix this one with rake rather than wing."},
 {"id": "mid_os_slow", "area": "mid", "label": "Oversteer mid-corner (slow corners)", "speed": "slow",
  "check": ["Are you on the throttle before the car has finished turning? Wait for the rotation, then throttle."],
  "fix": {
   "gtp": [C("RARB one step softer (in the car)", "rarb", "rarb", ""), C("FARB one step stiffer (in the car)", "farb", "farb", "")],
   "gt3": [C("Rear ARB one step softer", "rarb", "rarb", ""), C("Front ARB one step stiffer", "farb", "farb", "")],
   "other": [C("Softer rear anti-roll bar", "rarb", "rarb", ""), C("Stiffer front anti-roll bar", "farb", "farb", "")]},
  "wet": "In the wet soften the rear bar first."},
 {"id": "mid_os_fast", "area": "mid", "label": "Oversteer mid-corner (fast corners)", "speed": "fast",
  "check": ["Are you lifting in the fast corner? A lift moves the weight forward and the rear goes light: stay committed or lift very gently."],
  "fix": {
   "gtp": [C("One click more rear wing", "wing", "wing", "More rear downforce."), C("Less rake: rear pushrod down a touch", "rh", "rh_r", "Balance rearward at speed.")],
   "gt3": [C("One click more rear wing", "wing", "wing", ""), C("Lower the rear ride height a little", "rh", "rh_r", "Less rake = more stable at speed.")],
   "other": [C("More rear wing", "wing", "wing", ""), C("Less rake (rear down)", "rh", "rh_r", "")]},
  "wet": "In the wet more wing is almost always right."},
 {"id": "lazy", "area": "mid", "label": "Lazy changing direction (chicanes, esses)", "speed": False,
  "check": ["Are you waiting for the car to settle before the second turn? Use the curbs and a straighter line through the chicane."],
  "fix": {
   "gtp": [C("Stiffer FARB and RARB together, one step each", "farb", "farb", "More roll stiffness = quicker response, same balance."),
           C("More front toe-out", "toe", None, "Sharper turn-in.")],
   "gt3": [C("Stiffer front and rear ARB together", "farb", "farb", "Quicker response, same balance."), C("A touch more front toe-out", "toe", None, "")],
   "other": [C("Stiffer anti-roll bars front and rear", "farb", "farb", "")]},
  "wet": "Not for the wet: stay soft in the rain."},
 # ---------------------------------------------------------------- exit
 {"id": "exit_os", "area": "exit", "label": "Oversteer / wheelspin on exit", "speed": False,
  "check": ["Are you going to full throttle while the wheel is still turned? Unwind the steering first, then squeeze the throttle in."],
  "fix": {
   "gtp": [C("TC2 (slip) one step up (in the car)", "tc2", "tc2", "Steps in sooner and allows less wheelspin."),
           C("TC1 (gain) one step up", "tc1", "tc1", "Cuts harder when it steps in."),
           C("A little less diff preload or fewer clutch plates", "diff", "preload", "Both add on-throttle oversteer."),
           C("RARB one step softer (in the car)", "rarb", "rarb", "")],
   "gt3": [C("TC one step more intervention (in the car)", "tc", "tc", "GT3 TC was reworked in 2026 S3: check the range in game."),
           C("A little less diff preload / fewer friction faces", "diff", "preload", "Manual: both add on-throttle oversteer."),
           C("Softer rear springs or rear ARB", "rarb", "rarb", "More rear traction out of slow corners.")],
   "other": [C("More traction control", "tc", "tc", ""), C("Less diff preload", "diff", "preload", ""), C("Softer rear anti-roll bar", "rarb", "rarb", "")]},
  "wet": "In the wet: TC up 2–3 steps from dry and short-shift out of slow corners."},
 {"id": "exit_us", "area": "exit", "label": "Understeer on exit (runs wide on power)", "speed": False,
  "check": ["Are you picking up throttle too early with lots of steering? Get the car turned first."],
  "fix": {
   "gtp": [C("Higher drive ramp angle (less diff locking on power)", "diff", "ramps", "On the GTP a HIGHER ramp angle = LESS locking."),
           C("Fewer clutch plates", "diff", "plates", ""), C("FARB one step softer (in the car)", "farb", "farb", "")],
   "gt3": [C("Less front low-speed rebound", "damp", None, "Manual: front rebound adds on-throttle understeer."),
           C("Less rear low-speed compression", "damp", None, "Manual: rear LS compression adds understeer on throttle."),
           C("Front ARB one step softer", "farb", "farb", "")],
   "other": [C("Softer front anti-roll bar", "farb", "farb", ""), C("Less diff preload", "diff", "preload", "")]},
  "wet": "In the wet it's mostly technique: wait longer before the throttle."},
 {"id": "snap", "area": "exit", "label": "Snap oversteer (sudden, no warning)", "speed": False,
  "check": ["Does it happen when you go from off to on throttle quickly? Smooth, progressive throttle.",
            "Does it happen when you LIFT? That's lift-off oversteer: see 'Oversteer on turn-in' instead."],
  "fix": {
   "gtp": [C("A little less diff preload", "diff", "preload", ""), C("RARB one step softer (in the car)", "rarb", "rarb", ""),
           C("More rear low-speed rebound", "damp", None, "At high speed, snap can be the rear rising and the aero balance moving forward.")],
   "gt3": [C("Less diff preload / fewer friction faces", "diff", "preload", ""), C("Rear ARB one step softer", "rarb", "rarb", "")],
   "other": [C("Less diff preload", "diff", "preload", ""), C("Softer rear anti-roll bar", "rarb", "rarb", "")]},
  "wet": "In the wet the snap usually means too much throttle: TC up first."},
 # ---------------------------------------------------------------- bumps
 {"id": "bottoming", "area": "bumps", "label": "Bottoming / scraping", "speed": False,
  "check": ["Is it only over one big kerb? Change the line before the car."],
  "fix": {
   "gtp": [C("Stiffer heave spring (front) / third spring (rear) on the end that bottoms", "heave", "heave", "Controls ride height at speed without changing roll balance."),
           C("Raise ride height on that end a little", "rh", "rh_f", ""),
           C("Lower high-speed compression slope", "damp", None, "Softer over sharp bumps and kerbs.")],
   "gt3": [C("Raise the ride height on the end that bottoms", "rh", "rh_f", "The GT3 is very sensitive to small ride height changes."),
           C("Bigger bump rubber gap", "bump", None, "EVO only."), C("Stiffer springs on that end", "spring", None, "")],
   "other": [C("Raise ride height a little", "rh", "rh_f", ""), C("Stiffer springs", "spring", None, "")]},
  "wet": "In the wet raise the car a little anyway: standing water and bumps."},
 {"id": "kerbs", "area": "bumps", "label": "Bouncy / unsettled over kerbs", "speed": False,
  "check": ["Are you hitting the high sausage kerbs? Those will upset any setup: avoid them."],
  "fix": {
   "gtp": [C("Less high-speed compression (or lower HS slope)", "damp", None, "Lets the wheel ride over the kerb."),
           C("Less high-speed rebound", "damp", None, "Lets the wheel come back down faster.")],
   "gt3": [C("Less high-speed compression", "damp", None, ""), C("Softer springs on the end that bounces", "spring", None, "")],
   "other": [C("Softer high-speed dampers", "damp", None, ""), C("Softer springs", "spring", None, "")]},
  "wet": ""},
 # ---------------------------------------------------------------- straights
 {"id": "slow_straights", "area": "straights", "label": "Slow on the straights", "speed": False,
  "check": ["Is your exit from the corner before it good? Exit speed decides the whole straight."],
  "fix": {
   "gtp": [C("One click less rear wing", "wing", "wing", "Less drag. The manual says to load a lower-downforce setup if you need more than one click."),
           C("Lower ride heights a little (if it isn't bottoming)", "rh", "rh_r", "")],
   "gt3": [C("One click less rear wing", "wing", "wing", "Downforce guide: over 270 km/h top speed = low downforce trim."),
           C("Lower ride heights a little", "rh", "rh_r", "")],
   "other": [C("Less rear wing", "wing", "wing", "")]},
  "wet": "Not in the wet: keep the wing."},
 {"id": "unstable_speed", "area": "straights", "label": "Nervous at high speed / under braking from high speed", "speed": False,
  "check": [],
  "fix": {
   "gtp": [C("One click more rear wing", "wing", "wing", ""), C("Less rake", "rh", "rh_r", ""), C("A little more rear toe-in", "toe", None, "")],
   "gt3": [C("One click more rear wing", "wing", "wing", ""), C("Less rake", "rh", "rh_r", ""), C("More rear toe-in", "toe", None, "")],
   "other": [C("More rear wing", "wing", "wing", ""), C("More rear toe-in", "toe", None, "")]},
  "wet": "In the wet more wing."},
 # ---------------------------------------------------------------- tyres
 {"id": "tyres_hot", "area": "tyres", "label": "Grip fades over a stint / tyres too hot", "speed": False,
  "check": ["Are you sliding the car a lot? Sliding cooks the tyres: smoother inputs keep them alive."],
  "fix": {
   "gtp": [C("Lower cold pressure on the tyres that overheat", "press", "press", "Higher fast-track pressures, lower slow-track pressures (manual)."),
           C("A little less negative camber on that axle", "camber", "camber_f", "")],
   "gt3": [C("Lower cold pressure (target about 1.50–1.55 bar hot)", "press", "press", "Coach Dave baseline for GT3."),
           C("A little less negative camber", "camber", "camber_f", "")],
   "other": [C("Lower cold pressure", "press", "press", "")]},
  "wet": "In the wet tyres usually run cold: if grip is low, raise pressures a little."},
 {"id": "tyres_cold", "area": "tyres", "label": "No grip, tyres never warm up", "speed": False,
  "check": ["Are you pushing on the out lap? Brake and accelerate hard to bring them in."],
  "fix": {
   "gtp": [C("Raise cold pressure a little", "press", "press", ""), C("A little more negative camber", "camber", "camber_f", "")],
   "gt3": [C("Raise cold pressure a little", "press", "press", ""), C("A little more negative camber", "camber", "camber_f", "")],
   "other": [C("Raise cold pressure a little", "press", "press", "")]},
  "wet": "Common in the wet: raise pressures."},
]

# what the telemetry mechanic detects -> which bank problem it is
FROM_DETECTION = {("understeer", "entry"): "entry_us", ("oversteer", "entry"): "entry_os",
                  ("understeer", "mid", "slow"): "mid_us_slow", ("understeer", "mid", "fast"): "mid_us_fast",
                  ("oversteer", "mid", "slow"): "mid_os_slow", ("oversteer", "mid", "fast"): "mid_os_fast",
                  ("understeer", "exit"): "exit_us", ("oversteer", "exit"): "exit_os"}


def current_values(sess):
    """{key: 'value'} for the setup keys above, from a session's saved setup + in-car channels."""
    out = {}
    if sess is None:
        return out
    tr = None
    try:
        tr = sess.trace(sess.best["n"]) if sess.best else None
    except Exception:
        pass

    def walk(d, path=""):
        for k, v in (d or {}).items():
            if isinstance(v, dict):
                yield from walk(v, path + k + ".")
            else:
                yield path + k, str(v).strip()
    flat = list(walk(sess.setup))
    for key, names in K.items():
        for n in names:
            if n.startswith("@"):
                ch = n[1:]
                if tr is not None and ch in tr:
                    import numpy as np
                    out[key] = str(int(round(float(np.median(tr[ch]))))) if ch != "dcBrakeBias" else f"{float(np.median(tr[ch])):.1f}%"
                    break
                continue
            hit = next((v for p, v in flat if p.endswith(n) or p.split(".")[-1] == n), None)
            if hit:
                out[key] = hit
                break
    return out


# 2026-10-29 (car parity E7): car kinds -> the table they use. Only the GTP and GT3 tables come from car manuals (the
# BMWs'); every other kind (GT4, GTE, LMP2, LMP3, TCR, Cup, touring, club, classic, electric ...) gets the generic advice.
TABLE = {"gtp": "gtp", "gt3": "gt3"}
AID_KEYS = {"abs": "abs", "tc": "tc", "tc1": "tc", "tc2": "tc"}


def table_kind(kind):
    return TABLE.get(kind or "", "other")


def steps_for(problem, kind, aids=None):
    """The fix list for one problem and car kind. aids = {'abs': bool|None, 'tc': bool|None}: steps for an aid the car
    is known NOT to have are left out (car parity E9); unknown keeps them (they say "if the car has it" / "in the car")."""
    tk = table_kind(kind)
    steps = problem["fix"].get(tk) or problem["fix"]["other"]
    aids = aids or {}
    keep = [s for s in steps if not (AID_KEYS.get(s.get("key") or "") and aids.get(AID_KEYS[s["key"]]) is False)]
    return keep or [s for s in problem["fix"]["other"] if not (AID_KEYS.get(s.get("key") or "") and aids.get(AID_KEYS[s["key"]]) is False)]


def bank_for(kind, aids=None):
    tk = table_kind(kind)
    probs = []
    for p in PROBLEMS:
        steps = steps_for(p, kind, aids)
        probs.append({"id": p["id"], "area": p["area"], "label": p["label"], "check": p["check"], "wet": p["wet"],
                      "steps": [dict(s, where=W[tk].get(s["where"], s["where"]) if s["where"] else None) for s in steps]})
    return {"areas": AREAS, "problems": probs}


def detected(sess):
    """Problems the telemetry found (from mechanic.diagnose) as bank ids, with where."""
    from .mechanic import diagnose, MIN_REPEAT
    import numpy as np
    out = {}
    for e in diagnose(sess).values():
        spd = "fast" if np.median(e["speed"]) > 165 else "slow"
        for ph, counts in e["ph"].items():
            for sym, n in counts.items():
                if n >= max(MIN_REPEAT, int(np.ceil(e["laps"] * 0.5))):
                    pid = FROM_DETECTION.get((sym, ph, spd)) or FROM_DETECTION.get((sym, ph))
                    if pid:
                        out.setdefault(pid, []).append(e["name"])
    return [{"id": k, "corners": v} for k, v in sorted(out.items(), key=lambda kv: -len(kv[1]))]


def as_text(kind, aids=None):
    """The whole bank as plain text, for the team AI's context."""
    b = bank_for(kind, aids)
    lines = []
    for p in b["problems"]:
        lines.append(f"{p['label']}: " + " | ".join(f"{i + 1}) {s['t']}" for i, s in enumerate(p["steps"])))
    return "\n".join(lines)
