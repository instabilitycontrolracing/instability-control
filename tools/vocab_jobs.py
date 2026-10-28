import os, sys, re, json
sys.path.insert(0, os.path.dirname(__file__))
from vocab_spec import L, BLOCKS, NAME
ROOT = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1", "vocab")
TOK = re.compile(r"(\[[^\]]+\]|\{GTP:[^}]*\})")

def _w(n):
    from vocab_spec import words
    n = int(n)
    if n < 200: return words(n)
    if n < 1000: return words(n // 100) + " hundred" + ("" if n % 100 == 0 else " " + words(n % 100))
    return " ".join(words(int(c)) for c in str(n))

def spell(t):
    """Requested 2026-10-24: every number is written out as words so the voice can't misread it ("P1" -> "P one")."""
    t = re.sub(r"\bLMP(\d+)", lambda m: "El Em Pee " + _w(m.group(1)), t)     # class names keep their letters
    t = re.sub(r"\bGT(\d+)", lambda m: "Gee Tee " + _w(m.group(1)), t)
    t = re.sub(r"\bP(\d+)", lambda m: "P " + _w(m.group(1)), t)
    t = re.sub(r"(\d+)\.(\d+)", lambda m: _w(m.group(1)) + " point " + " ".join(_w(c) for c in m.group(2)), t)
    t = re.sub(r"\d+", lambda m: _w(m.group(0)), t)
    # Requested 2026-10-24: single letters in the phonetic alphabet ("Plan A" -> "Plan Alpha"), except P and I
    # ...but not the letters in corner names: "S Curves", "one-thirty R" (Suzuka, 2026-10-28)
    t = re.sub(r"(?<![\w'])(?<!thirty )([A-HJ-OQ-Z])(?![\w'])(?! Curves?\b)", lambda m: NATO[m.group(1)], t)
    return t

NATO = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliett Kilo Lima Mike "
                                              "November Oscar Papa Quebec Romeo Sierra Tango Uniform Victor Whiskey X-ray Yankee Zulu".split()))

def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "x"

LANDMARKS = [os.environ.get("CC_LANDMARKS") or r"C:\Program Files (x86)\Britton IT Ltd\CrewChiefV4\trackLandmarksData.json"]
# tracks whose named corners are rendered: the owner's IMSA / endurance tracks by name (2026-10-28: + Suzuka, Silverstone,
# Sebring) and every track with a research pack in engineer/track_packs.py (the Sports Car tracks)
NAMED_TRACKS = r"spa|lemans|le_mans|sarthe|daytona|watkins|mexico|miami|monza|suzuka|silverstone|sebring"
# how a corner is SAID when CrewChief's name doesn't read well (the clip key stays CrewChief's, so the app finds it)
CORNER_SAY = {"130r": "One-thirty R.", "maggots": "Maggotts.", "le_mans": "Le Mans.",
              # CrewChief spellings / letters the voice would misread (2026-10-28, Sports Car tracks)
              "a_1": "Ay one.", "t_13": "Turn thirteen.", "mobile_1": "Mobil one.", "varianti_alta": "Variante Alta.",
              "poggio_seco": "Poggio Secco.", "tore_vip": "Torre VIP.", "sachcsen_anhalt_kurve": "Sachsen-Anhalt Kurve.",
              "michael_schumacer_s": "Michael Schumacher Ess.", "obrien_aluminium_dogleg": "O'Brien Aluminium Dogleg.",
              "mcphillamy_park": "McPhillamy Park.", "mcintyre": "McIntyre.", "mclaren": "McLaren.", "mcleans": "McLeans.", "hyundai_n_kurve": "Hyundai En Kurve.",
              "ngk_shalken": "En Gee Kay Schikane.", "northern_bm_corner": "Northern Bee Em Corner.",
              # round 2 (2026-10-28): Magny-Cours and Thruxton, as the research packs name them
              "180": "One-eighty.", "lycee_pin": "Lycée.", "chateau_d_eau": "Château d'Eau.",
              "the_end_of_the_complex": "End of the complex.", "village_en": "Village.", "nurburgring": "Nürburgring."}


def corner_say(n):
    """Spoken text of a corner clip: "Senna S" -> "Senna Ess." (a lone S would be read as "Sierra")."""
    return CORNER_SAY.get(slug(n)) or re.sub(r" S$", " Ess", n) + "."


def _pack_ids():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from engineer.track_packs import PACK_TRACKS, PACK_ALIASES
    return set(PACK_TRACKS) | set(PACK_ALIASES)


