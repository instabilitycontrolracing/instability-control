"""Track identity for the window: the track's logo (ApexHUD's logo set) and colours taken from it.

ui/assets/tracks/<Track name>.png  (copied from ApexHUD-Native\\assets\\logos\\tracks)
"""
import colorsys, os, unicodedata
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_DIR = os.path.join(HERE, "ui", "assets", "tracks")
APEX_LOGOS = os.path.join(os.path.expanduser("~"), "Documents", "iRacing", "ApexHUD-Native", "assets", "logos", "tracks")
# beta (2026-10-24): on other PCs the logos come from an installed Grandstand (if any); the owner's folder above stays first
LOGO_SOURCES = [APEX_LOGOS, os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Grandstand", "assets", "logos", "tracks")]
_CACHE = {}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.split(" - ")[0]
    return "".join(ch for ch in s if ch.isalnum())


def _sync_logos():
    """Pick up logos added to ApexHUD later."""
    try:
        for src in LOGO_SOURCES:             # beta (2026-10-24): was APEX_LOGOS only
            if not os.path.isdir(src):
                continue
            os.makedirs(LOGO_DIR, exist_ok=True)
            import shutil
            for f in os.listdir(src):
                if f.lower().endswith(".png") and not os.path.exists(os.path.join(LOGO_DIR, f)):
                    shutil.copy2(os.path.join(src, f), os.path.join(LOGO_DIR, f))
    except OSError:
        pass


def find_logo(*names):
    try:
        files = [f for f in os.listdir(LOGO_DIR) if f.lower().endswith(".png")]
    except OSError:
        return None
    keys = sorted(((norm(os.path.splitext(f)[0]), f) for f in files), key=lambda kv: -len(kv[0]))
    aliases = {"lemans": "circuitdes24heuresdumans", "24heures": "circuitdes24heuresdumans", "spa": "circuitdespafrancorchamps",
               "cota": "circuitoftheamericas", "mexico": "autodromohermanosrodriguez", "mosport": "canadiantiremotorsportspark"}
    for raw in names:
        n = norm(raw)
        if len(n) < 3:
            continue
        for cand in [n] + [t for a, t in aliases.items() if a in n]:
            for k, f in keys:
                if len(cand) >= 4 and (cand == k or cand in k or k in cand):
                    return f
    return None


def _hex(c):
    return "#%02X%02X%02X" % tuple(int(max(0, min(255, round(x)))) for x in c[:3])


def _lum(c):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _readable(c, min_lum=0.28):
    """Lighten a colour until it reads well on the navy glass."""
    c = list(c[:3])
    for _ in range(12):
        if _lum(c) >= min_lum:
            break
        c = [x + (255 - x) * 0.18 for x in c]
    return c


def theme(*names):
    """-> {logo, plate, a1, a2, dark} or None."""
    key = tuple(names)
    if key in _CACHE:
        return _CACHE[key]
    _sync_logos()
    f = find_logo(*names)
    out = None
    if f:
        try:
            from PIL import Image
            im = Image.open(os.path.join(LOGO_DIR, f)).convert("RGBA")
            im.thumbnail((220, 220))
            w, h = im.size
            px = im.load()
            # a solid plate behind the logo (Le Mans' navy)?
            border = [px[x, y] for x in range(w) for y in (0, h - 1)] + [px[x, y] for y in range(h) for x in (0, w - 1)]
            plate = None
            if sum(1 for p in border if p[3] >= 245) >= len(border) * 0.95:
                col = Counter((p[0] // 8, p[1] // 8, p[2] // 8) for p in border).most_common(1)[0][0]
                col = (col[0] * 8 + 4, col[1] * 8 + 4, col[2] * 8 + 4)
                close = sum(1 for p in border if abs(p[0] - col[0]) + abs(p[1] - col[1]) + abs(p[2] - col[2]) < 60)
                if close >= len(border) * 0.9:
                    plate = col
            bins, sums, lum_all, n_all, n_dark = Counter(), {}, 0.0, 0, 0
            for y in range(h):
                for x in range(w):
                    r, g, b, a = px[x, y]
                    if a < 200:
                        continue
                    if plate and abs(r - plate[0]) + abs(g - plate[1]) + abs(b - plate[2]) < 60:
                        continue
                    L = _lum((r, g, b)); lum_all += L; n_all += 1; n_dark += L < 0.05
                    hh, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                    if s < 0.42 or v < 0.3:
                        continue
                    k = int(hh * 24) % 24
                    bins[k] += 1
                    t = sums.setdefault(k, [0, 0, 0])
                    t[0] += r; t[1] += g; t[2] += b
            cols = []
            for k, n in bins.most_common():
                if n < max(12, n_all * 0.03):
                    break
                c = [v / n for v in sums[k]]
                hue = k * 15
                if all(min(abs(hue - h2), 360 - abs(hue - h2)) > 40 for h2, _ in cols):
                    cols.append((hue, c))
                if len(cols) == 2:
                    break
            a1 = _readable(cols[0][1]) if cols else None
            a2 = _readable(cols[1][1]) if len(cols) > 1 else None
            out = {"logo": "assets/tracks/" + f, "file": f, "plate": _hex(plate) if plate else None,
                   "a1": _hex(a1) if a1 else None, "a2": _hex(a2) if a2 else None,
                   "dark": bool(n_all and n_dark / n_all > 0.5 and not plate)}
        except Exception:
            out = {"logo": "assets/tracks/" + f, "file": f, "plate": None, "a1": None, "a2": None, "dark": False}
    _CACHE[key] = out
    return out
