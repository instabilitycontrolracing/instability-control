"""Cut the rendered strategist clips into the pieces the app joins together.
usage: python cut_strategist.py chatterbox|f5
reads  Strategist/<engine>/raw/index.json  (from render_strategist.py)
writes Strategist/<engine>/s/<unit>/<n>.wav     sentence pieces around the numbers
       Strategist/<engine>/f/<kind>/<value>.wav  number clips ("13 laps")
       Strategist/<engine>/report.json + redo.txt (clips that didn't come out right: render again with another seed)
"""
import os, sys, json, re, difflib
import numpy as np, soundfile as sf
ROOT = os.path.join(os.path.expanduser("~"), "Documents", "CrewChiefVoices")
sys.path.insert(0, ROOT)
from engineer.strat_lines import units, EXAMPLE, CARRIER, KIND

SR = 24000
engine = sys.argv[1]
BASE = os.path.join(ROOT, "Strategist", engine)
RAW = os.path.join(BASE, "raw")
index = json.load(open(os.path.join(RAW, "index.json"), encoding="utf-8"))

from faster_whisper import WhisperModel
asr = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=4)

NUMW = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                         "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}


SAME = {"lab": "lap", "labs": "laps", "break": "brake", "tire": "tyre", "tires": "tyres", "liters": "litres",
        "liter": "litre", "alap": "a lap"}


def toks(t):
    t = t.lower().replace("%", " percent").replace("run down", "rundown").replace("to day", "today").replace("-", " ")
    raw = []
    for w in re.findall(r"[a-z0-9']+", t):
        w = SAME.get(w, w)
        raw += NUMW.get(w, w).split()
    out = []
    for w in raw:                                  # "1 20" -> "120", "p 15" -> "p15", "to stops" -> "2 stops"
        if out and w.isdigit() and out[-1].isdigit() and len(w) == 2 and len(out[-1]) == 1 and out[-1] in "12":
            out[-1] += w; continue
        if out and w.isdigit() and out[-1] == "p":
            out[-1] = "p" + w; continue
        if w in ("stops",) and out and out[-1] in ("to", "too"):
            out[-1] = "2"
        out.append(w)
    return out


