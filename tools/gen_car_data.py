"""Builds engineer/car_data.py from the per-car research files (car parity phase 2, 2026-10-29).

    python tools/gen_car_data.py <folder with the research *.json> [engineer/car_data.py]

The research files (one per Sports Car / Prototype on iRacing) each carry their `sources` and an `unverified` list.
Only what they mark as sourced goes into the app:
  - the CarPath only where it is verified (Lovely Car Data); unverified paths are left out and the car is found by
    its iRacing CarID instead (Garage 61 list),
  - ABS / TC only where a source states it ("yes"/"no"); everything else stays None = unknown, and the app checks
    the car's live telemetry (dcABS / dcTractionControl) instead,
  - hybrid only where the page says so ("no (not stated)" counts as unknown),
  - the engine text and the shift-light rpm only as given (the sound-mix voice is derived from them),
  - car notes: a short hand-picked subset of the sourced engineer notes (practical ones only, no trivia).
Never add a number here that is not in a research file.
"""
import glob, json, os, re, sys

# research class -> (setup / mechanic kind, spoken class label or None)
# spoken labels are only the ones the voice has recordings for (classes.py): GTP LMP2 LMP3 GT3 GT4 GTE
KIND = {
    "GTP": ("gtp", "GTP"), "LMP1": ("lmp1", None), "LMP2": ("lmp2", "LMP2"), "LMP3": ("lmp3", "LMP3"),
    "DP": ("dp", None), "Prototype (Radical)": ("proto", None),
    "GT3": ("gt3", "GT3"), "GT4": ("gt4", "GT4"), "GTE": ("gte", "GTE"), "GT1": ("gt1", None),
    "TCR": ("tcr", None),
    "Cup (Porsche)": ("cup", None), "Cup (Ferrari Challenge)": ("cup", None), "Cup (Clio)": ("cup", None),
    "IMSA GTP (1980s)": ("classic", None), "GTO": ("classic", None), "GT2 / GT3 (legacy)": ("classic", None),
    "Electric GT": ("electric", None),
}
TOURING = {"Touring", "Touring (CTS-V)", "Supercars", "Supercars (Gen2)", "V8 Supercars (legacy)", "Stock Car Brasil",
           "NASCAR Euro", "Mustang Challenge"}

# short practical notes, each taken from that car's sourced engineer_notes (trivia and app-internal notes left out).
# The two BMWs keep the notes the app already had (series.CAR_NOTES).
NOTES = {
    "acuraarx06gtp": ["Spec 50 kW hybrid."],
    "acuransxevo22gt3": ["Adjustable TC."],
    "amvalkyriegtp": ["No hybrid: no deploy, regen or battery calls.", "Naturally aspirated V12."],
    "audi-90-gto": ["AWD."],
    "audi-r8-lms-gt3": ["RWD race car, unlike the AWD road R8."],
    "audir18": ["Front wheels driven by the electric motor, rears by the diesel: very strong traction out of slow corners."],
    "audir8lmsevo2gt3": ["4-way adjustable dampers."],
    "audirs3lms": ["FWD."], "audirs3lmsgen2": ["FWD."], "hondacivictyper": ["FWD."], "hyundaielantracn7": ["FWD."],
    "hyundaivelostern": ["FWD."], "kia-optima": ["FWD."],
    "bmwm2csr": ["Has ABS."],
    "bmwm8gte": ["Front-engine, big car: hard to pass."],
    "caterham-caterhamacademy": ["Low-grip tyre on purpose: teaches car control."],
    "dallarap217": ["Gibson V8 spec engine, Xtrac 6-speed paddle shift."],
    "ferrari499p": ["LMH, not LMDh: 1,120 kg on iRacing's page (the LMDh cars are listed at 1,030 kg).", "7-speed sequential."],
    "ford-mustang-fr500s": ["Has ABS.", "Live rear axle."],
    "fordmustanggt3": ["Front-engine V8."],
    "hpdarx01c": ["Traction control fitted.", "Lots of downforce: carbon brakes, wings and tunnels."],
    "ligierjsp320": ["Has traction control.", "Faster class when mixed with GT4s."],
    "mazda-mx-5-roadster-2010": ["Right-hand drive."],
    "mercedes-amg-gt3": ["Traction control fitted."],
    "mercedesamgevogt3": ["Big naturally aspirated V8, front-mid engine."],
    "nissan-gtp-zx-t": ["1980s GTP: no hybrid."],
    "pontiac-solstice-club-sport": ["Momentum car: smooth inputs."],
    "porsche-gt3-cup": ["Rear engine: demanding to master."],
    "porsche-mission-r": ["Electric: no fuel calls."],
    "porsche963gtp": ["Spec 50 kW hybrid, 1,030 kg, same as the other GTPs."],
    "porsche9922cup": ["More in-car adjustments than the 992.1."],
    "porsche992rgt3": ["Rear-engine flat six (911)."],
    "radical-sr8": ["Revs to 10,500 rpm."],
    "radicalsr10": ["725 kg: very light, near LMP2 pace."],
    "riley-mkxx-daytona-prototype": ["Flat-bottomed, limited downforce."],
    "specracer": ["Momentum car: about 150 mph top speed."],
    "v8-supercar-ford-falcon-2009": ["Live rear axle."],
    "volkswagen-jetta-tdi": ["Has ABS.", "DSG automatic."],
}


