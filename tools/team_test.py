import sys, time, glob, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from engineer.settings import Settings
from engineer.team import Team, build_context
from engineer.analysis import open_session, compare, lap_index, all_time_best
from engineer.mechanic import car_summary

s = Settings.load()
ev = []
t = Team(s, log=print, emit=ev.append)
t.start()
t0 = time.time()
while t.state not in ("ready", "error", "missing") and time.time() - t0 < 120:
    time.sleep(0.5)
print("state", t.state, t.reason, "after", round(time.time() - t0, 1), "s")
idx = lap_index()
cands = [(k, v) for k, v in idx.items() if v.get("best") and v.get("track") == "lemans full" and sum(1 for L in v["laps"] if L["complete"]) >= 3]
k, v = cands[0]
se = open_session(v["path"])
full = [L for L in se.laps if L["complete"]]
lap = [L for L in full if L["n"] != se.best["n"]][-1]["n"]
cmp = compare(se, lap, se, se.best["n"])
ctx = build_context(se, cmp, lap, f"your best lap this session", None, car_summary(se))
for q in sys.argv[1:] or ["Debrief this lap", "What should we change on the car?"]:
    out = []
    t1 = time.time()
    done = []
    t.ask(q, ctx, [], lambda d: out.append(d), lambda err, full="": done.append((err, full)))
    txt = "".join(out)
    print(f"\nQ: {q}\n({round(time.time() - t1, 1)} s, ~{len(txt.split())} words)\n{txt}")
t.stop()
