import os, site, sys, json, re, difflib, warnings
warnings.filterwarnings("ignore")
for _d in ["cublas", "cudnn"]:
    _p = os.path.join(site.getsitepackages()[-1], "nvidia", _d, "bin")
    if os.path.isdir(_p):
        os.add_dll_directory(_p); os.environ["PATH"] = _p + os.pathsep + os.environ["PATH"]
import soundfile as sf
from faster_whisper import WhisperModel
V = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1", "vocab")
LAST = len(sys.argv) > 1 and sys.argv[1] == "final"
jobs = json.load(open(os.path.join(V, "jobs.json"), encoding="utf-8"))
m = WhisperModel("large-v3", device="cuda", device_index=1, compute_type="float16")
W = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
W.update({"oh": "0", "tyres": "tires", "tyre": "tire"})
sys.path.insert(0, os.path.dirname(__file__))
from vocab_spec import words
def _num(m):
    a, b = m.group(1), m.group(2)
    n = int(a)
    w = words(n) if n <= 199 else " ".join(words(int(c)) for c in a)
    return w + ((" point " + " ".join(words(int(c)) for c in b)) if b else "")
def norm(s):
    s = re.sub(r"(\d+)(?:\.(\d+))?", _num, s.lower())
    s = s.replace("-", " ")
    s = re.sub(r"[^a-z0-9. ]", " ", s)
    toks = [W.get(t, t) for t in s.replace(".", " ").split()]
    return "".join(toks)
bad, checked, log = [], 0, open(os.path.join(V, "verify_log.txt"), "a", encoding="utf-8")
state = json.load(open(os.path.join(V, "verified.json"))) if os.path.exists(os.path.join(V, "verified.json")) else {}
for j in jobs:
    f = os.path.join(V, j["id"] + ".wav")
    if not os.path.exists(f) or state.get(j["id"]) == "ok": continue
    checked += 1
    y, sr = sf.read(f); dur = len(y) / sr
    letters = len(re.sub(r"[^A-Za-z0-9]", "", j["text"]))
    too_long = dur > max(0.8, letters * 0.075) * 2.5 + 1.2
    segs, _ = m.transcribe(f, language=j["lang"], beam_size=5)
    heard = " ".join(s.text.strip() for s in segs)
    r = difflib.SequenceMatcher(None, norm(j["text"]), norm(heard)).ratio()
    short = letters <= 4
    ok = (not too_long) and dur >= 0.2 and (r >= (0.5 if short else 0.75))
    if ok:
        state[j["id"]] = "ok"
    else:
        bad.append(j["id"])
        print(f"BAD {j['id']} r={r:.2f} dur={dur:.1f}s want='{j['text']}' heard='{heard}'", file=log, flush=True)
        if not LAST: os.remove(f)
        else: state[j["id"]] = "flagged"
json.dump(state, open(os.path.join(V, "verified.json"), "w"), indent=1)
print(f"checked {checked}, bad {len(bad)}", file=log, flush=True)
print(f"checked {checked}, bad {len(bad)}")