def _yes_no(s):
    s = str(s or "").strip().lower()
    if s.startswith("yes"):
        return True
    if s.startswith("no") and "not stated" not in s:
        return False
    return None


def _cyl(engine):
    """Cylinder count only where the engine text names it."""
    e = str(engine or "").lower()
    if "electric motors" in e and "v" not in e.split("electric")[0]:
        return None
    m = re.search(r"\bv(\d{1,2})\b", e)
    if m:
        return int(m.group(1))
    if re.search(r"straight six|flat six|flat-six|inline six|\bi6\b", e):
        return 6
    if "five-cylinder" in e:
        return 5
    if re.search(r"inline four|turbo four|ford four|diesel four", e):
        return 4
    return None


def build(src):
    cars = []
    for f in sorted(glob.glob(os.path.join(src, "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        d = json.load(open(f, encoding="utf-8"))
        key = os.path.basename(f)[:-5]
        cls = d["class"]
        if cls in KIND:
            kind, spoken = KIND[cls]
        elif cls in TOURING:
            kind, spoken = "touring", None
        else:
            kind, spoken = "club", None
        verified_path = d["car_path"] if str(d.get("car_path_status", "")).startswith("verified") else None
        hy = str(d.get("hybrid") or "").lower()
        electric = "full electric" in hy
        engine_doubt = any(str(u).lower().startswith("engine") for u in d.get("unverified", []))
        sl = d.get("shift_lights") or {}
        red = sl.get("redline_rpm_by_gear") or {}
        cars.append({
            "key": key,
            "id": d["iracing_car_id"],
            "path": verified_path,
            "name": d["display_name"],
            "cls_text": cls,
            "cls": spoken,
            "kind": kind,
            "hybrid": False if electric else _yes_no(d.get("hybrid")),
            "electric": electric,
            "abs": _yes_no(d["aids"]["abs"]),
            "tc": _yes_no(d["aids"]["tc"]),
            "engine": d.get("engine"),
            "cyl": None if engine_doubt else _cyl(d.get("engine")),
            "shift_rpm": max(red.values()) if red else None,
            "notes": NOTES.get(key, []),
            "src": d.get("sources", []),
        })
    return cars


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/work/sc_cars/out"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "engineer", "car_data.py")
    cars = build(src)
    lines = ['"""Sports Car / Prototype data for every car on iRacing\'s Sports Car and Prototypes menus (car parity, 2026-10-29).',
             "",
             "GENERATED by tools/gen_car_data.py from the per-car research files - do not edit by hand.",
             "Each entry: id = iRacing CarID (Garage 61 list); path = iRacing CarPath ONLY where verified (Lovely Car Data),",
             "else None; abs / tc / hybrid = True / False only where a source states it, None = unknown (check live);",
             "cls = the spoken class label (only the ones with voice recordings), cls_text = the class as text;",
             "shift_rpm = Lovely Car Data's top shift-light rpm; src = where the facts come from.",
             '"""', "", "CARS = ["]
    for c in cars:
        lines.append(" " + json.dumps(c, ensure_ascii=False).replace(": true", ": True").replace(": false", ": False")
                     .replace(": null", ": None") + ",")
    lines.append("]")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{len(cars)} cars -> {out}")


if __name__ == "__main__":
    main()