def pack_track(tn, ids=None):
    """True if this CrewChief irTrackName ("brandshatch grandprix", "oulton fosters") is a track_packs track."""
    ids = _pack_ids() if ids is None else ids
    n = re.sub(r"[^a-z0-9]", "", (tn or "").lower())
    if len(n) < 4:
        return False
    if any(n == a or n.startswith(a) or a.startswith(n) or (len(n) > 6 and n in a) for a in ids):
        return True
    w = re.match(r"[a-z]+", (tn or "").lower())          # "zandvoort grandprix" -> any pack id starting "zandvoort"
    return bool(w and len(w.group(0)) >= 5 and any(a.startswith(w.group(0)) for a in ids))


def corner_tracks(d):
    """CrewChief track entries whose named corners get clips."""
    ids = _pack_ids()
    out = []
    for t in d.get("trackLandmarksData", []):
        tn = (t.get("irTrackName") or "").lower()
        if not tn or re.search(r"rallycross|bike|(?<!r)oval|\bev\b", tn):     # rovals (Charlotte) are road courses
            continue
        if t.get("isOval") and "roval" not in tn:          # 2026-10-28: "chicagoland" is not the Chicago street course
            continue
        if re.search(NAMED_TRACKS, tn) or pack_track(tn, ids):
            out.append(t)
    return out


def corner_names(paths=None):
    names = []
    for base in (paths or LANDMARKS):
        if os.path.exists(base):
            d = json.load(open(base, encoding="utf-8-sig"))
            for t in corner_tracks(d):
                for lm in t.get("trackLandmarks", []):
                    for raw in lm.get("landmarkNames", []):
                        if re.match(r"(?i)^turn_?\d+", raw): continue
                        n = raw.replace("_", " ").strip().title()
                        n = re.sub(r"(\D)(\d+)$", r"\1 \2", n)
                        n = {"Radillion": "Raidillon", "Lesmos 1": "Lesmo 1", "Lesmos 2": "Lesmo 2"}.get(n, n)
                        n = n.replace("Nascar", "NASCAR")
                        if n in ("No Name", "Man"): continue          # "man": Oran Park South, no sourced name
                        if n and n not in names: names.append(n)
    return names


def build():
    jobs, manifest = [], {"lines": [], "blocks": {}, "recorded_name": NAME}
    seen = set()
    vcount = {}
    for sid, lang, text in L:
        key = (sid, text)
        if key in seen: continue
        seen.add(key)
        v = vcount.get(sid, 0) + 1; vcount[sid] = v
        parts, k = [], 0
        for tok in TOK.split(text):
            tok = tok.strip()
            if not tok: continue
            if tok.startswith("[") and tok.endswith("]"):
                parts.append({"fill": tok[1:-1]}); continue
            gtp = tok.startswith("{GTP:")
            t = tok[5:-1].strip() if gtp else tok
            if not re.search(r"[A-Za-z0-9]", t): continue
            # the owner's rule: periods inside a line become commas (shorter pauses); only the last one stays
            t = re.sub(r"^[\s.,]+", "", t)
            t = re.sub(r"\.\s+(?=\S)", ", ", t)
            t = spell(t)
            k += 1
            jid = f"lines/{sid}/v{v}_{k}"
            jobs.append({"id": jid, "text": t, "lang": lang})
            parts.append({"clip": jid + ".wav", "gtp": gtp})
        manifest["lines"].append({"situation": sid, "variant": v, "lang": lang, "text": text, "parts": parts})
    # named corners for the owner's tracks from CrewChief's corner map
    names = corner_names()
    blocks = list(BLOCKS) + [("corner", slug(n), corner_say(n)) for n in names]
    for kind, key, text in blocks:
        jid = f"blocks/{kind}/{key}"
        jobs.append({"id": jid, "text": spell(text), "lang": "en"})
        manifest["blocks"].setdefault(kind, {})[key] = jid + ".wav"
    os.makedirs(ROOT, exist_ok=True)
    json.dump(jobs, open(os.path.join(ROOT, "jobs.json"), "w", encoding="utf-8"), indent=1)
    json.dump(manifest, open(os.path.join(ROOT, "manifest.json"), "w", encoding="utf-8"), indent=1)
    return jobs, names

if __name__ == "__main__":
    jobs, names = build()
    nl = sum(1 for j in jobs if j["id"].startswith("lines/"))
    print(f"{len(jobs)} clips: {nl} line pieces, {len(jobs)-nl} building blocks; {len(names)} named corners")
    print("corners sample:", names[:25])
