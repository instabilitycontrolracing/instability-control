"""Official race schedules.

Two sources, both kept in CrewChiefVoices\\schedules\\:
- account_<season>.json : from iRacing's own schedule data (read through your iRacing login). Most detail:
  race length, start times, in-sim date/time, forecast temperature and rain chance, BoP fuel % / weight /
  power per car, start type, incident limit, fixed/open.
- <season>.pdf          : iRacing's published season schedule (backup; read with pypdf).
"""
import datetime as dt
import glob, json, os, re

from .track_theme import norm

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(os.path.dirname(HERE), "schedules")
PDF_CODES = {"BMWGTP": "bmwlmdh", "M4GT3": "bmwm4gt3"}       # PDF car codes -> car folder names (your cars)
_cache = {}


def _account():
    files = sorted(glob.glob(os.path.join(DIR, "account_*.json")), key=os.path.getmtime)
    if not files:
        return []
    f = files[-1]
    if _cache.get("acc_f") != (f, os.path.getmtime(f)):
        try:
            _cache["acc"] = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            _cache["acc"] = []
        _cache["acc_f"] = (f, os.path.getmtime(f))
    return _cache["acc"]


def _pdf():
    out = []
    for f in sorted(glob.glob(os.path.join(DIR, "*.pdf")), key=os.path.getmtime)[-1:]:
        cj = f[:-4] + "_parsed.json"
        if os.path.exists(cj) and os.path.getmtime(cj) >= os.path.getmtime(f):
            try:
                return json.load(open(cj, encoding="utf-8"))
            except ValueError:
                pass
        try:
            out = parse_pdf(f)
            json.dump(out, open(cj, "w", encoding="utf-8"))
        except Exception:
            out = []
    return out


# 2026-10-28: "\) ?" - weeks 10-12 of the IMSA series are printed with no space after the date
# ("Week 10 (2026-11-17)Silverstone Circuit - Grand Prix") and were dropped
WEEK_RE = re.compile(r"^Week (\d+) \((\d{4}-\d\d-\d\d)\) ?(.+)$")


def parse_pdf(path):
    """iRacing season PDF -> [{name, weeks: [{wk, date, track, cfg, min, laps, sim_start, temp, rain, bop}]}]"""
    import pypdf
    r = pypdf.PdfReader(path)
    series, cur, wk = [], None, None
    for p in r.pages:
        lines = [l.strip() for l in (p.extract_text() or "").splitlines() if l.strip()]
        if not lines:
            continue
        head = "Season" in lines[0] and not lines[0].startswith("Week") and "...." not in lines[0]
        if head:
            if cur is None or cur["name"] != lines[0]:
                cur = {"name": lines[0], "weeks": []}
                series.append(cur)
        if cur is None:
            continue
        # 2026-10-28: a page that carries on a series starts straight with a "Week n" line - it was skipped
        # (IMSA weeks 4 and 7 went missing that way)
        for l in (lines[1:] if head else lines):
            m = WEEK_RE.match(l)
            if m:
                tr = m.group(3)
                track, cfg = (tr.rsplit(" - ", 1) + [""])[:2] if " - " in tr else (tr, "")
                wk = {"wk": int(m.group(1)), "date": m.group(2), "track": track, "cfg": cfg, "min": None, "laps": None,
                      "sim_start": None, "temp": None, "rain": None, "bop": {}}
                cur["weeks"].append(wk)
                continue
            if wk is None:
                continue
            m = re.match(r"^\((\d{4}-\d\d-\d\d \d\d:\d\d)", l)
            if m and not wk["sim_start"]:
                wk["sim_start"] = m.group(1).replace(" ", "T") + ":00"
            m = re.search(r"/(\d+)\D*C, Rain chance (None|\d+%)", l)
            if m:
                t = float(m.group(1)); wk["temp"] = [t, t]
                wk["rain"] = 0 if m.group(2) == "None" else float(m.group(2)[:-1])
            m = re.match(r"^(\w+): fuel: (\d+)%", l)
            if m:
                wk["bop"][PDF_CODES.get(m.group(1), m.group(1))] = [int(m.group(2)), 0, 0]
            m = re.match(r"^(\d+) mins?$", l)
            if m:
                wk["min"] = int(m.group(1))
            m = re.match(r"^(\d+) laps?$", l)
            if m:
                wk["laps"] = int(m.group(1))
    return series


def series(rid=None, name=None):
    """One series' season: from your account data if we have it, else the PDF."""
    for s in _account():
        if (rid and s.get("series_id") == rid) or (name and name.lower() in s.get("name", "").lower()):
            return dict(s, source="iRacing account")
    if name:
        for s in _pdf():
            if name.lower() in s["name"].lower():
                return dict(s, source="season PDF")
    return None


def week_now(s, today=None):
    today = today or dt.date.today()
    cur = None
    for w in s.get("weeks", []):
        if dt.date.fromisoformat(w["date"][:10]) <= today:
            cur = w
    return cur


def weeks_at(s, track_display):
    n = norm(track_display)
    out = []
    for w in s.get("weeks", []):
        k = norm(w["track"])
        if k and n and (k == n or k in n or n in k):
            out.append(w)
    return out


def next_at(s, track_display, today=None):
    """The next (or current) week at this track."""
    today = today or dt.date.today()
    ws = weeks_at(s, track_display)
    for w in ws:
        end = dt.date.fromisoformat(w["date"][:10]) + dt.timedelta(days=7)
        if end > today:
            return w
    return ws[-1] if ws else None


def fuel_pct(w, car_path):
    b = (w or {}).get("bop") or {}
    v = b.get(car_path)
    return v[0] if v else None


def summary(s, car_path):
    """Compact season list for the window."""
    if not s:
        return None
    today = dt.date.today()
    cur = week_now(s, today)
    return {"name": s["name"], "source": s.get("source"), "fixed": s.get("fixed"), "inc": s.get("inc"), "current": cur["wk"] if cur else None,
            "weeks": [{"wk": w["wk"], "date": w["date"], "track": w["track"], "cfg": w.get("cfg", ""), "min": w.get("min"), "laps": w.get("laps"),
                       "times": w.get("times"), "sim": w.get("sim_start"), "temp": w.get("temp"), "rain": w.get("rain"),
                       "start": w.get("start"), "fuel": fuel_pct(w, car_path),
                       "kg": ((w.get("bop") or {}).get(car_path) or [0, 0, 0])[1]} for w in s.get("weeks", [])]}
