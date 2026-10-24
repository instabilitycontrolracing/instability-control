# Rebuild jobs with the comma rule; move clips whose text changed into _old_periods so they re-render.
import os, sys, json, shutil
sys.path.insert(0, os.path.dirname(__file__))
import vocab_jobs
V = vocab_jobs.ROOT
old = {j["id"]: j["text"] for j in json.load(open(os.path.join(V, "jobs.json"), encoding="utf-8"))}
jobs, _ = vocab_jobs.build()
ver_p = os.path.join(V, "verified.json")
ver = json.load(open(ver_p, encoding="utf-8")) if os.path.exists(ver_p) else {}
arch = os.path.join(V, "_old_periods")
moved = 0
for j in jobs:
    i = j["id"]
    if old.get(i) == j["text"]: continue
    w = os.path.join(V, i.replace("/", os.sep) + ".wav")
    if os.path.exists(w):
        dst = os.path.join(arch, i.replace("/", os.sep) + ".wav")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(w, dst); moved += 1
    ver.pop(i, None)
json.dump(ver, open(ver_p, "w", encoding="utf-8"), indent=1)
todo = sum(1 for j in jobs if not os.path.exists(os.path.join(V, j["id"].replace("/", os.sep) + ".wav")))
print(f"moved {moved} old clips to _old_periods; {todo} clips to render")
for j in jobs[:6]: print(" ", j["text"])
