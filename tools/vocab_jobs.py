import os, sys, re, json
sys.path.insert(0, os.path.dirname(__file__))
from vocab_spec import L, BLOCKS
ROOT = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1", "vocab")
TOK = re.compile(r"(\[[^\]]+\]|\{GTP:[^}]*\})")

def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "x"

def build():
    jobs, manifest = [], {"lines": [], "blocks": {}}
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
            # Angelo's rule: periods inside a line become commas (shorter pauses); only the last one stays
            t = re.sub(r"^[\s.,]+", "", t)
            t = re.sub(r"\.\s+(?=\S)", ", ", t)
            k += 1
            jid = f"lines/{sid}/v{v}_{k}"
            jobs.append({"id": jid, "text": t, "lang": lang})
            parts.append({"clip": jid + ".wav", "gtp": gtp})
        manifest["lines"].append({"situation": sid, "variant": v, "lang": lang, "text": text, "parts": parts})
    # named corners for Angelo's tracks from CrewChief's corner map
    names = []
    for base in [r"C:\Program Files (x86)\Britton IT Ltd\CrewChiefV4\trackLandmarksData.json"]:
        if os.path.exists(base):
            d = json.load(open(base, encoding="utf-8-sig"))
            for t in d.get("trackLandmarksData", []):
                tn = (t.get("irTrackName") or "").lower()
                if re.search(r"spa|lemans|le_mans|sarthe|daytona|watkins|mexico|miami|monza", tn) and not re.search(r"rallycross|bike|oval|\bev\b", tn):
                    for lm in t.get("trackLandmarks", []):
                        for raw in lm.get("landmarkNames", []):
                            if re.match(r"(?i)^turn_?\d+", raw): continue
                            n = raw.replace("_", " ").strip().title()
                            n = re.sub(r"(\D)(\d+)$", r"\1 \2", n)
                            n = {"Radillion": "Raidillon", "Lesmos 1": "Lesmo 1", "Lesmos 2": "Lesmo 2"}.get(n, n)
                            n = n.replace("Nascar", "NASCAR")
                            if n in ("No Name",): continue
                            if n and n not in names: names.append(n)
    blocks = list(BLOCKS) + [("corner", slug(n), n + ".") for n in names]
    for kind, key, text in blocks:
        jid = f"blocks/{kind}/{key}"
        jobs.append({"id": jid, "text": text, "lang": "en"})
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
