"""Overnight voice prep (2026-10-24). Rebuilds the engineer job list with every number spelled out, backs up and
removes the clips that must be re-recorded, and writes the strategist's spelled-number overrides."""
import os, sys, json, re, shutil
R = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices")
T = os.path.join(R, "tools"); V = os.path.join(R, "Engineer1", "vocab")
BK = r"C:\SimRacing\Backups\voices_2026-10-24"
sys.path.insert(0, T)
os.makedirs(BK, exist_ok=True)
jp = os.path.join(V, "jobs.json")
old = {j["id"]: j["text"] for j in json.load(open(jp, encoding="utf-8"))} if os.path.exists(jp) else {}
shutil.copy2(jp, os.path.join(BK, "jobs_old.json")) if os.path.exists(jp) else None
import vocab_jobs
jobs, _ = vocab_jobs.build()
vp = os.path.join(V, "verified.json")
state = json.load(open(vp)) if os.path.exists(vp) else {}
shutil.copy2(vp, os.path.join(BK, "verified_old.json")) if os.path.exists(vp) else None
NUMK = {"num", "gap", "P", "secs", "sector", "class"}
FORCE = {"lines/faster_into/v1_1", "lines/b2_losing_time_into_a_corner/v1_2"}
redo = []
for j in jobs:
    i = j["id"]; f = os.path.join(V, i + ".wav")
    if not os.path.exists(f): continue
    p = i.split("/")
    why = None
    if old.get(i) is not None and old[i] != j["text"]: why = "text"
    elif p[0] == "blocks" and (p[1] in NUMK or (p[1] == "corner" and p[2].startswith("turn_"))): why = "number"
    elif i in FORCE: why = "poor take"
    if why:
        d = os.path.join(BK, "engineer", i + ".wav"); os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(f, d); os.remove(f); state.pop(i, None); redo.append((i, why))
json.dump(state, open(vp, "w"), indent=1)
missing = [j["id"] for j in jobs if not os.path.exists(os.path.join(V, j["id"] + ".wav"))]
print(f"engineer: {len(jobs)} clips, re-record {len(redo)}, to render now {len(missing)}")
for i, w in redo:
    if w != "number": print("  ", w, i)

# ---- strategist: spelled numbers for every clip with a digit (tools/strat_say_numbers.py)
import strat_say_numbers
strat_say_numbers.main()