def load(path):
    y, sr = sf.read(path, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        y = np.interp(np.arange(0, len(y), sr / SR), np.arange(len(y)), y).astype(np.float32)
    return y


def words(y):
    y16 = np.interp(np.arange(0, len(y), SR / 16000), np.arange(len(y)), y).astype(np.float32)
    segs, _ = asr.transcribe(y16, beam_size=5, word_timestamps=True, language="en")
    out = []
    for s in segs:
        for w in s.words or []:
            for tk in toks(w.word):
                out.append((tk, w.start, w.end))
    return out


def trim(y, thr=0.012, pad=0.04):
    a = np.abs(y)
    idx = np.flatnonzero(a > thr)
    if not len(idx):
        return y
    s, e = max(0, idx[0] - int(pad * SR)), min(len(y), idx[-1] + int(pad * SR * 2))
    return y[s:e]


def lead_trim(y, thr=0.012, pad=0.04):
    idx = np.flatnonzero(np.abs(y) > thr)
    return y[max(0, idx[0] - int(pad * SR)):] if len(idx) else y


def fade(y, ms=12):
    n = min(len(y) // 2, int(SR * ms / 1000))
    if n > 0:
        y = y.copy(); y[:n] *= np.linspace(0, 1, n); y[-n:] *= np.linspace(1, 0, n)
    return y


def span_of(expected, got, want):
    """indices in `got` covering expected[want[0]:want[1]] (via alignment) -> (i, j) or None"""
    sm = difflib.SequenceMatcher(a=expected, b=[g[0] for g in got], autojunk=False)
    m = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            m[a + k] = b + k
    if all(i in m for i in range(*want)):
        return m[want[0]], m[want[1] - 1]
    return None


def similar(a, b):
    return difflib.SequenceMatcher(a=a, b=b).ratio()


report, redo = {"units": {}, "fills": {}}, []
# ---- number clips
for name, it in index.items():
    if ":" not in name:
        continue
    kind, val = name.split(":", 1)
    y = load(os.path.join(RAW, it["file"]))
    got = words(y)
    exp = toks(CARRIER[kind].format(val))
    pre = toks(CARRIER[kind].split("{}")[0])
    want = (len(pre), len(pre) + len(toks(val)))
    sim = similar(exp, [g[0] for g in got])
    sp = span_of(exp, got, want)
    ok = sp is not None and sim > 0.75
    if ok:
        i, j = sp
        s = got[i][1] - 0.03
        prev_end = got[i - 1][2] if i > 0 else 0
        s = max(s, (prev_end + got[i][1]) / 2)
        e = got[j][2] + 0.06
        nxt = got[j + 1][1] if j + 1 < len(got) else len(y) / SR
        e = min(e, (got[j][2] + nxt) / 2 + 0.03)
        clip = fade(y[int(s * SR):int(e * SR)])
        os.makedirs(os.path.join(BASE, "f", kind), exist_ok=True)
        sf.write(os.path.join(BASE, "f", kind, val + ".wav"), clip, SR, subtype="PCM_16")
    else:
        redo.append(name)
    report["fills"][name] = {"ok": ok, "sim": round(sim, 2), "heard": " ".join(g[0] for g in got)}

# ---- sentence pieces
for key, sent in units():
    it = index.get(key)
    if not it:
        redo.append(key); continue
    y = load(os.path.join(RAW, it["file"]))
    got = words(y)
    parts = re.split(r"(\[[a-z]+\])", sent)            # text, [fill], text, ...
    exp, spans = [], []
    for p in parts:
        if p.startswith("["):
            ex = toks(EXAMPLE[p[1:-1]])
            spans.append((len(exp), len(exp) + len(ex)))
            exp += ex
        else:
            exp += toks(p)
    sim = similar(exp, [g[0] for g in got])
    ok = sim > 0.8
    cuts = []                                           # (start, end) seconds of each fill in this audio
    for sp in spans:
        r = span_of(exp, got, sp) if ok else None
        if r is None:
            ok = False; break
        i, j = r
        prev_end = got[i - 1][2] if i > 0 else 0.0
        nxt = got[j + 1][1] if j + 1 < len(got) else len(y) / SR
        cuts.append(((prev_end + got[i][1]) / 2, (got[j][2] + nxt) / 2))
    if ok:
        d = os.path.join(BASE, "s", key.replace("~", "__"))
        os.makedirs(d, exist_ok=True)
        edges = [0.0] + [c for cc in cuts for c in cc] + [len(y) / SR]
        for n in range(0, len(edges), 2):
            seg = y[int(edges[n] * SR):int(edges[n + 1] * SR)]
            if n == 0 and len(seg):
                seg = lead_trim(seg)
            if n == len(edges) - 2 and len(seg):
                seg = lead_trim(seg[::-1])[::-1]
            sf.write(os.path.join(d, f"{n // 2}.wav"), fade(seg, 6), SR, subtype="PCM_16")
    else:
        redo.append(key)
    report["units"][key] = {"ok": ok, "sim": round(sim, 2), "heard": " ".join(g[0] for g in got), "want": " ".join(exp)}

json.dump(report, open(os.path.join(BASE, "report.json"), "w", encoding="utf-8"), indent=1)
open(os.path.join(BASE, "redo.txt"), "w", encoding="utf-8").write("\n".join(redo))
nu = sum(1 for v in report["units"].values() if v["ok"]); nf = sum(1 for v in report["fills"].values() if v["ok"])
print(f"{engine}: sentences {nu}/{len(report['units'])} ok, numbers {nf}/{len(report['fills'])} ok, redo {len(redo)}")
